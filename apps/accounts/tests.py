from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class SignupTests(TestCase):
    def test_signup_creates_user_and_logs_in(self):
        response = self.client.post(reverse('accounts:signup'), {
            'username': 'niamh', 'email': 'niamh@example.com',
            'password1': 'rolled-oats-2026', 'password2': 'rolled-oats-2026',
        })

        self.assertRedirects(response, '/')
        user = User.objects.get(username='niamh')
        self.assertEqual(user.email, 'niamh@example.com')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_signup_requires_email(self):
        response = self.client.post(reverse('accounts:signup'), {
            'username': 'niamh', 'email': '',
            'password1': 'rolled-oats-2026', 'password2': 'rolled-oats-2026',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_signup_rejects_duplicate_email(self):
        User.objects.create_user('first', 'same@example.com', 'pw-12345-long')

        self.client.post(reverse('accounts:signup'), {
            'username': 'second', 'email': 'SAME@example.com',
            'password1': 'rolled-oats-2026', 'password2': 'rolled-oats-2026',
        })

        self.assertFalse(User.objects.filter(username='second').exists())


class LoginTests(TestCase):
    def setUp(self):
        User.objects.create_user('sean', 'sean@example.com', 'farm-gate-2026')

    def test_login_redirects_to_next(self):
        response = self.client.post(f"{reverse('accounts:login')}?next=/health/", {
            'username': 'sean', 'password': 'farm-gate-2026',
        })

        self.assertRedirects(response, '/health/', fetch_redirect_response=False)

    def test_logout_is_post(self):
        self.client.login(username='sean', password='farm-gate-2026')

        response = self.client.post(reverse('accounts:logout'))

        self.assertRedirects(response, '/', fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)


class ProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('sean', 'sean@example.com', 'farm-gate-2026')

    def test_requires_login(self):
        response = self.client.get(reverse('accounts:profile'))

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('accounts:profile')}")

    def test_update_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('accounts:profile'), {
            'first_name': 'Seán', 'last_name': 'Murphy', 'email': 'sean.murphy@example.com',
        })

        self.assertRedirects(response, reverse('accounts:profile'))
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.email), ('Seán', 'sean.murphy@example.com'))

    def test_password_change(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('accounts:password'), {
            'old_password': 'farm-gate-2026', 'new_password1': 'new-harvest-2027',
            'new_password2': 'new-harvest-2027',
        })

        self.assertRedirects(response, reverse('accounts:profile'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('new-harvest-2027'))
