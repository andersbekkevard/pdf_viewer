# Adversarial sources: test suites and synthetic PDFs

Phase 1 of the corpus took small samples from public PDF test suites and fuzzing
corpora, and generated synthetic files that each isolate one feature. Phase 2
enlarged the sources whose phase-1 sample failed most often in the probe
(pdfjs-linked, both SafeDocs sets) and added four synthetic generators; each
section says what phase 2 changed. These
files are chosen to break either the current viewer (pdf2htmlEX conversion plus
the light build) or a PDFium page renderer with a transparent text layer. Real
documents (arXiv, Common Crawl, books, scans) are described in other source
files.

All files are under `$PDFV_CORPUS_DIR/incoming/<source>/` (default
`~/.local/share/pdf_viewer/corpus/incoming/`). Each directory has `_files.tsv`
with `filename<TAB>url<TAB>license`. Repositories are cloned shallow and sparse
into `$PDFV_CORPUS_DIR/staging/` and only `.pdf` files are copied out;
nothing from a downloaded repository is executed. Paths inside a repository
become flat file names with `/` replaced by `__` and spaces by `_`. The url
column is a raw-file URL pinned to the commit that was cloned.

Counts and sizes are as taken on 2026-10-20/21.

## Rebuilding

All scripts are idempotent: files already listed in `_files.tsv` are skipped.

| step | command |
|---|---|
| test-suite repositories (pdfjs, pdfium, pdfium-templates, poppler-test, qpdf, verapdf-corpus) | `bench/corpus/fetch/adversarial-suites.sh [pdfjs pdfium poppler qpdf verapdf]` |
| copy helper used by the above | `bench/corpus/fetch/stage-copy.py` |
| pdf.js linked documents | `python3 -I bench/corpus/fetch/pdfjs-links.py --step 1` (phase 1 used `--step 3`) |
| SafeDocs issue trackers | `python3 -I bench/corpus/fetch/safedocs-sample.py issue-trackers --jobs 4 --quota <see below>` |
| SafeDocs fuzzed sets | `python3 -I bench/corpus/fetch/safedocs-sample.py unsafe --max-mb 20 --jobs 2 --quota <see below>` |
| PDFium `.in` templates | `python3 -I bench/corpus/synth/pdfium_templates.py $PDFV_CORPUS_DIR/staging/pdfium` |
| synthetic files | `uv run bench/corpus/synth/generate.py` |

The repository commits are pinned only by the url column; a fresh clone takes
the current commit, so a rebuild can differ slightly from the files listed.

| source | files | MB | available | most likely to break |
|---|---:|---:|---|---|
| `pdfjs` | 999 | 121 | all in-repo PDFs taken | both: fonts, broken files, XFA, odd encodings |
| `pdfjs-linked` | 459 | 692 | all 460 links taken; 1 failed | both: large real documents from bug reports |
| `pdfium` | 343 | 3.7 | all taken | PDFium-side corner cases, small |
| `pdfium-templates` | 564 | 3.2 | all taken | malformed objects, JavaScript/XFA forms |
| `poppler-test` | 83 | 4.3 | all taken | pdf2htmlEX (poppler-based) |
| `qpdf` | 717 | 39 | all taken | structure: xref, object streams, damage |
| `verapdf-corpus` | 2,906 | 164 | all taken (phase 3) | fonts, colour spaces, tagged PDF |
| `safedocs-issue-trackers` | 4,593 | 4,234 | ~20,600 PDFs, 15.7 GB | both: real attachments from parser bug reports |
| `safedocs-unsafe` | 2,197 | 1,797 | ~1.5 M files, ~1 TB | reliability (A6): crashes, hangs, fuzzed files |
| `synth` | 95 | 17 | regenerate at will | one feature per file, see below |

## pdfjs: Mozilla pdf.js test PDFs

What: every `.pdf` in `test/pdfs/` of github.com/mozilla/pdf.js at commit
`8fb674c` (2026-10-20). These are reduced test cases from pdf.js bug reports:
broken fonts (Type 1, CFF, TrueType with bad tables, Type 3), unusual encodings
and CMaps, shading and blend edge cases, annotations, AcroForm and XFA forms,
broken xref tables, encryption.

Why: pdf.js renders with its own engine and checks its output against
reference images, so these files are known to differ between engines. Many hit
font paths where pdf2htmlEX and PDFium differ.

License: the repository is Apache-2.0, but most PDFs come from bug reports and
keep their original copyright. License column: `unknown per file`.

Fetch: `adversarial-suites.sh pdfjs` (sparse clone of `test/pdfs/`).

## pdfjs-linked: documents linked from the pdf.js test suite

What: pdf.js keeps larger test documents outside the repository; each is a
`test/pdfs/<name>.pdf.link` file holding one URL (web.archive.org,
bugzilla.mozilla.org attachments, GitHub issue attachments). Phase 1 took every
third `.link` file in name order, 154 of ~460, and all 154 downloaded. Each
download was checked for `%PDF` in the first KB and against the md5 in
`test/test_manifest.json`; no mismatches.

Why: full-size real documents that once broke pdf.js: scanned books, CJK
government documents, very large or very long files, forms.

License: third-party documents, copyright with their owners; used here only as
local test data.

Phase 2 fetched all remaining links with `pdfjs-links.py --step 1`: one at a
time, 1.5 s pause, 80 MB cap per file, md5 checked against `test_manifest.json`.
Of 460 links, 459 downloaded (no md5 mismatches); `pr4731.pdf` failed with HTTP
500 from web.archive.org.

## pdfium: PDFium test resources

What: every `.pdf` under `testing/resources/` of pdfium.googlesource.com/pdfium
at commit `8fdce8e` (2026-10-20). Small files for PDFium's own pixel and
embedder tests, including many regression cases for crash bugs.

License: BSD-3-Clause (PDFium repository); a few files are third-party.

Fetch: `adversarial-suites.sh pdfium` (also expands the templates below).

## pdfium-templates: PDFium `.in` templates expanded

What: the 564 `testing/resources/**/*.in` files from the same checkout. They
are hand-written PDF text with placeholders for byte offsets (`{{object}}`,
`{{xref}}`, `{{streamlen}}`, ...). PDFium's own `fixup_pdf_template.py` was not
run; `bench/corpus/synth/pdfium_templates.py` reimplements the same rules and
writes `<path>.pdf`. About 137 of the results report errors in `pdfinfo`; the
sample checked were deliberate (dangling references, XFA forms without
`/Fields`, bad `/Length`), not expansion mistakes.

Why: targeted malformations and JavaScript/XFA form tests that are hard to
find in the wild.

License: BSD-3-Clause. The url column is
`generated:pdfium-template-fixup:<googlesource URL of the .in file>`.

Regenerate: `python3 -I bench/corpus/synth/pdfium_templates.py <pdfium checkout>`.

## poppler-test: poppler test repository

What: all 83 PDFs in gitlab.freedesktop.org/poppler/test at commit `48b6219`
(2026-08-14), from `unittestcases/`, `tests/` and `test-gen/`.

Why: pdf2htmlEX is built on poppler, so poppler's own regression files are
the most direct probe of the current pipeline.

License: the repository code is GPL-2.0; the PDFs come from bug reports and
keep their copyright. License column: `unknown per file`.

Fetch: `adversarial-suites.sh poppler`.

## qpdf: qpdf test files

What: all 717 `.pdf` files in github.com/qpdf/qpdf at commit `4eba958`
(2026-09-26), mostly `qpdf/qtest/qpdf/`. Many are deliberately damaged: bad
xref tables and streams, broken object streams, loops in the page tree,
damaged encryption dictionaries, and also many valid outputs of qpdf runs
(linearized, object streams, split pages), some near-duplicates.

Why: the A6 reliability axis needs files that test recovery from structural
damage, which is where qpdf is the reference.

License: Apache-2.0 (qpdf repository).

Fetch: `adversarial-suites.sh qpdf`.

## verapdf-corpus: veraPDF PDF/A and PDF/UA test files

What: github.com/veraPDF/veraPDF-corpus at commit `bb75f4f` (2026-09-16). Taken
in full: `ISO 32000-1`, `ISO 32000-2`, `Isartor test files`, `TWG test files`,
`Undefined` (306 files). From the `PDF_A-*` and `PDF_UA-*` directories, every
fifth file in path order (520 files). Each file is one atomic pass or fail case
for a validation rule, described in its outline.

Why: systematic coverage of font embedding, CIDFont and CMap rules, colour
spaces, transparency, annotations and structure trees. Files are small and
similar to each other, so only a fifth was taken.

License: CC BY 4.0 (veraPDF consortium).

Phase 3 took the other 2,080 files of `PDF_A-*`/`PDF_UA-*` with
`VERAPDF_STEP=1 adversarial-suites.sh verapdf`, so the whole corpus is in (2,906
files, 164 MB). Phase 2 had skipped it: the probe found only 15 % failing, and
76 % of the files have no text.

## safedocs-issue-trackers: SafeDocs "issue tracker" corpus

What: PDFs attached to bug reports in the issue trackers of PDF software,
collected by NASA JPL for the DARPA SafeDocs program and published on
digitalcorpora.org inside `CC-MAIN-2021-31-UNSAFE/corpora-pdf/` (zips
`corpora-pdf-x986.zip` to `x999.zip`, path `corpora-pdf/issue-trackers/<tracker>/`).
About 20,600 PDFs, 15.7 GB. Phase 1 took a stratified sample by tracker,
chosen by sha256 of the member name, files up to 25 MB: pdf.js 60, pdfium 60,
poppler 50, pdfbox 50, sumatrapdf 40, ocrmypdf 40, qpdf 40, mozilla-general 40,
libre-office 30, librepdf 15, poi 10 (435 planned, 432 taken: three members had
no `%PDF` header and were skipped). File names are `<tracker>__<original name>`.
Members were read with HTTP range requests (`bench/corpus/fetch/zip-range-extract.py`);
the zips were not downloaded whole.

Phase 2 raised the quotas, giving more weight to the trackers of viewers and
parsers (all PDFs of the small trackers, and more of pdfbox and pdf.js, whose
phase-1 samples failed most often in the probe). The quotas are totals, and the
sample includes the phase-1 files:

```
python3 -I bench/corpus/fetch/safedocs-sample.py issue-trackers --jobs 4 --quota \
  pdfium=379,poppler=359,sumatrapdf=213,ocrmypdf=187,qpdf=68,librepdf=15,poi=10,\
  pdfbox=800,mozilla-pdfjs=760,mozilla-general=450,libre-office=230
```

Taken: pdfbox 799, mozilla-pdfjs 760, mozilla-general 449, pdfium 379, poppler
351, libre-office 230, sumatrapdf 208, ocrmypdf 183, qpdf 68, librepdf 15,
poi 10. In total, 3,453 files (3.2 GB). Nine members have no `%PDF` header and
are skipped.

Phase 3 added more of pdfbox and mozilla-pdfjs:
`safedocs-sample.py issue-trackers --jobs 4 --quota pdfbox=1600,mozilla-pdfjs=1100`.
pdfbox now has 1,599 and mozilla-pdfjs 1,100; the source has 4,593 files
(4.1 GB). PDFBOX-606-0 has no `%PDF` header.

Why: every file was attached because some viewer or parser got it wrong. The
ocrmypdf files are mostly scans with OCR text layers; sumatrapdf and pdfium
files are viewer rendering bugs.

License: copyright with each attachment's owner; published for research and
testing. The corpus README warns the files were not virus-scanned.

More: list a zip's central directory with `safedocs-sample.py ... --dry-run` (cached in
`staging/safedocs-lists/`) or
`python3 -I bench/corpus/fetch/zip-range-extract.py list <zip url>`; the tracker
counts are mozilla-general 7,129, libre-office 5,183, pdfbox 3,577,
mozilla-pdfjs 2,400, pdfium 379, poppler 359, sumatrapdf 213, ocrmypdf 187,
qpdf 68 (PDF members only). `catalog.csv` in `x998.zip` maps files to issues.

## safedocs-unsafe: SafeDocs fuzzed and minimised PDFs

What: other parts of the same `CC-MAIN-2021-31-UNSAFE/corpora-pdf/` set:
`common-crawl-cmin` and `govdocs-cmin` (Common Crawl and Govdocs1 PDFs reduced
with afl-cmin against poppler's pdftoppm, so each file covers different parser
code), and the hackathon and evaluation sets (`evalThree`, `evalFour`,
`hackathonOne`, `hackathonTwo`, `hackathonThree`, `hackathonOnePrep`): AFL
outputs and real PDFs malformed by grammar-aware and random mutators. Sample
quota: common-crawl-cmin 100, govdocs-cmin 60, evalThree 60, evalFour 40,
hackathonTwo 40, hackathonOne 20, hackathonThree 20, hackathonOnePrep 10, taken
by sha256 of the member name from the zips whose directories were listed (one
zip in 25, plus x966-x999). Members without `%PDF` in the first 4 KB are
skipped. Names without an extension get `.pdf`.

Phase 2 quotas (totals):

```
python3 -I bench/corpus/fetch/safedocs-sample.py unsafe --max-mb 20 --jobs 2 --quota \
  common-crawl-cmin=350,govdocs-cmin=300,evalThree=250,evalFour=150,hackathonTwo=200,\
  hackathonOne=60,hackathonThree=60,hackathonOnePrep=20
```

Taken: common-crawl-cmin 350, govdocs-cmin 300, evalThree 250, hackathonTwo
200, evalFour 150, hackathonOne 60, hackathonThree 60, hackathonOnePrep 19
(1,389 files, 1.2 GB).

Phase 3 listed the 50 `corpora-pdf-x022-00` … `x031-04` zips, which hold
common-crawl-cmin (13,146 members; the other 25 `-NN` zips, x756–x760, are
hackathonTwo), and took 808 more files of at most 5 MB:

```
python3 -I bench/corpus/fetch/safedocs-sample.py unsafe --max-mb 5 --jobs 3 \
  --zips 'corpora-pdf-x0\d\d-\d\d' --quota common-crawl-cmin=850
```

Because the pool and the size limit changed, the phase 1–2 cmin files are mostly
outside this selection; they stay, so common-crawl-cmin now has 1,158 files.

Why: the README says these files crash or hang parsers and parse differently
in different tools. They are for the reliability axis (A6) and for making sure
a probe time limit works. Expect most to render as garbage; what matters is
that the viewer fails cleanly.

License: produced by the SafeDocs program from public PDFs; research and
testing use. Not virus-scanned.

More: 1,060 zips, about 1 TB, ~1.5 million files. Most of the volume is
`evalThree` (zips x035-x735) and `hackathonTwo` (x756-x985). The `TA3` and
`testPDFs` directories were not located in the zips that were listed.

## synth: generated feature files

What: 95 files from `bench/corpus/synth/` (75 in phase 1, 20 added in phase 2) (`uv run bench/corpus/synth/generate.py`,
`--list` prints the generators). Each file is `<generator>__<variant>.pdf`; the
url column is `generated:<generator>`. Most files are written object by object
(`rawpdf.py`), so a file contains only the feature under test plus visible
labels that say what a correct viewer shows.

| generator | variants | what it tests |
|---|---|---|
| `rotate` | mixed, all-90, text-angles | `/Rotate` 0/90/180/270/-90/450, invalid 45, rotation inherited from a Pages node, landscape box; text at angles, mirrored, sheared, Tz/Tc/Tw/Ts |
| `pagesize` | mixed, huge-200in, userunit-2000in, tiny-10pt, strip-200x1in | A0 to business card, 40 in receipt, MediaBox not at origin, CropBox hiding text, `/UserUnit` |
| `transparency` | blend-modes, groups-softmask | all 16 blend modes, isolated/knockout groups, constant alpha on text, luminosity soft mask, image SMask |
| `shading` | types-1-7, patterns | shading types 1 to 7, text filled and stroked with shading and tiling patterns |
| `ocg` | layers | default-off layer containing text, print-only layer, OCMD, form XObject with `/OC` |
| `invisible-text` | ocr-scan, hiding-tricks | JPEG page with render-mode-3 OCR text; Tr 7, white on white, text under rect/image, 0.01 pt text, clipped text, alpha 0, text drawn twice, off-page text |
| `annotations` | all-types, rotated-page | links (URI, GoTo, named), note, popup, FreeText, line, square, circle, polygon, ink, markup, stamp, attachment, hidden/NoView/print flags |
| `forms-raw` | need-appearances | AcroForm without appearance streams: text, multiline, comb, password, checkbox, radio, combo, list, button, signature, hierarchical names |
| `forms` | reportlab-acroform | AcroForm with appearance streams |
| `text-mapping` | wrong-tounicode, actualtext-ligatures, reading-order | ToUnicode that shifts letters or maps to the Private Use Area; fi/fl glyphs, ActualText; columns drawn right first, words drawn right to left, spaces only from TJ kerning |
| `type3` | vector-no-tounicode, bitmap-glyphs | Type 3 vector glyphs with private names; 1-bit image-mask glyphs |
| `tounicode-stripped` | latin-truetype, cjk-truetype | embedded TrueType subsets with the ToUnicode map removed |
| `base14` | standard-14, nonembedded-truetype | non-embedded base-14 fonts incl. Symbol and ZapfDingbats; non-embedded Arial, Calibri, Garamond, Wingdings and a made-up font name |
| `cjk` | nonembedded-cid, nonembedded-vertical | non-embedded Adobe-Japan1/GB1/CNS1/Korea1 CID fonts, vertical `UniJIS-UCS2-V` |
| `browser` | cjk, vertical-cjk, rtl, complex-scripts | Chrome print-to-PDF: Japanese, Chinese, Korean, ruby, vertical writing, Arabic, Hebrew, Persian, Urdu, bidi, Devanagari, Thai, emoji |
| `tex` | dvips-type3-300dpi, dvips-type3-600dpi, dvips-type1, pdflatex-t1-bitmap, pdflatex-no-tounicode, pdflatex-glyphtounicode | latex + dvips with an empty font map (PK bitmap fonts become Type 3 in ps2pdf), dvips Type 1, pdflatex with T1 encoding and no cm-super (Type 3), with and without ToUnicode |
| `book` | 2000-pages | pdflatex book, 2,089 pages, 40 chapters, outline, roman front-matter page labels, math, footnotes |
| `pagetree` | 10000-pages-flat, 10000-pages-balanced, 1000-deep-chain | 10,000 small pages in flat and balanced trees; a page tree 1,000 levels deep |
| `encrypt` | owner-only-rc4-40, -rc4-128, -aes128, -aes256, user-password-aes256, user-password-rc4-128 | owner password only (opens without a prompt, copy forbidden); user password `test` |
| `structure` | object-streams, linearized, pdf-2.0, version-1.0-header-1.7-catalog | valid structural variants |
| `damaged` | 18 variants | truncated at 50 %/90 %/no `%%EOF`, wrong startxref, shifted xref offsets, no xref, junk before the header, no header, trailing junk, wrong `/Length`, missing objects, wrong `/Count`, cyclic page tree, corrupt Flate data, truncated object streams, header `%PDF-9.9`, empty file, HTML named `.pdf` |
| `incremental` | three-revisions, deleted-page, broken-prev | appended updates: replaced content and added annotation (xref table), added page (xref stream), page removed and freed, `/Prev` off by five bytes |
| `markup` (phase 2) | with-appearances, without-appearances, rotated-pages, many-highlights, appearance-transforms | pages of body text with highlights (incl. two-line), underline, strikeout, squiggly, ink, FreeText, stamp, note with popup, square, circle; the same without `/AP`; on `/Rotate` 90/180/270 pages; 420 highlights over 10 pages; AP BBox scaled into Rect, 30° `/Matrix` stamp, `/AS` appearance states |
| `text-overlay` (phase 2) | translucent-rects, watermark-over, watermark-under, softmask-text, text-over-image | translucent and Multiply/Screen rects over lines of text; diagonal 25 % watermark after or before the text; body text in a group under a luminosity soft mask; text over a full-page image with blended title |
| `pageboxes` (phase 2) | crop-rotate-grid, crop-outside-media, negative-and-inverted, inherited-boxes, fractional-boxes, all-boxes-differ | 16 pages: four CropBoxes x `/Rotate` 0/90/180/270, each labelled with the expected visible size; CropBox past, outside or equal to MediaBox, zero-area; negative, reversed and inverted boxes; MediaBox/CropBox/Rotate inherited from a Pages node; fractional boxes and `/UserUnit` with CropBox; Bleed/Trim/Art boxes all different |
| `forms-ap` (phase 2) | acrobat-style, rotated-widgets, stale-appearance, flags | widgets with explicit `/AP`: alignments, auto font size, comb, multiline, password, checkboxes with down states, radios with custom state names, combo, list, button, signature; `/MK /R 90` on a rotated page; `/AP` that disagrees with `/V`; Hidden, NoView, ReadOnly, Locked, non-print flags |

Tools used: pikepdf, ReportLab and Pillow (inline script dependencies, Python
3.13 through `uv`), TeX Live (`latex`, `dvips`, `pdflatex`), Ghostscript
`ps2pdf`, and Google Chrome for `browser`. `tex__pdflatex-t1-bitmap` gives Type 1
fonts instead of Type 3 on a TeX installation that has cm-super.

License: CC0 for the generated files, except `browser` and
`tounicode-stripped`, which embed subsets of macOS system fonts and are for
local test use only.

Regenerate: `uv run bench/corpus/synth/generate.py [--only <generator>...] [--force]`.
Files are written under a `.part` name and renamed before their row is added.

## Not taken

- veraPDF, pdf.js links and SafeDocs: see "More" in each section.
- Other candidates for a bulk phase: the BFO PDF/A-2 test suite
  (github.com/bfosupport/pdfa-testsuite), the Apache Tika regression corpus
  (`corpora.tika.apache.org`, which holds the full issue-tracker set), the
  Ghostscript and PDFBox bug attachments (Ghostscript is not in the SafeDocs
  set), and Isartor in its original form (already inside veraPDF).
