from django.dispatch import receiver

from apps.core.emails import send_plain_email

from .signals import delivery_missed, subscription_changed, subscription_started


@receiver(subscription_started)
def started(sender, subscription, **kwargs):
    box, rule = subscription.box, subscription.rule
    send_plain_email(subscription.buyer, f'You subscribed to {box.name}',
                     f'Your {box.get_box_frequency_display().lower()} {box.name} from {box.producer.name} will be '
                     f'ready to collect on {rule} at {rule.point.name}. €{box.price}, paid when you collect.\n\n'
                     'You can skip a week, pause or cancel any time from "My subscriptions".')
    send_plain_email(box.producer.user, f'New subscriber for {box.name}',
                     f'{subscription.buyer.get_username()} subscribed to {box.name}, collecting {rule} at '
                     f'{rule.point.name}.')


@receiver(subscription_changed)
def changed(sender, subscription, **kwargs):
    send_plain_email(subscription.box.producer.user, f'Subscription {subscription.get_status_display().lower()}',
                     f'{subscription.buyer.get_username()}\'s subscription to {subscription.box.name} is now '
                     f'{subscription.get_status_display().lower()}.')


@receiver(delivery_missed)
def missed(sender, subscription, missed, **kwargs):
    text = (f'The {subscription.box.name} due on {missed.date:%A %d/%m/%Y} could not be booked because every '
            f'collection slot at {subscription.rule.point.name} that day was full. It will not be charged.')
    send_plain_email(subscription.buyer, 'A veg-box delivery could not be booked', text)
    send_plain_email(subscription.box.producer.user, 'A veg-box delivery could not be booked',
                     f'{text}\n\nSubscriber: {subscription.buyer.get_username()}. Consider adding capacity.')
