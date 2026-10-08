from django.conf import settings
from django.db import models

from apps.catalogue.models import Product


class Report(models.Model):
    class Reason(models.TextChoices):
        MISLEADING_INGREDIENTS = 'misleading_ingredients', 'Ingredients or claims look wrong'
        NOT_AS_DESCRIBED = 'not_as_described', 'Not as described'
        FOOD_SAFETY = 'food_safety', 'Food safety concern'
        PROHIBITED_ITEM = 'prohibited_item', 'Not allowed on Harvest'
        OTHER = 'other', 'Something else'

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        DISMISSED = 'dismissed', 'Dismissed'
        ACTIONED = 'actioned', 'Product unlisted'

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reports')
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reports')
    reason = models.CharField(max_length=30, choices=Reason.choices)
    details = models.TextField(max_length=2000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+')

    class Meta:
        ordering = ['status', '-created_at']

    def __str__(self):
        return f'{self.product}: {self.get_reason_display()}'
