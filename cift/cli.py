import argparse
import logging
from datetime import datetime
from datetime import timezone
from pathlib import Path

from pythonjsonlogger import jsonlogger

log = logging.getLogger(__name__)


def configure_logger(debug: bool = False) -> None:
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)
    logging.basicConfig(
        handlers=[handler], level=logging.DEBUG if debug else logging.INFO
    )


def get_parser():
    parser = argparse.ArgumentParser(description="Choose function and get arguments.")

    subparsers = parser.add_subparsers(dest="func")

    # -- SQLite pipeline commands (ADR-001); imports stay inside the handlers so
    # `ingest` runs on the minimal scraping environment without pandas/matplotlib.
    parser_ingest = subparsers.add_parser(
        "ingest", help="Snapshot all endpoints into one inbox database."
    )
    parser_ingest.add_argument("--db_root", default="data/db", type=Path)
    parser_ingest.add_argument("--debug", action="store_true")

    parser_compact = subparsers.add_parser(
        "compact", help="Fold complete days of inboxes into the partitions."
    )
    parser_compact.add_argument("--db_root", default="data/db", type=Path)
    parser_compact.add_argument("--max_inboxes", default=None, type=int)
    parser_compact.add_argument("--debug", action="store_true")

    parser_analyse = subparsers.add_parser(
        "analyse", help="Rebuild charts, README tables and stored statistics."
    )
    parser_analyse.add_argument("--db_root", default="data/db", type=Path)
    parser_analyse.add_argument("--charts", default="charts", type=Path)
    parser_analyse.add_argument("--readme", default="README.md", type=Path)
    parser_analyse.add_argument("--days", default=7, type=int)
    parser_analyse.add_argument("--debug", action="store_true")

    parser_migrate = subparsers.add_parser(
        "migrate", help="One-off historical migration with its verification gate."
    )
    parser_migrate.add_argument("--data_dir", default="data", type=Path)
    parser_migrate.add_argument("--db_root", default="data/db", type=Path)
    parser_migrate.add_argument(
        "--staging", default="migration_staging.sqlite", type=Path
    )
    parser_migrate.add_argument("--debug", action="store_true")

    return parser


def _cmd_ingest(args: argparse.Namespace) -> None:
    from cift.client import CarbonIntensityClient
    from cift.ingest import run_ingest

    path = run_ingest(
        db_root=args.db_root,
        now=datetime.now(tz=timezone.utc),
        client=CarbonIntensityClient(),
    )
    print(f"inbox={path}")


def _cmd_compact(args: argparse.Namespace) -> None:
    from cift.store import Store

    report = Store(args.db_root).compact(
        now=datetime.now(tz=timezone.utc), max_inboxes=args.max_inboxes
    )
    print(
        f"merged={report.merged_inboxes} remaining={report.remaining_inboxes}"
        f" quarantined={','.join(report.quarantined) or 'none'}"
    )


def _cmd_analyse(args: argparse.Namespace) -> None:
    from cift.analyse import run_analyse

    report = run_analyse(
        db_root=args.db_root,
        charts_dir=args.charts,
        readme_path=args.readme,
        now=datetime.now(tz=timezone.utc),
        days=args.days,
    )
    print(f"charts={len(report.charts)} stats_dates={','.join(report.stats_dates)}")
    for alert in report.health.alerts:
        print(f"HEALTH-ALERT: {alert}")


def _cmd_migrate(args: argparse.Namespace) -> None:
    from cift.migrate import GOLDEN_COUNT
    from cift.migrate import GOLDEN_MEAN
    from cift.migrate import run_migration

    report = run_migration(
        data_dir=args.data_dir, db_root=args.db_root, staging_path=args.staging
    )
    for name, stage in sorted(report.staged.items()):
        print(f"staged {name}: {stage.staged} files, {len(stage.excluded)} excluded")
        for filename, reason in stage.excluded[:20]:
            print(f"  excluded {filename}: {reason[:150]}")
        if len(stage.excluded) > 20:
            print(f"  ... and {len(stage.excluded) - 20} more exclusions")
    print(f"gaps={report.gap_count} emitted={report.emitted}")
    print(f"overlap_fatal={report.overlap.fatal}")
    for note in report.overlap.accepted:
        print(f"overlap_accepted: {note}")
    print(f"reconstruction={report.reconstruction}")
    print(f"reextraction_mismatches={report.reextraction_mismatches}")
    print(f"provenance_mismatches={report.provenance_mismatches}")
    print(f"leftover_inboxes={report.leftover_inboxes}")
    count, mean = report.golden
    print(f"golden count={count} mean={mean:.4f} (target {GOLDEN_COUNT}/{GOLDEN_MEAN})")
    print(f"reference={report.reference_counts}")
    golden_ok = count == GOLDEN_COUNT and round(mean, 4) == GOLDEN_MEAN
    if not (report.gate_passed and golden_ok):
        raise SystemExit("MIGRATION GATE FAILED - source files must not be deleted")
    print("MIGRATION GATE PASSED")


NEW_COMMANDS = {
    "ingest": _cmd_ingest,
    "compact": _cmd_compact,
    "analyse": _cmd_analyse,
    "migrate": _cmd_migrate,
}


def main(argv: list[str] | None = None) -> None:
    args = get_parser().parse_args(argv)
    configure_logger(getattr(args, "debug", False))

    if command := NEW_COMMANDS.get(args.func):
        command(args)
    else:
        get_parser().print_help()


if __name__ == "__main__":
    main()

# End
