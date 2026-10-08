from django.conf import settings
from django.db import models

from apps.orders.models import Order


class Message(models.Model):
    """A message between the buyer and the producer about one order."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages')
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at', 'pk']

    def __str__(self):
        return f'{self.sender} on {self.order}'
