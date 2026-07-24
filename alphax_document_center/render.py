# Copyright (c) 2026, Neotec Integrated Solution and contributors
# For license information, please see license.txt
#
# Safe PDF rendering.
#
# Frappe's frappe/utils/pdf.py -> inline_private_images() accesses img["src"]
# directly on every <img> tag in the rendered HTML. Any <img> without a src
# attribute raises KeyError: 'src' and kills the whole PDF render. Malformed
# image tags are common in hand-edited Letter Heads and Print Formats, so a
# single bad tag can break every document in a batch.
#
# We therefore render the HTML ourselves, strip image tags that could never
# have displayed anyway, and hand the cleaned HTML to get_pdf(). This is
# lossless: an <img> with no usable src renders as nothing either way.

import re

import frappe

# 1x1 fully transparent GIF. Renders as nothing, but satisfies the PDF
# pipeline's unconditional img["src"] access.
TRANSPARENT_PIXEL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"

IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
SRC_ATTR_RE = re.compile(r"""\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)


def _soup(html):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    return BeautifulSoup(html, "html.parser")


def find_broken_images(html):
    """Return a list of <img> tags that have no usable src attribute."""
    broken = []
    soup = _soup(html)

    if soup is not None:
        for img in soup.find_all("img"):
            src = img.attrs.get("src")
            if src is None or not str(src).strip():
                broken.append(str(img)[:300])
        return broken

    # Fallback if bs4 is unavailable: crude but adequate regex scan.
    for tag in IMG_TAG_RE.findall(html or ""):
        match = SRC_ATTR_RE.search(tag)
        value = ""
        if match:
            value = next((g for g in match.groups() if g is not None), "")
        if not value.strip():
            broken.append(tag[:300])
    return broken


def sanitize_print_html(html):
    """Neutralise <img> tags with a missing or empty src.

    The tag is NOT removed. Frappe's PDF pipeline only crashes because the
    `src` attribute is absent, so a 1x1 transparent placeholder is enough to
    make it safe. Keeping the element matters: print formats commonly declare
    an empty <img id="qrImg"> that JavaScript fills in at render time, and
    deleting it would silently drop the QR code from every label.

    Returns (cleaned_html, repaired_count).
    """
    if not html:
        return html, 0

    soup = _soup(html)
    if soup is not None:
        repaired = 0
        for img in soup.find_all("img"):
            src = img.attrs.get("src")
            if src is None or not str(src).strip():
                img["src"] = TRANSPARENT_PIXEL
                repaired += 1
        return (str(soup), repaired) if repaired else (html, 0)

    repaired = 0

    def _replace(match):
        nonlocal repaired
        tag = match.group(0)
        src_match = SRC_ATTR_RE.search(tag)
        value = ""
        if src_match:
            value = next((g for g in src_match.groups() if g is not None), "")
        if value.strip():
            return tag
        repaired += 1
        if src_match:
            # Replace the empty src in place.
            return tag[: src_match.start()] + f'src="{TRANSPARENT_PIXEL}"' + tag[src_match.end():]
        # No src attribute at all - insert one.
        closing = "/>" if tag.rstrip().endswith("/>") else ">"
        body = tag.rstrip()[: -len(closing)].rstrip()
        return f'{body} src="{TRANSPARENT_PIXEL}"{closing}'

    cleaned = IMG_TAG_RE.sub(_replace, html)
    return (cleaned, repaired) if repaired else (html, 0)


def get_html(doctype, name, print_format=None, letter_head=None, no_letterhead=0):
    """Rendered print HTML for one document (no PDF conversion)."""
    return frappe.get_print(
        doctype,
        name,
        print_format=(print_format or None),
        letterhead=(letter_head or None),
        no_letterhead=no_letterhead,
        as_pdf=False,
    )


def render_pdf(doctype, name, print_format=None, letter_head=None, pdf_options=None,
               no_letterhead=False):
    """Render one document to PDF bytes, resiliently.

    Strategy:
      1. Render HTML, sanitize broken <img> tags, convert to PDF.
      2. If that still fails and a letter head was used, retry without it.

    Returns (pdf_bytes, notes) where notes describes any repair that was
    applied, or an empty string.
    """
    from frappe.utils.pdf import get_pdf

    notes = []

    def _attempt(no_letterhead):
        html = get_html(
            doctype, name, print_format=print_format,
            letter_head=(None if no_letterhead else letter_head),
            no_letterhead=1 if no_letterhead else 0,
        )
        cleaned, removed = sanitize_print_html(html)
        if removed:
            notes.append(f"repaired {removed} image tag(s) with no src")
        return get_pdf(cleaned, options=pdf_options)

    try:
        pdf = _attempt(no_letterhead=bool(no_letterhead))
    except Exception:
        if not letter_head or no_letterhead:
            raise
        frappe.clear_last_message()
        notes.append("letter head skipped after render failure")
        pdf = _attempt(no_letterhead=True)

    return pdf, "; ".join(notes)


def _existing_fields(doctype, candidates):
    """Keep only the fieldnames that actually exist on this doctype.

    Field names drift between Frappe versions (Print Format stores raw output
    in `raw_commands`, not `raw_printing_template`). Selecting a column that
    isn't there raises OperationalError 1054 and takes the whole request down,
    so every lookup is filtered through the doctype meta first.
    """
    try:
        meta = frappe.get_meta(doctype)
    except Exception:
        return []
    return [f for f in candidates if meta.get_field(f)]


def _safe_get_value(doctype, name, candidates):
    """frappe.db.get_value limited to columns that exist. Returns a dict."""
    if not name:
        return {}
    fields = _existing_fields(doctype, candidates)
    if not fields:
        return {}
    try:
        return frappe.db.get_value(doctype, name, fields, as_dict=True) or {}
    except Exception:
        frappe.clear_last_message()
        return {}


# Content-bearing fields worth scanning for broken images, by doctype.
# Extras are harmless - anything absent is filtered out before the query.
LETTER_HEAD_CONTENT_FIELDS = ["content", "footer", "header_script", "image"]
PRINT_FORMAT_CONTENT_FIELDS = ["html", "raw_commands", "format_data", "css"]


def _config_checks(doctype, name, print_format, letter_head):
    """Cheap checks for the mistakes that break a whole batch."""
    findings = []

    def add(level, message):
        findings.append({"level": level, "message": message})

    if not frappe.db.exists(doctype, name):
        add("error", f"{doctype} '{name}' does not exist.")

    if print_format:
        pf = _safe_get_value(
            "Print Format",
            print_format,
            ["doc_type", "disabled", "print_format_type", "standard", "raw_printing", "pdf_generator"],
        )
        if not pf:
            add("error", f"Print Format '{print_format}' was not found.")
        else:
            if pf.get("doc_type") and pf["doc_type"] != doctype:
                add(
                    "error",
                    f"Print Format '{print_format}' belongs to {pf['doc_type']}, not {doctype}.",
                )
            if frappe.utils.cint(pf.get("disabled")):
                add("error", f"Print Format '{print_format}' is disabled.")
            if frappe.utils.cint(pf.get("raw_printing")):
                add(
                    "error",
                    f"Print Format '{print_format}' is a raw-printing format "
                    "(ESC/POS commands). It cannot be converted to PDF.",
                )
    else:
        add("info", "No print format set - the document type's default will be used.")

    # QR backend - an SVG-only backend renders as a broken image in PDF.
    try:
        from alphax_document_center.jinja_methods import qr_backend

        backend, fmt = qr_backend()
        if not backend:
            add("error", "No QR library on this bench. Run: bench pip install qrcode[pil]")
        elif fmt == "svg":
            add(
                "error",
                "QR codes would be generated as SVG (pypng missing). wkhtmltopdf "
                "cannot render SVG and the label shows a broken image. "
                "Run: bench pip install pypng  (or qrcode[pil])",
            )
        else:
            add("info", f"QR backend: {backend} ({fmt}).")
    except Exception:
        pass

    if letter_head:
        lh = _safe_get_value("Letter Head", letter_head, ["disabled"])
        if not lh:
            add("error", f"Letter Head '{letter_head}' was not found.")
        elif frappe.utils.cint(lh.get("disabled")):
            add("warning", f"Letter Head '{letter_head}' is disabled.")

    return findings


def diagnose(doctype, name, print_format=None, letter_head=None):
    """Explain why a document fails to render, and where the problem lives."""
    report = {
        "document": name,
        "print_format": print_format or "(default)",
        "letter_head": letter_head or "(none)",
        "broken_images": [],
        "sources": [],
        "config": [],
        "render_ok": False,
        "error": None,
        "repaired": None,
    }

    # 0. Configuration sanity - cheap checks that catch the common mistakes.
    report["config"] = _config_checks(doctype, name, print_format, letter_head)

    # 1. Which <img> tags in the full rendered output are missing a src?
    try:
        html = get_html(doctype, name, print_format=print_format, letter_head=letter_head)
        report["broken_images"] = find_broken_images(html)
    except Exception:
        report["error"] = frappe.get_traceback(with_context=False)
        return report

    # 2. Attribute them to the letter head or the print format where possible.
    if report["broken_images"]:
        if letter_head:
            lh = _safe_get_value("Letter Head", letter_head, LETTER_HEAD_CONTENT_FIELDS)
            for part, value in lh.items():
                found = find_broken_images(value or "")
                if found:
                    report["sources"].append(
                        {"where": f"Letter Head '{letter_head}' ({part})", "tags": found}
                    )
        if print_format:
            pf = _safe_get_value("Print Format", print_format, PRINT_FORMAT_CONTENT_FIELDS)
            for part, value in pf.items():
                found = find_broken_images(value or "")
                if found:
                    report["sources"].append(
                        {"where": f"Print Format '{print_format}' ({part})", "tags": found}
                    )
        if not report["sources"]:
            report["sources"].append(
                {"where": "Document content or a linked image field", "tags": []}
            )

    # 3. Does the repaired render actually succeed?
    try:
        pdf, notes = render_pdf(doctype, name, print_format=print_format, letter_head=letter_head)
        report["render_ok"] = bool(pdf)
        report["size"] = len(pdf or b"")
        report["repaired"] = notes or None
    except Exception:
        report["error"] = frappe.get_traceback(with_context=False)

    return report


# ----------------------------------------------------------------------
# Print Format repair
# ----------------------------------------------------------------------
QR_HINT_RE = re.compile(r"\b(qr|qrcode|qr_code|barcode)\b", re.IGNORECASE)


def _is_qr_tag(tag_html):
    """Does this <img> look like it is meant to hold a QR code?"""
    return bool(QR_HINT_RE.search(tag_html))


def repair_print_format(print_format, dry_run=True):
    """Replace src-less <img> tags in a Print Format with a server-side QR call.

    Only custom (non-standard) formats are touched - standard formats live in
    files inside an app and must be edited there. Returns a before/after
    preview so the change can be reviewed before it is saved.
    """
    result = {
        "print_format": print_format,
        "changed": False,
        "count": 0,
        "before": "",
        "after": "",
        "messages": [],
        "saved": False,
    }

    meta_fields = _existing_fields("Print Format", ["html", "standard", "disabled", "doc_type"])
    if "html" not in meta_fields:
        result["messages"].append("This Frappe version has no editable html field on Print Format.")
        return result

    row = _safe_get_value("Print Format", print_format, meta_fields)
    if not row:
        result["messages"].append(f"Print Format '{print_format}' not found.")
        return result

    if (row.get("standard") or "").lower() == "yes":
        result["messages"].append(
            f"'{print_format}' is a standard format defined in an app's files. "
            "Edit it in the app source, or duplicate it as a custom format first."
        )
        return result

    html = row.get("html") or ""
    if not html.strip():
        result["messages"].append(
            "This format has no HTML - it is probably built with the visual "
            "Print Format Builder, so the image must be fixed there."
        )
        return result

    result["before"] = html
    broken = find_broken_images(html)
    if not broken:
        result["messages"].append("No src-less image tags found. Nothing to repair.")
        result["after"] = html
        return result

    count = 0

    def _fix(match):
        nonlocal count
        tag = match.group(0)
        src_match = SRC_ATTR_RE.search(tag)
        value = ""
        if src_match:
            value = next((g for g in src_match.groups() if g is not None), "")
        if value.strip():
            return tag

        if _is_qr_tag(tag):
            replacement = 'src="{{ alphax_qr(doc.name) }}"'
        else:
            replacement = f'src="{TRANSPARENT_PIXEL}"'

        count += 1
        if src_match:
            return tag[: src_match.start()] + replacement + tag[src_match.end():]
        closing = "/>" if tag.rstrip().endswith("/>") else ">"
        body = tag.rstrip()[: -len(closing)].rstrip()
        return f"{body} {replacement}{closing}"

    new_html = IMG_TAG_RE.sub(_fix, html)
    result["after"] = new_html
    result["count"] = count
    result["changed"] = count > 0 and new_html != html

    if result["changed"]:
        result["messages"].append(
            f"{count} image tag(s) would be given a src. QR tags use "
            "{{ alphax_qr(doc.name) }}; others get a transparent placeholder."
        )
        if "qrImg" in html and "<script" in html.lower():
            result["messages"].append(
                "This format also contains a script that sets the QR image. It is "
                "harmless to leave, but it no longer does anything in PDF output."
            )

    if result["changed"] and not dry_run:
        doc = frappe.get_doc("Print Format", print_format)
        doc.html = new_html
        doc.save()
        result["saved"] = True
        result["messages"].append("Saved.")

    return result
