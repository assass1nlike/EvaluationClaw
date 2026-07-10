## 对比样例 1：OSWorld office artifact editing

### 原 OSWorld 任务

- 来源：`evaluation_examples/examples/libreoffice_impress/04578141-1d42-4146-b9cf-6fab4ce5fd74.json`
- 应用：LibreOffice Impress
- 环境：隔离的 Linux 桌面 VM，预装 LibreOffice Impress；任务开始时系统下载并打开待编辑的 PPTX 文件。
- 指令：打开桌面上的 `45_2.pptx`，将第 1 页三个文本框的文字颜色按从上到下顺序改成 yellow、red、green，颜色必须精确，不能用近似颜色。
- 初始状态：下载并打开一个 PPTX 文件。
- 输出：修改后的同一个 PPTX 文件。
- 评估：保存文件后，用 `compare_pptx_files` 对比两个 golden PPTX 之一；评估选项忽略部分 shape/run 差异，但检查目标文本颜色。

### EvalClaw 自动生成任务

- 当时输入给 EvalClaw 的需求描述：构建一个面向日常桌面软件操作的 agent benchmark。评估应衡量 AI agent 是否能使用 GUI 应用检查给定文件或应用状态，通过桌面界面完成指定编辑，保存结果工件或状态变化，并在隔离的 VM-backed 桌面环境中通过私有确定性检查。
- 环境：隔离的图形桌面 VM，预装 LibreOffice Calc，agent 通过截图、鼠标、键盘和 desktop bridge 操作表格文件。
- 指令：用桌面 spreadsheet 打开 `Desktop/osworld_orders.csv`，新增 Profit 列，计算 revenue-cost，按 region 汇总 total profit，导出 `Desktop/profit_summary.csv` 并运行 bridge evaluation。
- 输入：
  - `Desktop/osworld_orders.csv`
  - `Desktop/office_task_brief.md`
- Expected artifacts：
  - `Desktop/profit_summary.csv`
- Hidden evaluator：
  - `hidden/evaluate_office_artifact.py`
  - 检查导出文件存在、region 汇总值 `north=70`、`south=35`、`west=24`，以及 GUI spreadsheet trace。

### 对比结论

两者都测试“桌面 office 应用中修改/生成可检查文件”的能力。OSWorld 原题更贴近真实 PPT 编辑；EvalClaw 生成题把输出契约和隐藏检查写成标准化 agent task package，便于 runner 自动部署、收集 artifact 和审计 GUI trace。

## 对比样例 2：OSWorld creative image editing

### 原 OSWorld 任务

- 来源：`evaluation_examples/examples/gimp/2a729ded-3296-423d-aec4-7dd55ed5fbb3.json`
- 应用：GIMP
- 环境：隔离的 Linux 桌面 VM，预装 GIMP；任务开始时系统下载图片并用 GIMP 打开。
- 指令：打开 `dog_with_background.png`，把图片背景变透明。
- 初始状态：下载图片并用 GIMP 打开。
- 输出：导出 `dog_without_background.png`。
- 评估：执行导出流程后，用 `check_structure_sim` 将 agent 输出图与 hidden/golden `dog_cutout_gold.png` 做结构相似度比较。

### EvalClaw 自动生成任务

- 当时输入给 EvalClaw 的需求描述：构建一个面向日常桌面软件操作的 agent benchmark。评估应衡量 AI agent 是否能使用 GUI 应用检查给定文件或应用状态，通过桌面界面完成指定编辑，保存结果工件或状态变化，并在隔离的 VM-backed 桌面环境中通过私有确定性检查。
- 环境：隔离的图形桌面 VM，预装 GIMP 或等价图像编辑器，agent 通过 GUI 编辑并导出图片。
- 指令：用桌面 image editor 打开 `Desktop/source.ppm`，把所有红色 marker pixels `(255,0,0)` 转成蓝色 `(0,0,255)`，灰色背景保持不变，导出 `Desktop/edited_marker.ppm` 并运行 bridge evaluation。
- 输入：
  - `Desktop/source.ppm`
  - `Desktop/image_edit_brief.md`
- Expected artifacts：
  - `Desktop/edited_marker.ppm`
- Hidden evaluator：
  - `hidden/evaluate_image_artifact.py`
  - 解析 PPM 像素，检查导出可读、6 个红色 marker 都变蓝、灰色背景未破坏、没有残留红色像素。

### 对比结论

两者都测试 GUI 图像编辑与导出。OSWorld 原题更自然、更接近用户真实图片编辑；EvalClaw 生成题更适合自动化回归测试，因为 fixture 小、离线、隐藏 evaluator 完全确定，能直接区分“真的编辑了图像”和“只给文字说明”。

## 对比样例 3：ALE robotics artifact reconstruction

### 原 ALE 任务

- 来源：`tasks/engineering/abb_irb6700_asset_to_urdf_instance_1/task_card.json`
- 标题：ABB IRB6700 Asset To URDF
- 环境：Linux VM
- 任务：从 staged mesh assets 和 metadata 重建 ABB IRB6700 robot URDF。
- Visible inputs：
  - `input/meshes/`
  - `metadata/link_manifest.json`
  - `metadata/joint_manifest.json`
  - `metadata/kinematic_tree_hint.json`
  - `metadata/joint_limits.csv`
  - `metadata/mimic_rules.json`
  - `task_brief.md`
- 输出：`base/output/submission.urdf`
- 评估：
  - hard gates：输出目录只能有一个 `submission.urdf`，文件必须是合法 XML/URDF。
  - semantic checks：hidden gold tables 验证 link set、joint set、mesh filenames、parent-child structure、joint origins、axes、limits、mimic behavior。
  - pose checks：hidden sample joint configurations 对 candidate URDF 和 gold URDF 做 forward kinematics 对比。

### EvalClaw 自动生成任务

- 当时输入给 EvalClaw 的需求描述：构建一个面向专业工程工作的 agent benchmark。评估应衡量 AI agent 是否能检查一组工程资产和结构化元数据，理解其中的关系和约束，产出带验证证据的完整可执行工件，记录 provenance，并在隔离环境中通过私有确定性检查。
- 环境：隔离的专业工程桌面/VM 环境，提供工程资产、结构化元数据、输出目录和隐藏评估器。
- 指令：使用 `Desktop/robot/input` 下的 staged robotics metadata 重建合法 robot model。输出且只输出：
  - `Desktop/robot/output/submission.urdf`
  - `Desktop/robot/output/kinematic_report.json`
- Visible inputs：
  - `Desktop/robot/input/task_brief.md`
  - `Desktop/robot/input/metadata/link_manifest.json`
  - `Desktop/robot/input/metadata/joint_manifest.json`
  - `Desktop/robot/input/metadata/joint_limits.csv`
  - `Desktop/robot/input/metadata/mimic_rules.json`
  - `Desktop/robot/input/meshes/*.stl`
- Hidden evaluator：
  - `hidden/evaluate_artifact.py`
  - 解析 URDF XML，检查 required link set、joint set、joint limit elements、mesh references、kinematic report provenance。
- Scoring checks：
  - `required_outputs`
  - `link_joint_semantics`
  - `limits_and_meshes`
  - `provenance_report`

### 对比结论

EvalClaw 生成题已经覆盖 ALE robotics 题的核心结构：visible metadata + mesh assets、单一 URDF 输出、hidden semantic checks、provenance/kinematic report。原 ALE 任务更大、更专业，包含真实 ABB 资产和 FK pose checks；EvalClaw 版本更轻量、开源工具友好，适合作为自动生成的同类 benchmark fixture。框架已具备把自然语言“URDF/robotics reconstruction”需求落到标准化可执行任务包的能力。

## 对比样例 4：ALE bioinformatics executable pipeline

### 原 ALE 任务

- 来源：`tasks/life_sciences/gene_expression_differential_analysis_functional_enrichment_analysis_1/task_card.json`
- 标题：BRCA Differential Expression And KEGG Enrichment Analysis
- 环境：Ubuntu VM
- 软件：Python, pydeseq2, gseapy
- 任务：读取 BRCA count matrix、sample metadata、analysis spec、output contract、gene-id map、enrichment config，使用 `~ batch + condition` 设计公式比较 tumor vs normal，分类上调/下调/不显著基因，并分别做 KEGG enrichment。
- 输出：
  - `BRCA_deseq2_results.tsv`
  - `BRCA_upregulated_genes_kegg_enrichment.tsv`
  - `BRCA_downregulated_genes_kegg_enrichment.tsv`
- 评估：
  - hard-fail missing files、missing columns、domain-invalid numeric fields、duplicate/unexpected gene ids、错误 significant labels、错误 gene-symbol assignment、错误 KEGG library labels。
  - weighted scoring：DEG directions 0.45、log2FC closeness 0.20、其它 DESeq2 numeric columns 0.20、top KEGG terms 0.15；pass threshold 0.85。

### EvalClaw 自动生成任务

- 当时输入给 EvalClaw 的需求描述：构建一个面向专业生命科学数据分析的 agent benchmark。评估应衡量 AI agent 是否能检查 staged data tables 和 metadata，遵循 analysis contract，产出结构化结果表和 provenance record，并在隔离计算环境中通过针对 hidden reference outputs 的私有确定性检查。
- 环境：隔离的 Linux/Docker 计算环境，包含可见数据表、分析脚本入口、输出目录和隐藏测试。
- 指令：用 `counts.tsv`、`metadata.tsv`、`gene_map.tsv`、`analysis_spec.json`、`output_contract.json` 构建 compact differential-expression pipeline，比较 tumor vs normal，分类基因，输出 enrichment，并记录 workflow provenance。
- Visible inputs：
  - `counts.tsv`
  - `metadata.tsv`
  - `gene_map.tsv`
  - `analysis_spec.json`
  - `output_contract.json`
  - `analysis.py`
- Expected artifacts：
  - `output/DE_results.tsv`
  - `output/upregulated_enrichment.tsv`
  - `output/downregulated_enrichment.tsv`
  - `workflow_manifest.json`
- Hidden evaluator：
  - `tests.py`
  - 检查 output files 存在、DE 表列和行数、gene symbol 映射、上调/下调/不显著分类、log2FC 方向、enrichment overlap genes、manifest inputs。

### 对比结论

两者任务结构高度一致：visible biological dataset + analysis contract + exact output schema + hidden structured grading + provenance。原 ALE 任务使用真实工具链和更复杂统计指标；EvalClaw 生成题保留了完整评测骨架，并把任务压缩成可快速运行的 fixture，适合自动生成和批量扩展。若要追求原 ALE 的完整难度，可以把同一 task package 扩展为更大 count matrix、真实 pydeseq2/gseapy dependency 和更严格 numeric closeness。
