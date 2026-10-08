from django.contrib.auth.models import User
from django.dispatch import receiver
from django.urls import reverse

from apps.core.emails import absolute_url, send_plain_email

from .signals import farm_application_decided, farm_application_submitted


@receiver(farm_application_submitted)
def tell_staff(sender, application, **kwargs):
    for staff in User.objects.filter(is_staff=True, is_active=True).exclude(email=''):
        send_plain_email(staff, f'New farm application: {application.farm_name}',
                         f'{application.producer.user.get_username()} applied to become a verified farm.\n\n'
                         f'Farm: {application.farm_name}\nRegistration or herd number: {application.registration_no}\n'
                         f'County: {application.get_county_display()}\n\nReview it in the admin.')


@receiver(farm_application_decided)
def tell_applicant(sender, application, **kwargs):
    user = application.producer.user
    if application.status == application.Status.APPROVED:
        send_plain_email(user, 'Your farm application was approved',
                         f'Good news: {application.farm_name} has been approved as a verified farm.\n\n'
                         'You can now list unlimited products, sell veg-box subscriptions and receive reviews.\n'
                         f'Your public page: {absolute_url(reverse("producers:detail", args=[application.producer.slug]))}')
    else:
        send_plain_email(user, 'Your farm application',
                         f'Unfortunately we could not approve {application.farm_name} yet.\n\n'
                         f'Reason: {application.reason}\n\nYou are welcome to apply again with the details updated.')
