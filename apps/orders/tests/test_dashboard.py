from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.testing import make_order, make_point, make_producer, make_product, make_slot, make_user
from apps.orders import services
from apps.orders.models import Order


class DashboardTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.point = make_point(self.farm)
        self.carrots = make_product(self.farm, name='Carrots', price='2.00', stock=50)
        self.eggs = make_product(self.farm, name='Eggs', category='eggs', price='4.00', stock=2)
        make_product(self.farm, name='Paused low', stock=1, status='paused')

    def test_counts_and_sales(self):
        buyer = make_user('aoife')
        make_order(buyer, self.carrots, 1, status='pending')
        make_order(buyer, self.carrots, 1, status='pending')
        make_order(buyer, self.carrots, 1, status='accepted')
        recent = make_order(buyer, self.carrots, 3, status='collected')
        Order.objects.filter(pk=recent.pk).update(collected_at=timezone.now() - timedelta(days=2))
        eggs = make_order(buyer, self.eggs, 1, status='collected')
        Order.objects.filter(pk=eggs.pk).update(collected_at=timezone.now() - timedelta(days=5))
        old = make_order(buyer, self.carrots, 10, status='collected')
        Order.objects.filter(pk=old.pk).update(collected_at=timezone.now() - timedelta(days=40))
        make_order(buyer, self.carrots, 5, status='cancelled')

        data = services.dashboard(self.farm)

        self.assertEqual(data['open_orders'], {'pending': 2, 'accepted': 1, 'ready': 0})
        self.assertEqual(data['sales_30_days'], Decimal('10.00'))
        self.assertEqual(data['top_products'], [('Carrots', 3), ('Eggs', 1)])
        self.assertEqual([p.name for p in data['low_stock']], ['Eggs'])

    def test_slots_next_seven_days(self):
        soon = make_slot(self.point, hours_from_now=30)
        make_slot(self.point, hours_from_now=24 * 9)
        make_order(make_user('aoife'), self.carrots, slot=soon)

        data = services.dashboard(self.farm)

        self.assertEqual(data['slots_next_7_days'], [(soon, 1)])

    def test_view_requires_a_producer(self):
        self.client.force_login(make_user('buyer'))
        self.assertRedirects(self.client.get(reverse('orders:dashboard')), reverse('producers:setup'))

        self.client.force_login(self.farm.user)
        response = self.client.get(reverse('orders:dashboard'))
        self.assertContains(response, 'Low stock')
        self.assertContains(response, 'Eggs')
