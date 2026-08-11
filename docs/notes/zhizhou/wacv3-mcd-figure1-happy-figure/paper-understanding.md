# Paper understanding

## Source and extraction

- Paper: *Testing Modality-Contrastive Decoding for Dominant-Modality Bias in Omnimodal Models*.
- Primary source: `main.pdf`, parsed with the Happy Figure skill extractor using `pdftotext` (32,444 extracted characters).
- Extractor limitation: section detection was incomplete because the PDF includes line-numbered conference formatting. The extracted Figure 1 context was usable; the LaTeX source was consulted only to resolve the paper title, exact branch inputs, exact MCD equation, Figure 1 caption, and the statistical interpretation of the pilot outcome.
- Reference figure inspected: `figures/teaser.png` (original Figure 1).

## Research message selected for the redraw

This is a CS/ML multimodal-decoding teaser with a dual-stream method-plus-measured-outcome structure. It tests whether subtracting a hypothesized visual-dominant output distribution can recover cross-modal reasoning.

The full context is image + audio + question. A full branch and a visual-only branch run through the same frozen model/checkpoint with the same question; only the visual-only branch omits audio. Their option-logit vectors are combined by modality-contrastive decoding:

`l_F - λ l_V`

The measured result is a task-balanced 40-example OmniBench pilot. The only outcome values to visualize are:

- 50.0% baseline
- 37.5% MCD at λ=1
- 1.78× CPU latency
- No recovery

“No recovery” is intentionally narrow. The unit-strength point estimate is lower, but its paired confidence interval includes zero; therefore the figure must not imply a statistically significant degradation or a general population-level harm.

## Figure brief

- **Goal:** explain the complete two-branch MCD computation and place the measured pilot outcome immediately beside it.
- **Content community:** ICLR/ICML/NeurIPS with CVPR/WACV-compatible multimodal visual language.
- **Figure type:** graphical teaser / paper main figure, using a left-to-right dual-stream method followed by one measured-outcome card.
- **Inputs:** one explicit full-input source containing image, audio, and question.
- **Upper branch:** full branch; image + audio + question; same frozen model; produces full option logits `l_F`.
- **Lower branch:** visual-only branch; image + question and explicitly no audio; same frozen model; produces visual-only option logits `l_V`.
- **Merge:** both option-logit outputs enter one MCD subtraction module; no earlier fusion or cross-branch connection.
- **Outcome:** a single OmniBench pilot card containing exactly the three requested measurements and the conclusion “No recovery.”
- **Reading order:** full input → two parallel branches → MCD subtraction → measured outcome.
- **Default rendering target:** model-neutral but friendly to gpt-image-2 or another strong text-rendering model; wide landscape composition, publication-readable at two-column width.

## Reference-figure style observations

- Wide white canvas with a single left-to-right narrative.
- Rounded rectangular cards, thin color-coded outlines, generous whitespace, and restrained academic colors.
- Blue upper full branch, orange lower visual-only branch, purple subtraction module, and a distinct outcome card.
- Numbered badges and simple modality/logit glyphs create fast scanning.
- Orthogonal or gently bent arrows make the branch topology explicit.
- Bold short headers with smaller supporting labels; no dense prose.
- The original bar glyphs are schematic option-logit symbols, not empirical charts.

The redraws may transfer this hierarchy, branch color logic, clean cards, and arrow discipline. They must not copy pixel-level geometry, invent measurements, or turn schematic logit glyphs into quantitative charts.

## Non-negotiable scientific and visual boundaries

1. Do not add, remove, merge, swap, or reorder the full-input, full-branch, visual-only-branch, MCD, or OmniBench-outcome modules.
2. Audio must enter the full branch and must not enter the visual-only branch.
3. Image and question must enter both branches.
4. The two branches must be visibly identified as using the same frozen model; do not depict separate trained models, fine-tuning, gradients, parameter updates, or learned fusion.
5. MCD must subtract visual-only option logits from full option logits as `l_F - λ l_V`; do not reverse the operands or replace subtraction with fusion, averaging, attention, or concatenation.
6. Do not invent extra branches, modality gates, encoders, losses, datasets, benchmarks, sample counts, confidence intervals, p-values, significance stars, curves, axes, legends, or additional metrics.
7. The three numerical strings must remain exactly 50.0%, 37.5% at λ=1, and 1.78× CPU latency.
8. “No recovery” must be presented as a measured pilot conclusion, not as proof of statistically significant degradation.
9. Any mini bars are qualitative option-logit glyphs only: no axes, ticks, values, error bars, or quantitative visual encoding.
10. All visible text must be restricted to the exact whitelist embedded independently in each final prompt.
