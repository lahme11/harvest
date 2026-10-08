"""The analysis app's public interface: analyse ingredient text against the reference list in the database."""
import json

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from . import engine
from .models import Additive

_reference = None


def get_reference():
    """The reference list as an engine.Reference, built once and rebuilt after any Additive change."""
    global _reference
    if _reference is None:
        _reference = engine.Reference.from_entries([additive.as_entry() for additive in Additive.objects.all()])
    return _reference


def clear_reference_cache():
    global _reference
    _reference = None


@receiver([post_save, post_delete], sender=Additive)
def _additive_changed(sender, **kwargs):
    clear_reference_cache()


def analyse_text(text, product_name=''):
    return engine.analyse(text, get_reference(), product_name=product_name)


def load_reference_file():
    """Create or update every Additive from the bundled JSON file; returns (created, updated)."""
    created = updated = 0
    for row in json.loads(engine.DATA_FILE.read_text(encoding='utf-8')):
        lookup = {'code': row['code']} if row['code'] else {'code': None, 'name': row['name']}
        _, was_created = Additive.objects.update_or_create(
            **lookup,
            defaults={'name': row['name'], 'aliases': ', '.join(row['aliases']), 'kind': row['kind'],
                      'marker': row['marker']},
        )
        created += was_created
        updated += not was_created
    clear_reference_cache()
    return created, updated
