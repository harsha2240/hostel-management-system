from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from audit.models import AuditEvent


class Command(BaseCommand):
    help = "Remove audit entries older than the retention period (minimum 366 days)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=366)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["days"] < 366:
            raise CommandError("Audit retention must be at least 366 days.")
        cutoff = timezone.now() - timedelta(days=options["days"])
        eligible = AuditEvent.objects.filter(timestamp__lt=cutoff)
        if options["dry_run"]:
            count = eligible.count()
            self.stdout.write(f"{count} audit entries eligible for removal.")
        else:
            count, _ = AuditEvent.objects.purge_before(cutoff)
            self.stdout.write(f"Removed {count} expired audit entries.")
