"""Run #40's JMeter load/volume cases serially against disposable test_hms.

Requires Java 17+ and Apache JMeter 5.6.3 installed outside the repository.
The default is two 600-second, 50-user scenarios. Short runs are smoke checks
and never acceptance evidence. Run serially with all other MySQL test suites.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jmeter", required=True, type=Path)
    parser.add_argument("--java", type=Path)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument(
        "--scenario", choices=["baseline", "volume", "both"], default="both"
    )
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be positive.")
    jmeter = args.jmeter.resolve()
    jar = jmeter if jmeter.suffix == ".jar" else jmeter.with_name("ApacheJMeter.jar")
    if not jar.is_file():
        parser.error(
            "--jmeter must identify JMeter's bin/jmeter.bat or ApacheJMeter.jar."
        )
    java = args.java or (
        Path(os.environ["JAVA_HOME"]) / "bin" / "java.exe"
        if os.environ.get("JAVA_HOME")
        else shutil.which("java")
    )
    if not java or not Path(java).is_file():
        parser.error("Specify --java or JAVA_HOME pointing to Java 17+.")
    output = (
        args.output_dir
        or ROOT
        / "test-results"
        / "issue40-load"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    ).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error(
            "Choose a new empty output directory to preserve previous evidence."
        )
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", str(output / "private-evidence-check")],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if ignored.returncode != 0:
        parser.error(
            "Choose a Git-ignored output directory, for example test-results/issue40-load/NEW."
        )
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hms.settings")
    os.environ.pop("COVERAGE_RUN", None)
    os.environ["HMS_ISSUE40_LOAD_CONFIG"] = json.dumps(
        {
            "java": str(Path(java).resolve()),
            "jmeter_jar": str(jar),
            "seconds": args.seconds,
            "scenario": args.scenario,
            "output": str(output),
        }
    )
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connection

    database = settings.DATABASES["default"]
    if database["ENGINE"] != "django.db.backends.mysql" or database["NAME"] != "hms":
        parser.error(
            "This runner requires the documented MySQL hms configuration; its disposable database is test_hms."
        )
    if database.get("TEST", {}).get("NAME") not in (None, "test_hms"):
        parser.error("A custom test database is configured; refusing to touch it.")
    if database.get("TEST", {}).get("MIRROR"):
        parser.error("A mirrored test database is configured; refusing to touch it.")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = %s",
            ["test_hms"],
        )
        existing_test_database = cursor.fetchone()
    connection.close()
    if existing_test_database:
        parser.error(
            "test_hms already exists; refusing to let Django replace an existing database. "
            "Identify its owner and preserve/remove it separately before running this harness."
        )
    output.mkdir(parents=True, exist_ok=True)
    call_command("test", "test_issue40_load", interactive=False, verbosity=2)


if __name__ == "__main__":
    main()
