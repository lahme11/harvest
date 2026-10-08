from django.core.management.base import BaseCommand

from apps.subscriptions.services import generate_box_orders


class Command(BaseCommand):
    help = 'Create veg-box orders for deliveries due in the next 7 days. Idempotent; run daily.'

    def handle(self, *args, **options):
        result = generate_box_orders()
        if options['verbosity']:
            self.stdout.write(self.style.SUCCESS(
                f"{result['created']} box order(s) created, {result['skipped']} skipped, {result['missed']} missed."))
