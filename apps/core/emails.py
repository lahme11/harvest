"""Plain-text notification emails with a consistent greeting and footer."""
from django.conf import settings
from django.core.mail import send_mail


def send_plain_email(recipient, subject, body):
    """Email a user (or a plain address). Users without an email address are skipped."""
    if isinstance(recipient, str):
        address, name = recipient, ''
    else:
        address, name = recipient.email, recipient.first_name or recipient.get_username()
    if not address:
        return
    greeting = f'Hi {name},\n\n' if name else 'Hi,\n\n'
    footer = f'\n\n— Harvest\n{settings.SITE_URL}\n'
    send_mail(f'Harvest: {subject}', greeting + body + footer, settings.DEFAULT_FROM_EMAIL, [address])


def absolute_url(path):
    """A full link for emails, e.g. https://harvest.example/products/3/carrots/."""
    return settings.SITE_URL.rstrip('/') + path
