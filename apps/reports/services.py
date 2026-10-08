"""The reports app's public interface: buyers report products, staff dismiss or unlist."""
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from apps.catalogue import services as catalogue
from apps.core.emails import send_plain_email

from .models import Report


class ReportError(Exception):
    """A report that can't be filed, e.g. a second open report on the same product."""


def file_report(product, user, reason, details):
    if product.producer.user_id == user.pk:
        raise ReportError("You can't report your own product.")
    if Report.objects.filter(product=product, reporter=user, status=Report.Status.OPEN).exists():
        raise ReportError('You have already reported this product. Our team will look at it.')
    report = Report.objects.create(product=product, reporter=user, reason=reason, details=(details or '').strip())
    for staff in User.objects.filter(is_staff=True, is_active=True).exclude(email=''):
        send_plain_email(staff, f'Product reported: {product.name}',
                         f'{user.get_username()} reported {product.name} ({product.producer.name}).\n\n'
                         f'Reason: {report.get_reason_display()}\n{report.details}\n\nReview it in the admin.')
    return report


def _resolve(reports, status, staff_user):
    reports.update(status=status, resolved_at=timezone.now(), resolved_by=staff_user)


def dismiss(report, staff_user):
    _resolve(Report.objects.filter(pk=report.pk), Report.Status.DISMISSED, staff_user)


@transaction.atomic
def unlist(report, staff_user):
    """Archive the product, close every open report on it and tell the producer."""
    product = report.product
    catalogue.archive(product)
    _resolve(Report.objects.filter(product=product, status=Report.Status.OPEN), Report.Status.ACTIONED, staff_user)
    send_plain_email(product.producer.user, f'{product.name} has been unlisted',
                     f'After a report ({report.get_reason_display().lower()}), our team has unlisted '
                     f'{product.name}. Reply to this email if you think this is a mistake.')
