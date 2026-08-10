# Figure 1 redraw prompts

## Variant 1 — Strict ICLR/WACV conference paper figure

```text
Create a publication-ready wide landscape teaser figure for an ICLR/WACV computer-vision and machine-learning paper. The subject is multimodal decoding, and the figure must combine a dual-stream method schematic with one measured-outcome panel. Use a clean white background, restrained flat vector graphics, thin consistent outlines, crisp sans-serif typography, generous whitespace, and high legibility when reduced to a two-column paper width. The result must look like a rigorous conference-paper figure, not a poster, dashboard, slide, or commercial infographic.

COMPOSITION AND EXACT TOPOLOGY
Use one unbroken left-to-right reading order with five functional positions: full input at far left; two parallel branches in the middle-left; one MCD merge module in the middle-right; one OmniBench pilot outcome card at far right.

At far left, draw one rounded input card. Inside it, show three simple unlabeled modality glyphs stacked vertically: a landscape-image thumbnail, an orange audio waveform, and a plain question/speech-bubble shape. The card represents the complete full input and must explicitly state that it contains image, audio, and question.

From the input card, create exactly two outgoing data routes:
1. The upper blue route carries image, audio, and question into the upper full branch.
2. The lower orange route carries only image and question into the lower visual-only branch. The audio waveform or audio line must visibly stop before this lower route and must never enter or touch the visual-only branch.

Place the upper and lower branch cards in strict vertical alignment. The upper card is the full branch; the lower card is the visual-only branch. Inside each branch, draw the same frozen-model glyph with identical geometry, size, internal pattern, and cool-gray/ice-blue treatment. Render the exact label "Same frozen model" inside both branch cards, once per branch, to make parameter sharing unmistakable. Do not depict two differently trained models. The full branch receives image + audio + question and emits a compact qualitative four-bar option-logit glyph labeled as full option logits l_F. The visual-only branch receives image + question with no audio and emits a corresponding qualitative four-bar option-logit glyph labeled as visual-only option logits l_V. These glyphs are schematic vectors only, not measured charts: no axes, ticks, scales, values, legends, or error bars.

Route the upper l_F output and lower l_V output independently into one purple MCD module. The two arrows may meet only at this module. Inside it, show a clear subtraction operation and the exact formula "l_F - λ l_V". The upper full-logit input is the positive first operand; the lower visual-only-logit input is multiplied by λ and subtracted. Do not reverse the operands. From the MCD module, draw exactly one rightward arrow into the outcome card.

At far right, draw one compact OmniBench pilot card. Present the three measurements as three aligned text rows, followed by the conclusion. Use no bar chart and no visual encoding that suggests statistical significance. "No recovery" is a narrow pilot conclusion: give it firm but neutral emphasis in dark plum or muted burgundy, not a danger treatment. Keep 50.0% baseline and 37.5% MCD at λ=1 at equal typographic status. Do not add a down arrow, loss icon, significance star, p-value, confidence interval, or wording such as significant, degraded, worse, failure, or harm.

COLOR AND FORM
Use white as the canvas; blue for the full-input/full-branch route; orange for the visual-only route; purple for MCD; and a restrained neutral or muted burgundy outline for the pilot card. Use rounded rectangles with approximately 8–12 px corner radii at final raster scale, 1.5–2 px outlines, consistent arrowheads, and no heavy shadow. Very light pastel fills at 8–12% opacity are acceptable. Maintain strong contrast and color-blind-friendly distinctions. Keep all modules fully separated with no overlap.

SCIENTIFIC INVARIANTS
Strictly preserve: full input = image + audio + question; full and visual-only branches use the same frozen model; visual-only omits audio while retaining image and question; MCD subtracts option logits as l_F - λ l_V; measured OmniBench pilot values are 50.0% baseline, 37.5% MCD at λ=1, and 1.78× CPU latency; conclusion is No recovery without any claim of statistically significant degradation.

STRONG NO-INVENTION CONSTRAINTS
Do not add, remove, merge, duplicate, swap, or reorder any scientific module. Do not add any extra modality branch, audio-only branch, shuffled branch, encoder, decoder, attention map, fusion block, training loop, loss, gradient, parameter update, fine-tuning step, retrieved context, dataset sample, output answer, or benchmark. Do not invent quantitative data, additional values, curves, confidence intervals, p-values, significance marks, axes, scales, legends, color bars, tables, or empirical distributions. Do not turn the logit glyphs into evidence plots. Do not imply that the lower point estimate is statistically significant. No logo, watermark, citation, author name, venue logo, decorative mascot, photorealism, biomedical style, materials-science style, glossy 3D, or marketing effects.

EXACT VISIBLE-TEXT WHITELIST
All visible text in the figure must use only the following exact labels:
1. "Can dominant-modality subtraction recover cross-modal reasoning?"
2. "Full input"
3. "Image + audio + question"
4. "Full branch"
5. "Visual-only branch"
6. "Image + question (no audio)"
7. "Same frozen model"
8. "Full option logits l_F"
9. "Visual-only option logits l_V"
10. "MCD"
11. "Subtract option logits"
12. "l_F - λ l_V"
13. "OmniBench pilot"
14. "50.0% baseline"
15. "37.5% MCD at λ=1"
16. "1.78× CPU latency"
17. "No recovery"

Render "Same frozen model" exactly twice, once in each branch. Render every other whitelisted label exactly once. Do not render any title, legend, paragraph, footnote, panel letter, step number, icon text, random text, or structural field outside this list. Instructional headings such as COMPOSITION, TOPOLOGY, COLOR, SCIENTIFIC INVARIANTS, and WHITELIST are prompt structure only and must not appear in the figure.

Final output: one self-contained high-resolution landscape figure with sharp vector-like edges, no surrounding paper mockup, and no content outside the specified topology.
```

## Variant 2 — Premium academic graphical abstract

```text
Create a premium academic graphical abstract for a top-tier ICLR/WACV multimodal machine-learning paper. The figure must remain a technically exact CS system diagram while receiving a refined graphical-abstract finish: a spacious white-to-warm-white canvas, subtle layered cards, delicate soft shadows, restrained translucent fills, low-saturation warm–cool balance, tactile but 2D-first interface surfaces, and a strong visual center around the MCD subtraction. It should feel polished enough for a paper teaser or project page, but never like a marketing poster, dashboard collage, biomedical illustration, or generic icon-pack flowchart.

NARRATIVE AND EXACT TOPOLOGY
Build a wide left-to-right composition with a clear dual-stream center. The only scientific path is:
full input → {upper full branch, lower visual-only branch} → one MCD subtraction module → one OmniBench pilot outcome card.

Make the far-left full-input card a refined vertical stack of three small modality tiles: a miniature image tile, a narrow audio-wave tile, and a question tile. Keep these tiles illustrative and unlabeled except for the approved card text. The card must visibly establish the complete input as image + audio + question.

Create exactly two routes from this source. The upper route, in calm cobalt/teal-blue, transports all three modality glyphs into the full branch. The lower route, in warm amber/orange, transports a duplicated image glyph and question glyph into the visual-only branch, while the audio glyph remains behind in the full-input card. Show a clean visual cutoff or gap for audio before the lower route; do not use an X, prohibition word, or any unlisted symbol. Audio must have no connector into the lower branch.

Arrange two elegant branch cards as an upper–lower pair with identical dimensions. Each card contains an identical frozen-model core: same silhouette, same internal chip/token motif, same dimensions, same color treatment, and the exact repeated label "Same frozen model". The upper card receives image, audio, and question and produces a compact four-element blue option-logit ribbon labeled as full option logits l_F. The lower card receives image and question only and produces a compact four-element orange option-logit ribbon labeled as visual-only option logits l_V. Treat both ribbons as qualitative abstract vectors, not measured plots; use no coordinate frame, scale, values, ticks, or implied probability heights.

Let the two branch outputs curve gently but independently toward a visually dominant central MCD card. Use a refined translucent lavender panel with a precise thin violet outline and a subtle inner glow or soft shadow. The upper l_F ribbon enters as the first positive operand; the lower l_V ribbon enters below and is subtracted with λ. Place the exact formula "l_F - λ l_V" prominently inside, with "MCD" and "Subtract option logits" as controlled supporting labels. The streams may meet only inside this MCD card. From it, send one restrained violet arrow to the final pilot card.

Design the far-right OmniBench pilot card as a refined editorial result panel, not a chart. Use three evenly spaced measurement rows and a separated conclusion line. Preserve the exact values and wording. Present "No recovery" as a sober measured-sample takeaway in dark plum, with no alarm icon, red downward arrow, broken-object metaphor, or visual claim of significance. Keep the baseline and unit-MCD rows typographically balanced; do not make 37.5% appear as a statistically certified decline. The card may have a muted rose or warm-gray edge, but avoid saturated failure red.

VISUAL TREATMENT
Use a low-saturation palette: cobalt/teal-blue for full input and full branch, amber/orange for the visual-only branch, lavender/violet for MCD, and warm gray with restrained plum for the outcome. Apply depth only through 2–4 px soft shadows, very slight card elevation, translucent edge highlights, and layered paper/interface surfaces. Avoid perspective distortion and heavy 3D. Use crisp modern academic sans-serif typography, clear hierarchy, and generous negative space. Keep arrows thin, deliberate, and unambiguous. The central method should be the visual focus, while the outcome card remains immediately readable.

SCIENTIFIC INVARIANTS
Strictly preserve: full input = image + audio + question; the upper full branch and lower visual-only branch use the same frozen model; visual-only omits audio and retains image + question; MCD subtracts option logits as l_F - λ l_V; OmniBench pilot reports exactly 50.0% baseline, 37.5% MCD at λ=1, and 1.78× CPU latency; the conclusion is No recovery, with no implication of statistically significant degradation.

STRONG NO-INVENTION AND TOPOLOGY LOCK
Do not add, delete, merge, duplicate, reorder, or reinterpret the five functional positions. Do not connect audio to the visual-only branch. Do not merge branches before MCD. Do not reverse l_F and l_V. Do not depict independent model training, two different checkpoints, tunable parameters, gradients, fine-tuning, fusion learning, or a third stream. Do not add encoders, tokenizers, attention maps, losses, datasets, sample counts, option letters, generated answers, auxiliary controls, or downstream applications. Do not invent any value, empirical curve, chart, axis, error bar, confidence interval, p-value, significance star, legend, color bar, or comparison beyond the three whitelisted measurements. Do not use decorative science imagery that could be mistaken for evidence. No logos, watermarks, citations, venue marks, photorealistic devices, mascots, glossy marketing gradients, dramatic lighting, biomedical forms, or materials-science motifs.

EXACT VISIBLE-TEXT WHITELIST
All visible text in the figure must use only the following exact labels:
1. "Can dominant-modality subtraction recover cross-modal reasoning?"
2. "Full input"
3. "Image + audio + question"
4. "Full branch"
5. "Visual-only branch"
6. "Image + question (no audio)"
7. "Same frozen model"
8. "Full option logits l_F"
9. "Visual-only option logits l_V"
10. "MCD"
11. "Subtract option logits"
12. "l_F - λ l_V"
13. "OmniBench pilot"
14. "50.0% baseline"
15. "37.5% MCD at λ=1"
16. "1.78× CPU latency"
17. "No recovery"

Render "Same frozen model" exactly twice, once in each branch. Render every other whitelisted label exactly once. Do not render any title, legend, paragraph, footnote, panel letter, step number, icon text, random text, or structural field outside this list. The organizational headings in this prompt are instructions only and must not appear in the artwork.

Final output: one cohesive high-resolution landscape graphical abstract, technically exact, refined and memorable, with no surrounding webpage, paper mockup, caption, or extraneous decoration.
```

## Variant 3 — Minimal flat vector schematic

```text
Create a minimal flat vector schematic for a CS/ML multimodal-decoding paper. Use a wide landscape layout, pure white background, no texture, no gradient, no shadow, no perspective, and no decorative elements. Favor geometric economy, strong alignment, uniform 1.5–2 px strokes, compact rounded rectangles, simple line icons, and a restrained color-blind-friendly palette. The figure must remain complete and scientifically explicit despite the minimal treatment.

LOCKED LAYOUT AND DATA FLOW
Use a strict left-to-right grid with four columns:
Column 1: one full-input card.
Column 2: two parallel branch cards, full branch above and visual-only branch below.
Column 3: one vertically centered MCD subtraction card.
Column 4: one OmniBench pilot outcome card.

In Column 1, place three unlabeled outline glyphs inside the full-input card: image, audio waveform, and question bubble. The accompanying approved text must state image + audio + question.

Draw exactly two outgoing routes:
- A blue upper arrow carries image, audio, and question to the full branch.
- An orange lower arrow carries image and question only to the visual-only branch.
Terminate the audio component before the lower route begins. Do not draw any audio glyph, waveform, audio connector, or audio-colored segment inside or entering the visual-only branch.

In Column 2, make the two branch cards equal in width and height. Put the same simple frozen-model chip glyph in each card, identical pixel-for-pixel in shape and color. Place the exact label "Same frozen model" once in each. The upper card emits a blue four-cell option-logit strip labeled as full option logits l_F. The lower card emits an orange four-cell option-logit strip labeled as visual-only option logits l_V. The strips may vary in cell fill only as a qualitative vector symbol; they must not have bars with a baseline, axes, ticks, scales, numbers, legends, or data-chart appearance.

In Column 3, draw one purple MCD card receiving exactly two arrows: upper l_F and lower l_V. Place the formula "l_F - λ l_V" at its center. The upper full branch is the first operand; the lower visual-only branch is the subtracted operand. No branch may connect to the other branch, and neither branch may bypass MCD. Draw exactly one arrow from MCD to Column 4.

In Column 4, use a plain outlined result card with four text rows: the three requested measurements and the narrow conclusion. Use equal-size text for the two accuracy rows. Set "No recovery" in semibold dark plum, not bright red. Do not use a chart, trend arrow, thumbs-down, warning triangle, failure icon, broken line, or any other visual cue implying statistically significant degradation.

STYLE
Use only flat fills: pale blue for the full route, pale orange for the visual-only route, pale lavender for MCD, and white or very pale neutral for the outcome. Use dark charcoal text, consistent arrowheads, square or gently rounded line caps, and abundant whitespace. No numbered badges. No title banner container. No pictorial scenery. Make the figure readable in grayscale through line routing and position, not color alone.

SCIENTIFIC INVARIANTS
The complete full input is image + audio + question. Both branches use the same frozen model. The visual-only branch omits audio but keeps image and question. MCD subtracts visual-only option logits from full option logits using l_F - λ l_V. The only measured OmniBench pilot values are 50.0% baseline, 37.5% MCD at λ=1, and 1.78× CPU latency. The only conclusion is No recovery, and this must not be framed as statistically significant degradation.

ABSOLUTE NO-INVENTION CONSTRAINTS
Do not add, remove, merge, duplicate, reorder, rename, or reinterpret any module or arrow. Do not add a third branch, audio-only branch, shuffled-image branch, separate model checkpoint, modality encoder, fusion layer, attention, training, loss, gradient, fine-tuning, memory, cache, answer output, dataset sample, option letters, or application. Do not invent numbers, sample size, confidence interval, p-value, significance symbol, curve, axis, table, chart, legend, color bar, or extra result. Do not use bar height as measured evidence. No logo, watermark, citation, author, venue mark, page furniture, decoration, 3D, texture, shadow, photorealism, cartoon, biomedical styling, materials-science styling, or marketing styling.

EXACT VISIBLE-TEXT WHITELIST
All visible text in the figure must use only the following exact labels:
1. "Can dominant-modality subtraction recover cross-modal reasoning?"
2. "Full input"
3. "Image + audio + question"
4. "Full branch"
5. "Visual-only branch"
6. "Image + question (no audio)"
7. "Same frozen model"
8. "Full option logits l_F"
9. "Visual-only option logits l_V"
10. "MCD"
11. "Subtract option logits"
12. "l_F - λ l_V"
13. "OmniBench pilot"
14. "50.0% baseline"
15. "37.5% MCD at λ=1"
16. "1.78× CPU latency"
17. "No recovery"

Render "Same frozen model" exactly twice, once in each branch. Render every other whitelisted label exactly once. Do not render any title, legend, paragraph, footnote, panel letter, step number, icon text, random text, or structural field outside this list. Layout headings and bullet markers in this prompt are instructions only and must never appear in the figure.

Final output: one clean high-resolution flat vector-style landscape figure with no border around the overall canvas and no surrounding mockup.
```
