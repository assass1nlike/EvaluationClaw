"""HTML template for the human-facing generated-task browser."""

HTML_TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EvaluationClaw Task Browser</title>
  <style>
    :root {
      --ink: #17212b;
      --muted: #657384;
      --line: #dbe2e8;
      --surface: #ffffff;
      --surface-alt: #f4f7f9;
      --page: #edf1f3;
      --accent: #126782;
      --accent-soft: #dff1f5;
      --warm: #a6512f;
      --warm-soft: #f8e9df;
      --good: #2e7655;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--page);
      font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
    }
    .page { max-width: 1240px; margin: 0 auto; padding: 32px 22px 64px; }
    header {
      padding: 28px 30px;
      color: #fff;
      background: linear-gradient(118deg, #173e50, #126782 58%, #a6512f);
      border-radius: 10px;
      box-shadow: 0 12px 30px rgba(25, 49, 63, .16);
    }
    h1, h2, h3, p { margin: 0; }
    h1 { font-size: clamp(25px, 3vw, 38px); line-height: 1.15; letter-spacing: 0; }
    .objective { margin-top: 10px; max-width: 940px; color: #eaf6f8; white-space: pre-wrap; }
    .stats { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 20px; }
    .stat { padding: 6px 11px; color: #fff; background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.25); border-radius: 999px; }
    .toolbar {
      display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
      margin: 24px 0 18px; padding: 14px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
      position: sticky; top: 12px; z-index: 2; box-shadow: 0 5px 18px rgba(27, 46, 58, .07);
    }
    input[type="search"], select {
      min-height: 38px; padding: 7px 11px; color: var(--ink); background: #fff; border: 1px solid #bfcbd3; border-radius: 5px;
      font: inherit;
    }
    input[type="search"] { flex: 1 1 260px; min-width: 180px; }
    label.check { display: inline-flex; gap: 7px; align-items: center; color: var(--muted); white-space: nowrap; }
    .count { margin-left: auto; color: var(--muted); font-size: 13px; }
    .task-list { display: grid; gap: 18px; }
    .task {
      overflow: hidden; background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
      box-shadow: 0 7px 18px rgba(27, 46, 58, .06);
    }
    .task.hidden { display: none; }
    .task-head { padding: 20px 24px 17px; border-bottom: 1px solid var(--line); }
    .eyebrow { display: flex; flex-wrap: wrap; gap: 7px; align-items: center; margin-bottom: 8px; color: var(--muted); font-size: 12px; }
    .pill { display: inline-block; padding: 2px 8px; color: var(--accent); background: var(--accent-soft); border-radius: 999px; font-weight: 650; }
    .pill.warm { color: var(--warm); background: var(--warm-soft); }
    .task h2 { font-size: 22px; line-height: 1.3; letter-spacing: 0; }
    .summary { margin-top: 8px; color: var(--muted); }
    .task-body { display: grid; gap: 18px; padding: 21px 24px 24px; }
    .section { min-width: 0; }
    .section-title { margin-bottom: 8px; color: #315160; font-size: 13px; font-weight: 750; text-transform: uppercase; letter-spacing: .04em; }
    .description { white-space: pre-wrap; }
    .prompt { padding: 14px 16px; color: #1c2c35; background: #f7fafb; border-left: 4px solid var(--accent); border-radius: 4px; white-space: pre-wrap; overflow-wrap: anywhere; }
    .choices { display: grid; gap: 8px; }
    .choice { display: grid; grid-template-columns: 28px 1fr auto; gap: 10px; align-items: start; padding: 10px 12px; border: 1px solid var(--line); border-radius: 5px; }
    .choice-id { color: var(--accent); font-weight: 750; }
    .answer-mark { display: none; color: var(--good); font-size: 12px; font-weight: 700; }
    .show-answers .answer-mark { display: block; }
    .asset-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
    .asset { overflow: hidden; border: 1px solid var(--line); border-radius: 5px; background: var(--surface-alt); }
    .asset img { display: block; width: 100%; max-height: 230px; object-fit: contain; background: #e8edf0; }
    .asset-path { padding: 8px 10px; color: var(--muted); font: 12px/1.4 ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap: anywhere; }
    details { border-top: 1px solid var(--line); padding-top: 12px; }
    summary { cursor: pointer; color: var(--accent); font-weight: 700; }
    .details-body { display: grid; gap: 15px; padding-top: 13px; }
    .reference { padding: 13px 15px; background: #fff9f4; border: 1px solid #f0d8c5; border-radius: 5px; white-space: pre-wrap; overflow-wrap: anywhere; }
    .kv { display: grid; grid-template-columns: minmax(120px, 190px) 1fr; border: 1px solid var(--line); border-bottom: 0; }
    .kv > * { margin: 0; padding: 8px 10px; border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
    .kv dt { color: var(--muted); background: var(--surface-alt); font-size: 13px; }
    .kv dd { white-space: pre-wrap; }
    pre.json { margin: 0; padding: 12px; max-height: 360px; overflow: auto; color: #243640; background: #f5f8f9; border: 1px solid var(--line); border-radius: 5px; font: 12px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
    a { color: var(--accent); }
    .empty { padding: 32px; color: var(--muted); text-align: center; background: var(--surface); border: 1px dashed #b9c6ce; border-radius: 8px; }
    @media (max-width: 650px) {
      .page { padding: 14px 10px 40px; }
      header { padding: 22px 18px; }
      .toolbar { position: static; }
      .count { width: 100%; margin-left: 0; }
      .task-head, .task-body { padding-left: 16px; padding-right: 16px; }
      .kv { grid-template-columns: 1fr; }
      .kv dt { border-bottom: 0; padding-bottom: 2px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <header>
      <h1 id="page-title">Task Browser</h1>
      <p id="objective" class="objective"></p>
      <div id="stats" class="stats"></div>
    </header>
    <div class="toolbar">
      <input id="search" type="search" placeholder="Search tasks, prompts, or tags..." aria-label="Search tasks">
      <select id="type-filter" aria-label="Filter by task type"><option value="">All task types</option></select>
      <select id="dimension-filter" aria-label="Filter by dimension"><option value="">All dimensions</option></select>
      <label class="check"><input id="show-answers" type="checkbox"> Show reference answers</label>
      <span id="count" class="count"></span>
    </div>
    <main id="task-list" class="task-list"></main>
  </div>
  <script>
    const DATA = __PAYLOAD__;
    const typeLabels = {choice: "Choice", fill_blank: "Fill in the blank", generation: "Generation", multi_turn: "Multi-turn", agent: "Agent"};
    const $ = (selector) => document.querySelector(selector);
    const make = (tag, className, text) => {
      const value = document.createElement(tag);
      if (className) value.className = className;
      if (text !== undefined && text !== null) value.textContent = String(text);
      return value;
    };
    const nonempty = (value) => value !== null && value !== undefined && String(value).trim() !== "";
    const jsonText = (value) => JSON.stringify(value, null, 2);
    function addSection(parent, title, content) {
      if (!content) return;
      const section = make("section", "section");
      section.append(make("div", "section-title", title), content);
      parent.append(section);
    }
    function textSection(parent, title, value, className) {
      if (!nonempty(value)) return;
      addSection(parent, title, make("div", className || "description", value));
    }
    function objectSection(parent, title, value) {
      if (!value || typeof value !== "object" || !Object.keys(value).length) return;
      const pre = make("pre", "json", jsonText(value));
      addSection(parent, title, pre);
    }
    function renderAssets(parent, assets, taskType) {
      if (!Array.isArray(assets) || !assets.length) return;
      const grid = make("div", "asset-grid");
      assets.forEach((asset, index) => {
        const path = String(asset && asset.path || "");
        const label = taskType === "agent"
          ? path.split(/[\\/]/).pop()
          : `Image ${index + 1}`;
        const box = make("div", "asset");
        if (/\.(?:png|jpe?g|gif|webp|bmp|svg)(?:[?#].*)?$/i.test(path)) {
          const image = document.createElement("img");
          image.src = path;
          image.alt = label;
          image.addEventListener("error", () => image.remove());
          box.append(image);
        }
        box.append(make("div", "asset-path", label || "(unnamed asset)"));
        grid.append(box);
      });
      addSection(parent, "Assets", grid);
    }
    function renderChoices(parent, item) {
      if (!Array.isArray(item.choices) || !item.choices.length) return;
      const correct = new Set(item.correct_choice_ids || []);
      const list = make("div", "choices");
      item.choices.forEach((choice, index) => {
        const row = make("div", "choice");
        row.append(make("span", "choice-id", choice.id || String.fromCharCode(65 + index)));
        row.append(make("span", "choice-text", choice.text || ""));
        row.append(make("span", "answer-mark", correct.has(choice.id) ? "Correct" : ""));
        list.append(row);
      });
      addSection(parent, "Choices", list);
    }
    function renderEnvironment(parent, environment) {
      if (!environment || typeof environment !== "object" || !Object.keys(environment).length) return;
      const selected = {};
      ["type", "image", "workdir", "network", "setup_commands", "test_command", "max_steps", "timeout", "visible_files", "runtime_files", "session", "browser", "vm"].forEach((key) => {
        if (nonempty(environment[key]) || (environment[key] && typeof environment[key] === "object" && Object.keys(environment[key]).length)) selected[key] = environment[key];
      });
      objectSection(parent, "Execution environment", selected);
    }
    function renderReference(parent, item) {
      const body = make("div", "details-body");
      if (item.task_type === "choice" && (item.correct_choice_ids || []).length) {
        textSection(body, "Correct choice IDs", item.correct_choice_ids.join(", "), "reference");
      }
      textSection(body, "Expected answer", (item.expected_texts || []).join("\n"), "reference");
      textSection(body, "Rubric", item.rubric, "reference");
      objectSection(body, "Scoring", item.scoring);
      objectSection(body, "Output contract", item.output_contract);
      objectSection(body, "Judge tools", item.judge_tools);
      if (!body.childElementCount) return;
      const details = document.createElement("details");
      details.append(make("summary", "Reference and scoring"), body);
      parent.append(details);
    }
    function renderTask(item) {
      const card = make("article", "task");
      card.dataset.type = item.task_type;
      card.dataset.dimension = item.dimension_id;
      const head = make("div", "task-head");
      const eyebrow = make("div", "eyebrow");
      eyebrow.append(make("span", "pill", `Task ${item.number}`), make("span", "pill", typeLabels[item.task_type] || item.task_type));
      if (nonempty(item.dimension_name)) eyebrow.append(make("span", "pill warm", item.dimension_name));
      if (nonempty(item.challenge_effort)) eyebrow.append(make("span", "", item.challenge_effort));
      if (item.source && nonempty(item.source.kind)) eyebrow.append(make("span", "", `Source: ${item.source.kind}`));
      head.append(eyebrow, make("h2", "", item.title || item.id));
      if (nonempty(item.content_summary)) head.append(make("p", "summary", item.content_summary));
      const body = make("div", "task-body");
      textSection(body, "Description", item.description);
      textSection(body, "Prompt", item.prompt, "prompt");
      renderAssets(body, item.assets, item.task_type);
      renderChoices(body, item);
      textSection(body, "System prompt", item.system_prompt, "prompt");
      objectSection(body, "Interaction", item.interaction);
      renderEnvironment(body, item.environment);
      renderReference(body, item);
      if (item.source && (nonempty(item.source.uri) || nonempty(item.source.title) || nonempty(item.source.notes))) {
        const source = make("div", "reference");
        if (nonempty(item.source.title)) source.append(make("strong", "", item.source.title));
        if (nonempty(item.source.uri)) {
          const link = document.createElement("a");
          link.href = item.source.uri; link.target = "_blank"; link.rel = "noreferrer"; link.textContent = item.source.uri;
          source.append(document.createElement("br"), link);
        }
        if (nonempty(item.source.notes)) source.append(document.createElement("br"), make("span", "", item.source.notes));
        addSection(body, "Source", source);
      }
      if (Array.isArray(item.tags) && item.tags.length) textSection(body, "Tags", item.tags.join(", "));
      const id = make("div", "", `Task ID: ${item.id}`);
      id.style.color = "var(--muted)"; id.style.fontSize = "12px"; id.style.fontFamily = "ui-monospace, SFMono-Regular, Consolas, monospace";
      body.append(id);
      card.append(head, body);
      return card;
    }
    const tasks = Array.isArray(DATA.tasks) ? DATA.tasks : [];
    $("#page-title").textContent = DATA.title ? `Task Browser: ${DATA.title}` : "Task Browser";
    $("#objective").textContent = DATA.objective || "";
    const types = [...new Set(tasks.map((task) => task.task_type).filter(Boolean))].sort();
    const dimensions = [...new Map(tasks.map((task) => [task.dimension_id, task.dimension_name])).entries()].sort((a, b) => String(a[1]).localeCompare(String(b[1])));
    types.forEach((type) => {
      const option = make("option", "", typeLabels[type] || type);
      option.value = type;
      $("#type-filter").append(option);
    });
    dimensions.forEach(([id, name]) => { const option = make("option", "", name || id); option.value = id; $("#dimension-filter").append(option); });
    const stats = $("#stats");
    stats.append(make("span", "stat", `${tasks.length} tasks`), make("span", "stat", `${types.length} task types`), make("span", "stat", `${dimensions.length} dimensions`));
    const list = $("#task-list");
    tasks.forEach((task) => list.append(renderTask(task)));
    if (!tasks.length) list.append(make("div", "empty", "No generated tasks."));
    const applyFilters = () => {
      const query = $("#search").value.trim().toLowerCase();
      const type = $("#type-filter").value;
      const dimension = $("#dimension-filter").value;
      let visible = 0;
      [...list.querySelectorAll(".task")].forEach((card, index) => {
        const task = tasks[index];
        const haystack = [task.id, task.title, task.description, task.prompt, task.content_summary, ...(task.tags || [])].join(" ").toLowerCase();
        const matches = (!query || haystack.includes(query)) && (!type || task.task_type === type) && (!dimension || task.dimension_id === dimension);
        card.classList.toggle("hidden", !matches); if (matches) visible += 1;
      });
      $("#count").textContent = `${visible} of ${tasks.length} shown`;
      const empty = $("#empty-filter");
      if (!visible && tasks.length) {
        if (!empty) { const message = make("div", "empty", "No matching tasks."); message.id = "empty-filter"; list.append(message); }
      } else { empty?.remove(); }
    };
    $("#search").addEventListener("input", applyFilters);
    ["#type-filter", "#dimension-filter"].forEach((selector) => $(selector).addEventListener("change", applyFilters));
    $("#show-answers").addEventListener("change", (event) => document.body.classList.toggle("show-answers", event.target.checked));
    applyFilters();
  </script>
</body>
</html>
'''

__all__ = ["HTML_TEMPLATE"]
