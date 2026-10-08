import io
import json
from datetime import timedelta
from unittest import mock
from urllib.error import HTTPError, URLError

from django.test import TestCase
from django.utils import timezone

from apps.analysis import openfoodfacts
from apps.analysis.models import BarcodeLookup

CODE = '5000159484695'

FOUND = {
    'status': 1,
    'product': {
        'product_name': 'Chocolate bar',
        'ingredients_text': 'Sucre, beurre de cacao',
        'ingredients_text_en': 'Sugar, cocoa butter, skimmed milk powder, emulsifier (E442)',
        'allergens_tags': ['en:milk', 'en:soybeans', 'en:gluten', 'en:something-else'],
        'nova_group': 4,
    },
}


def response(payload):
    return io.BytesIO(json.dumps(payload).encode())


class BarcodeValidationTests(TestCase):
    def test_check_digits(self):
        self.assertTrue(openfoodfacts.is_valid_barcode('5000159484695'))
        self.assertFalse(openfoodfacts.is_valid_barcode('5000159484696'))
        self.assertTrue(openfoodfacts.is_valid_barcode('96385074'))
        self.assertFalse(openfoodfacts.is_valid_barcode('96385075'))
        self.assertFalse(openfoodfacts.is_valid_barcode('12345'))
        self.assertFalse(openfoodfacts.is_valid_barcode('abcdefghijklm'))

    def test_invalid_code_raises(self):
        with self.assertRaises(openfoodfacts.InvalidBarcode):
            openfoodfacts.lookup('5000159484696')

    def test_spaces_are_ignored(self):
        self.assertTrue(openfoodfacts.is_valid_barcode(' 5000159 484695 '))


@mock.patch('apps.analysis.openfoodfacts.urlopen')
class LookupTests(TestCase):
    def test_found_product(self, urlopen):
        urlopen.return_value = response(FOUND)

        product = openfoodfacts.lookup(CODE)

        self.assertEqual(product.barcode, CODE)
        self.assertEqual(product.name, 'Chocolate bar')
        self.assertEqual(product.ingredients, 'Sugar, cocoa butter, skimmed milk powder, emulsifier (E442)')
        self.assertEqual(product.allergens, ['milk', 'soybeans', 'cereals_gluten'])
        self.assertEqual(product.nova_group, 4)
        self.assertTrue(BarcodeLookup.objects.get(barcode=CODE).found)

    def test_request_headers_and_timeout(self, urlopen):
        urlopen.return_value = response(FOUND)

        openfoodfacts.lookup(CODE)

        request = urlopen.call_args.args[0]
        self.assertIn(f'/product/{CODE}.json', request.full_url)
        self.assertIn('fields=', request.full_url)
        self.assertEqual(request.get_header('User-agent'), 'Harvest/1.0 (portfolio project)')
        self.assertEqual(urlopen.call_args.kwargs['timeout'], 5)

    def test_second_lookup_uses_the_cache(self, urlopen):
        urlopen.return_value = response(FOUND)

        openfoodfacts.lookup(CODE)
        product = openfoodfacts.lookup(CODE)

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(product.name, 'Chocolate bar')

    def test_not_found_is_cached(self, urlopen):
        urlopen.return_value = response({'status': 0, 'status_verbose': 'product not found'})

        self.assertIsNone(openfoodfacts.lookup(CODE))
        self.assertIsNone(openfoodfacts.lookup(CODE))

        self.assertEqual(urlopen.call_count, 1)
        self.assertFalse(BarcodeLookup.objects.get(barcode=CODE).found)

    def test_http_404_counts_as_not_found(self, urlopen):
        urlopen.side_effect = HTTPError('url', 404, 'Not Found', {}, None)

        self.assertIsNone(openfoodfacts.lookup(CODE))

        self.assertFalse(BarcodeLookup.objects.get(barcode=CODE).found)

    def test_stale_cache_is_refetched(self, urlopen):
        urlopen.return_value = response(FOUND)
        openfoodfacts.lookup(CODE)
        BarcodeLookup.objects.update(fetched_at=timezone.now() - timedelta(days=31))
        urlopen.return_value = response(FOUND)

        openfoodfacts.lookup(CODE)

        self.assertEqual(urlopen.call_count, 2)

    def test_network_errors_return_none_and_are_not_cached(self, urlopen):
        for error in (URLError('down'), TimeoutError(), HTTPError('url', 503, 'Unavailable', {}, None),
                      ValueError('bad json')):
            with self.subTest(error=error):
                urlopen.side_effect = error

                self.assertIsNone(openfoodfacts.lookup(CODE))

        self.assertFalse(BarcodeLookup.objects.exists())

    def test_falls_back_to_generic_ingredients(self, urlopen):
        payload = json.loads(json.dumps(FOUND))
        del payload['product']['ingredients_text_en']
        urlopen.return_value = response(payload)

        self.assertEqual(openfoodfacts.lookup(CODE).ingredients, 'Sucre, beurre de cacao')

    def test_missing_nova_group(self, urlopen):
        payload = json.loads(json.dumps(FOUND))
        del payload['product']['nova_group']
        urlopen.return_value = response(payload)

        self.assertIsNone(openfoodfacts.lookup(CODE).nova_group)
