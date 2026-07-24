# Changelog

All notable changes to **Alpha-X Document Center**.

Format follows [Keep a Changelog](https://keepachangelog.com/).
Versioning is [Semantic Versioning](https://semver.org/).

---

## [1.7.0] — 2026-07-24

### Added
- **Print Labels button in the list view toolbar**, for document types that
  actually have a label print format. Bulk Print remains under Actions for
  everything else. Tagging is a repeated task; burying it two menus deep was
  the wrong call.
- **Print Label on the form view**, so a single damaged sticker can be
  reprinted without building a job by hand.
- The print dialog now **remembers the last settings per user and document
  type** - format, label mode, size, output. The second run is one click.

### Changed
- The print format is preselected from the document type's own **Default Print
  Format** (respecting Property Setters), falling back to a label-named format,
  then Standard. Previously the default was guessed from the name alone, which
  ignored the setting Frappe already provides. The picker stays, because
  reprinting one sticker and running a whole roll are not always the same
  format.
- The dialog shows which format is the document type's default, so it is clear
  when a different one has been chosen.
- Selecting nothing gives a clear "tick the rows you want" message instead of a
  terse warning.

---

## [1.6.1] — 2026-07-24

### Added
- **Label options in the list-view Bulk Print dialog.** Printing from the Asset
  list previously had no Label Mode, so it always produced A4 pages regardless
  of the format. The dialog now offers Label Mode, size presets and custom
  dimensions, and turns Label Mode on automatically when the chosen print
  format is named like a label (`qr`, `label`, `sticker`, `tag`).
- **The download is offered as soon as the job finishes**, from wherever it was
  started, instead of requiring a trip to the job record to find the file.

### Changed
- The dialog states exactly what will be printed - the count and the first few
  IDs - so there is no doubt that only ticked rows are included.
- On the Document Center page the button reads **Print N selected** when rows
  are ticked and **Print all N matching** when they are not, so the scope is
  visible before clicking rather than described in help text underneath.
- Label Mode forces Single PDF output, since a roll needs one continuous file.

---

## [1.6.0] — 2026-07-24

### Added
- **Built-in QR encoder** (`qrgen.py`). QR generation no longer depends on any
  external library. Standard library only (zlib, struct), always UTF-8 byte
  mode, always PNG output. Supports versions 1-20 and all four error
  correction levels.

  External QR libraries had been the weak link for several releases: `qrcode`
  needs Pillow and is not a Frappe dependency, `pyqrcode` defaults to latin-1
  and raises on Arabic, and `pyqrcode` without `pypng` emits SVG, which
  wkhtmltopdf cannot render. On a bench with none of them installed the helper
  returned an empty string and labels printed a broken-image icon.

  Verified by decoding generated codes with an independent scanner across
  ASCII, Arabic, mixed and long payloads, every EC level, and versions 1-18.

### Changed
- `alphax_qr` uses the built-in encoder first; `qrcode` and `pyqrcode` remain
  as fallbacks only.
- `qr_backend()` reports `built-in (no dependencies)`.

---

## [1.5.1] — 2026-07-24

### Fixed
- **QR codes rendered as a broken image on labels.** Two faults compounded:
  - `pyqrcode` defaults to **latin-1** and raises `UnicodeEncodeError` on any
    non-Latin text. Every Arabic asset name failed, and the exception was
    swallowed by a bare `except`, so the helper silently returned an empty
    string. It is now called with `encoding="utf-8"`.
  - The fallback emitted **SVG**, which wkhtmltopdf's Qt WebKit engine cannot
    render from a data URI - it shows a broken-image icon. Every backend now
    emits PNG; SVG survives only as a last resort and logs a loud warning.
- Backend failures are recorded with their reason instead of being discarded.

### Added
- **Test QR Code** (Tools) - generates a QR on the spot using an Arabic sample,
  reports which backend served it and whether the output will render in a PDF,
  and shows the image inline.
- Diagnose Print Issue now reports the QR backend, and flags an SVG-only or
  missing backend as an error with the exact `bench pip install` command.

---

## [1.5.0] — 2026-07-24

### Added
- **Label / Continuous Roll printing.** Label Mode sizes each PDF page to the
  label itself — exact width and height, zero margins, no smart shrinking, and
  no letter head. Without it wkhtmltopdf renders the sticker into the corner of
  an A4 page, which is unusable on a roll printer. Presets cover 50x28, 50x25,
  40x30, 57x32, 76x25, 100x50 and 100x150 mm, plus custom sizes and a DPI
  setting (300 by default).
- `{{ alphax_asset_payload(doc) }}` — the text encoded in an asset QR, exposed
  separately so it can be printed as human-readable text too.

### Changed
- `alphax_asset_qr` now encodes `Asset ID / Name / Desc` with the description
  truncated at 40 characters, matching the payload the old browser-side label
  script produced, so assets already tagged keep scanning to the same value.
- `alphax_qr` accepts `border`, `box_size` and `ecc`, and defaults to a 2-module
  quiet zone suited to sticker sizes.
- `render_pdf` accepts `no_letterhead` directly rather than only as a fallback.

---

## [1.4.3] — 2026-07-23

### Added
- **Repair Print Format** (Tools). Finds `<img>` tags with no `src` in the job's
  print format and gives them one: tags that look like QR holders (`qr`,
  `qrcode`, `barcode` in the id or class) get
  `src="{{ alphax_qr(doc.name) }}"`, others get a transparent placeholder.
  Shows a line-by-line diff and saves nothing until confirmed. Refuses standard
  (file-defined) formats, and is idempotent.

---

## [1.4.2] — 2026-07-23

### Fixed
- **A job could report success while producing an unusable file.** When PDFs
  failed to merge, `_build_merged_pdf` caught the error and continued, so a
  batch where every merge failed still produced a valid-looking 311-byte,
  zero-page PDF, attached it, and marked the job Completed. Merge failures are
  now reported per document, and a build that would yield no pages (or an empty
  archive) fails the job with the reason.
- Output that is not actually a PDF is now detected by signature (`%PDF-`).
  wkhtmltopdf occasionally returns an HTML error page, which was previously
  packaged as a corrupt file.
- `_attach_file` refuses to attach empty content.
- `Processed Documents` now counts documents that reached the output file, not
  documents that merely rendered.

### Added
- **Output** field on the job: `Asset_Labels.pdf (3.9 KB, 30 pages)` or
  `Asset_Labels.zip (9.7 KB, 30 files)`. An empty value means no file was
  produced — previously indistinguishable from a file that failed to download.

---

## [1.4.1] — 2026-07-23

### Changed
- Broken `<img>` tags are now **repaired rather than removed**. A missing `src`
  is replaced with a 1x1 transparent placeholder, which is all the PDF pipeline
  needs to stop crashing. Deleting the element was wrong: print formats commonly
  declare an empty `<img id="qrImg">` that JavaScript fills in at render time,
  and removing it silently dropped the QR code from every label.

### Added
- Jinja helpers callable from any Print Format:
  - `{{ alphax_qr(text) }}` — QR code as a data URI, generated server-side.
  - `{{ alphax_asset_qr(doc) }}` — asset label payload (id, name, category,
    location) as a QR data URI.
  Server-side generation is reliable in PDF output; client-side scripts may not
  run before the page is captured.

### Notes
- If a batch still fails after upgrading, confirm the worker is running this
  version: a traceback pointing at `frappe.get_print` inside `process_job`
  means an older `jobs.py` is deployed. From 1.3.0 onward the worker renders
  through `render_pdf()`.

---

## [1.4.0] — 2026-07-23

### Added
- **Safe rendering module** (`render.py`). Frappe's PDF pipeline calls
  `img["src"]` on every image tag; an `<img>` with no `src` raises
  `KeyError: 'src'` and kills the render. Such tags are common in hand-edited
  Letter Heads and Print Formats, so one bad tag could break an entire batch.
  The HTML is now rendered, cleaned, and only then converted to PDF.
- **Diagnose Print Issue** (Tools) — reports broken image tags and attributes
  them to the Letter Head, the Print Format, or the document itself.
- **Configuration checks** run before rendering is attempted: print format
  belonging to a different doctype, disabled print format, raw-printing
  (ESC/POS) formats that cannot become PDFs, and missing/disabled letter heads.

### Fixed
- `OperationalError (1054, "Unknown column 'raw_printing_template' in 'SELECT'")`
  when diagnosing a print issue. Print Format has no `raw_printing_template`
  column in Frappe v15 — raw output lives in `raw_commands`. All field lookups
  now pass through `_safe_get_value()`, which filters requested columns through
  the doctype meta, so version drift degrades the report instead of raising.
- `diagnose_print` no longer propagates exceptions; failures are returned as
  data. A diagnostic that returns HTTP 500 is worse than no diagnostic.

---

## [1.3.0] — 2026-07-23

### Added
- **Print** checkbox on each selected-document row. Only ticked rows render.
  The grid's own checkboxes are Frappe's row-selection controls (used for
  deletion) and were never a print filter.
- **Selection** menu: Print Only Ticked Rows, Tick All, Untick All,
  Remove Ticked Rows, Retry Failed Only.
- **Test Render** (Tools) — renders one document synchronously and shows the
  exact exception.
- **Why Rows Failed** (Tools) — per-row error messages without re-running.
- Automatic retry without the letter head when a render fails, so a broken
  letter head degrades one setting rather than the whole batch.

### Fixed
- Per-document errors were destroyed when every document failed: the summary
  `RuntimeError` reached the outer handler and overwrote `error_log` with its
  own traceback. Errors are now preserved and grouped by cause.
- Saving a job with no rows ticked now raises instead of queueing empty work.

---

## [1.2.0] — 2026-07-23

### Added
- **Dynamic filters per document type**, built from the doctype's own fields
  plus every active **Accounting Dimension** in the system — Cost Center,
  Project, and any custom dimension (Branch, Division, Segment) without a code
  change.
- **Document number range** (From Doc No / To Doc No), usable alone or with a
  date range.
- Fetch-then-untick workflow on the Document Center page: list what matches,
  untick what you don't want, print the rest. Includes search, All/None, and a
  warning when results are capped.

### Changed
- Filter engine returns a condition **list** rather than a dict, so multiple
  conditions can apply to one field (a number range needs both `>=` and `<=`).

### Fixed
- The child **Document** field rendered blank and rows silently vanished on
  save. It is a Dynamic Link reading `document_type` from its own row, which
  was empty on manually added rows. New rows now inherit the parent's document
  type, existing rows are backfilled, and Title/Party autofill on selection.

---

## [1.1.0] — 2026-07-23

### Added
- **Asset bulk printing**: Asset, Asset Movement, Asset Repair, and Asset
  Capitalization, with category / location / custodian / status filters.
- **Selection modes**: *By Filters* or *Selected Documents*.
- `Bulk Document Item` child table recording each document's own result
  (Rendered / Failed) and error message.
- **Bulk Print** action in the list view of every supported doctype
  (Actions → Bulk Print).
- Visual document picker with search and select-all.
- **Include Drafts** toggle — assets sit in Draft far more often than invoices,
  so submitted-only hid most of the register.

### Changed
- Print Format is now optional and falls back to the doctype default.
- Date range is optional in selection mode.

---

## [1.0.1] — 2026-06-16

### Fixed
- `TypeError: process_job() missing 1 required positional argument: 'job_name'`.
  `job_name` is a reserved parameter of `frappe.enqueue` (the RQ job label), so
  it was consumed by the queue and never reached the function. Renamed to
  `docname` throughout.

---

## [1.0.0] — 2026-06-16

### Added
- `Bulk Document Job` queue DocType with live realtime progress.
- Single merged PDF or ZIP of separate PDFs.
- Filters by document type, company, party, and date range, with optional JSON
  power-filters and a date-field override.
- Email distribution — one email per party with that party's documents attached.
- Month-end archive scheduler, gated by `Document Center Settings`.
- Completion notifications.
- Document Center desk page and workspace.
