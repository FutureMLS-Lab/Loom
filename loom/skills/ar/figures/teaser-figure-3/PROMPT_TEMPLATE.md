# Nano Banana Pipeline Prompt Templates

## Initial generation

Replace the bracketed fields and preserve quoted labels verbatim.

```text
Create a polished, publication-quality scientific teaser diagram for
[PAPER / METHOD].

Use the content reference for semantic structure and the style reference for
visual inspiration. Do not copy logos or exact composition.

Layout:
- wide landscape infographic;
- clean white background;
- crisp vector-illustration appearance;
- [PALETTE];
- consistent rounded cards;
- precise alignment and generous whitespace.

Show this workflow:
[ORDERED STAGES WITH EXACT QUOTED LABELS]

Show this state bank:
[STATE CELLS WITH EXACT LABELS]

Feedback edges:
[EXPLICIT ORIGIN -> DESTINATION FOR EACH EDGE]

Place every arrow label in an opaque light background so the line never crosses
the text. Keep text minimal and large. Spell only supplied labels. Do not
invent paragraphs, equations, logos, citations, watermarks, or extra labels.
Do not produce pseudo-text.
```

Suggested call:

```text
GenerateImage(
  description=<prompt above>,
  filename="<name>-ai-v1.png",
  reference_image_paths=[
    "<absolute content-reference path>",
    "<absolute style-reference path>"
  ],
  aspect_ratio="16:9"
)
```

## Worked initial Prompt: streaming gate

```text
Create a polished, publication-quality scientific teaser diagram for a
machine-learning paper titled conceptually “When to Write to Weights”.

Use the references for visual inspiration and semantic structure, but do not
copy their exact composition or logos. Wide landscape infographic on a clean
white background, crisp vector-illustration appearance, dark navy outer loop
and outlines, pale blue/cream/lavender/red/green stage cards, restrained
academic palette, consistent rounded corners, precise alignment, generous
whitespace, and strong visual hierarchy.

Show a five-stage closed-loop workflow from left to right with exactly these
large stage headings:
“1 Item arrives”
“2 Serve & meter”
“3 Option gate”
“4 Batch write”
“5 Fresh verification”

Under the workflow place a state bank titled “Measured policy state”, with
three cells:
“F(α) verified efficacy”
“ĥ, ρ̂ retrieval + interference”
“n̂ᵢ reuse forecast”

Add:
- green loop “PASS — keep in weights”;
- red branch “ROLLBACK — external store”;
- green feedback “update empirical state”;
- orange arrow “price next option”.

The green feedback label must have an opaque light-green background and must
not overlap its arrow. The red rollback label must be above its arrow with an
opaque light-red background.

Keep text minimal and large. Spell only supplied labels. Do not invent prose,
equations, logos, watermarks, citations, or extra labels. Do not produce
garbled pseudo-text.
```

## Worked correction Prompt: V3 to V4

```text
Refine the supplied scientific workflow teaser while preserving its overall
composition, exact five stage headings, card styling, icon quality, palette,
typography, and central “Measured policy state” bank.

Make only these routing corrections:

1. “ROLLBACK — external store” must leave “5 Fresh verification”, travel
   around the diagram without crossing text, and terminate with a red arrowhead
   at external store / “1 Item arrives”. It must not point to Measured policy
   state.
2. Add a separate green arrow from “5 Fresh verification” into the right edge
   of “Measured policy state”, labelled “update empirical state”. Put the label
   in an opaque light-green pill above its arrow.
3. Keep “PASS — keep in weights” as an independent top green loop.
4. Keep “price next option” from Measured policy state to “3 Option gate”.
5. Put the red rollback label above its arrow in an opaque light-red pill.

Keep all supplied text correctly spelled. Do not add paragraphs, pseudo-text,
new equations, logos, watermarks, or extra labels.
```

## Correction checklist

Before accepting a revised image:

```text
- [ ] Wrong edge now has the required destination
- [ ] Existing correct edges did not change
- [ ] Exact labels remain exact
- [ ] No new pseudo-text appeared
- [ ] Label backgrounds cover nearby arrows
- [ ] No text or icon is clipped
- [ ] Output version is preserved separately
```
