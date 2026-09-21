"""Display merged evaluation progress without changing running experiments."""
import json
from datetime import datetime
from pathlib import Path

outputs = Path(__file__).resolve().parent / "outputs"
for model, batch in [("GPT", "gpt_resume_0922"), ("Qwen", "qwen_resume_0921")]:
    progress = json.loads((outputs / batch / "combined/progress.json").read_text())
    finished, active, total = (progress[key] for key in ("finished", "active", "total"))
    updated = datetime.fromtimestamp(progress["time"]).astimezone().strftime("%m-%d %H:%M:%S")
    print(f"{model} | 已结束 {finished}/{total} | 运行 {active} | 排队 {total - finished - active}")
    print(f"结果分类：{progress['outcomes']}")
    print(f"更新时间：{updated}\n")
