from django.test import TestCase
from django.urls import reverse

from apps.core.testing import make_point, make_producer, make_rule, make_user
from apps.producers.models import CollectionPoint, CollectionSlot, FarmApplication, Producer, SlotRule


class SetupViewTests(TestCase):
    def test_requires_login(self):
        response = self.client.get(reverse('producers:setup'))

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('producers:setup')}")

    def test_create_profile(self):
        user = make_user('niamh')
        self.client.force_login(user)

        response = self.client.post(reverse('producers:setup'), {
            'name': 'Niamh’s Kitchen', 'county': 'galway', 'description': 'Sourdough and jams.',
        })

        producer = Producer.objects.get(user=user)
        self.assertRedirects(response, reverse('producers:points'))
        self.assertEqual(producer.slug, 'niamhs-kitchen')

    def test_existing_producer_is_sent_to_edit(self):
        producer = make_producer('maire')
        self.client.force_login(producer.user)

        response = self.client.get(reverse('producers:setup'))

        self.assertRedirects(response, reverse('producers:edit'))

    def test_producer_pages_need_a_profile(self):
        self.client.force_login(make_user('buyer'))

        response = self.client.get(reverse('producers:points'))

        self.assertRedirects(response, reverse('producers:setup'))


class ApplyViewTests(TestCase):
    def test_apply_and_see_pending_status(self):
        producer = make_producer('maire')
        self.client.force_login(producer.user)

        self.client.post(reverse('producers:apply'), {
            'farm_name': 'Burren Hill Farm', 'registration_no': 'IE-998877', 'county': 'clare',
            'description': 'Beef and lamb.',
        })
        response = self.client.get(reverse('producers:apply'))

        self.assertEqual(FarmApplication.objects.get().status, 'pending')
        self.assertContains(response, 'waiting for review')


class PointViewTests(TestCase):
    def setUp(self):
        self.producer = make_producer('maire', verified=True)
        self.client.force_login(self.producer.user)

    def test_create_point_and_rule_generates_slots(self):
        self.client.post(reverse('producers:point_create'), {
            'name': 'Milk Market stall', 'address': 'Limerick city', 'county': 'limerick', 'cutoff_hours': 12,
            'active': 'on',
        })
        point = CollectionPoint.objects.get()

        response = self.client.post(reverse('producers:rule_create', args=[point.pk]), {
            'weekday': 5, 'start_time': '09:00', 'end_time': '12:00', 'slot_minutes': 60, 'capacity': 5,
            'active': 'on',
        })

        self.assertRedirects(response, reverse('producers:points'))
        self.assertEqual(SlotRule.objects.get().capacity, 5)
        self.assertGreaterEqual(CollectionSlot.objects.filter(point=point).count(), 3)

    def test_rule_must_end_after_it_starts(self):
        point = make_point(self.producer)

        response = self.client.post(reverse('producers:rule_create', args=[point.pk]), {
            'weekday': 5, 'start_time': '12:00', 'end_time': '09:00', 'slot_minutes': 60, 'capacity': 5,
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SlotRule.objects.exists())

    def test_other_producers_points_are_404(self):
        other_point = make_point(make_producer('sean'))

        self.assertEqual(self.client.get(reverse('producers:point_edit', args=[other_point.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('producers:point_delete', args=[other_point.pk])).status_code, 404)

    def test_delete_point(self):
        point = make_point(self.producer)
        make_rule(point)

        response = self.client.post(reverse('producers:point_delete', args=[point.pk]))

        self.assertRedirects(response, reverse('producers:points'))
        self.assertFalse(CollectionPoint.objects.exists())


class PublicPageTests(TestCase):
    def test_unverified_page_is_404(self):
        producer = make_producer('niamh', verified=False)

        self.assertEqual(self.client.get(producer.get_absolute_url()).status_code, 404)

    def test_verified_page(self):
        producer = make_producer('maire', name='Burren Hill Farm', verified=True)

        response = self.client.get(producer.get_absolute_url())

        self.assertContains(response, 'Burren Hill Farm')
        self.assertContains(response, 'Verified farm')

    def test_directory_lists_verified_farms_and_filters_by_county(self):
        make_producer('maire', name='Burren Hill Farm', county='clare', verified=True)
        make_producer('sean', name='Kerry Hills', county='kerry', verified=True)
        make_producer('niamh', name='Niamh Kitchen', county='galway', verified=False)

        response = self.client.get(reverse('producers:directory'))
        filtered = self.client.get(reverse('producers:directory'), {'county': 'kerry'})

        self.assertContains(response, 'Burren Hill Farm')
        self.assertContains(response, 'Kerry Hills')
        self.assertNotContains(response, 'Niamh Kitchen')
        self.assertNotContains(filtered, 'Burren Hill Farm')
        self.assertContains(filtered, 'Kerry Hills')
