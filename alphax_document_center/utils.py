# Copyright (c) 2026, Neotec Integrated Solution and contributors
# For license information, please see license.txt

import json

import frappe

# ----------------------------------------------------------------------
# Per-doctype configuration.
#   date_field    : default field for the From/To date range filter
#   party_field   : field that stores the party (customer / supplier)
#   party_type    : the doctype of the party for that document
#   title_field   : friendly label used in the picker and child rows
#   picker_fields : columns shown in the selection grid
#   filter_fields : doctype-specific filter fields offered in the UI
# Add new rows here to support more documents - nothing else hardcoded.
# ----------------------------------------------------------------------
DOC_CONFIG = {
    "Sales Invoice": {
        "date_field": "posting_date", "party_field": "customer", "party_type": "Customer",
        "title_field": "customer_name",
        "picker_fields": ["customer_name", "posting_date", "grand_total", "status"],
        "filter_fields": ["customer_group", "territory", "sales_partner", "is_return", "currency"],
    },
    "Quotation": {
        "date_field": "transaction_date", "party_field": "party_name", "party_type": "Customer",
        "title_field": "customer_name",
        "picker_fields": ["customer_name", "transaction_date", "grand_total", "status"],
        "filter_fields": ["quotation_to", "customer_group", "territory", "currency"],
    },
    "Delivery Note": {
        "date_field": "posting_date", "party_field": "customer", "party_type": "Customer",
        "title_field": "customer_name",
        "picker_fields": ["customer_name", "posting_date", "grand_total", "status"],
        "filter_fields": ["customer_group", "territory", "set_warehouse", "currency"],
    },
    "Sales Order": {
        "date_field": "transaction_date", "party_field": "customer", "party_type": "Customer",
        "title_field": "customer_name",
        "picker_fields": ["customer_name", "transaction_date", "grand_total", "status"],
        "filter_fields": ["customer_group", "territory", "order_type", "currency"],
    },
    "Purchase Invoice": {
        "date_field": "posting_date", "party_field": "supplier", "party_type": "Supplier",
        "title_field": "supplier_name",
        "picker_fields": ["supplier_name", "posting_date", "grand_total", "status"],
        "filter_fields": ["supplier_group", "is_return", "currency"],
    },
    "Purchase Order": {
        "date_field": "transaction_date", "party_field": "supplier", "party_type": "Supplier",
        "title_field": "supplier_name",
        "picker_fields": ["supplier_name", "transaction_date", "grand_total", "status"],
        "filter_fields": ["supplier_group", "currency"],
    },
    "Purchase Receipt": {
        "date_field": "posting_date", "party_field": "supplier", "party_type": "Supplier",
        "title_field": "supplier_name",
        "picker_fields": ["supplier_name", "posting_date", "grand_total", "status"],
        "filter_fields": ["supplier_group", "set_warehouse", "currency"],
    },
    "Payment Entry": {
        "date_field": "posting_date", "party_field": "party", "party_type": None,
        "title_field": "party_name",
        "picker_fields": ["party_type", "party_name", "posting_date", "paid_amount", "status"],
        "filter_fields": ["payment_type", "mode_of_payment", "party_type"],
    },
    "Journal Entry": {
        "date_field": "posting_date", "party_field": None, "party_type": None,
        "title_field": "title",
        "picker_fields": ["title", "posting_date", "voucher_type", "total_debit"],
        "filter_fields": ["voucher_type", "finance_book"],
    },
    "Stock Entry": {
        "date_field": "posting_date", "party_field": None, "party_type": None,
        "title_field": "title",
        "picker_fields": ["title", "posting_date", "stock_entry_type", "total_amount"],
        "filter_fields": ["stock_entry_type", "purpose", "from_warehouse", "to_warehouse"],
    },
    # ---------------- Asset Management ----------------
    "Asset": {
        "date_field": "purchase_date", "party_field": None, "party_type": None,
        "title_field": "asset_name",
        "picker_fields": [
            "asset_name", "item_code", "asset_category", "location",
            "custodian", "purchase_date", "gross_purchase_amount", "status",
        ],
        "filter_fields": [
            "asset_category", "location", "custodian", "status", "item_code",
            "asset_owner", "department", "finance_book", "is_existing_asset",
            "maintenance_required", "calculate_depreciation",
        ],
    },
    "Asset Movement": {
        "date_field": "transaction_date", "party_field": None, "party_type": None,
        "title_field": "purpose",
        "picker_fields": ["purpose", "transaction_date", "company"],
        "filter_fields": ["purpose"],
    },
    "Asset Repair": {
        "date_field": "failure_date", "party_field": None, "party_type": None,
        "title_field": "asset_name",
        "picker_fields": ["asset", "asset_name", "failure_date", "repair_status", "repair_cost"],
        "filter_fields": ["asset", "repair_status", "cost_center", "project"],
    },
    "Asset Capitalization": {
        "date_field": "posting_date", "party_field": None, "party_type": None,
        "title_field": "target_asset_name",
        "picker_fields": ["posting_date", "entry_type", "target_asset_name", "total_value"],
        "filter_fields": ["entry_type", "target_asset", "target_item_code"],
    },
}

SUPPORTED_DOCTYPES = list(DOC_CONFIG.keys())

# Filters offered on any doctype that happens to have the field.
GENERIC_FILTER_FIELDS = [
    "status", "cost_center", "project", "branch", "department",
    "finance_book", "currency", "owner",
]


def get_config(doctype):
    cfg = DOC_CONFIG.get(doctype)
    if not cfg:
        frappe.throw(f"Document type '{doctype}' is not supported by the Document Center.")
    return cfg


def get_picker_fields(doctype):
    """Fields to display in the selection grid (existing ones only)."""
    cfg = get_config(doctype)
    meta = frappe.get_meta(doctype)
    fields = ["name"]
    for f in cfg.get("picker_fields") or []:
        if meta.get_field(f) and f not in fields:
            fields.append(f)
    return fields


def get_accounting_dimensions():
    """Every active accounting dimension defined in the system.

    Returns a list of {fieldname, label, document_type}. Includes the two
    default dimensions (Cost Center, Project) plus any custom dimension the
    client has configured - Branch, Division, Segment, Site, etc.
    """
    dims = []
    if not frappe.db.exists("DocType", "Accounting Dimension"):
        return dims
    try:
        records = frappe.get_all(
            "Accounting Dimension",
            filters={"disabled": 0},
            fields=["fieldname", "label", "document_type"],
        )
    except Exception:
        return dims

    for row in records:
        if row.get("fieldname"):
            dims.append(
                {
                    "fieldname": row["fieldname"],
                    "label": row.get("label") or frappe.unscrub(row["fieldname"]),
                    "document_type": row.get("document_type"),
                }
            )

    # Default dimensions are not always stored as Accounting Dimension records.
    known = {d["fieldname"] for d in dims}
    for fieldname, doctype in (("cost_center", "Cost Center"), ("project", "Project")):
        if fieldname not in known:
            dims.append(
                {"fieldname": fieldname, "label": frappe.unscrub(fieldname), "document_type": doctype}
            )
    return dims


def _field_def(meta, fieldname, label=None, link_to=None):
    """Turn a DocField into a filter control definition for the UI."""
    df = meta.get_field(fieldname)
    if not df:
        return None

    fieldtype = df.fieldtype
    options = df.options

    if fieldtype in ("Link", "Dynamic Link"):
        fieldtype = "Link"
        options = link_to or (options if df.fieldtype == "Link" else None)
        if not options:
            return None
    elif fieldtype == "Select":
        options = "\n".join([""] + [o for o in (df.options or "").split("\n") if o])
    elif fieldtype == "Check":
        options = None
    elif fieldtype in ("Data", "Small Text", "Text"):
        fieldtype = "Data"
    else:
        # Skip currency/float/table/etc - not useful as a simple equality filter.
        return None

    return {
        "fieldname": fieldname,
        "label": label or df.label or frappe.unscrub(fieldname),
        "fieldtype": fieldtype,
        "options": options,
    }


def get_filter_schema(doctype):
    """Filter controls the UI should render for this document type.

    Combines: company, party, doctype-specific fields, generic fields, and
    every accounting dimension configured in the system that exists on the
    document.
    """
    cfg = get_config(doctype)
    meta = frappe.get_meta(doctype)
    schema = []
    seen = set()

    def push(definition):
        if definition and definition["fieldname"] not in seen:
            seen.add(definition["fieldname"])
            schema.append(definition)

    if meta.get_field("company"):
        push({"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company"})

    # Party filter, driven by the doctype config.
    party_field = cfg.get("party_field")
    if party_field and meta.get_field(party_field):
        party_type = cfg.get("party_type")
        if party_type:
            push({"fieldname": "party", "label": party_type, "fieldtype": "Link", "options": party_type})
        else:
            push({"fieldname": "party_type", "label": "Party Type", "fieldtype": "Select",
                  "options": "\nCustomer\nSupplier\nEmployee\nShareholder"})
            push({"fieldname": "party", "label": "Party", "fieldtype": "Dynamic Link", "options": "party_type"})
        seen.add(party_field)

    for fieldname in cfg.get("filter_fields") or []:
        push(_field_def(meta, fieldname))

    for dim in get_accounting_dimensions():
        push(_field_def(meta, dim["fieldname"], label=dim["label"], link_to=dim.get("document_type")))

    for fieldname in GENERIC_FILTER_FIELDS:
        push(_field_def(meta, fieldname))

    return {
        "doctype": doctype,
        "date_field": cfg["date_field"],
        "date_field_label": (meta.get_field(cfg["date_field"]).label
                             if meta.get_field(cfg["date_field"]) else None),
        "is_submittable": bool(meta.is_submittable),
        "filters": schema,
    }


def _filterable_fieldnames(doctype):
    return [f["fieldname"] for f in get_filter_schema(doctype)["filters"]]


def build_filters(args):
    """Build a Frappe filter LIST from job/UI arguments.

    A list (rather than a dict) is used so more than one condition can apply
    to the same field - e.g. a document-number range needs both >= and <=.
    """
    if not isinstance(args, dict):
        args = args.as_dict() if hasattr(args, "as_dict") else dict(args)

    doctype = args.get("document_type")
    cfg = get_config(doctype)
    meta = frappe.get_meta(doctype)
    conditions = []

    # ---- date range -------------------------------------------------
    date_field = args.get("date_field") or cfg["date_field"]
    if meta.get_field(date_field):
        from_date, to_date = args.get("from_date"), args.get("to_date")
        if from_date and to_date:
            conditions.append([date_field, "between", [from_date, to_date]])
        elif from_date:
            conditions.append([date_field, ">=", from_date])
        elif to_date:
            conditions.append([date_field, "<=", to_date])

    # ---- document number range --------------------------------------
    from_doc, to_doc = args.get("from_document"), args.get("to_document")
    if from_doc:
        conditions.append(["name", ">=", from_doc])
    if to_doc:
        conditions.append(["name", "<=", to_doc])

    # ---- party ------------------------------------------------------
    party = args.get("party")
    if party and cfg.get("party_field"):
        conditions.append([cfg["party_field"], "=", party])
        if cfg["party_field"] == "party" and args.get("party_type"):
            conditions.append(["party_type", "=", args["party_type"]])

    # ---- every declared filter field / accounting dimension ---------
    for fieldname in _filterable_fieldnames(doctype):
        if fieldname in ("company", "party", "party_type"):
            continue
        value = args.get(fieldname)
        if value in (None, "", []):
            continue
        if meta.get_field(fieldname):
            conditions.append([fieldname, "=", value])

    if args.get("company") and meta.get_field("company"):
        conditions.append(["company", "=", args["company"]])

    # ---- draft handling ---------------------------------------------
    if meta.is_submittable:
        conditions.append(["docstatus", "<", 2] if args.get("include_drafts") else ["docstatus", "=", 1])

    # ---- power-user JSON --------------------------------------------
    extra = args.get("additional_filters")
    if extra:
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except ValueError:
                frappe.throw("Additional Filters is not valid JSON.")
        if isinstance(extra, dict):
            for key, value in extra.items():
                if not meta.get_field(key) and key != "name":
                    continue
                if isinstance(value, list) and len(value) == 2:
                    conditions.append([key, value[0], value[1]])
                else:
                    conditions.append([key, "=", value])
        elif isinstance(extra, list):
            conditions.extend(extra)

    return conditions


def get_party_for(doctype, name):
    """Return the party value for a single document, or None."""
    cfg = DOC_CONFIG.get(doctype) or {}
    field = cfg.get("party_field")
    if not field:
        return None
    return frappe.db.get_value(doctype, name, field)


def get_party_email(party_type, party):
    if not (party_type and party):
        return None
    return frappe.db.get_value(party_type, party, "email_id")


def publish_progress(job_name, processed, total, status, file_url=None):
    """Push a live progress update to the Document Center page."""
    progress = round((processed / total) * 100, 1) if total else 0
    frappe.publish_realtime(
        "adc_job_progress",
        {
            "job": job_name,
            "processed": processed,
            "total": total,
            "progress": progress,
            "status": status,
            "file_url": file_url,
        },
    )
