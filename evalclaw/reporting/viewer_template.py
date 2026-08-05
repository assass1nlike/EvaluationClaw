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
    section > h3 { margin-top: 18px; }
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
    .composition {
      display: grid;
      gap: 12px;
      margin-top: 8px;
    }
    .composition-summary {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .composition-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 12px;
      min-height: 76px;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.85);
    }
    .composition-card .label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    .composition-card .value {
      margin-top: 7px;
      font-size: 22px;
      font-weight: 750;
      overflow-wrap: anywhere;
    }
    .composition-distribution {
      display: grid;
      gap: 2px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 8px 12px;
    }
    .composition-row {
      display: grid;
      grid-template-columns: minmax(180px, 1fr) minmax(160px, 2fr) auto;
      gap: 12px;
      align-items: center;
      padding: 10px 0;
      border-bottom: 1px solid var(--line);
    }
    .composition-row:last-child { border-bottom: 0; }
    .composition-row .name {
      font-weight: 600;
      overflow-wrap: anywhere;
    }
    .composition-row .bar {
      height: 10px;
      border-radius: 999px;
      background: #e9eef6;
      overflow: hidden;
    }
    .composition-row .fill {
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), #58a6ff);
      min-width: 4px;
    }
    .composition-row .count {
      color: var(--muted);
      font-weight: 650;
      min-width: 36px;
      text-align: right;
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
      .composition-summary, .composition-row { grid-template-columns: 1fr; }
      .composition-row .count { text-align: left; }
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
        <a href="#overview">Overview</a>
        <a href="#capability">Capability Profile</a>
        <a href="#diagnostics">Diagnostics</a>
        <a href="#explorer">Item Explorer</a>
        <a href="#qc">Task Composition and QC</a>
      </nav>
    </aside>
    <main>
      <section id="overview"></section>
      <section id="capability"></section>
      <section id="diagnostics"></section>
      <section id="explorer"></section>
      <section id="qc"></section>
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
      const wrap = node("div", {class: "composition"});
      if (summaryRows && summaryRows.length) {
        const summary = node("div", {class: "composition-summary"});
        summaryRows.forEach(([label, value]) => {
          const card = node("div", {class: "composition-card"});
          card.append(node("div", {class: "label"}, label));
          card.append(node("div", {class: "value"}, value));
          summary.append(card);
        });
        wrap.append(summary);
      }

      if (distributionRows && distributionRows.length) {
        const distribution = node("div", {class: "composition-distribution"});
        const maxCount = Math.max(...distributionRows.map(row => Number(row[1] || 0)), 1);
        distributionRows.forEach(([label, value]) => {
          const count = Number(value || 0);
          const width = Math.max(4, Math.round((count / maxCount) * 100));
          const row = node("div", {class: "composition-row"});
          row.append(node("div", {class: "name"}, label));
          const bar = node("div", {class: "bar"});
          const fill = node("div", {class: "fill"});
          fill.style.width = `${width}%`;
          bar.append(fill);
          row.append(bar);
          row.append(node("div", {class: "count"}, value));
          distribution.append(row);
        });
        wrap.append(distribution);
      }
      return wrap;
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
    function itemByIdMap() {
      const map = new Map();
      (pkg.dataset.items || []).forEach(item => map.set(item.id, item));
      return map;
    }
    const datasetItemById = itemByIdMap();
    function groupedPerformanceRows(groupKey, labelFn) {
      const groups = new Map();
      (pkg.dataset.items || []).forEach(item => {
        const key = groupKey(item) || "-";
        if (!groups.has(key)) groups.set(key, {key, plannedTotal: 0, pass: 0, scoreSum: 0, scoreCount: 0});
        const group = groups.get(key);
        group.plannedTotal += 1;
      });
      (pkg.run.results || []).forEach(result => {
        const item = datasetItemById.get(result.item_id);
        if (!item) return;
        const key = groupKey(item) || "-";
        if (!groups.has(key)) groups.set(key, {key, plannedTotal: 0, pass: 0, scoreSum: 0, scoreCount: 0});
        const group = groups.get(key);
        const score = Number(result.score || 0);
        if (score >= 0.999) group.pass += 1;
        group.scoreSum += score;
        group.scoreCount += 1;
      });
      return [...groups.values()]
        .map(group => ({...group, total: group.scoreCount || group.plannedTotal}))
        .sort((a, b) => (b.total - a.total) || String(a.key).localeCompare(String(b.key)))
        .map(group => [
          labelFn(group.key),
          `${group.pass}/${group.total}`,
          group.scoreCount ? pct(group.scoreSum / group.scoreCount) : "not run",
        ]);
    }
    function taskTypePerformanceRows() {
      return groupedPerformanceRows(item => item.task_type, taskLabel);
    }
    function dimensionPerformanceRows() {
      return groupedPerformanceRows(item => item.dimension_id, dimensionLabel);
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
    function buildTaskRow(item) {
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
      const output = isPlainObject(pack.output_contract) ? pack.output_contract : {};
      const evaluation = isPlainObject(pack.evaluation)
        ? pack.evaluation
        : (isPlainObject(env.evaluation) ? env.evaluation : {});
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
        valueText(item.expected_text),
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
    }
    const taskRows = (pkg.dataset.items || []).map(buildTaskRow);
    function objectWithValues(entries) {
      const result = {};
      (entries || []).forEach(([key, value]) => {
        if (hasRenderableValue(value)) result[key] = redactedValue(value);
      });
      return result;
    }
    function firstRenderable(...values) {
      for (const value of values) {
        if (hasRenderableValue(value)) return value;
      }
      return "";
    }
    function stripBaseText(fullValue, baseValue) {
      const full = String(fullValue || "").trim();
      const base = String(baseValue || "").trim();
      if (!full || !base) return full;
      if (full === base) return "";
      if (full.startsWith(base)) return full.slice(base.length).trim();
      return full;
    }
    function linesFromEntries(entries) {
      return (entries || [])
        .filter(([, value]) => hasRenderableValue(value))
        .map(([label, value]) => `${label}: ${valueText(value)}`)
        .join("\\n");
    }
    function qualityFlagsForTask(row) {
      const {item, env, pack, hiddenFiles, hiddenRefs, multimodal} = row;
      const flags = [itemSourceLabel(item)];
      if (hasRenderableValue(pack)) flags.push("executable task package");
      if (env.requires_vm || hasRenderableValue(env.vm) || hasRenderableValue((pack.environment_requirements || {}).vm)) {
        flags.push("requires VM");
      }
      if (env.type === "gui_desktop" || (pack.environment_requirements || {}).requires_gui) flags.push("requires GUI");
      if (Object.keys(hiddenFiles || {}).length || hasRenderableValue(hiddenRefs.reference_artifacts)) {
        flags.push("requires hidden evaluator");
      }
      if (hasRenderableValue(multimodal.assets) || hasRenderableValue(multimodal.content)) flags.push("multimodal");
      return [...new Set(flags)];
    }
    function sourceSummary(row) {
      const {item, resourceProvenance} = row;
      if (itemSourceLabel(item) === "generated") return "";
      return objectWithValues([
        ["kind", item.source && item.source.kind],
        ["title", item.source && item.source.title],
        ["notes", item.source && item.source.notes],
        ["provenance", resourceProvenance.source_kind],
      ]);
    }
    function referenceMetadata(metadata) {
      const result = {};
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
        if (hasRenderableValue(metadata[key])) result[key] = metadata[key];
      });
      return result;
    }
    function buildUnifiedTaskView(row) {
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
        visibleFiles,
        hiddenFiles,
        referenceFiles,
        output,
        evaluation,
        required,
        expectedArtifacts,
      } = row;

      const capability = objectWithValues([
        ["name", capabilityTarget.name || capabilityTarget.content_summary],
        ["description", capabilityTarget.description],
      ]);
      const targetUserPrompt = item.prompt || visibleInputs.instructions || "";
      const initialAddendum = objectWithValues([
        ["initial_user_message_addendum", stripBaseText(interaction.initial_user_message, targetUserPrompt)],
        ["initial_task_content", initial.content || initial.summary],
        ["initial_observation_summary", initial.observation || initial.observation_summary],
        ["tool_summary", interaction.tool_summary],
        ["file_list", interaction.file_list],
      ]);
      const evaluationRequirements = linesFromEntries([
        ["Deliverables or final states", required],
        ["Artifacts or state evidence", expectedArtifacts],
        ["Structured format", output.schema],
        ["Constraints", output.constraints],
        ["Checks", evaluation.checks],
        ["Pass standard", evaluation.pass_criteria || item.rubric],
        ["Partial-credit standard", evaluation.partial_criteria],
        ["Failure standard", evaluation.fail_criteria],
      ]);
      const evaluationMetric = linesFromEntries([
        ["Method", evaluation.method || (item.scoring || {}).method],
        ["Score range", evaluation.score_range],
        ["Score levels", evaluation.score_levels || taskAgentScoring.levels],
        ["Pairwise preference", evaluation.preference_criteria],
      ]);
      const evaluatorProcess = objectWithValues([
        ["setup", execution.setup || env.setup_commands],
        ["run", execution.run],
        ["evaluate", execution.evaluate || env.test_command],
        ["test_command", env.test_command],
        ["artifact_collection", artifactCollection],
      ]);
      const hiddenRefSummary = objectWithout(hiddenRefs, ["files"]);
      const privateEvaluatorMaterials = objectWithValues([
        ["hidden_references", hiddenRefSummary],
        ["hidden_files", hiddenFiles],
      ]);
      const modelVisibleResources = objectWithValues([
        ["files", visibleFiles],
        ["assets", visibleInputs.assets || visibleInputs.resources || multimodal.assets],
        ["multimodal_content", multimodal.content],
        ["session_resources", visibleInputs.session],
      ]);
      const repositoryContext = objectWithValues([
        ["workspace", env.workspace],
      ]);
      const observationActionSpace = objectWithValues([
        ["environment_type", env.type || envRequirements.type],
        ["observation_channels", env.observation_channels || envRequirements.observation_channels],
        ["action_channels", env.action_channels || envRequirements.action_channels],
        ["available_tools", env.tools],
        ["required_tools", trajectoryRequirements.required_tools],
      ]);
      const evaluationEnvironment = objectWithValues([
        ["type", env.type || envRequirements.type],
        ["operating_system", env.os || envRequirements.os],
        ["image", env.image || envRequirements.image],
        ["pull_image", env.pull_image],
        ["image_selection", env.image_selection],
        ["image_build", env.image_build || envRequirements.image_build],
        ["vm", env.vm || envRequirements.vm],
        ["vm_materialization", env.vm_materialization],
        ["vm_provisioning", env.vm_provisioning || envRequirements.vm_provisioning],
        ["requires_vm", env.requires_vm || envRequirements.requires_vm],
        ["requires_gui", env.requires_gui || envRequirements.requires_gui],
        ["setup_commands", env.setup_commands],
      ]);
      const environmentTools = objectWithValues([
        ["tools", env.tools],
        ["tool_schemas", env.tool_schemas],
        ["required_software", env.required_software || envRequirements.required_software],
        ["installed_software", env.installed_software || envRequirements.installed_software],
        ["runtime_versions", env.runtime_versions || envRequirements.runtime_versions],
        ["desktop_bridge_url", env.bridge_url],
        ["vm_provider_url", env.vm_provider_url],
      ]);
      const environmentState = objectWithValues([
        ["workspace", env.workspace],
        ["session", env.session],
        ["initial_session", initial.session],
        ["initial_vm", initial.vm],
        ["initial_notes", initial.notes],
      ]);
      const environmentConstraints = objectWithValues([
        ["network", env.network || envRequirements.network],
        ["resource_limits", env.resource_limits || envRequirements.resource_limits],
        ["max_steps", env.max_steps || execution.max_steps],
        ["timeout", env.timeout || execution.timeout_s],
        ["forbidden_shortcuts", trajectoryRequirements.forbidden_shortcuts],
      ]);
      const referenceAnswer = objectWithValues([
        ["expected_text", item.expected_text],
        ["choices", item.choices],
        ["reference_metadata", referenceMetadata(metadata)],
        ["reference_artifacts", hiddenRefs.reference_artifacts],
        ["reference_files", referenceFiles],
      ]);
      return [
        {
          title: "1. Source and construction metadata",
          note: "Task source, construction mode, and high-level benchmark metadata.",
          required: true,
          rows: [
            ["Quality flags", qualityFlagsForTask(row)],
            ["Title", itemContentSummary(item)],
            ["Dimension", dimensionLabel(item.dimension_id)],
            ["Capability target", capability],
            ["Task type", taskLabel(item.task_type)],
            ["Challenge effort", humanLabel(item.challenge_effort)],
            ["Source summary", sourceSummary(row)],
            ["Construction notes", firstRenderable(resourceProvenance.construction_notes, metadata.construction_notes, metadata.generation_notes)],
          ],
        },
        {
          title: "2. Target-visible prompt",
          note: "System and first user-facing task instructions supplied to the evaluated model.",
          required: true,
          rows: [
            ["Target system prompt", agent.system_prompt || metadata.target_system_prompt || metadata.system_prompt],
            ["Target user prompt", targetUserPrompt],
            ["Target initial user message addendum", initialAddendum],
          ],
        },
        {
          title: "3. Outputs, scoring, and evaluator materials",
          note: "What success means, how it is scored, and the private materials used by the evaluator.",
          rows: [
            ["Evaluation requirements", evaluationRequirements],
            ["Evaluation metric", evaluationMetric],
            ["Evaluator process", evaluatorProcess],
            ["Private evaluator materials", privateEvaluatorMaterials],
          ],
        },
        {
          title: "4. Model-visible context and resources",
          note: "Files, assets, repositories, media, and other resources visible at task start.",
          rows: [
            ["Model-visible resources", modelVisibleResources],
            ["Repository context", repositoryContext],
          ],
        },
        {
          title: "5. Tools, environment, and initial state",
          note: "Objective runtime facts about observation/action channels, tools, environment, initial state, and limits.",
          rows: [
            ["Observation and action space", observationActionSpace],
            ["Evaluation environment", evaluationEnvironment],
            ["Environment tools", environmentTools],
            ["Environment state", environmentState],
            ["Environment constraints", environmentConstraints],
          ],
        },
        {
          title: "6. Reference answer or solution",
          note: "Reference answer, final state, patch, or artifact when a standalone reference is recorded.",
          rows: [["Reference answer", referenceAnswer]],
        },
      ];
    }
    function appendTaskDefinition(body, row) {
      buildUnifiedTaskView(row).forEach(section => {
        const rows = (section.rows || []).filter(([, value]) => hasRenderableValue(value));
        if (!section.required && !rows.length) return;
        body.append(renderTaskSection(section.title, section.note, rows.length ? [renderRows(rows)] : []));
      });
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
      section.append(node("h3", {}, "Capability By Dimension"));
      section.append(table(["Dimension", "Pass / Total", "Score"], dimensionPerformanceRows()));
      section.append(node("h3", {}, "Capability By Task Type"));
      section.append(table(["Task Type", "Pass / Total", "Score"], taskTypePerformanceRows()));
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
      const recommendations = (pkg.report && pkg.report.recommendations) || [];
      if (recommendations.length) {
        section.append(table(["Recommendation"], recommendations.map(recommendation => [recommendation])));
      }
    }
    function fillSelect(id, values, labelFn = humanLabel) {
      const sel = qs(id);
      values.forEach(value => sel.append(node("option", {value}, labelFn(value))));
    }
    const explorerRows = taskRows.flatMap(row => {
      const itemRecords = resultRecordsByItem.get(row.item.id) || [];
      if (!itemRecords.length) return [{row, record: null, anchor: true}];
      return itemRecords.map((record, index) => ({row, record, anchor: index === 0}));
    });
    function explorerSearchText(entry) {
      const record = entry.record || {};
      return [
        entry.row.search,
        record.target_id,
        record.judge_reasoning,
        record.error,
        record.raw_response,
        (record.risks || []).join(" "),
      ].join(" ").toLowerCase();
    }
    function explorerTarget(entry) {
      return entry.record ? entry.record.target_id : "not_run";
    }
    function explorerSeverity(entry) {
      return entry.record ? entry.record.severity : entry.row.status.label;
    }
    function renderExplorer() {
      const section = qs("explorer");
      section.innerHTML = `<h2>Item Explorer</h2>
        <div class="filters">
          <input id="filter-search" placeholder="Search task, file, output, model result">
          <select id="filter-target"><option value="">All targets</option></select>
          <select id="filter-dimension"><option value="">All dimensions</option></select>
          <select id="filter-task"><option value="">All task types</option></select>
          <select id="filter-severity"><option value="">All outcomes</option></select>
        </div>
        <div id="item-list"></div>`;
      fillSelect(
        "filter-target",
        [...new Set(explorerRows.map(explorerTarget).filter(Boolean))].sort(),
        value => value === "not_run" ? "Not run" : humanLabel(value),
      );
      fillSelect(
        "filter-dimension",
        [...new Set(explorerRows.map(entry => entry.row.item.dimension_id).filter(Boolean))].sort(),
        dimensionLabel,
      );
      fillSelect(
        "filter-task",
        [...new Set(explorerRows.map(entry => entry.row.item.task_type).filter(Boolean))].sort(),
        taskLabel,
      );
      fillSelect(
        "filter-severity",
        [...new Set(explorerRows.map(explorerSeverity).filter(Boolean))].sort(),
        humanLabel,
      );
      ["filter-search", "filter-target", "filter-dimension", "filter-task", "filter-severity"].forEach(id => qs(id).addEventListener("input", applyFilters));
      applyFilters();
    }
    function renderRecord(entry) {
      const {row, record, anchor} = entry;
      const itemData = row.item;
      const item = node("details", {class: "item"});
      if (anchor) item.id = taskAnchorId(itemData.id);
      item.setAttribute("data-target", explorerTarget(entry));
      item.setAttribute("data-dimension", itemData.dimension_id || "");
      item.setAttribute("data-task", itemData.task_type || "");
      item.setAttribute("data-severity", explorerSeverity(entry));
      item.setAttribute("data-search", explorerSearchText(entry));
      const summary = node("summary");
      const left = node("div");
      left.append(node("strong", {}, record ? itemRunTitle(record) : itemDesignTitle(itemData)));
      left.append(node("div", {class: "small"}, `${taskLabel(itemData.task_type)} | ${humanLabel(itemData.challenge_effort)} | ${itemSourceLabel(record || itemData)}`));
      const right = record
        ? node("div", {class: `tone-${scoreTone(record.score)}`}, `${record.score_label} ${record.severity}`)
        : node("span", {class: `status-pill ${row.status.cls}`}, row.status.label);
      summary.append(left, right);
      item.append(summary);
      const body = node("div", {class: "item-body"});
      appendTaskDefinition(body, row);

      const resultSection = node("div", {class: "task-section"});
      resultSection.append(node("h3", {}, "Evaluation result"));
      if (record) {
        resultSection.append(renderRows([
          ["Target", humanLabel(record.target_id)],
          ["Score", record.score_label],
          ["Outcome", humanLabel(record.severity)],
          ["Latency", record.latency_ms === null || record.latency_ms === undefined ? "-" : `${record.latency_ms} ms`],
          ["Error", displayText(record.error || "-")],
        ]));
        resultSection.append(node("h3", {}, "Judge reasoning"));
        resultSection.append(markdownNode(record.judge_reasoning || record.error || "-"));
      } else {
        resultSection.append(node("p", {class: "empty"}, "This task has not been executed against a target model."));
      }
      body.append(resultSection);

      if (record && record.agent_trace) {
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
      if (record && record.raw_response) {
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
      const filtered = explorerRows.filter(entry =>
        (!search || explorerSearchText(entry).includes(search)) &&
        (!target || explorerTarget(entry) === target) &&
        (!dimension || entry.row.item.dimension_id === dimension) &&
        (!task || entry.row.item.task_type === task) &&
        (!severity || explorerSeverity(entry) === severity)
      );
      if (!filtered.length) {
        list.append(node("p", {class: "empty"}, "No matching items."));
        return;
      }
      filtered.forEach(entry => list.append(renderRecord(entry)));
    }
    function renderQc() {
      const section = qs("qc");
      section.innerHTML = "<h2>Task Composition and QC</h2>";
      const qc = pkg.qc_report || {};
      const totalItems = diag.generated_items ?? (pkg.dataset.items || []).length;
      const usedItems = diag.used_items ?? (pkg.dataset.items || []).length;
      const averageQcIssues = (qc.issues || []).length / Math.max(1, totalItems);
      const averageQcIssueTone = averageQcIssues === 0 ? "good" : averageQcIssues <= 0.25 ? "warn" : "bad";
      const grid = node("div", {class: "grid cols-3"});
      grid.append(stat("Generated / QC passed", `${totalItems}/${usedItems}`));
      grid.append(stat("Sourced / QC passed", `${diag.source_backed_items}/${usedItems}`));
      grid.append(stat("Average QC issues", averageQcIssues.toFixed(2), averageQcIssueTone));
      section.append(grid);
      const challengeEffortRows = Object.entries(diag.challenge_effort_counts || {})
        .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
        .map(([effort, count]) => [bucketLabel(`challenge_effort:${effort}`), count]);
      if (challengeEffortRows.length) {
        section.append(node("h3", {}, "Challenge Effort Distribution"));
        section.append(compositionTable([], challengeEffortRows));
      }

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
      const judgeRows = [
        ["Planned LLM-judged items", diag.judge.planned_llm_judged_items],
        ["Planned deterministic/rule-scored items", diag.judge.planned_deterministic_items],
        ["Executed results", diag.judge.executed_results],
        ["Results with judge/evaluator reasoning", diag.judge.results_with_judge_reasoning],
        ["Results without judge/evaluator reasoning", diag.judge.results_without_judge_reasoning],
      ];
      if (diag.judge.double_pass_enabled) {
        judgeRows.push(["Double-pass instability flags", diag.judge.instability_flags]);
      }
      section.append(table(["Metric", "Value"], judgeRows));
    }
    renderOverview();
    renderCapability();
    renderDiagnostics();
    renderExplorer();
    renderQc();
  </script>
</body>
</html>
"""
