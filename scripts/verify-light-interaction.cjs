#!/usr/bin/env node
/*
 * Repeatable interaction proof for a cached canonical/light pair.
 *
 * Public seam: the daemon's direct cache-file routes, rather than /view:
 *   http://localhost:7435/<hash>/<canonical>.html
 *   http://localhost:7435/<hash>/<canonical>.light.html
 *
 * This is deliberately a supplement to the real Comet check. It exercises
 * Chromium's DOM, pointer and Clipboard APIs, but cannot prove extension or
 * Vimium behaviour.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const PORT = 7435;
const VIEWPORT = { width: 1440, height: 1000 };
const READY_TIMEOUT_MS = 30000;
const INTERACTION_TIMEOUT_MS = 20000;

function usage() {
  console.error(
    'usage: verify-light-interaction.cjs <hash> <canonical.html> --page <number> [--needle <text>] [--output <dir>]'
  );
}

function parseArgs(argv) {
  const positional = [];
  const options = { page: null, needle: 'Hopcroft-Karp', output: null };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--page' || arg === '--needle' || arg === '--output') {
      if (!argv[index + 1]) throw new Error(`missing value for ${arg}`);
      options[arg.slice(2)] = argv[++index];
    } else if (arg.startsWith('--page=')) {
      options.page = arg.slice('--page='.length);
    } else if (arg.startsWith('--needle=')) {
      options.needle = arg.slice('--needle='.length);
    } else if (arg.startsWith('--output=')) {
      options.output = arg.slice('--output='.length);
    } else if (arg === '--help' || arg === '-h') {
      usage();
      process.exit(0);
    } else if (arg.startsWith('-')) {
      throw new Error(`unknown option: ${arg}`);
    } else {
      positional.push(arg);
    }
  }
  if (positional.length !== 2) throw new Error('expected <hash> <canonical.html>');
  const [hash, canonical] = positional;
  if (!/^[a-f0-9]{16,}$/i.test(hash)) throw new Error(`invalid cache hash: ${hash}`);
  if (!canonical.endsWith('.html') || canonical.endsWith('.light.html') || /[\\/]/.test(canonical)) {
    throw new Error(`canonical filename must be a plain *.html name: ${canonical}`);
  }
  const page = Number(options.page);
  if (!Number.isInteger(page) || page < 1) throw new Error('--page must be a positive integer');
  const needle = String(options.needle || '').trim();
  if (!needle) throw new Error('--needle must not be empty');
  return { hash, canonical, page, needle, output: options.output };
}

function timestamp() {
  return new Date().toISOString().replace(/[:.]/g, '-');
}

function lightName(canonical) {
  return `${canonical.slice(0, -'.html'.length)}.light.html`;
}

function pageSelector(pageNumber) {
  return `#pf${pageNumber.toString(16)}`;
}

function normalized(text) {
  return String(text || '').replace(/[‐‑‒–—]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
}

function diagnostics() {
  return { consoleErrors: [], pageErrors: [], requestErrors: [] };
}

function attachDiagnostics(page, representation, report) {
  const sink = report.diagnostics[representation];
  page.on('console', (message) => {
    if (message.type() === 'error') sink.consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => sink.pageErrors.push(error.message));
  page.on('requestfailed', (request) => {
    sink.requestErrors.push(`${request.url()} (${request.failure()?.errorText || 'unknown'})`);
  });
  page.on('response', (response) => {
    if (response.status() >= 400) sink.requestErrors.push(`${response.url()} (HTTP ${response.status()})`);
  });
}

function check(report, representation, name, passed, detail) {
  const entry = { representation, name, passed: !!passed, detail };
  report.checks.push(entry);
  console.log(`${passed ? 'PASS' : 'FAIL'} ${representation}: ${name}${detail ? ` — ${detail}` : ''}`);
  return entry;
}

async function withinTimeout(promise, milliseconds, label) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out after ${milliseconds}ms`)), milliseconds);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function settle(page) {
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function loadViewer(page, url) {
  // Commit is enough to prove the daemon route. The explicit overlay readiness
  // wait below is the actual interaction gate, and has a finite timeout so a
  // huge document cannot strand this harness in an unbounded navigation wait.
  const response = await page.goto(url, { waitUntil: 'commit', timeout: READY_TIMEOUT_MS });
  if (!response || !response.ok()) {
    throw new Error(`viewer did not load OK: ${url} (HTTP ${response ? response.status() : 'no response'})`);
  }
  await page.waitForSelector('#pdf2html-pageno-current', { state: 'attached', timeout: READY_TIMEOUT_MS });
  await page.evaluate(() => {
    const container = document.getElementById('page-container');
    if (container) container.scrollTop = 0;
    window.getSelection()?.removeAllRanges();
  });
  await settle(page);
}

async function targetPageText(page, selector) {
  return page.evaluate((target) => {
    const frame = document.querySelector(target);
    if (!frame) return null;
    return Array.from(frame.querySelectorAll('.t')).map((line) => line.textContent || '').join('\n');
  }, selector);
}

async function jumpToPage(page, selector) {
  await page.evaluate((target) => {
    const frame = document.querySelector(target);
    frame?.scrollIntoView({ block: 'start', behavior: 'auto' });
  }, selector);
  await page.waitForFunction((target) => {
    const frame = document.querySelector(target);
    const container = document.getElementById('page-container');
    if (!frame || !container) return false;
    const a = frame.getBoundingClientRect();
    const b = container.getBoundingClientRect();
    return a.bottom > b.top && a.top < b.bottom;
  }, selector, { timeout: 15000 });
  await settle(page);
  return page.evaluate((target) => {
    const frame = document.querySelector(target);
    const container = document.getElementById('page-container');
    const rect = frame?.getBoundingClientRect();
    const viewport = container?.getBoundingClientRect();
    return {
      pageVisible: !!rect && !!viewport && rect.bottom > viewport.top && rect.top < viewport.bottom,
      currentPage: document.getElementById('pdf2html-pageno-current')?.textContent?.trim() || null,
      pageTop: rect?.top ?? null,
      pageBottom: rect?.bottom ?? null,
    };
  }, selector);
}

async function nativeFind(page, needle) {
  await page.evaluate(() => {
    const container = document.getElementById('page-container');
    if (container) container.scrollTop = 0;
    window.getSelection()?.removeAllRanges();
  });
  await settle(page);
  const result = await page.evaluate((query) => {
    const found = window.find(query, false, false, true, false, false, false);
    const selection = window.getSelection();
    const frame = selection?.anchorNode?.parentElement?.closest?.('.pf');
    return { found, selection: selection?.toString() || '', pageId: frame?.id || null };
  }, needle);
  await settle(page);
  return result;
}

async function selectByPointer(page, selector) {
  const line = await page.evaluate((target) => {
    const frame = document.querySelector(target);
    if (!frame) return null;
    const candidates = Array.from(frame.querySelectorAll('.t'));
    for (const candidate of candidates) {
      const text = (candidate.textContent || '').replace(/\s+/g, ' ').trim();
      const rect = candidate.getBoundingClientRect();
      if (text.length >= 8 && rect.width >= 40 && rect.height >= 4 && rect.top > 0 && rect.bottom < innerHeight) {
        return { text, left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
      }
    }
    return null;
  }, selector);
  if (!line) return { selected: '', expectedLine: null, selectionPageId: null, reason: 'no selectable visible line' };
  const y = Math.max(2, Math.min(VIEWPORT.height - 2, (line.top + line.bottom) / 2));
  const start = Math.max(2, Math.min(VIEWPORT.width - 2, line.left + Math.min(8, line.right - line.left - 2)));
  const end = Math.max(start + 2, Math.min(VIEWPORT.width - 2, line.right - 2));
  await page.mouse.move(start, y);
  await page.mouse.down();
  await page.mouse.move(end, y, { steps: 12 });
  await page.mouse.up();
  await settle(page);
  return page.evaluate((expectedLine) => {
    const selection = window.getSelection();
    const frame = selection?.anchorNode?.parentElement?.closest?.('.pf');
    return {
      selected: selection?.toString() || '',
      expectedLine,
      selectionPageId: frame?.id || null,
    };
  }, line.text);
}

async function copySelectionSafely(page) {
  return page.evaluate(async () => {
    const value = window.getSelection()?.toString() || '';
    if (!value) return { value, method: 'selection-api', copied: false, reason: 'selection empty' };
    if (!navigator.clipboard?.writeText || !navigator.clipboard?.readText) {
      return { value, method: 'selection-api', copied: false, reason: 'Clipboard API unavailable' };
    }
    let prior = null;
    try { prior = await navigator.clipboard.readText(); } catch (_) {}
    try {
      await navigator.clipboard.writeText(value);
      const copied = await navigator.clipboard.readText();
      if (prior !== null) await navigator.clipboard.writeText(prior);
      return { value, method: 'clipboard-write-read-restore', copied: copied === value, reason: null };
    } catch (error) {
      if (prior !== null) {
        try { await navigator.clipboard.writeText(prior); } catch (_) {}
      }
      return { value, method: 'selection-api', copied: false, reason: error.message };
    }
  });
}

async function overlaySearchCount(page, needle) {
  const supported = await page.evaluate(() => !!(window.CSS && CSS.highlights && typeof Highlight !== 'undefined'));
  if (!supported) return { reliable: false, count: null, text: null };
  await page.keyboard.press('/');
  const input = page.locator('#pdf2html-search-input');
  await input.waitFor({ state: 'visible', timeout: 10000 });
  await input.fill(needle);
  await page.waitForFunction(() => document.getElementById('pdf2html-search-count')?.textContent?.trim().length > 0, null, {
    timeout: 10000,
  });
  const text = await page.locator('#pdf2html-search-count').textContent();
  await page.keyboard.press('Escape');
  const match = String(text || '').match(/\/\s*(\d+)\s*$/);
  return { reliable: true, count: match ? Number(match[1]) : 0, text: String(text || '').trim() };
}

async function rasterState(page, selector, representation) {
  return page.evaluate(({ target, representation: kind }) => {
    const frame = document.querySelector(target);
    if (!frame) return null;
    const frameRect = frame.getBoundingClientRect();
    const rasters = Array.from(frame.querySelectorAll('.pc > img.bi'));
    return {
      frameState: frame.dataset.pdf2htmlRasterState || null,
      rasters: rasters.map((image) => {
        const rect = image.getBoundingClientRect();
        return {
          complete: image.complete,
          naturalWidth: image.naturalWidth,
          naturalHeight: image.naturalHeight,
          srcMounted: kind === 'light' ? image.getAttribute('src') === image.getAttribute('data-pdf2html-src') : !!image.getAttribute('src'),
          inPageBounds: rect.width > 0 && rect.height > 0
            && rect.left >= frameRect.left - 2 && rect.top >= frameRect.top - 2
            && rect.right <= frameRect.right + 2 && rect.bottom <= frameRect.bottom + 2,
          bounds: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        };
      }),
    };
  }, { target: selector, representation });
}

function writeReport(directory, report) {
  fs.writeFileSync(path.join(directory, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
}

function failureDetail(error) {
  const message = error?.message || String(error);
  return /timeout/i.test(message) ? `timed out: ${message.split('\n')[0]}` : message.split('\n')[0];
}

(async () => {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    usage();
    console.error(`FAIL: ${error.message}`);
    process.exit(2);
  }

  const output = path.resolve(options.output || path.join(ROOT, 'output/playwright/light-interaction', timestamp()));
  fs.mkdirSync(output, { recursive: true });
  const base = `http://localhost:${PORT}/${options.hash}`;
  const urls = {
    canonical: `${base}/${encodeURIComponent(options.canonical)}`,
    light: `${base}/${encodeURIComponent(lightName(options.canonical))}`,
  };
  const selector = pageSelector(options.page);
  const report = {
    hash: options.hash,
    canonical: options.canonical,
    light: lightName(options.canonical),
    targetPage: options.page,
    needle: options.needle,
    urls,
    viewport: { ...VIEWPORT, deviceScaleFactor: 1 },
    output,
    diagnostics: { canonical: diagnostics(), light: diagnostics() },
    checks: [],
    details: {},
    passed: false,
  };
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 });
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], `http://localhost:${PORT}`);
    for (const representation of ['canonical', 'light']) {
      const page = await context.newPage();
      attachDiagnostics(page, representation, report);
      page.setDefaultTimeout(INTERACTION_TIMEOUT_MS);
      page.setDefaultNavigationTimeout(READY_TIMEOUT_MS);
      report.details[representation] = {};
      try {
        await withinTimeout(loadViewer(page, urls[representation]), READY_TIMEOUT_MS + 1000,
          `${representation} viewer readiness`);
        check(report, representation, 'viewer reaches interactive overlay before timeout', true,
          `${READY_TIMEOUT_MS / 1000}s budget`);
      } catch (error) {
        report.details[representation].readinessFailure = error.stack || error.message;
        check(report, representation, 'viewer reaches interactive overlay before timeout', false, failureDetail(error));
        await withinTimeout(page.close(), 5000, `${representation} page close`).catch(() => {});
        continue;
      }

      try {
        const pageText = await targetPageText(page, selector);
        report.details[representation].targetPageTextLength = pageText?.length || 0;
        check(report, representation, 'target DOM text contains needle',
          !!pageText && normalized(pageText).includes(normalized(options.needle)), `page ${options.page}`);

        const find = await nativeFind(page, options.needle);
        report.details[representation].nativeFind = find;
        check(report, representation, 'far window.find finds needle', find.found && normalized(find.selection).includes(normalized(options.needle)),
          `selection page ${find.pageId || 'unknown'}`);

        const jumped = await jumpToPage(page, selector);
        report.details[representation].pageJump = jumped;
        check(report, representation, 'page jump makes target visible', jumped.pageVisible, `counter ${jumped.currentPage || 'unknown'}`);

        const selection = await selectByPointer(page, selector);
        report.details[representation].pointerSelection = selection;
        check(report, representation, 'pointer drag creates target-page selection',
          !!selection.selected.trim() && selection.selectionPageId === selector.slice(1),
          `${selection.selected.trim().slice(0, 80) || selection.reason || 'empty'}`);

        const copied = await copySelectionSafely(page);
        report.details[representation].copiedPlainText = copied;
        check(report, representation, 'selection plain text is copyable',
          !!copied.value.trim() && (copied.copied || copied.method === 'selection-api'), copied.method);

        const search = await overlaySearchCount(page, options.needle);
        report.details[representation].overlaySearch = search;
        check(report, representation, 'overlay search has visible-page results',
          !search.reliable || search.count > 0, search.reliable ? search.text : 'Highlight API unavailable; skipped');

        const raster = await rasterState(page, selector, representation);
        report.details[representation].raster = raster;
        const rasterReady = !!raster && raster.rasters.length > 0 && raster.rasters.every((image) =>
          image.complete && image.naturalWidth > 0 && image.naturalHeight > 0 && image.srcMounted && image.inPageBounds
        ) && (representation !== 'light' || raster.frameState === 'ready');
        check(report, representation, 'live raster state and bounds are valid', rasterReady,
          `${raster?.rasters.length || 0} raster(s), state ${raster?.frameState || 'n/a'}`);
      } catch (error) {
        report.details[representation].interactionFailure = error.stack || error.message;
        check(report, representation, 'interaction sequence completes before timeout', false, failureDetail(error));
      } finally {
        await withinTimeout(page.close(), 5000, `${representation} page close`).catch(() => {});
      }
    }
    await withinTimeout(context.close(), 5000, 'browser context close').catch(() => {});
    for (const representation of ['canonical', 'light']) {
      const diagnostic = report.diagnostics[representation];
      check(report, representation, 'console/page/request diagnostics are clean',
        diagnostic.consoleErrors.length === 0 && diagnostic.pageErrors.length === 0 && diagnostic.requestErrors.length === 0,
        `${diagnostic.consoleErrors.length} console, ${diagnostic.pageErrors.length} page, ${diagnostic.requestErrors.length} request`);
    }
    report.passed = report.checks.every((entry) => entry.passed);
  } catch (error) {
    report.fatalError = error.stack || error.message;
    console.error(`FAIL: ${error.message}`);
  } finally {
    if (browser) await withinTimeout(browser.close(), 5000, 'browser close').catch(() => {});
    writeReport(output, report);
  }
  if (!report.passed) {
    console.error(`light interaction: FAIL — artifacts: ${output}`);
    process.exitCode = 1;
  } else {
    console.log(`light interaction: PASS — ${report.checks.length} checks, artifacts: ${output}`);
  }
})();
