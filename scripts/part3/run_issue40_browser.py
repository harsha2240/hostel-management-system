"""Execute only #40 browser/HTTP cases in disposable test_hms.

Requires Node.js, Microsoft Edge and optional Playwright available to Node (for
example via NODE_PATH). Install verification tools outside the application repo.
Run serially with other Django/MySQL suites. No coverage or other Part 3 reports
are generated here. Results describe a candidate build pending team acceptance.
"""

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output = (
        args.output_dir
        or ROOT
        / "test-results"
        / "issue40-browser"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    output = output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error(
            "Choose a new empty output directory to preserve previous evidence."
        )
    # Fail before database setup if the optional browser tooling is unavailable.
    subprocess.run(
        ["node", "-e", "require('playwright');"],
        check=True,
        capture_output=True,
        text=True,
    )
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hms.settings")
    os.environ.pop("COVERAGE_RUN", None)
    os.environ["HMS_ISSUE40_OUTPUT_DIR"] = str(output)
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command

    database = settings.DATABASES["default"]
    if database["ENGINE"] != "django.db.backends.mysql" or database["NAME"] != "hms":
        parser.error(
            "This runner requires the documented MySQL hms configuration; its disposable database is test_hms."
        )
    configured_test = database.get("TEST", {}).get("NAME")
    if configured_test not in (None, "test_hms"):
        parser.error("A custom test database is configured; refusing to touch it.")
    if database.get("TEST", {}).get("MIRROR"):
        parser.error("A mirrored test database is configured; refusing to touch it.")
    output.mkdir(parents=True, exist_ok=True)
    call_command("test", "test_issue40_browser", interactive=False, verbosity=2)


if __name__ == "__main__":
    main()
