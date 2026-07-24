// Copyright (c) 2026, Neotec Integrated Solution and contributors
// Shared document picker + list-view "Bulk Print" action.

frappe.provide("alphax_document_center");

alphax_document_center.SUPPORTED = [];

// ---------------------------------------------------------------------
// Reusable picker dialog: shows matching records with checkboxes.
// on_select receives an array of row objects (each has .name and .__title)
// ---------------------------------------------------------------------
alphax_document_center.pick_documents = function (args, on_select) {
	if (!args.document_type) {
		frappe.msgprint(__("Select a Document Type first."));
		return;
	}

	const d = new frappe.ui.Dialog({
		title: __("Select {0} Documents", [args.document_type]),
		size: "extra-large",
		fields: [
			{ fieldname: "search", fieldtype: "Data", label: __("Search"), placeholder: __("Name or title…") },
			{ fieldname: "include_drafts", fieldtype: "Check", label: __("Include Drafts"), default: args.include_drafts ? 1 : 0 },
			{ fieldname: "grid_html", fieldtype: "HTML" },
		],
		primary_action_label: __("Add Selected"),
		primary_action() {
			const picked = [];
			d.$wrapper.find(".adc-row-check:checked").each(function () {
				const name = $(this).data("name");
				const row = (d._rows || []).find((r) => r.name === name);
				if (row) picked.push(row);
			});
			if (!picked.length) {
				frappe.msgprint(__("No documents ticked."));
				return;
			}
			d.hide();
			on_select(picked);
		},
	});

	const area = d.get_field("grid_html").$wrapper;

	function load() {
		area.html(`<div class="text-muted p-3">${__("Loading…")}</div>`);
		frappe.call({
			method: "alphax_document_center.api.list_documents",
			args: {
				args: Object.assign({}, args, { include_drafts: d.get_value("include_drafts") }),
				search: d.get_value("search") || null,
				limit: 1000,
			},
			callback: (r) => render((r.message && r.message.rows) || [], (r.message && r.message.fields) || []),
		});
	}

	function render(rows, fields) {
		d._rows = rows;
		if (!rows.length) {
			area.html(`<div class="text-muted p-3">${__("No documents match.")}</div>`);
			return;
		}
		const cols = fields.filter((f) => f !== "name");
		const head = cols.map((c) => `<th>${frappe.model.unscrub(c)}</th>`).join("");
		const body = rows
			.map((row) => {
				// Remember a friendly title for the child table.
				row.__title = row[cols[0]] || "";
				const cells = cols
					.map((c) => `<td>${frappe.utils.escape_html(String(row[c] == null ? "" : row[c]))}</td>`)
					.join("");
				return `<tr>
					<td><input type="checkbox" class="adc-row-check" data-name="${frappe.utils.escape_html(row.name)}"></td>
					<td><b>${frappe.utils.escape_html(row.name)}</b></td>
					${cells}
				</tr>`;
			})
			.join("");

		area.html(`
			<div class="mb-2 d-flex justify-content-between align-items-center">
				<span class="text-muted small">${__("{0} record(s)", [rows.length])}</span>
				<span class="text-muted small adc-picked">0 ${__("selected")}</span>
			</div>
			<div style="max-height: 55vh; overflow:auto; border:1px solid var(--border-color); border-radius:var(--border-radius);">
				<table class="table table-sm mb-0">
					<thead style="position:sticky; top:0; background:var(--fg-color); z-index:1;">
						<tr>
							<th style="width:36px;"><input type="checkbox" class="adc-check-all"></th>
							<th>${__("ID")}</th>
							${head}
						</tr>
					</thead>
					<tbody>${body}</tbody>
				</table>
			</div>
		`);

		const update_count = () => {
			const n = area.find(".adc-row-check:checked").length;
			area.find(".adc-picked").text(`${n} ${__("selected")}`);
		};
		area.find(".adc-check-all").on("change", function () {
			area.find(".adc-row-check").prop("checked", $(this).is(":checked"));
			update_count();
		});
		area.find(".adc-row-check").on("change", update_count);
	}

	let timer = null;
	d.get_field("search").$input.on("input", () => {
		clearTimeout(timer);
		timer = setTimeout(load, 350);
	});
	d.get_field("include_drafts").$input.on("change", load);

	d.show();
	load();
};

// ---------------------------------------------------------------------
// Bulk Print action in the list view of every supported doctype.
// ---------------------------------------------------------------------
// Remember what was chosen last time for this doctype, per user. Tagging is
// repetitive - the second run should be one click.
alphax_document_center.remember = function (doctype, values) {
	try {
		frappe.model.user_settings.save(doctype, "adc_bulk_print", values);
	} catch (e) {
		/* settings are a convenience, never a hard failure */
	}
};

alphax_document_center.recall = function (doctype) {
	try {
		const s = frappe.get_user_settings(doctype);
		return (s && s.adc_bulk_print) || {};
	} catch (e) {
		return {};
	}
};

alphax_document_center.LABEL_SIZES = {
	"50 x 28 mm (1.97 x 1.10 in)": [50, 28],
	"50 x 25 mm": [50, 25],
	"40 x 30 mm": [40, 30],
	"57 x 32 mm": [57, 32],
	"76 x 25 mm": [76, 25],
	"100 x 50 mm": [100, 50],
	"100 x 150 mm (shipping)": [100, 150],
};

// Watch a job and offer the file the moment it is ready.
alphax_document_center.follow_job = function (job_name, count) {
	const handler = (data) => {
		if (data.job !== job_name) return;
		if (data.status === "Completed" || data.status === "Partially Completed") {
			frappe.realtime.off("adc_job_progress", handler);
			frappe.msgprint({
				title: __("Ready to print"),
				indicator: "green",
				message: `
					<div>${__("{0} document(s) generated.", [data.processed || count])}</div>
					${
						data.file_url
							? `<a class="btn btn-primary btn-sm mt-3" href="${data.file_url}" target="_blank" download>${__(
									"Download"
							  )}</a>`
							: ""
					}
					<div class="text-muted small mt-2">
						<a href="/app/bulk-document-job/${job_name}">${__("Open job {0}", [job_name])}</a>
					</div>`,
			});
		} else if (data.status === "Failed") {
			frappe.realtime.off("adc_job_progress", handler);
			frappe.msgprint({
				title: __("Generation failed"),
				indicator: "red",
				message: `<a href="/app/bulk-document-job/${job_name}">${__(
					"Open job {0} to see why", [job_name]
				)}</a>`,
			});
		}
	};
	frappe.realtime.on("adc_job_progress", handler);
};

alphax_document_center.bulk_print_dialog = function (doctype, names, done) {
	frappe.call({
		method: "alphax_document_center.api.get_print_setup",
		args: { doctype: doctype },
		callback: (r) => {
			const setup = r.message || {};
			const formats = setup.formats || ["Standard"];
			const last = alphax_document_center.recall(doctype);

			const looks_like_label = (f) => /qr|label|sticker|tag|barcode/i.test(f || "");

			// Last used, else the doctype's Default Print Format, else a label format.
			const default_format =
				(last.print_format && formats.includes(last.print_format) && last.print_format) ||
				setup.default ||
				formats[0];

			const label_on =
				last.label_mode !== undefined
					? !!last.label_mode
					: looks_like_label(default_format);

			const d = new frappe.ui.Dialog({
				title: __("Print {0} selected {1}", [names.length, doctype]),
				fields: [
					{
						fieldname: "selected_info",
						fieldtype: "HTML",
						options: `<div class="mb-3" style="padding:8px 12px;border-radius:6px;
							background:var(--bg-light-gray);border:1px solid var(--border-color);">
							<b>${names.length}</b> ${__("selected")} —
							<span class="text-muted small">${frappe.utils.escape_html(
								names.slice(0, 4).join(", ")
							)}${names.length > 4 ? ", …" : ""}</span>
							<div class="text-muted small mt-1">${__(
								"Only these will be printed."
							)}</div>
						</div>`,
					},
					{
						fieldname: "print_format", fieldtype: "Select", label: __("Print Format"),
						options: formats, default: default_format, reqd: 1,
						description: setup.doctype_default
							? __("Default for {0}: {1}", [doctype, setup.doctype_default])
							: __("This document type has no default print format set."),
						onchange: () => {
							if (looks_like_label(d.get_value("print_format"))) {
								d.set_value("label_mode", 1);
							}
						},
					},
					{
						fieldname: "label_mode", fieldtype: "Check",
						label: __("Label / continuous roll"),
						default: label_on ? 1 : 0,
						description: __("Sizes each page to the label, with no margins or letter head."),
					},
					{
						fieldname: "label_preset", fieldtype: "Select", label: __("Label Size"),
						depends_on: "label_mode",
						options: Object.keys(alphax_document_center.LABEL_SIZES).concat(["Custom"]),
						default: last.label_preset || "50 x 28 mm (1.97 x 1.10 in)",
						onchange: () => {
							const s = alphax_document_center.LABEL_SIZES[d.get_value("label_preset")];
							if (s) {
								d.set_value("label_width_mm", s[0]);
								d.set_value("label_height_mm", s[1]);
							}
						},
					},
					{ fieldname: "cb_label", fieldtype: "Column Break", depends_on: "label_mode" },
					{
						fieldname: "label_width_mm", fieldtype: "Float", label: __("Width (mm)"),
						default: last.label_width_mm || 50, depends_on: "label_mode",
					},
					{
						fieldname: "label_height_mm", fieldtype: "Float", label: __("Height (mm)"),
						default: last.label_height_mm || 28, depends_on: "label_mode",
					},
					{ fieldname: "sb_out", fieldtype: "Section Break" },
					{
						fieldname: "output_type", fieldtype: "Select", label: __("Output"),
						options: ["Single PDF", "ZIP of PDFs"],
						default: names.length > 50 && !looks_like_label(default_format)
							? "ZIP of PDFs" : "Single PDF",
						description: __("Labels should stay a Single PDF so the roll feeds continuously."),
					},
					{
						fieldname: "info", fieldtype: "HTML",
						options: `<div class="text-muted small">${__(
							"Runs in the background. The download appears here as soon as it is ready."
						)}</div>`,
					},
				],
				primary_action_label: __("Generate"),
				primary_action(values) {
					d.hide();
					alphax_document_center.remember(doctype, {
						print_format: values.print_format,
						label_mode: values.label_mode ? 1 : 0,
						label_preset: values.label_preset,
						label_width_mm: values.label_width_mm,
						label_height_mm: values.label_height_mm,
						output_type: values.output_type,
					});
					frappe.call({
						method: "alphax_document_center.api.create_from_selection",
						args: {
							doctype: doctype,
							names: names,
							print_format: values.print_format === "Standard" ? null : values.print_format,
							output_type: values.label_mode ? "Single PDF" : values.output_type,
							label_mode: values.label_mode ? 1 : 0,
							label_preset: values.label_preset,
							label_width_mm: values.label_width_mm,
							label_height_mm: values.label_height_mm,
						},
						freeze: true,
						freeze_message: __("Queuing {0} document(s)…", [names.length]),
						callback: (res) => {
							if (done) done();
							alphax_document_center.follow_job(res.message, names.length);
							frappe.show_alert({
								message: __("Generating {0} document(s)…", [names.length]),
								indicator: "blue",
							}, 7);
						},
					});
				},
			});
			d.show();
		},
	});
};

// ---------------------------------------------------------------------
// List view integration.
//   - "Print Labels" sits in the toolbar for doctypes that actually have a
//     label format, because tagging is a repeated task and Actions is too
//     deep for it.
//   - "Bulk Print" stays in Actions for everything else, which is where
//     Frappe users expect bulk operations to live.
// ---------------------------------------------------------------------
alphax_document_center._setup_cache = {};

alphax_document_center.get_setup = function (doctype) {
	if (alphax_document_center._setup_cache[doctype]) {
		return Promise.resolve(alphax_document_center._setup_cache[doctype]);
	}
	return frappe
		.call({ method: "alphax_document_center.api.get_print_setup", args: { doctype: doctype } })
		.then((r) => {
			alphax_document_center._setup_cache[doctype] = r.message || {};
			return alphax_document_center._setup_cache[doctype];
		});
};

function checked_or_warn(listview) {
	const names = listview.get_checked_items(true);
	if (!names || !names.length) {
		frappe.msgprint({
			title: __("Nothing selected"),
			indicator: "orange",
			message: __("Tick the rows you want to print, then try again."),
		});
		return null;
	}
	return names;
}

frappe.after_ajax(() => {
	frappe.call({ method: "alphax_document_center.api.get_supported_doctypes" }).then((r) => {
		alphax_document_center.SUPPORTED = r.message || [];
		alphax_document_center.SUPPORTED.forEach((dt) => {
			frappe.listview_settings[dt] = frappe.listview_settings[dt] || {};
			const existing_onload = frappe.listview_settings[dt].onload;

			frappe.listview_settings[dt].onload = function (listview) {
				if (existing_onload) existing_onload(listview);

				// Always available, in the conventional place.
				listview.page.add_actions_menu_item(
					__("Bulk Print"),
					() => {
						const names = checked_or_warn(listview);
						if (names) {
							alphax_document_center.bulk_print_dialog(dt, names, () =>
								listview.clear_checked_items()
							);
						}
					},
					false
				);

				// Promoted to the toolbar when this doctype has a label format.
				alphax_document_center.get_setup(dt).then((setup) => {
					if (!setup.has_label_format) return;
					listview.page.add_inner_button(__("Print Labels"), () => {
						const names = checked_or_warn(listview);
						if (names) {
							alphax_document_center.bulk_print_dialog(dt, names, () =>
								listview.clear_checked_items()
							);
						}
					});
				});
			};
		});
	});
});

// ---------------------------------------------------------------------
// Form view: reprint a single record's label without building a job by hand.
// Useful when one sticker is damaged or an asset is re-tagged.
// ---------------------------------------------------------------------
frappe.after_ajax(() => {
	frappe.call({ method: "alphax_document_center.api.get_supported_doctypes" }).then((r) => {
		(r.message || []).forEach((dt) => {
			frappe.ui.form.on(dt, {
				refresh(frm) {
					if (frm.is_new()) return;
					alphax_document_center.get_setup(dt).then((setup) => {
						if (!setup.has_label_format) return;
						frm.add_custom_button(__("Print Label"), () => {
							alphax_document_center.bulk_print_dialog(dt, [frm.doc.name]);
						}, __("Print"));
					});
				},
			});
		});
	});
});
