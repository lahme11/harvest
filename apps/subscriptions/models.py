from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.catalogue.models import Product
from apps.producers.models import SlotRule


class Subscription(models.Model):
    """A buyer's regular veg box: which box, and their weekly collection time (a slot rule)."""

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        PAUSED = 'paused', 'Paused'
        CANCELLED = 'cancelled', 'Cancelled'

    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscriptions')
    box = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='subscriptions')
    rule = models.ForeignKey(SlotRule, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    start_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['buyer', 'box'], condition=~Q(status='cancelled'),
                                               name='one_current_subscription_per_box')]

    def __str__(self):
        return f'{self.buyer} · {self.box} · {self.rule}'

    @property
    def is_current(self):
        return self.status != self.Status.CANCELLED


class SkippedDelivery(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='skipped')
    date = models.DateField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['subscription', 'date'], name='one_skip_per_date')]

    def __str__(self):
        return f'{self.subscription} skipped {self.date}'


class MissedDelivery(models.Model):
    """A due delivery that could not be booked because every slot that day was full."""

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='missed')
    date = models.DateField()
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['subscription', 'date'], name='one_missed_record_per_date')]

    def __str__(self):
        return f'{self.subscription} missed {self.date}'
