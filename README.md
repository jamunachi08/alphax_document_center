# Alpha-X Document Center

Bulk PDF, ZIP & Document Distribution Engine for Alpha-X ERP (Frappe/ERPNext v15).

Generate, merge, archive and email large batches of transactional documents
(Sales Invoices, POs, Statements, etc.) from a single screen, processed in the
background so the UI never blocks.

## Features
- **Bulk Document Job** queue DocType with live progress (realtime).
- **Two selection modes**: *By Filters* (date range / party / dimensions) or
  *Selected Documents* (tick exactly the records you want).
- **Bulk Print from any list view** - select rows in the Asset (or Sales Invoice,
  PO, ...) list, then **Actions > Bulk Print**.
- **Asset support** with category / location / custodian / status filters and a
  visual document picker.
- **Dynamic filters per document type** - built from the doctype's own fields
  *plus every active Accounting Dimension in the system* (Cost Center, Project,
  and any custom dimension such as Branch, Division, Segment).
- **Document number range** (From Doc No / To Doc No), usable on its own or
  together with a date range.
- **Fetch then check/uncheck** - list what matches, untick what you don't want,
  print the rest.
- **Single merged PDF** or **ZIP of separate PDFs** output.
- Filters by document type, company, party (customer/supplier) and date range,
  plus optional JSON power-filters and a custom date-field override.
- **Email distribution** — one email per party with that party's PDFs attached.
- **Month-end archive** scheduler (gated by Document Center Settings).
- Completion notifications.
- A dedicated **Document Center** desk page + workspace.

## Supported documents
Sales Invoice, Quotation, Delivery Note, Sales Order, Purchase Invoice,
Purchase Order, Purchase Receipt, Payment Entry, Journal Entry, Stock Entry,
**Asset, Asset Movement, Asset Repair, Asset Capitalization**.
Add more in `alphax_document_center/utils.py` → `DOC_CONFIG` (no other changes).

## Install
```bash
cd $PATH_TO_YOUR_BENCH
bench get-app alphax_document_center /path/to/alphax_document_center
bench --site your.site install-app alphax_document_center
bench --site your.site migrate
bench build && bench clear-cache
```

For Frappe Cloud: push this folder to a GitHub repo, add it as a custom app on
the bench, then install it on the site.

## Use

### Option A - Document Center screen
Open **Document Center** from the workspace (or `/app/alphax-document-center`).

1. Pick a **Document Type**. The filter panel rebuilds itself for that doctype -
   party, dimensions, asset category/location/custodian, status, and so on.
2. Narrow it down with any combination of **date range**, **document number
   range**, and **filters**.
3. Hit **Fetch Documents**. Everything matching is listed and ticked.
4. **Untick** anything you don't want (there's a search box, plus All / None).
5. Hit **Generate**.

If you skip step 3, Generate simply prints everything matching the filters -
useful for very large runs you don't want to list in the browser.

### Option B - straight from a list view
Go to the **Asset** list (or any supported doctype), tick the rows you want,
then **Actions > Bulk Print**. Choose a print format and PDF/ZIP output; the job
is created and queued for you.

### Option C - on the job form
Open a Bulk Document Job and use **Pick Documents** to build the selection
visually. Each selected row records its own result (Rendered / Failed) so you
can see exactly which document failed and why.

## Troubleshooting

**All documents fail with `KeyError: 'src'`** - this is a bug in Frappe's
`frappe/utils/pdf.py`, which reads `img["src"]` on every image tag. Any `<img>`
without a `src` attribute (common in hand-edited Letter Heads and Print Formats)
crashes the whole PDF render. Document Center strips such tags automatically
before conversion, so jobs succeed regardless. Use **Tools > Diagnose Print
Issue** on a job to find which Letter Head or Print Format contains the bad tag
and fix it at source.

**Tools available on every job**
- *Test Render* - render one document synchronously and see the exact error.
- *Diagnose Print Issue* - locate broken image tags and their origin.
- *Why Rows Failed* - per-row error messages from the last run.
- *View Error Log* - grouped digest of all failures by cause.

## Requirements
- Frappe v15, a working `wkhtmltopdf` (for PDF rendering).
- `pypdf` (bundled with Frappe v15) for merging.
- A running **long** worker queue for background jobs.

## Print formats & QR codes

Frappe's PDF pipeline reads `img["src"]` on every image tag. An `<img>` with no
`src` raises `KeyError: 'src'` and kills the render — one bad tag in a shared
print format breaks every document in a batch.

Document Center repairs such tags automatically (transparent placeholder), so
batches succeed regardless. But if the image is a QR code filled in by
JavaScript, the PDF may capture the page before the script runs, leaving it
blank. Generate it server-side instead:

```html
<!-- instead of: <img class="qr" id="qrImg"> filled by JS -->
<img class="qr" src="{{ alphax_qr(doc.name) }}">

<!-- or, for an asset label with id / name / category / location encoded -->
<img class="qr" src="{{ alphax_asset_qr(doc) }}">
```

Requires `qrcode` or `pyqrcode` on the bench; `pyqrcode` ships with Frappe.

## Versioning & releases

The app version lives in `alphax_document_center/__init__.py` and is what
Frappe reports under **App Versions**. `pyproject.toml` reads it dynamically,
so it is set in exactly one place.

Use the helper to cut a release:

```bash
./release.sh 1.4.1           # bump, commit "Update v1.4.1", tag v1.4.1
./release.sh 1.4.1 --push    # same, then push branch and tag
```

Add the matching `## [1.4.1]` section to `CHANGELOG.md` first — the script
will warn if it is missing.
