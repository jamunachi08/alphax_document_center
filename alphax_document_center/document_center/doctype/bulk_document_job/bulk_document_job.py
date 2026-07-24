# Copyright (c) 2026, Neotec Integrated Solution and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document

from alphax_document_center.utils import get_config


class BulkDocumentJob(Document):
    def validate(self):
        get_config(self.document_type)

        if self.selection_mode == "Selected Documents":
            if not self.selected_documents:
                frappe.throw("Add at least one document, or switch Selection Mode to 'By Filters'.")
            self._validate_selection()
        else:
            if self.from_date and self.to_date and self.from_date > self.to_date:
                frappe.throw("From Date cannot be after To Date.")
            if self.from_document and self.to_document and self.from_document > self.to_document:
                frappe.throw("From Document No cannot be after To Document No.")
            if not self._has_any_filter():
                frappe.throw(
                    "Set at least one filter: a date range, a document number range, "
                    "a party, or another field - or switch to 'Selected Documents'."
                )

    def _has_any_filter(self):
        if self.from_date or self.to_date or self.from_document or self.to_document:
            return True
        if self.party or self.company:
            return True
        if self.additional_filters:
            try:
                return bool(json.loads(self.additional_filters))
            except ValueError:
                return False
        return False

    def _validate_selection(self):
        """Stamp document type on each row, dedupe, and reject missing records."""
        seen = set()
        keep = []
        for row in self.selected_documents:
            row.document_type = self.document_type
            if not row.document_name or row.document_name in seen:
                continue
            if not frappe.db.exists(self.document_type, row.document_name):
                frappe.throw(f"{self.document_type} '{row.document_name}' does not exist.")
            seen.add(row.document_name)
            keep.append(row)

        self.selected_documents = keep
        for i, row in enumerate(self.selected_documents, start=1):
            row.idx = i

        included = [r for r in keep if frappe.utils.cint(r.include)]
        if not included:
            frappe.throw(
                "No rows are ticked for printing. Tick the <b>Print</b> column on the "
                "rows you want, or use <b>Selection &gt; Tick All</b>."
            )
        self.total_documents = len(included)

    def before_insert(self):
        if not self.requested_by:
            self.requested_by = frappe.session.user
        if not self.status:
            self.status = "Pending"
        if not self.selection_mode:
            self.selection_mode = "By Filters"
        if not self.job_title:
            if self.selection_mode == "Selected Documents":
                self.job_title = f"{self.document_type} ({len(self.selected_documents or [])} selected)"
            elif self.from_date or self.to_date:
                self.job_title = f"{self.document_type} {self.from_date or ''} to {self.to_date or ''}".strip()
            elif self.from_document or self.to_document:
                self.job_title = f"{self.document_type} {self.from_document or ''}..{self.to_document or ''}"
            else:
                self.job_title = f"{self.document_type} (filtered)"
