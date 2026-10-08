"""Events other apps can react to. Each is sent with sender=FarmApplication and the application as `application`."""
from django.dispatch import Signal

farm_application_submitted = Signal()

farm_application_decided = Signal()
