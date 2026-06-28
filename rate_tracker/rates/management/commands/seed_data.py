"""
Management command: seed_data

Loads rate data from a Snappy-compressed Parquet file into the database.

Usage:
    python manage.py seed_data
    python manage.py seed_data --file /path/to/rates_seed.parquet
    python manage.py seed_data --batch-size 5000
    python manage.py seed_data --dry-run

This command is idempotent: running it multiple times produces identical DB state.
Duplicate rows are caught by the unique constraint and silently skipped.
"""
import os
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from rates.services.ingestion import run_seed_ingestion


class Command(BaseCommand):
    help = 'Load rate data from Parquet seed file into the database (idempotent)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='rates_seed.parquet',
            help='Path to the .parquet file (default: rates_seed.parquet in working dir)',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=10_000,
            help='Number of rows per bulk INSERT batch (default: 10000)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate and clean data without writing to the database',
        )

    def handle(self, *args, **options):
        file_path = options['file']
        batch_size = options['batch_size']
        dry_run = options['dry_run']

        # Resolve path — look relative to CWD and BASE_DIR
        resolved = Path(file_path)
        if not resolved.exists():
            # Try relative to project base
            base_candidates = [
                Path(os.getcwd()) / file_path,
                Path(__file__).resolve().parents[4] / file_path,
            ]
            for candidate in base_candidates:
                if candidate.exists():
                    resolved = candidate
                    break
            else:
                raise CommandError(
                    f"Parquet file not found: '{file_path}'. "
                    f"Tried: {[str(c) for c in base_candidates]}"
                )

        self.stdout.write(self.style.HTTP_INFO(
            f"\n{'[DRY RUN] ' if dry_run else ''}Starting ingestion from: {resolved}"
        ))
        self.stdout.write(f"  Batch size : {batch_size:,}")
        self.stdout.write(f"  Dry run    : {dry_run}\n")

        try:
            job = run_seed_ingestion(
                file_path=str(resolved),
                batch_size=batch_size,
                dry_run=dry_run,
            )
        except Exception as exc:
            raise CommandError(f"Ingestion failed: {exc}") from exc

        # Summary output
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write(self.style.SUCCESS(f"Ingestion completed: {job.status.upper()}"))
        self.stdout.write(f"  Job ID          : {job.id}")
        self.stdout.write(f"  Total rows      : {job.total_rows:,}")
        self.stdout.write(f"  Processed (new) : {job.processed_rows:,}")
        self.stdout.write(self.style.WARNING(
            f"  Failed (invalid): {job.failed_rows:,}"
        ))
        self.stdout.write(f"  Skipped (dups)  : {job.skipped_rows:,}")
        if job.completed_at and job.started_at:
            duration = (job.completed_at - job.started_at).total_seconds()
            self.stdout.write(f"  Duration        : {duration:.1f}s")
        self.stdout.write('=' * 60 + '\n')
