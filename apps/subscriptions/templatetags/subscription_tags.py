from django import template

from apps.subscriptions import services

register = template.Library()


@register.simple_tag
def places_left(box):
    return services.places_left(box)
