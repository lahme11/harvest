from django.core.management.base import BaseCommand

from apps.catalogue.services import reanalyse_all


class Command(BaseCommand):
    help = 'Re-run the ingredient analyser on every product, e.g. after editing the additive reference list.'

    def handle(self, *args, **options):
        changed = reanalyse_all()
        if options['verbosity']:
            self.stdout.write(self.style.SUCCESS(f'{changed} product(s) changed.'))
