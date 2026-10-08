"""The saved app's public interface: favourite products and saved searches with email alerts."""
from datetime import timedelta

from django.http import QueryDict
from django.utils import timezone

from apps.catalogue import services as catalogue

from .models import Favourite, SavedSearch

NOTIFY_EVERY = timedelta(hours=24)
IGNORED_PARAMS = ('page', 'csrfmiddlewaretoken')


def toggle_favourite(user, product):
    """Save or unsave a product; returns True if it is now saved."""
    deleted, _ = Favourite.objects.filter(user=user, product=product).delete()
    if deleted:
        return False
    Favourite.objects.create(user=user, product=product)
    return True


def is_favourite(user, product):
    return user.is_authenticated and Favourite.objects.filter(user=user, product=product).exists()


def favourites(user):
    return Favourite.objects.filter(user=user).select_related('product__producer')


def savers_of(product):
    return [favourite.user for favourite in
            Favourite.objects.filter(product=product).exclude(user=product.producer.user).select_related('user')]


def clean_query(query_string):
    params = QueryDict(query_string, mutable=True)
    for name in IGNORED_PARAMS:
        params.pop(name, None)
    for name in list(params):
        if all(value == '' for value in params.getlist(name)):
            params.pop(name)
    return params.urlencode()


def save_search(user, name, query_string):
    return SavedSearch.objects.create(user=user, name=(name or 'My search').strip()[:80],
                                      query_string=clean_query(query_string))


def matching_searches(product, now=None):
    """Saved searches that match a newly published product and haven't emailed in the last 24 hours."""
    now = now or timezone.now()
    matches = []
    candidates = (SavedSearch.objects.exclude(user=product.producer.user).select_related('user')
                  .exclude(last_notified_at__gt=now - NOTIFY_EVERY))
    for search in candidates:
        _, results = catalogue.search_from_params(QueryDict(search.query_string))
        if results.filter(pk=product.pk).exists():
            matches.append(search)
    return matches
