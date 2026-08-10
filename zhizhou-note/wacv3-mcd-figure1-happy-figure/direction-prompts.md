# Direction prompts

## 1. Premium graphical abstract / paper main figure

```text
Create a premium academic graphical abstract and paper main figure for an ICLR/WACV-style multimodal machine-learning paper. Optimize the composition for the current Cursor image generator or another strong text-rendering image model. Use a wide 16:9 landscape canvas, warm white background, crisp modern sans-serif typography, precise CS-system-diagram logic, low-saturation academic colors, subtle layered cards, delicate 2–4 px shadows, restrained translucent fills, and generous whitespace. Keep the artwork 2D-first and publication-readable at two-column width. The narrative must be problem → two-branch MCD test → measured no-recovery outcome, not a generic infographic or marketing poster.

EXACT TOPOLOGY
Use one locked left-to-right path with three major zones and no other scientific zones.

ZONE 1 — PROBLEM AND FULL INPUT, FAR LEFT
Create one problem-framing card containing a compact full-input card. Show exactly three unlabeled modality glyphs: one image tile, one audio waveform tile, and one question-bubble tile. Use a subtle visual emphasis around the image tile only to communicate that vision is the hypothesized dominant modality; do not draw a measured weight, probability, attention score, or established causal mechanism. This zone frames dominant-modality bias as a hypothesis to test, not as a proven per-example fact.

ZONE 2 — TWO-BRANCH MCD TEST, CENTER
From the full-input card, draw exactly two outgoing routes:
1. One upper blue route carries image, audio, and question into the upper full branch.
2. One lower amber route carries image and question into the lower visual-only branch. Audio must remain behind at the source: no audio glyph, waveform, line, or connector may enter or touch the lower branch.

Make the two branch cards equal in size and vertically aligned. Each branch must contain an identical frozen-model core with the same silhouette, dimensions, internal token/chip motif, color, and finish. Render the repeated model label once in each branch to show that the checkpoint is shared rather than trained twice. The upper branch emits one compact qualitative four-element option-logit ribbon for l_F. The lower branch emits one corresponding qualitative four-element option-logit ribbon for l_V. These ribbons are schematic vectors only: they must have no axis, tick, scale, number, legend, error bar, or quantitative bar height.

Route the upper l_F ribbon and lower l_V ribbon independently into exactly one violet MCD test card. The two routes may meet only inside this card. The upper full logits are the positive first operand; the lower visual-only logits are multiplied by λ and subtracted. Display the formula exactly as specified. Do not reverse the operands, fuse the branches earlier, or let either branch bypass MCD.

ZONE 3 — MEASURED OUTCOME, FAR RIGHT
Draw exactly one arrow from the MCD card to one editorial result card. Inside the result card, use four aligned text rows: full-input accuracy, primary raw-MCD accuracy, CPU latency, and the narrow conclusion. Use equal typographic weight for the two accuracy rows. Treat the result as a measured task-balanced 40-example pilot. Give “No recovery” sober neutral emphasis in dark plum, never bright failure red. Do not use a decline arrow, warning icon, broken object, significance star, chart, or visual metaphor of proven harm. The lower point estimate must not be presented as statistically significant degradation.

VISUAL SYSTEM
Use cobalt/teal blue for the full-input and full-branch route, amber/orange for the visual-only route, lavender/violet for MCD, and warm gray with muted plum for the outcome. Use thin consistent outlines and unambiguous arrowheads. The MCD card should be the visual center; the outcome should remain immediately legible. Make the topology readable in grayscale through position, line routing, and card hierarchy rather than color alone. No perspective distortion, heavy 3D, dramatic lighting, glossy gradients, dashboard widgets, biomedical forms, or materials-science motifs.

SCIENTIFIC AND NO-INVENTION CONSTRAINTS
Strictly preserve the following facts: the full context is image + audio + question; the visual-only context keeps image and question but omits audio; both branches use the same frozen model; MCD computes l_F - λ l_V; the measured pilot reports 50.0% for full input, 37.5% for raw MCD at λ=1, and 1.78× CPU latency; the measured conclusion is no recovery. Do not add, remove, merge, duplicate, reorder, or reinterpret any zone, branch, model, arrow, or result. Do not add an audio-only branch, shuffled branch, VCD-style branch, encoder, decoder, modality gate, attention map, fusion block, training loop, loss, gradient, parameter update, fine-tuning, generated answer, application, or extra benchmark. Do not invent any data, sample, value, confidence interval, p-value, significance statement, trend, curve, axis, table, legend, color bar, or empirical distribution. Do not claim that every example is visually dominated, that subtraction identifies an internal causal mechanism, or that MCD significantly degrades accuracy. No logo, watermark, citation, author name, venue logo, caption, or surrounding paper mockup.

EXACT VISIBLE-TEXT WHITELIST
All visible text in the figure must use only the following exact English labels:
1. "Can visual-prior subtraction recover cross-modal reasoning?"
2. "Hypothesized dominant-modality bias"
3. "Full input"
4. "Image + audio + question"
5. "Full branch"
6. "Visual-only branch"
7. "Image + question (no audio)"
8. "Same frozen model"
9. "Full option logits l_F"
10. "Visual-only option logits l_V"
11. "MCD test"
12. "l_F - λ l_V"
13. "Task-balanced 40-example OmniBench pilot"
14. "50.0% full input"
15. "37.5% raw MCD at λ=1"
16. "1.78× CPU latency"
17. "No recovery"

Render "Same frozen model" exactly twice, once in each branch. Render every other whitelisted label exactly once. Preserve capitalization, punctuation, mathematical symbols, spacing, and numerals verbatim. Do not render any text outside this whitelist. Prompt headings such as ZONE, EXACT TOPOLOGY, VISUAL SYSTEM, and WHITELIST are instructions only and must not appear in the figure.

Final output: one cohesive high-resolution landscape graphical abstract with sharp vector-like edges, exact text, exact branch routing, and no content outside the locked topology.
```

## 2. Mechanism explanation figure

```text
Create a publication-ready mechanism explanation figure for an ICLR/ICML/WACV multimodal machine-learning paper. Optimize it for the current Cursor image generator or another strong text-rendering model. Use a wide landscape white canvas, restrained Soft Tech scientific pastels, rounded geometric modules, crisp sans-serif labels, thin precise connectors, and a refined 2D academic finish. The figure must explain a tested hypothesis: a hypothesized removable visual output prior is subtracted as l_F - λ l_V, but at λ=1 the same operation corrects six baseline errors and breaks eleven baseline-correct answers, implying that useful visual evidence may also be removed. This is a mechanism interpretation of paired outcomes, not proof of statistically significant degradation.

EXACT TOPOLOGY
Use one locked left-to-right causal-explanation chain with four functional positions:
hypothesis card → parallel frozen-model computation → one MCD subtraction card → paired-outcome group → interpretation card.
No other scientific module or path is permitted.

POSITION 1 — HYPOTHESIS, FAR LEFT
Draw one compact hypothesis card with a stylized visual-distribution ribbon or visual tile behind a question mark. The graphic represents a hypothesized removable visual prior only. Do not depict this prior as measured, universally present, localized inside a network layer, or known to be causal. Draw exactly one arrow from this hypothesis card toward the two-context computation.

POSITION 2 — PARALLEL COMPUTATION, CENTER-LEFT
Create exactly two equal, vertically aligned context-and-model branches:
1. Upper blue branch: image, audio, and question enter one frozen-model card and produce a qualitative four-element option-logit ribbon l_F.
2. Lower amber branch: image and question enter an identical frozen-model card and produce a qualitative four-element option-logit ribbon l_V. Audio is absent; no audio glyph or connector may enter the lower branch.

The two model cores must be visually identical in geometry, size, internal motif, and color to denote one shared frozen checkpoint. The option-logit ribbons are abstract vector symbols, not quantitative evidence plots; do not add axes, ticks, values, baselines, scales, legends, or error bars.

POSITION 3 — EXACT SUBTRACTION, CENTER
Route l_F and l_V independently into exactly one violet MCD card. They may meet only inside this card. Show l_F as the first positive operand and subtract λ times l_V. The formula must appear exactly as l_F - λ l_V. Do not reverse the operands, add softmax equations, replace subtraction with fusion or averaging, or insert any learned component. Draw exactly one outgoing arrow from MCD to the paired-outcome group.

POSITION 4 — PAIRED OUTCOMES AND INTERPRETATION, RIGHT
Create one enclosing paired-outcome group containing exactly two equal subcards side by side:
- a cool teal correction subcard for six baseline errors corrected;
- a muted amber/plum breakage subcard for eleven baseline-correct answers broken.

Use counts as text cards, not bars, pies, scales, or proportional areas. Keep both subcards equal in size so area does not invent a quantitative encoding. Below them, inside the same group, place the non-significance statement as a neutral footer. From the enclosing paired-outcome group, draw exactly one arrow to one final interpretation card. The interpretation card must state only that useful visual evidence may also be removed. Visually suggest that the subtracted l_V ribbon can contain a mixture of an abstract nuisance component and task-relevant evidence by using two interleaved, unlabeled color strands inside the single l_V ribbon; do not turn these strands into new modules, measured proportions, named latent variables, or established internal decomposition. The point is that output subtraction cannot distinguish a visual shortcut from valid visual evidence, so it can expose useful alternatives while also removing useful signal.

VISUAL SYSTEM
Use blue for the full branch, amber for the visual-only branch, violet for subtraction, teal for corrected errors, and muted plum for broken correct answers. Avoid saturated red and all alarm or failure imagery. Keep the hypothesis visibly tentative with a question mark and dashed card border; keep all main data-flow arrows solid. Use no feedback loop. Use no dramatic slope, down arrow, or trend metaphor. Maintain conference-paper clarity, generous whitespace, and exact alignment.

SCIENTIFIC AND NO-INVENTION CONSTRAINTS
The visual-only branch is a predeclared hypothesized dominant branch, not a per-example oracle and not evidence that every question is visually dominated. The arithmetic is exactly l_F - λ l_V. At λ=1, six of twenty baseline errors are corrected and eleven of twenty baseline-correct predictions are broken; render only the requested six and eleven paired-change counts, not the denominators unless they are added to the whitelist. The paired test is not significant, so do not claim significant degradation, population-level harm, or a resolved population effect. Do not claim that subtraction literally separates a visual prior inside the model. Do not add a third branch, separate checkpoint, audio-only control, shuffled-image control, positive-scaling control, VCD-style score, training, gradients, losses, attention, feature maps, internal neurons, causal interventions, or representations not specified here. Do not invent any accuracy, percentage, confidence interval, p-value, significance star, effect size, probability, trend, axis, chart, legend, scale, or extra result. No logos, watermark, venue branding, citations, authors, decorative science icons, photorealism, biomedical styling, materials-science styling, or marketing effects.

EXACT VISIBLE-TEXT WHITELIST
All visible text in the figure must use only the following exact English labels:
1. "Hypothesis"
2. "Removable visual prior?"
3. "Full context"
4. "Image + audio + question"
5. "Visual-only context"
6. "Image + question (no audio)"
7. "Same frozen model"
8. "l_F"
9. "l_V"
10. "MCD"
11. "l_F - λ l_V"
12. "Paired answer changes at λ=1"
13. "6 baseline errors corrected"
14. "11 baseline-correct answers broken"
15. "Paired test not significant"
16. "Useful visual evidence may also be removed"

Render "Same frozen model" exactly twice, once in each branch. Render every other whitelisted label exactly once. Preserve every character, mathematical symbol, hyphen, space, and numeral verbatim. Do not render any title, annotation, legend, paragraph, footnote, icon text, or structural field outside this whitelist. Prompt headings and position names are instructions only and must not appear in the image.

Final output: one high-resolution, technically exact mechanism figure that makes the hypothesis, arithmetic, paired gains and losses, and narrow interpretation immediately understandable without overstating statistical evidence.
```

## 3. Multi-panel comparison figure

```text
Create a publication-ready four-panel comparison figure for an ICLR/WACV multimodal machine-learning paper, optimized for the current Cursor image generator or another strong text-rendering model. Use a wide 16:9 landscape canvas with a clean white background, a strict 2×2 panel grid, crisp sans-serif typography, thin cool-gray outlines, very light low-saturation panel fills, generous internal padding, and exact table-like numeric cards. This is a faithful display of committed measured values, not a request to infer or draw a statistical chart.

EXACT TOPOLOGY
Build exactly four equal outer panels in a locked 2×2 grid:
- Panel A at top left: accuracy.
- Panel B at top right: raw-MCD gain/loss.
- Panel C at bottom left: controls at λ=1.
- Panel D at bottom right: sequential MCD CPU latency.

No arrows connect the panels. No fifth panel, inset, caption strip, legend, or side annotation is allowed. Place one small panel letter in the upper-left corner of each corresponding panel, followed by its panel heading.

PANEL A — ACCURACY
Use one table-like stack of exactly seven equal-height rows in this exact order:
1. Full input, 50.0%.
2. Visual only, 30.0%.
3. Audio only, 25.0%.
4. Raw MCD λ=0.25, 42.5%.
5. Raw MCD λ=0.5, 45.0%.
6. Raw MCD λ=1, 37.5%.
7. Raw MCD λ=2, 20.0%.

Each row must be a fixed-width textual card with method on the left and value on the right, separated only by the visible vertical-bar character already included in the approved row text. Keep every row the same width, height, fill intensity, and font size. Do not map value to row length, area, saturation, position, icon count, or color. Do not sort the rows.

PANEL B — GAIN / LOSS
Use one table-like stack of exactly four equal-height rows in increasing λ order. Each row displays the raw-MCD λ and the exact gain/loss pair, where the first integer is baseline errors corrected and the second is baseline-correct answers broken:
λ=0.25 → 0/3;
λ=0.5 → 3/5;
λ=1 → 6/11;
λ=2 → 4/16.

Render these only as exact text rows. Do not turn the pairs into opposing bars, arrows, balances, people icons, colored counts, or proportional areas. Do not draw or label a trend.

PANEL C — CONTROLS AT λ=1
Use one table-like stack of exactly three equal-height rows in this exact order:
1. Shuffled visual, 40.0%.
2. VCD-style, 45.0%.
3. Positive scaling, 50.0%.

Use the same row geometry and typography as Panel A. These are accuracy cards. Do not add raw MCD or full input as extra rows in this panel, and do not infer a ranking or significance.

PANEL D — CPU LATENCY
Create one centered result card inside the panel. Place the latency heading above one large but restrained numeric line. The only latency result is 1.78× baseline for sequential MCD on CPU. Do not add seconds, memory, GPU extrapolation, throughput, preprocessing time, branch-time decomposition, or hardware details.

VISUAL SYSTEM
Use charcoal text, white cards, pale ice-blue accents for baseline/unimodal rows, pale lavender accents for raw MCD rows, pale sage accents for controls, and a pale warm-gray latency card. Colors are categorical decoration only, never a quantitative scale. Use tabular numerals and align decimal points where practical. Keep all values large enough to survive reduction to paper width. Use no shadows heavier than a subtle 1–2 px elevation, no gradients encoding magnitude, and no decorative imagery.

ABSOLUTE DATA AND NO-INVENTION CONSTRAINTS
Use only the exact committed values in the whitelist. Do not calculate, display, or imply deltas, totals, averages, ranges, rankings, best settings, monotonicity, recovery, degradation, significance, or causal interpretation. Do not invent or render confidence intervals, bootstrap intervals, p-values, significance stars, error bars, uncertainty bands, sample-level dots, curves, axes, ticks, scales, gridlines, legends, color bars, trend arrows, bar lengths, pie slices, sparklines, line charts, bar charts, or heatmaps. Do not alter decimal precision, percent signs, λ notation, gain/loss ordering, or row order. Do not add methods, controls, metrics, sample counts, timing values, footnotes, citations, logos, watermarks, authors, or venue marks. Do not use a dashboard, spreadsheet screenshot, marketing infographic, or photorealistic style.

EXACT VISIBLE-TEXT WHITELIST
All visible text in the figure must use only the following exact English labels:
1. "Measured 40-example OmniBench pilot"
2. "A"
3. "Accuracy"
4. "Full input | 50.0%"
5. "Visual only | 30.0%"
6. "Audio only | 25.0%"
7. "Raw MCD λ=0.25 | 42.5%"
8. "Raw MCD λ=0.5 | 45.0%"
9. "Raw MCD λ=1 | 37.5%"
10. "Raw MCD λ=2 | 20.0%"
11. "B"
12. "Gain / loss"
13. "λ=0.25 | 0/3"
14. "λ=0.5 | 3/5"
15. "λ=1 | 6/11"
16. "λ=2 | 4/16"
17. "C"
18. "Controls at λ=1"
19. "Shuffled visual | 40.0%"
20. "VCD-style | 45.0%"
21. "Positive scaling | 50.0%"
22. "D"
23. "Sequential MCD CPU latency"
24. "1.78× baseline"

Render each whitelisted label exactly once. Preserve capitalization, spacing, punctuation, slash direction, percent signs, decimal precision, λ, and × verbatim. Do not render any text outside this whitelist. The 2×2 grid instructions, panel descriptions, list numbers, and prompt headings are structural instructions only and must not appear in the figure.

Final output: one high-resolution four-panel academic comparison figure composed only of exact numeric cards and table-like rows, with no free-form generated chart and no invented statistical content.
```

## 4. Technical roadmap

```text
Create a publication-ready technical roadmap for an ICLR/WACV multimodal machine-learning experiment, optimized for the current Cursor image generator or another strong text-rendering model. Use a wide landscape white canvas, a rigorous left-to-right CS/ML pipeline, Soft Tech scientific pastels, rounded cards, thin precise arrows, crisp sans-serif text, and clear grouping. The roadmap must show the immutable evaluation flow from a task-balanced OmniBench subset through two frozen Qwen2.5-Omni-7B forward passes, stored first-token option logits, an offline λ sweep, and paired evaluation. It must look like a conference methods figure, not a project-management roadmap, dashboard, poster, or training architecture.

EXACT TOPOLOGY
Use one locked left-to-right pipeline with six functional positions:
dataset subset → example contents → exactly two parallel frozen-model branches → paired logit storage → offline λ sweep → evaluation outputs.
A separate timing connector may run from the enclosing two-forward-pass group directly to the CPU-latency output card, as specified below. No other branch, loop, shortcut, or feedback path is allowed.

POSITION 1 — DATASET SUBSET, FAR LEFT
Draw one compact dataset card containing a stack of abstract sample sheets. State that the subset is task-balanced and contains exactly 40 examples. Do not depict a full-benchmark evaluation, random population sample, class distribution, task names, or per-task counts.

POSITION 2 — EXAMPLE CONTENTS
Draw exactly four small tiles in one enclosing example card: an image tile, an audio-waveform tile, a question-bubble tile, and an option tile containing A, B, C, and D. The option tile represents the four constrained answer labels. Do not show sample-specific media, answer content, a correct-option marker, token IDs, or generated prose.

POSITION 3 — EXACTLY TWO FROZEN FORWARD PASSES
From the example card, create exactly two outgoing routes:
1. Upper blue full route: image, audio, question, and options A-D enter the upper full-branch card.
2. Lower amber visual-only route: image, question, and options A-D enter the lower visual-only-branch card. Audio must stop at the source and must have no glyph, line, or connector entering the lower branch.

The two branch cards must be equal in size and vertically aligned. Each must contain an identical model core and the exact same repeated model label, showing one frozen Qwen2.5-Omni-7B checkpoint with shared weights. Do not draw two checkpoints, training, parameter updates, or model selection. Each branch runs once per example and emits exactly one first-token vector over options A, B, C, and D. Draw each vector as four equal cells labeled by the single option letters; do not add vocabulary tokens outside A-D, probabilities, softmax bars, axes, or autoregressive token sequences.

POSITION 4 — PAIRED LOGIT STORAGE
Route the two four-logit vectors independently into one central storage card. The routes may meet only at this storage card. The card stores four full-branch logits and four visual-only-branch logits per example. It is not a database of images, embeddings, generated answers, gradients, or model states.

POSITION 5 — OFFLINE λ SWEEP
Draw exactly one arrow from logit storage to one violet offline-sweep card. Inside the card, show the exact ordered set {0.25, 0.5, 1, 2} and identify λ=1 as primary. Visually emphasize λ=1 with a thin outline only. The sweep is derived offline from the same stored logits; no arrow may return to either model branch, and no λ value may trigger another forward pass. Do not depict hyperparameter optimization, model selection, tuning on outcomes, or stochastic generation.

POSITION 6 — EVALUATION OUTPUTS, FAR RIGHT
Draw exactly one arrow from the offline-sweep card into one enclosing evaluation group containing four equal output cards:
1. exact option accuracy;
2. gain/loss relative to paired full-input outcomes;
3. 10,000 paired bootstrap resamples;
4. a two-sided paired exact test.

These cards name evaluation operations only. Do not invent or display any accuracy value, gain/loss count, confidence interval, p-value, significance result, or selected best λ in this roadmap.

TIMING CONNECTION
Enclose the two model branches within one subtle forward-pass boundary. From that enclosing boundary, draw one separate thin gray timing connector directly to one CPU-latency card placed beneath the evaluation group. This timing path measures sequential CPU forward latency and must not originate from the bootstrap or exact-test cards. Do not display a latency value, seconds, GPU estimate, memory value, throughput, or hardware specification.

VISUAL SYSTEM
Use ice blue for the full branch, pale amber for the visual-only branch, lavender for stored-logit arithmetic and the λ sweep, pale sage for evaluation, and warm gray for timing. Use identical geometry for the repeated model cores and identical four-cell geometry for both logit vectors. Keep arrows orthogonal or gently curved, with solid lines for data flow and one thin gray line for timing. Avoid decorative icons unrelated to the specified objects. Keep the pipeline readable in grayscale through position and connector routing.

SCIENTIFIC AND NO-INVENTION CONSTRAINTS
Strictly preserve: a task-balanced 40-example OmniBench subset; each example has image, audio, question, and four options A-D; the full and visual-only branches use the same frozen Qwen2.5-Omni-7B; visual-only omits audio but retains image, question, and options; each branch stores four first-token option logits; every λ is computed offline from those stored logits; the sweep is exactly {0.25, 0.5, 1, 2}; λ=1 is primary; evaluation reports exact option accuracy, gain/loss, paired bootstrap, a paired exact test, and sequential CPU latency. Do not add an audio-only branch, shuffled-visual branch, VCD-style branch, positive-scaling branch, encoder, decoder, attention map, fusion module, loss, gradient, optimizer, training loop, fine-tuning, cache, generated answer, data augmentation, cross-validation, validation set, deployment stage, or downstream application. Do not imply that the λ sweep changes preprocessing, model state, or stochastic generation. Do not invent task labels, samples, values, distributions, CIs, p-values, significance marks, charts, axes, legends, color bars, equations, timings, memory values, GPU behavior, or additional metrics. No logo, watermark, citation, author name, venue logo, step numbers, page furniture, photorealism, heavy 3D, biomedical styling, materials-science styling, or marketing effects.

EXACT VISIBLE-TEXT WHITELIST
All visible text in the figure must use only the following exact English labels:
1. "Technical roadmap"
2. "Task-balanced OmniBench subset"
3. "40 examples"
4. "Image"
5. "Audio"
6. "Question"
7. "Options A-D"
8. "Full branch"
9. "Image + audio + question + options A-D"
10. "Visual-only branch"
11. "Image + question + options A-D (no audio)"
12. "Same frozen Qwen2.5-Omni-7B"
13. "First-token option logits"
14. "A | B | C | D"
15. "Store four logits per branch"
16. "Offline λ sweep"
17. "{0.25, 0.5, 1, 2}"
18. "Primary λ=1"
19. "Exact option accuracy"
20. "Gain / loss"
21. "10,000 paired bootstrap resamples"
22. "Two-sided paired exact test"
23. "Sequential CPU latency"

Render "Same frozen Qwen2.5-Omni-7B" exactly twice, once in each branch. Render "First-token option logits" exactly twice, once above each branch output vector. Render "A | B | C | D" exactly twice, once inside each vector. Render every other whitelisted label exactly once. Preserve capitalization, hyphenation, braces, commas, spaces, λ, numerals, and vertical bars verbatim. Do not render any title, annotation, legend, paragraph, footnote, random token, or structural field outside this whitelist. Prompt headings, position names, list numbers, and topology descriptions are instructions only and must not appear in the image.

Final output: one self-contained high-resolution technical roadmap with exact topology, exact labels, and no scientific content beyond the locked evaluation protocol.
```
