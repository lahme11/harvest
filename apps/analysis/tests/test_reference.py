import json
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from apps.analysis import engine, services
from apps.analysis.models import Additive

DATA = Path(engine.__file__).resolve().parent / 'data' / 'additives.json'


class ReferenceDataTests(TestCase):
    def test_file_is_well_formed(self):
        entries = json.loads(DATA.read_text())

        self.assertGreaterEqual(len(entries), 250)
        codes = [entry['code'] for entry in entries if entry['code']]
        self.assertEqual(len(codes), len(set(codes)))
        kinds = {choice for choice, _ in Additive.Kind.choices}
        for entry in entries:
            with self.subTest(entry=entry['name']):
                self.assertIn(entry['kind'], kinds)
                self.assertIsInstance(entry['marker'], bool)
                self.assertIsInstance(entry['aliases'], list)
                if entry['code']:
                    self.assertEqual(engine.normalise_e_number(entry['code']), entry['code'])

    def test_marker_kinds_follow_the_spec(self):
        for entry in json.loads(DATA.read_text()):
            if entry['kind'] in ('preservative', 'antioxidant', 'acidity_regulator', 'raising_agent', 'anti_caking'):
                with self.subTest(entry=entry['name']):
                    self.assertFalse(entry['marker'])

    def test_migration_loaded_the_reference_list(self):
        self.assertGreaterEqual(Additive.objects.count(), 250)
        self.assertTrue(Additive.objects.get(code='E471').marker)
        self.assertFalse(Additive.objects.get(code='E250').marker)


class LoadCommandTests(TestCase):
    def test_load_additives_is_idempotent(self):
        before = Additive.objects.count()

        call_command('load_additives', verbosity=0)
        call_command('load_additives', verbosity=0)

        self.assertEqual(Additive.objects.count(), before)

    def test_load_additives_restores_edited_entries(self):
        Additive.objects.filter(code='E471').update(name='edited')

        call_command('load_additives', verbosity=0)

        self.assertEqual(Additive.objects.get(code='E471').name, 'Mono- and diglycerides of fatty acids')


class ServiceTests(TestCase):
    def test_analyse_text_uses_the_database(self):
        self.assertEqual(services.analyse_text('oats, E300').nova_group, 3)

        Additive.objects.filter(code='E300').update(marker=True)
        Additive.objects.get(code='E300').save()

        self.assertEqual(services.analyse_text('oats, E300').nova_group, 4)

    def test_reference_cache_clears_when_an_additive_is_added(self):
        services.analyse_text('oats')

        Additive.objects.create(name='Mystery thickener', aliases='mystery gum', kind='thickener', marker=True)

        self.assertEqual(services.analyse_text('oats, mystery gum').nova_group, 4)
