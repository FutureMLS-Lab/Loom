---
name: teaser-figure-3
description: Generate an icon-rich scientific pipeline, architecture, or closed-loop teaser with Cursor GenerateImage (the Cursor 2.4 backend was described as Nano Banana Pro), using a deterministic semantic blueprint and reference figures, then iterate after manual arrow/text review. Use when the user asks for an AI-generated paper pipeline, premium workflow infographic, architecture teaser, or Nano Banana figure. Not for quantitative result plots or equation-heavy diagrams.
disable-model-invocation: true
---

# teaser-figure-3

This skill makes a polished raster teaser with Cursor's `GenerateImage` tool.
It is the **default AR teaser workflow** whenever Auto Research decides to
create or refresh a teaser, Figure 1, overview, architecture, or pipeline. The
Author applies it proactively; no user request or skill name is required.
It is the AI-illustration alternative to:

- `teaser-figure-1`: deterministic tinted boxes and arrows;
- `teaser-figure-2`: deterministic white-ground object-and-chart layout.

Use this third style when a pipeline needs expressive icons and editorial visual
polish, while the number of exact labels and arrows remains small.

Cursor does not expose an image-provider selector. Cursor 2.4 identified its
image backend as Nano Banana Pro, but the current tool is provider-abstracted;
do not assume the backend is permanently fixed.

## The red line

**The image model proposes pixels; it never decides scientific content.**

Before generation, freeze:

- every node and stage;
- every directed edge and its endpoint;
- every exact label;
- pass/fail/rollback semantics;
- every number or claim shown;
- which elements may be decorative.

All scientific claims come from the manuscript or result files. If the
generated image changes an edge, invents text, drops a condition, or points an
arrow at the wrong state, reject it even when it looks better.

Do not use this skill for:

- experiment curves, ablations, or statistical plots;
- formulas that must remain editable and exact;
- tables or dense paragraphs;
- a figure whose labels cannot tolerate rasterization.

Use `results-figure-1`, `results-figure-2`, or deterministic SVG/PDF instead.

## Inputs

Prepare three inputs before calling the image tool:

1. **Semantic blueprint** — a table of node IDs, exact labels, and edges.
2. **Content reference** — preferably a deterministic draft whose arrows and
   labels are already correct.
3. **Style reference** — one or two figures supplying palette, icon language,
   density, and visual hierarchy.

The content reference controls truth. The style reference controls appearance.
Never ask the model to infer the graph from prose alone.

## Workflow

### 1. Freeze the semantic blueprint

Write a compact ledger:

```markdown
| ID | Exact label | Incoming | Outgoing | Meaning |
|---|---|---|---|---|
| S1 | Item arrives | rollback | S2 | external-store item |
| S2 | Serve & meter | S1, pass | S3 | observe reuse |
| S3 | Option gate | policy state | S4 | decide whether to trial |
| S4 | Batch write | S3 | S5 | write LoRA update |
| S5 | Fresh verification | S4 | pass, rollback, state update | verify write |
```

List feedback edges separately. This makes endpoint errors obvious during
review.

### 2. Produce a deterministic content reference

Draw a rough but semantically correct version with Python/SVG first. It may be
plain. Its purpose is to fix:

- stage order;
- arrow direction;
- label spelling;
- loop endpoints;
- relative grouping.

The image model receives this alongside the style reference.

### 3. Draft the generation Prompt

Use [`PROMPT_TEMPLATE.md`](PROMPT_TEMPLATE.md). Specify:

- wide scientific teaser;
- exact stage headings in quotation marks;
- exact feedback labels;
- explicit arrow origins and destinations;
- “minimal text” and “no pseudo-text”;
- no logos, citations, watermarks, or invented equations;
- opaque label backgrounds when arrows pass nearby.

Avoid vague instructions such as “make the workflow correct.”

### 4. Generate V1

Call Cursor Agent's image tool:

```text
GenerateImage(
  description=<complete prompt>,
  filename="<paper>-pipeline-ai-v1.png",
  reference_image_paths=[
    "<absolute content-reference path>",
    "<absolute style-reference path>"
  ],
  aspect_ratio="16:9"
)
```

`filename` cannot contain a directory. Copy the absolute output path returned
by Cursor into the Paper Task or a stable review directory.

### 5. Perform manual semantic review

Open the generated image itself. Do not approve from the Prompt or tool success
message.

Check in this order:

1. Are all required stages present exactly once?
2. Are labels spelled exactly?
3. Does every arrow terminate at the correct node?
4. Are pass, rollback, and state-update paths distinct?
5. Is any text hidden under an arrow?
6. Are label boxes above their arrows?
7. Are icons semantically compatible with their stage?
8. Did the model invent numbers, formulas, labels, or logos?
9. Is anything clipped at the image boundary?
10. Is text readable at final paper width?

Record semantic failures, not subjective requests like “make it nicer.”

### 6. Generate a correction version

Keep the first output and create `v2`, `v3`, etc. Supply the previous output and
the deterministic content reference.

The correction Prompt must say:

- preserve all parts that are already correct;
- name the wrong edge or label precisely;
- state the required origin and destination;
- prohibit unrelated layout or wording changes.

Example:

```text
Preserve the five cards and all typography. Change only feedback routing:
ROLLBACK must leave Fresh verification and terminate at Item arrives /
external store. It must not point to Measured policy state. Add a separate
green arrow from Fresh verification into Measured policy state.
```

### 7. Save provenance

Keep:

```text
<name>-ai-v1.png
<name>-ai-v2.png
<name>-selected.png
<name>-prompts.md
```

Never overwrite the current paper figure before the user chooses a version.

## Worked example

[`example.png`](example.png) is the selected V4 for the “When to Write to
Weights” streaming gate.

Its successful correction split three meanings that V3 had conflated:

- `PASS — keep in weights`: top green loop;
- `ROLLBACK — external store`: red loop back to Stage 1;
- `update empirical state`: separate green edge into the state bank.

The exact generation and correction Prompts are in
[`PROMPT_TEMPLATE.md`](PROMPT_TEMPLATE.md).

## Output quality

Cursor image output is raster. At 1536 px width, a 7-inch figure is about
219 dpi. That can be acceptable for a teaser, but it is not a native vector
asset.

If vector editing is required:

- retain AI-generated icons as PNG;
- redraw text, formulas, cards, borders, and arrows in SVG/Matplotlib;
- export SVG/PDF with embedded fonts;
- preserve the raster version as the visual reference.

Do not automatically trace the whole PNG: text becomes paths, geometry becomes
noisy, and the result is neither clean nor meaningfully editable.
