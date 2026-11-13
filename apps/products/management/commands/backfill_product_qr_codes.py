from django.core.management.base import BaseCommand, CommandError

from apps.products.models import Product
from apps.products.signals import generate_missing_qr_code


class Command(BaseCommand):
    help = "List products missing a QR asset; --apply generates them after a storage outage or upgrade."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--limit", type=int, default=1000)

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 10000:
            raise CommandError("--limit must be between 1 and 10000.")
        ids = list(Product.objects.filter(qr_code="").order_by("pk").values_list("pk", flat=True)[:options["limit"]])
        for product_id in ids:
            if options["apply"]:
                generate_missing_qr_code(product_id)
        remaining = Product.objects.filter(pk__in=ids, qr_code="").count()
        self.stdout.write(f"Selected {len(ids)} products; remaining missing {remaining}; apply={options['apply']}.")
        if options["apply"] and remaining:
            raise CommandError("Some QR assets remain missing; check private operational logs and storage.")
