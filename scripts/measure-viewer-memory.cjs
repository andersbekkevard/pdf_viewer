#!/usr/bin/env node
/*
 * Sequential physical-footprint benchmark for one cached viewer entry.
 *
 * Public report seam: `summarizeSamples({ canonical, original_light,
 * geometry_light })`.  The live seam is a fresh Chromium browser per trial:
 * its process tree must contain exactly one fresh `--type=renderer` process.
 * That renderer alone is sampled with macOS `footprint -p PID -f bytes` after
 * the identical viewport/load/native-find/settle journey.
 */
'use strict';

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
let chromium;

const ROOT = path.resolve(__dirname, '..');
const DEFAULT_HASH = '3b592f92ab8c17e5';
const DEFAULT_CANONICAL = 'AlgDat-Pensumbok.html';
const REPRESENTATIONS = [
  { key: 'canonical', filename: (canonical) => canonical, expectedTextMode: null },
  { key: 'original_light', filename: (canonical) => `${canonical.slice(0, -5)}.light.html`, expectedTextMode: 'original' },
  { key: 'geometry_light', filename: (canonical) => `${canonical.slice(0, -5)}.geometry.light.html`, expectedTextMode: 'geometry' },
  { key: 'paint_safe', filename: (canonical) => `${canonical.slice(0, -5)}.paint-safe.light.html`, expectedTextMode: 'paint-safe' },
];
const SUMMARY_REPRESENTATIONS = REPRESENTATIONS.slice(0, 3);
const VIEWPORT = { width: 1600, height: 1200 };
const FIND_TERM = 'Hopcroft-Karp';
const FIND_PAGE = 918;
const FIND_OCCURRENCE_AT_PAGE = 6;
const FIVE_GIB = 5 * 1024 ** 3;
const EIGHT_GIB = 8 * 1024 ** 3;

function usage() {
  console.error(`usage: measure-viewer-memory.cjs [<hash> <canonical.html>] [options]

Measures the AlgDat canonical, conservative original-text light, and geometry
light representations sequentially. Defaults: ${DEFAULT_HASH} ${DEFAULT_CANONICAL}

options:
  --trials <n>       fresh browser trials per representation (default: 3)
  --representations <names>  comma-separated subset for bounded diagnosis
  --journey-timeout-ms <ms>  maximum load/find readiness time (default: 120000)
  --settle-ms <ms>   post-find settle time before sampling (default: 5000)
  --output <dir>     artifact directory (default: output/playwright/viewer-memory/<timestamp>)
  --headless         use headless Chromium (headed is the physical-use default)
  -h, --help         show this help
`);
}

function timestamp() {
  return new Date().toISOString().replace(/[:.]/g, '-');
}

function parsePositiveInteger(value, option) {
  if (!/^\d+$/.test(String(value)) || Number(value) < 1) throw new Error(`${option} must be a positive integer`);
  return Number(value);
}

function parseArgs(argv) {
  const positional = [];
  const options = { trials: 3, representations: SUMMARY_REPRESENTATIONS.map(({ key }) => key), journeyTimeoutMs: 120000, settleMs: 5000, output: null, headless: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const take = (name) => {
      if (!argv[index + 1]) throw new Error(`missing value for ${name}`);
      return argv[++index];
    };
    if (arg === '--trials') options.trials = parsePositiveInteger(take(arg), arg);
    else if (arg.startsWith('--trials=')) options.trials = parsePositiveInteger(arg.slice(9), '--trials');
    else if (arg === '--representations') options.representations = String(take(arg)).split(',').filter(Boolean);
    else if (arg.startsWith('--representations=')) options.representations = arg.slice(18).split(',').filter(Boolean);
    else if (arg === '--journey-timeout-ms') options.journeyTimeoutMs = parsePositiveInteger(take(arg), arg);
    else if (arg.startsWith('--journey-timeout-ms=')) options.journeyTimeoutMs = parsePositiveInteger(arg.slice(21), '--journey-timeout-ms');
    else if (arg === '--settle-ms') options.settleMs = parsePositiveInteger(take(arg), arg);
    else if (arg.startsWith('--settle-ms=')) options.settleMs = parsePositiveInteger(arg.slice(12), '--settle-ms');
    else if (arg === '--output') options.output = take(arg);
    else if (arg.startsWith('--output=')) options.output = arg.slice(9);
    else if (arg === '--headless') options.headless = true;
    else if (arg === '--help' || arg === '-h') return { help: true };
    else if (arg.startsWith('-')) throw new Error(`unknown option: ${arg}`);
    else positional.push(arg);
  }
  if (positional.length !== 0 && positional.length !== 2) throw new Error('supply both <hash> and <canonical.html>, or neither');
  const hash = positional[0] || DEFAULT_HASH;
  const canonical = positional[1] || DEFAULT_CANONICAL;
  if (!/^[a-f0-9]{16,}$/i.test(hash)) throw new Error(`invalid cache hash: ${hash}`);
  if (!canonical.endsWith('.html') || canonical.endsWith('.light.html') || /[\\/]/.test(canonical)) {
    throw new Error(`canonical filename must be a plain *.html name: ${canonical}`);
  }
  if (!options.representations.length || options.representations.some((key) => !REPRESENTATIONS.some((representation) => representation.key === key))) {
    throw new Error(`--representations must use: ${REPRESENTATIONS.map(({ key }) => key).join(',')}`);
  }
  return { ...options, hash, canonical };
}

function processTable() {
  const result = spawnSync('ps', ['-axo', 'pid=,ppid=,rss=,command='], { encoding: 'utf8' });
  if (result.error || result.status !== 0) throw new Error(`ps failed: ${result.error?.message || result.stderr || result.status}`);
  return result.stdout.split('\n').map((line) => {
    const match = line.trim().match(/^(\d+)\s+(\d+)\s+(\d+)\s+(.*)$/);
    return match ? {
      pid: Number(match[1]), ppid: Number(match[2]), rss_kib: Number(match[3]), command: match[4],
    } : null;
  }).filter(Boolean);
}

function rendererProcesses(table = processTable()) {
  return table.filter((process) => /(?:^|\s)--type=renderer(?:\s|$)/.test(process.command));
}

function descendants(rootPid, table = processTable()) {
  const children = new Map();
  for (const process of table) {
    const list = children.get(process.ppid) || [];
    list.push(process);
    children.set(process.ppid, list);
  }
  const discovered = [];
  const pending = [rootPid];
  const visited = new Set(pending);
  while (pending.length) {
    const parent = pending.shift();
    for (const child of children.get(parent) || []) {
      if (visited.has(child.pid)) continue;
      visited.add(child.pid);
      discovered.push(child);
      pending.push(child.pid);
    }
  }
  return discovered;
}

async function identifyFreshRenderer(browserPid, preexistingPids) {
  let last = [];
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const table = processTable();
    last = descendants(browserPid, table).filter((process) =>
      /(?:^|\s)--type=renderer(?:\s|$)/.test(process.command));
    const fresh = last.filter((process) => !preexistingPids.has(process.pid)).sort((left, right) => right.rss_kib - left.rss_kib);
    // Chromium commonly keeps a tiny spare renderer alongside the page
    // renderer. The loaded page is deterministically the largest fresh
    // renderer after the full journey; retain all candidates in the report.
    if (fresh.length > 0 && (fresh.length === 1 || fresh[0].rss_kib > fresh[1].rss_kib)) {
      return { selected: fresh[0], candidates: fresh };
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  const seen = last.map((process) => `${process.pid} rss=${process.rss_kib}KiB: ${process.command}`).join('\n');
  throw new Error(`could not identify a single largest fresh page renderer below browser PID ${browserPid}; candidates=${last.length}\n${seen}`);
}

function footprint(pid) {
  const result = spawnSync('footprint', ['-p', String(pid), '-f', 'bytes'], { encoding: 'utf8' });
  const output = `${result.stdout || ''}${result.stderr || ''}`;
  if (result.error || result.status !== 0) throw new Error(`footprint failed for renderer ${pid}: ${result.error?.message || output.trim()}`);
  const match = output.match(/^\s*phys_footprint:\s*(\d+)\s+B\s*$/m);
  if (!match) throw new Error(`footprint did not report phys_footprint for renderer ${pid}: ${output.trim()}`);
  return { bytes: Number(match[1]), raw: output };
}

function median(numbers) {
  const sorted = [...numbers].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function threshold(bytes, limit) {
  return bytes <= limit ? 'fits' : 'does_not_fit';
}

function highThreshold(bytes, limit) {
  return bytes >= limit ? 'exceeds' : 'below';
}

function gib(bytes) {
  return Number((bytes / 1024 ** 3).toFixed(2));
}

function summarizeSamples(samples) {
  const medians = Object.fromEntries(SUMMARY_REPRESENTATIONS.map(({ key }) => {
    const values = samples[key];
    if (!Array.isArray(values) || values.length === 0 || values.some((value) => !Number.isFinite(value) || value < 0)) {
      throw new Error(`missing valid samples for ${key}`);
    }
    return [key, median(values)];
  }));
  const ratios = Object.fromEntries(SUMMARY_REPRESENTATIONS.map(({ key }) => [
    key,
    Number((medians[key] / medians.canonical).toFixed(4)),
  ]));
  const thresholds = Object.fromEntries(SUMMARY_REPRESENTATIONS.map(({ key }) => [key, {
    '5_gib': threshold(medians[key], FIVE_GIB),
    '8_gib': highThreshold(medians[key], EIGHT_GIB),
  }]));
  const representation = SUMMARY_REPRESENTATIONS.map(({ key }) => key).reduce((best, key) =>
    medians[key] < medians[best] ? key : best, 'canonical');
  const bestBytes = medians[representation];
  const summary = bestBytes <= FIVE_GIB
    ? `${representation} is the lowest median and fits the <=5 GiB target (${gib(bestBytes)} GiB).`
    : `No representation fits the <=5 GiB target; ${representation} is lowest at ${gib(bestBytes)} GiB${bestBytes >= EIGHT_GIB ? ' and exceeds >=8 GiB.' : '.'}`;
  return {
    medians_bytes: medians,
    medians_gib: Object.fromEntries(Object.entries(medians).map(([key, value]) => [key, gib(value)])),
    ratios_to_canonical: ratios,
    thresholds,
    recommendation: { representation, summary },
  };
}

function writeJson(filename, data) {
  fs.writeFileSync(filename, `${JSON.stringify(data, null, 2)}\n`);
}

function conciseSummary(summary) {
  const lines = ['Renderer physical footprint (median, fresh Chromium renderer per sequential trial)'];
  for (const { key } of SUMMARY_REPRESENTATIONS) {
    lines.push(`${key}: ${summary.medians_gib[key]} GiB (${(summary.ratios_to_canonical[key] * 100).toFixed(1)}% of canonical; <=5 GiB ${summary.thresholds[key]['5_gib']}; >=8 GiB ${summary.thresholds[key]['8_gib']})`);
  }
  lines.push(`Recommendation: ${summary.recommendation.summary}`);
  return `${lines.join('\n')}\n`;
}

function deadline(promise, milliseconds, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} exceeded ${milliseconds} ms`)), milliseconds);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function settleJourney(page, representation, url, settleMs, journeyTimeoutMs) {
  // Playwright's protocol timeout can itself stall when Chromium's renderer is
  // unresponsive. Keep an independent Node timer so the trial remains bounded.
  const response = await deadline(
    page.goto(url, { waitUntil: 'networkidle', timeout: journeyTimeoutMs }),
    journeyTimeoutMs,
    `load/find journey for ${representation.key}`
  );
  if (!response || !response.ok()) throw new Error(`viewer did not load OK: ${url} (HTTP ${response?.status() || 'no response'})`);
  await page.waitForSelector('#pdf2html-pageno-current', { state: 'attached', timeout: 60000 });
  const journey = await page.evaluate(({ expectedTextMode, findTerm, pageId, occurrence }) => {
    const normalizeFindText = (value) => String(value)
      .normalize('NFKC')
      .replace(/[‐‑‒–—−]/g, '-')
      .replace(/\s+/g, ' ')
      .toLocaleLowerCase();
    window.scrollTo(0, 0);
    window.getSelection()?.removeAllRanges();
    const frame = document.querySelector(pageId);
    const textAtPage = normalizeFindText(frame?.textContent).includes(normalizeFindText(findTerm));
    const findResults = Array.from({ length: occurrence }, () => window.find(findTerm, false, false, true, false, false, false));
    const rect = frame?.getBoundingClientRect();
    const visible = !!rect && rect.bottom > 0 && rect.top < window.innerHeight;
    return {
      representation: document.documentElement.dataset.pdf2htmlRepresentation || 'canonical',
      textMode: document.documentElement.dataset.pdf2htmlTextMode || null,
      expectedTextMode,
      targetPagePresent: !!frame,
      targetPageContainsTerm: textAtPage,
      nativeFindResult: findResults.every(Boolean),
      nativeFindOccurrences: findResults.length,
      targetPageVisibleAfterFind: visible,
      scrollY: window.scrollY,
    };
  }, { expectedTextMode: representation.expectedTextMode, findTerm: FIND_TERM, pageId: `#pf${FIND_PAGE.toString(16)}`, occurrence: FIND_OCCURRENCE_AT_PAGE });
  // Chromium's headless native-find implementation advances the match but does
  // not repaint/scroll the window. The matching/occurrence contract is the
  // stable physical-workload seam; retain the viewport flag as diagnostics.
  if (!journey.targetPagePresent || !journey.targetPageContainsTerm || !journey.nativeFindResult) {
    throw new Error(`far native find did not reach ${FIND_TERM} on page ${FIND_PAGE}: ${JSON.stringify(journey)}`);
  }
  if (journey.textMode !== representation.expectedTextMode) {
    throw new Error(`wrong representation served: expected text mode ${representation.expectedTextMode}, got ${journey.textMode}`);
  }
  await page.waitForTimeout(settleMs);
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  return journey;
}

async function closeFreshBrowser(browser, browserServer) {
  if (!browserServer) return;
  const timer = new Promise((resolve) => setTimeout(resolve, 5000));
  const closing = Promise.allSettled([
    browser ? browser.close() : Promise.resolve(),
    browserServer.close(),
  ]);
  await Promise.race([closing, timer]);
  // A renderer killed by memory pressure can leave the CDP close handshake
  // unresolved. This browser belongs solely to this trial, so force its root
  // process down before proceeding to the next sequential representation.
  const process = browserServer.process();
  if (process.exitCode === null) process.kill('SIGKILL');
}

async function runTrial(options, representation, trial) {
  const url = `http://127.0.0.1:7435/${options.hash}/${encodeURIComponent(representation.filename(options.canonical))}`;
  const preexistingPids = new Set(rendererProcesses().map((process) => process.pid));
  const record = { representation: representation.key, trial, url, started_at: new Date().toISOString(), preexisting_renderer_pids: [...preexistingPids] };
  let browser;
  let browserServer;
  try {
    browserServer = await chromium.launchServer({
      headless: options.headless,
      args: ['--disable-background-networking', '--disable-component-update', '--no-first-run'],
    });
    record.browser_pid = browserServer.process().pid;
    browser = await chromium.connect(browserServer.wsEndpoint());
    const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 });
    const page = await context.newPage();
    try {
      record.journey = await settleJourney(page, representation, url, options.settleMs, options.journeyTimeoutMs);
    } catch (error) {
      // The physical snapshot remains valuable evidence: this is exactly the
      // renderer produced by the same load/find journey at its bounded failure.
      record.journey_error = error.stack || error.message;
    }
    const renderer = await identifyFreshRenderer(record.browser_pid, preexistingPids);
    record.renderer_candidates = renderer.candidates.map(({ pid, ppid, rss_kib, command }) => ({ pid, ppid, rss_kib, command }));
    record.renderer = {
      pid: renderer.selected.pid,
      ppid: renderer.selected.ppid,
      rss_kib: renderer.selected.rss_kib,
      selection: 'largest RSS fresh --type=renderer descendant after full journey',
      command: renderer.selected.command,
    };
    record.footprint = footprint(renderer.selected.pid);
    await context.close();
    record.completed_at = new Date().toISOString();
    return record;
  } finally {
    await closeFreshBrowser(browser, browserServer);
  }
}

async function main() {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    usage();
    throw error;
  }
  if (options.help) return;
  chromium = require('playwright').chromium;
  const output = path.resolve(options.output || path.join(ROOT, 'output/playwright/viewer-memory', timestamp()));
  fs.mkdirSync(output, { recursive: true });
  const report = {
    started_at: new Date().toISOString(),
    command: process.argv.join(' '),
    options: { ...options, output },
    journey: { viewport: { ...VIEWPORT, deviceScaleFactor: 1 }, native_find: FIND_TERM, expected_page: FIND_PAGE, sequential: true },
    trials: [],
    passed: false,
  };
  const selectedRepresentations = REPRESENTATIONS.filter(({ key }) => options.representations.includes(key));
  try {
    for (const representation of selectedRepresentations) {
      for (let trial = 1; trial <= options.trials; trial += 1) {
        console.log(`${representation.key} trial ${trial}/${options.trials}: loading, finding ${FIND_TERM}, sampling fresh renderer`);
        try {
        const record = await runTrial(options, representation, trial);
        report.trials.push(record);
        const outcome = record.journey_error ? `journey failed; snapshot` : 'ready';
        console.log(`${representation.key} trial ${trial}/${options.trials}: ${outcome}, renderer ${record.renderer.pid}, ${gib(record.footprint.bytes)} GiB`);
        } catch (error) {
          const record = {
            representation: representation.key,
            trial,
            failed_at: new Date().toISOString(),
            error: error.stack || error.message,
          };
          report.trials.push(record);
          console.error(`${representation.key} trial ${trial}/${options.trials}: FAIL — ${error.message}`);
        }
      }
    }
    const samples = Object.fromEntries(SUMMARY_REPRESENTATIONS.map(({ key }) => [
      key,
      report.trials.filter((trial) => trial.representation === key && trial.footprint).map((trial) => trial.footprint.bytes),
    ]));
    const complete = Object.values(samples).every((values) => values.length === options.trials);
    report.summary = complete ? summarizeSamples(samples) : null;
    report.incomplete = !complete;
    const journeyFailures = report.trials.filter((trial) => trial.journey_error);
    report.journey_failures = journeyFailures.map(({ representation, trial, journey_error }) => ({ representation, trial, error: journey_error }));
    report.passed = complete && journeyFailures.length === 0;
    if (!complete) {
      const failures = report.trials.filter((trial) => trial.error).map((trial) => `${trial.representation} trial ${trial.trial}`).join(', ');
      fs.writeFileSync(path.join(output, 'summary.txt'), `INCOMPLETE: no threshold recommendation because the same load/find/settle journey failed for ${failures}. See report.json for errors and any successful samples.\n`);
      console.error(`INCOMPLETE: no threshold recommendation; failed journeys: ${failures}`);
      return;
    }
    const physical = conciseSummary(report.summary);
    const qualification = journeyFailures.length
      ? `\nFunctional qualification: FAIL (${journeyFailures.map((trial) => `${trial.representation} trial ${trial.trial}`).join(', ')} did not complete load/find/settle before the bound). Values above are bounded failure snapshots, not successful same-journey results.\n`
      : '';
    fs.writeFileSync(path.join(output, 'summary.txt'), `${physical}${qualification}`);
    console.log(`${physical}${qualification}`.trim());
  } catch (error) {
    report.fatal_error = error.stack || error.message;
    console.error(`FAIL: ${error.message}`);
    process.exitCode = 1;
  } finally {
    report.completed_at = new Date().toISOString();
    writeJson(path.join(output, 'report.json'), report);
    console.log(`artifacts: ${output}`);
  }
}

module.exports = { summarizeSamples, median, parseArgs, descendants, rendererProcesses };

if (require.main === module) {
  main().catch((error) => {
    console.error(`FAIL: ${error.stack || error.message}`);
    process.exitCode = 1;
  });
}
