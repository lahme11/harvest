import datetime as dt
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from apps.core.testing import local, make_point, make_producer, make_rule, make_slot, make_user
from apps.producers import services
from apps.producers.models import CollectionSlot, FarmApplication, Producer


class ProducerSetupTests(TestCase):
    def test_create_producer_with_unique_slug(self):
        first = services.create_producer(make_user('a'), name='Hillside Farm', county='cork', description='')
        second = services.create_producer(make_user('b'), name='Hillside Farm', county='kerry', description='')

        self.assertEqual(first.slug, 'hillside-farm')
        self.assertEqual(second.slug, 'hillside-farm-2')
        self.assertFalse(first.verified)

    def test_one_profile_per_user(self):
        user = make_user('a')
        services.create_producer(user, name='One', county='cork', description='')

        with self.assertRaises(services.ProducerError):
            services.create_producer(user, name='Two', county='cork', description='')

    def test_get_producer_and_is_verified(self):
        producer = make_producer('maire', verified=True)
        buyer = make_user('buyer')

        self.assertEqual(services.get_producer(producer.user), producer)
        self.assertTrue(services.is_verified(producer.user))
        self.assertIsNone(services.get_producer(buyer))
        self.assertFalse(services.is_verified(buyer))


class VerificationTests(TestCase):
    def setUp(self):
        self.producer = make_producer('maire')
        self.staff = make_user('staff', is_staff=True)

    def apply(self):
        return services.apply_for_verification(self.producer, farm_name='Máire’s Organic Farm',
                                               registration_no='IE-123456', county='clare',
                                               description='Mixed farm since 1982.')

    def test_apply_creates_pending_application_and_tells_staff(self):
        application = self.apply()

        self.assertEqual(application.status, FarmApplication.Status.PENDING)
        self.assertEqual(mail.outbox[0].to, ['staff@example.com'])
        self.assertIn('IE-123456', mail.outbox[0].body)

    def test_cannot_apply_twice_while_pending(self):
        self.apply()

        with self.assertRaises(services.ProducerError):
            self.apply()

    def test_cannot_apply_when_already_verified(self):
        self.producer.verified = True
        self.producer.save()

        with self.assertRaises(services.ProducerError):
            self.apply()

    def test_approve(self):
        application = self.apply()
        mail.outbox.clear()

        services.approve_application(application, self.staff)

        self.producer.refresh_from_db()
        application.refresh_from_db()
        self.assertTrue(self.producer.verified)
        self.assertIsNotNone(self.producer.verified_at)
        self.assertEqual(self.producer.county, 'clare')
        self.assertEqual(application.status, FarmApplication.Status.APPROVED)
        self.assertEqual(application.decided_by, self.staff)
        self.assertEqual(mail.outbox[0].to, ['maire@example.com'])
        self.assertIn('approved', mail.outbox[0].subject.lower())

    def test_reject_needs_a_reason_and_emails_it(self):
        application = self.apply()
        mail.outbox.clear()

        with self.assertRaises(services.ProducerError):
            services.reject_application(application, '  ', self.staff)

        services.reject_application(application, 'Registration number not found.', self.staff)

        self.producer.refresh_from_db()
        self.assertFalse(self.producer.verified)
        self.assertIn('Registration number not found.', mail.outbox[0].body)

    def test_can_reapply_after_rejection(self):
        services.reject_application(self.apply(), 'Missing details.', self.staff)

        self.assertEqual(self.apply().status, FarmApplication.Status.PENDING)

    def test_decided_application_cannot_be_decided_again(self):
        application = self.apply()
        services.approve_application(application, self.staff)

        with self.assertRaises(services.ProducerError):
            services.reject_application(application, 'Changed my mind.', self.staff)


class GenerateSlotsTests(TestCase):
    def setUp(self):
        self.producer = make_producer('maire', verified=True)
        self.point = make_point(self.producer)

    def test_saturday_morning_rule(self):
        make_rule(self.point, weekday=5, start='09:00', end='12:00', slot_minutes=60, capacity=4)

        created = services.generate_slots(today=dt.date(2026, 11, 2), now=local(2026, 11, 2), days=14)

        self.assertEqual(created, 6)
        starts = [timezone.localtime(slot.start) for slot in CollectionSlot.objects.order_by('start')]
        self.assertEqual([(s.day, s.hour) for s in starts], [(7, 9), (7, 10), (7, 11), (14, 9), (14, 10), (14, 11)])
        self.assertTrue(all(slot.capacity == 4 for slot in CollectionSlot.objects.all()))

    def test_is_idempotent(self):
        make_rule(self.point)
        services.generate_slots(today=dt.date(2026, 11, 2), now=local(2026, 11, 2), days=14)

        self.assertEqual(services.generate_slots(today=dt.date(2026, 11, 2), now=local(2026, 11, 2), days=14), 0)

    def test_half_hour_slots(self):
        make_rule(self.point, weekday=0, start='16:00', end='19:00', slot_minutes=30)

        self.assertEqual(services.generate_slots(today=dt.date(2026, 11, 2), now=local(2026, 11, 2), days=1), 6)

    def test_slot_that_does_not_fit_is_left_out(self):
        make_rule(self.point, weekday=0, start='16:00', end='17:30', slot_minutes=60)

        self.assertEqual(services.generate_slots(today=dt.date(2026, 11, 2), now=local(2026, 11, 2), days=1), 1)

    def test_clock_change_keeps_local_times(self):
        make_rule(self.point, weekday=6, start='10:00', end='11:00')

        services.generate_slots(today=dt.date(2026, 10, 12), now=local(2026, 10, 12), days=14)

        slots = [timezone.localtime(slot.start) for slot in CollectionSlot.objects.order_by('start')]
        self.assertEqual([(s.month, s.day, s.hour) for s in slots], [(10, 18, 10), (10, 25, 10)])
        self.assertNotEqual(slots[0].utcoffset(), slots[1].utcoffset())

    def test_past_slots_are_skipped(self):
        make_rule(self.point, weekday=0, start='09:00', end='12:00')

        created = services.generate_slots(today=dt.date(2026, 11, 2), now=local(2026, 11, 2, 10, 30), days=1)

        self.assertEqual(created, 1)

    def test_inactive_rules_and_points_are_ignored(self):
        make_rule(self.point).__class__.objects.update(active=False)
        other = make_point(self.producer, name='Market')
        make_rule(other)
        other.active = False
        other.save()

        self.assertEqual(services.generate_slots(today=dt.date(2026, 11, 2), now=local(2026, 11, 2), days=14), 0)

    def test_limited_to_one_point(self):
        make_rule(self.point)
        other = make_point(self.producer, name='Market')
        make_rule(other)

        services.generate_slots(point=other, today=dt.date(2026, 11, 2), now=local(2026, 11, 2), days=14)

        self.assertEqual(set(CollectionSlot.objects.values_list('point', flat=True)), {other.pk})


class BookableSlotTests(TestCase):
    def test_cutoff_and_inactive_points(self):
        producer = make_producer('maire', verified=True)
        point = make_point(producer, cutoff_hours=12)
        soon = make_slot(point, hours_from_now=6)
        later = make_slot(point, hours_from_now=30)
        closed = make_point(producer, name='Closed')
        closed.active = False
        closed.save()
        make_slot(closed, hours_from_now=30)

        self.assertEqual(services.bookable_slots(producer), [later])
        self.assertNotIn(soon, services.bookable_slots(producer))


class InUseCheckTests(TestCase):
    def test_registered_checks_block_deletion(self):
        point = make_point(make_producer('maire'))
        self.assertTrue(services.can_delete_point(point))

        with mock.patch.dict(services.IN_USE_CHECKS, {'point': [lambda p: p.pk == point.pk]}):
            self.assertFalse(services.can_delete_point(point))
            with self.assertRaises(services.ProducerError):
                services.delete_point(point)

        services.delete_point(point)
        self.assertFalse(point.__class__.objects.exists())

    def test_regenerate_rule_slots_keeps_slots_in_use(self):
        point = make_point(make_producer('maire'))
        rule = make_rule(point, weekday=timezone.localdate().weekday(), start='23:00', end='23:59', slot_minutes=30)
        used = make_slot(point, rule=rule, hours_from_now=72)
        spare = make_slot(point, rule=rule, hours_from_now=96)

        with mock.patch.dict(services.IN_USE_CHECKS, {'slot': [lambda s: s.pk == used.pk]}):
            services.regenerate_rule_slots(rule)

        self.assertTrue(CollectionSlot.objects.filter(pk=used.pk).exists())
        self.assertFalse(CollectionSlot.objects.filter(pk=spare.pk).exists())


class ProducerModelTests(TestCase):
    def test_str_and_url(self):
        producer = make_producer('maire', name='Burren Hill Farm', verified=True)

        self.assertEqual(str(producer), 'Burren Hill Farm')
        self.assertEqual(producer.get_absolute_url(), '/producers/burren-hill-farm/')
        self.assertEqual(Producer.objects.verified().count(), 1)
