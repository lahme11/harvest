from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.orders'

    def ready(self):
        from apps.catalogue import services as catalogue
        from apps.producers import services as producers

        from . import receivers  # noqa: F401
        from . import services

        catalogue.set_hold_counter(lambda product, exclude_user=None: services.held_quantity(product, exclude_user))
        producers.register_in_use_check('point', services.point_in_use)
        producers.register_in_use_check('slot', services.slot_in_use)
        producers.register_collected_order_check(services.has_collected_order)
