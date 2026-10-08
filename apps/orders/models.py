from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.catalogue.models import Product
from apps.producers.models import CollectionPoint, CollectionSlot, Producer


class BasketItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='basket_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='+')
    quantity = models.PositiveSmallIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['added_at']
        constraints = [models.UniqueConstraint(fields=['user', 'product'], name='one_basket_line_per_product')]

    def __str__(self):
        return f'{self.quantity} × {self.product}'


class StockHold(models.Model):
    """Stock set aside for a buyer during checkout, for STOCK_HOLD_MINUTES."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stock_holds')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='holds')
    slot = models.ForeignKey(CollectionSlot, on_delete=models.CASCADE, related_name='holds')
    quantity = models.PositiveSmallIntegerField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['product', 'expires_at'])]

    def __str__(self):
        return f'{self.quantity} × {self.product} for {self.user} until {self.expires_at:%H:%M}'


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Waiting for the producer'
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'
        READY = 'ready', 'Ready to collect'
        COLLECTED = 'collected', 'Collected'
        NO_SHOW = 'no_show', 'Not collected'
        CANCELLED = 'cancelled', 'Cancelled'

    class Payment(models.TextChoices):
        CASH = 'cash', 'Cash'
        CARD = 'card', 'Card'
        OTHER = 'other', 'Other'

    OPEN = (Status.PENDING, Status.ACCEPTED, Status.READY)
    HOLDS_SLOT = (Status.PENDING, Status.ACCEPTED, Status.READY, Status.COLLECTED, Status.NO_SHOW)

    number = models.CharField(max_length=16, unique=True)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders')
    producer = models.ForeignKey(Producer, on_delete=models.PROTECT, related_name='orders')
    slot = models.ForeignKey(CollectionSlot, on_delete=models.PROTECT, related_name='orders')
    point = models.ForeignKey(CollectionPoint, on_delete=models.PROTECT, related_name='orders')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    total = models.DecimalField(max_digits=9, decimal_places=2)
    payment_method = models.CharField(max_length=8, choices=Payment.choices, blank=True)
    reject_reason = models.TextField(blank=True)
    is_box = models.BooleanField(default=False)
    subscription = models.ForeignKey('subscriptions.Subscription', null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='orders')
    delivery_date = models.DateField(null=True, blank=True, help_text='For box orders: the subscription date.')
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    collected_at = models.DateTimeField(null=True, blank=True)
    no_show_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['producer', 'status']), models.Index(fields=['buyer', 'status'])]

    def __str__(self):
        return self.number

    def get_absolute_url(self):
        return reverse('orders:detail', args=[self.number])

    @property
    def is_open(self):
        return self.status in self.OPEN


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    name = models.CharField(max_length=100)
    unit = models.CharField(max_length=30)
    unit_price = models.DecimalField(max_digits=7, decimal_places=2)
    quantity = models.PositiveSmallIntegerField()
    line_total = models.DecimalField(max_digits=9, decimal_places=2)

    def __str__(self):
        return f'{self.quantity} × {self.name}'


class OrderEvent(models.Model):
    """One step in an order's history (the audit trail)."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='+')
    from_status = models.CharField(max_length=10, blank=True)
    to_status = models.CharField(max_length=10)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']

    def __str__(self):
        return f'{self.order}: {self.from_status or "new"} → {self.to_status}'
