/* =========================================================================
   Library Management System — frontend application logic (vanilla JS).

   Responsibilities:
     - Talk to the Flask JSON API (session-cookie auth via Flask-Login).
     - Manage authentication state and a small client-side router.
     - Render every screen: dashboard, books, members, borrowing, returns,
       fines and reports — with search, filtering, modal forms and toasts.

   The code is organised as small modules attached to a single `App` object so
   there are no globals leaking onto `window` beyond `App` itself.
   ========================================================================= */
(function () {
  "use strict";

  // When the frontend is served by Flask it shares the origin, so a relative
  // base works. Override here if you host the frontend separately.
  const API_BASE = (window.LMS_API_BASE || "") + "/api";

  /* ------------------------------- API ------------------------------- */
  const api = {
    async request(path, { method = "GET", body } = {}) {
      const opts = {
        method,
        headers: { "Content-Type": "application/json" },
        credentials: "include",
      };
      if (body !== undefined) opts.body = JSON.stringify(body);

      const res = await fetch(API_BASE + path, opts);
      let payload = null;
      try {
        payload = await res.json();
      } catch (_) {
        payload = null;
      }
      if (!res.ok) {
        const message = (payload && payload.error) || `Request failed (${res.status}).`;
        const err = new Error(message);
        err.status = res.status;
        err.details = (payload && payload.details) || {};
        throw err;
      }
      return payload;
    },
    async upload(path, file) {
      // Multipart upload: let the browser set the Content-Type/boundary.
      const data = new FormData();
      data.append("file", file);
      const res = await fetch(API_BASE + path, {
        method: "POST", body: data, credentials: "include",
      });
      let payload = null;
      try { payload = await res.json(); } catch (_) { payload = null; }
      if (!res.ok) {
        const err = new Error((payload && payload.error) || `Request failed (${res.status}).`);
        err.status = res.status;
        err.details = (payload && payload.details) || {};
        throw err;
      }
      return payload;
    },
    get(p) { return this.request(p); },
    post(p, body) { return this.request(p, { method: "POST", body }); },
    put(p, body) { return this.request(p, { method: "PUT", body }); },
    del(p) { return this.request(p, { method: "DELETE" }); },
  };

  /* ----------------------------- State ----------------------------- */
  const state = {
    user: null,
    view: "dashboard",
  };

  /* ---------------------------- Helpers ---------------------------- */
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "html") node.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") {
        node.addEventListener(k.slice(2).toLowerCase(), v);
      } else if (v !== null && v !== undefined) {
        node.setAttribute(k, v);
      }
    }
    for (const c of [].concat(children)) {
      if (c == null) continue;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return node;
  }

  const icon = (name) =>
    `<svg class="icon"><use href="#i-${name}"></use></svg>`;

  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  const money = (n) => "KES " + Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtDate = (s) => (s ? new Date(s).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—");

  function isStaff() {
    return state.user && (state.user.role === "admin" || state.user.role === "librarian");
  }

  // Debounce for search inputs.
  function debounce(fn, delay = 300) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), delay);
    };
  }

  /* ----------------------------- Toasts ----------------------------- */
  function toast(message, type = "info") {
    const iconName = type === "success" ? "check" : type === "error" ? "alert" : "info";
    const node = el("div", { class: `toast ${type}` }, [
      el("span", { class: "toast-icon", html: icon(iconName) }),
      el("span", { class: "toast-text" }, message),
    ]);
    $("#toast-root").appendChild(node);
    setTimeout(() => {
      node.classList.add("leaving");
      node.addEventListener("animationend", () => node.remove());
    }, 3200);
  }

  /* ----------------------------- Modal ----------------------------- */
  const modal = {
    open(title, bodyNode) {
      $("#modal-title").textContent = title;
      const body = $("#modal-body");
      body.innerHTML = "";
      body.appendChild(bodyNode);
      $("#modal-root").hidden = false;
    },
    close() {
      $("#modal-root").hidden = true;
      $("#modal-body").innerHTML = "";
    },
  };

  /* ------------------------- Badge helpers ------------------------- */
  function statusBadge(status) {
    const map = {
      borrowed: ["badge-blue", "loan", "Borrowed"],
      returned: ["badge-green", "check", "Returned"],
      overdue: ["badge-red", "alert", "Overdue"],
      active: ["badge-green", "check", "Active"],
      suspended: ["badge-amber", "alert", "Suspended"],
      available: ["badge-green", "check", "Available"],
      out_of_stock: ["badge-red", "x", "Out of stock"],
      unpaid: ["badge-red", "fine", "Unpaid"],
      paid: ["badge-green", "check", "Paid"],
      waived: ["badge-gray", "info", "Waived"],
    };
    const [cls, ic, label] = map[status] || ["badge-gray", "info", status];
    return `<span class="badge ${cls}">${icon(ic)}${escapeHtml(label)}</span>`;
  }

  /* ============================ VIEWS ============================ */
  const container = () => $("#view-container");

  function setLoading() {
    container().innerHTML = `<div class="skeleton">Loading…</div>`;
  }

  function viewHeader(title, subtitle, actions) {
    const header = el("div", { class: "view-header" });
    const left = el("div", {}, [
      el("h3", {}, title),
      subtitle ? el("p", {}, subtitle) : null,
    ]);
    header.appendChild(left);
    if (actions) header.appendChild(actions);
    return header;
  }

  function emptyState(text) {
    return `<div class="empty-state">${icon("info")}<p>${escapeHtml(text)}</p></div>`;
  }

  /* --------------------------- Dashboard --------------------------- */
  async function renderDashboard() {
    setLoading();
    const [{ data: stats }, { data: overdue }] = await Promise.all([
      api.get("/dashboard/stats"),
      api.get("/loans/overdue"),
    ]);

    const cards = [
      { label: "Total Books", value: stats.total_books, ic: "book", tone: "" },
      { label: "Books On Loan", value: stats.books_on_loan, ic: "loan", tone: "" },
      { label: "Members", value: stats.total_members, ic: "users", tone: "green" },
      { label: "Active Loans", value: stats.active_loans, ic: "layers", tone: "" },
      { label: "Overdue Loans", value: stats.overdue_loans, ic: "alert", tone: "red" },
      { label: "Available Copies", value: stats.available_copies, ic: "check", tone: "green" },
      { label: "Active Members", value: stats.active_members, ic: "user-check", tone: "green" },
      { label: "Outstanding Fines", value: money(stats.outstanding_fines), ic: "fine", tone: "amber" },
    ];

    const root = el("div");
    root.appendChild(viewHeader("Dashboard", `Welcome back, ${state.user.name}.`));

    const grid = el("div", { class: "stat-grid" });
    cards.forEach((c) => {
      grid.appendChild(el("div", { class: "stat-card" }, [
        el("div", { class: `stat-icon ${c.tone}`, html: icon(c.ic) }),
        el("div", { class: "stat-meta" }, [
          el("div", { class: "value" }, String(c.value)),
          el("div", { class: "label" }, c.label),
        ]),
      ]));
    });
    root.appendChild(grid);

    // Overdue panel.
    const panel = el("div", { class: "panel" });
    panel.appendChild(el("div", { class: "panel-header" }, [
      el("h4", {}, "Overdue Books"),
      el("span", { class: "badge badge-red", html: `${icon("alert")} ${overdue.length} overdue` }),
    ]));
    if (!overdue.length) {
      panel.appendChild(el("div", { class: "panel-body", html: emptyState("No overdue books. Everything is on time.") }));
    } else {
      const rows = overdue.map((l) => `
        <tr>
          <td><div class="cell-strong">${escapeHtml(l.book_title)}</div><div class="cell-sub">${escapeHtml(l.book_isbn)}</div></td>
          <td><div class="cell-strong">${escapeHtml(l.member_name)}</div><div class="cell-sub">${escapeHtml(l.membership_id)}</div></td>
          <td>${fmtDate(l.due_date)}</td>
          <td><span class="badge badge-red">${icon("clock")} ${l.days_overdue} day(s)</span></td>
        </tr>`).join("");
      panel.appendChild(el("div", { class: "panel-body table-wrap", html: `
        <table class="data"><thead><tr><th>Book</th><th>Member</th><th>Due</th><th>Overdue</th></tr></thead><tbody>${rows}</tbody></table>` }));
    }
    root.appendChild(panel);

    container().innerHTML = "";
    container().appendChild(root);
  }

  /* ----------------------------- Books ----------------------------- */
  const booksFilter = { q: "", category: "", availability: "" };

  async function renderBooks() {
    setLoading();
    const root = el("div");

    const actions = el("div", { class: "toolbar" });
    if (isStaff()) {
      actions.appendChild(el("button", { class: "btn btn-ghost", onClick: () => openImportBooks() }, [
        spanIcon("upload"), "Import Books",
      ]));
      actions.appendChild(el("button", { class: "btn btn-primary", onClick: () => openBookForm() }, [
        spanIcon("plus"), "Add Book",
      ]));
    }
    root.appendChild(viewHeader("Books", "Browse and manage the catalogue.", actions));

    // Filter toolbar.
    const filterBar = el("div", { class: "toolbar", style: "margin-bottom:16px" });
    const search = el("div", { class: "search-field", html: icon("search") });
    const searchInput = el("input", { type: "search", placeholder: "Search title, author, ISBN…", value: booksFilter.q });
    searchInput.addEventListener("input", debounce((e) => { booksFilter.q = e.target.value; loadBooks(); }));
    search.appendChild(searchInput);
    filterBar.appendChild(search);

    const catSelect = el("select");
    catSelect.appendChild(el("option", { value: "" }, "All categories"));
    catSelect.addEventListener("change", (e) => { booksFilter.category = e.target.value; loadBooks(); });
    filterBar.appendChild(catSelect);

    const availSelect = el("select");
    [["", "All availability"], ["available", "Available"], ["out_of_stock", "Out of stock"]].forEach(([v, t]) =>
      availSelect.appendChild(el("option", { value: v, ...(booksFilter.availability === v ? { selected: "selected" } : {}) }, t)));
    availSelect.addEventListener("change", (e) => { booksFilter.availability = e.target.value; loadBooks(); });
    filterBar.appendChild(availSelect);
    root.appendChild(filterBar);

    const panel = el("div", { class: "panel" });
    const body = el("div", { class: "panel-body table-wrap", id: "books-body", html: `<div class="skeleton">Loading…</div>` });
    panel.appendChild(body);
    root.appendChild(panel);

    container().innerHTML = "";
    container().appendChild(root);

    // Populate categories then load.
    try {
      const { data: cats } = await api.get("/books/categories");
      cats.forEach((c) => catSelect.appendChild(el("option", { value: c, ...(booksFilter.category === c ? { selected: "selected" } : {}) }, c)));
    } catch (_) { /* ignore */ }
    loadBooks();
  }

  async function loadBooks() {
    const body = $("#books-body");
    if (!body) return;
    const params = new URLSearchParams();
    if (booksFilter.q) params.set("q", booksFilter.q);
    if (booksFilter.category) params.set("category", booksFilter.category);
    if (booksFilter.availability) params.set("availability", booksFilter.availability);
    const { data: books } = await api.get("/books?" + params.toString());

    if (!books.length) { body.innerHTML = emptyState("No books match your search."); return; }

    const rows = books.map((b) => `
      <tr>
        <td><div class="cell-strong">${escapeHtml(b.title)}</div><div class="cell-sub">${escapeHtml(b.author)}</div></td>
        <td>${escapeHtml(b.isbn)}</td>
        <td>${b.category ? `<span class="badge badge-blue">${escapeHtml(b.category)}</span>` : "—"}</td>
        <td>${b.available_copies} / ${b.total_copies}</td>
        <td>${statusBadge(b.status)}</td>
        <td><div class="row-actions" data-id="${b.id}">
          <button class="icon-btn" data-act="view" title="Details">${icon("info")}</button>
          ${isStaff() ? `<button class="icon-btn" data-act="edit" title="Edit">${icon("edit")}</button>
          <button class="icon-btn" data-act="delete" title="Delete">${icon("trash")}</button>` : ""}
        </div></td>
      </tr>`).join("");

    body.innerHTML = `<table class="data"><thead><tr>
      <th>Title</th><th>ISBN</th><th>Category</th><th>Copies</th><th>Status</th><th></th>
    </tr></thead><tbody>${rows}</tbody></table>`;

    body.querySelectorAll(".row-actions").forEach((wrap) => {
      const id = Number(wrap.dataset.id);
      const book = books.find((x) => x.id === id);
      wrap.querySelector('[data-act="view"]').onclick = () => showBookDetail(book);
      const editBtn = wrap.querySelector('[data-act="edit"]');
      if (editBtn) editBtn.onclick = () => openBookForm(book);
      const delBtn = wrap.querySelector('[data-act="delete"]');
      if (delBtn) delBtn.onclick = () => deleteBook(book);
    });
  }

  function showBookDetail(b) {
    const node = el("div", { class: "detail-list", html: `
      <div class="detail-item"><span>Title</span><strong>${escapeHtml(b.title)}</strong></div>
      <div class="detail-item"><span>Author</span><strong>${escapeHtml(b.author)}</strong></div>
      <div class="detail-item"><span>ISBN</span><strong>${escapeHtml(b.isbn)}</strong></div>
      <div class="detail-item"><span>Category</span><strong>${escapeHtml(b.category || "—")}</strong></div>
      <div class="detail-item"><span>Publisher</span><strong>${escapeHtml(b.publisher || "—")}</strong></div>
      <div class="detail-item"><span>Year</span><strong>${escapeHtml(b.published_year || "—")}</strong></div>
      <div class="detail-item"><span>Shelf</span><strong>${escapeHtml(b.shelf_location || "—")}</strong></div>
      <div class="detail-item"><span>Copies</span><strong>${b.available_copies} / ${b.total_copies}</strong></div>
      <div class="detail-item full"><span>Description</span><strong>${escapeHtml(b.description || "—")}</strong></div>` });
    modal.open("Book details", node);
  }

  function openBookForm(book) {
    const editing = !!book;
    const b = book || {};
    const form = el("form", { class: "form-grid" });
    form.innerHTML = `
      <label class="field full">Title<input name="title" required value="${escapeHtml(b.title || "")}"></label>
      <label class="field">Author<input name="author" required value="${escapeHtml(b.author || "")}"></label>
      <label class="field">ISBN<input name="isbn" required value="${escapeHtml(b.isbn || "")}"></label>
      <label class="field">Category<input name="category" value="${escapeHtml(b.category || "")}"></label>
      <label class="field">Publisher<input name="publisher" value="${escapeHtml(b.publisher || "")}"></label>
      <label class="field">Published year<input name="published_year" type="number" value="${escapeHtml(b.published_year || "")}"></label>
      <label class="field">Shelf location<input name="shelf_location" value="${escapeHtml(b.shelf_location || "")}"></label>
      <label class="field full">Total copies<input name="total_copies" type="number" min="1" value="${escapeHtml(b.total_copies || 1)}"></label>
      <label class="field full">Description<textarea name="description">${escapeHtml(b.description || "")}</textarea></label>
      <p class="form-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="btn btn-ghost" data-cancel>Cancel</button>
        <button type="submit" class="btn btn-primary">${editing ? "Save changes" : "Create book"}</button>
      </div>`;
    bindForm(form, async (payload) => {
      payload.published_year = payload.published_year || null;
      payload.total_copies = Number(payload.total_copies || 1);
      if (editing) {
        await api.put(`/books/${b.id}`, payload);
        toast("Book updated.", "success");
      } else {
        await api.post("/books", payload);
        toast("Book added.", "success");
      }
      modal.close();
      loadBooks();
    });
    modal.open(editing ? "Edit book" : "Add book", form);
  }

  // Bulk import books from a CSV/XLSX file with a downloadable template.
  function openImportBooks() {
    const form = el("form", { class: "form" });
    form.innerHTML = `
      <p style="margin-bottom:10px;color:var(--ink-700)">
        Upload a <strong>.csv</strong> or <strong>.xlsx</strong> file with columns:
        <code>title, author, isbn, category, publisher, published_year, total_copies</code>.
        A row whose ISBN already exists adds its copies to that book.
      </p>
      <p style="margin-bottom:14px">
        <a href="${API_BASE}/books/import/template?format=csv">Download CSV template</a>
        &nbsp;·&nbsp;
        <a href="${API_BASE}/books/import/template?format=xlsx">Download Excel template</a>
      </p>
      <label>File
        <input name="file" type="file" accept=".csv,.xlsx" required />
      </label>
      <div class="form-error" hidden></div>
      <div class="import-result" hidden style="margin-top:8px"></div>
      <div class="modal-actions">
        <button type="button" class="btn btn-ghost" data-cancel>Cancel</button>
        <button type="submit" class="btn btn-primary">${icon("upload")} Import</button>
      </div>`;
    modal.open("Import books", form);

    const resultBox = form.querySelector(".import-result");
    const fileInput = form.querySelector('input[name="file"]');
    bindForm(form, async () => {
      const file = fileInput.files[0];
      if (!file) throw new Error("Choose a file to import.");
      const { data } = await api.upload("/books/import", file);
      const lines = [
        `<strong>${data.created}</strong> book(s) added`,
        `<strong>${data.copies_added}</strong> copies added to existing books`,
        `<strong>${data.skipped.length}</strong> row(s) skipped`,
      ];
      resultBox.hidden = false;
      resultBox.innerHTML = lines.join(" · ") + (data.skipped.length
        ? `<ul style="margin:8px 0 0;padding-left:18px;color:var(--ink-700)">` +
          data.skipped.map((s) => `<li>Row ${s.row}: ${escapeHtml(s.reason)}</li>`).join("") +
          `</ul>`
        : "");
      toast(`Import complete: ${data.created} added, ${data.copies_added} copies added.`, "success");
      loadBooks();
    });
  }

  async function deleteBook(book) {
    confirmDialog(`Delete "${book.title}"? This cannot be undone.`, async () => {
      await api.del(`/books/${book.id}`);
      toast("Book deleted.", "success");
      loadBooks();
    });
  }

  /* ---------------------------- Members ---------------------------- */
  const membersFilter = { q: "", status: "" };

  async function renderMembers() {
    setLoading();
    const root = el("div");
    const actions = el("div", { class: "toolbar" });
    if (isStaff()) {
      actions.appendChild(el("button", { class: "btn btn-primary", onClick: () => openMemberForm() }, [spanIcon("plus"), "Add Member"]));
    }
    root.appendChild(viewHeader("Members", "Manage library patrons.", actions));

    const filterBar = el("div", { class: "toolbar", style: "margin-bottom:16px" });
    const search = el("div", { class: "search-field", html: icon("search") });
    const searchInput = el("input", { type: "search", placeholder: "Search name, email, ID…", value: membersFilter.q });
    searchInput.addEventListener("input", debounce((e) => { membersFilter.q = e.target.value; loadMembers(); }));
    search.appendChild(searchInput);
    filterBar.appendChild(search);
    const statusSelect = el("select");
    [["", "All statuses"], ["active", "Active"], ["suspended", "Suspended"]].forEach(([v, t]) =>
      statusSelect.appendChild(el("option", { value: v }, t)));
    statusSelect.addEventListener("change", (e) => { membersFilter.status = e.target.value; loadMembers(); });
    filterBar.appendChild(statusSelect);
    root.appendChild(filterBar);

    const panel = el("div", { class: "panel" });
    panel.appendChild(el("div", { class: "panel-body table-wrap", id: "members-body", html: `<div class="skeleton">Loading…</div>` }));
    root.appendChild(panel);
    container().innerHTML = "";
    container().appendChild(root);
    loadMembers();
  }

  async function loadMembers() {
    const body = $("#members-body");
    if (!body) return;
    const params = new URLSearchParams();
    if (membersFilter.q) params.set("q", membersFilter.q);
    if (membersFilter.status) params.set("status", membersFilter.status);
    const { data: members } = await api.get("/members?" + params.toString());
    if (!members.length) { body.innerHTML = emptyState("No members found."); return; }

    const rows = members.map((m) => `
      <tr>
        <td><div class="cell-strong">${escapeHtml(m.name)}</div><div class="cell-sub">${escapeHtml(m.membership_id)}</div></td>
        <td><div>${escapeHtml(m.email)}</div><div class="cell-sub">${escapeHtml(m.phone || "")}</div></td>
        <td><span class="badge badge-blue">${escapeHtml(m.membership_type)}</span></td>
        <td>${m.active_loans}</td>
        <td>${m.outstanding_fines > 0 ? `<span class="badge badge-amber">${money(m.outstanding_fines)}</span>` : "—"}</td>
        <td>${statusBadge(m.status)}</td>
        <td><div class="row-actions" data-id="${m.id}">
          <button class="icon-btn" data-act="view" title="Details">${icon("info")}</button>
          ${isStaff() ? `<button class="icon-btn" data-act="edit" title="Edit">${icon("edit")}</button>
          <button class="icon-btn" data-act="delete" title="Delete">${icon("trash")}</button>` : ""}
        </div></td>
      </tr>`).join("");

    body.innerHTML = `<table class="data"><thead><tr>
      <th>Member</th><th>Contact</th><th>Type</th><th>Loans</th><th>Fines</th><th>Status</th><th></th>
    </tr></thead><tbody>${rows}</tbody></table>`;

    body.querySelectorAll(".row-actions").forEach((wrap) => {
      const id = Number(wrap.dataset.id);
      const member = members.find((x) => x.id === id);
      wrap.querySelector('[data-act="view"]').onclick = () => showMemberDetail(member);
      const editBtn = wrap.querySelector('[data-act="edit"]');
      if (editBtn) editBtn.onclick = () => openMemberForm(member);
      const delBtn = wrap.querySelector('[data-act="delete"]');
      if (delBtn) delBtn.onclick = () => deleteMember(member);
    });
  }

  function showMemberDetail(m) {
    const node = el("div", { class: "detail-list", html: `
      <div class="detail-item"><span>Name</span><strong>${escapeHtml(m.name)}</strong></div>
      <div class="detail-item"><span>Membership ID</span><strong>${escapeHtml(m.membership_id)}</strong></div>
      <div class="detail-item"><span>Email</span><strong>${escapeHtml(m.email)}</strong></div>
      <div class="detail-item"><span>Phone</span><strong>${escapeHtml(m.phone || "—")}</strong></div>
      <div class="detail-item"><span>Type</span><strong>${escapeHtml(m.membership_type)}</strong></div>
      <div class="detail-item"><span>Status</span><strong>${escapeHtml(m.status)}</strong></div>
      <div class="detail-item"><span>Active loans</span><strong>${m.active_loans}</strong></div>
      <div class="detail-item"><span>Outstanding fines</span><strong>${money(m.outstanding_fines)}</strong></div>
      <div class="detail-item"><span>Joined</span><strong>${fmtDate(m.join_date)}</strong></div>
      <div class="detail-item full"><span>Address</span><strong>${escapeHtml(m.address || "—")}</strong></div>` });
    modal.open("Member details", node);
  }

  function openMemberForm(member) {
    const editing = !!member;
    const m = member || {};
    const form = el("form", { class: "form-grid" });
    form.innerHTML = `
      <label class="field full">Full name<input name="name" required value="${escapeHtml(m.name || "")}"></label>
      <label class="field">Email<input name="email" type="email" required value="${escapeHtml(m.email || "")}"></label>
      <label class="field">Phone<input name="phone" value="${escapeHtml(m.phone || "")}"></label>
      <label class="field">Membership type<select name="membership_type">
        ${["standard", "student", "premium"].map((t) => `<option ${m.membership_type === t ? "selected" : ""}>${t}</option>`).join("")}
      </select></label>
      <label class="field">Status<select name="status">
        ${["active", "suspended"].map((t) => `<option ${m.status === t ? "selected" : ""}>${t}</option>`).join("")}
      </select></label>
      <label class="field full">Address<textarea name="address">${escapeHtml(m.address || "")}</textarea></label>
      <p class="form-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="btn btn-ghost" data-cancel>Cancel</button>
        <button type="submit" class="btn btn-primary">${editing ? "Save changes" : "Create member"}</button>
      </div>`;
    bindForm(form, async (payload) => {
      if (editing) {
        await api.put(`/members/${m.id}`, payload);
        toast("Member updated.", "success");
      } else {
        await api.post("/members", payload);
        toast("Member added.", "success");
      }
      modal.close();
      loadMembers();
    });
    modal.open(editing ? "Edit member" : "Add member", form);
  }

  async function deleteMember(member) {
    confirmDialog(`Delete member "${member.name}"?`, async () => {
      await api.del(`/members/${member.id}`);
      toast("Member deleted.", "success");
      loadMembers();
    });
  }

  /* ----------------------------- Loans ----------------------------- */
  const loansFilter = { status: "" };

  async function renderLoans() {
    setLoading();
    const root = el("div");
    const actions = el("div", { class: "toolbar" });
    if (isStaff()) {
      actions.appendChild(el("button", { class: "btn btn-primary", onClick: () => openIssueForm() }, [spanIcon("plus"), "Issue Book"]));
    }
    root.appendChild(viewHeader("Borrowing", "Issue books and track active loans.", actions));

    const filterBar = el("div", { class: "toolbar", style: "margin-bottom:16px" });
    const statusSelect = el("select");
    [["", "All loans"], ["borrowed", "Borrowed"], ["overdue", "Overdue"], ["returned", "Returned"]].forEach(([v, t]) =>
      statusSelect.appendChild(el("option", { value: v }, t)));
    statusSelect.addEventListener("change", (e) => { loansFilter.status = e.target.value; loadLoans(); });
    filterBar.appendChild(statusSelect);
    root.appendChild(filterBar);

    const panel = el("div", { class: "panel" });
    panel.appendChild(el("div", { class: "panel-body table-wrap", id: "loans-body", html: `<div class="skeleton">Loading…</div>` }));
    root.appendChild(panel);
    container().innerHTML = "";
    container().appendChild(root);
    loadLoans();
  }

  async function loadLoans() {
    const body = $("#loans-body");
    if (!body) return;
    const params = new URLSearchParams();
    if (loansFilter.status) params.set("status", loansFilter.status);
    const { data: loans } = await api.get("/loans?" + params.toString());
    if (!loans.length) { body.innerHTML = emptyState("No loans to show."); return; }

    const rows = loans.map((l) => `
      <tr>
        <td><div class="cell-strong">${escapeHtml(l.book_title)}</div><div class="cell-sub">${escapeHtml(l.book_isbn)}</div></td>
        <td><div class="cell-strong">${escapeHtml(l.member_name)}</div><div class="cell-sub">${escapeHtml(l.membership_id)}</div></td>
        <td>${fmtDate(l.loan_date)}</td>
        <td>${fmtDate(l.due_date)}</td>
        <td>${statusBadge(l.status)}</td>
        <td>${l.status !== "returned" && isStaff() ? `<button class="btn btn-sm btn-success" data-return="${l.id}">${icon("return")} Return</button>` : (l.return_date ? fmtDate(l.return_date) : "—")}</td>
      </tr>`).join("");
    body.innerHTML = `<table class="data"><thead><tr>
      <th>Book</th><th>Member</th><th>Issued</th><th>Due</th><th>Status</th><th></th>
    </tr></thead><tbody>${rows}</tbody></table>`;

    body.querySelectorAll("[data-return]").forEach((btn) => {
      btn.onclick = () => returnLoan(Number(btn.dataset.return));
    });
  }

  async function openIssueForm() {
    const [{ data: books }, { data: members }] = await Promise.all([
      api.get("/books?availability=available&per_page=200"),
      api.get("/members?status=active"),
    ]);
    const form = el("form", { class: "form-grid" });
    form.innerHTML = `
      <label class="field full">Book<select name="book_id" required>
        <option value="">Select an available book…</option>
        ${books.map((b) => `<option value="${b.id}">${escapeHtml(b.title)} — ${escapeHtml(b.author)} (${b.available_copies} left)</option>`).join("")}
      </select></label>
      <label class="field full">Member<select name="member_id" required>
        <option value="">Select a member…</option>
        ${members.map((m) => `<option value="${m.id}">${escapeHtml(m.name)} (${escapeHtml(m.membership_id)})</option>`).join("")}
      </select></label>
      <p class="form-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="btn btn-ghost" data-cancel>Cancel</button>
        <button type="submit" class="btn btn-primary">${icon("loan")} Issue book</button>
      </div>`;
    bindForm(form, async (payload) => {
      await api.post("/loans", { book_id: Number(payload.book_id), member_id: Number(payload.member_id) });
      toast("Book issued.", "success");
      modal.close();
      loadLoans();
    });
    modal.open("Issue a book", form);
  }

  async function returnLoan(id) {
    confirmDialog("Mark this book as returned? Overdue fines are applied automatically.", async () => {
      const { data: loan } = await api.post(`/loans/${id}/return`, {});
      if (loan.fine) toast(`Returned. Fine raised: ${money(loan.fine.amount)}.`, "info");
      else toast("Book returned.", "success");
      route(state.view); // refresh current view (loans or returns)
    });
  }

  /* ---------------------------- Returns ---------------------------- */
  async function renderReturns() {
    setLoading();
    const root = el("div");
    root.appendChild(viewHeader("Returns", "Books currently out on loan, ready to be returned."));

    const panel = el("div", { class: "panel" });
    panel.appendChild(el("div", { class: "panel-body table-wrap", id: "returns-body", html: `<div class="skeleton">Loading…</div>` }));
    root.appendChild(panel);
    container().innerHTML = "";
    container().appendChild(root);

    const { data: loans } = await api.get("/loans?status=borrowed");
    const { data: overdue } = await api.get("/loans?status=overdue");
    const active = loans.concat(overdue);
    const body = $("#returns-body");
    if (!active.length) { body.innerHTML = emptyState("No books are currently out on loan."); return; }

    const rows = active.map((l) => `
      <tr>
        <td><div class="cell-strong">${escapeHtml(l.book_title)}</div><div class="cell-sub">${escapeHtml(l.book_isbn)}</div></td>
        <td><div class="cell-strong">${escapeHtml(l.member_name)}</div><div class="cell-sub">${escapeHtml(l.membership_id)}</div></td>
        <td>${fmtDate(l.due_date)}</td>
        <td>${statusBadge(l.status)}</td>
        <td>${isStaff() ? `<button class="btn btn-sm btn-success" data-return="${l.id}">${icon("return")} Return</button>` : "—"}</td>
      </tr>`).join("");
    body.innerHTML = `<table class="data"><thead><tr>
      <th>Book</th><th>Member</th><th>Due</th><th>Status</th><th></th>
    </tr></thead><tbody>${rows}</tbody></table>`;
    body.querySelectorAll("[data-return]").forEach((btn) => {
      btn.onclick = () => returnLoan(Number(btn.dataset.return));
    });
  }

  /* ----------------------------- Fines ----------------------------- */
  const finesFilter = { status: "" };

  async function renderFines() {
    setLoading();
    const root = el("div");
    root.appendChild(viewHeader("Fines", "Track and settle overdue penalties."));

    const filterBar = el("div", { class: "toolbar", style: "margin-bottom:16px" });
    const statusSelect = el("select");
    [["", "All fines"], ["unpaid", "Unpaid"], ["paid", "Paid"], ["waived", "Waived"]].forEach(([v, t]) =>
      statusSelect.appendChild(el("option", { value: v }, t)));
    statusSelect.addEventListener("change", (e) => { finesFilter.status = e.target.value; loadFines(); });
    filterBar.appendChild(statusSelect);
    root.appendChild(filterBar);

    const panel = el("div", { class: "panel" });
    panel.appendChild(el("div", { class: "panel-body table-wrap", id: "fines-body", html: `<div class="skeleton">Loading…</div>` }));
    root.appendChild(panel);
    container().innerHTML = "";
    container().appendChild(root);
    loadFines();
  }

  async function loadFines() {
    const body = $("#fines-body");
    if (!body) return;
    const params = new URLSearchParams();
    if (finesFilter.status) params.set("status", finesFilter.status);
    const res = await api.get("/fines?" + params.toString());
    const fines = res.data;
    if (!fines.length) { body.innerHTML = emptyState("No fines recorded."); return; }

    const rows = fines.map((f) => `
      <tr>
        <td><div class="cell-strong">${escapeHtml(f.member_name)}</div></td>
        <td>${escapeHtml(f.reason || "—")}</td>
        <td class="cell-strong">${money(f.amount)}</td>
        <td>${statusBadge(f.status)}</td>
        <td>${fmtDate(f.created_at)}</td>
        <td>${f.status === "unpaid" && isStaff() ? `
          <div class="row-actions">
            <button class="btn btn-sm btn-success" data-mpesa="${f.id}" data-amount="${f.amount}" data-member="${escapeHtml(f.member_name)}">${icon("fine")} Pay with M-Pesa</button>
            <button class="btn btn-sm btn-ghost" data-pay="${f.id}">Mark paid</button>
            <button class="btn btn-sm btn-ghost" data-waive="${f.id}">Waive</button>
          </div>` : "—"}</td>
      </tr>`).join("");
    body.innerHTML = `<table class="data"><thead><tr>
      <th>Member</th><th>Reason</th><th>Amount</th><th>Status</th><th>Date</th><th></th>
    </tr></thead><tbody>${rows}</tbody></table>`;

    body.querySelectorAll("[data-mpesa]").forEach((btn) => {
      btn.onclick = () => payWithMpesa(btn.dataset.mpesa, btn.dataset.amount, btn.dataset.member);
    });
    body.querySelectorAll("[data-pay]").forEach((btn) => {
      btn.onclick = async () => { await api.post(`/fines/${btn.dataset.pay}/pay`, {}); toast("Fine marked as paid.", "success"); loadFines(); };
    });
    body.querySelectorAll("[data-waive]").forEach((btn) => {
      btn.onclick = () => confirmDialog("Waive this fine?", async () => { await api.post(`/fines/${btn.dataset.waive}/waive`, {}); toast("Fine waived.", "success"); loadFines(); });
    });
  }

  /* ------------------------- M-Pesa STK Push ------------------------- */
  // Initiate a Daraja STK Push for a fine, then poll until it settles.
  function payWithMpesa(fineId, amount, memberName) {
    const form = el("form", { class: "form" });
    form.innerHTML = `
      <p style="margin-bottom:14px;color:var(--ink-700)">
        Send an M-Pesa payment request of <strong>${money(amount)}</strong>
        to ${escapeHtml(memberName)}'s phone.
      </p>
      <label>Phone number
        <input name="phone" placeholder="07XX XXX XXX or 2547XXXXXXXX" required />
      </label>
      <div class="form-error" hidden></div>
      <div class="mpesa-status" hidden style="margin-top:6px;color:var(--ink-700)"></div>
      <div class="modal-actions">
        <button type="button" class="btn btn-ghost" data-cancel>Cancel</button>
        <button type="submit" class="btn btn-success">${icon("fine")} Send STK Push</button>
      </div>`;
    modal.open("Pay fine with M-Pesa", form);

    const statusBox = form.querySelector(".mpesa-status");
    bindForm(form, async (data) => {
      statusBox.hidden = false;
      statusBox.textContent = "Sending payment request…";
      const res = await api.post("/payments/stkpush", { fine_id: Number(fineId), phone: data.phone });
      const checkoutId = res.data.checkout_request_id;
      statusBox.textContent = res.customer_message
        || "Request sent. Ask the member to enter their M-Pesa PIN on their phone.";
      await pollMpesa(checkoutId, statusBox);
    });
  }

  // Poll the payment status endpoint until success/failure or timeout (~90s).
  async function pollMpesa(checkoutId, statusBox) {
    if (!checkoutId) return;
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      let p;
      try { p = (await api.get(`/payments/${encodeURIComponent(checkoutId)}`)).data; }
      catch (_) { continue; }
      if (p.status === "success") {
        statusBox.textContent = `Payment confirmed${p.mpesa_receipt ? ` (${p.mpesa_receipt})` : ""}.`;
        toast("Payment received. Fine settled.", "success");
        modal.close();
        loadFines();
        return;
      }
      if (p.status === "failed") {
        statusBox.textContent = p.result_desc || "Payment failed or was cancelled.";
        toast("Payment was not completed.", "error");
        return;
      }
      statusBox.textContent = "Waiting for the member to confirm on their phone…";
    }
    statusBox.textContent = "Still pending. It will update automatically once confirmed.";
  }

  /* ---------------------------- Reports ---------------------------- */
  async function renderReports() {
    setLoading();
    const { data: r } = await api.get("/dashboard/reports");
    const root = el("div");
    root.appendChild(viewHeader("Reports & Analytics", "Insights across the library."));

    const grid = el("div", { class: "grid-2" });

    // Popular books — horizontal bars.
    const maxLoans = Math.max(1, ...r.popular_books.map((p) => p.loans));
    const popularPanel = el("div", { class: "panel" });
    popularPanel.appendChild(el("div", { class: "panel-header", html: `<h4>Most Borrowed Books</h4>` }));
    popularPanel.appendChild(el("div", { class: "chart", html: r.popular_books.length
      ? r.popular_books.map((p) => `
        <div class="bar-row">
          <div class="bar-label" title="${escapeHtml(p.title)}">${escapeHtml(p.title)}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${(p.loans / maxLoans) * 100}%"></div></div>
          <div class="bar-value">${p.loans}</div>
        </div>`).join("")
      : emptyState("No loans yet.") }));
    grid.appendChild(popularPanel);

    // Books by category.
    const maxCat = Math.max(1, ...r.books_by_category.map((c) => c.count));
    const catPanel = el("div", { class: "panel" });
    catPanel.appendChild(el("div", { class: "panel-header", html: `<h4>Books by Category</h4>` }));
    catPanel.appendChild(el("div", { class: "chart", html: r.books_by_category.length
      ? r.books_by_category.map((c) => `
        <div class="bar-row">
          <div class="bar-label" title="${escapeHtml(c.category)}">${escapeHtml(c.category)}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${(c.count / maxCat) * 100}%"></div></div>
          <div class="bar-value">${c.count}</div>
        </div>`).join("")
      : emptyState("No data.") }));
    grid.appendChild(catPanel);
    root.appendChild(grid);

    // Loans over time — vertical spark bars.
    const maxDay = Math.max(1, ...r.loans_over_time.map((d) => d.loans));
    const timePanel = el("div", { class: "panel", style: "margin-top:18px" });
    timePanel.appendChild(el("div", { class: "panel-header", html: `<h4>Loans — Last 14 Days</h4>` }));
    timePanel.appendChild(el("div", { class: "spark", html: r.loans_over_time.map((d) => `
      <div class="spark-col" title="${fmtDate(d.date)}: ${d.loans} loan(s)">
        <div class="spark-bar" style="height:${(d.loans / maxDay) * 100}%"></div>
        <div class="spark-x">${new Date(d.date).getDate()}</div>
      </div>`).join("") }));
    root.appendChild(timePanel);

    // Fines summary.
    const finePanel = el("div", { class: "panel", style: "margin-top:18px" });
    finePanel.appendChild(el("div", { class: "panel-header", html: `<h4>Fines by Status</h4>` }));
    finePanel.appendChild(el("div", { class: "stat-grid", style: "padding:18px;margin:0" , html: r.fines_by_status.length
      ? r.fines_by_status.map((f) => `
        <div class="stat-card">
          <div class="stat-icon ${f.status === "paid" ? "green" : f.status === "unpaid" ? "red" : ""}">${icon("fine")}</div>
          <div class="stat-meta"><div class="value">${money(f.amount)}</div><div class="label" style="text-transform:capitalize">${escapeHtml(f.status)}</div></div>
        </div>`).join("")
      : emptyState("No fines recorded.") }));
    root.appendChild(finePanel);

    container().innerHTML = "";
    container().appendChild(root);
  }

  /* ------------------------ Shared form utils ------------------------ */
  function spanIcon(name) {
    const s = el("span", { html: icon(name) });
    return s.firstChild;
  }

  function bindForm(form, onSubmit) {
    const cancel = form.querySelector("[data-cancel]");
    if (cancel) cancel.onclick = () => modal.close();
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const errBox = form.querySelector(".form-error");
      if (errBox) errBox.hidden = true;
      const submitBtn = form.querySelector('button[type="submit"]');
      const data = Object.fromEntries(new FormData(form).entries());
      if (submitBtn) { submitBtn.disabled = true; }
      try {
        await onSubmit(data);
      } catch (err) {
        if (errBox) { errBox.textContent = err.message; errBox.hidden = false; }
        else toast(err.message, "error");
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  function confirmDialog(message, onConfirm) {
    const node = el("div", {}, [
      el("p", { style: "margin-bottom:20px;color:var(--ink-700)" }, message),
      el("div", { class: "modal-actions" }, [
        el("button", { class: "btn btn-ghost", onClick: () => modal.close() }, "Cancel"),
        el("button", { class: "btn btn-danger", onClick: async () => {
          try { await onConfirm(); modal.close(); }
          catch (err) { toast(err.message, "error"); }
        } }, "Confirm"),
      ]),
    ]);
    modal.open("Please confirm", node);
  }

  /* ----------------------------- Router ----------------------------- */
  const routes = {
    dashboard: { title: "Dashboard", render: renderDashboard },
    books: { title: "Books", render: renderBooks },
    members: { title: "Members", render: renderMembers },
    loans: { title: "Borrowing", render: renderLoans },
    returns: { title: "Returns", render: renderReturns },
    fines: { title: "Fines", render: renderFines },
    reports: { title: "Reports & Analytics", render: renderReports },
  };

  async function route(view) {
    const def = routes[view] || routes.dashboard;
    state.view = routes[view] ? view : "dashboard";
    $("#page-title").textContent = def.title;
    $$(".nav-link[data-view]").forEach((a) => a.classList.toggle("active", a.dataset.view === state.view));
    closeMobileSidebar();
    try {
      await def.render();
    } catch (err) {
      if (err.status === 401) return showAuth();
      container().innerHTML = emptyState(err.message || "Something went wrong.");
      toast(err.message || "Failed to load.", "error");
    }
  }

  /* --------------------------- Auth flow --------------------------- */
  function showAuth() {
    $("#auth-screen").hidden = false;
    $("#app").hidden = true;
  }

  function showApp() {
    $("#auth-screen").hidden = true;
    $("#app").hidden = false;
    const u = state.user;
    $("#user-name").textContent = u.name;
    $("#user-role").textContent = u.role;
    $("#user-avatar").textContent = (u.name || "?").charAt(0);
  }

  async function bootstrap() {
    try {
      const { data: user } = await api.get("/auth/me");
      if (user) {
        state.user = user;
        showApp();
        route("dashboard");
        return;
      }
    } catch (_) { /* fall through to login */ }
    showAuth();
  }

  /* --------------------------- Event wiring --------------------------- */
  function wireEvents() {
    // Login.
    $("#login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const errBox = $("#login-error");
      errBox.hidden = true;
      const data = Object.fromEntries(new FormData(e.target).entries());
      try {
        const { data: user } = await api.post("/auth/login", {
          email: data.email, password: data.password, remember: !!data.remember,
        });
        state.user = user;
        showApp();
        route("dashboard");
        toast(`Welcome, ${user.name}.`, "success");
      } catch (err) {
        errBox.textContent = err.message;
        errBox.hidden = false;
      }
    });

    // Logout.
    $("#logout-btn").addEventListener("click", async () => {
      try { await api.post("/auth/logout", {}); } catch (_) {}
      state.user = null;
      showAuth();
    });

    // Sidebar navigation.
    $$(".nav-link[data-view]").forEach((link) => {
      link.addEventListener("click", (e) => { e.preventDefault(); route(link.dataset.view); });
    });

    // Sidebar collapse / mobile toggle.
    $("#sidebar-toggle").addEventListener("click", () => {
      const shell = $("#app");
      if (window.innerWidth <= 900) shell.classList.toggle("mobile-open");
      else shell.classList.toggle("collapsed");
    });

    // Global search jumps to books with the query.
    $("#global-search").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        booksFilter.q = e.target.value;
        route("books");
      }
    });

    // Modal close handlers.
    $("#modal-root").addEventListener("click", (e) => {
      if (e.target.hasAttribute("data-close-modal")) modal.close();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !$("#modal-root").hidden) modal.close();
    });
  }

  function closeMobileSidebar() {
    $("#app").classList.remove("mobile-open");
  }

  // Mobile scrim element (added once).
  function addScrim() {
    const scrim = el("div", { class: "scrim", onClick: closeMobileSidebar });
    $("#app").appendChild(scrim);
  }

  document.addEventListener("DOMContentLoaded", () => {
    wireEvents();
    addScrim();
    bootstrap();
  });
})();
