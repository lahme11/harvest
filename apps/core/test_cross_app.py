"""Behaviour that spans apps: safe redirects, multi-file photo upload and absolute links in emails."""
from decimal import Decimal

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.catalogue import services as catalogue
from apps.catalogue.forms import PhotoUploadForm
from apps.core.testing import make_order, make_producer, make_product, make_user
from apps.messaging import services as messaging
from apps.producers import services as producers
from apps.saved import services as saved


class SafeRedirectTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.product = make_product(self.farm, stock=5)
        self.buyer = make_user('aoife')
        self.client.force_login(self.buyer)

    def test_add_to_basket_ignores_outside_next(self):
        response = self.client.post(reverse('orders:add', args=[self.product.pk]),
                                    {'quantity': '1', 'next': 'https://evil.example/'})

        self.assertRedirects(response, reverse('orders:basket'))

    def test_add_to_basket_follows_local_next(self):
        response = self.client.post(reverse('orders:add', args=[self.product.pk]),
                                    {'quantity': '1', 'next': '/products/'})

        self.assertRedirects(response, '/products/')

    def test_favourite_toggle_ignores_outside_next(self):
        response = self.client.post(reverse('saved:toggle', args=[self.product.pk]), {'next': '//evil.example/x'})

        self.assertRedirects(response, self.product.get_absolute_url())

    def test_order_action_ignores_outside_next(self):
        order = make_order(self.buyer, self.product)

        response = self.client.post(reverse('orders:act', args=[order.number]),
                                    {'action': 'cancel', 'next': 'https://evil.example/'})

        self.assertRedirects(response, order.get_absolute_url())


class PhotoWidgetTests(TestCase):
    def test_photo_input_allows_several_files(self):
        html = str(PhotoUploadForm()['photos'])

        self.assertIn(' multiple', html)
        self.assertNotIn('allow_multiple_selected', html)


@override_settings(SITE_URL='https://harvest.example')
class AbsoluteEmailLinkTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.product = make_product(self.farm, price='3.00')
        self.buyer = make_user('aoife')

    def test_alert_links_are_absolute(self):
        saved.toggle_favourite(self.buyer, self.product)
        mail.outbox.clear()

        catalogue.change_price(self.product, Decimal('2.00'))

        self.assertIn(f'https://harvest.example{self.product.get_absolute_url()}', mail.outbox[0].body)

    def test_message_links_are_absolute(self):
        order = make_order(self.buyer, self.product)
        mail.outbox.clear()

        messaging.post_message(order, self.buyer, 'Hello')

        self.assertIn(f'https://harvest.example/messages/{order.number}/', mail.outbox[0].body)

    def test_farm_approval_link_is_absolute(self):
        home = make_producer('niamh')
        application = producers.apply_for_verification(home, 'Niamh Farm', 'IE-1', 'dublin', 'Hens.')
        mail.outbox.clear()

        producers.approve_application(application)

        self.assertIn(f'https://harvest.example/producers/{home.slug}/', mail.outbox[0].body)
