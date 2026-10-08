from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.analysis.models import Additive
from apps.analysis.openfoodfacts import OffProduct
from apps.catalogue import services, signals
from apps.catalogue.models import Product
from apps.core.testing import make_producer, make_product, make_user


def product_data(**overrides):
    data = {
        'name': 'Sourdough loaf', 'category': 'bakery', 'unit': 'each', 'price': '6.50', 'stock': '12',
        'description': 'Long-fermented, baked on Saturday mornings.',
        'ingredients': 'organic wheat flour, water, sea salt', 'allergens': ['cereals_gluten'],
        'season_months': [], 'organic': '', 'barcode': '', 'kind': 'standard', 'box_frequency': '',
        'max_subscribers': '',
    }
    data.update(overrides)
    return data


class SaveProductTests(TestCase):
    def setUp(self):
        self.home = make_producer('niamh', verified=False)
        self.farm = make_producer('maire', verified=True)

    def clean(self, **overrides):
        data = product_data(**overrides)
        data['price'] = Decimal(data['price'])
        data['stock'] = int(data['stock'])
        data['organic'] = bool(data['organic'])
        data['max_subscribers'] = int(data['max_subscribers']) if data['max_subscribers'] else None
        return data

    def test_stores_the_analysis(self):
        product = services.save_product(self.home, self.clean())

        self.assertEqual(product.nova_group, 3)
        self.assertEqual(product.grade, 'A')
        self.assertIn('Contains added salt', product.analysis_json['reasons'])
        self.assertEqual(product.status, Product.Status.DRAFT)

    def test_marker_label_is_nova_4(self):
        product = services.save_product(self.home, self.clean(ingredients='oat flour, glucose-fructose syrup, E471'))

        self.assertEqual(product.nova_group, 4)

    def test_editing_ingredients_reanalyses(self):
        product = services.save_product(self.home, self.clean())

        services.save_product(self.home, self.clean(ingredients='wheat flour, E471'), product=product)

        product.refresh_from_db()
        self.assertEqual(product.nova_group, 4)

    def test_whole_food_categories_need_no_ingredients(self):
        product = services.save_product(self.home, self.clean(name='Carrots', category='vegetables', ingredients=''))

        self.assertEqual((product.nova_group, product.grade), (1, 'A'))

    def test_other_categories_need_ingredients(self):
        with self.assertRaises(services.ProductError):
            services.save_product(self.home, self.clean(ingredients='  '))

    def test_organic_is_for_verified_farms(self):
        with self.assertRaises(services.ProductError):
            services.save_product(self.home, self.clean(organic=True))

        self.assertTrue(services.save_product(self.farm, self.clean(organic=True)).organic)

    def test_boxes_are_for_verified_farms_and_need_details(self):
        box = self.clean(name='Veg box', category='vegetables', ingredients='', kind='box', box_frequency='weekly',
                         max_subscribers='20')
        with self.assertRaises(services.ProductError):
            services.save_product(self.home, box)
        with self.assertRaises(services.ProductError):
            services.save_product(self.farm, {**box, 'box_frequency': ''})

        product = services.save_product(self.farm, box)

        self.assertEqual((product.kind, product.max_subscribers), ('box', 20))

    def test_invalid_barcode_is_rejected(self):
        with self.assertRaises(services.ProductError):
            services.save_product(self.home, self.clean(barcode='5000159484696'))


class PublishTests(TestCase):
    def setUp(self):
        self.home = make_producer('niamh', verified=False)

    @override_settings(HOME_PRODUCER_PRODUCT_LIMIT=8)
    def test_home_producer_limit(self):
        for i in range(8):
            make_product(self.home, name=f'Jar {i}')
        ninth = make_product(self.home, name='Jar 9', status='draft')

        with self.assertRaises(services.ProductError):
            services.publish(ninth)

    def test_verified_farms_have_no_limit(self):
        farm = make_producer('maire', verified=True)
        for i in range(8):
            make_product(farm, name=f'Veg {i}')
        ninth = make_product(farm, name='Veg 9', status='draft')

        services.publish(ninth)

        self.assertEqual(ninth.status, Product.Status.LIVE)

    def test_publish_sends_the_signal_once(self):
        product = make_product(self.home, status='draft')
        receiver = mock.Mock()
        signals.product_published.connect(receiver)
        self.addCleanup(signals.product_published.disconnect, receiver)

        services.publish(product)
        services.publish(product)

        self.assertEqual(receiver.call_count, 1)
        self.assertIsNotNone(product.published_at)

    def test_pause_and_archive_send_unlisted(self):
        product = make_product(self.home)
        receiver = mock.Mock()
        signals.product_unlisted.connect(receiver)
        self.addCleanup(signals.product_unlisted.disconnect, receiver)

        services.pause(product)
        services.archive(product)
        self.assertEqual(product.status, Product.Status.ARCHIVED)
        self.assertEqual(receiver.call_count, 1)

        live = make_product(self.home, name='Second')
        services.archive(live)
        self.assertEqual(receiver.call_count, 2)


class PriceAndStockSignalTests(TestCase):
    def setUp(self):
        self.product = make_product(make_producer('niamh'), price='5.00', stock=0)
        self.dropped = mock.Mock()
        self.back = mock.Mock()
        signals.product_price_dropped.connect(self.dropped)
        signals.product_back_in_stock.connect(self.back)
        self.addCleanup(signals.product_price_dropped.disconnect, self.dropped)
        self.addCleanup(signals.product_back_in_stock.disconnect, self.back)

    def test_price_drop_sends_signal(self):
        services.change_price(self.product, Decimal('4.00'))

        self.dropped.assert_called_once()
        self.assertEqual(self.dropped.call_args.kwargs['old_price'], Decimal('5.00'))

    def test_price_rise_does_not(self):
        services.change_price(self.product, Decimal('6.00'))

        self.dropped.assert_not_called()

    def test_back_in_stock(self):
        services.set_stock(self.product, 5)
        services.set_stock(self.product, 7)

        self.back.assert_called_once()

    def test_not_back_in_stock_while_paused(self):
        self.product.status = Product.Status.PAUSED
        self.product.save()

        services.set_stock(self.product, 5)

        self.back.assert_not_called()

    def test_negative_stock_is_refused(self):
        with self.assertRaises(services.ProductError):
            services.set_stock(self.product, -1)


class ReanalyseTests(TestCase):
    def test_reanalyse_after_reference_change(self):
        product = make_product(make_producer('niamh'), name='Granola', category='pantry', ingredients='oats, E300')
        self.assertEqual(product.nova_group, 3)
        Additive.objects.get(code='E300').__class__.objects.filter(code='E300').update(marker=True)
        Additive.objects.get(code='E300').save()

        changed = services.reanalyse_all()

        product.refresh_from_db()
        self.assertEqual(changed, 1)
        self.assertEqual(product.nova_group, 4)


class SellViewTests(TestCase):
    def setUp(self):
        self.producer = make_producer('niamh')
        self.client.force_login(self.producer.user)

    def test_create_product(self):
        response = self.client.post(reverse('catalogue:create'), product_data())

        product = Product.objects.get()
        self.assertRedirects(response, reverse('catalogue:photos', args=[product.pk]))
        self.assertEqual(product.producer, self.producer)
        self.assertEqual(product.allergen_list, ['cereals_gluten'])

    def test_form_shows_rule_errors(self):
        response = self.client.post(reverse('catalogue:create'), product_data(ingredients=''))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'List the ingredients')
        self.assertFalse(Product.objects.exists())

    def test_create_needs_a_producer_profile(self):
        self.client.force_login(make_user('buyer'))

        response = self.client.get(reverse('catalogue:create'))

        self.assertRedirects(response, reverse('producers:setup'))

    def test_cannot_edit_someone_elses_product(self):
        other = make_product(make_producer('sean'))

        self.assertEqual(self.client.get(reverse('catalogue:edit', args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('catalogue:publish', args=[other.pk])).status_code, 404)

    def test_publish_and_quick_actions(self):
        product = make_product(self.producer, status='draft', stock=0)

        self.client.post(reverse('catalogue:publish', args=[product.pk]))
        self.client.post(reverse('catalogue:stock', args=[product.pk]), {'stock': '9'})
        self.client.post(reverse('catalogue:price', args=[product.pk]), {'price': '3.10'})

        product.refresh_from_db()
        self.assertEqual((product.status, product.stock, product.price), ('live', 9, Decimal('3.10')))

    def test_publish_over_limit_shows_message(self):
        with override_settings(HOME_PRODUCER_PRODUCT_LIMIT=1):
            make_product(self.producer, name='One')
            draft = make_product(self.producer, name='Two', status='draft')

            response = self.client.post(reverse('catalogue:publish', args=[draft.pk]), follow=True)

        self.assertContains(response, 'up to 1 live product')

    def test_my_products_lists_own_products(self):
        make_product(self.producer, name='Rhubarb jam', category='pantry', ingredients='rhubarb, sugar')
        make_product(make_producer('sean'), name='Not mine')

        response = self.client.get(reverse('catalogue:mine'))

        self.assertContains(response, 'Rhubarb jam')
        self.assertNotContains(response, 'Not mine')


@mock.patch('apps.catalogue.views.openfoodfacts.lookup')
class BarcodeViewTests(TestCase):
    def setUp(self):
        self.client.force_login(make_producer('niamh').user)

    def test_found(self, lookup):
        lookup.return_value = OffProduct(barcode='5000159484695', name='Oat biscuits', ingredients='oats, sugar',
                                         allergens=['cereals_gluten'], nova_group=3)

        data = self.client.get(reverse('catalogue:barcode'), {'code': '5000159484695'}).json()

        self.assertEqual(data, {'found': True, 'name': 'Oat biscuits', 'ingredients': 'oats, sugar',
                                'allergens': ['cereals_gluten'], 'nova_group': 3})

    def test_not_found(self, lookup):
        lookup.return_value = None

        self.assertEqual(self.client.get(reverse('catalogue:barcode'), {'code': '5000159484695'}).json(),
                         {'found': False})

    def test_invalid_code(self, lookup):
        from apps.analysis.openfoodfacts import InvalidBarcode
        lookup.side_effect = InvalidBarcode('x')

        response = self.client.get(reverse('catalogue:barcode'), {'code': '123'})

        self.assertEqual(response.status_code, 400)

    def test_needs_producer(self, lookup):
        self.client.force_login(make_user('buyer'))

        response = self.client.get(reverse('catalogue:barcode'), {'code': '5000159484695'})

        self.assertEqual(response.status_code, 302)
        lookup.assert_not_called()
