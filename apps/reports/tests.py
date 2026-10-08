from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.catalogue.models import Product
from apps.core.testing import make_producer, make_product, make_user
from apps.reports import services
from apps.reports.models import Report


class ReportTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', verified=True)
        self.product = make_product(self.farm, name='"Organic" crisps', category='pantry',
                                    ingredients='potatoes, oil, flavouring')
        self.reporter = make_user('aoife')
        self.staff = make_user('staff', is_staff=True)

    def test_one_open_report_per_user_and_product(self):
        services.file_report(self.product, self.reporter, 'misleading_ingredients', 'Not organic at all.')

        with self.assertRaises(services.ReportError):
            services.file_report(self.product, self.reporter, 'other', 'Again.')

    def test_cannot_report_own_product(self):
        with self.assertRaises(services.ReportError):
            services.file_report(self.product, self.farm.user, 'other', 'Hmm.')

    def test_dismiss(self):
        report = services.file_report(self.product, self.reporter, 'other', 'Hmm.')

        services.dismiss(report, self.staff)

        report.refresh_from_db()
        self.assertEqual((report.status, report.resolved_by), ('dismissed', self.staff))

    def test_unlist_archives_and_closes_all_open_reports(self):
        first = services.file_report(self.product, self.reporter, 'misleading_ingredients', 'Not organic.')
        second = services.file_report(self.product, make_user('brian'), 'not_as_described', 'Soggy.')
        mail.outbox.clear()

        services.unlist(first, self.staff)

        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.ARCHIVED)
        self.assertEqual(set(Report.objects.values_list('status', flat=True)), {'actioned'})
        self.assertEqual(mail.outbox[-1].to, ['maire@example.com'])
        second.refresh_from_db()
        self.assertIsNotNone(second.resolved_at)

    def test_report_view_requires_login_and_files(self):
        url = reverse('reports:create', args=[self.product.pk])
        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(self.reporter)
        response = self.client.post(url, {'reason': 'misleading_ingredients', 'details': 'Says organic.'})

        self.assertRedirects(response, self.product.get_absolute_url())
        self.assertEqual(Report.objects.get().reason, 'misleading_ingredients')

    def test_staff_are_told_about_new_reports(self):
        mail.outbox.clear()

        services.file_report(self.product, self.reporter, 'food_safety', 'Smelled off.')

        self.assertEqual(mail.outbox[0].to, ['staff@example.com'])
