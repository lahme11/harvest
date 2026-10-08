"""Events sent with sender=Subscription and the subscription as `subscription`."""
from django.dispatch import Signal

subscription_started = Signal()

subscription_changed = Signal()

delivery_missed = Signal()
