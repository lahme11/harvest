from django.core.management.base import BaseCommand

from apps.analysis.services import load_reference_file


class Command(BaseCommand):
    help = 'Load or refresh the additive reference list from apps/analysis/data/additives.json.'

    def handle(self, *args, **options):
        created, updated = load_reference_file()
        if options['verbosity']:
            self.stdout.write(self.style.SUCCESS(f'Additives: {created} created, {updated} updated.'))
