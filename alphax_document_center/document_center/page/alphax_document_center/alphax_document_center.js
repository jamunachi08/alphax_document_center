// Copyright (c) 2026, Neotec Integrated Solution and contributors
// For license information, please see license.txt

frappe.pages["alphax-document-center"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Alpha-X Document Center"),
		single_column: true,
	});
	new DocumentCenter(page);
};

const FETCH_LIMIT = 2000;

class DocumentCenter {
	constructor(page) {
		this.page = page;
		this.controls = {};
		this.base = {};
		this.rows = [];
		this.fields = [];
		this.checked = new Set();
		this.schema = null;
		this._total = 0;
		this.make_layout();
		this.make_base_controls();
		this.bind_realtime();
		this.load_jobs();
	}

	make_layout() {
		this.body = $(`
			<div class="adc-wrap">
				<div class="row">
					<div class="col-md-4">
						<div class="frappe-card p-4 mb-4">
							<h5 class="mb-3">${__("Filters")}</h5>
							<div class="adc-base"></div>
							<div class="adc-dynamic mt-2"></div>
							<div class="adc-actions mt-3"></div>
						</div>
						<div class="frappe-card p-4">
							<h5 class="text-muted">${__("Recent Jobs")}</h5>
							<div class="adc-jobs mt-2"></div>
						</div>
					</div>
					<div class="col-md-8">
						<div class="frappe-card p-4">
							<div class="d-flex justify-content-between align-items-center mb-2">
								<h5 class="mb-0">${__("Documents")}</h5>
								<div class="adc-toolbar"></div>
							</div>
							<div class="adc-results"></div>
						</div>
					</div>
				</div>
			</div>
		`).appendTo(this.page.main);

		this.base_area = this.body.find(".adc-base");
		this.dynamic_area = this.body.find(".adc-dynamic");
		this.actions_area = this.body.find(".adc-actions");
		this.toolbar = this.body.find(".adc-toolbar");
		this.results = this.body.find(".adc-results");
		this.jobs_area = this.body.find(".adc-jobs");
		this.clear_results();
	}

	control(parent, df) {
		const wrap = $('<div class="mb-2"></div>').appendTo(parent);
		const c = frappe.ui.form.make_control({ parent: wrap, df: df, render_input: true });
		c.refresh();
		c.$wrapper_row = wrap;
		return c;
	}

	make_base_controls() {
		this.base.document_type = this.control(this.base_area, {
			fieldname: "document_type",
			label: __("Document Type"),
			fieldtype: "Select",
			options: [""],
			reqd: 1,
			change: () => this.on_doctype_change(),
		});

		const dates = $('<div class="row"></div>').appendTo(this.base_area);
		this.base.from_date = this.control($('<div class="col-6"></div>').appendTo(dates), {
			fieldname: "from_date", label: __("From Date"), fieldtype: "Date",
		});
		this.base.to_date = this.control($('<div class="col-6"></div>').appendTo(dates), {
			fieldname: "to_date", label: __("To Date"), fieldtype: "Date",
		});

		const nums = $('<div class="row"></div>').appendTo(this.base_area);
		this.base.from_document = this.control($('<div class="col-6"></div>').appendTo(nums), {
			fieldname: "from_document", label: __("From Doc No"), fieldtype: "Data",
		});
		this.base.to_document = this.control($('<div class="col-6"></div>').appendTo(nums), {
			fieldname: "to_document", label: __("To Doc No"), fieldtype: "Data",
		});

		this.base.include_drafts = this.control(this.base_area, {
			fieldname: "include_drafts", label: __("Include Drafts"), fieldtype: "Check",
		});

		$(`<hr><div class="text-muted small mb-2">${__("Output")}</div>`).appendTo(this.base_area);
		this.base.print_format = this.control(this.base_area, {
			fieldname: "print_format", label: __("Print Format"), fieldtype: "Link",
			options: "Print Format",
			description: __("Blank = default format"),
			get_query: () => ({ filters: { doc_type: this.base.document_type.get_value(), disabled: 0 } }),
		});
		this.base.letter_head = this.control(this.base_area, {
			fieldname: "letter_head", label: __("Letter Head"), fieldtype: "Link", options: "Letter Head",
		});
		this.base.output_type = this.control(this.base_area, {
			fieldname: "output_type", label: __("Output"), fieldtype: "Select",
			options: ["Single PDF", "ZIP of PDFs"], default: "Single PDF",
		});
		this.base.email_documents = this.control(this.base_area, {
			fieldname: "email_documents", label: __("Email documents to each party"), fieldtype: "Check",
		});

		// --- Label / continuous roll ---
		$(`<hr><div class="text-muted small mb-2">${__("Label / Continuous Roll")}</div>`).appendTo(this.base_area);
		this.base.label_mode = this.control(this.base_area, {
			fieldname: "label_mode", label: __("Label Mode"), fieldtype: "Check",
			change: () => this.toggle_label_fields(),
		});
		this.base.label_preset = this.control(this.base_area, {
			fieldname: "label_preset", label: __("Label Size"), fieldtype: "Select",
			options: [
				"50 x 28 mm (1.97 x 1.10 in)", "50 x 25 mm", "40 x 30 mm", "57 x 32 mm",
				"76 x 25 mm", "100 x 50 mm", "100 x 150 mm (shipping)", "Custom",
			],
			default: "50 x 28 mm (1.97 x 1.10 in)",
			change: () => this.apply_label_preset(),
		});
		const lrow = $('<div class="row"></div>').appendTo(this.base_area);
		this.base.label_width_mm = this.control($('<div class="col-6"></div>').appendTo(lrow), {
			fieldname: "label_width_mm", label: __("Width (mm)"), fieldtype: "Float", default: 50,
		});
		this.base.label_height_mm = this.control($('<div class="col-6"></div>').appendTo(lrow), {
			fieldname: "label_height_mm", label: __("Height (mm)"), fieldtype: "Float", default: 28,
		});
		this.toggle_label_fields();

		this.fetch_btn = $(`<button class="btn btn-default btn-sm mr-2">${__("Fetch Documents")}</button>`)
			.appendTo(this.actions_area).on("click", () => this.fetch());
		this.generate_btn = $(`<button class="btn btn-primary btn-sm">${__("Generate")}</button>`)
			.appendTo(this.actions_area).on("click", () => this.generate());
		this.hint = $('<div class="text-muted small mt-2"></div>').appendTo(this.actions_area);

		frappe.call("alphax_document_center.api.get_supported_doctypes").then((r) => {
			const opts = [""].concat(r.message || []);
			this.base.document_type.df.options = opts;
			this.base.document_type.refresh();
		});
	}

	on_doctype_change() {
		const dt = this.base.document_type.get_value();
		this.clear_results();
		this.dynamic_area.empty();
		this.controls = {};
		this.base.print_format.set_value("");
		if (!dt) return;

		frappe.call({
			method: "alphax_document_center.api.get_filter_fields",
			args: { doctype: dt },
			callback: (r) => {
				this.schema = r.message;
				if (!this.schema) return;
				$(`<div class="text-muted small mb-2">${__("Filters for {0}", [dt])}</div>`).appendTo(this.dynamic_area);
				(this.schema.filters || []).forEach((f) => {
					const df = {
						fieldname: f.fieldname,
						label: __(f.label),
						fieldtype: f.fieldtype,
						options: f.options,
					};
					if (f.fieldtype === "Dynamic Link") {
						df.get_options = () =>
							this.controls.party_type ? this.controls.party_type.get_value() : null;
					}
					this.controls[f.fieldname] = this.control(this.dynamic_area, df);
				});
				this.base.include_drafts.$wrapper_row.toggle(!!this.schema.is_submittable);
			},
		});
	}

	apply_label_preset() {
		const sizes = {
			"50 x 28 mm (1.97 x 1.10 in)": [50, 28],
			"50 x 25 mm": [50, 25],
			"40 x 30 mm": [40, 30],
			"57 x 32 mm": [57, 32],
			"76 x 25 mm": [76, 25],
			"100 x 50 mm": [100, 50],
			"100 x 150 mm (shipping)": [100, 150],
		};
		const s = sizes[this.base.label_preset.get_value()];
		if (s) {
			this.base.label_width_mm.set_value(s[0]);
			this.base.label_height_mm.set_value(s[1]);
		}
	}

	toggle_label_fields() {
		const on = !!this.base.label_mode.get_value();
		["label_preset", "label_width_mm", "label_height_mm"].forEach((f) => {
			this.base[f].$wrapper_row.toggle(on);
		});
		if (on) this.base.output_type.set_value("Single PDF");
	}

	collect(with_selection) {
		const v = {};
		Object.keys(this.base).forEach((k) => (v[k] = this.base[k].get_value()));
		Object.keys(this.controls).forEach((k) => (v[k] = this.controls[k].get_value()));
		if (v.label_mode) v.suppress_letter_head = 1;
		if (with_selection && this.checked.size) {
			v.selection_mode = "Selected Documents";
			v.selected_documents = Array.from(this.checked);
		}
		return v;
	}

	clear_results() {
		this.rows = [];
		this.checked = new Set();
		this._total = 0;
		if (this.toolbar) this.toolbar.empty();
		if (this.results) {
			this.results.html(
				`<div class="text-muted p-4 text-center">${__(
					"Choose a document type and filters, then hit Fetch Documents."
				)}</div>`
			);
		}
		if (this.hint) this.hint.text("");
		if (this.generate_btn) this.generate_btn.text(__("Generate"));
	}

	fetch() {
		const args = this.collect(false);
		if (!args.document_type) {
			frappe.msgprint(__("Select a Document Type first."));
			return;
		}
		this.results.html(`<div class="text-muted p-4 text-center">${__("Loading…")}</div>`);
		frappe.call({
			method: "alphax_document_center.api.list_documents",
			args: { args: args, limit: FETCH_LIMIT },
			callback: (r) => {
				const msg = r.message || {};
				this.rows = msg.rows || [];
				this.fields = msg.fields || [];
				this.checked = new Set(this.rows.map((x) => x.name));
				this.render_results(msg.total);
			},
		});
	}

	render_results(total) {
		this.toolbar.empty();
		this._total = total || this.rows.length;
		if (!this.rows.length) {
			this.results.html(
				`<div class="text-muted p-4 text-center">${__("No documents match these filters.")}</div>`
			);
			this.hint.text("");
			return;
		}

		const search = $(
			`<input type="text" class="form-control form-control-sm d-inline-block mr-2" style="width:200px" placeholder="${__(
				"Search…"
			)}">`
		).appendTo(this.toolbar);
		$(`<button class="btn btn-xs btn-default mr-1">${__("All")}</button>`)
			.appendTo(this.toolbar)
			.on("click", () => this.set_all(true));
		$(`<button class="btn btn-xs btn-default">${__("None")}</button>`)
			.appendTo(this.toolbar)
			.on("click", () => this.set_all(false));

		const cols = this.fields.filter((f) => f !== "name");
		const head = cols.map((c) => `<th>${__(frappe.model.unscrub(c))}</th>`).join("");

		this.results.html(`
			<div class="mb-2 adc-summary text-muted small"></div>
			<div style="max-height:62vh; overflow:auto; border:1px solid var(--border-color); border-radius:var(--border-radius);">
				<table class="table table-sm mb-0" style="font-size: var(--text-sm);">
					<thead style="position:sticky; top:0; background:var(--card-bg); z-index:2;">
						<tr>
							<th style="width:34px;"><input type="checkbox" class="adc-all" checked></th>
							<th>${__("ID")}</th>
							${head}
						</tr>
					</thead>
					<tbody class="adc-tbody"></tbody>
				</table>
			</div>
		`);

		this.tbody = this.results.find(".adc-tbody");
		this.paint(cols, "");
		this.update_summary();

		this.results.find(".adc-all").on("change", (e) => this.set_all($(e.target).is(":checked")));

		let timer = null;
		search.on("input", () => {
			clearTimeout(timer);
			timer = setTimeout(() => this.paint(cols, search.val() || ""), 200);
		});
	}

	paint(cols, term) {
		const t = (term || "").toLowerCase();
		const visible = this.rows.filter((row) => {
			if (!t) return true;
			return Object.keys(row).some((k) =>
				String(row[k] == null ? "" : row[k]).toLowerCase().includes(t)
			);
		});

		const dt_slug = frappe.router.slug(this.base.document_type.get_value());
		this.tbody.html(
			visible
				.map((row) => {
					const cells = cols
						.map((c) => {
							let v = row[c];
							if (v == null) v = "";
							return `<td>${frappe.utils.escape_html(String(v))}</td>`;
						})
						.join("");
					const on = this.checked.has(row.name) ? "checked" : "";
					const safe = frappe.utils.escape_html(row.name);
					return `<tr>
						<td><input type="checkbox" class="adc-chk" data-name="${safe}" ${on}></td>
						<td><a href="/app/${dt_slug}/${encodeURIComponent(row.name)}" target="_blank">${safe}</a></td>
						${cells}
					</tr>`;
				})
				.join("")
		);

		this.tbody.find(".adc-chk").on("change", (e) => {
			const $el = $(e.target);
			const name = String($el.data("name"));
			if ($el.is(":checked")) this.checked.add(name);
			else this.checked.delete(name);
			this.update_summary();
		});
	}

	set_all(on) {
		this.tbody.find(".adc-chk").each((_i, el) => {
			const name = String($(el).data("name"));
			$(el).prop("checked", on);
			if (on) this.checked.add(name);
			else this.checked.delete(name);
		});
		this.update_summary();
	}

	update_summary() {
		const capped = this._total > this.rows.length;
		this.results.find(".adc-summary").html(
			`<b>${this.checked.size}</b> ${__("of")} <b>${this.rows.length}</b> ${__("selected")}` +
				(capped
					? ` <span class="text-danger">${__("(showing first {0} of {1} — narrow the filters)", [
							this.rows.length,
							this._total,
					  ])}</span>`
					: "")
		);
		if (this.checked.size) {
			this.generate_btn
				.removeClass("btn-default").addClass("btn-primary")
				.text(__("Print {0} selected", [this.checked.size]));
			this.hint.text(__("Only the ticked documents will be printed."));
		} else {
			this.generate_btn
				.removeClass("btn-primary").addClass("btn-default")
				.text(__("Print all {0} matching", [this._total || 0]));
			this.hint.text(__("Nothing ticked — everything matching the filters will be printed."));
		}
	}

	generate() {
		const args = this.collect(true);
		if (!args.document_type) {
			frappe.msgprint(__("Select a Document Type first."));
			return;
		}
		const manual = args.selected_documents && args.selected_documents.length;
		if (!manual) {
			const has_filter =
				args.from_date || args.to_date || args.from_document || args.to_document ||
				Object.keys(this.controls).some((k) => this.controls[k].get_value());
			if (!has_filter) {
				frappe.msgprint(__("Tick some documents, or set at least one filter."));
				return;
			}
		}

		const count = manual ? args.selected_documents.length : this._total || 0;

		const go = () =>
			frappe.call({
				method: "alphax_document_center.api.create_and_enqueue",
				args: { args: args },
				freeze: true,
				freeze_message: __("Creating job…"),
				callback: (r) => {
					if (window.alphax_document_center && alphax_document_center.follow_job) {
						alphax_document_center.follow_job(r.message, count);
					}
					frappe.show_alert({
						message: __("Generating {0} document(s)…", [count]), indicator: "blue",
					}, 7);
					this.load_jobs();
				},
			});

		if (count > 500) {
			frappe.confirm(__("This will generate {0} documents in the background. Continue?", [count]), go);
		} else {
			go();
		}
	}

	bind_realtime() {
		frappe.realtime.on("adc_job_progress", (data) => {
			const row = this.jobs_area.find(`[data-job="${data.job}"]`);
			if (row.length) {
				row.find(".progress-bar").css("width", `${data.progress}%`).text(`${data.progress}%`);
				row.find(".adc-status").text(data.status);
				if (["Completed", "Failed", "Partially Completed"].includes(data.status)) this.load_jobs();
			} else {
				this.load_jobs();
			}
		});
	}

	load_jobs() {
		frappe.call({
			method: "alphax_document_center.api.get_recent_jobs",
			args: { limit: 8 },
			callback: (r) => this.render_jobs(r.message || []),
		});
	}

	render_jobs(jobs) {
		this.jobs_area.empty();
		if (!jobs.length) {
			this.jobs_area.html(`<div class="text-muted small">${__("No jobs yet.")}</div>`);
			return;
		}
		const color = {
			Completed: "green", Failed: "red", "Partially Completed": "orange",
			Running: "blue", Queued: "blue", Pending: "gray",
		};
		jobs.forEach((j) => {
			const pct = j.progress || (j.status === "Completed" ? 100 : 0);
			const dl = j.generated_file
				? `<a class="btn btn-xs btn-default mt-2" href="${j.generated_file}" target="_blank">${__("Download")}</a>`
				: "";
			$(`
				<div class="mb-3 pb-2" data-job="${j.name}" style="border-bottom:1px solid var(--border-color);">
					<div class="d-flex justify-content-between align-items-start">
						<a href="/app/bulk-document-job/${j.name}" class="small"><b>${frappe.utils.escape_html(j.job_title || j.name)}</b></a>
						<span class="indicator-pill ${color[j.status] || "gray"} adc-status">${j.status}</span>
					</div>
					<div class="text-muted small">${j.document_type} · ${j.processed_documents || 0}/${j.total_documents || 0}</div>
					<div class="progress mt-1" style="height:12px;">
						<div class="progress-bar" style="width:${pct}%;">${pct}%</div>
					</div>
					${dl}
				</div>
			`).appendTo(this.jobs_area);
		});
	}
}
