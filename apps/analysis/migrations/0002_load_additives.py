import json
from pathlib import Path

from django.db import migrations

DATA_FILE = Path(__file__).resolve().parent.parent / 'data' / 'additives.json'


def load(apps, schema_editor):
    Additive = apps.get_model('analysis', 'Additive')
    for row in json.loads(DATA_FILE.read_text(encoding='utf-8')):
        Additive.objects.create(code=row['code'], name=row['name'], aliases=', '.join(row['aliases']),
                                kind=row['kind'], marker=row['marker'])


def unload(apps, schema_editor):
    apps.get_model('analysis', 'Additive').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [('analysis', '0001_initial')]

    operations = [migrations.RunPython(load, unload)]
