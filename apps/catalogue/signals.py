"""Events other apps can react to without the catalogue knowing about them.

Each signal is sent with sender=Product and the product as `product`; price drops also carry `old_price`.
"""
from django.dispatch import Signal

product_published = Signal()

product_price_dropped = Signal()

product_back_in_stock = Signal()

product_unlisted = Signal()
