from django.conf import settings


def site(request):
    """Values every template may need."""
    return {'currency_symbol': settings.CURRENCY_SYMBOL}
