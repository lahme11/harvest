"""Sent with sender=Message and the new message as `message`."""
from django.dispatch import Signal

message_posted = Signal()
