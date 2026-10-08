"""Free-text product search: every word must match something about the product."""
import shlex

from django.db.models import Q
from django.utils import timezone

from apps.core.choices import COUNTIES

from .models import Product

CATEGORY_WORDS = {}
for value, label in Product.Category.choices:
    CATEGORY_WORDS[value] = value
    CATEGORY_WORDS[label.lower()] = value
CATEGORY_WORDS.update({'veg': 'vegetables', 'vegetable': 'vegetables', 'egg': 'eggs', 'bread': 'bakery',
                       'drink': 'drinks', 'cheese': 'dairy', 'milk': 'dairy'})

COUNTY_WORDS = {label.lower(): slug for slug, label in COUNTIES}
SEASON_WORDS = {'season', 'seasonal', 'in-season'}


def _words(text):
    try:
        return [word.lower() for word in shlex.split(text) if word.strip()]
    except ValueError:
        return [word.lower() for word in text.split() if word.strip()]


def _season_q():
    month = timezone.localdate().month
    return Q(season_months__regex=rf'(^|,){month}(,|$)')


def word_q(word):
    """Everything a single search word may match."""
    q = (Q(name__icontains=word) | Q(producer__name__icontains=word) | Q(ingredients__icontains=word))
    if word in CATEGORY_WORDS:
        q |= Q(category=CATEGORY_WORDS[word])
    if word in COUNTY_WORDS:
        q |= Q(producer__county=COUNTY_WORDS[word])
    if word == 'organic':
        q = Q(organic=True)
    if word in SEASON_WORDS:
        q |= _season_q()
    return q


def search_products(queryset, text):
    for word in _words(text or ''):
        queryset = queryset.filter(word_q(word))
    return queryset
