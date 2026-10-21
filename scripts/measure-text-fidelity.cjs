#!/usr/bin/env node
/*
 * Text-layer fidelity of a converted HTML file: does every glyph paint
 * exactly once, and does a selection leave the text it selects readable?
 *
 * pdf2htmlEX draws each glyph either into the page raster (`.bi`) or as an
 * opaque HTML glyph in a `.t` line, never both. Two defect classes break that:
 *
 *   ghosts     an opaque HTML glyph whose ink also exists in the raster: the
 *              same letter painted twice, a pixel or two apart (a "ghost").
 *              Raster ink that also fills the glyph box's background is a
 *              dark band or rule the text sits on, not a second glyph.
 *   occlusion  text ink that stops being visible once the whole page is
 *              selected: a later line's line box reaches over the line above
 *              it and paints its highlight on top. The highlight uses the
 *              viewer's own ::selection paint from assets/overlay.css.
 *
 * Both are measured from pixels, not from the converter's bookkeeping. Point
 * it at raw pdf2htmlEX output: the page is rendered at deviceScaleFactor 3
 * and no overlay is loaded, so the result describes the converter alone.
 *
 * It also reports the tallest line box (in ems) carrying opaque text, since a
 * selection highlight is exactly as tall as the line box.
 *
 * Usage: measure-text-fidelity.cjs <file.html> [--pages 1,2] [--save <dir>]
 * Prints one JSON object: { pages: [...], totals: {...} }.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright');

const DPR = 3;
const DARK = 110;          // luma below this is glyph ink
const GHOST_OVERLAP = 0.4; // share of a glyph's HTML ink with raster ink under it
const GHOST_BACKGROUND = 0.2; // max share of the box's background that is raster ink
const RASTER_SLOP = 2;     // device px of misregistration tolerated between copies
// Glyphs with less ink than twice the slop window (a dot, a period, a stroke
// of picture-mode line art) are flagged by any line that crosses them, so
// the overlap test cannot tell a duplicate from a crossing; skip them.
const MIN_GLYPH_INK = 2 * (2 * RASTER_SLOP + 1) ** 2;
const OVERLAY_CSS = path.join(__dirname, '..', 'assets', 'overlay.css');

// The viewer's selection paint: the first plain `::selection { ... }` rule.
function viewerSelectionCss() {
    const css = fs.readFileSync(OVERLAY_CSS, 'utf8');
    const rule = css.match(/^::selection\s*\{([^}]*)\}/m);
    if (!rule) throw new Error('no ::selection rule in ' + OVERLAY_CSS);
    const body = rule[1].replace(/;?\s*$/, '').split(';').map((d) => d.trim() + '!important').join(';');
    return `::selection{${body}}`;
}

function parseArgs(argv) {
    const options = { file: null, pages: null, save: null };
    for (let i = 0; i < argv.length; i += 1) {
        const arg = argv[i];
        if (arg === '--probe') process.exit(0); // Playwright resolved; nothing to measure
        else if (arg === '--pages') options.pages = argv[++i].split(',').map(Number);
        else if (arg === '--save') options.save = argv[++i];
        else if (!options.file) options.file = arg;
        else throw new Error(`unexpected argument: ${arg}`);
    }
    if (!options.file) throw new Error('usage: measure-text-fidelity.cjs <file.html> [--pages 1,2] [--save dir]');
    return options;
}

// Runs in the page. Character boxes of every opaque, visible glyph on one
// page, in CSS px relative to the page box, and the tallest line box among
// them in ems: a selection highlight is as tall as the line box.
function collectGlyphBoxes(pageId) {
    const pf = document.getElementById(pageId);
    const origin = pf.getBoundingClientRect();
    const boxes = [];
    let lineBoxEm = 0;
    const walker = document.createTreeWalker(pf, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    let node;
    while ((node = walker.nextNode())) {
        const parent = node.parentElement;
        if (!parent || !parent.closest('.t')) continue;
        const style = getComputedStyle(parent);
        if (style.visibility !== 'visible') continue;
        const color = style.color.match(/[\d.]+/g) || [];
        if (color.length === 4 && Number(color[3]) === 0) continue;
        const text = node.data;
        if (/\S/.test(text)) {
            lineBoxEm = Math.max(lineBoxEm, parseFloat(style.lineHeight) / parseFloat(style.fontSize) || 0);
        }
        for (let i = 0; i < text.length; i += 1) {
            if (/\s/.test(text[i])) continue;
            range.setStart(node, i);
            range.setEnd(node, i + 1);
            const r = range.getClientRects()[0];
            if (!r || r.width < 0.5 || r.height < 0.5) continue;
            boxes.push({
                ch: text[i],
                x: r.left - origin.left, y: r.top - origin.top, w: r.width, h: r.height,
            });
        }
    }
    return { boxes, lineBoxEm };
}

function selectPage(pageId) {
    const pc = document.querySelector('#' + pageId + ' .pc');
    const range = document.createRange();
    range.selectNodeContents(pc);
    const sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
}

// Runs in the page: decode PNG screenshots (data URLs) to RGBA arrays and
// compute both metrics. Canvas decoding keeps the harness dependency-free.
async function analyse(input) {
    async function pixels(url) {
        const img = new Image();
        img.src = url;
        await img.decode();
        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0);
        return { w: canvas.width, h: canvas.height, d: ctx.getImageData(0, 0, canvas.width, canvas.height).data };
    }
    const [text, raster, selected] = await Promise.all([input.text, input.raster, input.selected].map(pixels));
    const { w, h } = text;
    const luma = (img, i) => 0.299 * img.d[i] + 0.587 * img.d[i + 1] + 0.114 * img.d[i + 2];
    const dark = (img, x, y) => luma(img, (y * w + x) * 4) < input.dark;

    // Ink of one layer, dilated by the misregistration slop.
    function dilatedInk(img) {
        const mask = new Uint8Array(w * h);
        for (let y = 0; y < h; y += 1) {
            for (let x = 0; x < w; x += 1) {
                if (!dark(img, x, y)) continue;
                for (let dy = -input.slop; dy <= input.slop; dy += 1) {
                    for (let dx = -input.slop; dx <= input.slop; dx += 1) {
                        const yy = y + dy, xx = x + dx;
                        if (yy >= 0 && yy < h && xx >= 0 && xx < w) mask[yy * w + xx] = 1;
                    }
                }
            }
        }
        return mask;
    }
    const rasterInk = dilatedInk(raster);
    const nearText = dilatedInk(text);

    const ghosts = [];
    let glyphs = 0;
    for (const b of input.boxes) {
        const x0 = Math.max(0, Math.floor(b.x * input.dpr)), x1 = Math.min(w, Math.ceil((b.x + b.w) * input.dpr));
        const y0 = Math.max(0, Math.floor(b.y * input.dpr)), y1 = Math.min(h, Math.ceil((b.y + b.h) * input.dpr));
        let ink = 0, doubled = 0, background = 0, backgroundInk = 0;
        for (let y = y0; y < y1; y += 1) {
            for (let x = x0; x < x1; x += 1) {
                if (dark(text, x, y)) {
                    ink += 1;
                    if (rasterInk[y * w + x]) doubled += 1;
                } else if (!nearText[y * w + x]) {
                    background += 1;
                    if (dark(raster, x, y)) backgroundInk += 1;
                }
            }
        }
        if (ink < input.minInk) continue;
        glyphs += 1;
        const filled = background ? backgroundInk / background : 0;
        if (doubled / ink >= input.overlap && filled <= input.background) {
            ghosts.push({ ch: b.ch, x: Math.round(b.x), y: Math.round(b.y) });
        }
    }

    // Occlusion: text ink that is no longer ink once the page is selected.
    // Selected glyphs repaint dark on their own highlight; a glyph hidden
    // under another line's highlight shows the highlight colour instead.
    let textInk = 0, occluded = 0;
    for (let i = 0; i < w * h * 4; i += 4) {
        if (luma(text, i) >= input.dark) continue;
        textInk += 1;
        if (luma(selected, i) >= input.dark) occluded += 1;
    }
    return { glyphs, ghosts, textInk, occluded };
}

async function main() {
    const options = parseArgs(process.argv.slice(2));
    const browser = await chromium.launch();
    const context = await browser.newContext({
        viewport: { width: 1600, height: 1200 },
        deviceScaleFactor: DPR,
    });
    const page = await context.newPage();
    await page.goto(pathToFileURL(path.resolve(options.file)).href);
    // A blank page for canvas decoding, away from the document's own CSS.
    const lab = await (await browser.newContext()).newPage();

    const pageIds = await page.$$eval('#page-container > .pf', (els) => els.map((e) => e.id));
    const wanted = options.pages ? options.pages.map((n) => pageIds[n - 1]).filter(Boolean) : pageIds;
    // Font classes set visibility:visible on spans, which would override a
    // hidden .t parent, so hide every descendant explicitly.
    const styleRaster = '.t,.t *{visibility:hidden!important}';
    const styleText = '.bi{visibility:hidden!important}' + viewerSelectionCss();

    const results = [];
    for (const id of wanted) {
        const el = await page.$('#' + id);
        await el.scrollIntoViewIfNeeded();
        const shot = async (css) => {
            const handle = await page.addStyleTag({ content: css });
            await page.evaluate(() => document.fonts.ready);
            const png = await el.screenshot({ animations: 'disabled' });
            await handle.evaluate((node) => node.remove());
            return png;
        };
        const raster = await shot(styleRaster);
        const text = await shot(styleText);
        await page.evaluate(selectPage, id);
        const selected = await shot(styleText);
        await page.evaluate(() => getSelection().removeAllRanges());
        const { boxes, lineBoxEm } = await page.evaluate(collectGlyphBoxes, id);
        if (options.save) {
            fs.mkdirSync(options.save, { recursive: true });
            fs.writeFileSync(path.join(options.save, `${id}-raster.png`), raster);
            fs.writeFileSync(path.join(options.save, `${id}-text.png`), text);
            fs.writeFileSync(path.join(options.save, `${id}-selected.png`), selected);
        }
        const url = (buf) => 'data:image/png;base64,' + buf.toString('base64');
        const m = await lab.evaluate(analyse, {
            text: url(text), raster: url(raster), selected: url(selected), boxes,
            dpr: DPR, dark: DARK, slop: RASTER_SLOP, overlap: GHOST_OVERLAP, background: GHOST_BACKGROUND,
            minInk: MIN_GLYPH_INK,
        });
        results.push({
            page: id,
            glyphs: m.glyphs,
            ghosts: m.ghosts.length,
            ghostSample: m.ghosts.slice(0, 12).map((g) => g.ch).join(''),
            ghostAt: m.ghosts.slice(0, 12),
            occlusion: m.textInk ? m.occluded / m.textInk : 0,
            lineBoxEm,
        });
    }
    await browser.close();

    const glyphs = results.reduce((s, r) => s + r.glyphs, 0);
    const ghosts = results.reduce((s, r) => s + r.ghosts, 0);
    const occlusion = results.reduce((s, r) => Math.max(s, r.occlusion), 0);
    const lineBoxEm = results.reduce((s, r) => Math.max(s, r.lineBoxEm), 0);
    process.stdout.write(JSON.stringify({
        file: options.file,
        pages: results,
        totals: { glyphs, ghosts, ghostRate: glyphs ? ghosts / glyphs : 0, maxOcclusion: occlusion, maxLineBoxEm: lineBoxEm },
    }) + '\n');
}

main().catch((err) => {
    console.error(err && err.stack ? err.stack : err);
    process.exit(1);
});
