from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.subscriptions'

    def ready(self):
        from apps.producers import services as producers

        from . import receivers  # noqa: F401
        from . import services

        producers.register_in_use_check('rule', services.rule_in_use)
        producers.register_in_use_check('point', services.point_in_use)
