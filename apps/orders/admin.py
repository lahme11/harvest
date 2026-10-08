from django.contrib import admin

from .models import BasketItem, Order, OrderEvent, OrderItem, StockHold


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'name', 'unit', 'unit_price', 'quantity', 'line_total')
    can_delete = False


class OrderEventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    readonly_fields = ('actor', 'from_status', 'to_status', 'note', 'created_at')
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('number', 'buyer', 'producer', 'status', 'total', 'slot', 'created_at')
    list_filter = ('status', 'is_box', 'producer')
    search_fields = ('number', 'buyer__username', 'producer__name')
    readonly_fields = ('number', 'buyer', 'producer', 'slot', 'point', 'total', 'created_at', 'accepted_at',
                       'ready_at', 'collected_at', 'no_show_at', 'closed_at')
    inlines = [OrderItemInline, OrderEventInline]


@admin.register(StockHold)
class StockHoldAdmin(admin.ModelAdmin):
    list_display = ('product', 'user', 'quantity', 'slot', 'expires_at')


@admin.register(BasketItem)
class BasketItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'quantity', 'added_at')
