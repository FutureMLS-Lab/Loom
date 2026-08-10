# Worked Example: Modality-Contrastive Decoding

[`example.png`](example.png) demonstrates the strict conference-paper treatment.

## Paper understanding

The paper tests whether subtracting a visual-only output distribution from a
full image-audio output distribution recovers cross-modal reasoning.

## Figure Brief

- **Content community:** ICLR/ICML/NeurIPS with CVPR/WACV-compatible multimodal
  visual language.
- **Visual treatment:** strict conference figure.
- **Figure type:** graphical teaser / paper main figure.
- **Reading order:** full input → two parallel frozen-model branches → MCD
  subtraction → measured OmniBench outcome.
- **Full branch input:** image + audio + question.
- **Visual-only branch input:** image + question, explicitly no audio.
- **Shared component:** the same frozen Qwen2.5-Omni-7B checkpoint.
- **Exact operation:** `ℓ_F − λℓ_V`.
- **Measured pilot:** task-balanced 40-example OmniBench subset.

## Fact lock

Exact outcome strings:

```text
50.0% baseline
37.5% MCD at λ=1
1.78× CPU latency
No recovery
```

`No recovery` is narrow: the point estimate decreases, but the paired
confidence interval includes zero. The figure must not claim significant
degradation or general harm.

## Rejection conditions

Reject a candidate if:

- audio enters the visual-only branch;
- the two branches appear to use separately trained models;
- subtraction becomes `ℓ_V − λℓ_F`, fusion, averaging, or attention;
- the image adds training, gradients, a third branch, another dataset, or a
  fabricated result;
- an exact value, symbol, decimal place, or qualifier changes;
- qualitative option-logit glyphs become quantitative charts.

## Why this candidate was selected

The bundled candidate explicitly preserves:

- both branch inputs;
- the same frozen model;
- full and visual-only option logits;
- subtraction direction;
- the three measured values;
- the restrained negative conclusion.

More decorative candidates can look stronger while silently adding numbered
badges, removing the explicit no-audio label, or weakening topology. Under this
skill, scientific completeness outranks polish.
