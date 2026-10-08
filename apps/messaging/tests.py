from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.core.testing import make_order, make_producer, make_product, make_user
from apps.messaging import services
from apps.messaging.models import Message


class MessagingTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.buyer = make_user('aoife')
        self.order = make_order(self.buyer, make_product(self.farm))

    def test_both_parties_can_post_and_unread_counts(self):
        services.post_message(self.order, self.buyer, 'Can I collect at 10:15 instead?')

        self.assertEqual(services.unread_count(self.farm.user), 1)
        self.assertEqual(services.unread_count(self.buyer), 0)

        services.post_message(self.order, self.farm.user, 'No problem.')
        services.mark_read(self.order, self.farm.user)

        self.assertEqual(services.unread_count(self.farm.user), 0)
        self.assertEqual(services.unread_count(self.buyer), 1)

    def test_outsiders_cannot_post(self):
        with self.assertRaises(services.MessagingError):
            services.post_message(self.order, make_user('nosy'), 'Hello')

    def test_body_length(self):
        with self.assertRaises(services.MessagingError):
            services.post_message(self.order, self.buyer, '   ')
        with self.assertRaises(services.MessagingError):
            services.post_message(self.order, self.buyer, 'x' * 2001)

    def test_new_message_emails_the_recipient(self):
        mail.outbox.clear()

        services.post_message(self.order, self.buyer, 'Is the box ready?')

        self.assertEqual(mail.outbox[0].to, ['maire@example.com'])
        self.assertIn('Is the box ready?', mail.outbox[0].body)


class MessagingViewTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.buyer = make_user('aoife')
        self.order = make_order(self.buyer, make_product(self.farm))

    def test_thread_view_posts_and_marks_read(self):
        services.post_message(self.order, self.farm.user, 'Ready from 9.')
        self.client.force_login(self.buyer)

        response = self.client.get(reverse('messaging:thread', args=[self.order.number]))
        self.assertContains(response, 'Ready from 9.')
        self.assertEqual(services.unread_count(self.buyer), 0)

        self.client.post(reverse('messaging:thread', args=[self.order.number]), {'body': 'Thanks!'})
        self.assertEqual(Message.objects.filter(sender=self.buyer).count(), 1)

    def test_outsider_gets_404(self):
        self.client.force_login(make_user('nosy'))

        self.assertEqual(self.client.get(reverse('messaging:thread', args=[self.order.number])).status_code, 404)

    def test_inbox_and_navbar_badge(self):
        services.post_message(self.order, self.farm.user, 'Hello')
        self.client.force_login(self.buyer)

        inbox = self.client.get(reverse('messaging:inbox'))

        self.assertContains(inbox, self.order.number)
        self.assertContains(inbox, 'title="Unread messages"')
