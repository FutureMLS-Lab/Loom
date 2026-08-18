# WSDM 2027 CMT Registration: Remaining Three Papers

This file contains the three papers currently not recommended for priority
submission. The titles, abstracts, and subject areas are plain-text,
copy-paste-ready CMT registration fields if these papers are registered.

- Enter authors, conflicts, and other administrative metadata separately.
- Internal automated reviews are included only for selection context; do not
  paste them into CMT.

## Registration Summary

| ID | Status | Final round | Primary subject area |
|---|---|---:|---|
| `wsdm-05` | Delivered | 6 | Web Mining and Content Analysis → Web recommender systems and algorithms |
| `wsdm-11` | Delivered | 5 | Foundation Models and Agentic Systems → Evaluation and benchmarking of foundation models in search/mining |
| `wsdm-12` | Delivered | 8 | Web Mining and Content Analysis → Web recommender systems and algorithms |

## 1. wsdm-05

**Status:** Delivered, Round 6

### Title

When Does One Step Suffice? A Four-Gate Audit of Diffusion Recommendation Distillation

### Subject Areas

- **Primary:** Web Mining and Content Analysis → Web recommender systems and algorithms
- **Secondary:** Web Mining and Content Analysis → Scalable algorithms for mining web data, opinion mining and sentiment analysis
- **Secondary:** Web Search → Search benchmarking and evaluation
- **Secondary:** Privacy, Fairness, Interpretability → Model and algorithm transparency

### Abstract

A one-call deployment claim bundles four different statements: the teacher is competent, iterative sampling helps, the student preserves the teacher, and the result has serving value. We introduce a four-gate audit that tests these claims separately and scopes every decision to a checkpoint and protocol.

Using a common full-catalog harness over MovieLens-1M and Steam, together with a native Amazon Beauty DiffuRec reproduction, we compare diffusion teachers, iterative sampling, one-pass controls, and endpoint regression under matched evaluation. Utility-tuned SASRec outperforms the audited teachers in all 16 metric-level comparisons, and DDIM-1 outperforms the multi-step endpoint in 15 of 16; the remaining comparison is inconclusive. Endpoint regression sometimes preserves aggregate utility under simultaneous noninferiority tests, yet exact teacher top-10 set identity never exceeds 20.5%. The contribution is a falsifiable deployment contract and checkpoint-level evidence, not a broad claim that one step or many steps universally wins.

### Internal Automated Review — Do Not Paste into CMT

Round 6 panel score: **4/10 · soundness 2/4 · weak reject**.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 5/10 | 3/4 | 3/4 | 2/4 | Borderline |
| Cursor Grok 4.5 | 4/10 | 2/4 | 2/4 | 2/4 | Weak reject |

## 2. wsdm-11

**Status:** Delivered, Round 5

### Title

Query-Term Repetition Repels LLM Selectors from Weak Result Cards: A Controlled Audit

### Subject Areas

- **Primary:** Foundation Models and Agentic Systems → Evaluation and benchmarking of foundation models in search/mining
- **Secondary:** Web Search → Search user behavior and log analysis; Search user interfaces and interaction
- **Secondary:** Foundation Models and Agentic Systems → Retrieval, indexing, and ranking with foundation models
- **Secondary:** Web Search → Query analysis and query processing
- **Secondary:** Privacy, Fairness, Interpretability → Model and algorithm transparency

### Abstract

Implicit feedback is useful only when selection remains aligned with landing-page relevance. We audit one proposed surface intervention for deterministic LLM selectors: replacing generic metadata with repeated query terms in weak result cards. In paired result-card displays, lower-relevance cards contain either one copy or repeated copies of the same query terms, while answer content, landing page, judgment, card length, unique term set, topic, rank schedule, and all higher-relevance cards remain fixed.

Across four confirmatory selectors, repetition reduces false-choice rates by 2.3–6.2 percentage points, with Holm-adjusted p < .001 in every case. A short warning about repeated query words produces no detectable interaction with this effect and therefore does not explain an earlier hardened-prompt contrast. Exact frequency does not explain an earlier synthetic same-query effect that also changed topic and plausibility. We make no human-click claim, and we treat an earlier answer-rewrite audit without independent regrades as conditional evidence only.

### Internal Automated Review — Do Not Paste into CMT

Round 5 panel score: **4/10 · soundness 3/4 · weak reject**.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 2/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 5/10 | 3/4 | 2/4 | 2/4 | Weak reject |
| Cursor Grok 4.5 | 4/10 | 3/4 | 3/4 | 2/4 | Weak reject |

## 3. wsdm-12

**Status:** Delivered, Round 8

### Title

How Small Can You Go? Spectral Bounds for Recommendation Subsets

### Subject Areas

- **Primary:** Web Mining and Content Analysis → Web recommender systems and algorithms
- **Secondary:** Web Mining and Content Analysis → Large-scale graph analysis
- **Secondary:** Web Mining and Content Analysis → Scalable algorithms for mining web data, opinion mining and sentiment analysis
- **Secondary:** Privacy, Fairness, Interpretability → Model and algorithm transparency

### Abstract

How many original-identity interactions are necessary—and how many are actually sufficient—to preserve a collaborative-filtering propagation subspace? We separate these questions. For a source graph's rank-r normalized-biadjacency frame, every unweighted edge subset incurs joint projector loss at least the source leverage mass outside its retained user and item coordinates. Requiring an identifiable cutoff adds a component-multiplicity floor. The combined floor is asymptotically attainable on a block-complete family.

Real recommendation graphs are different. We audit three public graphs at ranks 2, 4, and 8. At rank eight, the necessary floors retain at most 2.1% of edges, while the first observed identifiable witnesses require at least 33%. A connectivity-preserving construction also remains far above the floor. The theorem therefore rules out ultra-small subsets but does not predict the attainable projector-collapse budget on these graphs. We report a lower-to-upper interval rather than call the necessary floor tight. The result applies to unweighted same-identity subsets, not synthetic identities, reweighted sparsifiers, arbitrary finite codes, or ranking utility.

### Internal Automated Review — Do Not Paste into CMT

Round 8 panel score: **4/10 · soundness 2/4 · weak reject**.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Cursor Grok 4.5 | 4/10 | 2/4 | 2/4 | 2/4 | Weak reject |

## CMT Registration Checklist

For each paper:

- Copy the title exactly from the `Title` field.
- Copy both abstract paragraphs into the CMT abstract field.
- Select the listed primary subject area first, then the suggested secondary
  areas that CMT permits.
- Enter authors, affiliations, conflicts, and contact information separately.
- Do not paste the internal automated-review section into CMT.
