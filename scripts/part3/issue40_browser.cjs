// Candidate-build execution for HMS-18 / issue #40. Playwright is an optional
// verification tool, supplied through NODE_PATH; it is not a runtime dependency.
const assert = require('node:assert/strict');
const { performance } = require('node:perf_hooks');
const { chromium } = require('playwright');

let phase = 'configuration';
const sensitive = new Set();

async function run() {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const config = JSON.parse(input);
  sensitive.add(config.password);
  const origin = new URL(config.base_url);
  assert.equal(origin.protocol, 'http:');
  assert(['localhost', '127.0.0.1'].includes(origin.hostname));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  const observations = [];
  const bedSnapshots = [];
  const absolute = path => new URL(path, config.base_url).href;
  const observe = (id, actual, status = 'PASS') => observations.push({ id, status, actual });
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.name));
    context.on('response', response => {
      if (response.status() >= 500) errors.push(`HTTP ${response.status()}`);
    });
    async function login(target, username) {
      await target.goto(absolute('/login/'));
      await target.getByLabel('Username', { exact: true }).fill(username);
      await target.getByLabel('Password', { exact: true }).fill(config.password);
      await Promise.all([
        target.waitForURL(absolute('/dashboard/')),
        target.getByRole('button', { name: 'Sign in', exact: true }).click(),
      ]);
    }
    async function createForm(target, student, bed) {
      await target.goto(absolute('/allocations/create/'));
      await target.locator('#id_student').selectOption(String(student));
      await target.locator('#id_bed').selectOption(String(bed));
      await target.locator('#id_allocated_on').fill(config.today);
    }
    async function confirm(target, path, redirect) {
      const pending = target.waitForResponse(response =>
        response.request().method() === 'POST' && new URL(response.url()).pathname === path);
      await target.getByRole('button', { name: 'Confirm', exact: true }).click();
      const response = await pending;
      assert.equal(response.status(), redirect ? 302 : 200);
      if (redirect) await target.waitForURL(absolute('/allocations/'));
      return response;
    }
    async function allocations() {
      const response = await context.request.get(absolute(`/allocations/?q=${config.student.student_id}`), {
        headers: { Accept: 'application/json' },
      });
      assert.equal(response.status(), 200);
      return (await response.json()).results;
    }
    async function bedStates(checkpoint, expected) {
      const bedPage = await context.newPage();
      try {
        const response = await bedPage.goto(absolute(`/beds/?hostel=${config.hostel_id}&status=`));
        assert.equal(response.status(), 200);
        const rows = await bedPage.locator('main tbody tr').evaluateAll(nodes =>
          nodes.map(node => [...node.querySelectorAll('td')].map(cell => cell.textContent.trim())));
        const actual = {};
        for (const [label, status] of Object.entries(expected)) {
          const row = rows.find(cells => cells[0] === label);
          assert(row, `Bed ${label} is present`);
          assert.equal(row[5], status);
          actual[label] = row[5];
        }
        bedSnapshots.push({ checkpoint, states: actual });
      } finally {
        await bedPage.close();
      }
    }
    async function paymentStatus(expected) {
      await page.goto(absolute(`/students/${config.student.pk}/payment-status/`));
      const actual = await page.locator('main dd').last().innerText();
      assert.equal(actual, expected);
      return actual;
    }
    async function pay(amount, reference, valid) {
      await page.goto(absolute('/payments/create/'));
      await page.locator('#id_student').selectOption(String(config.student.pk));
      await page.locator('#id_amount').fill(amount);
      await page.locator('#id_date').fill(config.today);
      await page.locator('#id_mode').selectOption('UPI');
      await page.locator('#id_reference').fill(reference);
      // Invalid amounts must reach server validation rather than browser min=.
      if (!valid) await page.locator('main form').evaluate(form => { form.noValidate = true; });
      const pending = page.waitForResponse(response =>
        response.request().method() === 'POST' && new URL(response.url()).pathname === '/payments/create/');
      await page.getByRole('button', { name: 'Record payment', exact: true }).click();
      assert.equal((await pending).status(), valid ? 302 : 200);
      if (valid) {
        await page.getByRole('heading', { name: 'Payment receipt', exact: true }).waitFor();
        const number = await page.locator('main h2').innerText();
        assert.match(number, /^R\d{11}$/);
        return number;
      }
      assert.equal(await page.locator('#id_amount').getAttribute('aria-invalid'), 'true');
      assert.match(await page.getByRole('alert').innerText(), /greater than or equal to 0\.01/);
      return null;
    }
    async function report(path, heading) {
      await page.goto(absolute(path));
      await page.locator('#hostel').selectOption(String(config.hostel_id));
      await Promise.all([
        page.waitForURL(url => url.pathname === path && url.searchParams.get('hostel') === String(config.hostel_id)),
        page.getByRole('button', { name: 'View report', exact: true }).click(),
      ]);
      await page.getByRole('heading', { name: heading, exact: true }).waitFor();
      const rows = await page.locator('main tbody tr').evaluateAll(nodes =>
        nodes.map(node => [...node.querySelectorAll('td')].map(cell => cell.textContent.trim())));
      const downloadPromise = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Download CSV', exact: true }).click();
      const download = await downloadPromise;
      assert.equal(await download.failure(), null);
      const stream = await download.createReadStream();
      const chunks = [];
      for await (const chunk of stream) chunks.push(chunk);
      return { html_rows: rows, csv: Buffer.concat(chunks).toString('utf8') };
    }

    phase = 'staff login and stale allocation forms';
    await login(page, config.warden);
    for (const cookie of await context.cookies()) sensitive.add(cookie.value);
    // Keep real pre-existing form selections to exercise server-side race guards.
    const occupiedPage = await context.newPage();
    const duplicatePage = await context.newPage();
    await createForm(occupiedPage, config.other_student_pk, config.old_bed);
    await createForm(duplicatePage, config.student.pk, config.target_bed);

    phase = 'TC-ALC-01';
    await createForm(page, config.student.pk, config.old_bed);
    await confirm(page, '/allocations/create/', true);
    assert.match(await page.getByRole('status').innerText(), /allocated to/);
    let history = await allocations();
    assert.equal(history.length, 1);
    assert.equal(history[0].bed_id, config.old_bed);
    assert.equal(history[0].allocated_on, config.today);
    const original = history[0].allocation_id;
    await bedStates('after allocation', { [config.old_bed_label]: 'Occupied', [config.target_bed_label]: 'Available' });
    observe(phase, 'Browser form saved allocation/date and displayed confirmation; a separate bed-list page showed Occupied after commit.');

    phase = 'TC-ALC-02';
    await confirm(occupiedPage, '/allocations/create/', false);
    assert.match(await occupiedPage.getByRole('alert').innerText(), /bed already has an active allocation/);
    assert.equal((await allocations()).length, 1);
    observe(phase, 'A different student using a stale form was rejected with the occupied-bed reason; no duplicate allocation.');
    await occupiedPage.close();

    phase = 'TC-ALC-03';
    await confirm(duplicatePage, '/allocations/create/', false);
    assert.match(await duplicatePage.getByRole('alert').innerText(), /student already has an active allocation/);
    history = await allocations();
    assert.equal(history.length, 1);
    assert.equal(history[0].allocation_id, original);
    observe(phase, 'Second allocation for the same student was rejected; original ID and bed unchanged.');
    await duplicatePage.close();

    phase = 'TC-ALC-04';
    await createForm(page, config.female_student_pk, config.target_bed);
    await confirm(page, '/allocations/create/', false);
    assert.match(await page.getByRole('alert').innerText(), /gender does not match the hostel type/);
    observe(phase, 'Browser rejected female student / Boys hostel with a gender mismatch reason; MySQL verifies no write.');

    phase = 'TC-ALC-05';
    await page.goto(absolute(`/allocations/${original}/transfer/`));
    await page.locator('#id_new_bed').selectOption(String(config.target_bed));
    await confirm(page, `/allocations/${original}/transfer/`, true);
    assert.match(await page.getByRole('status').innerText(), /history is preserved/);
    history = await allocations();
    assert.equal(history.length, 2);
    const successor = history.find(row => row.status === 'Active');
    assert.equal(successor.bed_id, config.target_bed);
    assert.notEqual(successor.allocation_id, original);
    assert.equal(history.find(row => row.allocation_id === original).status, 'Completed');
    await bedStates('after transfer', { [config.old_bed_label]: 'Available', [config.target_bed_label]: 'Occupied' });
    observe(phase, 'Browser transfer preserved original and created successor; injected storage-failure rollback must be verified by the separate regression suite.', 'PARTIAL');

    phase = 'TC-ALC-06';
    await page.goto(absolute(`/allocations/${successor.allocation_id}/release/`));
    await page.locator('#id_vacate_date').fill(config.today);
    await confirm(page, `/allocations/${successor.allocation_id}/release/`, true);
    assert.equal(await page.getByRole('status').innerText(), 'Allocation released.');
    await page.goto(absolute(`/students/${config.student.pk}/allocations/`));
    const historyRows = await page.locator('main tbody tr').evaluateAll(nodes =>
      nodes.map(node => [...node.querySelectorAll('td')].map(cell => cell.textContent.trim())));
    assert.deepEqual(historyRows.map(row => row[4]), [config.target_bed_label, config.old_bed_label]);
    assert(historyRows.every(row => row[7] === 'Completed' && row[6] !== '—'));
    history = await allocations();
    assert.deepEqual(history.map(row => row.allocation_id), [successor.allocation_id, original]);
    assert(history.every(row => row.vacated_on === config.today && row.status === 'Completed'));
    await bedStates('after release', { [config.old_bed_label]: 'Available', [config.target_bed_label]: 'Available' });
    observe(phase, 'Browser release stored vacate date and showed newest-first preserved history; both released beds are checked in MySQL.');

    phase = 'TC-PAY-02 pending';
    const states = [await paymentStatus('Pending')];
    phase = 'TC-PAY-01';
    const firstReceipt = await pay('5000.00', 'PART340A', true);
    const pdfUrl = await page.getByRole('link', { name: 'Download PDF', exact: true }).getAttribute('href');
    const pdf = await context.request.get(absolute(pdfUrl));
    assert.equal(pdf.status(), 200);
    assert.match(pdf.headers()['content-type'], /^application\/pdf/);
    const pdfBase64 = (await pdf.body()).toString('base64');
    await pay('0', 'INVALID0', false);
    await pay('-1', 'INVALID1', false);
    const payments = await context.request.get(absolute('/payments/'), { headers: { Accept: 'application/json' } });
    assert.equal((await payments.json()).total, 1);
    observe(phase, 'Browser recorded INR 5000 UPI payment and downloaded PDF; zero/negative submissions reached server errors without additional receipts.');

    phase = 'TC-PAY-02';
    states.push(await paymentStatus('Partial'));
    const secondReceipt = await pay('5000.00', 'PART340B', true);
    assert.equal(BigInt(secondReceipt.slice(1)), BigInt(firstReceipt.slice(1)) + 1n);
    states.push(await paymentStatus('Paid'));
    observe(phase, `Browser payment statuses: ${states.join(' -> ')}; final paid INR 10000, due INR 0 checked in MySQL.`);

    phase = 'TC-RPT-01';
    const reports = {
      occupancy: await report('/reports/occupancy/', 'Occupancy'),
      payment: await report('/reports/payment-status/', 'Payment status'),
    };
    observe(phase, 'Browser filtered both reports by hostel and used each Download CSV button; Python independently reconciles HTML, CSV and MySQL values.');

    phase = 'TC-PERF-02 twenty committed HTTP allocations';
    const cookies = await context.cookies(config.base_url);
    const csrf = cookies.find(cookie => cookie.name === 'csrftoken').value;
    sensitive.add(csrf);
    const headers = { Accept: 'application/json', 'X-CSRFToken': csrf, Origin: origin.origin };
    const timings = [];
    for (const fixture of config.timed_allocations) {
      const started = performance.now();
      const response = await context.request.post(absolute('/allocations/'), {
        headers,
        data: { student_id: fixture.student_id, bed_id: fixture.bed_id, allocated_on: config.today },
      });
      const data = await response.json();
      const milliseconds = performance.now() - started;
      assert.equal(response.status(), 201);
      assert.equal(data.bed_id, fixture.bed_id);
      timings.push({ allocation_id: data.allocation_id, student_id: fixture.student_id, bed_id: fixture.bed_id, milliseconds });
    }
    phase = 'TC-PERF-02 concurrent same-bed HTTP requests';
    const conflictClock = performance.now();
    const conflict = await Promise.all(config.conflict_students.map(async student_id => {
      const started = performance.now() - conflictClock;
      const response = await context.request.post(absolute('/allocations/'), {
        headers, data: { student_id, bed_id: config.conflict_bed, allocated_on: config.today },
      });
      await response.body();
      return { student_id, status: response.status(), started_ms: started, completed_ms: performance.now() - conflictClock };
    }));
    const conflictStatuses = conflict.map(row => row.status).sort();
    assert.deepEqual(conflictStatuses, [201, 409]);
    const conflictOverlap = Math.max(...conflict.map(row => row.started_ms)) < Math.min(...conflict.map(row => row.completed_ms));
    assert(conflictOverlap, 'The two client request intervals must overlap');
    const allocationTimingsPassed = timings.every(row => row.milliseconds < 3000);
    observe('TC-PERF-02', '20 successful real HTTP allocations with durable commits; overlapping client same-bed requests returned one 201 and one 409; MySQL verifies a single winner.', allocationTimingsPassed ? 'PASS' : 'FAIL');

    phase = 'student allocation/payment integration';
    const studentContext = await browser.newContext();
    const studentPage = await studentContext.newPage();
    await login(studentPage, config.student_login);
    await studentPage.goto(absolute('/my-records/'));
    const studentContent = await studentPage.locator('main').innerText();
    assert(studentContent.includes(firstReceipt) && studentContent.includes(secondReceipt));
    assert(studentContent.includes(config.hostel_name));
    assert(studentContent.includes('Paid'));
    await studentContext.close();
    assert.deepEqual(errors, []);
    await context.close();
    process.stdout.write(JSON.stringify({
      scope: 'HMS-18 / issue #40 candidate-build execution; final acceptance requires reviewed cases and the accepted revision',
      browser: 'Microsoft Edge', browser_version: browser.version(),
      node_version: process.version, playwright_version: require('playwright/package.json').version,
      observations, allocation_ids: [original, successor.allocation_id],
      receipts: [firstReceipt, secondReceipt], receipt_pdf_base64: pdfBase64,
      reports, payment_states: states, allocation_timings: timings,
      concurrency_statuses: conflictStatuses, concurrency_requests: conflict,
      concurrency_client_intervals_overlap: conflictOverlap, allocation_timings_passed: allocationTimingsPassed,
      bed_state_snapshots: bedSnapshots,
      student_allocation_payment_integration: true, browser_errors: errors,
    }) + '\n');
  } finally {
    await browser.close();
  }
}

run().catch(error => {
  let message = String(error.message).split('\n')[0];
  for (const secret of sensitive) if (secret) message = message.split(secret).join('[redacted]');
  process.stderr.write(JSON.stringify({ phase, error: error.name, message }) + '\n');
  process.exitCode = 1;
});
