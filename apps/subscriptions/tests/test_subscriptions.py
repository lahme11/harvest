import datetime as dt
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.testing import local, make_order, make_point, make_producer, make_product, make_rule, make_slot, make_user
from apps.orders.models import Order
from apps.orders.services import perform
from apps.producers import services as producers
from apps.producers.models import CollectionSlot
from apps.subscriptions import services
from apps.subscriptions.models import MissedDelivery, Subscription

MONDAY = dt.date(2026, 11, 2)


def slot_at(point, date, hour, capacity=4, rule=None):
    start = timezone.make_aware(dt.datetime.combine(date, dt.time(hour)))
    return CollectionSlot.objects.get_or_create(point=point, start=start, defaults={
        'end': start + timedelta(hours=1), 'capacity': capacity, 'rule': rule})[0]


class SubscriptionTestCase(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.point = make_point(self.farm, cutoff_hours=12)
        self.rule = make_rule(self.point, weekday=4, start='16:00', end='18:00', slot_minutes=60, capacity=2)
        self.box = make_product(self.farm, name='Small veg box', price='18.00', kind='box', box_frequency='weekly',
                                max_subscribers=2)
        self.buyer = make_user('aoife')


class SubscribeTests(SubscriptionTestCase):
    def test_subscribe(self):
        subscription = services.subscribe(self.buyer, self.box, self.rule)

        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)
        self.assertEqual({tuple(m.to) for m in mail.outbox}, {('aoife@example.com',), ('maire@example.com',)})

    def test_box_full(self):
        services.subscribe(make_user('a'), self.box, self.rule)
        services.subscribe(make_user('b'), self.box, self.rule)

        with self.assertRaisesMessage(services.SubscriptionError, 'full'):
            services.subscribe(self.buyer, self.box, self.rule)

    def test_cancelled_subscriptions_free_a_place(self):
        first = services.subscribe(make_user('a'), self.box, self.rule)
        services.subscribe(make_user('b'), self.box, self.rule)
        services.cancel(first)

        self.assertEqual(services.places_left(self.box), 1)
        services.subscribe(self.buyer, self.box, self.rule)

    def test_cannot_subscribe_twice_or_to_own_box_or_with_another_farms_rule(self):
        services.subscribe(self.buyer, self.box, self.rule)
        with self.assertRaises(services.SubscriptionError):
            services.subscribe(self.buyer, self.box, self.rule)
        with self.assertRaises(services.SubscriptionError):
            services.subscribe(self.farm.user, self.box, self.rule)
        other_rule = make_rule(make_point(make_producer('sean')))
        with self.assertRaises(services.SubscriptionError):
            services.subscribe(make_user('c'), self.box, other_rule)

    def test_only_boxes(self):
        carrots = make_product(self.farm, name='Carrots')

        with self.assertRaises(services.SubscriptionError):
            services.subscribe(self.buyer, carrots, self.rule)

    def test_rule_in_use_cannot_be_deleted(self):
        services.subscribe(self.buyer, self.box, self.rule)

        with self.assertRaises(producers.ProducerError):
            producers.delete_rule(self.rule)


class FirstDeliveryTests(SubscriptionTestCase):
    def test_first_delivery_is_outside_the_cutoff(self):
        with mock.patch('django.utils.timezone.now', return_value=local(2026, 11, 6, 14)):
            subscription = services.subscribe(self.buyer, self.box, self.rule)

        self.assertEqual(subscription.start_date, dt.date(2026, 11, 13))

    def test_same_day_is_fine_when_far_enough_ahead(self):
        with mock.patch('django.utils.timezone.now', return_value=local(2026, 11, 6, 2)):
            subscription = services.subscribe(self.buyer, self.box, self.rule)

        self.assertEqual(subscription.start_date, dt.date(2026, 11, 6))

    def test_passed_delivery_is_not_recorded_as_missed(self):
        subscription = services.subscribe(self.buyer, self.box, self.rule)
        subscription.start_date = dt.date(2026, 11, 6)
        subscription.save()

        result = services.generate_box_orders(now=local(2026, 11, 6, 19))

        self.assertEqual(result['missed'], 0)
        self.assertFalse(MissedDelivery.objects.exists())


class DueDateTests(SubscriptionTestCase):
    def test_weekly(self):
        subscription = services.subscribe(self.buyer, self.box, self.rule)
        subscription.start_date = MONDAY
        subscription.save()

        dates = services.due_dates(subscription, MONDAY, MONDAY + timedelta(days=20))

        self.assertEqual(dates, [dt.date(2026, 11, 6), dt.date(2026, 11, 13), dt.date(2026, 11, 20)])

    def test_fortnightly(self):
        self.box.box_frequency = 'fortnightly'
        self.box.save()
        subscription = services.subscribe(self.buyer, self.box, self.rule)
        subscription.start_date = MONDAY
        subscription.save()

        dates = services.due_dates(subscription, MONDAY + timedelta(days=5), MONDAY + timedelta(days=40))

        self.assertEqual(dates, [dt.date(2026, 11, 20), dt.date(2026, 12, 4)])


class GenerateTests(SubscriptionTestCase):
    def setUp(self):
        super().setUp()
        self.now = local(2026, 11, 2, 9)
        self.friday = dt.date(2026, 11, 6)
        self.subscription = services.subscribe(self.buyer, self.box, self.rule)
        self.subscription.start_date = MONDAY
        self.subscription.save()
        mail.outbox.clear()

    def generate(self):
        return services.generate_box_orders(now=self.now)

    def test_creates_one_order_per_due_date_in_the_next_week(self):
        result = self.generate()

        self.assertEqual(result['created'], 1)
        order = Order.objects.get()
        self.assertTrue(order.is_box)
        self.assertEqual(order.subscription, self.subscription)
        self.assertEqual(order.delivery_date, self.friday)
        self.assertEqual(timezone.localtime(order.slot.start).hour, 16)
        self.assertEqual(order.total, self.box.price)
        self.assertEqual(order.items.get().name, 'Small veg box')

    def test_is_idempotent(self):
        self.generate()

        self.assertEqual(self.generate()['created'], 0)
        self.assertEqual(Order.objects.count(), 1)

    def test_skipped_delivery(self):
        with mock.patch('django.utils.timezone.now', return_value=self.now):
            services.skip(self.subscription, self.friday)

        result = self.generate()

        self.assertEqual((result['created'], result['skipped']), (0, 1))

    def test_cannot_skip_after_cutoff_or_a_date_that_is_not_due(self):
        with mock.patch('django.utils.timezone.now', return_value=local(2026, 11, 6, 6)):
            with self.assertRaises(services.SubscriptionError):
                services.skip(self.subscription, self.friday)
        with mock.patch('django.utils.timezone.now', return_value=self.now):
            with self.assertRaises(services.SubscriptionError):
                services.skip(self.subscription, dt.date(2026, 11, 5))

    def test_skipping_cancels_an_order_already_created(self):
        self.generate()

        with mock.patch('django.utils.timezone.now', return_value=self.now):
            services.skip(self.subscription, self.friday)

        self.assertEqual(Order.objects.get().status, Order.Status.CANCELLED)

    def test_paused_generates_nothing(self):
        services.pause(self.subscription)

        self.assertEqual(self.generate()['created'], 0)

        services.resume(self.subscription)
        self.assertEqual(self.generate()['created'], 1)

    def test_full_slot_falls_back_to_the_next_slot_that_day(self):
        full = slot_at(self.point, self.friday, 16, capacity=1, rule=self.rule)
        slot_at(self.point, self.friday, 17, rule=self.rule)
        carrots = make_product(self.farm, name='Carrots')
        make_order(make_user('other'), carrots, slot=full)

        self.generate()

        order = Order.objects.get(is_box=True)
        self.assertEqual(timezone.localtime(order.slot.start).hour, 17)

    def test_no_room_records_a_missed_delivery_and_emails_both(self):
        carrots = make_product(self.farm, name='Carrots')
        for hour in (16, 17):
            slot = slot_at(self.point, self.friday, hour, capacity=1, rule=self.rule)
            make_order(make_user(f'other{hour}'), carrots, slot=slot)
        mail.outbox.clear()

        result = self.generate()

        self.assertEqual((result['created'], result['missed']), (0, 1))
        self.assertEqual(MissedDelivery.objects.get().date, self.friday)
        self.assertEqual({tuple(m.to) for m in mail.outbox}, {('aoife@example.com',), ('maire@example.com',)})
        self.assertEqual(self.generate()['missed'], 0)

    def test_box_orders_follow_the_normal_lifecycle(self):
        self.generate()
        order = Order.objects.get()

        perform(order, self.farm.user, 'accept')

        self.assertEqual(order.status, Order.Status.ACCEPTED)

    def test_command(self):
        with mock.patch('django.utils.timezone.now', return_value=self.now):
            call_command('generate_box_orders', verbosity=0)

        self.assertEqual(Order.objects.count(), 1)


class SubscriptionViewTests(SubscriptionTestCase):
    def test_subscribe_from_the_box_page(self):
        self.client.force_login(self.buyer)

        page = self.client.get(self.box.get_absolute_url())
        self.assertContains(page, 'Subscribe')
        response = self.client.post(reverse('subscriptions:subscribe', args=[self.box.pk]), {'rule': self.rule.pk})

        self.assertRedirects(response, reverse('subscriptions:mine'))
        self.assertTrue(Subscription.objects.filter(buyer=self.buyer).exists())

    def test_my_subscriptions_and_controls(self):
        subscription = services.subscribe(self.buyer, self.box, self.rule)
        self.client.force_login(self.buyer)

        self.assertContains(self.client.get(reverse('subscriptions:mine')), 'Small veg box')
        self.client.post(reverse('subscriptions:pause', args=[subscription.pk]))
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, 'paused')

    def test_other_users_cannot_control_a_subscription(self):
        subscription = services.subscribe(self.buyer, self.box, self.rule)
        self.client.force_login(make_user('nosy'))

        response = self.client.post(reverse('subscriptions:cancel', args=[subscription.pk]))

        self.assertEqual(response.status_code, 404)

    def test_producer_sees_subscribers(self):
        services.subscribe(self.buyer, self.box, self.rule)
        self.client.force_login(self.farm.user)

        self.assertContains(self.client.get(reverse('subscriptions:producer')), 'aoife')
