from django import template

from apps.catalogue import services

register = template.Library()


@register.inclusion_tag('catalogue/includes/product_grid.html')
def producer_products(producer):
    return {'products': services.live_products_for(producer)}


@register.inclusion_tag('catalogue/includes/product_grid.html')
def newest_products(limit=8):
    return {'products': services.newest_live(limit)}
