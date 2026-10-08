from django.dispatch import receiver
from django.urls import reverse

from apps.core.emails import absolute_url, send_plain_email

from .signals import message_posted


@receiver(message_posted)
def tell_recipient(sender, message, **kwargs):
    order = message.order
    recipient = order.producer.user if message.sender_id == order.buyer_id else order.buyer
    send_plain_email(recipient, f'New message about order {order.number}',
                     f'{message.sender.get_username()} wrote:\n\n{message.body}\n\n'
                     f'Reply: {absolute_url(reverse("messaging:thread", args=[order.number]))}')
