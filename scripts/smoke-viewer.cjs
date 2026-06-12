#!/usr/bin/env node
/*
 * smoke-viewer.cjs — headless-Chromium overlay smoke assertions.
 *
 * Invoked by scripts/smoke-viewer.sh against a real daemon-served cache
 * entry on :7435. Exits non-zero with a pointed message on the first failed
 * assertion. Do not run this directly — the .sh wrapper builds the temp
 * cache entry, resolves the Playwright module path, and traps cleanup.
 *
 * argv[2] = full http://localhost:7435/<hash>/<file>.html URL to load.
 *
 * Asserted invariants (the overlay regressions that have repeatedly bitten):
 *   - expected .pf page count renders (basic_text.pdf is 1 page)
 *   - overlay booted: #pdf2html-pageno-current present, sidebar DOM present
 *   - pdf2htmlEX render loop killed: defaultViewer.render_timer === null
 *   - native find works: window.find('Normal') === true
 *   - zero console errors, zero failed /_assets/ requests
 */
'use strict';

const { chromium } = require('playwright');

const URL = process.argv[2];
const EXPECTED_PF = 1;
const KNOWN_WORD = 'Normal'; // contiguous text node in basic_text.html

if (!URL) {
  console.error('FAIL: missing viewer URL argument');
  process.exit(2);
}

function fail(msg) {
  console.error(`FAIL: ${msg}`);
  process.exitCode = 1;
}

(async () => {
  const consoleErrors = [];
  const failedAssetRequests = [];

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
    }
  });
  page.on('pageerror', (err) => {
    consoleErrors.push(`pageerror: ${err.message}`);
  });
  page.on('requestfailed', (req) => {
    if (req.url().includes('/_assets/')) {
      failedAssetRequests.push(`${req.url()} (${req.failure()?.errorText || 'unknown'})`);
    }
  });
  page.on('response', (resp) => {
    if (resp.url().includes('/_assets/') && resp.status() >= 400) {
      failedAssetRequests.push(`${resp.url()} (HTTP ${resp.status()})`);
    }
  });

  try {
    const nav = await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 });
    if (!nav || !nav.ok()) {
      fail(`viewer URL did not load OK: ${URL} (HTTP ${nav ? nav.status() : 'no-response'})`);
      await browser.close();
      process.exit(1);
    }

    // Give the deferred overlay script a beat to boot and run its render-loop kill.
    await page.waitForSelector('#pdf2html-pageno-current', { timeout: 10000 }).catch(() => {});

    // --- .pf page count ---------------------------------------------------
    const pfCount = await page.locator('.pf').count();
    if (pfCount !== EXPECTED_PF) {
      fail(`expected ${EXPECTED_PF} .pf page(s), found ${pfCount}`);
    }

    // --- overlay booted ---------------------------------------------------
    const hasPageno = await page.locator('#pdf2html-pageno-current').count();
    if (hasPageno < 1) {
      fail('overlay did not boot: #pdf2html-pageno-current missing');
    }

    // pdf2htmlEX emits #sidebar; the overlay mounts #pdf2html-sidebar-* chrome
    // into it. Require both: the base container and overlay-built sidebar chrome.
    const hasSidebar = await page.evaluate(() => {
      return (
        !!document.getElementById('sidebar') &&
        !!document.querySelector('[id^="pdf2html-sidebar"]')
      );
    });
    if (!hasSidebar) {
      fail('overlay sidebar DOM missing');
    }

    // --- render loop killed ----------------------------------------------
    const renderTimer = await page.evaluate(() => {
      try {
        return window.pdf2htmlEX &&
          window.pdf2htmlEX.defaultViewer &&
          window.pdf2htmlEX.defaultViewer.render_timer;
      } catch (e) {
        return `THREW:${e.message}`;
      }
    });
    if (renderTimer !== null) {
      fail(
        `pdf2htmlEX render loop not killed: render_timer === ${JSON.stringify(
          renderTimer
        )} (expected null — check killPdf2htmlExRenderLoop in overlay.js)`
      );
    }

    // --- native find works ------------------------------------------------
    const found = await page.evaluate((word) => window.find(word), KNOWN_WORD);
    if (found !== true) {
      fail(`window.find('${KNOWN_WORD}') returned ${JSON.stringify(found)} (expected true)`);
    }

    // --- console errors / failed asset requests ---------------------------
    if (consoleErrors.length > 0) {
      fail(`console errors detected (${consoleErrors.length}):\n  - ${consoleErrors.join('\n  - ')}`);
    }
    if (failedAssetRequests.length > 0) {
      fail(`failed /_assets/ requests (${failedAssetRequests.length}):\n  - ${failedAssetRequests.join('\n  - ')}`);
    }
  } catch (err) {
    fail(`unexpected error: ${err.stack || err.message}`);
  } finally {
    await browser.close();
  }

  if (process.exitCode === 1) {
    console.error('smoke-viewer: FAILED');
  } else {
    console.log(
      `smoke-viewer: PASS — ${EXPECTED_PF} page, overlay booted, render loop killed, ` +
        `find('${KNOWN_WORD}') ok, 0 console errors, 0 failed /_assets/ requests`
    );
  }
})();
