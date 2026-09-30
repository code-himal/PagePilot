/* DocPixly frontend. Vanilla JS, no build step. */
(() => {
  "use strict";

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));

  const tray = $("#tray"), trayInner = $("#trayInner"), fileInput = $("#fileInput"),
        browseBtn = $("#browseBtn"), langSelect = $("#langSelect"), pagesInput = $("#pagesInput"),
        workspace = $("#workspace"), stepsEl = $("#steps"), toasts = $("#toasts");

  /** @type {Map<string, {id:string, file:File, status:string, result?:any, error?:string,
   *                        activePage:number, el:HTMLElement}>} */
  const docs = new Map();
  let docSeq = 0;

  // ------------------------------------------------------------------ toasts
  function toast(message, kind = "info") {
    const t = document.createElement("div");
    t.className = "toast" + (kind === "error" ? " toast--error" : "");
    t.textContent = message;
    toasts.appendChild(t);
    setTimeout(() => t.remove(), 5200);
  }

  // ------------------------------------------------------------------ steps rail
  function setStep(name) {
    const order = ["upload", "read", "review", "download"];
    const idx = order.indexOf(name);
    $$(".steps__item", stepsEl).forEach((li, i) => {
      li.classList.toggle("is-active", i === idx);
      li.classList.toggle("is-done", i < idx);
    });
  }

  // ------------------------------------------------------------------ config
  async function loadConfig() {
    try {
      const r = await fetch("/api/config");
      const cfg = await r.json();
      langSelect.innerHTML = cfg.languages
        .map((l) => `<option value="${esc(l.code)}">${esc(l.label)}</option>`).join("");
      if (!cfg.ocr) {
        toast("OCR is not available on this server — scanned files can't be read right now.", "error");
      }
    } catch (e) {
      // Keep the default English-only option; not fatal.
    }
  }
  loadConfig();

  // ------------------------------------------------------------------ file intake
  browseBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    addFiles(fileInput.files);
    fileInput.value = "";
  });
  ["dragenter", "dragover"].forEach((ev) =>
    tray.addEventListener(ev, (e) => { e.preventDefault(); tray.classList.add("is-dragover"); }));
  ["dragleave", "drop"].forEach((ev) =>
    tray.addEventListener(ev, (e) => { e.preventDefault(); tray.classList.remove("is-dragover"); }));
  tray.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

  function addFiles(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    workspace.hidden = false;
    setStep("read");
    for (const file of files) startDoc(file);
  }

  // ------------------------------------------------------------------ per-document flow
  function startDoc(file) {
    const id = "d" + (++docSeq);
    const el = document.createElement("div");
    el.className = "doc";
    el.innerHTML = docShellHTML(file.name);
    workspace.appendChild(el);
    const entry = { id, file, status: "loading", activePage: 0, el };
    docs.set(id, entry);
    $(".doc__remove", el).addEventListener("click", () => removeDoc(id));
    extract(entry);
  }

  function docShellHTML(name) {
    return `
      <div class="doc__head">
        <div class="doc__title">
          <span class="doc__name" title="${esc(name)}">${esc(name)}</span>
          <span class="doc__meta doc-meta"></span>
        </div>
        <div class="doc__actions">
          <button type="button" class="btn btn--sm btn--danger-ghost doc__remove">Remove</button>
        </div>
      </div>
      <div class="doc__status"><span class="spinner"></span> Reading this file&hellip;</div>`;
  }

  function removeDoc(id) {
    const entry = docs.get(id);
    if (!entry) return;
    entry.el.remove();
    docs.delete(id);
    if (docs.size === 0) {
      workspace.hidden = true;
      setStep("upload");
    }
    updateBatchBar();
  }

  async function extract(entry) {
    const fd = new FormData();
    fd.append("file", entry.file, entry.file.name);
    fd.append("lang", langSelect.value || "eng");
    fd.append("pages", pagesInput.value.trim());
    try {
      const res = await fetch("/api/extract", { method: "POST", body: fd });
      const body = await res.json();
      if (!res.ok) throw new ApiError(body);
      entry.status = "done";
      entry.result = body;
      renderDoc(entry);
      afterAnyDocSettled();
    } catch (err) {
      entry.status = "error";
      entry.error = err instanceof ApiError ? err.message : "This file could not be read. Please try again.";
      renderDocError(entry);
      afterAnyDocSettled();
    }
  }

  class ApiError extends Error {
    constructor(body) {
      const msg = body && body.error && body.error.message ? body.error.message : "Something went wrong.";
      super(msg);
      this.message = msg;
    }
  }

  function afterAnyDocSettled() {
    const all = Array.from(docs.values());
    if (all.length && all.every((d) => d.status !== "loading")) {
      const anyDone = all.some((d) => d.status === "done");
      setStep(anyDone ? "review" : "read");
    }
    updateBatchBar();
  }

  function renderDocError(entry) {
    entry.el.innerHTML = docShellHTML(entry.file.name).replace(
      /<div class="doc__status">[\s\S]*?<\/div>/,
      `<div class="doc__error"><strong>Could not read this file</strong>${esc(entry.error)}</div>`
    );
    $(".doc__remove", entry.el).addEventListener("click", () => removeDoc(entry.id));
  }

  // ------------------------------------------------------------------ rendering a successful result
  function renderDoc(entry) {
    const r = entry.result;
    const pages = r.pages;
    entry.el.querySelector(".doc-meta").textContent =
      `${r.stats.pages} page${r.stats.pages === 1 ? "" : "s"} · ${r.stats.tables} table${r.stats.tables === 1 ? "" : "s"} · ${r.stats.seconds}s`;

    const warnHTML = (r.warnings || []).map((w) => `<div class="warn-strip">${esc(w)}</div>`).join("");

    const railHTML = pages.map((p, i) => `
        <button type="button" class="pagerail__item${i === 0 ? " is-active" : ""}" data-page="${i}">
          ${p.preview ? `<img class="pagerail__thumb" src="${p.preview}" alt="Page ${p.number}">`
                      : `<span class="pagerail__thumb pagerail__thumb--empty">p.${p.number}</span>`}
          <span class="pagerail__label">Page ${p.number}</span>
        </button>`).join("");

    entry.el.innerHTML = `
      <div class="doc__head">
        <div class="doc__title">
          <span class="doc__name" title="${esc(entry.file.name)}">${esc(entry.file.name)}</span>
          <span class="doc__meta">${esc(r.stats.pages)} page${r.stats.pages === 1 ? "" : "s"} · ${esc(r.stats.tables)} table${r.stats.tables === 1 ? "" : "s"} · ${esc(r.stats.seconds)}s</span>
        </div>
        <div class="doc__actions">
          <button type="button" class="btn btn--sm btn--danger-ghost doc__remove">Remove</button>
        </div>
      </div>
      ${warnHTML}
      <div class="doc__body">
        <nav class="pagerail" aria-label="Pages">${railHTML}</nav>
        <div class="content"></div>
      </div>
      <div class="downloads">
        <span class="downloads__label">Download:</span>
        <button type="button" class="btn btn--sm btn--primary" data-fmt="docx">Word (.docx)</button>
        <button type="button" class="btn btn--sm btn--ghost" data-fmt="xlsx">Excel (.xlsx)</button>
        <button type="button" class="btn btn--sm btn--ghost" data-fmt="csv">CSV</button>
        <button type="button" class="btn btn--sm btn--ghost" data-fmt="txt">Text (.txt)</button>
      </div>`;

    $(".doc__remove", entry.el).addEventListener("click", () => removeDoc(entry.id));
    $$(".pagerail__item", entry.el).forEach((btn) =>
      btn.addEventListener("click", () => {
        entry.activePage = Number(btn.dataset.page);
        $$(".pagerail__item", entry.el).forEach((b) => b.classList.toggle("is-active", b === btn));
        renderPage(entry);
      }));
    $$(".downloads [data-fmt]", entry.el).forEach((btn) =>
      btn.addEventListener("click", () => downloadOne(entry, btn.dataset.fmt)));

    renderPage(entry);
  }

  function renderPage(entry) {
    const r = entry.result;
    const page = r.pages[entry.activePage];
    const content = $(".content", entry.el);

    const methodLabel = page.method === "text" ? "digital text" : "OCR";
    const confBadge = page.confidence != null
      ? `<span class="badge${page.confidence >= 80 ? " badge--ok" : page.confidence < 60 ? " badge--flag" : ""}">${page.confidence}% confidence</span>`
      : "";
    const pageWarn = (page.warnings || []).map((w) => `<span class="badge badge--flag">${esc(w)}</span>`).join("");

    let fieldsHTML = "";
    const pageFields = (r.fields || []).filter((f) => f.page === page.number);
    if (pageFields.length) {
      fieldsHTML = `<dl class="fields">${pageFields.map((f) => `
          <div class="field"><dt>${esc(f.key)}</dt><dd>${esc(f.value)}</dd></div>`).join("")}</dl>`;
    }

    let tn = 0;
    const blocksHTML = page.blocks.length
      ? page.blocks.map((b) => blockHTML(b, () => ++tn)).join("")
      : `<p class="content__empty">No text was found on this page.</p>`;

    content.innerHTML = `
      <div class="content__pagehead">
        <h3>Page ${page.number} <span class="content__method">— ${methodLabel}</span></h3>
        ${confBadge}${pageWarn}
      </div>
      ${fieldsHTML}
      ${blocksHTML}`;

    wireEditable(content, entry);
  }

  function blockHTML(b, nextTableNum) {
    if (b.type === "heading") {
      const tag = `h${Math.min(Math.max(b.level, 1), 3)}`;
      return `<${tag} class="block blk-text" data-path="text">${esc(b.text)}</${tag}>`;
    }
    if (b.type === "list_item") {
      return `<ul class="block block--list"><li class="blk-text" contenteditable="true" data-path="text">${esc(b.text)}</li></ul>`;
    }
    if (b.type === "table") {
      const n = nextTableNum();
      const rows = b.rows, low = b.low || [];
      const rowsHTML = rows.map((row, ri) => `
          <tr${b.header && ri === 0 ? ' class="hdr"' : ""}>
            ${row.map((c, ci) => `<td contenteditable="true" data-r="${ri}" data-c="${ci}"
                class="${low[ri] && low[ri][ci] ? "is-low" : ""}">${esc(c)}</td>`).join("")}
          </tr>`).join("");
      return `
        <div class="tblwrap" data-table-id="${esc(b.id)}">
          <div class="tblwrap__head">
            <span>Table ${n} · ${rows.length} rows × ${(rows[0] || []).length} cols</span>
            <button type="button" class="btn btn--sm btn--ghost tbl-csv" data-table-id="${esc(b.id)}">Download this table as CSV</button>
          </div>
          <table class="dtable">${rowsHTML}</table>
        </div>`;
    }
    // paragraph
    return `<p class="block blk-text" contenteditable="true" data-path="text">${esc(b.text)}</p>`;
  }

  function wireEditable(content, entry) {
    // paragraph / heading / list text
    $$(".blk-text[data-path='text']", content).forEach((el, i) => {
      if (!el.hasAttribute("contenteditable")) el.setAttribute("contenteditable", "true");
      el.addEventListener("blur", () => {
        const page = entry.result.pages[entry.activePage];
        const idx = findBlockIndex(page, el);
        if (idx >= 0) page.blocks[idx].text = el.innerText.replace(/\n+$/, "");
      });
    });
    // table cells
    $$("table.dtable td", content).forEach((td) => {
      td.addEventListener("blur", () => {
        const wrap = td.closest(".tblwrap");
        const tableId = wrap.dataset.tableId;
        const page = entry.result.pages[entry.activePage];
        const block = page.blocks.find((b) => b.type === "table" && b.id === tableId);
        if (!block) return;
        const r = Number(td.dataset.r), c = Number(td.dataset.c);
        block.rows[r][c] = td.innerText.replace(/\n+$/, "");
        if (block.low && block.low[r]) block.low[r][c] = false;   // edited cells are no longer "uncertain"
        td.classList.remove("is-low");
      });
    });
    $$(".tbl-csv", content).forEach((btn) =>
      btn.addEventListener("click", () => downloadOne(entry, "csv", btn.dataset.tableId)));
  }

  function findBlockIndex(page, el) {
    // Blocks render in order; find by matching element identity via a live query.
    const all = $$(".blk-text[data-path='text']", el.closest(".content"));
    return all.indexOf(el);
  }

  // ------------------------------------------------------------------ export
  function docForExport(entry) {
    const r = entry.result;
    return {
      filename: entry.file.name,
      pages: r.pages.map((p) => ({ number: p.number, blocks: p.blocks })),
      fields: r.fields || [],
    };
  }

  async function requestExport(body, fallbackName) {
    const res = await fetch("/api/export", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new ApiError(errBody);
    }
    const blob = await res.blob();
    const disp = res.headers.get("Content-Disposition") || "";
    const m = /filename="?([^"]+)"?/.exec(disp);
    triggerDownload(blob, m ? m[1] : fallbackName);
  }

  function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  async function downloadOne(entry, fmt, tableId) {
    setStep("download");
    try {
      const body = { format: fmt, documents: [docForExport(entry)] };
      if (tableId) body.table = tableId;
      await requestExport(body, `${entry.file.name}.${fmt}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not create that file. Please try again.", "error");
    }
  }

  async function downloadBatch(fmt) {
    const ready = Array.from(docs.values()).filter((d) => d.status === "done");
    if (!ready.length) return;
    setStep("download");
    try {
      await requestExport(
        { format: fmt, documents: ready.map(docForExport) },
        `docpixly-${fmt}.zip`
      );
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not create that file. Please try again.", "error");
    }
  }

  // ------------------------------------------------------------------ batch bar (2+ documents)
  let batchBar = null;
  function updateBatchBar() {
    const ready = Array.from(docs.values()).filter((d) => d.status === "done");
    if (ready.length < 2) {
      if (batchBar) { batchBar.remove(); batchBar = null; }
      return;
    }
    if (!batchBar) {
      batchBar = document.createElement("div");
      batchBar.className = "doc doc--batchbar";
      workspace.insertBefore(batchBar, workspace.firstChild);
    }
    batchBar.innerHTML = `
      <div class="downloads downloads--flat">
        <span class="downloads__label">${ready.length} files ready — download all as:</span>
        <button type="button" class="btn btn--sm btn--primary" data-fmt="docx">Word</button>
        <button type="button" class="btn btn--sm btn--ghost" data-fmt="xlsx">Excel</button>
        <button type="button" class="btn btn--sm btn--ghost" data-fmt="csv">CSV</button>
        <button type="button" class="btn btn--sm btn--ghost" data-fmt="txt">Text</button>
      </div>`;
    $$("[data-fmt]", batchBar).forEach((btn) => btn.addEventListener("click", () => downloadBatch(btn.dataset.fmt)));
  }
})();
