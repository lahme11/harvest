from django.dispatch import receiver
from django.utils import timezone

from apps.catalogue.signals import product_back_in_stock, product_price_dropped, product_published
from apps.core.emails import absolute_url, send_plain_email

from . import services


@receiver(product_price_dropped)
def price_dropped(sender, product, old_price, **kwargs):
    for user in services.savers_of(product):
        send_plain_email(user, f'Price drop: {product.name}',
                         f'{product.name} from {product.producer.name} has dropped from €{old_price} to '
                         f'€{product.price} {product.get_unit_display()}.\n\n{absolute_url(product.get_absolute_url())}')


@receiver(product_back_in_stock)
def back_in_stock(sender, product, **kwargs):
    for user in services.savers_of(product):
        send_plain_email(user, f'{product.name} is back in stock',
                         f'{product.name} from {product.producer.name} is back in stock.\n\n'
                         f'{absolute_url(product.get_absolute_url())}')


@receiver(product_published)
def new_match(sender, product, **kwargs):
    now = timezone.now()
    for search in services.matching_searches(product, now):
        send_plain_email(search.user, f'New match for "{search.name}"',
                         f'{product.name} from {product.producer.name} ({product.producer.get_county_display()}) '
                         f'matches your saved search "{search.name}".\n\n{absolute_url(product.get_absolute_url())}')
        search.last_notified_at = now
        search.save(update_fields=['last_notified_at'])
