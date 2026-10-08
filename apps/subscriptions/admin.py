from django.contrib import admin

from .models import MissedDelivery, SkippedDelivery, Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('buyer', 'box', 'rule', 'status', 'start_date')
    list_filter = ('status',)
    search_fields = ('buyer__username', 'box__name')


@admin.register(MissedDelivery)
class MissedDeliveryAdmin(admin.ModelAdmin):
    list_display = ('subscription', 'date', 'reason', 'created_at')


admin.site.register(SkippedDelivery)
