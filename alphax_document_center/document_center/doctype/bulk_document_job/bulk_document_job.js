// Copyright (c) 2026, Neotec Integrated Solution and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bulk Document Job", {
	refresh(frm) {
		frm.set_query("print_format", function () {
			return { filters: { doc_type: frm.doc.document_type, disabled: 0 } };
		});

		// The child Document field is a Dynamic Link driven by row.document_type.
		set_row_link_doctype(frm);

		const busy = ["Queued", "Running"].includes(frm.doc.status);

		if (!frm.is_new() && !busy) {
			frm.add_custom_button(__("Generate Documents"), function () {
				frappe.call({
					method: "alphax_document_center.api.enqueue_job",
					args: { job_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Queuing job…"),
					callback: function () {
						frappe.show_alert({ message: __("Job queued"), indicator: "green" });
						frm.reload_doc();
					},
				});
			}).addClass("btn-primary");
		}

		if (!busy && frm.doc.document_type) {
			frm.add_custom_button(__("Pick Documents"), () => open_picker(frm));
		}

		// ---- Selection helpers (Selected Documents mode) ----
		if (!busy && frm.doc.selection_mode === "Selected Documents") {
			const grid = frm.fields_dict.selected_documents.grid;

			frm.add_custom_button(__("Print Only Ticked Rows"), () => {
				const picked = grid.get_selected();
				if (!picked.length) {
					frappe.msgprint(__("Tick the rows you want to print first."));
					return;
				}
				const keep = new Set(
					picked.map((cdn) => (locals["Bulk Document Item"][cdn] || {}).document_name)
				);
				let on = 0;
				(frm.doc.selected_documents || []).forEach((row) => {
					const val = keep.has(row.document_name) ? 1 : 0;
					frappe.model.set_value(row.doctype, row.name, "include", val);
					if (val) on++;
				});
				grid.clear_selection && grid.clear_selection();
				frm.refresh_field("selected_documents");
				frappe.show_alert({
					message: __("{0} row(s) marked for printing", [on]),
					indicator: "green",
				});
			}, __("Selection"));

			frm.add_custom_button(__("Tick All"), () => set_include_all(frm, 1), __("Selection"));
			frm.add_custom_button(__("Untick All"), () => set_include_all(frm, 0), __("Selection"));

			frm.add_custom_button(__("Remove Ticked Rows"), () => {
				const picked = grid.get_selected();
				if (!picked.length) {
					frappe.msgprint(__("Tick the rows you want to remove."));
					return;
				}
				picked.forEach((cdn) => frappe.model.clear_doc("Bulk Document Item", cdn));
				frm.refresh_field("selected_documents");
			}, __("Selection"));

			frm.add_custom_button(__("Retry Failed Only"), () => {
				let n = 0;
				(frm.doc.selected_documents || []).forEach((row) => {
					const val = row.result === "Failed" ? 1 : 0;
					frappe.model.set_value(row.doctype, row.name, "include", val);
					if (val) n++;
				});
				frm.refresh_field("selected_documents");
				frappe.show_alert({ message: __("{0} failed row(s) marked", [n]), indicator: "orange" });
			}, __("Selection"));
		}

		// ---- Diagnostics ----
		if (frm.doc.document_type) {
			frm.add_custom_button(__("Test Render"), () => test_render(frm), __("Tools"));
			frm.add_custom_button(__("Diagnose Print Issue"), () => diagnose_print(frm), __("Tools"));
		}
		const failed_rows = (frm.doc.selected_documents || []).filter(
			(r) => r.result === "Failed" && r.error_message
		);
		if (failed_rows.length) {
			frm.add_custom_button(__("Why Rows Failed"), () => {
				const html = failed_rows
					.slice(0, 30)
					.map(
						(r) =>
							`<div style="margin-bottom:10px;"><b>${frappe.utils.escape_html(
								r.document_name
							)}</b><pre style="white-space:pre-wrap;font-size:11px;margin:2px 0;">${frappe.utils.escape_html(
								r.error_message
							)}</pre></div>`
					)
					.join("");
				frappe.msgprint({
					title: __("{0} failed row(s)", [failed_rows.length]),
					indicator: "red",
					wide: true,
					message: `<div style="max-height:60vh;overflow:auto;">${html}</div>`,
				});
			}, __("Tools"));
		}

		if (frm.doc.print_format) {
			frm.add_custom_button(__("Repair Print Format"), () => repair_format(frm), __("Tools"));
		}

		frm.add_custom_button(__("Test QR Code"), () => {
			frappe.call({
				method: "alphax_document_center.api.qr_selftest",
				freeze: true,
				freeze_message: __("Generating a QR…"),
				callback: (r) => {
					const res = r.message || {};
					const preview = res.data_uri
						? `<div class="mt-2"><img src="${res.data_uri}" style="width:120px;height:120px;border:1px solid var(--border-color);"></div>`
						: "";
					frappe.msgprint({
						title: __("QR Self-Test"),
						indicator: res.ok ? "green" : "red",
						message: `<div><b>${__("Backend")}:</b> ${frappe.utils.escape_html(
							res.backend || "none"
						)} (${frappe.utils.escape_html(res.format || "-")})</div>
						<div class="mt-1">${frappe.utils.escape_html(res.message || "")}</div>
						${preview}
						<div class="text-muted small mt-2">${__(
							"If this square is visible here but missing in the PDF, the image format is not supported by the PDF engine."
						)}</div>`,
					});
				},
			});
		}, __("Tools"));

		if (frm.doc.error_log) {
			frm.add_custom_button(__("View Error Log"), () => {
				frappe.msgprint({
					title: __("Error Log"),
					indicator: "red",
					message: `<pre style="white-space:pre-wrap; max-height:60vh; overflow:auto; font-size:11px;">${frappe.utils.escape_html(
						frm.doc.error_log
					)}</pre>`,
					wide: true,
				});
			}, __("Tools"));
		}

		if (frm.doc.generated_file) {
			frm.add_custom_button(__("Download File"), function () {
				window.open(frm.doc.generated_file);
			});
		}

		if (busy) {
			frm.dashboard.add_progress(
				__("Progress"),
				frm.doc.progress || 0,
				`${frm.doc.processed_documents || 0} / ${frm.doc.total_documents || 0}`
			);
			if (!frm._adc_listener) {
				frm._adc_listener = true;
				frappe.realtime.on("adc_job_progress", function (data) {
					if (data.job !== frm.doc.name) return;
					if (["Completed", "Failed", "Partially Completed"].includes(data.status)) {
						frm.reload_doc();
					} else {
						frm.dashboard.show_progress(
							__("Progress"),
							data.progress || 0,
							`${data.processed} / ${data.total}`
						);
					}
				});
			}
		}
	},

	label_preset(frm) {
		const sizes = {
			"50 x 28 mm (1.97 x 1.10 in)": [50, 28],
			"50 x 25 mm": [50, 25],
			"40 x 30 mm": [40, 30],
			"57 x 32 mm": [57, 32],
			"76 x 25 mm": [76, 25],
			"100 x 50 mm": [100, 50],
			"100 x 150 mm (shipping)": [100, 150],
		};
		const s = sizes[frm.doc.label_preset];
		if (s) {
			frm.set_value("label_width_mm", s[0]);
			frm.set_value("label_height_mm", s[1]);
		}
	},

	label_mode(frm) {
		if (frm.doc.label_mode) {
			// A label roll wants one sticker per page in a single stream.
			if (!frm.doc.output_type || frm.doc.output_type === "ZIP of PDFs") {
				frm.set_value("output_type", "Single PDF");
			}
			if (!frm.doc.label_width_mm) frm.set_value("label_width_mm", 50);
			if (!frm.doc.label_height_mm) frm.set_value("label_height_mm", 28);
		}
	},

	document_type(frm) {
		frm.set_value("print_format", null);
		frm.clear_table("selected_documents");
		frm.refresh_field("selected_documents");
		set_row_link_doctype(frm);
	},

	// Fires when the user clicks "Add Row" in the Documents grid.
	selected_documents_add(frm, cdt, cdn) {
		if (!frm.doc.document_type) {
			frappe.msgprint(__("Select a Document Type first, then add rows."));
			frappe.model.clear_doc(cdt, cdn);
			frm.refresh_field("selected_documents");
			return;
		}
		frappe.model.set_value(cdt, cdn, "document_type", frm.doc.document_type);
	},

	selection_mode(frm) {
		set_row_link_doctype(frm);
	},
});

// Make the child "Document" field a live link into the parent's document type,
// and backfill document_type on any rows that are missing it.
function set_row_link_doctype(frm) {
	(frm.doc.selected_documents || []).forEach((row) => {
		if (!row.document_type && frm.doc.document_type) {
			row.document_type = frm.doc.document_type;
		}
	});
	frm.refresh_field("selected_documents");
}

// Autocomplete the Document field against the parent's document type.
frappe.ui.form.on("Bulk Document Item", {
	document_name(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.document_name) return;
		if (!row.document_type) row.document_type = frm.doc.document_type;
		// Pull a friendly title + party for the row.
		frappe.call({
			method: "alphax_document_center.api.describe_document",
			args: { doctype: frm.doc.document_type, name: row.document_name },
			callback: (r) => {
				if (!r.message) return;
				frappe.model.set_value(cdt, cdn, "document_title", r.message.title || "");
				frappe.model.set_value(cdt, cdn, "party", r.message.party || "");
			},
		});
	},
});

// ---------------------------------------------------------------------
// Document picker dialog - reused by the Document Center page too.
// ---------------------------------------------------------------------
function open_picker(frm) {
	const args = {
		document_type: frm.doc.document_type,
		company: frm.doc.company,
		party_type: frm.doc.party_type,
		party: frm.doc.party,
		from_date: frm.doc.selection_mode === "Selected Documents" ? null : frm.doc.from_date,
		to_date: frm.doc.selection_mode === "Selected Documents" ? null : frm.doc.to_date,
		include_drafts: frm.doc.include_drafts,
	};

	alphax_document_center.pick_documents(args, (selected) => {
		frm.set_value("selection_mode", "Selected Documents");
		frm.clear_table("selected_documents");
		selected.forEach((row) => {
			const child = frm.add_child("selected_documents");
			child.document_type = frm.doc.document_type;
			child.document_name = row.name;
			child.document_title = row.__title || "";
			child.result = "Pending";
		});
		frm.refresh_field("selected_documents");
		frappe.show_alert({
			message: __("{0} document(s) selected", [selected.length]),
			indicator: "green",
		});
	});
}


function set_include_all(frm, value) {
	(frm.doc.selected_documents || []).forEach((row) => {
		frappe.model.set_value(row.doctype, row.name, "include", value);
	});
	frm.refresh_field("selected_documents");
}

// Render a single document synchronously to surface the real error.
function test_render(frm) {
	const rows = frm.doc.selected_documents || [];
	let name = rows.length ? rows[0].document_name : null;

	const run = (docname) => {
		if (!docname) {
			frappe.msgprint(__("No document to test. Add a row or pick documents first."));
			return;
		}
		frappe.call({
			method: "alphax_document_center.api.test_render",
			args: {
				doctype: frm.doc.document_type,
				name: docname,
				print_format: frm.doc.print_format,
				letter_head: frm.doc.letter_head,
			},
			freeze: true,
			freeze_message: __("Rendering {0}…", [docname]),
			callback: (r) => {
				const res = r.message || {};
				if (res.ok) {
					frappe.msgprint({
						title: __("Render OK"),
						indicator: "green",
						message:
							__("{0} rendered successfully ({1} KB).", [
								docname,
								(res.size / 1024).toFixed(1),
							]) +
							(res.repaired
								? `<br><span class="text-muted small">${__("Auto-repair applied")}: ${frappe.utils.escape_html(
										res.repaired
								  )}</span>`
								: ""),
					});
				} else {
					frappe.msgprint({
						title: __("Render Failed — this is the real cause"),
						indicator: "red",
						wide: true,
						message: `<pre style="white-space:pre-wrap; max-height:60vh; overflow:auto; font-size:11px;">${frappe.utils.escape_html(
							res.error || "Unknown error"
						)}</pre>`,
					});
				}
			},
		});
	};

	// Let the user choose which document to test.
	const d = new frappe.ui.Dialog({
		title: __("Test Render"),
		fields: [
			{
				fieldname: "docname",
				fieldtype: "Link",
				label: frm.doc.document_type,
				options: frm.doc.document_type,
				default: name,
				reqd: 1,
			},
			{
				fieldname: "info",
				fieldtype: "HTML",
				options: `<div class="text-muted small">${__(
					"Renders one document right now using this job's print format and letter head, and shows the exact error if it fails."
				)}</div>`,
			},
		],
		primary_action_label: __("Render"),
		primary_action(v) {
			d.hide();
			run(v.docname);
		},
	});
	d.show();
}


// Locate broken <img> tags and say which Letter Head / Print Format holds them.
function diagnose_print(frm) {
	const rows = frm.doc.selected_documents || [];
	const d = new frappe.ui.Dialog({
		title: __("Diagnose Print Issue"),
		fields: [
			{
				fieldname: "docname",
				fieldtype: "Link",
				label: frm.doc.document_type,
				options: frm.doc.document_type,
				default: rows.length ? rows[0].document_name : null,
				reqd: 1,
			},
		],
		primary_action_label: __("Diagnose"),
		primary_action(v) {
			d.hide();
			frappe.call({
				method: "alphax_document_center.api.diagnose_print",
				args: {
					doctype: frm.doc.document_type,
					name: v.docname,
					print_format: frm.doc.print_format,
					letter_head: frm.doc.letter_head,
				},
				freeze: true,
				freeze_message: __("Analysing…"),
				callback: (r) => {
					const res = r.message || {};
					let html = "";

					// Configuration findings come first - these are usually the cause.
					const cfg = res.config || [];
					if (cfg.length) {
						const colour = { error: "red", warning: "orange", info: "gray" };
						html += `<div class="mb-3"><b>${__("Configuration")}</b>`;
						cfg.forEach((c) => {
							html += `<div class="mt-1"><span class="indicator-pill ${
								colour[c.level] || "gray"
							}">${c.level}</span> ${frappe.utils.escape_html(c.message)}</div>`;
						});
						html += `</div>`;
					}

					if (res.error) {
						html += `<div class="mb-3"><b>${__("Render still fails")}</b>
							<pre style="white-space:pre-wrap;font-size:11px;">${frappe.utils.escape_html(res.error)}</pre></div>`;
					}

					const n = (res.broken_images || []).length;
					html += `<p><b>${__("Image tags missing a src attribute")}:</b> ${n}</p>`;

					if (n) {
						html += `<p class="text-muted small">${__(
							"These crash Frappe's PDF engine. Document Center gives them a transparent placeholder so the render succeeds and any script that fills them still works. For a QR code, generating it server-side with {{ alphax_qr(doc.name) }} is the reliable fix."
						)}</p>`;
						(res.sources || []).forEach((src) => {
							html += `<div class="mb-2"><b>${frappe.utils.escape_html(src.where)}</b>`;
							if (src.tags && src.tags.length) {
								html += `<pre style="white-space:pre-wrap;font-size:11px;">${frappe.utils.escape_html(
									src.tags.join("\n")
								)}</pre>`;
							}
							html += `</div>`;
						});
						html += `<details><summary class="text-muted small">${__(
							"Show offending tags from the rendered output"
						)}</summary><pre style="white-space:pre-wrap;font-size:11px;">${frappe.utils.escape_html(
							(res.broken_images || []).join("\n")
						)}</pre></details>`;
					}

					if (res.render_ok) {
						html += `<div class="mt-3 text-success"><b>${__(
							"After auto-repair this document renders fine"
						)}</b> (${((res.size || 0) / 1024).toFixed(1)} KB).</div>`;
					}

					frappe.msgprint({
						title: __("Print Diagnosis"),
						indicator: res.render_ok ? "green" : "red",
						wide: true,
						message: `<div style="max-height:60vh;overflow:auto;">${html}</div>`,
					});
				},
			});
		},
	});
	d.show();
}


// Preview and optionally apply a fix to the print format's image tags.
function repair_format(frm) {
	frappe.call({
		method: "alphax_document_center.api.repair_print_format_api",
		args: { print_format: frm.doc.print_format, dry_run: 1 },
		freeze: true,
		freeze_message: __("Checking print format…"),
		callback: (r) => {
			const res = r.message || {};
			const notes = (res.messages || [])
				.map((m) => `<div class="mt-1">${frappe.utils.escape_html(m)}</div>`)
				.join("");

			if (!res.changed) {
				frappe.msgprint({
					title: __("Nothing to repair"),
					indicator: "blue",
					message: notes || __("No changes needed."),
				});
				return;
			}

			// Show only the image lines that change, not the whole template.
			const before_lines = (res.before || "").split("\n");
			const after_lines = (res.after || "").split("\n");
			let diff = "";
			for (let i = 0; i < Math.max(before_lines.length, after_lines.length); i++) {
				if (before_lines[i] !== after_lines[i]) {
					diff += `<div style="color:var(--red-500)">- ${frappe.utils.escape_html(
						before_lines[i] || ""
					)}</div>`;
					diff += `<div style="color:var(--green-600)">+ ${frappe.utils.escape_html(
						after_lines[i] || ""
					)}</div>`;
				}
			}

			const d = new frappe.ui.Dialog({
				title: __("Repair '{0}'", [res.print_format]),
				size: "large",
				fields: [
					{
						fieldname: "preview",
						fieldtype: "HTML",
						options: `${notes}
							<div class="mt-3"><b>${__("Proposed change")}</b></div>
							<pre style="white-space:pre-wrap;font-size:11px;max-height:45vh;overflow:auto;
								border:1px solid var(--border-color);padding:8px;border-radius:6px;">${diff}</pre>
							<div class="text-muted small mt-2">${__(
								"This edits the print format itself. Nothing else is changed."
							)}</div>`,
					},
				],
				primary_action_label: __("Apply"),
				primary_action() {
					d.hide();
					frappe.call({
						method: "alphax_document_center.api.repair_print_format_api",
						args: { print_format: frm.doc.print_format, dry_run: 0 },
						freeze: true,
						freeze_message: __("Saving…"),
						callback: (r2) => {
							const out = r2.message || {};
							frappe.msgprint({
								title: out.saved ? __("Repaired") : __("Not saved"),
								indicator: out.saved ? "green" : "orange",
								message: (out.messages || []).join("<br>"),
							});
						},
					});
				},
			});
			d.show();
		},
	});
}
