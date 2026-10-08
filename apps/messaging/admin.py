from django.contrib import admin

from .models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('order', 'sender', 'created_at', 'read_at')
    search_fields = ('order__number', 'sender__username', 'body')
