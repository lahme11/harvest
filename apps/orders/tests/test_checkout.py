from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalogue import services as catalogue
from apps.core.testing import make_order, make_point, make_producer, make_product, make_slot, make_user
from apps.orders import services
from apps.orders.models import BasketItem, Order, StockHold
from apps.producers import services as producers


class BasketTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.buyer = make_user('aoife')
        self.carrots = make_product(self.farm, name='Carrots', price='2.00', stock=5)

    def test_add_and_increment(self):
        services.add_to_basket(self.buyer, self.carrots, 2)
        services.add_to_basket(self.buyer, self.carrots, 1)

        self.assertEqual(BasketItem.objects.get().quantity, 3)

    def test_cannot_add_more_than_available(self):
        with self.assertRaisesMessage(services.OrderError, 'Only 5'):
            services.add_to_basket(self.buyer, self.carrots, 6)

    def test_cannot_add_own_product(self):
        with self.assertRaises(services.OrderError):
            services.add_to_basket(self.farm.user, self.carrots, 1)

    def test_cannot_add_draft_box_or_sold_out(self):
        draft = make_product(self.farm, name='Draft', status='draft')
        box = make_product(self.farm, name='Veg box', kind='box', box_frequency='weekly', max_subscribers=10)
        sold_out = make_product(self.farm, name='Gone', stock=0)

        for product in (draft, box, sold_out):
            with self.subTest(product=product.name), self.assertRaises(services.OrderError):
                services.add_to_basket(self.buyer, product, 1)

    def test_update_and_remove(self):
        services.add_to_basket(self.buyer, self.carrots, 2)

        services.update_quantity(self.buyer, self.carrots, 4)
        self.assertEqual(BasketItem.objects.get().quantity, 4)

        services.update_quantity(self.buyer, self.carrots, 0)
        self.assertFalse(BasketItem.objects.exists())

    def test_groups_split_by_producer(self):
        other = make_producer('sean')
        bread = make_product(other, name='Sourdough', category='bakery', price='6.50',
                             ingredients='wheat flour, water, salt')
        services.add_to_basket(self.buyer, self.carrots, 3)
        services.add_to_basket(self.buyer, bread, 2)

        groups = services.basket_groups(self.buyer)

        self.assertEqual({group.producer for group in groups}, {self.farm, other})
        subtotals = {group.producer: group.subtotal for group in groups}
        self.assertEqual(subtotals[self.farm], Decimal('6.00'))
        self.assertEqual(subtotals[other], Decimal('13.00'))
        self.assertEqual(services.basket_count(self.buyer), 5)

    def test_unavailable_lines_are_flagged(self):
        services.add_to_basket(self.buyer, self.carrots, 2)
        catalogue.pause(self.carrots)

        line = services.basket_groups(self.buyer)[0].lines[0]

        self.assertTrue(line.problem)


class CheckoutTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.point = make_point(self.farm)
        self.slot = make_slot(self.point, hours_from_now=48, capacity=3)
        self.carrots = make_product(self.farm, name='Carrots', price='2.00', stock=4)
        self.aoife = make_user('aoife')
        self.brian = make_user('brian')

    def test_reserve_creates_holds_for_fifteen_minutes(self):
        services.add_to_basket(self.aoife, self.carrots, 3)

        holds = services.reserve(self.aoife, self.farm, self.slot)

        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0].quantity, 3)
        self.assertAlmostEqual(holds[0].expires_at, timezone.now() + timedelta(minutes=15),
                               delta=timedelta(seconds=5))
        self.assertEqual(catalogue.available_stock(self.carrots), 1)
        self.assertEqual(catalogue.available_stock(self.carrots, exclude_user=self.aoife), 4)

    def test_second_buyer_cannot_reserve_held_stock(self):
        services.add_to_basket(self.aoife, self.carrots, 4)
        services.add_to_basket(self.brian, self.carrots, 1)
        services.reserve(self.aoife, self.farm, self.slot)

        with self.assertRaisesMessage(services.OrderError, 'Carrots'):
            services.reserve(self.brian, self.farm, self.slot)

        self.assertFalse(StockHold.objects.filter(user=self.brian).exists())

    def test_expired_hold_no_longer_blocks(self):
        services.add_to_basket(self.aoife, self.carrots, 4)
        services.add_to_basket(self.brian, self.carrots, 1)
        services.reserve(self.aoife, self.farm, self.slot)
        StockHold.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        services.reserve(self.brian, self.farm, self.slot)

        self.assertEqual(services.release_expired_holds(), 1)

    def test_full_slot_cannot_be_reserved(self):
        self.slot.capacity = 1
        self.slot.save()
        make_order(self.brian, self.carrots, slot=self.slot)
        services.add_to_basket(self.aoife, self.carrots, 1)

        with self.assertRaisesMessage(services.OrderError, 'full'):
            services.reserve(self.aoife, self.farm, self.slot)

    def test_slot_inside_cutoff_cannot_be_reserved(self):
        soon = make_slot(self.point, hours_from_now=3)
        services.add_to_basket(self.aoife, self.carrots, 1)

        with self.assertRaises(services.OrderError):
            services.reserve(self.aoife, self.farm, soon)

    def test_slot_of_another_producer_cannot_be_used(self):
        other_slot = make_slot(make_point(make_producer('sean')))
        services.add_to_basket(self.aoife, self.carrots, 1)

        with self.assertRaises(services.OrderError):
            services.reserve(self.aoife, self.farm, other_slot)

    def test_confirm_places_the_order(self):
        services.add_to_basket(self.aoife, self.carrots, 3)
        services.reserve(self.aoife, self.farm, self.slot)
        mail.outbox.clear()

        order = services.confirm(self.aoife, self.farm, self.slot)

        self.carrots.refresh_from_db()
        self.assertEqual(self.carrots.stock, 1)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.number, f'HV-{timezone.localdate().year}-000001')
        self.assertEqual(order.total, Decimal('6.00'))
        item = order.items.get()
        self.assertEqual((item.name, item.unit_price, item.quantity, item.line_total),
                         ('Carrots', Decimal('2.00'), 3, Decimal('6.00')))
        self.assertFalse(BasketItem.objects.exists())
        self.assertFalse(StockHold.objects.exists())
        self.assertEqual(order.events.get().to_status, 'pending')
        self.assertEqual({tuple(m.to) for m in mail.outbox}, {('maire@example.com',), ('aoife@example.com',)})

    def test_order_numbers_count_up(self):
        first = make_order(self.brian, self.carrots, slot=self.slot)
        services.add_to_basket(self.aoife, self.carrots, 1)
        services.reserve(self.aoife, self.farm, self.slot)

        second = services.confirm(self.aoife, self.farm, self.slot)

        self.assertEqual(int(second.number[-6:]), int(first.number[-6:]) + 1)

    def test_confirm_without_reservation_fails(self):
        services.add_to_basket(self.aoife, self.carrots, 1)

        with self.assertRaisesMessage(services.OrderError, 'reserve'):
            services.confirm(self.aoife, self.farm, self.slot)

    def test_confirm_after_hold_expired_and_stock_sold_fails(self):
        services.add_to_basket(self.aoife, self.carrots, 4)
        services.reserve(self.aoife, self.farm, self.slot)
        StockHold.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        services.add_to_basket(self.brian, self.carrots, 4)
        services.reserve(self.brian, self.farm, self.slot)
        services.confirm(self.brian, self.farm, self.slot)

        with self.assertRaises(services.OrderError):
            services.confirm(self.aoife, self.farm, self.slot)

        self.carrots.refresh_from_db()
        self.assertEqual(self.carrots.stock, 0)
        self.assertEqual(Order.objects.count(), 1)

    def test_price_change_after_ordering_keeps_order_prices(self):
        services.add_to_basket(self.aoife, self.carrots, 2)
        services.reserve(self.aoife, self.farm, self.slot)
        order = services.confirm(self.aoife, self.farm, self.slot)

        catalogue.change_price(self.carrots, Decimal('3.50'))

        order.refresh_from_db()
        self.assertEqual(order.items.get().unit_price, Decimal('2.00'))
        self.assertEqual(order.total, Decimal('4.00'))

    def test_point_with_orders_cannot_be_deleted(self):
        make_order(self.aoife, self.carrots, slot=self.slot)

        self.assertFalse(producers.can_delete_point(self.point))
        with self.assertRaises(producers.ProducerError):
            producers.delete_point(self.point)

    def test_slot_with_orders_is_kept_when_rule_changes(self):
        make_order(self.aoife, self.carrots, slot=self.slot)

        self.assertTrue(producers._in_use('slot', self.slot))


class CheckoutViewTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.point = make_point(self.farm)
        self.slot = make_slot(self.point, hours_from_now=48)
        self.carrots = make_product(self.farm, name='Carrots', price='2.00', stock=4)
        self.buyer = make_user('aoife')
        self.client.force_login(self.buyer)

    def test_basket_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse('orders:basket'))

        self.assertEqual(response.status_code, 302)

    def test_add_from_product_page_and_view_basket(self):
        self.client.post(reverse('orders:add', args=[self.carrots.pk]), {'quantity': '2'})

        response = self.client.get(reverse('orders:basket'))

        self.assertContains(response, 'Carrots')
        self.assertContains(response, '€4.00')

    def test_full_checkout(self):
        services.add_to_basket(self.buyer, self.carrots, 2)

        page = self.client.get(reverse('orders:checkout', args=[self.farm.pk]))
        self.assertContains(page, timezone.localtime(self.slot.start).strftime('%H:%M'))

        response = self.client.post(reverse('orders:checkout', args=[self.farm.pk]), {'slot': self.slot.pk})
        self.assertRedirects(response, reverse('orders:confirm', args=[self.farm.pk, self.slot.pk]))

        response = self.client.post(reverse('orders:confirm', args=[self.farm.pk, self.slot.pk]))
        order = Order.objects.get()
        self.assertRedirects(response, reverse('orders:detail', args=[order.number]))

    def test_product_page_has_add_to_basket(self):
        response = self.client.get(self.carrots.get_absolute_url())

        self.assertContains(response, reverse('orders:add', args=[self.carrots.pk]))

    def test_navbar_shows_basket_count(self):
        services.add_to_basket(self.buyer, self.carrots, 3)

        response = self.client.get(reverse('catalogue:browse'))

        self.assertContains(response, 'Basket <span class="badge')
