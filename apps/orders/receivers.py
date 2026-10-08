from django.dispatch import receiver
from django.utils import timezone

from apps.core.emails import send_plain_email

from .signals import order_placed, order_status_changed


def describe(order):
    lines = '\n'.join(f'  {item.quantity} × {item.name} ({item.unit}) €{item.line_total}' for item in order.items.all())
    start = timezone.localtime(order.slot.start)
    return (f'Order {order.number}\n{lines}\nTotal €{order.total} (pay when you collect)\n\n'
            f'Collection: {start:%A %d/%m/%Y %H:%M} at {order.point.name}, {order.point.address}')


@receiver(order_placed)
def tell_both_sides(sender, order, **kwargs):
    send_plain_email(order.producer.user, f'New order {order.number}',
                     f'{order.buyer.get_username()} placed an order. Please accept or reject it soon: orders '
                     f'that are not accepted within 24 hours are cancelled automatically.\n\n{describe(order)}')
    send_plain_email(order.buyer, f'Order {order.number} placed',
                     f'Thanks for your order from {order.producer.name}. We will email you when they accept it.\n\n'
                     f'{describe(order)}')


STATUS_MESSAGES = {
    'accepted': ('accepted your order', 'Collect it at the time you chose and pay when you collect.'),
    'rejected': ('could not accept your order', 'Any stock has been put back. Reason: {reason}'),
    'ready': ('has your order ready', 'It is ready to collect at your slot.'),
    'collected': ('marked your order as collected', 'Thanks for shopping local!'),
    'no_show': ('marked your order as not collected',
                'If this is a mistake, please message them. Two missed collections in 90 days limit you to '
                'one open order at a time.'),
}


@receiver(order_status_changed)
def tell_other_party(sender, order, from_status, to_status, actor, **kwargs):
    if actor is None:
        for user in (order.buyer, order.producer.user):
            send_plain_email(user, f'Order {order.number} cancelled',
                             f'Order {order.number} was cancelled automatically because it was not accepted in '
                             f'time. Any stock has been put back.\n\n{describe(order)}')
        return
    if actor.pk == order.buyer_id:
        send_plain_email(order.producer.user, f'Order {order.number} {to_status.replace("_", " ")}',
                         f'{order.buyer.get_username()} cancelled order {order.number}. The stock has been put '
                         f'back.\n\n{describe(order)}')
        return
    verb, extra = STATUS_MESSAGES.get(to_status, ('updated your order', ''))
    send_plain_email(order.buyer, f'Order {order.number}: {order.get_status_display().lower()}',
                     f'{order.producer.name} {verb}. {extra.format(reason=order.reject_reason)}\n\n{describe(order)}')
