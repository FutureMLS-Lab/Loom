---
name: teaser-figure-4
description: Create paper-grounded teaser Prompts with the Happy Figure workflow, exact text/fact locks, multiple visual directions, and rendered-image audits. Use for Figure 1 redesigns, graphical abstracts, mechanism explanations, conceptual comparisons, technical roadmaps, or several visually distinct but scientifically identical teaser directions.
disable-model-invocation: true
---

# teaser-figure-4

This skill adapts the Happy Figure workflow to an Auto Research Paper Task.
It treats the **drawing Prompt as a reviewed scientific artifact** between the
paper and the image model.

The pipeline is:

```text
Paper sources and PDF
    → Paper Understanding
    → immutable facts and forbidden claims
    → content community
    → visual treatment
    → figure-type master
    → exact Prompt and visible-text whitelist
    → GenerateImage candidates
    → semantic and visual audit
```

## When to use it

Use this skill when:

- a Paper Task already has enough manuscript content to understand;
- Figure 1 must be reconstructed from the paper rather than from a short prose
  instruction;
- the user wants strict, premium, minimal, or multiple visual directions;
- the figure may be a graphical abstract, mechanism explanation, conceptual
  comparison, or technical roadmap;
- exact scientific labels, topology, caveats, and measured outcomes matter.

Prefer another skill when:

- the required figure is a quantitative plot: use `results-figure-1/2`;
- exact equations or fully editable vector geometry dominate: use
  `teaser-figure-1/2`;
- a simple pipeline already has a frozen semantic blueprint and one desired
  visual direction: `teaser-figure-3` is faster.

`teaser-figure-3` remains the default AR teaser. This fourth skill is the
document-first, multi-direction alternative.

## The red line

**The paper determines the science; the image model only renders it.**

Never let the image model:

- invent, remove, merge, reorder, or reinterpret a scientific module;
- add training, branches, datasets, metrics, equations, legends, or results;
- reverse an operand, edge, causal direction, pass/fail path, or timeline;
- turn a hypothesis into a confirmed mechanism;
- turn a point estimate into significance or a pilot into a general result;
- encode numbers through invented bar lengths, areas, or colour intensity;
- write visible text outside the exact whitelist.

Any scientific error invalidates the candidate, regardless of visual quality.

## 1. Locate the authoritative inputs

Read, in this order:

1. compiled `main.pdf`;
2. abstract and introduction;
3. method;
4. experiments/results;
5. the current Figure 1 and caption, if present;
6. result files behind every displayed number.

For an AR Paper Task these normally live under:

```text
<task>/work/manuscript/
<task>/work/code/
```

PDF extraction is a starting point, not authority. If section detection or
equations are incomplete, resolve them from the LaTeX source and result files.
For an image-only scan, require OCR or readable source instead of guessing.

## 2. Write `paper-understanding.md`

Before drafting a Prompt, record:

```markdown
# Paper Understanding

## Research message
<one paragraph>

## Figure goal
<what a reader should understand in ten seconds>

## Content community
<CS/ML family, materials/chemistry, biology/medicine, or a justified custom one>

## Inputs and modules
<exact nodes, branch inputs, shared/frozen components>

## Equations and operations
<exact operands and direction>

## Measured outcome
<exact values, conditions, sample size, uncertainty, and narrow conclusion>

## Immutable facts
- ...

## Forbidden interpretations
- ...

## Existing-figure observations
<topology that must stay; visual choices that may change>
```

Keep scientific statements traceable to a source location.

## 3. Freeze a fact ledger

Create a compact table:

```markdown
| ID | Fact or label | Source | May paraphrase? | Visual role |
|---|---|---|---:|---|
| F1 | ... | method equation | no | mechanism |
| F2 | ... | result JSON | no | outcome |
| F3 | ... | discussion | yes, narrowly | caveat |
```

Also list explicit rejection conditions. Typical examples:

- an omitted modality enters a branch where it is forbidden;
- two branches stop sharing the same frozen model;
- subtraction becomes fusion or reverses its operands;
- an offline sweep is drawn as repeated model forwards;
- a confidence interval containing zero becomes a significant effect;
- an exact number, unit, symbol, or decimal place changes.

## 4. Select two independent dimensions

Do not conflate scientific community with aesthetic treatment.

### Content community

This controls information organization and scientific visual language.

For CS/ML, choose the closest family:

- NeurIPS/ICML/ICLR: mechanism, ablation logic, representation flow;
- CVPR/WACV: visual inputs, branch semantics, image/video tasks;
- ACL/EMNLP: language inputs, retrieval/reasoning stages, evaluation;
- KDD/WWW/VLDB/SIGMOD: data flow, stores, queries, system boundaries;
- systems venues: execution path, memory, scheduling, throughput.

### Visual treatment

Choose one:

1. **Strict conference figure** — restrained white ground, explicit topology,
   compact labels, minimal decoration.
2. **Premium academic graphical abstract** — stronger hierarchy, polished
   cards/icons, generous whitespace, but unchanged CS/ML logic.
3. **Minimal flat schematic** — few shapes, thin lines, short labels, lowest
   typography risk.
4. **Research presentation overview** — only when the artifact is for a talk or
   white paper rather than the submitted PDF.

If the user did not choose and the distinction materially changes the paid
generation result, present 2–3 short options and recommend one. In autonomous
AR operation, select the strict conference figure unless the manuscript
explicitly calls for a graphical abstract.

## 5. Select a figure-type master

The figure type adapts the content community; it does not replace it.

### Graphical abstract / paper main figure

One visual thesis:

```text
problem or hypothesis → method → measured outcome
```

Keep one reading direction and one dominant result.

### Mechanism explanation

Expose the operation and why it succeeds or fails. Show causal claims only when
the paper establishes them; otherwise label them as hypotheses or observations.

### Multi-panel conceptual comparison

Use equal-size cards and exact text when an image model might fabricate chart
geometry. For real quantitative charts, use a results skill instead.

### Technical roadmap

Show the reproducible protocol, including storage, offline/online boundaries,
statistics, and timing paths. No arrow may bypass a mandatory stage.

## 6. Form the Figure Brief

Write:

```markdown
## Figure Brief

- Goal:
- Content community:
- Visual treatment:
- Figure type:
- Canvas/aspect ratio:
- Reading order:
- Zones/modules:
- Directed connections:
- Feedback/offline/timing paths:
- Exact equations:
- Exact measured values:
- Caveats:
- Visible-text whitelist:
- Forbidden content:
```

The Figure Brief is the source of the final Prompt. Do not ask the image model
to infer the graph from the manuscript prose.

## 7. Draft the exact image Prompt

Use [`PROMPT_TEMPLATE.md`](PROMPT_TEMPLATE.md). Replace every placeholder.

Priority:

```text
scientific facts
    > explicit user requirements
    > content-community visual language
    > figure-type structure
    > model adaptation
    > aesthetic adjectives
```

For an English paper, use an English Prompt and English labels even when the
conversation is Chinese.

The final Prompt must embed:

```text
All visible text in the figure must use only the following exact labels:
1. "..."
2. "..."

Do not render any title, legend, paragraph, footnote, random text, numbered
badge, or structural field outside this list.
```

Never leave template markers such as `{VISIBLE_TEXT}`, `[Label ...]`,
`[insert context]`, `BEGIN PROMPT`, or `END PROMPT`.

## 8. Choose a bounded candidate set

Do not generate seven images by default.

Recommended:

- one strict candidate;
- optionally one premium or minimal candidate when the visual decision is
  genuinely unresolved;
- one correction version for each candidate that fails a fixable audit.

Generate a larger direction matrix only when the user explicitly requests
exploration.

Use timestamped or versioned filenames and never overwrite the current paper
figure before selection.

## 9. Generate

For Cursor GenerateImage:

```text
GenerateImage(
  description=<complete reviewed Prompt>,
  filename="<paper>-teaser-happy-v1.png",
  aspect_ratio="16:9",
  reference_image_paths=[
    "<current semantically correct figure>",
    "<optional style reference>"
  ]
)
```

The content reference controls truth. The style reference controls appearance.
Do not pre-guess the generated asset path; use the path returned by the tool.

## 10. Audit the rendered image

Open the actual PNG. Check in this order:

1. Every required module appears exactly once.
2. Branch inputs are correct.
3. Every arrow has the correct origin, destination, and direction.
4. Equations preserve operands, signs, subscripts, and Greek symbols.
5. Every number, unit, condition, and qualifier matches the fact ledger.
6. Hypotheses, pilots, null results, and significance are not overstated.
7. Visible text is entirely inside the whitelist.
8. No random badge, logo, watermark, pseudo-text, or invented legend appears.
9. Text remains readable at final two-column width.
10. Nothing is clipped or hidden under arrows/cards.

Record failures in `audit-vN.md`. Use precise corrections:

```text
Preserve all correct modules. Change only edge E3: it must leave Storage and
terminate at Offline sweep. It must not return to either model branch.
```

Reject and regenerate rather than manually rationalizing a scientific error.

## 11. Save provenance

Keep:

```text
<figure-name>/
├── paper-understanding.md
├── fact-ledger.md
├── figure-brief.md
├── prompt-v1.md
├── candidate-v1.png
├── audit-v1.md
├── candidate-v2.png
├── selected.png
└── README.md
```

The README must preview every candidate, name the selected version, and list
known limitations.

## 12. Output and vector boundary

GenerateImage output is raster. Do not call it a vector figure.

If vector editing is required:

- retain approved icons or illustrations as raster assets;
- redraw labels, formulas, cards, borders, axes, and arrows in SVG/Matplotlib;
- export SVG/PDF with embedded fonts;
- preserve the generated PNG and Prompt as provenance.

## Worked example

[`example.png`](example.png) is a strict conference-style redraw of a
modality-contrastive decoding Figure 1. It preserves:

- full versus visual-only branch inputs;
- one shared frozen model;
- the exact subtraction direction;
- exact pilot values and latency;
- the narrow `No recovery` conclusion.

See [`EXAMPLE.md`](EXAMPLE.md) for the Figure Brief and audit lessons.
Source and adaptation provenance is recorded in [`SOURCE.md`](SOURCE.md).
