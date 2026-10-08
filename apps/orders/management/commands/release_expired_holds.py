from django.core.management.base import BaseCommand

from apps.orders.services import release_expired_holds


class Command(BaseCommand):
    help = 'Delete checkout stock holds that have expired. Safe to run often.'

    def handle(self, *args, **options):
        deleted = release_expired_holds()
        if options['verbosity']:
            self.stdout.write(self.style.SUCCESS(f'{deleted} expired hold(s) released.'))
