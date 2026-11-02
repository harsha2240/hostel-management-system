# Issue #40: owned execution evidence

Owner: Devansh Gupta (`DevaOnL`). Executed **2 November 2026**.
[HMS-18 / #40](https://github.com/Sreeharsha2240/hostel-management-system/issues/40)
is the only execution assignment handled here. This supplies evidence for
[Part 3](../../../PART3.md); other contributors' cases/reports and #42 remain
with their assigned owners.

## Latest execution and acceptance boundary

**All 13 owned case areas passed on the local candidate build.** The reviewed
case register/RTM and tool substitution in #37, independent teammate review and
acceptance of the build in PR #36, and integration into #38 remain pending.
Issue #40 stays open for those team acceptance steps. No teammate approval,
final System Validation Report, coverage report or whole-Test-Plan exit is
claimed by these results.

The runs record base commit `265d24fe9dc1a7346e8e3210349ee3fda885d26f` and
`git_dirty=true` while the new harnesses/evidence were being prepared. Exact
harness SHA-256 values are retained. Git normalizes the load JMX from CRLF to LF;
the load JSON records both byte hashes and equal parsed XML canonical forms.
Only line breaks differ. Other current harness hashes match the final files.
Application, migration, template and existing regression-test source remained
unchanged from that base. CI verifies the published revision separately; do
not replace these truthful run provenance fields with a later commit hash.

| Owned case | Actual candidate result | Fresh evidence |
|---|---|---|
| TC-ALC-01..04, TC-ALC-06 | PASS: allocation/date/status; occupied-bed, duplicate and gender rejection; release/date/history | [Edge/HTTP execution](completion-browser.json) and [regressions](completion-regressions.json) |
| TC-ALC-05 | PASS using combined evidence: browser transfer/status/history plus independently forced target-save failure with complete transaction rollback | Browser JSON deliberately retains PARTIAL for its own missing injection step; `test_transfer_failure_rolls_back_both_beds_and_history` passes in the regression JSON |
| TC-PAY-01..02 | PASS: positive payment/PDF/date/sequence, zero/negative rejection, Pending/Partial/Paid; companion tests cover modes/dates, immutable adjustments, counter/audit rollback and concurrency | Browser and regression JSON |
| TC-RPT-01 | PASS: filtered occupancy/payment HTML and downloaded CSV reconcile with MySQL; companion tests cover JSON, permissions, zero beds and maintenance | Browser and regression JSON |
| TC-PERF-01 | PASS: actual 50-user full ten-minute baseline, login/search/bed content assertions, no errors and 100% of HTTP samples within two seconds | [Full JMeter results](completion-load.json) |
| TC-PERF-02 | PASS: 20 committed HTTP allocations, maximum **69.95 ms**; overlapping same-bed requests produce one winner and one conflict, with one active row | Browser JSON |
| TC-PERF-03 | PASS: exactly 5,000 students / 2,000 beds, repeated 50-user full ten-minute load; every search within two seconds | Full JMeter results |
| TC-OPS-01 | PASS: actual naturally triggered daily jobs, recent backup, populated separate-database restore, matching all-table contents/schema, zero logical violations and no observed loss | [Final recovery](completion-recovery.json); [initial failure history](candidate-recovery.json) |

The browser JSON predates the full load/recovery runs, so its per-run
`remaining_owned_cases` and ALC-05 companion-needed fields are preserved.
The later load/recovery and 60-method regression artifacts supply that evidence;
those earlier fields are not the aggregate status above.

## Performance results

| Workload | HTTP samples | Errors | Within 2 s | HTTP p95 | Search max | Observed HTTP requests/s |
|---|---:|---:|---:|---:|---:|---:|
| Baseline: 100 students, 80 beds | 29,002 | 0 | 100% | 57 ms | 166 ms | 47.79 |
| Volume: 5,000 students, 2,000 beds | 28,906 | 0 | 100% | 57 ms | 309 ms | 47.64 |

Each run has 50 unique start/end markers and one common measurement start after
the five-second ramp/barrier. Minimum measured user intervals were
**600,351 ms** and
**600,113 ms**, respectively.
Every user performed exactly one login-form GET and authenticated login, plus
repeated search/bed requests. Both routes asserted real synthetic table rows and
the authenticated user, rejecting a login page returned with HTTP 200. All
HTTP/authentication/setup samples and all sampler/controller errors are retained.
The volume gate additionally requires every search sample within 2,000 ms.

Environment: Python 3.14.7, Django 5.2.18, MySQL 8.4.9, JMeter 5.6.3 and Eclipse
Temurin Java 17.0.20+8. Official archive checksums and sources are in the load
JSON. JMeter uses 50 distinct Warden accounts, the normal password hasher,
real session/audit writes and one second of think time before each measured
HTTP sampler. Followed redirects are included in HTTP transaction latency.
This is a threaded Django test server over loopback HTTP on Windows, with local
secure-redirect/cookie flags disabled and synthetic disposable `test_hms` data.
It establishes the stated local candidate observations. The original Test Plan
names Selenium/MySQL 8.0; this run uses the available Edge/Playwright browser
automation for the same steps and supported MySQL 8.4 LTS. Team review of these
substitutions and the final accepted-build rerun remain separate.

[The October comparison](../../../../test-evidence/E2E_AUDIT_LOG.md)
preserves the earlier 50-user, 2,000-student/2,000-bed pre-pagination failures
(bed p95 29.6 seconds) and blocked socket-error rerun. The new volume run verifies
the post-pagination target using 5,000 students. Versions, workload/pacing and
harness differ; no controlled percentage speedup is inferred.

The fresh 20 allocation samples range from **26.16 ms** to
**69.95 ms**, median **27.72 ms**.
Each measurement includes a real POST through receipt of the response after
commit, outside a transaction-wrapped test. Raw browser intervals and database
verification establish the simultaneous-conflict result.

## Backup, recovery and retests

The live `hms` source had no populated domain records. A separate private
MySQL 8.4.9 instance, bound to a distinct loopback port with its own datadir,
held three synthetic students, four beds (including maintenance), two
allocations (active/history), two payments (original/adjustment) and three audit
rows. Its natural Windows daily trigger produced the backup actually restored
to its previously absent `test_hms`. All 18 tables' counts, row digests and schema
digests matched; all 17 logical checks found zero violations, including orphan
references, active-allocation uniqueness, occupied-bed state and receipt/adjustment
consistency. Backup age at final comparison was **1497.366
seconds**, under 24 hours. No rows were lost relative to the unchanged source.
The restored database was removed and the owned private server stopped.

A separately observed read-only live `hms` daily backup also completed. The
remaining Windows task `HMS-Issue40-DailyBackup` was **Ready**, last result **0**,
with daily interval **1** and next trigger **3 November 2026 at 09:21:55 IST**.
Its action hash was unchanged by the populated recovery reruns. Live `hms` was
never seeded or restored. This is an **interactive current-user task**: Windows,
MySQL and the user session must be available; `StartWhenAvailable` handles a
missed trigger when available. It is not evidence of unattended service uptime.
Private SQL dumps and connection settings stay outside Git.

The execution history preserves three harness failures and their retests:

- Initial shutdown refused a Windows MySQL monitor/child PID difference. Exact
  executable, parent/child ownership, port and datadir were verified before manual
  shutdown. The corrected guarded automatic shutdown subsequently passed.
- The first consistency rerun failed because MySQL 8.4 reserves `LAST_VALUE`;
  the receipt counter column is now quoted.
- The next rerun exposed MySQL aggregate `Decimal` values during JSON encoding;
  counts are now normalized to integers, with an offline regression. The final
  populated restore, all 17 SQL checks, target removal and automatic shutdown passed.

Original failures, tested harness hashes and actual rerun outcomes remain in the
linked JSON. A passing final result does not rewrite those observations.

## Verification and reproduction

Fresh verification passed **60 focused methods**, the explicit Edge/HTTP
workflows, **21 offline recovery safety methods**, and all **12 repository gates**.
The full suite discovered 185 methods: 184 passed under coverage, one deliberate
timing skip was followed by a separate passing timing run. The mixed-suite
coverage gate is routine repository verification; it does not prepare #42's two
reports or prove unit-test-attributable coverage. The new safety suite is also
an explicit step in both Python 3.11/3.14 CI jobs. Inspect the matching final-head
CI result separately; optional browser/JMeter/Windows scheduling runs are local.

Use the documented MySQL environment and run one suite at a time against its
server's disposable database. Both browser/load wrappers refuse an existing
`test_hms`, mirrored/custom database settings, nonempty evidence destinations
and output outside Git-ignored storage. Actual refusal tests preserved a random
sentinel in a pre-existing test database. Do not remove a database without
identifying its owner.

```powershell
python manage.py test allocations payments reports hms.test_system_journey --noinput --testrunner=xmlrunner.extra.djangotestrunner.XMLTestRunner
python -m unittest discover -s scripts/part3 -p test_issue40_recovery_safety.py -v
python scripts/run_checks.py
```

For the browser runner, provide optional Playwright through `NODE_PATH` and an
installed Edge browser, then use a fresh ignored output directory:

```powershell
python scripts/part3/run_issue40_browser.py --output-dir test-results/issue40-browser/NEW
```

Install verified JMeter 5.6.3 and Java 17+ privately, then pass their paths:

```powershell
python scripts/part3/run_issue40_load.py --jmeter C:/private/apache-jmeter-5.6.3/bin/jmeter.bat --java C:/private/java/bin/java.exe --output-dir test-results/issue40-load/NEW
```

Defaults execute both 600-second scenarios. `--seconds 8 --scenario baseline`
is only a smoke check and is explicitly classified `SMOKE_NOT_ACCEPTANCE`.
The wrapper launches the JMeter JAR directly and removes transient secret
properties in a `finally` context; raw results remain ignored.

The recovery runner requires installed MySQL 8.4 tools and Windows Task
Scheduler. A new demonstration refuses an existing task of the same name and
uses a previously absent private directory outside the repository:

```powershell
python scripts/part3/run_issue40_recovery.py --private-dir C:/private/issue40-NEW
```

This registers and observes a natural sandbox daily trigger, restores and
checks it, then replaces only that owned task with a live read-only daily backup
and observes its natural trigger. It leaves the live daily task in place. The
`--resume-private-dir` mode rechecks a preserved sandbox and its original scheduled
backup without replacing the existing live task; it preserves earlier results.
The installed task already exists on the execution machine, so a new initial
run will safely refuse it. Review/sanitize evidence before publishing; never
commit credentials, raw properties/logs or SQL dumps.

## Historical first checkpoint

Owner: Devansh Gupta (`DevaOnL`). Date: 2 November 2026.
Scope: [HMS-18 / #40](https://github.com/Sreeharsha2240/hostel-management-system/issues/40)
only. This contributes owned execution evidence to the [Part 3 plan](../../../PART3.md);
the Unit, System Validation and Coverage reports remain their assigned work.

### Status and tested source

**Candidate checkpoint; final case/build acceptance is pending.** The updated
case register in #37 and PR #36 were still awaiting team acceptance at this run.
The observations below do not close #40 or establish the full Test Plan exit
criteria. No other contributor's execution issue or coverage issue #42 was
completed by this checkpoint.

The focused MySQL regression run tested candidate `c991e8827c97cfcb469e2868d152c544429a9d32`;
the browser run used `33491e3aa92f16781f3161733d2daadc510961d6`. Existing application,
test and template source was identical between those revisions. Both runs
truthfully record a dirty working tree while the documentation/manual harness
was being prepared. The browser evidence records SHA-256 hashes for the exact
three harness files used; these matched the files published at that checkpoint
(`265d24f`). The later wrapper guards change its hash, recorded in the fresh
browser evidence. Preserve these facts
and rerun against the eventual accepted submission revision.

Environment: Windows; Python 3.14.7, Django 5.2.18, MySQL 8.4.9, Microsoft Edge
156.0.4314.58, Node.js 26.8.1 and Playwright 1.64.1. The browser harness uses a
threaded Django test server on loopback with a fresh disposable `test_hms`, real
HTTP requests and real commits, outside coverage instrumentation. This is a local
test-host observation, not deployed/concurrent-load acceptance.

### Evidence and original case mapping

- [Focused regression results](candidate-regressions.json): 60 unique methods,
  all passed, no errors/failures/skips. Includes MySQL concurrency/constraints,
  allocation and audit rollback, payment adjustments/immutability/PDF details,
  report exports and the integrated staff-to-student journey.
- [Browser/HTTP results](candidate-browser.json): real form actions, rendered
  rejection reasons, intermediate bed states, preserved history, PDF fields
  including date, downloaded CSVs, independent MySQL reconciliation, twenty
  allocation timings and overlapping conflict requests. Fixture data is synthetic.

| Original case | Candidate observation | Remaining acceptance work |
|---|---|---|
| TC-ALC-01 | Browser allocated an active male student to an available Boys-hostel bed, stored today's date, displayed confirmation and showed Occupied | Reviewed-case/final-build rerun |
| TC-ALC-02 | Another student's stale form was rejected with the occupied-bed reason; no duplicate allocation | Reviewed-case/final-build rerun |
| TC-ALC-03 | A student's second stale allocation form was rejected; original allocation ID/bed remained unchanged | Reviewed-case/final-build rerun |
| TC-ALC-04 | Female student/Boys hostel submission showed the gender-mismatch reason and wrote no allocation | Reviewed-case/final-build rerun |
| TC-ALC-05 | Browser transfer made the old bed Available and new bed Occupied, preserving history. Companion forced-save-failure regression passed with rollback | Browser JSON retains PARTIAL for its missing fault-injection step; the companion method below supplies that separate evidence. Reviewed-case/final-build rerun remains |
| TC-ALC-06 | Release stored the vacate date, made both released beds Available and displayed ordered historical rows | Reviewed-case/final-build rerun |
| TC-PAY-01 | Recorded INR 5,000 UPI payment; zero/negative submissions reached server validation without extra receipts; sequential numbering and downloaded PDF receipt fields matched | Reviewed-case/final-build rerun |
| TC-PAY-02 | Browser displayed Pending, Partial and Paid; final fee/paid/due values were INR 10,000 / 10,000 / 0 | Reviewed-case/final-build rerun |
| TC-RPT-01 | Filtered both reports and downloaded CSVs; HTML/CSV matched independently queried MySQL counts, room fees and payments | Reviewed-case/final-build rerun |
| TC-PERF-01 | NOT RUN: 50-user, ten-minute normal workload is outstanding | JMeter login/search/bed workload; at least 95% within two seconds and no errors |
| TC-PERF-02 | Twenty real committed HTTP allocations passed the under-three-second target; overlapping same-bed requests returned one 201 and one 409, with one active database row | Reviewed-case/final-build rerun; do not generalize local timings to 50-user load |
| TC-PERF-03 | NOT RUN: full 5,000-student/2,000-bed load execution is outstanding | Seed isolated synthetic volume and repeat the planned load/search measurement |
| TC-OPS-01 | NOT RUN: daily scheduling and populated separate-database recovery were not executed here | Demonstrate actual daily job, last-24-hour backup, separate populated restore and completeness/loss criteria |

The ALC-05 companion is
`allocations.test_workflows.AllocationWorkflowTests.test_transfer_failure_rolls_back_both_beds_and_history`.
Its passing result is in `candidate-regressions.json`; it deliberately fails the
target-bed save in a separate fixture and verifies the original active allocation,
both bed states, history count and absence of a committed transfer audit event.
The browser's own PARTIAL observation is preserved rather than rewritten.

Allocation timing: 20 samples, minimum **25.41 ms**, median **27.94 ms**, maximum
**36.35 ms**. Timing begins before each real HTTP POST and ends after its response
body; MySQL rows are checked independently after commits. Conflict-request client
intervals overlapped and the persisted bed had exactly one active allocation.
Raw samples, intervals and versions are in the browser JSON.

For the report fixture, the selected hostel had five beds: one occupied, three
available, one under maintenance, and 20.00% occupancy. The two student rows
showed one fully paid student and one pending resident. Other timing fixtures
used a separate hostel so they did not contaminate this filter's totals.

### Reproduce serially

Follow the repository's documented MySQL setup. Run only one Django/MySQL suite
at a time; do not point this harness at an application or recovery database.
The wrapper accepts only the documented MySQL `hms` configuration and lets
Django create/drop `test_hms`; custom or mirrored test databases are rejected.
The harness uses only synthetic fixtures and transmits ephemeral credentials to
the local browser process through stdin, without saving them in evidence.

Focused regression command:

```sh
python manage.py test allocations payments reports hms.test_system_journey --noinput --testrunner=xmlrunner.extra.djangotestrunner.XMLTestRunner
```

Set `HMS_TEST_OUTPUT_DIR` to a new ignored `test-results/` directory when saving
JUnit output. Inspect the exit status and XML totals; do not copy historical counts.

The explicit browser runner additionally needs Node.js, installed Microsoft Edge
and optional Playwright. It is intentionally separate from the normal CI suite.
For example, from the repository root in PowerShell:

```powershell
npm install --prefix .tmp/issue40-browser playwright@1.64.1
$env:NODE_PATH = (Resolve-Path .tmp/issue40-browser/node_modules).Path
python scripts/part3/run_issue40_browser.py
```

An already-installed private Playwright package may supply `NODE_PATH`; that was
used for this checkpoint. Dependencies stay outside tracked source. Each browser
run requires a fresh output directory and saves `browser-results.json` under
ignored `test-results/issue40-browser/`. Preserve failure console logs if a run
stops before producing JSON. Review and sanitize new evidence before publishing.

Before final acceptance, obtain the reviewed owned-case batch and accepted build,
complete PERF-01/PERF-03/OPS-01, log owned defects and retest, and supply the final
execution results to #38 and #37. MySQL client/dump binaries are installed locally;
the recovery target's permissions and a real daily scheduling arrangement still
need confirmation. No backup/scheduling pass is inferred from that preflight.
