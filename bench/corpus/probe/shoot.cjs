#!/usr/bin/env node
/*
 * Screenshot sampled pages of a light HTML entry as the viewer shows them.
 *
 * The entry lives in a scratch cache built by probe/convert.sh. Requests to
 * http://pdfv-probe.test/ are answered from that cache directory (so the
 * overlay at /_assets/ and the page images at /<hash>/page-images/ resolve as
 * they do behind the daemon); every other request is aborted, and daemon API
 * routes (/library, /entry/...) get 404. The overlay's zoom preference is set
 * before load so pages render at a fixed CSS width (fit-width).
 *
 * Usage: shoot.cjs <cache-dir> <url-path> <out-dir> --zoom Z --pages 1,5,9
 *                  [--viewport 1700x1100] [--dpr 2] [--wait-ms 15000]
 * Prints one JSON object on stdout.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const ORIGIN = 'http://pdfv-probe.test';

function parseArgs(argv) {
    const o = { zoom: 1, pages: [], viewport: '1700x1100', dpr: 2, waitMs: 15000, positional: [] };
    for (let i = 0; i < argv.length; i += 1) {
        const a = argv[i];
        if (a === '--zoom') o.zoom = Number(argv[++i]);
        else if (a === '--pages') o.pages = argv[++i].split(',').filter(Boolean).map(Number);
        else if (a === '--viewport') o.viewport = argv[++i];
        else if (a === '--dpr') o.dpr = Number(argv[++i]);
        else if (a === '--wait-ms') o.waitMs = Number(argv[++i]);
        else o.positional.push(a);
    }
    [o.cacheDir, o.urlPath, o.outDir] = o.positional;
    if (!o.cacheDir || !o.urlPath || !o.outDir) {
        throw new Error('usage: shoot.cjs <cache-dir> <url-path> <out-dir> --zoom Z --pages 1,2');
    }
    const [w, h] = o.viewport.split('x').map(Number);
    o.width = w; o.height = h;
    return o;
}

async function main() {
    const o = parseArgs(process.argv.slice(2));
    const root = path.resolve(o.cacheDir);
    fs.mkdirSync(o.outDir, { recursive: true });
    const result = { url: ORIGIN + o.urlPath, pages: [], consoleErrors: [], failedRequests: [], abortedRequests: 0 };
    const t0 = Date.now();
    const browser = await chromium.launch();
    try {
        const context = await browser.newContext({
            viewport: { width: o.width, height: o.height },
            deviceScaleFactor: o.dpr,
            serviceWorkers: 'block',
        });
        await context.addInitScript((zoom) => {
            try { localStorage.setItem('pdf2html-zoom', String(zoom)); } catch (e) { /* ignore */ }
        }, o.zoom);
        await context.route('**/*', async (route) => {
            const url = new URL(route.request().url());
            if (url.origin !== ORIGIN) {
                if (url.protocol === 'data:' || url.protocol === 'blob:') return route.continue();
                result.abortedRequests += 1;
                return route.abort();
            }
            let rel;
            try { rel = decodeURIComponent(url.pathname); } catch (e) { return route.fulfill({ status: 400 }); }
            const file = path.resolve(root, '.' + rel);
            // Stay inside the cache dir (the _assets symlink resolves into the repo).
            if (!file.startsWith(root + path.sep)) return route.fulfill({ status: 403 });
            try {
                if (fs.statSync(file).isFile()) return route.fulfill({ path: file });
            } catch (e) { /* fall through */ }
            return route.fulfill({ status: 404, body: 'not found' });
        });
        const page = await context.newPage();
        page.on('console', (m) => {
            if (m.type() === 'error' && result.consoleErrors.length < 20) result.consoleErrors.push(m.text().slice(0, 300));
        });
        page.on('pageerror', (e) => {
            if (result.consoleErrors.length < 20) result.consoleErrors.push('pageerror: ' + String(e).slice(0, 300));
        });
        page.on('response', (r) => {
            const u = new URL(r.url());
            if (r.status() >= 400 && u.origin === ORIGIN && !/^\/(library|entry|mapping|healthz|visits?)\b/.test(u.pathname)) {
                if (result.failedRequests.length < 20) result.failedRequests.push(`${r.status()} ${u.pathname}`);
            }
        });
        await page.goto(result.url, { waitUntil: 'load', timeout: o.waitMs * 2 });
        result.loadMs = Date.now() - t0;
        await page.waitForFunction(() => document.getElementById('page-container')
            && getComputedStyle(document.getElementById('page-container')).getPropertyValue('--pdf2html-zoom'),
        null, { timeout: o.waitMs }).catch(() => { result.zoomNotApplied = true; });
        const info = await page.evaluate(() => {
            const pfs = Array.from(document.querySelectorAll('#page-container > .pf'));
            return {
                pageCount: pfs.length,
                pageNumbers: pfs.map((pf) => parseInt(pf.getAttribute('data-page-no') || pf.id.slice(2), 16)),
                representation: document.documentElement.getAttribute('data-pdf2html-representation'),
                zoom: getComputedStyle(document.getElementById('page-container') || document.body).getPropertyValue('--pdf2html-zoom'),
            };
        });
        Object.assign(result, info);
        // Hide overlay chrome (fixed toolbars, page number badge, toasts) so a
        // page screenshot holds only the page.
        await page.addStyleTag({ content: 'body > :not(#page-container){display:none!important}' });

        for (const n of o.pages) {
            const entry = { page: n, found: false };
            result.pages.push(entry);
            const id = 'pf' + n.toString(16);
            const el = await page.$('#' + id);
            if (!el) continue;
            entry.found = true;
            const s0 = Date.now();
            await el.evaluate((node) => node.scrollIntoView({ block: 'center', inline: 'center' }));
            // Raster lifecycle: wait for 'ready' (or no rasters on this page).
            entry.rasterState = await page.waitForFunction((pid) => {
                const pf = document.getElementById(pid);
                const st = pf.dataset.pdf2htmlRasterState;
                if (!st && !pf.querySelector('img.bi[data-pdf2html-src]')) return 'none';
                return st === 'ready' || st === 'error' ? st : false;
            }, id, { timeout: o.waitMs }).then((h) => h.jsonValue()).catch(() => 'timeout');
            await page.evaluate(() => document.fonts.ready.then(() => new Promise((r) =>
                requestAnimationFrame(() => requestAnimationFrame(r)))));
            entry.htmlChars = await page.evaluate((pid) => {
                const pc = document.querySelector('#' + pid + ' .pc') || document.getElementById(pid);
                return (pc.textContent || '').replace(/\s+/g, '').length;
            }, id);
            const file = path.join(o.outDir, `html-${n}.png`);
            try {
                const rect = await el.evaluate((node) => {
                    const r = node.getBoundingClientRect();
                    return { x: r.left, y: r.top, width: r.width, height: r.height };
                });
                entry.rect = rect;
                // A page outside the viewport is not painted there; report it instead of a cut screenshot.
                if (rect.y < 0 || rect.x < 0 || rect.y + rect.height > o.height + 0.5 || rect.x + rect.width > o.width + 0.5) {
                    entry.clipped = true;
                }
                // Large DPR-2 captures can take long under parallel load; allow 4x the wait.
                await page.screenshot({ path: file, clip: rect, animations: 'disabled', timeout: o.waitMs * 4 });
                entry.file = file;
            } catch (e) {
                entry.error = String(e).slice(0, 300);
            }
            entry.ms = Date.now() - s0;
        }
    } finally {
        await browser.close();
    }
    result.totalMs = Date.now() - t0;
    process.stdout.write(JSON.stringify(result) + '\n');
}

main().catch((err) => {
    process.stdout.write(JSON.stringify({ fatal: String(err && err.stack ? err.stack : err).slice(0, 2000) }) + '\n');
    process.exit(1);
});
