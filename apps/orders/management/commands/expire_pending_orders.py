from django.core.management.base import BaseCommand

from apps.orders.services import expire_pending


class Command(BaseCommand):
    help = 'Cancel pending orders that were not accepted within ORDER_ACCEPT_HOURS or before their slot. Run hourly.'

    def handle(self, *args, **options):
        expired = expire_pending()
        if options['verbosity']:
            self.stdout.write(self.style.SUCCESS(f'{expired} order(s) expired.'))
