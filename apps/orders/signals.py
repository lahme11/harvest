"""Events other apps can react to. Sent with sender=Order and the order as `order`.

order_status_changed also carries `from_status`, `to_status` and `actor` (None for system changes).
"""
from django.dispatch import Signal

order_placed = Signal()

order_status_changed = Signal()
