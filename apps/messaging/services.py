"""The messaging app's public interface: one conversation per order between buyer and producer."""
from django.db.models import Max, Q
from django.utils import timezone

from apps.orders.models import Order

from . import signals
from .models import Message

MAX_LENGTH = 2000


class MessagingError(Exception):
    """A message that can't be sent, e.g. from someone outside the order."""


def participants(order):
    return {order.buyer_id, order.producer.user_id}


def post_message(order, user, body):
    if user.pk not in participants(order):
        raise MessagingError('Only the buyer and the producer can message about an order.')
    body = (body or '').strip()
    if not body:
        raise MessagingError('Write a message first.')
    if len(body) > MAX_LENGTH:
        raise MessagingError(f'Messages can be up to {MAX_LENGTH} characters.')
    message = Message.objects.create(order=order, sender=user, body=body)
    signals.message_posted.send(sender=Message, message=message)
    return message


def _involving(user):
    return Q(order__buyer=user) | Q(order__producer__user=user)


def unread_count(user):
    if not user.is_authenticated:
        return 0
    return Message.objects.filter(_involving(user), read_at__isnull=True).exclude(sender=user).count()


def mark_read(order, user):
    order.messages.filter(read_at__isnull=True).exclude(sender=user).update(read_at=timezone.now())


def inbox(user):
    """Orders the user has messages about, newest conversation first, with unread counts."""
    orders = (Order.objects.filter(Q(buyer=user) | Q(producer__user=user), messages__isnull=False)
              .annotate(last_message_at=Max('messages__created_at')).select_related('producer', 'buyer')
              .order_by('-last_message_at').distinct())
    unread = {}
    for order_id in (Message.objects.filter(_involving(user), read_at__isnull=True).exclude(sender=user)
                     .values_list('order_id', flat=True)):
        unread[order_id] = unread.get(order_id, 0) + 1
    return [(order, unread.get(order.pk, 0)) for order in orders]
