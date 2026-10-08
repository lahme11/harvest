"""The catalogue app's public interface and business rules.

Other apps work with products through these functions (plus the signals in signals.py) rather than by
changing Product rows themselves.
"""
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.analysis import engine
from apps.analysis.openfoodfacts import is_valid_barcode
from apps.analysis.services import analyse_text

from . import signals
from .models import WHOLE_FOOD_CATEGORIES, Product, ProductPhoto
from .photos import process_upload

HOLD_COUNTER = lambda product, exclude_user=None: 0  # noqa: E731

EDITABLE_FIELDS = ('name', 'category', 'unit', 'price', 'stock', 'description', 'ingredients', 'organic', 'barcode',
                   'kind', 'box_frequency', 'max_subscribers')


class ProductError(Exception):
    """A product change that breaks a marketplace rule, e.g. going over the home producer limit."""


def set_hold_counter(counter):
    """Let the orders app report how many units of a product other buyers are holding at checkout."""
    global HOLD_COUNTER
    HOLD_COUNTER = counter


def rule_errors(producer, data):
    """{field: message} for every marketplace rule the product data breaks."""
    errors = {}
    category = data.get('category')
    if category not in WHOLE_FOOD_CATEGORIES and not (data.get('ingredients') or '').strip() \
            and data.get('kind') != Product.Kind.BOX:
        errors['ingredients'] = 'List the ingredients exactly as they appear on the label.'
    if data.get('organic') and not producer.verified:
        errors['organic'] = 'Only verified farms can sell certified organic products.'
    if data.get('kind') == Product.Kind.BOX:
        if not producer.verified:
            errors['kind'] = 'Only verified farms can sell veg-box subscriptions.'
        if not data.get('box_frequency'):
            errors['box_frequency'] = 'Choose how often the box is collected.'
        if not data.get('max_subscribers'):
            errors['max_subscribers'] = 'Set how many subscribers you can supply.'
    barcode = (data.get('barcode') or '').strip()
    if barcode and not is_valid_barcode(barcode):
        errors['barcode'] = 'That is not a valid EAN-8 or EAN-13 barcode.'
    return errors


def refresh_analysis(product):
    """Run the ingredient analyser and store the result on the product (does not save)."""
    result = analyse_text(product.ingredients, product_name=product.name)
    product.nova_group = result.nova_group
    product.clean_score = result.clean_score
    product.grade = result.grade
    product.analysis_json = result.to_dict()


def allergen_hints(product):
    return engine.allergen_hints(product.ingredients or product.name, set(product.allergen_list))


@transaction.atomic
def save_product(producer, data, product=None):
    """Create or update a product from cleaned form data, enforcing the rules and storing the analysis."""
    errors = rule_errors(producer, data)
    if errors:
        raise ProductError(next(iter(errors.values())))
    old_price = product.price if product else None
    old_stock = product.stock if product else None
    product = product or Product(producer=producer)
    for name in EDITABLE_FIELDS:
        if name in data:
            setattr(product, name, data[name])
    product.barcode = (product.barcode or '').strip()
    if product.kind != Product.Kind.BOX:
        product.box_frequency, product.max_subscribers = '', None
    if 'allergens' in data:
        product.allergens = ','.join(data['allergens'])
    if 'season_months' in data:
        product.season_months = ','.join(str(int(month)) for month in data['season_months'])
    if 'off_nova_group' in data:
        product.off_nova_group = data['off_nova_group']
    refresh_analysis(product)
    product.save()
    _after_change(product, old_price, old_stock)
    return product


def _after_change(product, old_price, old_stock):
    if not product.is_live:
        return
    if old_price is not None and product.price < old_price:
        signals.product_price_dropped.send(sender=Product, product=product, old_price=old_price)
    if old_stock == 0 and product.stock > 0:
        signals.product_back_in_stock.send(sender=Product, product=product)


def live_count(producer):
    return Product.objects.filter(producer=producer, status=Product.Status.LIVE).count()


def limit_for(producer):
    """How many live products the producer may have; None means unlimited (verified farms)."""
    return None if producer.verified else settings.HOME_PRODUCER_PRODUCT_LIMIT


def publish(product):
    if product.is_live:
        return product
    limit = limit_for(product.producer)
    if limit is not None and live_count(product.producer) >= limit:
        raise ProductError(f'Home producers can have up to {limit} live product{"s" if limit != 1 else ""}. '
                           'Pause one first, or apply to become a verified farm.')
    product.status = Product.Status.LIVE
    product.published_at = product.published_at or timezone.now()
    product.save(update_fields=['status', 'published_at', 'updated_at'])
    signals.product_published.send(sender=Product, product=product)
    return product


def _unlist(product, status):
    was_live = product.is_live
    product.status = status
    product.save(update_fields=['status', 'updated_at'])
    if was_live:
        signals.product_unlisted.send(sender=Product, product=product)
    return product


def pause(product):
    return _unlist(product, Product.Status.PAUSED)


def archive(product):
    return _unlist(product, Product.Status.ARCHIVED)


def set_stock(product, stock):
    if stock < 0:
        raise ProductError('Stock cannot be negative.')
    old_stock = product.stock
    product.stock = stock
    product.save(update_fields=['stock', 'updated_at'])
    _after_change(product, None, old_stock)
    return product


def change_price(product, price):
    old_price = product.price
    product.price = price
    product.full_clean(validate_unique=False, exclude=[f.name for f in Product._meta.fields if f.name != 'price'])
    product.save(update_fields=['price', 'updated_at'])
    _after_change(product, old_price, None)
    return product


def decrement_stock(product, quantity):
    """Take ordered units out of stock (called inside the orders transaction)."""
    if product.stock < quantity:
        raise ProductError(f'Only {product.stock} left of {product.name}.')
    product.stock -= quantity
    product.save(update_fields=['stock', 'updated_at'])


def return_stock(product, quantity):
    """Put units back after a rejection or cancellation; may trigger a back-in-stock alert."""
    old_stock = product.stock
    product.stock += quantity
    product.save(update_fields=['stock', 'updated_at'])
    _after_change(product, None, old_stock)


def add_photos(product, files):
    existing = product.photos.count()
    if existing + len(files) > settings.MAX_PHOTOS_PER_PRODUCT:
        raise ProductError(f'A product can have up to {settings.MAX_PHOTOS_PER_PRODUCT} photos.')
    has_cover = product.photos.filter(is_cover=True).exists()
    created = []
    for offset, upload in enumerate(files):
        image, thumbnail = process_upload(upload)
        created.append(ProductPhoto.objects.create(product=product, image=image, thumbnail=thumbnail,
                                                   position=existing + offset,
                                                   is_cover=not has_cover and offset == 0))
    return created


@transaction.atomic
def set_cover(photo):
    photo.product.photos.update(is_cover=False)
    photo.is_cover = True
    photo.save(update_fields=['is_cover'])


@transaction.atomic
def delete_photo(photo):
    product = photo.product
    was_cover = photo.is_cover
    photo.delete()
    if was_cover:
        replacement = product.photos.order_by('position').first()
        if replacement:
            set_cover(replacement)


def available_stock(product, exclude_user=None):
    """Stock other buyers are not holding at checkout right now."""
    return max(0, product.stock - HOLD_COUNTER(product, exclude_user))


def get_product(pk):
    return Product.objects.select_related('producer__user').filter(pk=pk).first()


def get_live_product(pk):
    return Product.objects.live().select_related('producer__user').filter(pk=pk).first()


def products_for(producer):
    return Product.objects.filter(producer=producer).exclude(status=Product.Status.ARCHIVED).for_cards()


def live_products_for(producer):
    return Product.objects.live().filter(producer=producer).for_cards()


def is_visible_to(product, user):
    if product.is_live:
        return True
    return user.is_authenticated and (user.pk == product.producer.user_id or user.is_staff)


def record_view(product, user):
    if not user.is_authenticated or user.pk != product.producer.user_id:
        Product.objects.filter(pk=product.pk).update(view_count=F('view_count') + 1)


def reanalyse_all():
    """Re-run the analyser on every product after the reference list changes; returns how many changed."""
    changed = 0
    for product in Product.objects.all():
        before = (product.nova_group, product.clean_score, product.grade)
        refresh_analysis(product)
        if (product.nova_group, product.clean_score, product.grade) != before:
            changed += 1
        product.save(update_fields=['nova_group', 'clean_score', 'grade', 'analysis_json'])
    return changed


SORTS = {'newest': ('-published_at', '-pk'), 'score': ('-clean_score', 'name'), 'price': ('price', 'name'),
         '-price': ('-price', 'name'), 'name': ('name',)}


def search_from_params(params):
    """Validate search parameters and return (form, matching live products); invalid fields are ignored."""
    from django.db.models import Q

    from .forms import ProductSearchForm
    from .search import _season_q, search_products

    form = ProductSearchForm(params or None)
    products = Product.objects.live().for_cards()
    if not form.is_bound:
        return form, products.order_by(*SORTS['newest'])
    data = form.cleaned_or_ignored()
    products = search_products(products, data.get('q'))
    if data.get('category'):
        products = products.filter(category=data['category'])
    if data.get('county'):
        products = products.filter(producer__county=data['county'])
    if data.get('max_nova'):
        products = products.filter(nova_group__lte=data['max_nova'])
    if data.get('min_score') is not None:
        products = products.filter(clean_score__gte=data['min_score'])
    for slug in data.get('free_from') or []:
        products = products.exclude(allergens__regex=rf'(^|,){slug}(,|$)')
    if data.get('organic'):
        products = products.filter(organic=True)
    if data.get('in_season'):
        products = products.filter(Q(season_months='') | _season_q())
    if data.get('verified'):
        products = products.filter(producer__verified=True)
    if data.get('price_min') is not None:
        products = products.filter(price__gte=data['price_min'])
    if data.get('price_max') is not None:
        products = products.filter(price__lte=data['price_max'])
    return form, products.order_by(*SORTS.get(data.get('sort') or 'newest', SORTS['newest']))


def in_season_by_category(month):
    """Live products with this month among their season months, grouped as [(category label, [products])]."""
    products = (Product.objects.live().for_cards().exclude(season_months='')
                .filter(season_months__regex=rf'(^|,){month}(,|$)').order_by('category', 'name'))
    groups = {}
    for product in products:
        groups.setdefault(product.get_category_display(), []).append(product)
    return list(groups.items())


def newest_live(limit=8):
    return Product.objects.live().for_cards().order_by('-published_at')[:limit]
