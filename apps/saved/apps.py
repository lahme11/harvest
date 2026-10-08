from django.apps import AppConfig


class SavedConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.saved'

    def ready(self):
        from . import receivers  # noqa: F401
