import datetime as dt
from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.testing import make_order, make_point, make_producer, make_product, make_slot, make_user
from apps.orders import services
from apps.orders.models import Order


class LifecycleTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.point = make_point(self.farm, cutoff_hours=12)
        self.slot = make_slot(self.point, hours_from_now=48)
        self.product = make_product(self.farm, name='Carrots', price='2.00', stock=10)
        self.buyer = make_user('aoife')
        self.stranger = make_user('stranger')
        self.order = make_order(self.buyer, self.product, quantity=3, slot=self.slot)
        self.product.stock = 7
        self.product.save()

    def act(self, user, action, **kwargs):
        return services.perform(self.order, user, action, **kwargs)

    def stock(self):
        self.product.refresh_from_db()
        return self.product.stock

    def test_happy_path(self):
        self.assertEqual(services.allowed_actions(self.order, self.farm.user), ['accept', 'reject'])
        self.assertEqual(services.allowed_actions(self.order, self.buyer), ['cancel'])
        self.assertEqual(services.allowed_actions(self.order, self.stranger), [])

        self.act(self.farm.user, 'accept')
        self.act(self.farm.user, 'mark_ready')
        self.act(self.farm.user, 'collect', payment_method='card')

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.COLLECTED)
        self.assertEqual(self.order.payment_method, 'card')
        self.assertIsNotNone(self.order.collected_at)
        self.assertEqual([e.to_status for e in self.order.events.all()], ['accepted', 'ready', 'collected'])

    def test_wrong_actor_is_refused(self):
        with self.assertRaises(services.OrderError):
            self.act(self.buyer, 'accept')
        with self.assertRaises(services.OrderError):
            self.act(self.stranger, 'cancel')

    def test_reject_needs_a_reason_and_returns_stock(self):
        with self.assertRaises(services.OrderError):
            self.act(self.farm.user, 'reject', reason=' ')

        self.act(self.farm.user, 'reject', reason='Frost got the carrots.')

        self.assertEqual(self.order.reject_reason, 'Frost got the carrots.')
        self.assertEqual(self.stock(), 10)

    def test_buyer_cancel_before_cutoff(self):
        self.slot.start = timezone.now() + timedelta(hours=13)
        self.slot.end = self.slot.start + timedelta(hours=1)
        self.slot.save()

        self.act(self.buyer, 'cancel')

        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertEqual(self.stock(), 10)

    def test_buyer_cannot_cancel_inside_cutoff(self):
        self.slot.start = timezone.now() + timedelta(hours=11)
        self.slot.end = self.slot.start + timedelta(hours=1)
        self.slot.save()

        self.assertNotIn('cancel', services.allowed_actions(self.order, self.buyer))
        with self.assertRaises(services.OrderError):
            self.act(self.buyer, 'cancel')

    def test_accept_not_allowed_after_slot_starts(self):
        later = timezone.now() + timedelta(hours=49)

        self.assertNotIn('accept', services.allowed_actions(self.order, self.farm.user, now=later))

    def test_no_show_only_after_grace(self):
        self.act(self.farm.user, 'accept')
        self.act(self.farm.user, 'mark_ready')
        slot_end = self.slot.end

        self.assertNotIn('no_show', services.allowed_actions(self.order, self.farm.user,
                                                             now=slot_end + timedelta(hours=1)))
        self.assertIn('no_show', services.allowed_actions(self.order, self.farm.user,
                                                          now=slot_end + timedelta(hours=2, minutes=1)))

    def test_no_show_keeps_stock(self):
        self.order.status = Order.Status.READY
        self.order.save()
        self.slot.start = timezone.now() - timedelta(hours=5)
        self.slot.end = timezone.now() - timedelta(hours=4)
        self.slot.save()

        self.act(self.farm.user, 'no_show')

        self.assertEqual(self.order.status, Order.Status.NO_SHOW)
        self.assertIsNotNone(self.order.no_show_at)
        self.assertEqual(self.stock(), 7)

    def test_collect_needs_a_payment_method(self):
        self.order.status = Order.Status.READY
        self.order.save()

        with self.assertRaises(services.OrderError):
            self.act(self.farm.user, 'collect', payment_method='')

    def test_transitions_email_the_other_party(self):
        mail.outbox.clear()

        self.act(self.farm.user, 'accept')
        self.assertEqual(mail.outbox[-1].to, ['aoife@example.com'])

        self.act(self.buyer, 'cancel')
        self.assertEqual(mail.outbox[-1].to, ['maire@example.com'])


class ExpiryTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.point = make_point(self.farm)
        self.product = make_product(self.farm, stock=5)
        self.buyer = make_user('aoife')

    def test_expires_after_24_hours(self):
        order = make_order(self.buyer, self.product, quantity=2, slot=make_slot(self.point, hours_from_now=72))
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(hours=25))

        self.assertEqual(services.expire_pending(), 1)

        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(self.product.stock, 7)
        event = order.events.last()
        self.assertIsNone(event.actor)
        self.assertIn('not accepted', event.note)

    def test_expires_at_slot_start_if_sooner(self):
        slot = make_slot(self.point, hours_from_now=2)
        order = make_order(self.buyer, self.product, slot=slot)

        self.assertEqual(services.expire_pending(now=timezone.now() + timedelta(hours=3)), 1)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)

    def test_recent_and_accepted_orders_are_left_alone(self):
        make_order(self.buyer, self.product, slot=make_slot(self.point, hours_from_now=72))
        make_order(self.buyer, self.product, slot=make_slot(self.point, hours_from_now=96), status='accepted')

        self.assertEqual(services.expire_pending(), 0)

    def test_command(self):
        order = make_order(self.buyer, self.product, slot=make_slot(self.point, hours_from_now=72))
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(days=2))

        call_command('expire_pending_orders', verbosity=0)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)


class NoShowPolicyTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.point = make_point(self.farm)
        self.product = make_product(self.farm, stock=50)
        self.buyer = make_user('aoife')

    def add_no_show(self, days_ago):
        order = make_order(self.buyer, self.product, slot=make_slot(self.point, hours_from_now=-24 * days_ago - 4),
                           status='no_show')
        Order.objects.filter(pk=order.pk).update(no_show_at=timezone.now() - timedelta(days=days_ago))

    def test_two_no_shows_limit_to_one_open_order(self):
        self.add_no_show(10)
        self.add_no_show(20)
        self.assertFalse(services.open_order_limit_reached(self.buyer))

        make_order(self.buyer, self.product, slot=make_slot(self.point))

        self.assertTrue(services.open_order_limit_reached(self.buyer))
        services.add_to_basket(self.buyer, self.product, 1)
        with self.assertRaises(services.OrderError):
            services.reserve(self.buyer, self.farm, make_slot(self.point, hours_from_now=60))

    def test_limit_lifts_after_ninety_days(self):
        self.add_no_show(91)
        self.add_no_show(95)
        make_order(self.buyer, self.product, slot=make_slot(self.point))

        self.assertFalse(services.open_order_limit_reached(self.buyer))

    def test_one_no_show_is_not_enough(self):
        self.add_no_show(5)
        make_order(self.buyer, self.product, slot=make_slot(self.point))

        self.assertFalse(services.open_order_limit_reached(self.buyer))


class PickListTests(TestCase):
    def test_totals_for_one_day(self):
        farm = make_producer('maire', verified=True)
        point = make_point(farm)
        carrots = make_product(farm, name='Carrots', unit='kg', stock=50)
        eggs = make_product(farm, name='Eggs', category='eggs', unit='dozen', stock=50)
        day = timezone.localdate() + timedelta(days=3)
        morning = make_slot(point, start=timezone.make_aware(dt.datetime.combine(day, dt.time(9))))
        noon = make_slot(point, start=timezone.make_aware(dt.datetime.combine(day, dt.time(12))))
        other_day = make_slot(point, start=timezone.make_aware(dt.datetime.combine(day + timedelta(days=1), dt.time(9))))
        make_order(make_user('a'), carrots, 2, slot=morning, status='accepted')
        make_order(make_user('b'), carrots, 3, slot=noon, status='ready')
        make_order(make_user('c'), eggs, 1, slot=noon, status='accepted')
        make_order(make_user('d'), carrots, 9, slot=noon, status='pending')
        make_order(make_user('e'), carrots, 9, slot=other_day, status='accepted')

        result = services.pick_list(farm, day)

        self.assertEqual(result['products'], [('Carrots', 'per kg', 5), ('Eggs', 'per dozen', 1)])
        self.assertEqual(len(result['orders']), 3)


class OrderViewTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.product = make_product(self.farm, stock=5)
        self.buyer = make_user('aoife')
        self.order = make_order(self.buyer, self.product)

    def test_other_buyers_get_404(self):
        self.client.force_login(make_user('nosy'))

        self.assertEqual(self.client.get(self.order.get_absolute_url()).status_code, 404)
        response = self.client.post(reverse('orders:act', args=[self.order.number]), {'action': 'cancel'})
        self.assertEqual(response.status_code, 404)

    def test_other_producer_cannot_act(self):
        self.client.force_login(make_producer('sean').user)

        response = self.client.post(reverse('orders:act', args=[self.order.number]), {'action': 'accept'})

        self.assertEqual(response.status_code, 404)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')

    def test_producer_accepts_through_the_view(self):
        self.client.force_login(self.farm.user)

        detail = self.client.get(self.order.get_absolute_url())
        self.assertContains(detail, 'value="accept"')
        self.client.post(reverse('orders:act', args=[self.order.number]), {'action': 'accept'})

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'accepted')

    def test_disallowed_action_shows_an_error(self):
        self.client.force_login(self.buyer)

        response = self.client.post(reverse('orders:act', args=[self.order.number]), {'action': 'collect'},
                                    follow=True)

        self.assertContains(response, 'not possible')

    def test_producer_order_list_and_pick_list(self):
        self.client.force_login(self.farm.user)

        listing = self.client.get(reverse('orders:producer_orders'))
        picks = self.client.get(reverse('orders:pick_list'), {'date': timezone.localdate().isoformat()})

        self.assertContains(listing, self.order.number)
        self.assertEqual(picks.status_code, 200)

    def test_buyer_list(self):
        self.client.force_login(self.buyer)

        self.assertContains(self.client.get(reverse('orders:mine')), self.order.number)
        self.assertEqual(Decimal(self.order.total), Decimal('2.50'))
