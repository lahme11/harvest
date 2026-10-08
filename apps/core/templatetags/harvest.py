from decimal import Decimal, ROUND_HALF_UP

from django import template
from django.conf import settings
from django.utils.html import format_html

register = template.Library()

NOVA_LABELS = {
    1: 'Unprocessed',
    2: 'Culinary ingredient',
    3: 'Processed',
    4: 'Ultra-processed',
}


@register.filter
def euro(value):
    """Format a price as €1,234.50."""
    if value is None or value == '':
        return ''
    amount = Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return f'{settings.CURRENCY_SYMBOL}{amount:,.2f}'


@register.filter
def stars(value):
    """Render a 1–5 rating as filled and empty stars."""
    if value is None or value == '':
        return ''
    filled = max(0, min(5, int(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))))
    return '★' * filled + '☆' * (5 - filled)


@register.filter
def nova_badge(group):
    """A coloured badge such as "NOVA 4 · Ultra-processed"."""
    if not group:
        return ''
    return format_html('<span class="badge nova nova-{}" title="NOVA group {}">NOVA {} · {}</span>',
                       group, group, group, NOVA_LABELS.get(group, ''))


@register.filter
def grade_badge(grade):
    """A badge for a clean-score grade A–E."""
    if not grade:
        return ''
    return format_html('<span class="badge grade grade-{}">{}</span>', grade.lower(), grade)


@register.filter
def nova_label(group):
    return NOVA_LABELS.get(group, '')


@register.simple_tag(takes_context=True)
def query_with(context, **changes):
    """The current query string with some parameters replaced, for pagination and sorting links."""
    params = context['request'].GET.copy()
    for key, value in changes.items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()
