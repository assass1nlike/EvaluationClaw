English print views of the human-review interface. The layout, controls and rendering functions come from `evalclaw/reporting/human_judge_template.py`; the figure renderer translates labels and adjusts spacing for print. It does not connect to the review server or create reviewer sessions or votes.

The checked-in `examples.json` contains task/response excerpts from three existing review pairs, selected to illustrate multiple-choice, multi-turn and agent interfaces. Each paired alternative is a free-response task. Excerpt boundaries are explicit; no prompt, answer, reference or score is synthesized. The examples illustrate presentation, not measured human preferences or a representative quality estimate. A/B positions vary across figures and all preference controls remain unselected.

Regenerate from the repository root (Playwright with Chromium is needed only for figure generation):

```bash
.venv/bin/python paper/figures/human_judge/render.py
NODE_PATH=/path/to/node_modules node paper/figures/human_judge/render.cjs
```

Vector PDFs are included in the paper; PNGs provide full-resolution previews. To refresh the examples from the frozen local review export, run `prepare.py benchmark-output/human-judge/formal-20260922/comparisons.json` before rendering. The rendering itself is deterministic and makes no model calls. The checked-in examples allow regeneration without the local experiment directory.
