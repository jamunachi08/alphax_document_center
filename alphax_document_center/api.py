# Copyright (c) 2026, Neotec Integrated Solution and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _

from alphax_document_center.render import diagnose, repair_print_format, render_pdf
from alphax_document_center.utils import (
    SUPPORTED_DOCTYPES,
    build_filters,
    get_config,
    get_filter_schema,
    get_party_for,
    get_picker_fields,
)

LONG_QUEUE_TIMEOUT = 60 * 60  # 1 hour
PICKER_LIMIT = 1000


def _parse(args):
    if isinstance(args, str):
        args = json.loads(args)
    return args or {}


def _check_read(doctype):
    if not frappe.has_permission(doctype, "read"):
        frappe.throw(_("Not permitted to read {0}").format(doctype), frappe.PermissionError)


@frappe.whitelist()
def get_supported_doctypes():
    """List of document types the Document Center can process."""
    return SUPPORTED_DOCTYPES


@frappe.whitelist()
def get_filter_fields(doctype):
    """Filter controls to render for a document type, incl. accounting dimensions."""
    _check_read(doctype)
    return get_filter_schema(doctype)


@frappe.whitelist()
def describe_document(doctype, name):
    """Title + party for a single document, used to fill in child rows."""
    _check_read(doctype)
    if not frappe.db.exists(doctype, name):
        return None
    cfg = get_config(doctype)
    title_field = cfg.get("title_field")
    title = None
    if title_field and frappe.get_meta(doctype).get_field(title_field):
        title = frappe.db.get_value(doctype, name, title_field)
    return {"name": name, "title": title, "party": get_party_for(doctype, name)}


@frappe.whitelist()
def count_documents(args):
    """Return how many documents match the given filters (for the live counter)."""
    args = _parse(args)
    doctype = args.get("document_type")
    if not doctype:
        return 0
    _check_read(doctype)
    return frappe.db.count(doctype, build_filters(args))


@frappe.whitelist()
def list_documents(args, limit=PICKER_LIMIT, search=None):
    """Rows for the document picker grid: name + a few readable columns."""
    args = _parse(args)
    doctype = args.get("document_type")
    if not doctype:
        return {"fields": [], "rows": []}
    _check_read(doctype)

    cfg = get_config(doctype)
    fields = get_picker_fields(doctype)
    filters = build_filters(args)

    or_filters = None
    if search:
        meta = frappe.get_meta(doctype)
        title = cfg.get("title_field")
        or_filters = {"name": ["like", f"%{search}%"]}
        if title and meta.get_field(title):
            or_filters[title] = ["like", f"%{search}%"]

    rows = frappe.get_all(
        doctype,
        filters=filters,
        or_filters=or_filters,
        fields=fields,
        limit_page_length=frappe.utils.cint(limit) or PICKER_LIMIT,
        order_by="modified desc",
    )
    total = frappe.db.count(doctype, filters)
    return {
        "fields": fields,
        "rows": rows,
        "total": total,
        "limit": frappe.utils.cint(limit) or PICKER_LIMIT,
    }


@frappe.whitelist()
def create_and_enqueue(args):
    """Create a Bulk Document Job from UI args and queue it. Returns the job name."""
    args = _parse(args)
    doctype = args.get("document_type")
    if not doctype:
        frappe.throw(_("Document Type is required."))
    get_config(doctype)
    _check_read(doctype)

    selection_mode = args.get("selection_mode") or "By Filters"
    selected = args.get("selected_documents") or []
    if isinstance(selected, str):
        selected = json.loads(selected)
    if selected:
        selection_mode = "Selected Documents"

    # Dimension filters (asset category / location / custodian / status) have no
    # dedicated field on the job, so fold them into additional_filters to persist.
    extra = args.get("additional_filters") or {}
    if isinstance(extra, str):
        extra = json.loads(extra) if extra.strip() else {}
    schema = get_filter_schema(doctype)
    for f in schema["filters"]:
        fn = f["fieldname"]
        if fn in ("company", "party", "party_type"):
            continue  # these have dedicated fields on the job
        if args.get(fn) not in (None, "", []):
            extra[fn] = args[fn]
    additional_filters = json.dumps(extra, indent=1) if extra else None

    job = frappe.get_doc(
        {
            "doctype": "Bulk Document Job",
            "job_title": args.get("job_title"),
            "document_type": doctype,
            "selection_mode": selection_mode,
            "company": args.get("company"),
            "party_type": args.get("party_type"),
            "party": args.get("party"),
            "from_date": args.get("from_date"),
            "to_date": args.get("to_date"),
            "from_document": args.get("from_document"),
            "to_document": args.get("to_document"),
            "date_field": args.get("date_field"),
            "include_drafts": 1 if args.get("include_drafts") else 0,
            "additional_filters": additional_filters,
            "print_format": args.get("print_format"),
            "letter_head": args.get("letter_head"),
            "output_type": args.get("output_type") or "Single PDF",
            "label_mode": 1 if args.get("label_mode") else 0,
            "label_preset": args.get("label_preset"),
            "label_width_mm": args.get("label_width_mm"),
            "label_height_mm": args.get("label_height_mm"),
            "label_margin_mm": args.get("label_margin_mm"),
            "label_dpi": args.get("label_dpi"),
            "suppress_letter_head": 1 if args.get("suppress_letter_head", 1) else 0,
            "email_documents": 1 if args.get("email_documents") else 0,
        }
    )
    for name in selected:
        job.append("selected_documents", _selection_row(doctype, name))

    job.insert()
    enqueue_job(job.name)
    return job.name


@frappe.whitelist()
def create_from_selection(doctype, names, print_format=None, output_type="ZIP of PDFs",
                          job_title=None, label_mode=0, label_width_mm=None,
                          label_height_mm=None, label_preset=None):
    """Entry point for the list-view 'Bulk Print' action."""
    if isinstance(names, str):
        names = json.loads(names)
    if not names:
        frappe.throw(_("No documents selected."))
    get_config(doctype)
    _check_read(doctype)

    job = frappe.get_doc(
        {
            "doctype": "Bulk Document Job",
            "job_title": job_title or f"{doctype} - {len(names)} selected",
            "document_type": doctype,
            "selection_mode": "Selected Documents",
            "print_format": print_format,
            "output_type": output_type or "ZIP of PDFs",
            "label_mode": frappe.utils.cint(label_mode),
            "label_preset": label_preset,
            "label_width_mm": label_width_mm,
            "label_height_mm": label_height_mm,
            "suppress_letter_head": 1,
        }
    )
    for name in names:
        job.append("selected_documents", _selection_row(doctype, name))

    job.insert()
    enqueue_job(job.name)
    return job.name


def _selection_row(doctype, name):
    cfg = get_config(doctype)
    title_field = cfg.get("title_field")
    title = None
    if title_field and frappe.get_meta(doctype).get_field(title_field):
        title = frappe.db.get_value(doctype, name, title_field)
    return {
        "document_type": doctype,
        "document_name": name,
        "document_title": title,
        "party": get_party_for(doctype, name),
        "include": 1,
        "result": "Pending",
    }


@frappe.whitelist()
def test_render(doctype, name, print_format=None, letter_head=None):
    """Render ONE document synchronously and report the real error, if any.

    Used by the "Test Render" button so a failing job can be diagnosed without
    reading through a background traceback.
    """
    _check_read(doctype)
    if not frappe.db.exists(doctype, name):
        return {"ok": False, "error": f"{doctype} '{name}' does not exist."}
    try:
        pdf, notes = render_pdf(
            doctype, name, print_format=print_format, letter_head=letter_head
        )
        return {"ok": True, "size": len(pdf or b""), "name": name, "repaired": notes or None}
    except Exception:
        return {"ok": False, "error": frappe.get_traceback(with_context=False)}


@frappe.whitelist()
def diagnose_print(doctype, name, print_format=None, letter_head=None):
    """Find broken image tags and report where they come from.

    A diagnostic must never raise - if it does, the user is left with a 500
    instead of an explanation. Any failure is returned as data.
    """
    _check_read(doctype)
    if not frappe.db.exists(doctype, name):
        return {"error": f"{doctype} '{name}' does not exist."}
    try:
        return diagnose(doctype, name, print_format=print_format, letter_head=letter_head)
    except Exception:
        tb = frappe.get_traceback(with_context=False)
        frappe.clear_last_message()
        return {
            "document": name,
            "print_format": print_format or "(default)",
            "letter_head": letter_head or "(none)",
            "broken_images": [],
            "sources": [],
            "config": [{"level": "error", "message": "The diagnostic itself failed."}],
            "render_ok": False,
            "error": tb,
        }


@frappe.whitelist()
def set_row_inclusion(job_name, names, include=1):
    """Tick / untick the Print flag on specific rows of a job."""
    if isinstance(names, str):
        names = json.loads(names)
    job = frappe.get_doc("Bulk Document Job", job_name)
    job.check_permission("write")

    include = frappe.utils.cint(include)
    changed = 0
    for row in job.selected_documents:
        if row.document_name in names and frappe.utils.cint(row.include) != include:
            row.db_set("include", include, update_modified=False)
            changed += 1
    frappe.db.commit()
    return changed


@frappe.whitelist()
def repair_print_format_api(print_format, dry_run=1):
    """Preview (dry_run=1) or apply (dry_run=0) a print-format image repair."""
    if not frappe.has_permission("Print Format", "write"):
        frappe.throw(_("Not permitted to edit Print Formats."), frappe.PermissionError)
    try:
        return repair_print_format(print_format, dry_run=frappe.utils.cint(dry_run) == 1)
    except Exception:
        tb = frappe.get_traceback(with_context=False)
        frappe.clear_last_message()
        return {"print_format": print_format, "changed": False, "count": 0,
                "before": "", "after": "", "saved": False,
                "messages": ["The repair failed.", tb]}


@frappe.whitelist()
def qr_selftest(text=None):
    """Generate a QR right now and report the backend, format and size."""
    from alphax_document_center.jinja_methods import alphax_qr, qr_backend

    # Deliberately include Arabic: pyqrcode defaults to latin-1 and fails on it,
    # which is exactly the failure this test exists to catch.
    text = text or "IRS-TEST-0001 | كرسي مكتب متحرك"
    frappe.flags.alphax_qr_failures = None
    backend, fmt = qr_backend()
    uri = alphax_qr(text)
    return {
        "backend": backend,
        "format": fmt,
        "ok": bool(uri) and uri.startswith("data:image/png"),
        "data_uri": uri,
        "bytes": len(uri),
        "sample_text": text,
        "failures": frappe.flags.get("alphax_qr_failures") or [],
        "message": (
            "OK - PNG, renders in PDF." if uri.startswith("data:image/png")
            else "SVG output will NOT render in PDF. Install pypng or qrcode[pil]."
            if uri.startswith("data:image/svg")
            else "No QR produced. Install qrcode[pil] on the bench."
        ),
    }


@frappe.whitelist()
def enqueue_job(job_name):
    """Queue an existing Bulk Document Job for background processing."""
    job = frappe.get_doc("Bulk Document Job", job_name)
    job.check_permission("write")
    if job.status in ("Queued", "Running"):
        frappe.throw(_("Job {0} is already {1}.").format(job_name, job.status))

    job.db_set("status", "Queued")
    frappe.enqueue(
        "alphax_document_center.jobs.process_job",
        queue="long",
        timeout=LONG_QUEUE_TIMEOUT,
        docname=job.name,
        enqueue_after_commit=True,
    )
    return "Queued"


LABEL_NAME_HINT = ("qr", "label", "sticker", "tag", "barcode")


@frappe.whitelist()
def get_print_formats(doctype):
    """Print formats available for a document type (plus Standard)."""
    formats = frappe.get_all(
        "Print Format",
        filters={"doc_type": doctype, "disabled": 0},
        pluck="name",
        order_by="name asc",
    )
    return ["Standard"] + [f for f in formats if f != "Standard"]


@frappe.whitelist()
def get_print_setup(doctype):
    """Everything the print dialog needs to preselect sensible values.

    Order of preference for the format:
      1. The doctype's own Default Print Format (respects Property Setters).
      2. A format whose name reads like a label.
      3. Standard.
    """
    _check_read(doctype)
    formats = get_print_formats(doctype)

    default = None
    try:
        meta_default = frappe.get_meta(doctype).default_print_format
        if meta_default and meta_default in formats:
            default = meta_default
    except Exception:
        pass

    def looks_like_label(name):
        low = (name or "").lower()
        return any(h in low for h in LABEL_NAME_HINT)

    label_formats = [f for f in formats if looks_like_label(f)]
    if not default:
        default = label_formats[0] if label_formats else (formats[1] if len(formats) > 1 else "Standard")

    return {
        "formats": formats,
        "default": default,
        "doctype_default": frappe.get_meta(doctype).default_print_format or None,
        "label_formats": label_formats,
        "has_label_format": bool(label_formats),
        "is_label_default": looks_like_label(default),
    }


@frappe.whitelist()
def get_recent_jobs(limit=10):
    """Recent jobs for the status panel."""
    return frappe.get_all(
        "Bulk Document Job",
        fields=[
            "name", "job_title", "document_type", "status", "progress",
            "total_documents", "processed_documents", "failed_documents",
            "generated_file", "creation",
        ],
        order_by="creation desc",
        limit=frappe.utils.cint(limit) or 10,
    )
