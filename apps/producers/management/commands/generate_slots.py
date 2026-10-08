from django.core.management.base import BaseCommand

from apps.producers.services import generate_slots


class Command(BaseCommand):
    help = 'Create collection slots for the next SLOT_DAYS_AHEAD days from every active slot rule. Run daily.'

    def handle(self, *args, **options):
        created = generate_slots()
        if options['verbosity']:
            self.stdout.write(self.style.SUCCESS(f'{created} new collection slot(s).'))
