# Teaser Figure 4 Prompt Template

Copy this template into `prompt-vN.md` and replace every brace-delimited field.
Do not send the template itself to an image model.

```text
Create a publication-ready scientific teaser figure for an English-language
{CONTENT_COMMUNITY} paper.

ARTIFACT
- Figure type: {FIGURE_TYPE}
- Visual treatment: {VISUAL_TREATMENT}
- Canvas: wide landscape, {ASPECT_RATIO}
- Intended use: {PAPER_FIGURE_OR_PRESENTATION}
- Reading direction: {READING_DIRECTION}

SCIENTIFIC OBJECTIVE
{ONE_SENTENCE_FIGURE_GOAL}

SCIENTIFIC STATUS
- Established by the paper: {ESTABLISHED_FACTS}
- Hypothesis or interpretation only: {HYPOTHESES}
- Narrow measured conclusion: {MEASURED_CONCLUSION}
- Required caveat: {CAVEAT}

LAYOUT

ZONE 1 — {ZONE_1_NAME}
- Position: {ZONE_1_POSITION}
- Required objects: {ZONE_1_OBJECTS}
- Required labels: {ZONE_1_LABELS}

ZONE 2 — {ZONE_2_NAME}
- Position: {ZONE_2_POSITION}
- Required objects: {ZONE_2_OBJECTS}
- Required labels: {ZONE_2_LABELS}

ZONE 3 — {ZONE_3_NAME}
- Position: {ZONE_3_POSITION}
- Required objects: {ZONE_3_OBJECTS}
- Required labels: {ZONE_3_LABELS}

{OPTIONAL_ADDITIONAL_ZONES}

CONNECTIONS
1. {EDGE_1_ORIGIN} → {EDGE_1_DESTINATION}: {EDGE_1_MEANING}
2. {EDGE_2_ORIGIN} → {EDGE_2_DESTINATION}: {EDGE_2_MEANING}
3. {EDGE_3_ORIGIN} → {EDGE_3_DESTINATION}: {EDGE_3_MEANING}
{OPTIONAL_ADDITIONAL_EDGES}

No required stage may be bypassed. Offline, feedback, rollback, and timing paths
must be visually distinct from the main forward path.

EXACT EQUATIONS AND VALUES
- {EXACT_EQUATION_OR_NONE}
- {EXACT_VALUE_1}
- {EXACT_VALUE_2}
- {EXACT_VALUE_3}

Do not infer, round, rescale, reorder, or visually exaggerate these values.

All visible text in the figure must use only the following exact labels:
1. "{VISIBLE_LABEL_1}"
2. "{VISIBLE_LABEL_2}"
3. "{VISIBLE_LABEL_3}"
{COMPLETE_VISIBLE_TEXT_WHITELIST}

Do not render any title, legend, paragraph, footnote, random text, numbered
badge, watermark, logo, citation, or structural field outside this list.
ZONE headings above organize this Prompt and must not appear in the image unless
they are explicitly included in the visible-text whitelist.

VISUAL LANGUAGE
{CONTENT_COMMUNITY_VISUAL_LANGUAGE}

Use {PALETTE}. Keep generous whitespace, thin disciplined arrows, concise
publication-readable labels, restrained academic styling, and clear hierarchy.
The content reference controls topology and scientific meaning. The style
reference may influence palette, typography, icon language, density, and
spacing only.

FORBIDDEN CONTENT
- Do not add, remove, merge, reorder, or reinterpret scientific modules.
- Do not invent training, models, datasets, metrics, equations, numerical
  results, curves, axes, legends, confidence intervals, or significance.
- Do not reverse any edge, branch input, operand, timeline, pass/fail path, or
  offline/online boundary.
- Do not convert a hypothesis into a confirmed causal mechanism.
- Do not use bar length, area, or colour intensity to encode a number unless
  the source is a verified result chart and the Prompt specifies its scale.
- {PROJECT_SPECIFIC_FORBIDDEN_ITEMS}

Before finishing, internally verify every module, edge, equation, value, caveat,
and visible label against this Prompt. Prefer an empty area over invented
content.
```

## Correction Prompt

```text
Use the previous candidate and the semantically correct content reference.
Preserve every module, label, value, colour role, and edge not named below.

Change only:
1. {PRECISE_ERROR}: {EXACT_CORRECTION}
2. {PRECISE_ERROR}: {EXACT_CORRECTION}

Required edge correction:
{ORIGIN} → {DESTINATION}, meaning {MEANING}.

Do not make unrelated layout, wording, icon, number, equation, or topology
changes. All visible text remains restricted to the original exact whitelist.
```
