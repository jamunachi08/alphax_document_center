app_name = "alphax_document_center"
app_title = "Alpha-X Document Center"
app_publisher = "Neotec Integrated Solution"
app_description = "Bulk PDF, ZIP & Document Distribution Engine for Alpha-X ERP"
app_email = "support@neotec.ai"
app_license = "MIT"
required_apps = ["frappe"]

# Include the shared picker + list-view "Bulk Print" action on every desk page.
app_include_js = ["adc_bulk_print.bundle.js"]

# Helpers callable from any Print Format, e.g. {{ alphax_qr(doc.name) }}
jinja = {
    "methods": [
        "alphax_document_center.jinja_methods.alphax_qr",
        "alphax_document_center.jinja_methods.alphax_asset_qr",
        "alphax_document_center.jinja_methods.alphax_asset_payload",
    ]
}

# Scheduler --------------------------------------------------------------
# Run the monthly archive job at 02:00 on the 1st of every month.
# It is a no-op unless enabled in "Document Center Settings".
scheduler_events = {
    "cron": {
        "0 2 1 * *": [
            "alphax_document_center.jobs.create_monthly_archive"
        ]
    }
}

# Fixtures (export the workspace so it ships with the app) ----------------
fixtures = [
    {
        "doctype": "Workspace",
        "filters": [["name", "in", ["Document Center"]]],
    }
]
