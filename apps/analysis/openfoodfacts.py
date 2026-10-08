"""Look up packaged products by barcode in Open Food Facts, to pre-fill a product's ingredients.

Harvest's own analyser still decides the NOVA group; Open Food Facts only saves the seller some typing.
Responses (including "not found") are cached for BARCODE_CACHE_DAYS. Network problems return None.
"""
import json
from dataclasses import dataclass
from datetime import timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from .models import BarcodeLookup

FIELDS = 'product_name,ingredients_text_en,ingredients_text,allergens_tags,nova_group'
USER_AGENT = 'Harvest/1.0 (portfolio project)'
TIMEOUT_SECONDS = 5

ALLERGEN_TAGS = {
    'en:celery': 'celery', 'en:gluten': 'cereals_gluten', 'en:crustaceans': 'crustaceans', 'en:eggs': 'eggs',
    'en:fish': 'fish', 'en:lupin': 'lupin', 'en:milk': 'milk', 'en:molluscs': 'molluscs', 'en:mustard': 'mustard',
    'en:nuts': 'nuts', 'en:peanuts': 'peanuts', 'en:sesame-seeds': 'sesame', 'en:soybeans': 'soybeans',
    'en:sulphur-dioxide-and-sulphites': 'sulphites',
}


class InvalidBarcode(ValueError):
    """The code is not a valid EAN-8 or EAN-13 barcode."""


@dataclass
class OffProduct:
    barcode: str
    name: str
    ingredients: str
    allergens: list
    nova_group: int | None


def clean_barcode(code):
    return ''.join((code or '').split())


def is_valid_barcode(code):
    """True for an EAN-8 or EAN-13 code with a correct check digit."""
    code = clean_barcode(code)
    if not code.isdigit() or len(code) not in (8, 13):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    weights = (3, 1) if len(code) == 8 else (1, 3)
    total = sum(d * weights[i % 2] for i, d in enumerate(body))
    return (10 - total % 10) % 10 == check


def _product_from(code, data):
    allergens = []
    for tag in data.get('allergens_tags') or []:
        slug = ALLERGEN_TAGS.get(tag)
        if slug and slug not in allergens:
            allergens.append(slug)
    nova = data.get('nova_group')
    return OffProduct(
        barcode=code,
        name=(data.get('product_name') or '').strip(),
        ingredients=(data.get('ingredients_text_en') or data.get('ingredients_text') or '').strip(),
        allergens=allergens,
        nova_group=int(nova) if nova in (1, 2, 3, 4, '1', '2', '3', '4') else None,
    )


def _fetch(code):
    """Return (found, product_data); raises on network problems."""
    url = settings.OFF_API_URL.format(code=code) + '?' + urlencode({'fields': FIELDS})
    request = Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
            payload = json.load(reply)
    except HTTPError as error:
        if error.code == 404:
            return False, {}
        raise
    if payload.get('status') == 1 and payload.get('product'):
        return True, payload['product']
    return False, {}


def lookup(code):
    """The Open Food Facts product for a barcode, or None if it isn't known or the service can't be reached."""
    code = clean_barcode(code)
    if not is_valid_barcode(code):
        raise InvalidBarcode(code)
    cutoff = timezone.now() - timedelta(days=settings.BARCODE_CACHE_DAYS)
    cached = BarcodeLookup.objects.filter(barcode=code, fetched_at__gte=cutoff).first()
    if cached is None:
        try:
            found, data = _fetch(code)
        except (OSError, ValueError):
            return None
        cached, _ = BarcodeLookup.objects.update_or_create(
            barcode=code, defaults={'found': found, 'data': data, 'fetched_at': timezone.now()})
    return _product_from(code, cached.data) if cached.found else None
