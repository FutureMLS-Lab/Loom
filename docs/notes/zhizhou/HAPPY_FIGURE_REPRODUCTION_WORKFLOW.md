# Happy Figure 科研绘图复现流程

本文记录如何从论文 PDF 出发，使用 `happy-figure-skill` 理解论文、生成受控
绘图 Prompt，再调用 Cursor `GenerateImage` 生成本目录中 MCD 论文的全部候选图。

## 复现目标

输入论文：

```text
/data/shared/zhizhousha/workspace/loom-project/loom-claude-paper/research-factory/.RUD/wacv3-modality-contrastive-decoding-removing-dominant-modality-bias-in-omnimoda/work/manuscript/main.pdf
```

原始 Figure 1：

```text
/data/shared/zhizhousha/workspace/loom-project/loom-claude-paper/research-factory/.RUD/wacv3-modality-contrastive-decoding-removing-dominant-modality-bias-in-omnimoda/work/manuscript/figures/teaser.png
```

当前产物目录：

```text
/data/shared/zhizhousha/workspace/loom-project/loom-zhongzhu/zhizhou-note/wacv3-mcd-figure1-happy-figure
```

复现的终止条件：

1. 论文内容和 Figure 1 拓扑已核对。
2. Skill 生成的 Prompt 不含未替换占位符。
3. 七张候选图全部生成并可解码。
4. 所有事实、数字、公式和箭头通过人工/多模态检查。
5. 输出目录的 `README.md` 能直接预览全部图片。

> `GenerateImage` 是非确定性生成工具。复现指重跑同一工作流、科学约束和
> 图类型，不保证得到逐像素相同的图片。

## 1. 环境和依赖

### 1.1 Skill 位置

源码：

```text
/data/shared/zhizhousha/workspace/loom-project/happy-figure-skill
```

Cursor 个人 Skill：

```text
~/.cursor/skills/happy-figure-skill
```

检查：

```bash
test -f ~/.cursor/skills/happy-figure-skill/SKILL.md
cursor-agent status
```

如果尚未安装，且目标不存在：

```bash
mkdir -p ~/.cursor/skills
test -e ~/.cursor/skills/happy-figure-skill || \
  ln -s /data/shared/zhizhousha/workspace/loom-project/happy-figure-skill \
  ~/.cursor/skills/happy-figure-skill
```

### 1.2 文档解析依赖

Python 包：

```bash
python3 -m pip install --user --upgrade \
  pdfplumber pypdf python-docx mammoth pypandoc-binary
```

当前安装还提供：

- Pandoc：`~/.local/bin/pandoc`
- Poppler `pdftotext`：`~/.local/bin/pdftotext`

检查：

```bash
pandoc --version
pdftotext -v
python3 -c "import pdfplumber, pypdf, docx, mammoth, pypandoc"
```

扫描版 PDF 的 OCR 不在当前提取脚本能力内。遇到扫描件时，应要求用户提供
OCR 文本，而不是假装已经解析。

## 2. 建立独立运行目录

不要默认覆盖现有结果。新 Agent 应建立单独的 rerun 目录：

```bash
OUTPUT_ROOT=/data/shared/zhizhousha/workspace/loom-project/loom-zhongzhu/zhizhou-note/wacv3-mcd-figure1-happy-figure
RUN_DIR="$OUTPUT_ROOT/rerun-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN_DIR"
```

如果用户明确要求更新当前版本，才写回 `OUTPUT_ROOT` 中现有文件名。

## 3. 用 Skill 提取和理解论文

先运行 Skill 自带提取器：

```bash
python3 ~/.cursor/skills/happy-figure-skill/scripts/extract_research_doc.py \
  /data/shared/zhizhousha/workspace/loom-project/loom-claude-paper/research-factory/.RUD/wacv3-modality-contrastive-decoding-removing-dominant-modality-bias-in-omnimoda/work/manuscript/main.pdf \
  --format json
```

本论文 PDF 使用带行号的会议排版，自动 section detection 不完整。因此还必须读取：

```text
work/manuscript/sections/00_abstract.tex
work/manuscript/sections/01_introduction.tex
work/manuscript/sections/03_method.tex
work/manuscript/sections/04_experiments.tex
work/manuscript/figures/teaser.png
work/manuscript/figures/main_results.png
```

已经整理好的理解结果：

```text
wacv3-mcd-figure1-happy-figure/paper-understanding.md
```

### 3.1 不可改变的科学事实

- Full context：image + audio + question。
- Visual-only context：image + question，不包含 audio。
- 两条分支使用同一个 frozen Qwen2.5-Omni-7B checkpoint。
- MCD 必须是 `ℓ_F − λℓ_V`，不能反转操作数。
- OmniBench pilot 是 task-balanced 40 examples。
- Figure 1 数字只能是：
  - `50.0% baseline`
  - `37.5% MCD at λ=1`
  - `1.78× CPU latency`
  - `No recovery`
- `No recovery` 不等于统计显著退化；paired CI 包含 0。
- λ=1 时修正 6 个 baseline errors，同时破坏 11 个 baseline-correct answers。
- λ sweep 是从同一对已保存 logits 离线计算，不能画成多次模型 forward。

出现以下任一情况必须拒绝结果并重生成：

- Audio 进入 visual-only branch。
- 公式变成 `ℓ_V − λℓ_F` 或其他 fusion/average。
- 新增训练、梯度、第三分支、额外数据集或虚构指标。
- 把 `No recovery` 表述成显著退化或已证明的普遍伤害。
- 任一真实数字写错。

## 4. 使用 Happy Figure Skill 生成 Prompt

调用方式：

```text
Use $happy-figure-skill explicitly.
```

Skill 只生成 Prompt，不生成图片。

### 4.1 Figure 1 三种视觉气质

完整 Prompt 已保存在：

```text
wacv3-mcd-figure1-happy-figure/prompts.md
```

包含：

1. Strict ICLR/WACV conference paper figure
2. Premium academic graphical abstract
3. Minimal flat vector schematic

如需从头重新生成 Prompt，让 Agent：

1. 读取论文和原 Figure 1。
2. 明确 CS/ML multimodal decoding 内容社区。
3. 使用双流 method + measured outcome 图类型。
4. 跳过风格确认，直接输出上述三种候选。
5. 每个 Prompt 内嵌 exact visible-text whitelist。
6. 禁止新增数据、分支、图例、CI、p-value 或显著性表达。

### 4.2 四种不同图类型

完整 Prompt 已保存在：

```text
wacv3-mcd-figure1-happy-figure/direction-prompts.md
```

包含：

1. Graphical abstract / paper main figure
2. Mechanism explanation
3. Multi-panel comparison
4. Technical roadmap

Prompt 生成时必须使用：

- `references/domain-masters.md` 的 CS/ML 母版。
- `references/figure-type-masters.md` 的对应图类型适配层。
- `references/language-strategy.md` 的 English paper label 策略。
- `references/prompt-quality-check.md` 做最终检查。

## 5. 调用 Cursor GenerateImage

用户必须明确请求生成图片后才能调用。

通用调用：

```text
GenerateImage(
  description=<从 prompts.md 或 direction-prompts.md 复制对应完整 Prompt>,
  filename="<仅文件名，不能包含目录>",
  aspect_ratio="16:9",
  reference_image_paths=[
    "/absolute/path/to/reference.png"
  ]
)
```

工具会返回 Cursor session assets 中的绝对路径。随后将该路径复制到
`RUN_DIR` 或用户指定目录。不要预先猜测 assets 路径。

### 5.1 三种 Figure 1 视觉气质

三次调用可以并行：

| Prompt | GenerateImage filename | 保存文件名 | 参考图 |
|---|---|---|---|
| `prompts.md` Variant 1 | `mcd-figure1-strict.png` | `figure1-strict.png` | 原 Figure 1 |
| `prompts.md` Variant 2 | `mcd-figure1-premium.png` | `figure1-premium.png` | 原 Figure 1 |
| `prompts.md` Variant 3 | `mcd-figure1-minimal.png` | `figure1-minimal.png` | 原 Figure 1 |

### 5.2 四种图类型

| Prompt | GenerateImage filename | 保存文件名 | 参考图 |
|---|---|---|---|
| Graphical abstract | `mcd-direction-graphical-abstract.png` | `direction-graphical-abstract.png` | 原 Figure 1 |
| Mechanism explanation | `mcd-direction-mechanism.png` | `direction-mechanism-explanation.png` | 原 Figure 1 |
| Multi-panel comparison | `mcd-direction-comparison.png` | `direction-multi-panel-comparison.png` | 无；只服从精确数值卡片 |
| Technical roadmap | `mcd-direction-roadmap-v2.png` | `direction-technical-roadmap.png` | 无；优先保证 protocol 拓扑 |

## 6. Technical roadmap 的强制修正

第一次 roadmap 生成漏掉了 paired-logit storage，使两条 forward 输出直接进入
λ sweep。该图被拒绝，没有保存为最终候选。

最终 roadmap 使用以下强化要求重生成。若 `direction-prompts.md` 的普通 Prompt
仍漏掉 storage，必须把下面约束追加到 `GenerateImage.description`：

```text
Use exactly five horizontal positions:
1. Task-balanced OmniBench subset with 40 examples and Image, Audio, Question,
   Options A-D.
2. Exactly two parallel frozen Qwen2.5-Omni-7B branches. Full branch receives
   image + audio + question + options A-D. Visual-only branch receives image +
   question + options A-D and no audio. Each emits four first-token option
   logits A | B | C | D.
3. Both branch vectors MUST enter one central card labeled
   "Store four logits per branch" BEFORE any lambda sweep. No branch may bypass
   this storage card.
4. Storage points to "Offline λ sweep" with exact
   "{0.25, 0.5, 1, 2}" and "Primary λ=1". No arrow returns to the model.
5. The sweep points to Exact option accuracy, Gain / loss,
   10,000 paired bootstrap resamples, and Two-sided paired exact test.
A separate timing line originates from the enclosing pair of model branches
and terminates at Sequential CPU latency.
Do not render numbered badges, result values, p-values, confidence intervals,
seconds, memory values, extra branches, or any text outside the whitelist.
```

Roadmap 验收重点：

- 必须存在 `Store four logits per branch`。
- Storage 必须位于两分支和 offline λ sweep 之间。
- λ sweep 不能回到模型。
- Timing connector 从两次 forward 的 enclosing group 出发，不能从统计模块出发。

## 7. 多面板比较图的数据锁

图片模型只允许生成等尺寸文字卡片，不允许自由绘制定量 chart。

必须逐字核对：

```text
Full input | 50.0%
Visual only | 30.0%
Audio only | 25.0%
Raw MCD λ=0.25 | 42.5%
Raw MCD λ=0.5 | 45.0%
Raw MCD λ=1 | 37.5%
Raw MCD λ=2 | 20.0%

λ=0.25 | 0/3
λ=0.5 | 3/5
λ=1 | 6/11
λ=2 | 4/16

Shuffled visual | 40.0%
VCD-style | 45.0%
Positive scaling | 50.0%

1.78× baseline
```

任一字符、百分号、小数位、λ、× 或 gain/loss 顺序错误时必须重生成。

## 8. 生成后审核

### 8.1 基础审核

对每张图片检查：

- 文件可解码，当前生成通常为 `1536 × 1024 RGB PNG`。
- 没有水印、Logo、随机文本或 Prompt 结构字段。
- 允许文字均来自对应 whitelist。
- 线条没有错误连接或被卡片遮挡。
- 图中文字在缩放后仍可读。

### 8.2 各图专项审核

**Figure 1 三风格**

- Strict：应最接近原始论文图逻辑。
- Premium：允许更强质感，但不能增加科学模块。
- Minimal：不能因精简而丢掉 no-audio 语义。

**Graphical abstract**

- 视觉主导只是假设，不能画成已证实的因果机制。
- 结果卡必须保持 `No recovery` 的窄结论。

**Mechanism explanation**

- 必须同时出现 6 corrected 和 11 broken。
- 必须明确 `Paired test not significant`。
- 最终解释只能是 useful visual evidence may also be removed。

**Multi-panel comparison**

- 逐项核对第 7 节全部数字。
- 禁止模型用条长、面积、颜色深浅额外编码数值。

**Technical roadmap**

- 使用第 6 节验收清单。

## 9. 保存和验证

将 GenerateImage 返回路径复制到运行目录，例如：

```bash
cp "<GenerateImage 返回的绝对路径>" \
  "$RUN_DIR/direction-mechanism-explanation.png"
```

验证：

```bash
identify "$RUN_DIR"/*.png

python3 - <<'PY'
from pathlib import Path
from PIL import Image

for path in sorted(Path("RUN_DIR_PLACEHOLDER").glob("*.png")):
    with Image.open(path) as image:
        image.verify()
        print(path.name, image.size, image.mode)
PY
```

将 `RUN_DIR_PLACEHOLDER` 替换为实际目录。不要把占位符直接执行。

## 10. 当前产物清单

输出目录：

```text
wacv3-mcd-figure1-happy-figure/
├── README.md
├── paper-understanding.md
├── prompts.md
├── direction-prompts.md
├── figure1-strict.png
├── figure1-premium.png
├── figure1-minimal.png
├── direction-graphical-abstract.png
├── direction-mechanism-explanation.png
├── direction-multi-panel-comparison.png
└── direction-technical-roadmap.png
```

`README.md` 必须包含全部图片的 Markdown 预览和简短已知限制。

## 11. 当前结果中的已知现象

- `figure1-strict.png`：三种原 Figure 1 重绘中科学约束最完整。
- `figure1-premium.png`：图像模型额外生成了编号徽章 `1–5`。
- `figure1-minimal.png`：visual-only 路径正确，但缺少显式
  `Image + question (no audio)` supporting label。
- `direction-graphical-abstract.png`：核心拓扑正确；部分 supporting label
  可能被模型省略。
- `direction-mechanism-explanation.png`：当前最适合解释论文负结果的候选。
- `direction-multi-panel-comparison.png`：当前全部数值和顺序核对正确。
- `direction-technical-roadmap.png`：使用修正版 Prompt，已包含 paired-logit
  storage 和离线 λ sweep。

## 12. 给后续 Agent 的执行指令

```text
先完整阅读 HAPPY_FIGURE_REPRODUCTION_WORKFLOW.md。
使用已安装的 $happy-figure-skill。
不要覆盖现有图片；新建 timestamped rerun 目录。
先复核论文和不可改变的科学事实，再从 prompts.md 与
direction-prompts.md 读取对应 Prompt。
调用 GenerateImage 后逐图检查文字、数字、公式和箭头。
任何科学事实错误都必须拒绝并重生成。
最后更新 rerun 目录中的 README.md，并报告各候选的已知缺陷。
```
