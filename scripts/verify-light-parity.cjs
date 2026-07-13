#!/usr/bin/env node
/*
 * Deterministic visual parity check for a cached canonical/light HTML pair.
 * The public seam is the daemon's direct cache-file route, deliberately not
 * /view: http://localhost:7435/<hash>/<canonical>.html and its .light peer.
 */
'use strict';

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const PORT = 7435;
const VIEWPORT = { width: 1600, height: 1200 };

function usage() {
  console.error(
    'usage: verify-light-parity.cjs <hash> <canonical.html> [--light <derived.html>] [--pages 1,2] [--zooms 1,2] [--output <dir>]'
  );
}

function parseList(value, name, predicate) {
  const values = String(value).split(',').map((item) => item.trim()).filter(Boolean);
  if (!values.length || values.some((item) => !predicate(item))) {
    throw new Error(`invalid ${name}: ${value}`);
  }
  return values;
}

function parseArgs(argv) {
  const positional = [];
  const options = { light: null, pages: ['1'], zooms: ['1'], output: null };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--light' || arg === '--pages' || arg === '--zooms' || arg === '--output') {
      if (!argv[i + 1]) throw new Error(`missing value for ${arg}`);
      options[arg.slice(2)] = argv[++i];
    } else if (arg.startsWith('--pages=')) {
      options.pages = arg.slice('--pages='.length);
    } else if (arg.startsWith('--zooms=')) {
      options.zooms = arg.slice('--zooms='.length);
    } else if (arg.startsWith('--output=')) {
      options.output = arg.slice('--output='.length);
    } else if (arg.startsWith('--light=')) {
      options.light = arg.slice('--light='.length);
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
  const light = options.light || lightName(canonical);
  if (!light.endsWith('.html') || /[\\/]/.test(light)) {
    throw new Error(`light filename must be a plain *.html name: ${light}`);
  }
  return {
    hash,
    canonical,
    light,
    pages: parseList(options.pages, 'pages', (value) => /^\d+$/.test(value) && Number(value) > 0).map(Number),
    zooms: parseList(options.zooms, 'zooms', (value) => /^\d+(?:\.\d+)?$/.test(value) && Number(value) > 0).map(Number),
    output: options.output,
  };
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

function captureName(representation, page, zoom) {
  return `${representation}-p${page}-z${String(zoom).replace('.', '_')}.png`;
}

function runCompare(canonical, light, diff) {
  const result = spawnSync('magick', ['compare', '-metric', 'AE', canonical, light, diff], {
    encoding: 'utf8',
  });
  const output = `${result.stdout || ''}${result.stderr || ''}`.trim();
  const match = output.match(/\d+/);
  if (result.error || result.status === null || !match || result.status > 1) {
    throw new Error(`magick compare failed: ${result.error?.message || output || `exit ${result.status}`}`);
  }
  return Number(match[0]);
}

async function waitForOverlay(page, url) {
  const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
  if (!response || !response.ok()) {
    throw new Error(`viewer did not load OK: ${url} (HTTP ${response ? response.status() : 'no response'})`);
  }
  await page.waitForSelector('#pdf2html-pageno-current', { state: 'attached', timeout: 60000 });
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function capturePage(page, representation, pageNumber, zoom, filename) {
  await page.evaluate((value) => { document.body.style.zoom = String(value); }, zoom);
  const selector = pageSelector(pageNumber);
  const target = page.locator(selector);
  await target.waitFor({ state: 'attached', timeout: 15000 });
  await target.scrollIntoViewIfNeeded();

  if (representation === 'light') {
    await page.waitForFunction(
      (pageId) => {
        const frame = document.querySelector(pageId);
        if (!frame) return false;
        const rasters = Array.from(frame.querySelectorAll('img.bi[data-pdf2html-src]'));
        return rasters.length > 0
          && frame.dataset.pdf2htmlRasterState === 'ready'
          && rasters.every((img) => img.getAttribute('src') === img.getAttribute('data-pdf2html-src')
            && img.complete && img.naturalWidth > 0);
      },
      selector,
      { timeout: 30000 }
    );
  }

  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await target.screenshot({ path: filename, animations: 'disabled' });
  return page.evaluate((pageId) => {
    const frame = document.querySelector(pageId);
    const rasters = frame ? Array.from(frame.querySelectorAll('img.bi[data-pdf2html-src]')) : [];
    return {
      pageFrame: !!frame,
      mountedRasters: rasters.filter((img) => img.getAttribute('src') === img.getAttribute('data-pdf2html-src')
        && img.complete && img.naturalWidth > 0).length,
      rasterCount: rasters.length,
      rasterState: frame?.dataset.pdf2htmlRasterState || null,
    };
  }, selector);
}

function diagnostics() {
  return { consoleErrors: [], networkErrors: [], rasterErrors: [] };
}

function attachDiagnostics(page, name, report) {
  const sink = report.diagnostics[name];
  page.on('console', (message) => {
    if (message.type() === 'error') sink.consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => sink.consoleErrors.push(`pageerror: ${error.message}`));
  page.on('requestfailed', (request) => {
    sink.networkErrors.push(`${request.url()} (${request.failure()?.errorText || 'unknown'})`);
  });
  page.on('response', (response) => {
    if (response.status() >= 400) sink.networkErrors.push(`${response.url()} (HTTP ${response.status()})`);
  });
  page.on('requestfinished', async (request) => {
    if (!request.url().includes('/page-images/')) return;
    const response = await request.response();
    if (!response || !response.ok()) sink.rasterErrors.push(`${request.url()} (HTTP ${response?.status() || 'no response'})`);
  });
}

function writeReport(output, report) {
  fs.writeFileSync(path.join(output, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
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

  const runDirectory = path.resolve(options.output || path.join(ROOT, 'output/playwright/light-parity', timestamp()));
  fs.mkdirSync(runDirectory, { recursive: true });
  const base = `http://localhost:${PORT}/${options.hash}`;
  const urls = {
    canonical: `${base}/${encodeURIComponent(options.canonical)}`,
    light: `${base}/${encodeURIComponent(options.light)}`,
  };
  const report = {
    hash: options.hash,
    canonical: options.canonical,
    light: options.light,
    urls,
    viewport: { ...VIEWPORT, deviceScaleFactor: 1 },
    output: runDirectory,
    diagnostics: { canonical: diagnostics(), light: diagnostics() },
    checks: [],
    passed: false,
  };
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 });
    const canonicalPage = await context.newPage();
    const lightPage = await context.newPage();
    attachDiagnostics(canonicalPage, 'canonical', report);
    attachDiagnostics(lightPage, 'light', report);
    await Promise.all([waitForOverlay(canonicalPage, urls.canonical), waitForOverlay(lightPage, urls.light)]);

    for (const zoom of options.zooms) {
      for (const pageNumber of options.pages) {
        const canonicalPath = path.join(runDirectory, captureName('canonical', pageNumber, zoom));
        const lightPath = path.join(runDirectory, captureName('light', pageNumber, zoom));
        const diffPath = path.join(runDirectory, `diff-p${pageNumber}-z${String(zoom).replace('.', '_')}.png`);
        const [canonical, light] = await Promise.all([
          capturePage(canonicalPage, 'canonical', pageNumber, zoom, canonicalPath),
          capturePage(lightPage, 'light', pageNumber, zoom, lightPath),
        ]);
        const ae = runCompare(canonicalPath, lightPath, diffPath);
        const check = { page: pageNumber, zoom, canonical, light, ae, difference: ae !== 0, artifacts: {
          canonical: path.basename(canonicalPath), light: path.basename(lightPath), diff: path.basename(diffPath),
        } };
        report.checks.push(check);
        console.log(`page ${pageNumber} zoom ${zoom}: AE=${ae}, mounted rasters=${light.mountedRasters}/${light.rasterCount}`);
      }
    }
    await context.close();
    const diagnosticErrors = Object.values(report.diagnostics).some((diagnostic) =>
      diagnostic.consoleErrors.length || diagnostic.networkErrors.length || diagnostic.rasterErrors.length
    );
    report.passed = report.checks.every((check) => check.ae === 0 && check.light.mountedRasters === check.light.rasterCount)
      && !diagnosticErrors;
  } catch (error) {
    report.fatalError = error.stack || error.message;
    console.error(`FAIL: ${error.message}`);
  } finally {
    if (browser) await browser.close();
    writeReport(runDirectory, report);
  }

  if (!report.passed) {
    console.error(`light parity: FAIL — artifacts: ${runDirectory}`);
    process.exitCode = 1;
  } else {
    console.log(`light parity: PASS — ${report.checks.length} check(s), artifacts: ${runDirectory}`);
  }
})();
