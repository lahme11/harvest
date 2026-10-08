from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalogue import services as catalogue
from apps.core.testing import make_producer, make_product, make_user
from apps.saved import services
from apps.saved.models import SavedSearch


class FavouriteTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.product = make_product(self.farm, name='Rhubarb', price='3.00', stock=0)
        self.saver = make_user('aoife')
        services.toggle_favourite(self.saver, self.product)
        mail.outbox.clear()

    def test_toggle(self):
        self.assertTrue(services.is_favourite(self.saver, self.product))

        services.toggle_favourite(self.saver, self.product)

        self.assertFalse(services.is_favourite(self.saver, self.product))

    def test_price_drop_emails_savers(self):
        catalogue.change_price(self.product, Decimal('2.50'))

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['aoife@example.com'])
        self.assertIn('€3.00', mail.outbox[0].body)
        self.assertIn('€2.50', mail.outbox[0].body)

    def test_price_rise_does_not(self):
        catalogue.change_price(self.product, Decimal('3.50'))

        self.assertEqual(mail.outbox, [])

    def test_back_in_stock_emails_savers(self):
        catalogue.set_stock(self.product, 4)

        self.assertIn('back in stock', mail.outbox[0].subject)

    def test_favourites_view_and_toggle_view(self):
        self.client.force_login(self.saver)

        self.assertContains(self.client.get(reverse('saved:favourites')), 'Rhubarb')
        self.client.post(reverse('saved:toggle', args=[self.product.pk]))
        self.assertFalse(services.is_favourite(self.saver, self.product))


class SavedSearchTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', county='cork', verified=True)
        self.searcher = make_user('aoife')
        self.search = services.save_search(self.searcher, 'Cork eggs', 'q=eggs&county=cork&page=3')
        mail.outbox.clear()

    def publish(self, **kwargs):
        product = make_product(self.farm, status='draft', **kwargs)
        catalogue.publish(product)
        return product

    def test_page_is_dropped_from_the_query(self):
        self.assertEqual(self.search.query_string, 'q=eggs&county=cork')

    def test_matching_product_emails_once_a_day(self):
        self.publish(name='Free-range eggs', category='eggs')
        self.publish(name='Duck eggs', category='eggs')

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Free-range eggs', mail.outbox[0].body)

        SavedSearch.objects.update(last_notified_at=timezone.now() - timedelta(hours=25))
        self.publish(name='Goose eggs', category='eggs')
        self.assertEqual(len(mail.outbox), 2)

    def test_non_matching_product_does_not_email(self):
        self.publish(name='Carrots')

        self.assertEqual(mail.outbox, [])

    def test_own_products_do_not_email(self):
        services.save_search(self.farm.user, 'Mine', 'q=eggs')

        self.publish(name='Eggs', category='eggs')

        self.assertEqual([m.to for m in mail.outbox], [['aoife@example.com']])

    def test_views(self):
        self.client.force_login(self.searcher)

        self.client.post(reverse('saved:save_search'), {'name': 'Organic', 'query_string': 'organic=on'})
        listing = self.client.get(reverse('saved:searches'))
        self.assertContains(listing, 'Organic')
        self.client.post(reverse('saved:delete_search', args=[self.search.pk]))
        self.assertFalse(SavedSearch.objects.filter(pk=self.search.pk).exists())

    def test_cannot_delete_someone_elses_search(self):
        self.client.force_login(make_user('nosy'))

        response = self.client.post(reverse('saved:delete_search', args=[self.search.pk]))

        self.assertEqual(response.status_code, 404)
