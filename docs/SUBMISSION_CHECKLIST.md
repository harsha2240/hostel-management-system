# HMS submission checklist

This checklist covers the whole Team 3 submission: planning, design,
implementation, verification and packaging. Historical audit results are
identified below; use the checks on the final submission commit for current
automated evidence. Check the course rubric for required slides, live demo,
signatures and naming; those requirements cannot be inferred from the source
repository.

## Planning and team records

- [x] Sprint schedule and estimated backlog are documented in `HMS_Part1_Sprint_Backlog.docx`.
- [x] Member responsibilities and test ownership are documented in `HMS_Part1_Work_Distribution.docx`.
- [x] Sprint implementation notes are available in `docs/SPRINT1_TESTING.md` and `docs/SPRINT2.md`.
- [x] Added a two-sprint burndown reconstruction: `docs/BURNDOWN.md`, `docs/burndown.svg` and `docs/BURNDOWN_DATA.csv`. It uses dated merge/closure history and backlog story points, not invented daily board data. The planned 24 Sprint 2 points are recorded as closed by 28 October. HMS-14 / issue #32 was opened on 27 October and was In Progress at the 29 October snapshot, with no estimate or Sprint field, so it is separate follow-up scope. Do not move it to Done just to complete the chart.
- [ ] Confirm the instructor accepts a merge-history reconstruction. If daily board history is required, export it and replace this chart with verified daily values. Confirm whether to estimate/assign HMS-14 to a sprint as an explicit scope change.

## Requirements and design package

- [x] SRS, SAD and Test Plan are present as DOCX files.
- [x] Five PDF copies are present in `pdf/`; compare them to their DOCX sources after any later edits.
- [x] `Design_README.md` and four UML diagrams are present in rendered PNG and editable Mermaid formats.
- [x] The Test Plan contains 33 test cases and an RTM, as listed in README.

## Implementation and Git

- [x] Django source, migrations, dependency manifests, `.env.example`, setup guide and CI workflow are present.
- [x] Bed availability is paginated at 50 rows; a regression test covers page size, total count and page two.
- [x] Pagination and audit fixes from `bf70a66` were included in merged PR #35.
- [ ] Confirm the final submission revision has passed CI and required teammate review. A local run does not replace remote CI or review.
- [ ] Confirm GitHub issue states and owners match the completed work. The Part 1 backlog is a planning artifact, not a current board export.
- [x] Added `.tmp/` to `.gitignore`; keep generated credentials, database dumps, JMeter results and downloaded tools out of the submission.

## Verification evidence

- [ ] Run `python scripts/run_checks.py` on the final revision and inspect all gates, test totals and coverage in `test-results/<run>/run.json`. CI runs the same command on MySQL 8.4 with Python 3.11 and 3.14; download the matching commit's `hms-test-evidence-*` artifacts.
- [x] Historical 29 October SQLite-compatible audit: 154 passed, 0 failures/errors; 163 discovered, with 9 MySQL-specific tests excluded. See `test-evidence/E2E_FINAL_TESTS.txt`. This is not the current MySQL verification result.
- [x] Historical CI run #29 passed MySQL 8.4 on Python 3.11 and 3.14; that run predates pagination. Board/issue status lists HMS-13 Done/closed, but PR #33 review explicitly called it partial and asked to keep it open until populated recovery and concurrent performance evidence. The later local audit supplied a populated restore and 50-user run, but the performance target was exceeded and the post-pagination comparison was blocked.
- [ ] Resolve the HMS-13 evidence/acceptance discrepancy with the team before final acceptance; later unit/integration CI does not establish concurrent load performance.
- [x] Before pagination, a 50-user/10-minute-peak local JMeter run completed with no failed samples. The 2,000-bed listing averaged 12.2 seconds (p95 29.6 seconds, maximum 46.8 seconds), which prompted pagination.
- [ ] Repeat the JMeter smoke/full load after pagination. A post-change attempt was blocked by loopback socket access and is recorded as invalid, not a pass.
- [x] A populated local MySQL dump restore to a separate database had matching table counts; a manual timestamped backup ZIP passed integrity validation.
- [ ] If daily backup automation is required, arrange a permitted Task Scheduler job and capture a fresh backup/restore record; local scheduling was blocked by Windows task/CIM permissions.
- [ ] If security scanning/live deployment is required, run ZAP and verify TLS/Secure cookies against the actual demo host. Django production-profile settings validation alone is not live deployment evidence.
- [ ] Walk through Admin, Warden and Student accounts on the final demo host and save only rubric-requested screenshots. Local automated checks do not establish browser/OS compatibility on that host.

## Final packaging

- [ ] Check Git status and include only source, required documents, diagrams and evidence. Exclude `.tmp/`, `.env`, local databases, passwords, backups and raw load files.
- [ ] Follow the README setup from a clean environment and verify demo accounts are fresh, synthetic and distributed only through the instructor-approved channel.
- [ ] Check DOCX/PDF pairs, filenames, team names/IDs, page rendering, links, signatures and rubric-specific cover fields.
- [ ] Confirm whether slides, a demo video or live URL are required. No slide deck is present in this repository.
