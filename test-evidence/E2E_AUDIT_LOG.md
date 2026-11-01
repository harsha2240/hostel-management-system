# HMS end-to-end audit tracker

> Historical audit record from 28–29 October 2026. Checkout paths, commands,
> test totals and publication restrictions below describe that audit session.
> Its application fixes were subsequently merged in PR #35. For current setup
> and verification, use [README](../README.md), the final commit's CI artifacts
> and the [submission checklist](../docs/SUBMISSION_CHECKLIST.md).

## Purpose and resume point

Audit the merged HMS application feature by feature. Reproduce defects in a disposable environment, fix them in this isolated checkout, add regression coverage, and keep this file current so another turn can resume without losing completed work.

- Audit checkout: `work/hms_e2e_fix`
- Base commit: `5f0cd5fdb5e159f4afd61b4d7cf48f26eda25830` (`origin/main` as checked 2026-10-28)
- Local demo: `http://127.0.0.1:8022/` (latest audit checkout; isolated SQLite database)
- Test database/settings: `work/hms_e2e_env/latest_hms.sqlite3`, `latest_settings.py` (outside source checkout)
- Do not commit, push, merge, or use the user's production database without a separate request.
- Final local run: `python manage.py test --noinput` under `SQLiteCompatibleTestRunner`: **153 passed / 162 discovered**; nine MySQL-specific tests excluded locally. The same merged base commit passed MySQL 8.4 CI run #27 on Python 3.11 and 3.14; the uncommitted audit fixes are not in that run. SQLite output is saved in `test-evidence/E2E_FINAL_TESTS.txt`. Django checks, migration consistency, static collection and CRLF-aware diff checks passed.

## Fixes already made in this audit

- `reports/urls.py`: `/reports/` now redirects to `/reports/occupancy/` instead of a 404.
- `reports/test_reports.py`: regression test for the reports landing route. `docs/SPRINT2.md`: corrected the report-test count and labeled the 136-test MySQL run as historical, documenting newer CI evidence separately.
- Current audit checkout coverage: **91.85% combined with branch coverage**, measured via the pinned Coverage 7.16.2 across 153 selected tests (162 discovered; 9 MySQL-specific tests excluded; the wall-clock timing smoke is skipped under coverage), above the configured 70% gate. Exact report and test output are in `test-evidence/E2E_COVERAGE.txt`. The 89.27% MySQL CI figure is a separate earlier base revision.
- `accounts/templates/accounts/login.html`: changed “Welcome back” to “Welcome to HMS”; explains that first-time users get an account from their hostel administrator. No public registration endpoint is added because account role and student-record linking are staff-managed.
- `accounts/tests.py`: regression tests for login copy, account-creation guidance, profile/password settings, audit records, no-op saves and session preservation. `audit/tests.py`: covers audited admin create/update/deactivation paths and delete denial.
- The screenshot payload `<script>alert(1)</script>` was tested in a rendered student page; Django escaped it as text. CSRF checks, report role restrictions, report HTML/CSV, and student self-service authorization also passed in an HTTP-level check.

## Specification-level assessment

- Functional SRS requirements REQ-1 through REQ-24 have automated test coverage in the account, student, hostel, allocation, payment, report and self-service suites (ledger items 2–9), plus a passing cross-feature journey (item 15). The complete local selected suite is green when run without coverage instrumentation; under coverage, only the wall-clock smoke is skipped.
- Local SQLite execution does not prove MySQL-specific behavior; merged base MySQL CI run #27 covers the base revision. Audit-only code and test changes still need publication and a fresh MySQL CI run.
- Test Plan non-functional exit criteria are not complete: NFR-1 to NFR-3 require real JMeter load and 2,000-bed volume; NFR-4 requires scheduled daily backups and restore validation; TC-SEC-06 needs deployed TLS/cookie checks; OWASP ZAP and TC-QUAL-01 browser/usability checks remain open. See ledger items 12–16.
- Do not report the project as having passed the full Test Plan until those acceptance checks have evidence.
## Feature-by-feature ledger

Status legend: `DONE` = tested in current audit checkout; `IN PROGRESS` = started but needs focused verification; `PENDING` = not yet tested; `BLOCKED` = requires external setup/evidence.

| # | Area | Status | Evidence / next action |
|---|---|---|---|
| 1 | Runtime, URL routing, templates, static assets, migrations | DONE | Django checks and migration consistency pass; all migrations applied. Added `STATIC_ROOT`, its regression test, and role-based dashboard smoke tests (3/3). Actual `collectstatic` copied 128 files; final dry-run reported all 128 unchanged. |
| 2 | Login, password validation, lockout, roles, session expiry, settings, account admin | DONE | `python manage.py test accounts --noinput`: 27/27 passed in the uninstrumented full run. Includes new profile/password settings tests for audit events, no-op saves, session preservation and invalid credentials. The login timing smoke passes uninstrumented and is skipped during coverage because tracing adds measurement overhead. |
| 3 | Student register/list/edit/deactivate, validation and account linking | DONE | `python manage.py test students --noinput`: 33/33 passed. Added regression test verifies `<script>alert(1)</script>` is escaped and SQL-shaped search input does not expose unrelated student records. |
| 4 | Hostel/room/bed CRUD, capacity, status and fee validation | DONE | `python manage.py test hostels --noinput`: 29/29 passed on SQLite-compatible runner. Covers hostel/room/bed forms, status and capacity validations, permissions, fee behavior and audit integration. |
| 5 | Allocation, transfer, release, history, conflicts, atomic rollback | DONE on merged main; audit changes need CI rerun | Local SQLite run: 23 functional tests passed; 3 concurrency tests excluded because SQLite locking differs. GitHub Actions run #27 passed on base commit `5f0cd5f` using MySQL 8.4 across Python 3.11/3.14, covering concurrency tests. |
| 6 | Payments, receipts, corrections, balances, PDF | DONE on merged main; audit changes need CI rerun | Local SQLite run: 15 functional tests passed, including receipts/PDF, adjustments, balances, permissions and rollback; 2 concurrency tests excluded locally. GitHub Actions run #27 passed on base commit `5f0cd5f` using MySQL 8.4 across Python 3.11/3.14, covering payment numbering concurrency. |
| 7 | Occupancy/payment reports, filters, HTML/JSON/CSV | DONE | `python manage.py test reports --noinput`: 10/10 passed. Covers calculations, zero-bed, maintenance, stale flags, CSV formula injection, HTML escaping, filters, JSON/CSV, access control and new `/reports/` redirect. |
| 8 | Audit trail, immutability, retention/purge command | DONE | Audit tests 11/11 passed, including admin create/update/deactivation actor attribution and delete denial; `audit.mixins` is now 100% branch coverage. `purge_audit_logs --dry-run` reports 0 eligible records and deletes nothing. |
| 9 | Student self-service privacy and staff/student dashboard navigation | DONE (functional) | Student suite 33/33 passed; HTTP probe confirmed linked user gets own-record page (200), student is denied staff reports/records (403), and unlinked-account behavior is covered by suite. UI route smoke results are recorded in item 12. |
| 10 | Security probes: CSRF, XSS, injection-shaped input, authorization, cache/cookie headers | DONE (local) | CSRF, role denials, escaped XSS payload, SQL-shaped search, CSV formula injection, no-store/session checks all pass. Production-profile `check --deploy` passes when the documented HTTPS/HSTS settings are supplied. Keep subdomain/preload opt-in until the actual domain qualifies. |
| 11 | Project-wide automated regression | PARTIAL | Complete local SQLite suite: 153/153 selected tests passed (162 discovered); 9 MySQL-only tests were excluded locally, and the cross-feature journey was included. The merged main base commit `5f0cd5f` passed Actions run #27 with MySQL 8.4 on Python 3.11 and 3.14. A separate coverage run on this audit checkout passed 152 tests with one timing smoke skipped (coverage was 91.85%). Audit-only fixes have not run in CI. |
| 12 | Browser usability and compatibility (Test Plan TC-QUAL-01) | PARTIAL | Route/template smoke tests: admin 9 linked pages, warden 6, student 3 load; role denials pass. Local login page text is verified. Still required: visual authenticated-page review, latest Chrome/Firefox/Edge compatibility, and a new-warden task walkthrough under 5 minutes. |
| 13 | Database backup/restore recovery (SRS NFR-4; TC-OPS-01) | PARTIAL | Issue-13 evidence records a one-time MySQL dump and a basic separate-database restore/table-count check. A scheduled daily backup, last-24-hour backup evidence, and populated allocation/payment recovery are not demonstrated. |
| 14 | Performance/data volume (SRS NFR-1–NFR-3; TC-PERF-01–03) | PARTIAL | Local tests cover 5,000-student search and login/dashboard timing; the full uninstrumented timing smoke passed. MySQL CI covers allocation/payment race correctness. Not measured: 50 concurrent users for 10 minutes with 95% under 2 seconds, allocation under 3 seconds across repeated runs, or load with 2,000 beds. |
| 15 | Cross-feature staff-to-student journey | DONE (focused test) | `hms/test_system_journey.py`: 1/1 passed. Staff allocation and payment endpoints, receipt/PDF, student self-service privacy, occupancy/payment report totals, role denial, and audit events agree end to end. Included in the complete 153-test suite (all selected tests passed). |
| 16 | Deployment security validation (SRS NFR-12; TC-SEC-06, OWASP ZAP) | PARTIAL | Django `check --deploy` passed for a production-style HTTPS/HSTS config; production flags are documented. No deployed TLS 1.2 scan, live Secure-cookie/redirect verification, or OWASP ZAP scan has been run. |

## Completed test checkpoints

- 2026-10-28 — Accounts/authentication: `python manage.py test accounts --noinput`, 24 passed, 0 failed/errors; SQLite-compatible runner.
- 2026-10-28 — Student workflows/self-service/security: `python manage.py test students --noinput`, 33 passed, 0 failed/errors; includes script escaping and SQL-shaped search.
- 2026-10-28 — Hostel/room/bed: `python manage.py test hostels --noinput`, 29 passed, 0 failed/errors; SQLite-compatible runner.
- 2026-10-28 — Allocation workflows: `python manage.py test allocations --noinput`, 23 passed; 3 concurrency tests excluded on SQLite. No functional failures.
- 2026-10-28 — Payments/receipts: `python manage.py test payments --noinput`, 15 passed; 2 concurrency tests excluded on SQLite. Receipt and PDF test coverage passed.
- 2026-10-28 — Reports: `python manage.py test reports --noinput`, 10 passed, 0 failed/errors. CSV injection/escaping and report landing route covered.
- 2026-10-28 — Audit retention: `python manage.py purge_audit_logs --dry-run`, 0 eligible, no deletions; all migrations are applied. Initial local HTTP `check --deploy` showed expected dev/test warnings; after adding environment-configurable HSTS, a production-style HTTPS profile passed `check --deploy` with no warnings.
- 2026-10-28 — Static assets: reproduced missing-`STATIC_ROOT` failure; added setting/test. `collectstatic --noinput` copied 128 files; dry-run found 128 unchanged.
- 2026-10-28 — Navigation: 3 route smoke tests passed for admin, warden and student pages; guarded routes returned 403 to non-admin roles.
- 2026-10-28 — Production config: HSTS is environment-configurable and documented; the fully configured HTTPS profile passed `check --deploy`. Include-subdomains/preload remain opt-in pending domain configuration.
- 2026-10-28 — Documentation reconciliation: updated `docs/SPRINT2.md` to list ten report tests and distinguish the older 136-test checkpoint from current MySQL CI run #27 and the local audit run.
- 2026-10-28 — Cross-feature web journey: `python manage.py test hms.test_system_journey --noinput --settings=latest_settings --testrunner=sqlite_compat_runner.SQLiteCompatibleTestRunner`, 1 passed, 0 failed/errors. Django discovers it from the installed `hms` app.
- 2026-10-28 — MySQL CI: GitHub Actions run #27 on `main` commit `5f0cd5f` completed successfully. Workflow provisions MySQL 8.4 and tests on Python 3.11/3.14; covers the merged allocation/payment concurrency tests. This run predates audit-only changes.
- 2026-10-28 — Final regression: 149 tests passed, 0 failures/errors; 9 MySQL configuration/concurrency tests were excluded in SQLite mode. Output saved in `test-evidence/E2E_FINAL_TESTS.txt`.
- 2026-10-28 — Audit: `python manage.py test audit --noinput`, 10 passed, 0 failed/errors. `purge_audit_logs --dry-run` reported 0 eligible records and deleted nothing.



## Audit notes and test limitations

- Unfiltered SQLite run on the prior code snapshot reported failures only in MySQL vendor/`information_schema`/SQL-mode checks and SQLite lock errors in concurrency tests. This is not proof of MySQL behavior.
- No MySQL credentials are stored in this log. Never record secrets or real user credentials here.
- A disposable malicious-name probe generated audit events; its student account has been disabled and its student/room probe data removed where database protections permit. These records are confined to the test SQLite DB.
- 2026-10-28 local server login created for preview: username `e2e_admin`; reset/temporary password is communicated in chat only, not stored here.

## Resume instructions

1. Read this file and `git status --short` before continuing.
2. Resume from the latest continuation checkpoint below. The local full suite is already green for this checkout; rerun it only after code changes. Prioritize outstanding external checks: fresh CI for published audit fixes, scheduled backup plus populated MySQL restore, JMeter/load and 2,000-bed tests, browser usability, deployed TLS, and OWASP ZAP.
3. Record exact test command/count, observed behavior, reproducible defect, fix file, and regression test.
4. The merged base code has MySQL 8.4 CI evidence (run #27); rerun CI after publishing audit fixes before treating those fixes as MySQL-verified. Do not mislabel SQLite locking behavior as application failure.
5. At each checkpoint, save this log before long test runs or if an interruption appears likely.

## Continuation checkpoint — 2026-10-28

- Repeated the complete local selected suite after resuming the audit. Command: `python manage.py test --noinput --settings=latest_settings --testrunner=sqlite_compat_runner.SQLiteCompatibleTestRunner`. Result: **149 tests passed, 0 failures/errors, 158 discovered**, with 9 MySQL-specific configuration/concurrency tests excluded; duration 142.722 seconds. Output refreshed in `test-evidence/E2E_FINAL_TESTS.txt`. The first retry attempts stopped before a valid suite because the shell lacked local Django/ReportLab/pypdf paths; those workspace packages were added to `PYTHONPATH`, and the full run passed. These setup failures were not application test failures.
- Repeated `python manage.py check --settings=latest_settings`: no issues.
- Repeated `python manage.py makemigrations --check --dry-run --settings=latest_settings`: no changes detected.
- Repeated `python manage.py collectstatic --dry-run --noinput --settings=latest_settings`: 128 files unchanged.
- Repeated `python manage.py check --deploy --settings=prod_check_settings` with a simulated production HSTS profile (one-year HSTS, subdomains and preload enabled): no issues. This is configuration validation only, not a live deployment/TLS scan; keep HSTS subdomains/preload disabled until the production domain is verified for those settings.
- Installed pinned Coverage 7.16.2 in the isolated test environment. Earlier coverage run: 149 passed / 158 discovered; 9 MySQL-specific tests excluded; 89.55% combined coverage. `test-evidence/E2E_COVERAGE.txt` stores the latest run and full report.
- Load/restore setup check: no `jmeter` or `mysql` executable was found on PATH; TCP port 3306 on localhost is unreachable. Windows service inventory was denied by the environment. Therefore JMeter NFR-1–3 tests and a populated MySQL backup/restore drill remain outstanding; no substitute result is claimed.
- Browser check: after the user confirmed Browser was enabled, CUA continued to report local browser use disabled in Work settings. The app browser-panel request for `http://127.0.0.1:8022/login/` returned queued; page visibility could not be verified through CUA. The Django development server is running at that address. Previously saved local UI smoke and login text results remain as listed above; authenticated cross-browser/usability review is still open.
- Local Git diff whitespace check passed. Working tree remains uncommitted; no remote branch, PR, or merge was changed.


## Continuation checkpoint — 2026-10-28 (admin-audit coverage follow-up)

- Added `AuditedAdminMixinTests` in `audit/tests.py` to exercise admin create, update, account deactivation, student status deactivation, audit actor attribution, parent admin logging, and delete denial. Focused test passed: 1/1. It exposed no application defect; it closes previously untested audit-admin behavior.
- Re-ran the full suite under pinned Coverage 7.16.2: **150 passed, 0 failures/errors, 159 discovered**, with 9 MySQL-specific tests excluded; duration 231.147 seconds. Current combined branch coverage is **90.49%**, above the configured 70% gate. `audit/mixins.py` coverage is now 100% (previously 33.33%). Updated test output and full coverage report are saved in `test-evidence/E2E_FINAL_TESTS.txt` and `test-evidence/E2E_COVERAGE.txt`.
- The user's in-app browser context now shows `http://127.0.0.1:8022/login/`. The browser-control API still reports local browser use disabled in Work settings, so I could not inspect the live DOM or walk authenticated pages in this continuation.
- All previously recorded open system-level acceptance checks remain outstanding: post-publication MySQL CI, JMeter/concurrent load and 2,000-bed volume, scheduled backup and populated restore drill, deployed TLS/OWASP ZAP, and authenticated cross-browser/usability walkthrough.


## Continuation checkpoint — 2026-10-28 (settings and timing follow-up)

- Added three account-settings regressions in `accounts/tests.py`: profile save writes one UPDATE audit event while a no-op save does not; valid password change updates the password, rotates the session key while keeping the user signed in, and does not store the new password in audit data; invalid password submission leaves the password unchanged and emits no UPDATE event. An initial assertion mistakenly counted the expected LOGIN event; it was narrowed to UPDATE events, then all three focused tests passed.
- Full uninstrumented suite: **153 passed, 0 failures/errors, 162 discovered**, with 9 MySQL-only tests excluded by the SQLite-compatible runner; duration 199.398 seconds. Saved in `test-evidence/E2E_FINAL_TESTS.txt`.
- Full Coverage 7.16.2 run: 153 selected, 152 passed and the one wall-clock timing smoke skipped; 9 MySQL-specific tests excluded. Coverage is **91.85% combined branch-aware** (70% project gate). `accounts/views.py` is now 91.72% and `audit/mixins.py` is 100%. Saved in `test-evidence/E2E_COVERAGE.txt`.
- The first instrumented full run failed only because admin login measured 2.44 seconds against a 2-second threshold under Coverage. The same timing test passed without Coverage, including in the complete uninstrumented suite. To avoid a misleading CI failure, it now skips only while `COVERAGE_RUN=true`; the ordinary run still measures the 2-second threshold. The first failure is preserved in `test-evidence/E2E_COVERAGE_TIMING_FAILURE.txt`.
- Focused audit suite: 11/11 passed. Focused timing test: 1/1 passed without Coverage.
- User's browser context shows `http://127.0.0.1:8022/login/` open; direct CUA/browser controls continue to report disabled. No authenticated visual walkthrough or cross-browser review was possible here.
- No GitHub publication or merge was made. System-level performance/load, MySQL CI after publication, backup/restore, deployed TLS/OWASP ZAP and authenticated usability checks remain open as in the Test Plan.

## Continuation checkpoint — 2026-10-28 (browser recheck)

- The user's in-app browser panel visibly rendered `http://127.0.0.1:8022/login/`. The login page shows “Welcome to HMS”, sign-in guidance, and first-time account guidance (“Ask your hostel administrator to create an account”). This confirms the updated login copy is present in the running preview.
- Retried browser enumeration after the user enabled Browser access. CUA still returned `Browsers: Error: Local browser use is disabled in Work settings`; the app panel is visible but this does not grant browser automation. A separate Windows Chrome window is on GitHub and is not the HMS browser panel. No login, form submission, or authenticated role walkthrough was performed.
- A direct local HTTP smoke attempt was blocked by the command sandbox (`An attempt was made to access a socket in a way forbidden by its access permissions`). Therefore the visible panel is the only live-browser evidence in this checkpoint; automated Django tests remain the authoritative route/feature evidence.
- `git -c core.whitespace=cr-at-eol diff --check` passed. Working tree remains uncommitted; no remote branch, PR, or merge was changed.
- Resume from the latest audit status above. Do not claim cross-browser or authenticated end-to-end acceptance; outstanding items remain post-publication MySQL CI, JMeter/concurrent load and 2,000-bed volume, scheduled backup and populated restore drill, deployed TLS/OWASP ZAP, and authenticated usability review.

## Continuation checkpoint — 2026-10-28 (offline verification, no installs)

- Per user instruction, no packages were installed and the previously saved full regression output was used as evidence: 153 passed, 0 failures/errors, 162 discovered, with 9 MySQL-only tests excluded; branch-aware Coverage report remains 91.85%. The attempted duplicate full-suite rerun was interrupted before completion and is not counted as a result.
- Reused the already bundled Python runtime and available project package paths. Fresh offline results: `manage.py check --settings=latest_settings` passed; `makemigrations --check --dry-run --settings=latest_settings` reported no changes; `collectstatic --dry-run --noinput --settings=latest_settings` reported 128 unchanged; production-profile `check --deploy --settings=prod_check_settings` passed with the documented local HTTPS/HSTS variables; and `git -c core.whitespace=cr-at-eol diff --check` passed.
- Browser automation remains unavailable (`Local browser use is disabled in Work settings`), despite the HMS login page being visible in the app browser panel. No authenticated role walkthrough was completed.
- Offline scope is now verified as far as the available tools allow: application unit/integration tests from the saved suite, Django system and migration checks, static asset configuration, production security settings validation, route/permission tests, HTML/CSV security regressions, and the staff-to-student journey. Remaining checks require external/live facilities: fresh MySQL CI for this unpublished checkout, JMeter concurrency/load and 2,000-bed volume, scheduled backup plus populated MySQL restore drill, real deployed TLS/cookie validation, OWASP ZAP, and authenticated visual/cross-browser usability.
- No code change was needed from this checkpoint. Audit changes remain uncommitted and unpublished.

## Continuation checkpoint — 2026-10-28 (resume in constrained runtime)

- Read this audit log and checked the checkout before running checks. The working tree is intentionally uncommitted: modified `.env.example`, `README.md`, login template, account/audit/student tests, settings, reports route/tests and `docs/SPRINT2.md`; added navigation/settings/system-journey tests and audit evidence files; `.tmp/` is also untracked. No files were reset, staged, committed, or pushed.
- Fresh `git -c core.whitespace=cr-at-eol diff --check` passed (no output).
- This turn's PATH Python is `C:\Python314\python.exe`; it cannot import Django, Coverage, ReportLab, pypdf, or a MySQL driver. No `jmeter` or `mysql` executable is available. The prior task-local package directory contains only Coverage and pypdf at inspection, so a fresh Django check/test run is not supported from this shell without adding/installing dependencies; none were installed. The saved offline rerun and full-suite evidence above remain the most recent valid project-test results (153 passed; 9 MySQL-only excluded; 91.85% branch-aware coverage).
- No further environment-backed checks were available in this continuation. Outstanding external checks remain fresh MySQL CI after publishing, JMeter/load and 2,000-bed volume, scheduled backups and populated MySQL restore, deployed TLS and OWASP ZAP, and authenticated browser/cross-browser usability. No CI publication or deployment was attempted.

## Continuation checkpoint — 2026-10-28 (full offline rerun)

- Located and reused existing Django 5.2.18, ReportLab 4.5.1 and pypdf 6.21.2 package copies in sibling project work directories; no packages were installed. Because this checkout's current environment requires environment-backed settings, test commands used a dummy audit-only `DJANGO_SECRET_KEY` plus dummy DB credentials that are overridden by the isolated SQLite settings. No production credentials were used.
- Full command: `python manage.py test --noinput --settings=latest_settings --testrunner=sqlite_compat_runner.SQLiteCompatibleTestRunner`. Result: **153 passed, 0 failures/errors, 162 discovered**, 9 MySQL-only configuration/concurrency tests excluded; duration 60.879 seconds. This includes the cross-feature system journey.
- Fresh `python manage.py check --settings=latest_settings`: passed, no issues. `makemigrations --check --dry-run --settings=latest_settings`: no changes detected. `collectstatic --dry-run --noinput --settings=latest_settings`: 128 files unchanged. `purge_audit_logs --dry-run --settings=latest_settings`: 0 eligible records, no deletions. `git -c core.whitespace=cr-at-eol diff --check`: passed.
- Production-profile `check --deploy --settings=prod_check_settings` passed with secure cookies, HTTPS redirect, one-year HSTS, subdomains and preload enabled in the simulated configuration. This validates settings only; actual domain suitability, deployed TLS and preload eligibility are not verified. With subdomains/preload disabled it emits the expected Django W005/W021 warnings.
- Browser E2E was attempted against a local Django server at `http://127.0.0.1:8022/login/`; the in-app browser reported connection refused/timed out, so authenticated visual usability checks remain blocked. The local server was stopped afterward. This is an environment connectivity limitation, not a reproduced application defect.
- MySQL client `mysqlsh` is installed, but localhost TCP/3306 is unreachable. Docker CLI is present, but the Docker daemon is not running; JMeter is not on PATH. Therefore MySQL-specific tests/CI, load and 2,000-bed tests, and MySQL backup/restore remain blocked pending reachable services/tooling. A fresh CI run also requires publication, which was not done under the no-commit/push instruction.
- No application defect was exposed by the rerun, so no additional source changes were needed. Existing working-tree audit changes and artifacts remain uncommitted and preserved.

## Continuation checkpoint — 2026-10-28 (MySQL and remaining external checks)

- Checked remaining local tooling. MySQL Server 8.0.46 (`mysqld.exe`) and MySQL Shell are installed; JMeter is absent from PATH and the common local install locations checked. Docker CLI is installed, but the Docker daemon is unavailable. Service/task inventory access is restricted in this environment.
- To attempt MySQL coverage without installing anything or touching an existing database, initialized a new disposable MySQL 8.0.46 data directory under `.tmp/mysql-audit-data` and started the server on `127.0.0.1:13306`. The server reported ready, but MySQL Shell could not connect to that loopback port (Windows socket error 10060); MySQL test execution therefore remains blocked by the execution environment's local network isolation. The server was stopped. The temporary test data directory remains under `.tmp` because the sandbox rejected the cleanup operation; it contains only the newly initialized, empty test instance, no production data or test credentials.
- This local instance was MySQL 8.0.46, not the MySQL 8.4 CI version, and no MySQL test was counted as passing. Publishing remains prohibited by the existing no-commit/push instruction, so audit changes cannot be exercised by a new GitHub Actions run from this turn.
- JMeter performance/concurrency/2,000-bed tests still require JMeter. Backup scheduling and populated restore still require an accessible MySQL environment and backup target. Deployed TLS and OWASP ZAP still require a deployed endpoint. Authenticated browser usability remains blocked because the in-app browser could not connect to the local preview.
- No source defect was found in the new checks; no application code was changed. The previously recorded 153-test SQLite-compatible suite and Django check results remain valid.

## Publication checkpoint — 2026-10-28

- Committed the reviewed audit source, regression tests, documentation and evidence on local branch `codex/hms-e2e-audit`. Generated `.tmp/` test data was excluded.
- Push to `origin` was attempted after the user authorized publication, but Git Credential Manager could not start from Git's shell. Direct helper lookup found no cached GitHub credential and Windows denied credential-store enumeration (`Access is denied`). No branch was pushed, no pull request was opened, and no fresh CI run has started.
- Resume publication after GitHub authentication is made available to Git Credential Manager. Then push this branch, open a PR to `main` (the workflow runs on pull requests), and inspect the MySQL 8.4 / Python 3.11 and 3.14 workflow results. Do not include `.tmp/` in the PR.


## Continuation checkpoint — 2026-10-28 (fresh MySQL CI)

- Pushed in commit `57ae5a28b00f3cd9b3d7be94894bca160330e22f`. The first CI run failed on literal `\r\n` characters at the end of `hms/test_system_journey.py`, introduced during EOF whitespace cleanup; this was a test-file syntax issue and was fixed.
- SQLite-compatible regression rerun: 153 passed, 0 failures/errors, 162 discovered; 9 MySQL-only tests excluded; 77.632 seconds.
- Fresh GitHub Actions run #29 (`40684127245`) passed both matrix jobs using MySQL 8.4.13: Python 3.11.17 and Python 3.14. Each ran 162 tests with one expected coverage-mode skip; system checks, migrations, tests and coverage gate passed.
- PR #35 is open from `codex/hms-e2e-audit` to `main`. Remaining Test Plan items requiring external facilities are JMeter concurrency/load and 2,000-bed volume, scheduled backup plus populated restore, deployed TLS/cookie checks, OWASP ZAP, and authenticated cross-browser usability (ledger items 12–16).


## Continuation checkpoint — 2026-10-28 (remaining acceptance checks attempted)

- Rechecked available tooling: JMeter and ZAP are absent from PATH and the common install locations checked; no `.jmx` load plan or staging/deployment workflow/URL is present in this checkout. Docker CLI exists but `docker info` cannot reach the Docker Desktop daemon. No MySQL server is listening on the default port, and the local HMS preview at `127.0.0.1:8022` is not running.
- With temporary loopback access enabled, started a new empty disposable MySQL 8.0.46 instance under `.tmp/mysql-restore-audit` on `127.0.0.1:13306`; `SELECT VERSION()` connected and returned 8.0.46. The instance was stopped after the connectivity probe. It was not MySQL 8.4 and had no HMS schema/data; no application backup/restore or MySQL integration test is claimed. The current Python 3.14 runtime has no Django installed, and no local Django package copy or virtual environment is available, so it could not populate the database without installing dependencies (not permitted). MySQL binaries are installed outside PATH.
- Remaining acceptance checks were not runnable here: JMeter 50-user/10-minute and 2,000-bed tests; scheduled daily backup and populated HMS restore; deployed TLS/Secure-cookie and OWASP ZAP checks; authenticated cross-browser walkthrough. There is no configured staging host, test account, backup target, or browser-accessible HMS endpoint in this checkout.
- No application defect was found and no source change was needed. The disposable MySQL process is stopped. The temporary initialized database directory remains in ignored `.tmp/`; it contains no HMS data.

## Continuation checkpoint — 2026-10-28 (local load test and bed pagination)

- Prepared a disposable local load environment with JMeter 5.6.3, OWASP ZAP 2.17.0, MySQL 8.0.46 and synthetic-only HMS data (2,000 beds, 2,000 students, 50 allocations/payments). The populated backup was restored into a separate database and table counts matched; a manual daily backup ZIP passed integrity validation. Windows Task Scheduler registration remains blocked by restricted CIM/`schtasks` access.
- JMeter smoke: 2 users, 15 seconds, 30 recorded samples, zero failed samples; both logins landed on the dashboard.
- Full JMeter run: 50 users, 60-second ramp, 10 minutes at peak; 11,194 recorded samples, zero JMeter failures, 11,144 HTTP 200 responses and 50 login redirects. Aggregate mean was 1.9 seconds; worst sample 46.8 seconds. The `/beds/` route was the clear hotspot: 1,247 samples, 12.2-second mean, 29.6-second p95, 46.8-second maximum while rendering all 2,000 beds. These are local test figures; no production latency SLA is specified.
- Fixed the hotspot by paginating `/beds/` at 50 rows per page while preserving the existing queryset context and GET filters. Added regression coverage for page size, total results and second-page navigation. Focused bed-filter suite: 6/6 passed. Full SQLite-compatible suite after the fix: 154 passed, 0 failures/errors, 163 discovered; 9 MySQL-specific tests excluded; 62.815 seconds. Django system check passed.
- A post-fix load run has not yet been performed, so the performance improvement is not quantified. OWASP ZAP has not yet been run. Deployed TLS, authenticated cross-browser/usability walkthrough and scheduled-task backup remain deployment/environment blockers. The test plan should retain these as open if they are required by the submission rubric.

- Post-fix JMeter smoke was attempted after the full test run, but the local application endpoint then rejected loopback connections (`java.net.SocketException` / Windows socket access forbidden); the 28 failed socket samples are invalid for application performance and are not counted as a post-fix result. The full post-fix test suite remains valid. A rerun needs the local preview server and loopback access restored. OWASP ZAP was not run because it also requires a reachable endpoint.

## Submission board reconciliation — 2026-10-29

- Read the live HMS Team 3 Development Board and issue records. HMS-14 / issue #32 is in **In Progress**, opened 27 October, with three assignees. Its acceptance criteria require role-based Admin/Warden/Student end-to-end workflows, desktop/mobile usability checks and saved scenario evidence. Do not move it to Done to make the burndown look complete; close it only after its real acceptance criteria are evidenced. It has no Sprint or Story Points field set, so it is outside the original 13-issue, 53-point Part-1 backlog baseline unless the team records a scope change and estimate.
- The board currently shows HMS-13 / issue #13 Done/closed; PR #33 merged 28 October. However, the PR review explicitly said it was partial and requested that #13 remain open until populated allocation/payment recovery and concurrent-user performance were measured. Later local audit evidence now includes a populated restore and 50-user JMeter run, but the SRS target of 95% of requests within 2 seconds was exceeded (especially `/beds/` before pagination), and the post-pagination load comparison remains blocked. The board closure and evidence should be reconciled with the team; the burndown records the board's closure date while this acceptance caveat remains visible.
- Added `docs/SUBMISSION_CHECKLIST.md`, `docs/BURNDOWN.md`, the SVG chart and CSV source. The chart is based on the planned Sprint 1 and Sprint 2 issue set and dated merge/closure history. HMS-14 is shown as separate unestimated follow-up scope rather than retroactively inserted.
