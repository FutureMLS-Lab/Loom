# Every Loom skill, on one page

<!-- GENERATED - edit the skills, then run scripts/gen_skills_index.py -->

A skill is a markdown file; injection is text. Three tiers decide who
reads what, and when:

1. **Always on** - in every prompt, nobody chooses it.
2. **Human-picked** - the task creator selects; full text is injected,
   and every task prompt also carries this tier as an on-demand menu
   (name + pitch + path) so agents can read unselected ones anyway.
3. **Pipeline-injected** - the Paper Factory hands each AR role its
   methodology itself; these never appear in the picker.

## Always on

- **DEFAULT_PROMPT** — Loom default prompt
    `loom/skills/DEFAULT_PROMPT.md`

## Human-picked (the task picker / the skill shelf)

- **charlie_skills** — 在开始实现或 review 前，先把任务目标、当前 plan、成功标准整理清楚，只保留对后续执行有用的信息。默认遵守下面的工作习惯：
    `loom/skills/charlie_skills.md`
- **ARIS** — ARIS — Autonomous Research-In-Sleep loop
    `loom/skills/aris/ARIS.md`
- **loom-hot-restart** — Restarts a running Loom web service from an updated source checkout while preserving its authentication environment, disk-backed tasks, tmux
    `loom/skills/dev/loom-hot-restart/SKILL.md`
- **remote_control** — loom Remote Control
    `loom/skills/remote_control/remote_control.md`
- **server_setup** — Loom Agent Server Setup
    `loom/skills/server_setup/server_setup.md`

## Pipeline-injected (AR / Paper Factory)

### Studio

- **AR-STUDIO** — Surveys the field and proposes grounded ideas.
    Injected in full into every Studio job (mine, ideas, ground).
    `loom/skills/ar/AR-STUDIO.md`

### Author

- **AR-AUTHOR** — Writes the paper and runs the experiments behind it.
    Injected in full into every author round prompt.
    `loom/skills/ar/AR-AUTHOR.md`
- **paper-results-reporting** — Standardizes result-table statistics and manuscript-safe provenance.
    Injected in full into every author prompt.
    `loom/skills/ar/paper-results-reporting/SKILL.md`
- **wsdm-submission-readiness** — Packages anonymous WSDM papers under ACM and nine-page rules.
    Injected in full only into WSDM author prompts.
    `loom/skills/ar/wsdm-submission-readiness/SKILL.md`
- **wacv-submission-readiness** — Packages anonymous WACV papers under track and eight-page rules.
    Injected in full only into WACV author prompts.
    `loom/skills/ar/wacv-submission-readiness/SKILL.md`

### Reviewer

- **AR-REVIEWER** — Reviews each round the way a venue would.
    Injected in full into every reviewer run.
    `loom/skills/ar/AR-REVIEWER.md`

### Rebuttal

- **paper-rebuttal** — Drafts acceptance-oriented, evidence-bounded responses to reviewers.
    Named in every author round prompt; the author reads it before answering the reviewers.
    `loom/skills/ar/paper-rebuttal/SKILL.md`

### Figures

- **checkbib** — Verify every citation in a LaTeX paper against a real fetched source, and catch fabricated references before submission
    Listed as a menu in every author round; the author reads the one it needs.
    `loom/skills/ar/figures/checkbib/SKILL.md`
- **results-figure-1** — Draw a results figure for one of this repo's papers — a chart carrying measurements, in the house style the existing figures already use: Okabe-Ito colours, the paper's serif face, TrueType output, references drawn as labelled baselines rather than legend entries, and a printed summary of every number the figure asserts
    Listed as a menu in every author round; the author reads the one it needs.
    `loom/skills/ar/figures/results-figure-1/SKILL.md`
- **results-figure-2** — Draw a results figure that shows the distribution behind every number it asserts — the aggregate in one panel, every individual run in the next, dashed reference lines carrying the published value in their own colour, and the statistics set inside the panel
    Listed as a menu in every author round; the author reads the one it needs.
    `loom/skills/ar/figures/results-figure-2/SKILL.md`
- **teaser-figure-1** — Draw a paper's page-one teaser — the three-panel problem/method/result schematic of tinted rounded boxes and arrows that explains a contribution at a glance
    Listed as a menu in every author round; the author reads the one it needs.
    `loom/skills/ar/figures/teaser-figure-1/SKILL.md`
- **teaser-figure-2** — Draw a paper's page-one teaser in the unadorned conference idiom — white ground, no tinted panels, the objects themselves drawn rather than named, panel names underneath as "(a) Obstacle: ...", and a real measured chart as the result panel
    Listed as a menu in every author round; the author reads the one it needs.
    `loom/skills/ar/figures/teaser-figure-2/SKILL.md`
- **teaser-figure-3** — Generate an icon-rich scientific pipeline, architecture, or closed-loop teaser with Cursor GenerateImage (the Cursor 2.4 backend was described as Nano Banana Pro), using a deterministic semantic blueprint and reference figures, then iterate after manual arrow/text review
    The default teaser: every author round is told to use this proactively for page-one figures.
    `loom/skills/ar/figures/teaser-figure-3/SKILL.md`
- **teaser-figure-4** — Create paper-grounded teaser Prompts with the Happy Figure workflow, exact text/fact locks, multiple visual directions, and rendered-image audits
    Listed as a menu in every author round; the author reads the one it needs.
    `loom/skills/ar/figures/teaser-figure-4/SKILL.md`
