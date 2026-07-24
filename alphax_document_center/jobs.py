# Copyright (c) 2026, Neotec Integrated Solution and contributors
# For license information, please see license.txt

import io
import zipfile
from collections import defaultdict

import frappe
from frappe.utils import add_months, get_first_day, get_last_day, getdate, nowdate

from alphax_document_center.render import render_pdf
from alphax_document_center.utils import (
    build_filters,
    get_config,
    get_party_email,
    get_party_for,
    publish_progress,
)

# How often (in documents) we flush progress to the DB / realtime channel.
PROGRESS_EVERY = 5


# ----------------------------------------------------------------------
# Main entry point — called from the long queue.
# ----------------------------------------------------------------------
def process_job(docname):
    job_name = docname  # 'job_name' is reserved by frappe.enqueue, so we receive it as 'docname'
    job = frappe.get_doc("Bulk Document Job", job_name)
    job.db_set("status", "Running")
    job.db_set("started_at", frappe.utils.now())
    job.db_set("error_log", "")
    frappe.db.commit()

    try:
        cfg = get_config(job.document_type)
        names = _resolve_names(job)

        total = len(names)
        job.db_set("total_documents", total)
        job.db_set("processed_documents", 0)
        job.db_set("failed_documents", 0)
        frappe.db.commit()
        publish_progress(job_name, 0, total, "Running")

        if not total:
            job.db_set("status", "Completed")
            job.db_set("progress", 100)
            job.db_set("completed_at", frappe.utils.now())
            frappe.db.commit()
            publish_progress(job_name, 0, 0, "Completed")
            return

        rendered = []   # list of (name, party, pdf_bytes)
        errors = []
        processed = 0

        for name in names:
            try:
                pdf, notes = _render(job, name)
                party = get_party_for(job.document_type, name)
                rendered.append((name, party, pdf))
                _set_row_result(job, name, "Rendered", notes or None)
            except Exception:
                message = frappe.get_traceback(with_context=False)
                errors.append(f"{name}: {message}")
                _set_row_result(job, name, "Failed", message)
                frappe.clear_last_message()

            processed += 1
            if processed % PROGRESS_EVERY == 0 or processed == total:
                job.db_set("processed_documents", processed, commit=True)
                job.db_set("failed_documents", len(errors), commit=True)
                publish_progress(job_name, processed, total, "Running")

        if not rendered:
            # Fail here directly rather than raising, so the per-document
            # tracebacks survive instead of being replaced by a summary error.
            job.reload()
            job.db_set("status", "Failed")
            job.db_set("processed_documents", 0)
            job.db_set("failed_documents", len(errors))
            job.db_set("completed_at", frappe.utils.now())
            job.db_set("error_log", _format_errors(errors, total)[:140000])
            frappe.db.commit()
            publish_progress(job_name, 0, total, "Failed")
            frappe.log_error(
                title=f"Bulk Document Job rendered nothing: {job_name}",
                message=_format_errors(errors, total),
            )
            return

        # Build the deliverable.
        if job.output_type == "ZIP of PDFs":
            content, filename, build_failures = _build_zip(rendered, job)
        else:
            content, filename, build_failures = _build_merged_pdf(rendered, job)

        # A document that rendered but could not be packaged is still a failure.
        for failure in build_failures:
            errors.append(failure)
            _set_row_result(job, failure.split(":", 1)[0], "Failed", failure)

        file_url = _attach_file(job, filename, content)
        job.db_set("output_summary", _describe_output(filename, content))

        # Optional email distribution (grouped per party).
        if job.email_documents:
            _email_documents(job, rendered)

        status = "Partially Completed" if errors else "Completed"
        job.db_set("status", status)
        job.db_set("processed_documents", max(len(rendered) - len(build_failures), 0))
        job.db_set("failed_documents", len(errors))
        job.db_set("progress", 100)
        job.db_set("completed_at", frappe.utils.now())
        if errors:
            job.db_set("error_log", _format_errors(errors, total)[:140000])
        frappe.db.commit()

        publish_progress(job_name, len(rendered), total, status, file_url=file_url)
        _notify_completion(job, file_url)

    except Exception:
        tb = frappe.get_traceback()
        job.reload()
        job.db_set("status", "Failed")
        job.db_set("error_log", tb[:140000])
        job.db_set("completed_at", frappe.utils.now())
        frappe.db.commit()
        publish_progress(job_name, job.processed_documents or 0, job.total_documents or 0, "Failed")
        frappe.log_error(title=f"Bulk Document Job failed: {job_name}", message=tb)


# ----------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------
def _looks_like_pdf(content):
    """A real PDF starts with %PDF-. wkhtmltopdf occasionally returns an HTML
    error page instead, which would otherwise be packaged as a corrupt file."""
    return isinstance(content, (bytes, bytearray)) and bytes(content[:5]) == b"%PDF-"


def _build_merged_pdf(rendered, job):
    """Merge rendered PDFs into one file.

    Returns (content, filename, failures). Merge errors are reported rather
    than skipped - silently continuing produced a valid-looking but zero-page
    PDF and a job that claimed to have succeeded.
    """
    writer = _pdf_writer()
    failures = []
    pages = 0

    for name, _party, pdf in rendered:
        if not isinstance(pdf, (bytes, bytearray)):
            failures.append(f"{name}: renderer returned {type(pdf).__name__}, expected bytes")
            continue
        if not pdf:
            failures.append(f"{name}: rendered to an empty file")
            continue
        if not _looks_like_pdf(pdf):
            failures.append(f"{name}: output is not a PDF (renderer returned something else)")
            continue
        try:
            reader = _pdf_reader(io.BytesIO(pdf))
            for page in reader.pages:
                writer.add_page(page)
                pages += 1
        except Exception as exc:
            failures.append(f"{name}: could not be merged ({type(exc).__name__}: {exc})")

    if not pages:
        raise RuntimeError(
            "The merged PDF would contain no pages. "
            + (failures[0] if failures else "No readable PDFs were produced.")
        )

    out = io.BytesIO()
    writer.write(out)
    content = out.getvalue()
    if not content:
        raise RuntimeError("PDF merge produced an empty file.")

    return content, f"{_slug(job)}.pdf", failures


def _build_zip(rendered, job):
    """Zip each rendered PDF separately. Returns (content, filename, failures)."""
    buf = io.BytesIO()
    seen = defaultdict(int)
    failures = []
    written = 0

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, _party, pdf in rendered:
            if not isinstance(pdf, (bytes, bytearray)) or not pdf:
                failures.append(f"{name}: nothing to write (empty or wrong type)")
                continue
            if not _looks_like_pdf(pdf):
                failures.append(f"{name}: output is not a PDF (renderer returned something else)")
                continue
            entry = f"{name}.pdf"
            seen[entry] += 1
            if seen[entry] > 1:
                entry = f"{name}-{seen[entry]}.pdf"
            zf.writestr(entry, bytes(pdf))
            written += 1

    if not written:
        raise RuntimeError(
            "The archive would be empty. "
            + (failures[0] if failures else "No documents were produced.")
        )

    return buf.getvalue(), f"{_slug(job)}.zip", failures


def _describe_output(filename, content):
    """Human-readable proof that a file was produced, shown on the job."""
    size_mb = len(content) / (1024 * 1024)
    size = f"{size_mb:.2f} MB" if size_mb >= 1 else f"{len(content) / 1024:.1f} KB"
    detail = ""
    try:
        if filename.lower().endswith(".pdf"):
            detail = f", {len(_pdf_reader(io.BytesIO(content)).pages)} pages"
        elif filename.lower().endswith(".zip"):
            detail = f", {len(zipfile.ZipFile(io.BytesIO(content)).namelist())} files"
    except Exception:
        pass
    return f"{filename} ({size}{detail})"


def _attach_file(job, filename, content):
    if not content:
        raise RuntimeError("Refusing to attach an empty file.")
    _file = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": filename,
            "attached_to_doctype": "Bulk Document Job",
            "attached_to_name": job.name,
            "attached_to_field": "generated_file",
            "is_private": 1,
            "content": content,
        }
    )
    _file.insert(ignore_permissions=True)
    job.db_set("generated_file", _file.file_url)
    return _file.file_url


# ----------------------------------------------------------------------
# Email distribution (one email per party, with that party's PDFs attached)
# ----------------------------------------------------------------------
def _email_documents(job, rendered):
    cfg = get_config(job.document_type)
    party_type = job.party_type or cfg.get("party_type")

    groups = defaultdict(list)
    for name, party, pdf in rendered:
        groups[party].append((name, pdf))

    for party, docs in groups.items():
        if not party:
            continue
        email = get_party_email(party_type, party)
        if not email:
            continue

        attachments = [{"fname": f"{name}.pdf", "fcontent": pdf} for name, pdf in docs]
        subject = f"{job.document_type} documents — {party}"
        body = (
            f"Dear {party},<br><br>"
            f"Please find attached {len(docs)} {job.document_type} document(s).<br><br>"
            f"Regards,<br>{frappe.db.get_default('company') or 'Accounts Team'}"
        )
        try:
            frappe.sendmail(
                recipients=[email],
                subject=subject,
                message=body,
                attachments=attachments,
                reference_doctype="Bulk Document Job",
                reference_name=job.name,
            )
        except Exception:
            frappe.log_error(title=f"Email failed for party {party}", message=frappe.get_traceback())


def _notify_completion(job, file_url):
    try:
        settings = frappe.get_single("Document Center Settings")
    except Exception:
        return
    if not settings.get("notify_on_completion"):
        return

    recipients = []
    if settings.get("notification_recipients"):
        recipients = [r.strip() for r in settings.notification_recipients.split(",") if r.strip()]
    owner_email = frappe.db.get_value("User", job.requested_by or job.owner, "email")
    if owner_email:
        recipients.append(owner_email)
    recipients = list(dict.fromkeys(recipients))
    if not recipients:
        return

    site = frappe.utils.get_url()
    frappe.sendmail(
        recipients=recipients,
        subject=f"[Document Center] {job.name} — {job.status}",
        message=(
            f"Bulk Document Job <b>{job.name}</b> finished with status "
            f"<b>{job.status}</b>.<br>"
            f"Documents: {job.processed_documents}/{job.total_documents}"
            f" (failed: {job.failed_documents}).<br>"
            f'<a href="{site}{file_url}">Download generated file</a>'
        ),
        reference_doctype="Bulk Document Job",
        reference_name=job.name,
    )


# ----------------------------------------------------------------------
# Premium feature: month-end archive (scheduled, gated by settings)
# ----------------------------------------------------------------------
def create_monthly_archive():
    try:
        settings = frappe.get_single("Document Center Settings")
    except Exception:
        return
    if not settings.get("enable_monthly_archive"):
        return

    doctype = settings.get("archive_document_type") or "Sales Invoice"
    print_format = settings.get("archive_print_format")
    if not print_format:
        return

    last_month = add_months(nowdate(), -1)
    from_date = get_first_day(last_month)
    to_date = get_last_day(last_month)
    label = getdate(from_date).strftime("%Y_%m")

    job = frappe.get_doc(
        {
            "doctype": "Bulk Document Job",
            "job_title": f"Monthly Archive {doctype} {label}",
            "document_type": doctype,
            "from_date": from_date,
            "to_date": to_date,
            "print_format": print_format,
            "output_type": settings.get("archive_output_type") or "ZIP of PDFs",
        }
    )
    job.insert(ignore_permissions=True)
    job.db_set("status", "Queued")
    frappe.enqueue(
        "alphax_document_center.jobs.process_job",
        queue="long",
        timeout=60 * 60 * 4,
        docname=job.name,
    )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _slug(job):
    title = job.job_title or f"{job.document_type}-{job.name}"
    return frappe.utils.cstr(title).replace(" ", "_").replace("/", "-")


def _pdf_writer():
    try:
        from pypdf import PdfWriter
    except ImportError:  # pragma: no cover
        from PyPDF2 import PdfWriter
    return PdfWriter()


def _pdf_reader(stream):
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        from PyPDF2 import PdfReader
    return PdfReader(stream)


def _label_pdf_options(job):
    """wkhtmltopdf options for label / continuous-roll output.

    Returns (options, no_letterhead). A label roll needs the page to BE the
    label: exact width and height, zero margins, and no smart shrinking, or
    wkhtmltopdf scales the artwork to fit A4 and the sticker prints tiny in
    the corner of a huge page.
    """
    if not frappe.utils.cint(getattr(job, "label_mode", 0)):
        return None, False

    width = frappe.utils.flt(job.label_width_mm) or 50.0
    height = frappe.utils.flt(job.label_height_mm) or 28.0
    margin = frappe.utils.flt(job.label_margin_mm) or 0.0
    dpi = frappe.utils.cint(job.label_dpi) or 300

    options = {
        "page-width": f"{width}mm",
        "page-height": f"{height}mm",
        "margin-top": f"{margin}mm",
        "margin-bottom": f"{margin}mm",
        "margin-left": f"{margin}mm",
        "margin-right": f"{margin}mm",
        "disable-smart-shrinking": None,
        "dpi": dpi,
        "zoom": 1,
    }
    return options, bool(frappe.utils.cint(getattr(job, "suppress_letter_head", 1)))


def _render(job, name):
    """Render one document to PDF via the resilient renderer."""
    pdf_options, no_letterhead = _label_pdf_options(job)
    pdf, notes = render_pdf(
        job.document_type,
        name,
        print_format=job.print_format,
        letter_head=job.letter_head,
        pdf_options=pdf_options,
        no_letterhead=no_letterhead,
    )
    return pdf, notes


def _format_errors(errors, total):
    """Readable error digest: a summary of distinct causes, then the detail."""
    if not errors:
        return ""

    # Group by the last line of each traceback so a repeated cause is obvious.
    causes = {}
    for entry in errors:
        last = entry.strip().splitlines()[-1].strip() if entry.strip() else "Unknown error"
        causes.setdefault(last, 0)
        causes[last] += 1

    lines = [f"{len(errors)} of {total} document(s) failed to render.", "", "SUMMARY OF CAUSES:"]
    for cause, count in sorted(causes.items(), key=lambda x: -x[1]):
        lines.append(f"  [{count}x] {cause}")
    lines += ["", "-" * 60, "DETAIL (first 20):", ""]
    lines.extend(errors[:20])
    if len(errors) > 20:
        lines.append(f"... and {len(errors) - 20} more.")
    return "\n".join(lines)


def _resolve_names(job):
    """Document names to print - either hand-picked rows or a filter query."""
    if job.selection_mode == "Selected Documents":
        # Only rows with Include ticked are printed.
        names = [
            r.document_name
            for r in (job.selected_documents or [])
            if r.document_name and frappe.utils.cint(r.include)
        ]
        # Drop anything deleted since the job was created.
        existing = set(
            frappe.get_all(
                job.document_type,
                filters={"name": ["in", names]},
                pluck="name",
            )
        ) if names else set()
        return [n for n in names if n in existing]

    filters = build_filters(job)
    return frappe.get_all(job.document_type, filters=filters, pluck="name", order_by="creation asc")


def _set_row_result(job, document_name, result, message=None):
    """Update the child row for a document, if the job used manual selection."""
    if job.selection_mode != "Selected Documents":
        return
    try:
        frappe.db.set_value(
            "Bulk Document Item",
            {"parent": job.name, "document_name": document_name},
            {"result": result, "error_message": (message or "")[:500]},
            update_modified=False,
        )
    except Exception:
        pass
