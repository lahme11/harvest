from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from apps.catalogue.models import Product
from apps.orders.models import Order
from apps.producers.models import Producer
from apps.subscriptions.models import Subscription


class SeedDemoDataTests(TestCase):
    def run_seed(self, *args):
        out = StringIO()
        call_command('seed_demo_data', *args, stdout=out)
        return out.getvalue()

    def test_seed_creates_a_realistic_marketplace(self):
        output = self.run_seed()

        self.assertIn('password', output.lower())
        self.assertGreaterEqual(Producer.objects.filter(verified=True).count(), 6)
        self.assertGreaterEqual(Producer.objects.filter(verified=False).count(), 3)
        self.assertGreaterEqual(Product.objects.live().count(), 40)
        self.assertEqual(set(Product.objects.values_list('nova_group', flat=True)), {1, 2, 3, 4})
        self.assertGreaterEqual(len(set(Order.objects.values_list('status', flat=True))), 6)
        self.assertTrue(Subscription.objects.exists())
        self.assertTrue(User.objects.filter(is_superuser=True).exists())

    def test_reset_rebuilds_without_duplicates(self):
        self.run_seed()
        products = Product.objects.count()

        self.run_seed('--reset')

        self.assertEqual(Product.objects.count(), products)

    def test_running_twice_without_reset_is_refused_politely(self):
        self.run_seed()

        output = self.run_seed()

        self.assertIn('--reset', output)
