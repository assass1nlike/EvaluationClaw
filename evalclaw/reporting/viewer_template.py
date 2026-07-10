"""Self-contained HTML/JavaScript template for report viewer pages."""

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #667085;
      --line: #d7dce2;
      --soft: #eef1f5;
      --accent: #155eef;
      --good: #147a4f;
      --warn: #a75c00;
      --bad: #b42318;
      --shadow: 0 10px 24px rgba(16, 24, 40, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 20;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(8px);
    }
    .topbar {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 16px;
      align-items: center;
      max-width: 1480px;
      margin: 0 auto;
      padding: 14px 24px;
    }
    h1, h2, h3, p { margin: 0; }
    h1 { font-size: 20px; line-height: 1.2; font-weight: 700; }
    h2 { font-size: 16px; margin-bottom: 12px; }
    h3 { font-size: 14px; margin-bottom: 8px; }
    .objective { color: var(--muted); margin-top: 5px; max-width: 980px; }
    .app {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      gap: 18px;
      max-width: 1480px;
      margin: 0 auto;
      padding: 18px 24px 32px;
    }
    aside {
      position: sticky;
      top: 88px;
      align-self: start;
      display: grid;
      gap: 10px;
    }
    nav, section, .card, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    nav { padding: 10px; }
    nav a {
      display: block;
      color: var(--ink);
      text-decoration: none;
      padding: 8px 10px;
      border-radius: 6px;
    }
    nav a:hover { background: var(--soft); }
    main { display: grid; gap: 18px; min-width: 0; }
    section { padding: 16px; }
    .part-heading {
      background: #17202a;
      color: #fff;
      border-color: #17202a;
    }
    .part-heading h2 { margin-bottom: 6px; }
    .part-heading p { color: #d7dce2; max-width: 920px; }
    .nav-label {
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 8px 10px 4px;
    }
    .grid { display: grid; gap: 12px; }
    .grid.cols-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .grid.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .stat {
      background: var(--soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 72px;
    }
    .stat .label { color: var(--muted); font-size: 12px; }
    .stat .value { margin-top: 6px; font-size: 20px; font-weight: 700; overflow-wrap: anywhere; }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 999px;
      padding: 4px 9px;
      color: var(--muted);
      font-size: 12px;
    }
    .tone-good { color: var(--good); }
    .tone-warn { color: var(--warn); }
    .tone-bad { color: var(--bad); }
    .table-separator td {
      border-top: 2px solid #17202a;
      padding: 5px 0;
      height: 1px;
      background: #fff;
    }
    table { width: 100%; border-collapse: collapse; }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 8px 7px;
      text-align: left;
      vertical-align: top;
    }
    th { color: var(--muted); font-size: 12px; font-weight: 650; }
    td { overflow-wrap: anywhere; }
    .filters {
      display: grid;
      grid-template-columns: minmax(220px, 2fr) repeat(4, minmax(120px, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }
    input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 8px 9px;
      font: inherit;
    }
    details.item {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      margin-top: 10px;
      overflow: hidden;
    }
    details.item[open] { box-shadow: 0 6px 16px rgba(16, 24, 40, 0.06); }
    details.item summary {
      cursor: pointer;
      list-style: none;
      padding: 12px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      border-bottom: 1px solid transparent;
    }
    details.item[open] summary { border-bottom-color: var(--line); }
    summary::-webkit-details-marker { display: none; }
    .item-body { padding: 12px; display: grid; gap: 12px; }
    .task-section {
      display: grid;
      gap: 8px;
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }
    .task-section:first-child {
      border-top: 0;
      padding-top: 0;
    }
    .two-col { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
    .file-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    details.file-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
      overflow: hidden;
    }
    details.file-card summary {
      cursor: pointer;
      padding: 9px 10px;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }
    .file-card pre {
      border-radius: 0;
      max-height: 320px;
    }
    .status-pill {
      display: inline-flex;
      border-radius: 999px;
      border: 1px solid var(--line);
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 650;
      background: #fff;
    }
    .status-run { color: var(--good); }
    .status-rejected { color: var(--bad); }
    .status-accepted { color: var(--warn); }
    pre {
      margin: 0;
      max-height: 420px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      background: #111827;
      color: #f9fafb;
      border-radius: 8px;
      padding: 12px;
      font-size: 12px;
      line-height: 1.45;
    }
    .empty { color: var(--muted); padding: 10px 0; }
    .small { color: var(--muted); font-size: 12px; }
    .markdown {
      display: grid;
      gap: 6px;
      max-width: 760px;
    }
    .markdown p,
    .markdown ul,
    .markdown ol,
    .markdown pre { margin: 0; }
    .markdown ul,
    .markdown ol { padding-left: 20px; }
    .markdown h1,
    .markdown h2,
    .markdown h3 {
      margin: 4px 0 2px;
      font-size: 13px;
      line-height: 1.25;
    }
    .markdown code {
      border-radius: 4px;
      background: #eef1f5;
      padding: 1px 4px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }
    .markdown pre {
      max-height: 260px;
      background: #111827;
      color: #f9fafb;
    }
    .qc-more {
      margin-top: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
    }
    .qc-more summary {
      cursor: pointer;
      padding: 7px 9px;
      color: var(--accent);
      font-weight: 650;
    }
    .qc-history {
      display: grid;
      gap: 10px;
      padding: 9px;
      border-top: 1px solid var(--line);
    }
    .qc-entry {
      display: grid;
      gap: 6px;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
    }
    .qc-entry-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; padding: 14px; }
      aside { position: static; }
      .grid.cols-4, .grid.cols-3, .two-col, .filters { grid-template-columns: 1fr; }
      .topbar { grid-template-columns: 1fr; padding: 12px 14px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div>
        <h1>EvaluationClaw Diagnostic Report: __SPEC_ID__</h1>
        <p class="objective">__OBJECTIVE__</p>
      </div>
    </div>
  </header>
  <div class="app">
    <aside>
      <nav>
        <div class="nav-label">Model Performance</div>
        <a href="#overview">Overview</a>
        <a href="#capability">Capability Profile</a>
        <a href="#diagnostics">Diagnostics</a>
        <a href="#explorer">Item Explorer</a>
        <a href="#qc">QC and Judge</a>
        <div class="nav-label">Task Content</div>
        <a href="#task-content">Task Designs</a>
        <a href="#artifacts">Artifacts</a>
      </nav>
    </aside>
    <main>
      <section id="performance-part" class="part-heading">
        <h2>Part 1: Model Performance</h2>
        <p>Scores, failures, traces, QC decisions, and runtime diagnostics for the target model runs.</p>
      </section>
      <section id="overview"></section>
      <section id="capability"></section>
      <section id="diagnostics"></section>
      <section id="explorer"></section>
      <section id="qc"></section>
      <section id="task-part" class="part-heading">
        <h2>Part 2: Task Content</h2>
        <p>Human-readable task designs: what the target model can see, what remains hidden for scoring, and what outputs each task requires.</p>
      </section>
      <section id="task-content"></section>
      <section id="artifacts"></section>
    </main>
  </div>
  <script id="eval-data" type="application/json">__DATA__</script>
  <script>
    const payload = JSON.parse(document.getElementById("eval-data").textContent);
    const pkg = payload.package;
    const diag = payload.diagnostics;
    const records = diag.result_records || [];
    const itemById = new Map((pkg.dataset.items || []).map(item => [item.id, item]));
    const resultRecordsByItem = new Map();
    records.forEach(record => {
      if (!resultRecordsByItem.has(record.item_id)) resultRecordsByItem.set(record.item_id, []);
      resultRecordsByItem.get(record.item_id).push(record);
    });
    const passedItems = new Set((pkg.qc_report && pkg.qc_report.passed_item_ids) || []);
    const rejectedItems = new Set((pkg.qc_report && pkg.qc_report.rejected_item_ids) || []);
    const qs = id => document.getElementById(id);
    const pct = value => `${(Number(value || 0) * 100).toFixed(1)}%`;
    const scoreTone = value => Number(value || 0) >= 0.8 ? "good" : Number(value || 0) >= 0.5 ? "warn" : "bad";
    function node(tag, attrs = {}, text = null) {
      const el = document.createElement(tag);
      for (const [key, value] of Object.entries(attrs)) {
        if (key === "class") el.className = value;
        else if (key.startsWith("data-")) el.setAttribute(key, value);
        else el[key] = value;
      }
      if (text !== null && text !== undefined) el.textContent = String(text);
      return el;
    }
    function chip(text) { return node("span", {class: "chip"}, text); }
    function humanLabel(value, options = {}) {
      let text = value === null || value === undefined ? "" : String(value).trim();
      if (options.stripHash) text = text.replace(/[_-][0-9a-f]{8,16}$/i, "");
      text = text.replace(/_/g, " ").replace(/\\s+/g, " ").trim();
      if (!text) return "-";
      return text.split(" ").map(word => {
        if (/^[A-Z0-9]+$/.test(word)) return word;
        return word.charAt(0).toUpperCase() + word.slice(1);
      }).join(" ");
    }
    function itemLabel(value) { return humanLabel(value, {stripHash: true}); }
    function dimensionLabel(value) { return humanLabel(value); }
    function taskLabel(value) { return humanLabel(value); }
    function envLabel(value) { return humanLabel(value); }
    function bucketLabel(value) {
      const text = String(value || "");
      if (!text.includes(":")) return humanLabel(text);
      const [kind, rest] = text.split(/:(.*)/s);
      return `${humanLabel(kind)}: ${humanLabel(rest)}`;
    }
    function escapeRegExp(text) {
      const specials = new Set([".", "*", "+", "?", "^", "$", "{", "}", "(", ")", "|", "[", "]", "\\\\"]);
      return String(text).split("").map(char => specials.has(char) ? "\\\\" + char : char).join("");
    }
    const displayReplacements = [];
    function addDisplayReplacement(raw, label) {
      const rawText = raw === null || raw === undefined ? "" : String(raw);
      const labelText = label === null || label === undefined ? "" : String(label);
      if (rawText && labelText && rawText !== labelText) displayReplacements.push([rawText, labelText]);
    }
    ((pkg.dataset.spec || {}).dimensions || []).forEach(dimension => addDisplayReplacement(dimension.id, dimensionLabel(dimension.name || dimension.id)));
    displayReplacements.sort((a, b) => b[0].length - a[0].length);
    function displayText(value) {
      let text = value === null || value === undefined || value === "" ? "-" : String(value);
      displayReplacements.forEach(([raw, label]) => {
        text = text.replace(new RegExp(escapeRegExp(raw), "g"), label);
      });
      return text;
    }
    function escapeHtml(text) {
      return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }
    function renderInlineMarkdown(text) {
      let html = escapeHtml(displayText(text));
      html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
      html = html.replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>");
      html = html.replace(/\\*([^*]+)\\*/g, "<em>$1</em>");
      html = html.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)\\s]+)\\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
      return html;
    }
    function markdownNode(value) {
      const text = displayText(value);
      const root = node("div", {class: "markdown"});
      if (!text || text === "-") {
        root.append(node("span", {}, "-"));
        return root;
      }
      const lines = String(text).replace(/\\r\\n/g, "\\n").split("\\n");
      let paragraph = [];
      let list = null;
      let inFence = false;
      let fenceLines = [];
      const flushParagraph = () => {
        if (!paragraph.length) return;
        const p = node("p");
        p.innerHTML = renderInlineMarkdown(paragraph.join(" "));
        root.append(p);
        paragraph = [];
      };
      const flushList = () => {
        if (!list) return;
        root.append(list.el);
        list = null;
      };
      const flushFence = () => {
        const block = pre(fenceLines.join("\\n"));
        root.append(block);
        fenceLines = [];
      };
      lines.forEach(line => {
        if (/^\\s*```/.test(line)) {
          if (inFence) {
            inFence = false;
            flushFence();
          } else {
            flushParagraph();
            flushList();
            inFence = true;
            fenceLines = [];
          }
          return;
        }
        if (inFence) {
          fenceLines.push(line);
          return;
        }
        if (!line.trim()) {
          flushParagraph();
          flushList();
          return;
        }
        const heading = line.match(/^\\s{0,3}(#{1,3})\\s+(.+)$/);
        if (heading) {
          flushParagraph();
          flushList();
          const h = node(`h${heading[1].length}`);
          h.innerHTML = renderInlineMarkdown(heading[2]);
          root.append(h);
          return;
        }
        const bullet = line.match(/^\\s*[-*]\\s+(.+)$/);
        const ordered = line.match(/^\\s*\\d+\\.\\s+(.+)$/);
        if (bullet || ordered) {
          flushParagraph();
          const tag = ordered ? "ol" : "ul";
          if (!list || list.tag !== tag) {
            flushList();
            list = {tag, el: node(tag)};
          }
          const li = node("li");
          li.innerHTML = renderInlineMarkdown((bullet || ordered)[1]);
          list.el.append(li);
          return;
        }
        paragraph.push(line.trim());
      });
      if (inFence) flushFence();
      flushParagraph();
      flushList();
      return root;
    }
    function stat(label, value, tone = "") {
      const box = node("div", {class: "stat"});
      box.append(node("div", {class: "label"}, label));
      box.append(node("div", {class: `value ${tone ? "tone-" + tone : ""}`}, value));
      return box;
    }
    function pre(text) { return node("pre", {}, text || "-"); }
    function table(headers, rows) {
      if (!rows || rows.length === 0) return node("p", {class: "empty"}, "No rows.");
      const tbl = node("table");
      const thead = node("thead");
      const trh = node("tr");
      headers.forEach(header => trh.append(node("th", {}, header)));
      thead.append(trh);
      tbl.append(thead);
      const tbody = node("tbody");
      rows.forEach(row => {
        const tr = node("tr");
        row.forEach(cell => {
          const td = node("td");
          if (cell instanceof Node) td.append(cell);
          else td.textContent = String(cell ?? "-");
          tr.append(td);
        });
        tbody.append(tr);
      });
      tbl.append(tbody);
      return tbl;
    }
    function compositionTable(summaryRows, distributionRows) {
      const tbl = node("table");
      const thead = node("thead");
      const trh = node("tr");
      ["Bucket", "Count"].forEach(header => trh.append(node("th", {}, header)));
      thead.append(trh);
      tbl.append(thead);
      const tbody = node("tbody");
      const appendRow = row => {
        const tr = node("tr");
        row.forEach(cell => tr.append(node("td", {}, cell)));
        tbody.append(tr);
      };
      summaryRows.forEach(appendRow);
      if (distributionRows.length) {
        const sep = node("tr", {class: "table-separator"});
        const td = node("td");
        td.colSpan = 2;
        sep.append(td);
        tbody.append(sep);
      }
      distributionRows.forEach(appendRow);
      tbl.append(tbody);
      return tbl;
    }
    function clipText(value, limit = 12000) {
      const text = value === null || value === undefined ? "" : String(value);
      if (text.length <= limit) return text;
      const half = Math.floor(limit / 2);
      return `${text.slice(0, half)}\\n\\n...[clipped in browser view]...\\n\\n${text.slice(-half)}`;
    }
    function agentEnv(item) {
      const metadata = item.metadata || {};
      if (metadata.agent_env && typeof metadata.agent_env === "object") return metadata.agent_env;
      const taskAgent = metadata.task_agent || {};
      const execution = taskAgent.execution || {};
      if (execution.agent_env && typeof execution.agent_env === "object") return execution.agent_env;
      return {};
    }
    function taskPackage(item) {
      const metadata = item.metadata || {};
      return metadata.agent_task_package && typeof metadata.agent_task_package === "object" ? metadata.agent_task_package : {};
    }
    function taskAgent(item) {
      const metadata = item.metadata || {};
      return metadata.task_agent && typeof metadata.task_agent === "object" ? metadata.task_agent : {};
    }
    function fileMap(env, names) {
      for (const name of names) {
        const value = env[name];
        if (value && typeof value === "object" && !Array.isArray(value)) return value;
      }
      return {};
    }
    function taskStatus(item) {
      const results = resultRecordsByItem.get(item.id) || [];
      if (results.length) return {label: "Run", cls: "status-run"};
      if (rejectedItems.has(item.id)) return {label: "QC rejected", cls: "status-rejected"};
      if (passedItems.has(item.id)) return {label: "Accepted, not run", cls: "status-accepted"};
      return {label: "Not accepted", cls: "status-accepted"};
    }
    function domId(value) {
      return String(value || "").replace(/[^A-Za-z0-9_-]/g, "-");
    }
    function taskAnchorId(itemId) {
      return `task-${domId(itemId)}`;
    }
    function itemBaseLabel(itemOrId) {
      const id = typeof itemOrId === "object" && itemOrId ? itemOrId.id : itemOrId;
      return itemLabel(id).replace(/\\s+\\d+$/, "").trim() || "-";
    }
    function shortContentSummary(text) {
      const cleaned = String(text || "")
        .replace(/[_]+/g, " ")
        .replace(/\\s+/g, " ")
        .trim();
      if (!cleaned) return "";
      const words = cleaned.split(/\\s+/).slice(0, 8).join(" ");
      return humanLabel(words) + (cleaned.split(/\\s+/).length > 8 ? "..." : "");
    }
    function itemContentSummary(itemOrId) {
      const item = typeof itemOrId === "object" && itemOrId ? itemOrId : itemById.get(itemOrId);
      if (!item) return "";
      const metadata = item.metadata && typeof item.metadata === "object" ? item.metadata : {};
      if (metadata.task_content_summary) return humanLabel(metadata.task_content_summary);
      const sourceTitle = item.source && item.source.title ? String(item.source.title).trim() : "";
      const candidates = [sourceTitle, item.prompt, item.rubric];
      for (const candidate of candidates) {
        const value = String(candidate || "").trim();
        if (!value || value === item.id || value.includes(item.id)) continue;
        const summary = shortContentSummary(value);
        if (summary && summary !== itemBaseLabel(item)) return summary;
      }
      return taskLabel(item.task_type || "task");
    }
    function itemTaskTitle(itemOrId) {
      return `${itemBaseLabel(itemOrId)} - ${itemContentSummary(itemOrId)}`;
    }
    function targetsForItem(itemId) {
      const targets = [...new Set((resultRecordsByItem.get(itemId) || []).map(record => humanLabel(record.target_id)))];
      return targets.length ? targets.join(", ") : "Not Run";
    }
    function itemRunTitle(record) {
      return `${itemTaskTitle(record.item_id)} - ${humanLabel(record.target_id)}`;
    }
    function itemDesignTitle(item) {
      return `${itemTaskTitle(item)} - ${targetsForItem(item.id)}`;
    }
    function itemSourceLabel(itemOrRecord) {
      if (!itemOrRecord) return "generated";
      if ("source_backed" in itemOrRecord) return itemOrRecord.source_backed ? "sourced" : "generated";
      const kind = itemOrRecord.source && itemOrRecord.source.kind ? String(itemOrRecord.source.kind) : "";
      return kind && kind !== "self_generated" ? "sourced" : "generated";
    }
    (pkg.dataset.items || []).forEach(item => addDisplayReplacement(item.id, itemTaskTitle(item)));
    displayReplacements.sort((a, b) => b[0].length - a[0].length);
    function itemDisplayTitle(itemId) {
      const item = itemById.get(itemId);
      return item ? itemTaskTitle(item) : itemTaskTitle(itemId);
    }
    function itemTaskLink(itemId) {
      return node("a", {href: `#${taskAnchorId(itemId)}`}, itemDisplayTitle(itemId));
    }
    function dimensionPassSummary(targetId, dimensionId) {
      const scoped = records.filter(record => record.target_id === targetId && record.dimension_id === dimensionId);
      if (!scoped.length) return "-";
      const passed = scoped.filter(record => !record.error && Number(record.score || 0) >= 0.8).length;
      return `${passed}/${scoped.length}`;
    }
    function renderFiles(title, files, note, defaultOpen = false) {
      const wrap = node("div");
      wrap.append(node("h3", {}, title));
      if (note) wrap.append(node("p", {class: "small"}, note));
      const entries = Object.entries(files || {});
      if (!entries.length) {
        wrap.append(node("p", {class: "empty"}, "No files."));
        return wrap;
      }
      const grid = node("div", {class: "file-grid"});
      entries.forEach(([path, content]) => {
        const details = node("details", {class: "file-card"});
        if (defaultOpen) details.open = true;
        const summary = node("summary");
        summary.append(node("strong", {}, path));
        summary.append(node("span", {class: "small"}, `${String(content ?? "").length} chars`));
        details.append(summary);
        details.append(pre(clipText(content, 14000)));
        grid.append(details);
      });
      wrap.append(grid);
      return wrap;
    }
    function isPlainObject(value) {
      return value !== null && typeof value === "object" && !Array.isArray(value);
    }
    function isSecretKey(key) {
      return /(?:api[_-]?key|secret|token|password|credential|authorization)/i.test(String(key || ""));
    }
    function redactedValue(value) {
      if (Array.isArray(value)) return value.map(redactedValue);
      if (!isPlainObject(value)) return value;
      const result = {};
      Object.entries(value).forEach(([key, child]) => {
        result[key] = isSecretKey(key) ? "[redacted]" : redactedValue(child);
      });
      return result;
    }
    function hasRenderableValue(value) {
      if (value === null || value === undefined) return false;
      if (typeof value === "string") return value.trim() !== "" && value.trim() !== "-";
      if (Array.isArray(value)) return value.length > 0;
      if (isPlainObject(value)) return Object.keys(value).length > 0;
      return true;
    }
    function asArray(value) {
      if (Array.isArray(value)) return value;
      return hasRenderableValue(value) ? [value] : [];
    }
    function valueText(value) {
      const safe = redactedValue(value);
      if (safe === null || safe === undefined) return "";
      if (typeof safe === "string") return safe;
      if (typeof safe === "number" || typeof safe === "boolean") return String(safe);
      return JSON.stringify(safe, null, 2);
    }
    function renderDataDetails(summary, value, defaultOpen = false) {
      const details = node("details", {class: "file-card"});
      if (defaultOpen) details.open = true;
      details.append(node("summary", {}, summary));
      details.append(pre(clipText(valueText(value), 20000)));
      return details;
    }
    function renderValue(value) {
      if (!hasRenderableValue(value)) return node("span", {}, "-");
      const text = valueText(value);
      if (Array.isArray(value) || isPlainObject(value)) return renderDataDetails("Show details", value);
      if (text.includes("\\n") || text.length > 180) return pre(clipText(text, 9000));
      return node("span", {}, text);
    }
    function renderRows(rows) {
      const filtered = (rows || []).filter(row => hasRenderableValue(row[1]));
      return table(["Field", "Value"], filtered.map(([label, value]) => [label, renderValue(value)]));
    }
    function renderTaskSection(title, note, children) {
      const section = node("div", {class: "task-section"});
      section.append(node("h3", {}, title));
      if (note) section.append(node("p", {class: "small"}, note));
      const usefulChildren = (children || []).filter(Boolean);
      if (!usefulChildren.length) {
        section.append(node("p", {class: "empty"}, "No additional information recorded."));
      } else {
        usefulChildren.forEach(child => section.append(child));
      }
      return section;
    }
    function addFileEntries(target, files, sourceLabel = "") {
      if (!isPlainObject(files)) return;
      Object.entries(files).forEach(([path, content]) => {
        if (!path) return;
        if (!(path in target)) {
          target[path] = content;
          return;
        }
        if (String(target[path]) === String(content)) return;
        const suffix = sourceLabel ? ` [${sourceLabel}]` : " [duplicate]";
        target[`${path}${suffix}`] = content;
      });
    }
    function combinedFileMap(entries) {
      const files = {};
      (entries || []).forEach(entry => addFileEntries(files, entry.files, entry.source));
      return files;
    }
    function renderFileCards(files, defaultOpen = false) {
      const entries = Object.entries(files || {});
      if (!entries.length) return node("p", {class: "empty"}, "No files recorded.");
      const grid = node("div", {class: "file-grid"});
      entries.forEach(([path, content]) => {
        const details = node("details", {class: "file-card"});
        if (defaultOpen) details.open = true;
        const summary = node("summary");
        summary.append(node("strong", {}, path));
        summary.append(node("span", {class: "small"}, `${String(content ?? "").length} chars`));
        details.append(summary);
        details.append(pre(clipText(content, 14000)));
        grid.append(details);
      });
      return grid;
    }
    function objectWithout(value, excludedKeys) {
      if (!isPlainObject(value)) return {};
      const excluded = new Set(excludedKeys || []);
      return Object.fromEntries(Object.entries(value).filter(([key, child]) => !excluded.has(key) && hasRenderableValue(child)));
    }
    function matchingFileMap(files, pattern) {
      const selected = {};
      if (!isPlainObject(files)) return selected;
      Object.entries(files).forEach(([path, content]) => {
        const text = `${path}\\n${String(content || "").slice(0, 400)}`;
        if (pattern.test(text)) selected[path] = content;
      });
      return selected;
    }
    function renderOverview() {
      const section = qs("overview");
      section.innerHTML = "<h2>Overview</h2>";
      const summaries = pkg.run.summaries || [];
      const avg = summaries.length ? summaries.reduce((sum, row) => sum + Number(row.average_score || 0), 0) / summaries.length : 0;
      const dimensions = ((pkg.dataset.spec || {}).dimensions || []).length;
      const grid = node("div", {class: "grid cols-3"});
      grid.append(stat("Dimensions", dimensions));
      grid.append(stat("Used items", diag.used_items ?? (pkg.run.results || []).length));
      grid.append(stat("Mean target accuracy", summaries.length ? pct(avg) : "not run", summaries.length ? scoreTone(avg) : ""));
      section.append(grid);
      const targetRows = summaries.map(row => [humanLabel(row.target_id), pct(row.average_score), row.total_items, row.errors]);
      section.append(node("h3", {}, "Targets"));
      section.append(table(["Target", "Average", "Items", "Errors"], targetRows));
    }
    function renderCapability() {
      const section = qs("capability");
      section.innerHTML = "<h2>Capability Profile</h2>";
      const rows = [];
      (pkg.run.summaries || []).forEach(summary => {
        Object.entries(summary.score_by_dimension || {}).forEach(([dimension, score]) => rows.push([
          humanLabel(summary.target_id),
          dimensionLabel(dimension),
          dimensionPassSummary(summary.target_id, dimension),
          pct(score),
        ]));
      });
      section.append(table(["Target", "Dimension", "Pass / Total", "Score"], rows));
      const totalItems = diag.generated_items ?? (pkg.dataset.items || []).length;
      const usedItems = diag.used_items ?? (pkg.dataset.items || []).length;
      const summaryRows = [
        ["Task designs", usedItems],
        ["Generated / QC passed", `${totalItems}/${usedItems}`],
        ["Sourced / QC passed", `${diag.source_backed_items}/${usedItems}`],
      ];
      const distributionRows = [
        ...Object.entries(diag.task_counts || {}).map(([k, v]) => [bucketLabel(`task:${k}`), v]),
        ...Object.entries(diag.difficulty_counts || {}).map(([k, v]) => [bucketLabel(`difficulty:${k}`), v]),
      ];
      section.append(node("h3", {}, "Dataset Composition"));
      section.append(compositionTable(summaryRows, distributionRows));
    }
    function renderDiagnostics() {
      const section = qs("diagnostics");
      section.innerHTML = "<h2>Diagnostics</h2>";
      const failureRows = (diag.failure_modes || []).map(row => [
        humanLabel(row.target_id),
        dimensionLabel(row.dimension_id),
        row.items,
        pct(row.average_score),
        itemTaskLink(row.worst_item),
      ]);
      section.append(table(["Target", "Weak Dimension", "Items", "Average", "Worst Item"], failureRows));
    }
    function uniqueValues(key) {
      return [...new Set(records.map(row => row[key]).filter(Boolean))].sort();
    }
    function fillSelect(id, values, labelFn = humanLabel) {
      const sel = qs(id);
      values.forEach(value => sel.append(node("option", {value}, labelFn(value))));
    }
    function recordSearchText(record) {
      return [record.item_id, record.target_id, record.dimension_id, record.task_type, record.prompt, record.rubric, record.judge_reasoning, record.error, (record.risks || []).join(" ")].join(" ").toLowerCase();
    }
    function renderExplorer() {
      const section = qs("explorer");
      section.innerHTML = `<h2>Item Explorer</h2>
        <div class="filters">
          <input id="filter-search" placeholder="Search item, prompt, judge evidence, risk">
          <select id="filter-target"><option value="">All targets</option></select>
          <select id="filter-dimension"><option value="">All dimensions</option></select>
          <select id="filter-task"><option value="">All task types</option></select>
          <select id="filter-severity"><option value="">All outcomes</option></select>
        </div>
        <div id="item-list"></div>`;
      fillSelect("filter-target", uniqueValues("target_id"), humanLabel);
      fillSelect("filter-dimension", uniqueValues("dimension_id"), dimensionLabel);
      fillSelect("filter-task", uniqueValues("task_type"), taskLabel);
      fillSelect("filter-severity", uniqueValues("severity"));
      ["filter-search", "filter-target", "filter-dimension", "filter-task", "filter-severity"].forEach(id => qs(id).addEventListener("input", applyFilters));
      applyFilters();
    }
    function renderRecord(record) {
      const item = node("details", {class: "item"});
      item.setAttribute("data-target", record.target_id);
      item.setAttribute("data-dimension", record.dimension_id);
      item.setAttribute("data-task", record.task_type);
      item.setAttribute("data-severity", record.severity);
      item.setAttribute("data-search", recordSearchText(record));
      const summary = node("summary");
      const left = node("div");
      left.append(node("strong", {}, itemRunTitle(record)));
      left.append(node("div", {class: "small"}, `${taskLabel(record.task_type)} | ${humanLabel(record.difficulty)} | ${itemSourceLabel(record)}`));
      const right = node("div", {class: `tone-${scoreTone(record.score)}`}, `${record.score_label} ${record.severity}`);
      summary.append(left, right);
      item.append(summary);
      const body = node("div", {class: "item-body"});
      body.append(node("h3", {}, "Prompt"));
      body.append(pre(record.prompt));
      if (record.rubric) {
        body.append(node("h3", {}, "Evaluation Criteria"));
        body.append(pre(record.rubric));
      }
      body.append(node("h3", {}, "Judge Reasoning"));
      body.append(pre(displayText(record.error || record.judge_reasoning || "-")));
      if (record.agent_trace) {
        const traceDetails = node("details", {class: "file-card"});
        traceDetails.append(node("summary", {}, "Agent Trace Summary"));
        traceDetails.append(table(["Step", "Action", "Score", "Done", "Error", "Observation"], (record.agent_trace.trace || []).map(step => [
          step.step,
          displayText(JSON.stringify(step.action || {})),
          step.score_after_step ?? "-",
          step.done ?? "-",
          displayText(step.error || "-"),
          displayText(step.observation || "-"),
        ])));
        traceDetails.append(node("h3", {}, "Final State"));
        traceDetails.append(pre(displayText(JSON.stringify(record.agent_trace.final_state || {}, null, 2))));
        body.append(traceDetails);
      }
      if (record.raw_response) {
        const raw = node("details", {class: "file-card"});
        raw.append(node("summary", {}, "Raw response"));
        raw.append(pre(displayText(record.raw_response)));
        body.append(raw);
      }
      item.append(body);
      return item;
    }
    function applyFilters() {
      const list = qs("item-list");
      list.innerHTML = "";
      const search = (qs("filter-search").value || "").toLowerCase();
      const target = qs("filter-target").value;
      const dimension = qs("filter-dimension").value;
      const task = qs("filter-task").value;
      const severity = qs("filter-severity").value;
      const filtered = records.filter(record =>
        (!search || recordSearchText(record).includes(search)) &&
        (!target || record.target_id === target) &&
        (!dimension || record.dimension_id === dimension) &&
        (!task || record.task_type === task) &&
        (!severity || record.severity === severity)
      );
      if (!filtered.length) {
        list.append(node("p", {class: "empty"}, "No matching item records."));
        return;
      }
      filtered.forEach(record => list.append(renderRecord(record)));
    }
    function renderTaskContent() {
      const section = qs("task-content");
      section.innerHTML = `<h2>Task Designs</h2>
        <div class="filters">
          <input id="task-filter-search" placeholder="Search task, file name, output, scoring">
          <select id="task-filter-status"><option value="">All statuses</option></select>
          <select id="task-filter-env"><option value="">All environments</option></select>
          <select id="task-filter-dimension"><option value="">All dimensions</option></select>
          <select id="task-filter-type"><option value="">All task types</option></select>
        </div>
        <div id="task-list"></div>`;
      const items = pkg.dataset.items || [];
      const taskRows = items.map(item => {
        const metadata = item.metadata || {};
        const env = agentEnv(item);
        const pack = taskPackage(item);
        const agent = taskAgent(item);
        const visibleInputs = isPlainObject(pack.visible_inputs) ? pack.visible_inputs : {};
        const hiddenRefs = isPlainObject(pack.hidden_references) ? pack.hidden_references : {};
        const initial = isPlainObject(agent.initial_content) ? agent.initial_content : {};
        const interaction = isPlainObject(agent.interaction) ? agent.interaction : {};
        const taskAgentScoring = isPlainObject(agent.scoring) ? agent.scoring : {};
        const execution = isPlainObject(pack.execution) ? pack.execution : {};
        const envRequirements = isPlainObject(pack.environment_requirements) ? pack.environment_requirements : {};
        const artifactCollection = isPlainObject(pack.artifact_collection) ? pack.artifact_collection : {};
        const trajectoryRequirements = isPlainObject(pack.trajectory_requirements) ? pack.trajectory_requirements : {};
        const resourceProvenance = isPlainObject(pack.resource_provenance) ? pack.resource_provenance : {};
        const capabilityTarget = isPlainObject(pack.capability_target) ? pack.capability_target : {};
        const multimodal = isPlainObject(metadata.multimodal) ? metadata.multimodal : {};
        const swebench = isPlainObject(metadata.swebench) ? metadata.swebench : {};
        const envSession = isPlainObject(env.session) ? env.session : {};
        const initialSession = isPlainObject(initial.session) ? initial.session : {};
        const visibleFiles = combinedFileMap([
          {files: fileMap(env, ["visible_files", "files"]), source: "agent_env"},
          {files: visibleInputs.files, source: "visible_inputs"},
          {files: visibleInputs.asset_files, source: "visible_inputs.assets"},
          {files: initial.files, source: "initial_content"},
          {files: envSession.asset_files, source: "agent_env.session"},
          {files: initialSession.asset_files, source: "initial_content.session"},
        ]);
        const hiddenFiles = combinedFileMap([
          {files: fileMap(env, ["hidden_files"]), source: "agent_env"},
          {files: hiddenRefs.files, source: "hidden_references"},
        ]);
        const referenceFiles = matchingFileMap(
          hiddenFiles,
          /(?:gold|reference|expected|solution|answer|oracle|fixed|truth)/i,
        );
        const output = pack.output_contract || {};
        const evaluation = pack.evaluation || env.evaluation || {};
        const status = taskStatus(item);
        const required = asArray(output.required_outputs);
        const expectedArtifacts = asArray(output.expected_artifacts || evaluation.expected_artifacts);
        const search = [
          item.id,
          item.dimension_id,
          item.task_type,
          item.prompt,
          item.rubric,
          env.type,
          env.test_command,
          Object.keys(visibleFiles).join(" "),
          Object.keys(hiddenFiles).join(" "),
          valueText(required),
          valueText(expectedArtifacts),
          evaluation.pass_criteria,
          valueText(capabilityTarget),
          valueText(visibleInputs.assets),
          valueText(envRequirements),
          valueText(resourceProvenance),
          valueText(item.answer),
        ].join(" ").toLowerCase();
        return {
          item,
          metadata,
          env,
          pack,
          agent,
          visibleInputs,
          hiddenRefs,
          initial,
          interaction,
          taskAgentScoring,
          execution,
          envRequirements,
          artifactCollection,
          trajectoryRequirements,
          resourceProvenance,
          capabilityTarget,
          multimodal,
          swebench,
          visibleFiles,
          hiddenFiles,
          referenceFiles,
          output,
          evaluation,
          status,
          required,
          expectedArtifacts,
          search,
        };
      });
      const setOptions = (id, values) => {
        const sel = qs(id);
        [...new Set(values.filter(Boolean).map(String))].sort().forEach(value => sel.append(node("option", {value}, humanLabel(value))));
      };
      setOptions("task-filter-status", taskRows.map(row => row.status.label));
      setOptions("task-filter-env", taskRows.map(row => row.env.type || "unknown"));
      setOptions("task-filter-dimension", taskRows.map(row => row.item.dimension_id));
      setOptions("task-filter-type", taskRows.map(row => row.item.task_type));
      ["task-filter-search", "task-filter-status", "task-filter-env", "task-filter-dimension", "task-filter-type"].forEach(id => qs(id).addEventListener("input", applyTaskFilters));

      function renderTask(row) {
        const {
          item,
          metadata,
          env,
          pack,
          agent,
          visibleInputs,
          hiddenRefs,
          initial,
          interaction,
          taskAgentScoring,
          execution,
          envRequirements,
          artifactCollection,
          trajectoryRequirements,
          resourceProvenance,
          capabilityTarget,
          multimodal,
          swebench,
          visibleFiles,
          hiddenFiles,
          referenceFiles,
          output,
          evaluation,
          status,
          required,
          expectedArtifacts,
        } = row;
        const details = node("details", {class: "item"});
        details.id = taskAnchorId(item.id);
        details.setAttribute("data-search", row.search);
        details.setAttribute("data-status", status.label);
        details.setAttribute("data-env", env.type || "unknown");
        details.setAttribute("data-dimension", item.dimension_id || "");
        details.setAttribute("data-task", item.task_type || "");
        const summary = node("summary");
        const left = node("div");
        left.append(node("strong", {}, itemDesignTitle(item)));
        left.append(node("div", {class: "small"}, `${taskLabel(item.task_type)} | ${envLabel(env.type || "unknown")} | ${itemSourceLabel(item)}`));
        const pill = node("span", {class: `status-pill ${status.cls}`}, status.label);
        summary.append(left, pill);
        details.append(summary);

        const body = node("div", {class: "item-body"});

        const promptChildren = [pre(item.prompt || "-")];
        if (hasRenderableValue(visibleInputs.instructions) && String(visibleInputs.instructions).trim() !== String(item.prompt || "").trim()) {
          promptChildren.push(renderDataDetails("Visible input instructions", visibleInputs.instructions));
        }
        if (hasRenderableValue(interaction.initial_user_message) && String(interaction.initial_user_message).trim() !== String(item.prompt || "").trim()) {
          promptChildren.push(renderDataDetails("Initial user message", interaction.initial_user_message));
        }
        if (hasRenderableValue(interaction.user_turns)) {
          promptChildren.push(renderDataDetails("Scripted follow-up turns", interaction.user_turns));
        }
        if (hasRenderableValue(multimodal.content)) {
          promptChildren.push(renderDataDetails("Multimodal prompt content blocks", multimodal.content));
        }
        if (agent.system_prompt) {
          promptChildren.push(renderDataDetails("Task-agent system prompt", agent.system_prompt));
        }
        body.append(renderTaskSection(
          "1. Target-visible prompt",
          "The prompt, interaction messages, and system/task-agent instructions supplied to the evaluated model.",
          promptChildren,
        ));

        const contractRows = [
          ["Required outputs", required],
          ["Expected artifacts", expectedArtifacts],
          ["Output schema", output.schema],
          ["Output constraints", output.constraints],
          ["Test command", env.test_command],
          ["Evaluation command/process", execution.evaluate],
          ["Execution setup", execution.setup],
          ["Execution run protocol", execution.run],
          ["Scoring method", evaluation.method || (item.scoring || {}).method || "-"],
          ["Evaluation checks", evaluation.checks],
          ["Pass criteria", evaluation.pass_criteria || item.rubric || "-"],
          ["Partial criteria", evaluation.partial_criteria || "-"],
          ["Fail criteria", evaluation.fail_criteria || "-"],
          ["Score levels", evaluation.score_levels || taskAgentScoring.levels],
          ["Task-agent scoring guidance", taskAgentScoring],
          ["SWE-bench fail-to-pass tests", swebench.FAIL_TO_PASS],
          ["SWE-bench pass-to-pass tests", swebench.PASS_TO_PASS],
        ];
        const scoringChildren = [renderRows(contractRows)];
        const hiddenRefSummary = objectWithout(hiddenRefs, ["files"]);
        if (hasRenderableValue(hiddenRefSummary)) {
          scoringChildren.push(renderDataDetails("Hidden reference / evaluator metadata", hiddenRefSummary));
        }
        if (hasRenderableValue(swebench.test_patch)) {
          scoringChildren.push(renderDataDetails("SWE-bench hidden test_patch", swebench.test_patch));
        }
        if (Object.keys(hiddenFiles).length) {
          scoringChildren.push(node("p", {class: "small"}, "Runner-private evaluator files and hidden references. The target model does not see these during evaluation."));
          scoringChildren.push(renderFileCards(hiddenFiles));
        }
        body.append(renderTaskSection(
          "2. Outputs, scoring, and evaluator materials",
          "Required deliverables, pass/partial/fail criteria, evaluation process, and private evaluator materials.",
          scoringChildren,
        ));

        const visibleContextRows = [
          ["Visible assets/resources", visibleInputs.assets || visibleInputs.resources],
          ["Initial scenario", initial.scenario],
          ["Initial session", initial.session],
          ["Initial VM summary", initial.vm],
          ["Initial notes", initial.notes],
          ["Multimodal modalities", multimodal.modalities],
          ["Multimodal assets", multimodal.assets],
          ["SWE-bench repository", swebench.repo],
          ["SWE-bench base commit", swebench.base_commit],
          ["SWE-bench environment setup commit", swebench.environment_setup_commit],
          ["SWE-bench problem version", swebench.version],
        ];
        const visibleChildren = [renderRows(visibleContextRows)];
        if (Object.keys(visibleFiles).length) {
          visibleChildren.push(node("p", {class: "small"}, "Files and resources staged before the run and visible through the target agent's file or desktop tools."));
          visibleChildren.push(renderFileCards(visibleFiles));
        }
        body.append(renderTaskSection(
          "3. Model-visible context and resources",
          "Files, assets, repository snapshots, media, session state, and other input resources visible to the model.",
          visibleChildren,
        ));

        const environmentRows = [
          ["Environment type", env.type || envRequirements.type],
          ["Tools", env.tools],
          ["Required tools", trajectoryRequirements.required_tools],
          ["Forbidden shortcuts", trajectoryRequirements.forbidden_shortcuts],
          ["Required software", env.required_software || envRequirements.required_software],
          ["Network", env.network || envRequirements.network],
          ["Docker/VM image", env.image || envRequirements.image],
          ["Docker image selection", env.image_selection],
          ["Docker image build", env.image_build || envRequirements.image_build],
          ["Pull image", env.pull_image],
          ["Setup commands", env.setup_commands],
          ["Max steps", env.max_steps || execution.max_steps],
          ["Timeout", env.timeout || execution.timeout_s],
          ["Workspace", env.workspace],
          ["Session", env.session],
          ["VM", env.vm || envRequirements.vm],
          ["VM materialization", env.vm_materialization],
          ["VM provisioning", env.vm_provisioning || envRequirements.vm_provisioning],
          ["Requires VM", env.requires_vm || envRequirements.requires_vm],
          ["Resource limits", env.resource_limits || envRequirements.resource_limits],
          ["Desktop bridge URL", env.bridge_url],
          ["VM provider URL", env.vm_provider_url],
          ["Artifact collection", artifactCollection],
          ["Trajectory audit requirements", trajectoryRequirements],
          ["Task-agent role", agent.agent_role],
        ];
        body.append(renderTaskSection(
          "4. Tools, environment, and initial state",
          "Runtime tools, sandbox/VM/desktop environment, setup, limits, and initial state required to execute the task.",
          [renderRows(environmentRows)],
        ));

        const referenceMetadata = {};
        [
          "reference_answer",
          "reference_solution",
          "standard_answer",
          "expected_answer",
          "gold_answer",
          "gold_patch",
          "oracle_answer",
          "solution",
        ].forEach(key => {
          if (hasRenderableValue(metadata[key])) referenceMetadata[key] = metadata[key];
        });
        const referenceRows = [
          ["Answer key", item.answer],
          ["Choices", item.choices],
          ["Reference metadata", referenceMetadata],
          ["Reference artifacts", hiddenRefs.reference_artifacts],
          ["Reference notes", hiddenRefs.notes],
          ["SWE-bench gold patch", swebench.patch],
        ];
        const referenceChildren = [];
        const hasReferenceRows = referenceRows.some(row => hasRenderableValue(row[1]));
        if (hasReferenceRows) {
          referenceChildren.push(renderRows(referenceRows));
        }
        if (Object.keys(referenceFiles).length) {
          referenceChildren.push(node("p", {class: "small"}, "Reference-like hidden files inferred from names/content such as gold, expected, solution, oracle, answer, or truth."));
          referenceChildren.push(renderFileCards(referenceFiles));
        }
        if (!hasReferenceRows && !Object.keys(referenceFiles).length) {
          referenceChildren.push(node("p", {class: "empty"}, "No standalone reference answer is recorded; the evaluator materials and scoring criteria define success."));
        }
        body.append(renderTaskSection(
          "5. Reference answer or solution",
          "Gold answers, reference outputs, expected artifacts, oracle notes, or reference patches when the task has them.",
          referenceChildren,
        ));

        const constructionMetadata = objectWithout(metadata, [
          "agent_env",
          "task_agent",
          "agent_task_package",
          "multimodal",
          "swebench",
        ]);
        const sourceRows = [
          ["Item ID", item.id],
          ["Dimension", item.dimension_id],
          ["Task type", item.task_type],
          ["Difficulty", item.difficulty],
          ["Tags", item.tags],
          ["Source label", itemSourceLabel(item)],
          ["Source kind", item.source && item.source.kind],
          ["Source title", item.source && item.source.title],
          ["Source URI", item.source && item.source.uri],
          ["Source notes", item.source && item.source.notes],
          ["Package schema/style", [pack.schema_version, pack.style].filter(Boolean).join(" / ")],
          ["Capability target", capabilityTarget],
          ["Resource provenance", resourceProvenance],
          ["SWE-bench instance", swebench.instance_id || swebench.instance_ids],
          ["Additional construction metadata", constructionMetadata],
        ];
        body.append(renderTaskSection(
          "6. Source and construction metadata",
          "Where the task came from, how it was constructed, and the capability/dimension metadata used for benchmark review.",
          [renderRows(sourceRows)],
        ));

        const runRows = (resultRecordsByItem.get(item.id) || []).map(record => [
          humanLabel(record.target_id),
          record.score_label,
          record.error || "-",
          displayText(record.judge_reasoning || "-"),
        ]);
        body.append(node("h3", {}, "Run result for this task"));
        body.append(table(["Target", "Score", "Error", "Reasoning"], runRows));
        details.append(body);
        return details;
      }

      function applyTaskFilters() {
        const list = qs("task-list");
        list.innerHTML = "";
        const search = (qs("task-filter-search").value || "").toLowerCase();
        const status = qs("task-filter-status").value;
        const env = qs("task-filter-env").value;
        const dimension = qs("task-filter-dimension").value;
        const task = qs("task-filter-type").value;
        const filtered = taskRows.filter(row =>
          (!search || row.search.includes(search)) &&
          (!status || row.status.label === status) &&
          (!env || (row.env.type || "unknown") === env) &&
          (!dimension || row.item.dimension_id === dimension) &&
          (!task || row.item.task_type === task)
        );
        if (!filtered.length) {
          list.append(node("p", {class: "empty"}, "No matching tasks."));
          return;
        }
        filtered.forEach(row => list.append(renderTask(row)));
      }

      applyTaskFilters();
    }
    function renderQc() {
      const section = qs("qc");
      section.innerHTML = "<h2>QC and Judge Audit</h2>";
      const qc = pkg.qc_report || {};
      const grid = node("div", {class: "grid cols-4"});
      grid.append(stat("QC quality", pct(qc.quality_score), scoreTone(qc.quality_score)));
      grid.append(stat("Passed items", (qc.passed_item_ids || []).length));
      grid.append(stat("Rejected items", (qc.rejected_item_ids || []).length));
      grid.append(stat("QC issues", (qc.issues || []).length, (qc.issues || []).length ? "warn" : "good"));
      section.append(grid);

      function groupedQcIssues(issues) {
        const groups = [];
        const byItem = new Map();
        (issues || []).forEach((issue, index) => {
          const itemId = issue.item_id ? String(issue.item_id) : "";
          const key = itemId ? `item:${itemId}` : `global:${index}`;
          let group = byItem.get(key);
          if (!group) {
            group = {item_id: itemId, issues: []};
            byItem.set(key, group);
            groups.push(group);
          }
          group.issues.push({...issue, _order: index + 1});
        });
        return groups;
      }
      function qcHistoryDetails(group) {
        if (!group.issues || group.issues.length <= 1) return null;
        const details = node("details", {class: "qc-more"});
        details.append(node("summary", {}, `Show more (${group.issues.length} QC entries)`));
        const history = node("div", {class: "qc-history"});
        group.issues.forEach(issue => {
          const entry = node("div", {class: "qc-entry"});
          const meta = node("div", {class: "qc-entry-meta"});
          meta.append(node("span", {}, `#${issue._order}`));
          meta.append(node("span", {}, humanLabel(issue.severity)));
          meta.append(node("span", {}, humanLabel(issue.category)));
          entry.append(meta);
          entry.append(markdownNode(issue.message || "-"));
          if (issue.suggested_action) {
            entry.append(node("div", {class: "small"}, "Suggested action"));
            entry.append(markdownNode(issue.suggested_action));
          }
          history.append(entry);
        });
        details.append(history);
        return details;
      }
      const qcRows = groupedQcIssues(qc.issues || []).map(group => {
        const first = group.issues[0] || {};
        const message = node("div");
        message.append(markdownNode(first.message || "-"));
        const history = qcHistoryDetails(group);
        if (history) message.append(history);
        return [
          humanLabel(first.severity),
          humanLabel(first.category),
          group.item_id ? itemTaskLink(group.item_id) : "-",
          message,
          markdownNode(first.suggested_action || "-"),
        ];
      });
      section.append(table(["Severity", "Category", "Item", "Message", "Suggested Action"], qcRows));
      section.append(node("h3", {}, "Judge Signals"));
      section.append(table(["Metric", "Value"], [
        ["LLM-judged results", diag.judge.llm_judged_results],
        ["Deterministic or unjudged results", diag.judge.deterministic_or_unjudged_results],
        ["Double-pass instability flags", diag.judge.instability_flags],
      ]));
    }
    function renderArtifacts() {
      const section = qs("artifacts");
      section.innerHTML = "<h2>Artifacts</h2>";
      const rows = [
        ["Canonical JSON", "This HTML embeds a clipped viewer payload; use the package JSON for full raw values."],
        ["Markdown", "The Markdown report remains generated for terminal and diff-friendly review."],
        ["lm-eval export", "Interoperability artifacts are generated when the pipeline persists a package."],
      ];
      section.append(table(["Artifact", "Purpose"], rows));
      if (pkg.report && pkg.report.recommendations) {
        section.append(node("h3", {}, "Recommendations"));
        section.append(table(["Recommendation"], pkg.report.recommendations.map(row => [row])));
      }
    }
    renderOverview();
    renderCapability();
    renderDiagnostics();
    renderExplorer();
    renderQc();
    renderTaskContent();
    renderArtifacts();
  </script>
</body>
</html>
"""
