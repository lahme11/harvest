from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.choices import ALLERGENS, COUNTIES, MONTHS
from apps.core.emails import send_plain_email
from apps.core.templatetags.harvest import euro, nova_badge, stars


class ChoicesTests(TestCase):
    def test_reference_lists(self):
        self.assertEqual(len(COUNTIES), 26)
        self.assertEqual(len(ALLERGENS), 14)
        self.assertEqual(len(MONTHS), 12)
        self.assertIn(('cork', 'Cork'), COUNTIES)
        self.assertIn('milk', dict(ALLERGENS))


class FilterTests(TestCase):
    def test_euro(self):
        self.assertEqual(euro(Decimal('1234.5')), '€1,234.50')
        self.assertEqual(euro(Decimal('0.4')), '€0.40')
        self.assertEqual(euro(None), '')

    def test_stars(self):
        self.assertEqual(stars(3), '★★★☆☆')
        self.assertEqual(stars(4.6), '★★★★★')
        self.assertEqual(stars(None), '')

    def test_nova_badge(self):
        html = nova_badge(4)
        self.assertIn('NOVA 4', html)
        self.assertIn('nova-4', html)
        self.assertEqual(nova_badge(None), '')


class EmailTests(TestCase):
    def test_sends_with_greeting_and_footer(self):
        user = User.objects.create_user('aoife', 'aoife@example.com', 'pw-12345-long', first_name='Aoife')

        send_plain_email(user, 'Your order', 'It is ready.')

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['aoife@example.com'])
        self.assertTrue(message.subject.startswith('Harvest: '))
        self.assertIn('Hi Aoife', message.body)
        self.assertIn('It is ready.', message.body)
        self.assertIn('http://', message.body)

    def test_skips_users_without_email(self):
        user = User.objects.create_user('noemail', '', 'pw-12345-long')

        send_plain_email(user, 'Subject', 'Body')

        self.assertEqual(mail.outbox, [])

    def test_accepts_plain_address(self):
        send_plain_email('someone@example.com', 'Subject', 'Body')

        self.assertEqual(mail.outbox[0].to, ['someone@example.com'])


class PageTests(TestCase):
    def test_health(self):
        response = self.client.get('/health/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    @override_settings(DEBUG=False)
    def test_custom_404(self):
        response = self.client.get('/no-such-page/')

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Page not found', status_code=404)

    def test_home_renders(self):
        response = self.client.get(reverse('core:home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Harvest')
