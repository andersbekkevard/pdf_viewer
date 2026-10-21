# Real-world sources

Openly accessible real-world PDFs: a phase 1 sample (2026-10-20) and a phase 2
bulk download (2026-10-21).
Each section says what the source is, why it is in the corpus, the license or
terms, what was taken, how much more exists, and how to fetch more. Files are in
`$PDFV_CORPUS_DIR/incoming/<source>/` with one `_files.tsv` row per file
(filename, url, license, and in phase 2 often a fourth labels column). The filename prefix before `__` is a label (for
example `arxiv-1992-hepth`, `ocw-18.650-beamer`).

Helper scripts are in [`../fetch/`](../fetch/):

| script | what it does |
|---|---|
| `fetch-one.sh <source> <url> <filename> <license> [max_mb]` | downloads to `.part/`, checks for `%PDF-` in the first 1 KB, moves into place, then appends the `_files.tsv` row; refuses to run below 55 GB free |
| `arxiv-sample.py <plan.tsv>` | arXiv API query per (label, query, date range, count), one request every 3 s |
| `zip-range-extract.py list|get <zip_url> ...` | reads a remote ZIP's central directory and extracts single members with HTTP range requests (ZIP64, stored and deflate) |
| `ocw-sample.sh <label> <page_url> <count>` | follows `/resources/` links on an MIT OCW page and fetches each resource's PDF |
| `who-iris-sample.py <lang>:<n> ...` | WHO IRIS DSpace 7 REST search by `dc.language.iso`, downloads the first PDF bitstream of each item |
| `page-pdfs.py <source> <label> <page_url> <count> <license> [regex]` | spread-samples the `.pdf` links on one HTML page |

All requests send `User-Agent: pdfv-corpus/0.1 (...)` and run sequentially with
1–3 s pauses.

## Totals

Phase 1 (2026-10-20) took a sample from each source. Phase 2 (2026-10-21)
bulk-downloaded the sources weighted by the probe's failure rates; see
[Phase 2](#phase-2) at the end. MB is `du -sm` of the source directory.

| source | phase 1 files | phase 2 files | total files | total MB |
|---|---|---|---|---|
| arxiv | 40 | 1,409 | 1,449 | 1,562 |
| commoncrawl-cc-main-2021-31 | 126 | 2,065 | 2,191 | 2,304 |
| openstax | 5 | 5 | 10 | 2,062 |
| mit-ocw | 32 | 600 | 632 | 481 |
| internet-archive | 15 | 56 | 71 | 1,609 |
| gov-irs | 16 | 103 | 119 | 56 |
| gov-govinfo | 11 | 0 | 11 | 29 |
| gov-nasa-ntrs | 21 | 100 | 121 | 695 |
| gov-uspto | 17 | 0 | 17 | 18 |
| gov-japan | 6 | 0 | 6 | 6 |
| who-iris-multilingual | 14 | 150 | 164 | 215 |
| wikimedia-commons | 16 | 62 | 78 | 467 |
| datasheets | 16 | 0 | 16 | 49 |
| usgs-geopdf | 6 | 10 | 16 | 310 |
| sheet-music | 15 | 104 | 119 | 108 |
| magazine-layout | 6 | 0 | 6 | 18 |
| ctan-docs | 12 | 22 | 34 | 76 |
| forms-annotations | 0 | 138 | 138 | 158 |
| **total** | **374** | **4,824** | **5,198** | **~10,200** |

## arxiv

**What**: arXiv papers sampled by era and category: 1992 hep-th, 1995 cond-mat,
1997 astro-ph, 1998 math, 1999 cs, 2002 quant-ph, 2005 gr-qc, 2008 math.PR,
2011 stat.ML, 2014 q-fin, 2017 cs.CV, 2019 econ, 2021 cs.CL, 2023
physics.optics, 2024 math.AG, 2025 cs.LG, plus abstracts mentioning "in Chinese"
and "in Russian". `_arxiv-ids.tsv` records id, label, primary category and title.

**Why**: the main reading material. Producers in the sample: arXiv's
Ghostscript 9.22 re-distillation of 1990s and 2000s dvips output (Type 1C fonts
without ToUnicode, non-embedded base-14 Times), `dvips + Ghostscript`, pdfTeX
1.40.12–1.40.25, Word 2016 and Office 365, Acrobat Distiller 5, iTextSharp and
pikepdf (author-supplied PDFs). Seven files contain Type 3 fonts; 39 of 40 have
at least one font without a ToUnicode map, which matters for find and copy.
arXiv does not compile XeLaTeX or LuaLaTeX, so those producers are covered by
`ctan-docs` instead (an `abs:xelatex` query returned nothing usable).

**License**: arXiv's non-exclusive distribution licence or the author's CC
licence, per paper. Fetched only through `export.arxiv.org`, one request every
3 seconds.

**More**: about 2.9 million papers. Method: write more rows into a plan TSV and
run `python3 -I bench/corpus/fetch/arxiv-sample.py plan.tsv`
(`label<TAB>search_query<TAB>YYYYMMDD<TAB>YYYYMMDD<TAB>count`). At 3 s per
request that is about 14,000 papers per day including the API calls. IDs for
targeted pulls can come from OAI-PMH (`https://export.arxiv.org/oai2?verb=ListRecords&metadataPrefix=arXiv&set=physics:hep-th`).
arXiv's S3 bulk bucket is requester-pays and therefore out of scope.

## commoncrawl-cc-main-2021-31

**What**: the DARPA SafeDocs / digitalcorpora.org re-crawl of every PDF in Common
Crawl CC-MAIN-2021-31, untruncated, deduplicated by SHA-256. 66 files were picked
from `0000.zip` using the published pdfinfo table to cover one or two files per
producer family (InDesign, Word, Excel, PowerPoint, LibreOffice, OpenOffice,
Quartz, Skia/Chrome, pdfTeX, XeTeX, dvips, Ghostscript, iText, ReportLab,
TCPDF, FPDF, dompdf, wkhtmltopdf, Prince, Crystal Reports, QuarkXPress,
Illustrator, Photoshop, Pages, Canon/Ricoh/Xerox/Konica scanners, Qt, cairo,
PDFium), plus files with pdfinfo errors, AcroForms, JavaScript, more than 300
pages, rotation and A0/A1 page sizes. A further 60 files (prefix
`random4500__`) are a uniform random sample from `4500.zip` for estimating
failure rates on unselected web PDFs.

**Why**: the widest producer and feature spread available in one place, and the
best estimate of what arbitrary web PDFs do to each pipeline.

**License**: Common Crawl terms of use; each document's copyright stays with its
owner. Research and testing use only; do not redistribute.

**Files**: `_files.tsv` URLs are `<zip_url>#<member>`. One selected member,
`0000819.pdf`, was rejected because it has no `%PDF-` header in the first 1 KB
(pdfinfo also failed on it in the published metadata).

**More**: 7,933 ZIPs, about 7.9 million PDFs, about 8 TB.
URL pattern: `https://digitalcorpora.s3.amazonaws.com/corpora/files/CC-MAIN-2021-31-PDF-UNTRUNCATED/zipfiles/NNNN-NNNN/NNNN.zip`
(for example `0000-0999/0000.zip`, `4000-4999/4500.zip`); each ZIP is 1.0–2.8 GB
and holds about 1,000 PDFs. Whole ZIPs exceed the per-source cap, so use
`zip-range-extract.py list <zip>` and `get <zip> <source> <license> <members...>`
to pull members. For targeted selection by producer, page count, page size,
forms or parse errors, download the metadata tables in
`.../CC-MAIN-2021-31-PDF-UNTRUNCATED/metadata/`: `pdfinfo-20230315.csv.gz`
(329 MB, all files), `tika-20230714.csv.gz` (448 MB), `cc-hosts-20230303.csv.gz`
(248 MB, host and country), plus 1k-row samples for `0000.zip`. File
`NNNNNNN.pdf` is always in ZIP `NNNN`.

## openstax

**What**: five OpenStax textbooks: Chemistry 2e (1,203 pages, 213 MB),
University Physics Volume 1 (959 pages, 82 MB), Calculus Volume 1 (769 pages,
51 MB), Principles of Microeconomics 3e (29 MB) and Introduction to Python
Programming (10 MB).

**Why**: long textbooks with heavy colour figures, math, tables and margin
features; this is the conversion-time, memory and page-count stress case.

**License**: per book, from the OpenStax CMS API: most current books are
CC BY-NC-SA 4.0, some CC BY 4.0; the Spanish books report no license field. The
license string is in each `_files.tsv` row.

**More**: 84 live books (73 English, 11 Spanish) totalling about 8.5 GB, from
9 MB (Introduction to Python Programming) to 476 MB (Anatomy and Physiology 2e)
and 401 MB (Biology 2e); 34 retired and 8 unlisted books also have PDFs.
List with sizes:
`curl "https://openstax.org/apps/cms/api/v2/pages/?type=books.Book&fields=title,high_resolution_pdf_url,book_state,license_name&limit=250"`,
then HEAD each `high_resolution_pdf_url`. URL pattern:
`https://assets.openstax.org/oscms-prodcms/media/documents/<Title>_-_WEB.pdf`.

## mit-ocw

**What**: 32 PDFs from 11 MIT OpenCourseWare courses: Beamer slides (18.650
Fall 2016), PowerPoint-derived slides (6.0001 Fall 2016, 15.401 Fall 2008),
handwritten lecture notes scanned or tablet-written (6.851 Spring 2012
`MIT6_851S12_L*`, 6.046J Spring 2015 `writtenlec*`), typed lecture notes (8.04
Spring 2016, 6.046J, 18.03 Spring 2010), problem sets with solutions (18.06
Spring 2010), labs (6.034 Fall 2010), exams and reviews (15.401, 18.03) and the
6.042J textbook chapter. Two files labelled `ocw-15.401-ppt__<id>.pdf` are in
fact wkhtmltopdf-rendered video transcripts, not slides.

**Why**: Anders' actual reading at MIT: slides with odd page sizes, handwritten
notes (image or ink paths with little text), Word and Distiller output.

**License**: CC BY-NC-SA 4.0 (MIT OpenCourseWare).

**More**: about 2,500 courses; robots.txt allows everything. Course list:
`https://ocw.mit.edu/sitemap.xml`. Per page:
`bench/corpus/fetch/ocw-sample.sh <label> <course page url> <count>`. Many
section URLs under `/pages/` redirect to `/resources/<section>/`, which is
rendered client-side and has no links; use the `/pages/` URL of each lecture or
the course's `/pages/lecture-notes/` style page. Each course also has a
"Download course" ZIP on its home page for whole-course pulls.

## internet-archive

**What**: 15 public-domain scanned books (1874–1925) with OCR text layers:
Maxwell's Scientific Papers (668 pages), Archimedes, Fermat (grayscale
derivative), Weyl's Space–Time–Matter, Gray on Bessel functions, Smithsonian
physical tables, a textbook of entomology (762 pages, plates), Baum's Wizard of
Oz (grayscale), a Tagalog dictionary, Pitman shorthand, a drawing manual, the
Aryabhatiya (Devanagari), a CIHM microform scan, and two Google Books scans
(German, mathematical tables).

**Why**: scanned pages with invisible OCR text (render mode 3), JPEG 2000 and
JBIG2-style compression ("Internet Archive PDF 1.4.x", "Recoded by
LuraDocument", "Google Books PDF Converter"), 300–770 pages each. These test the
raster path, invisible-text handling, page count and memory.

**License**: public domain (pre-1929 publications; most items carry
`possible-copyright-status: NOT_IN_COPYRIGHT`). Avoid items with
`access-restricted-item` (lending library).

**More**: millions of texts. Search API:
`https://archive.org/advancedsearch.php?q=<query>&fl[]=identifier&rows=N&output=json`
(for example `collection:americana AND mediatype:texts AND year:[1850 TO 1900]`:
1,820 hits with `subject:mathematics`; `collection:toronto ... subject:physics`:
340; `collection:cdl AND year:[1890 TO 1925]`: 123,783;
`language:jpn AND year:[1500 TO 1928]`: 11,426). File list per item:
`https://archive.org/metadata/<id>`; take the file whose `format` is
`Text PDF` (or `Grayscale PDF` / `Image Container PDF`) and fetch
`https://archive.org/download/<id>/<file>`. Downloads ran at about 1 MB/s.

## gov-irs

**What**: 16 IRS forms, instructions and publications: Form 1040 (XFA plus
AcroForm), 1040-NR, 1040-SP (Spanish), Schedule 1, W-4, W-9, 8949, 8843,
Publication 17 (tax guide), 15, 519, the 1040 general instructions, and prior
years: Form 1040 for 1964, 1980 and 1995 and the 1975 instructions (scans).

**Why**: fillable forms (AcroForm and XFA), dense small type, and old scanned
forms; these are the forms Anders actually reads.

**License**: US federal government work, public domain.

**More**: about 2,000 current forms and publications under
`https://www.irs.gov/pub/irs-pdf/` and tens of thousands of prior-year files
under `https://www.irs.gov/pub/irs-prior/<form>--<year>.pdf`. robots.txt
disallows the forms search pages, so build URL lists from known form numbers
rather than crawling the search.

## gov-govinfo

**What**: GAO reports and decisions from 2001 and 2008 (six files), the FY2025
US Budget, the Federal Register of 2024-01-02 (three-column, 13 MB), the
Congressional Record of 2024-03-07, CFR Title 26 volume 1 and Public Law
117-169.

**Why**: replaces gao.gov and cbo.gov, which both return HTTP 403 (Akamai bot
protection) to scripted requests. govinfo serves the same GAO reports for
1994–2008 and other dense multi-column government typesetting.

**License**: US federal government work, public domain.

**More**: per-collection sitemaps, for example
`https://www.govinfo.gov/sitemap/GAOREPORTS_sitemap_index.xml` (20 yearly
sitemaps, about 700–1,100 reports each). PDF URL from a package id:
`https://www.govinfo.gov/content/pkg/<PKG>/pdf/<PKG>.pdf`. The three 1994 GAO
packages tried have no PDF (the URL returns an HTML error page). The same
pattern covers `BUDGET-<year>-BUD`, `FR-<date>`, `CREC-<date>`,
`CFR-<year>-title<N>-vol<M>` and `PLAW-<congress>publ<N>`. CBO reports are not
on govinfo and were not obtained.

## gov-nasa-ntrs

**What**: 21 NASA technical reports in six eras: 1930s–40s NACA reports
(scanned, Acrobat Paper Capture), 1960s Apollo documents (272-page
proceedings), 1970s Space Shuttle documents (493 and 336 pages, scanned), 1985–95
composite-structures reports, a 2009 Quartz-made slide deck, and 2019–2025
Distiller, LuaTeX and Quartz output.

**Why**: old scans with OCR layers from several OCR engines, typewritten
equations, fold-out figures, and modern mixed producers.

**License**: US government work; only records with `distribution: PUBLIC` were
taken.

**More**: 648,157 records in total, 189,023 published up to 1979 (not all have a
PDF). API: `https://ntrs.nasa.gov/api/citations/search?q=<q>&published.gte=YYYY-MM-DD&published.lte=YYYY-MM-DD&page.size=N`;
each result's `downloads[].links.pdf` is a path under `https://ntrs.nasa.gov`.
robots.txt allows everything.

## gov-uspto

**What**: 17 US patents: Bell's telephone (174,465, 1876), Edison's lamp
(223,898), the Wright brothers (821,393), patent number 1,647, the transistor
(2,524,035), round numbers 3, 4, 5, 6, 9, 10 and 11 million, 7,654,321, a design
patent (D500000), a plant patent (PP20000), a reissue (RE40000) and an
application publication (20200000001).

**Why**: image-only scanned pages for everything before about 1976 and the
USPTO's image-wrapped PDFs after that; tests the no-text path and page-size
consistency.

**License**: US government work, public domain.

**More**: over 12 million granted patents plus applications.
`https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/<number>`;
numbers below 1,000,000 must be zero-padded to seven digits (`0174465`),
otherwise HTTP 400. Design, plant and reissue use `D`, `PP`, `RE` prefixes.

## gov-japan

**What**: four PDFs from the Japanese Ministry of Finance FY2024 budget page
(tables in Japanese) and two Bank of Japan research papers.

**Why**: born-digital Japanese (CID fonts, Shift-JIS/Unicode CMaps).

**License**: Government of Japan Standard Terms of Use (compatible with
CC BY 4.0); BOJ allows reuse with attribution.

**More**: `page-pdfs.py gov-japan <label> <page> <n> <license>` against any
ministry index page; the MOF page alone links 36 PDFs. The official gazette
(kanpo.go.jp) disallows `/20*` in robots.txt and was not used.

## who-iris-multilingual

**What**: WHO IRIS documents in Arabic (4), Chinese (4) and Russian (4), plus
two English files that the Persian (`fa`) language filter returned
(`who-fa__*`, mislabelled; they are English).

**Why**: replaces UN documents. `documents.un.org` disallows `/doc`, `/api` and
`/access` in robots.txt, and `digitallibrary.un.org` answers record pages with
an empty HTTP 202 bot challenge. WHO publishes the same kind of multilingual
UN-family reports, typeset in Arabic (RTL, shaping), Chinese and Russian.

**License**: mostly CC BY-NC-SA 3.0 IGO; see each item's handle.

**More**: 16,783 Arabic, 12,556 Chinese, 25,656 Russian, 25,952 Spanish and
89,530 French items. Method:
`python3 -I bench/corpus/fetch/who-iris-sample.py ar:N zh:N ru:N` (DSpace REST
at `https://iris.who.int/server/api`; robots.txt only disallows the web UI
search pages).

## wikimedia-commons

**What**: 16 PDFs found by Commons full-text search with script-specific terms:
Japanese (a born-digital Aozora Bunko vertical-text edition of Dazai, a MEXT
manual, an NDL Meiji-era scan), Persian (1970s Ettelaat newspaper scan),
Arabic (two books and one English book about Egypt), Chinese (Taiwan National
Central Library scan of a ROC law compilation), Korean (a 2020 election district
list and a 1947 Seoul newspaper scan), Hebrew (three files), Hindi (an English
cyclone report), Thai (a calendar) and Greek (a CC BY thesis). Some matches are
in English despite the search term; the language prefix in the filename is the
search language, not a verified document language. The title of each file is in
the license column of `_files.tsv`.

**Why**: the only openly scriptable source found for Hebrew, Persian and Korean
PDFs, and for vertical Japanese.

**License**: per file (public domain, CC0, CC BY, CC BY-SA); in `_files.tsv`.

**More**: about 6.96 million PDF files on Commons. API:
`https://commons.wikimedia.org/w/api.php?action=query&list=search&srnamespace=6&srsearch=filemime:application/pdf filesize:<30000 <terms>`,
then `prop=imageinfo&iiprop=url|size|extmetadata` for URLs and licenses;
`intitle:<word in script>` gives cleaner language matches. Send a descriptive
User-Agent and keep to about one request per second.

## datasheets

**What**: ten Texas Instruments datasheets (LM358, NE555, TPS54331,
MSP430G2553, BQ24075, OPA2134, SN74HC595, TL072, ADS1115, CC2640R2F), Microchip
ATmega328P and PIC16F84A, Infineon IRFZ44N, Espressif ESP32, the Raspberry Pi
RP2040 datasheet (Asciidoctor output) and the Raspberry Pi 4 schematics.

**Why**: dense vector diagrams, tables, rotated text, many fonts; five of the
16 contain Type 3 fonts.

**License**: vendor copyright; freely downloadable without login; for local
testing only.

**More**: TI: any part at `https://www.ti.com/lit/ds/symlink/<part>.pdf`
(tens of thousands of parts). Microchip, Infineon, Espressif and Raspberry Pi
serve direct URLs. ST (`st.com`) and Analog Devices (`analog.com`) time out to
scripted requests (bot protection) and NXP's tried URL returned 404.

## usgs-geopdf

**What**: two modern US Topo GeoPDFs (Ashburnham MA 2012 and 2021, Boston South
2024; 18–47 MB, a single page of 1728 × 2088 pt with optional-content layers)
and three Historical Topographic Map Collection scans (Boston South 1944 at
1:24,000, Boston 1943 at 1:125,000, Boston 1985 at 1:100,000).

**Why**: huge single pages, OCG layers, georeferencing dictionaries, very
large embedded rasters and dense vector line work; the hardest rendering case
in the sample.

**License**: USGS, US government work, public domain.

**More**: S3 bucket `https://prd-tnm.s3.amazonaws.com/` with prefixes
`StagedProducts/Maps/USTopo/PDF/<STATE>/` (every quad, several editions each;
Massachusetts alone has 500+ PDFs) and
`StagedProducts/Maps/HistoricalTopo/PDF/<STATE>/<scale>/` (about 190,000
historical maps). List with `?list-type=2&prefix=...`, or use the TNM API:
`https://tnmaccess.nationalmap.gov/api/v1/products?datasets=Historical%20Topographic%20Maps&bbox=<w,s,e,n>&prodFormats=GeoPDF`
(the `US Topo Current` dataset name returned 0 there; the S3 listing works).

## sheet-music

**What**: ten Mutopia Project engravings (LilyPond, A4: Bach, Mozart,
Beethoven, Chopin, Satie) and five Commons scores (an 1840s Viennese print, an
18th-century manuscript opera score of 19 MB, a CC BY lead sheet, a Renaissance
madrigal, an 1846 Polish piano print).

**Why**: pages made almost entirely of music-font glyphs and vector lines, and
manuscript scans.

**License**: Mutopia pieces are public domain or CC BY / CC BY-SA; Commons
license per file in `_files.tsv`.

**Not used**: IMSLP. Its robots.txt disallows `/images/`, `/imglnks/` and
`/wiki/File:` (all download paths), and downloads need a disclaimer click.

**More**: about 2,100 Mutopia pieces; per composer
`https://www.mutopiaproject.org/cgibin/make-table.cgi?Composer=<Name>` and
`page-pdfs.py sheet-music <label> <url> <n> <license> '-a4\.pdf$'`. Commons
search `incategory:"Sheet music" filemime:application/pdf` has 195 hits under
20 MB; wider Commons music categories have more.

## magazine-layout

**What**: three Federal Reserve Monetary Policy Reports (2013, 2019, 2026), the
BIS Annual Economic Report 2024, and two NASA History Series books (one tagged
PDF).

**Why**: designed report layouts (InDesign-style multi-column pages, sidebars,
charts, full-bleed colour). More InDesign, QuarkXPress and Word magazine files
are in the Common Crawl sample.

**License**: Federal Reserve and NASA: US government work, public domain. BIS:
reproduction permitted with attribution.

**More**: the Fed MPR page links 37 PDFs; NASA History Series pages link one PDF
each (`https://www.nasa.gov/history/history-publications-and-resources/nasa-history-series/`).
regjeringen.no (Norwegian NOU reports) is behind a Cloudflare JavaScript
challenge and was not used.

## ctan-docs

**What**: 12 package manuals from CTAN: `pgfmanual.pdf` (1,324 pages, LuaTeX,
vector-graphics heavy), `luatex.pdf`, `biblatex.pdf`, `bxjscls-manual.pdf`
(LuaTeX, Japanese), `fontspec.pdf`, `unicode-math.pdf`, `newcm-doc.pdf`,
`lshort.pdf`, `xeCJK.pdf` (XeTeX/xdvipdfmx, Chinese), `memman.pdf` (625 pages),
`tcolorbox.pdf` (567 pages), `beameruserguide.pdf` (pdfTeX).

**Why**: the XeLaTeX (xdvipdfmx) and LuaLaTeX producers that arXiv cannot
supply, OpenType and Unicode math fonts, and very long vector-heavy manuals.

**License**: per package, mostly LPPL 1.3c; some GPL or public domain.

**More**: about 6,000 CTAN packages ship PDF documentation. URL:
`https://mirrors.ctan.org/<path in CTAN tree>`; the path for each package's
documentation is on `https://ctan.org/pkg/<name>` (for example pgf's manual is
under `graphics/pgf/base/doc/generic/pgf/`).

## Phase 2

Phase 2 followed the probe's failure rates on 30 documents per source (mit-ocw
88 %, sheet-music 80 %, internet-archive 73 %, arxiv 45 %, who-iris 36 %,
commoncrawl and ctan-docs 25 %, nasa-ntrs, irs and commons 19 %; govinfo,
datasheets, uspto, openstax and magazine-layout low) and the features that
failed most (annotations, transparency, forms, RTL). uspto, govinfo, datasheets,
magazine-layout and gov-japan were not extended. Every plan file used is in
`../fetch/` so the download can be repeated; the seeds are given below.

| source | added | method (all scripts in `../fetch/`) |
|---|---|---|
| arxiv | 1,409 | `arxiv-sample.py arxiv-plan-phase2.tsv`: 350 rows, 42 papers per year 1991–2026, each year split over 5–10 category groups (pre-1999 old archives such as `alg-geom`, `chao-dyn`, `cmp-lg`; later `cs.*`, `math.*`, `stat.*`, `econ.*`/`q-fin.*`, `q-bio.*`/`eess.*`, physics), one random month per row. Per decade: 1990s 324, 2000s 399, 2010s 420, 2020s 302 (totals including phase 1). Early years have fewer papers than requested; 7 PDFs returned errors (withdrawn papers). The label is the query group; `_arxiv-ids.tsv` has each paper's actual primary category. |
| commoncrawl-cc-main-2021-31 | 2,065 | `cc-random.py 10 48 15 <seed>` with seeds 101–104 plus a stopped run with seed 20261021: 2,006 uniform random members up to 15 MB from 44 random zips (prefix `random<zip>__`). Plus 59 Arabic, Hebrew, Persian or Urdu documents (prefix `rtl__`, by Tika `tika_eval_lang`) selected by `cc-tika-select.py`. |
| openstax | 5 | `openstax-fetch.sh`: Anatomy and Physiology 2e, Biology 2e, Microbiology, Workplace Software and Skills, College Physics 2e (263–476 MB each; Biology 2e has the most pages). |
| mit-ocw | 600 | `ocw-bulk.py 130 6 620 2026` (289 files, prefix `ocw2-<dept>-<class>__`): courses drawn round-robin over all departments from the sitemap, course files classified by name. `ocw-learn.py` with `ocw-learn-plan-phase2.tsv` (seed 2026) and `ocw-learn-plan-phase2-b.tsv` (seed 77) (311 files, prefix `ocw3-<label>__`): MIT Learn search (`https://api.learn.mit.edu/api/v1/content_file_search/?platform=ocw`) for slides, PowerPoint, Beamer, handwritten and scanned notes, problem sets and solutions, exams and solutions, lecture notes, recitations, open textbooks and "annotated" files. ocw3 counts: slides 59, slides-ppt 20, slides-beamer 6, handwritten 61, pset 35, pset-sol 20, exam 35, exam-sol 15, notes 30, recitation 10, textbook 10, annotated 10. Labels come from the search query, not from inspecting the file. |
| internet-archive | 56 | `ia-bulk.py ia-plan-phase2.tsv 40 2026`: 1700s and 1800s Americana, Toronto science books, CDL, Biodiversity Heritage Library, Google Books scans, CIHM microform, and German, French, Latin, Japanese, Chinese, Arabic, Hebrew, Russian and Persian books (label `ia2-<group>`); public domain by year 1928 or earlier, or `NOT_IN_COPYRIGHT`; each under 40 MB. |
| gov-irs | 103 | `irs-forms.sh`: 74 current forms and schedules (many with XFA or AcroForm fields), 10 instructions, 19 prior-year forms and publications from 1913 to 2020 (prefixes `irs2-form`, `irs2-instr`, `irs2-prior`). Some prior-year stems do not exist and returned 404. |
| gov-nasa-ntrs | 100 | `ntrs-bulk.py ntrs-plan-phase2.tsv 40 2026`: 50 published before 1980 (1915–1979 scans) and 50 from 1980–2026. |
| who-iris-multilingual | 150 | `SEED=2026 LABEL_PREFIX=who2 who-iris-sample.py ar:50 zh:50 ru:50`: random result pages over each language, preferring the bitstream whose name carries the language suffix. |
| wikimedia-commons | 62 | `commons-search.py` with `commons-plan-phase2-multilingual.tsv` (seed 2026), `-b.tsv` (seed 77) and `commons-plan-phase2-legacyfont.tsv` (seed 7). The fourth `_files.tsv` column records the script check: `script-<x>` means at least 20 % of the extracted letters in the first 3 pages are in that script; `script-<x>-unverified` means the file has no extractable text (a scan). Files whose text was in another script were discarded, except 4 Bangladesh Open University Bengali files (prefix `commons2-bn-legacyfont__`): their text extracts as Latin characters because they use a legacy non-Unicode Bengali font encoding, which is itself a text-layer test case. Thai, Amharic, Burmese and Georgian searches found nothing. |
| usgs-geopdf | 10 | `usgs-bulk.py 2026 50 CO:ustopo AK:ustopo HI:ustopo AZ:ustopo NY:ustopo CA:hist/24000 WA:hist/62500 TX:hist/250000 UT:hist/24000 PR:ustopo`. |
| sheet-music | 104 | `mutopia-bulk.sh 45 2 2026` and `mutopia-bulk.sh 30 2 77` (88 Mutopia A4 scores, prefix `mutopia2-<composer>__`), and `commons-search.py sheet-music commons-plan-phase2-music.tsv 30 2026` (16 Commons scores, many manuscript or print scans). |
| ctan-docs | 22 | `ctan-fetch.sh` with package:regex specs (KOMA-Script guide, interface3, pgfplots, listings, luatexja, polyglossia, babel code, hyperref, siunitx code, ctex, jlreq, bidi, xepersian, arabxetex, kotex, luaotfload, chemfig, tabularray, pst-node) and direct URLs for `source2e.pdf`, `source3.pdf` and `xetex-reference.pdf`. These include XeTeX and LuaTeX output in Chinese, Japanese, Korean, Arabic and Persian. ConTeXt manuals from pragma-ade.com returned 404. |
| forms-annotations (new) | 138 | `cc-tika-select.py <tika csv> 2026` then `uv run --no-project --with pypdfium2 python -I cc-forms-annots.py cc-tika-candidates-phase2.tsv <scratch> 70 15`. 60 Common Crawl PDFs with XFA (`cc-xfa__`), 58 with AcroForm fields and no XFA (`cc-acroform__`), and 20 with markup annotations (`cc-annot__`). Annotation candidates were 1,500 incrementally updated PDFs from 60 zips; each was opened with PDFium and kept only if a page has a markup annotation (free text 10, highlight 6, square 3, stamp 3, strikeout 1, text note 1; files can have several). About 1 % of candidates qualified. |

**Metadata used for selection**: the Common Crawl corpus's Tika table
(`metadata/tika-20230714.csv.gz`, 448 MB, kept outside the corpus) has `has_xfa`
(4,346 files), `pdf_has_acroform_fields` (159,006 files), `tika_eval_lang`
(26,535 Arabic, Hebrew, Persian or Urdu files) and `pdf_incremental_updates`
(13,999 candidates in the 60 sampled zips). It has no annotation fields, so
annotated files have to be found by opening candidates.

**Throughput**: the digitalcorpora S3 bucket gave about 0.3 MB/s per
connection. Four `cc-random.py` workers ran in parallel; every other source
ran as one sequential process. arXiv took about 4 hours at one request every 3
seconds.

## Sources tried and not used

| source | result |
|---|---|
| undocs.org / documents.un.org | robots.txt disallows `/doc`, `/api`, `/access`. Three probe requests to `/api/symbol/access` returned PDFs before robots.txt was read; nothing was kept. Replaced by WHO IRIS. |
| digitallibrary.un.org | record pages return an empty HTTP 202 bot challenge |
| gao.gov, cbo.gov | HTTP 403 (Akamai). GAO replaced by govinfo; CBO not covered |
| IMSLP | download paths disallowed by robots.txt |
| kanpo.go.jp (Japanese gazette, vertical text) | robots.txt disallows `/20*` |
| st.com, analog.com | connection timeouts to scripted requests |
| regjeringen.no | Cloudflare challenge |
| NVA / NTNU Open (Norwegian theses) | search API works (`https://api.nva.unit.no/search/resources?instanceType=DegreeMaster&query=NTNU`, 6,057 hits) but the file download endpoint tried returned 403; not pursued |
| Korean and Hebrew government sites (kdi.re.kr, bok.or.kr, boi.org.il, knesset.gov.il, gov.il) | PDF links are rendered by JavaScript or blocked; Commons used instead |
