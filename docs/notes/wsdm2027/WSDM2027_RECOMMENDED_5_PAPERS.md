# WSDM 2027 CMT Registration: Recommended Five Papers

This file contains the five papers currently recommended for priority
submission. The titles, abstracts, and subject areas are plain-text,
copy-paste-ready CMT registration fields.

- Enter authors, conflicts, and other administrative metadata separately.
- Internal automated reviews are included only for selection context; do not
  paste them into CMT.
- `wsdm-06` is still in Round 3. Its title is ready, but its abstract and review
  must be refreshed after delivery.

## Registration Summary

| ID | Status | Final/current round | Primary subject area |
|---|---|---:|---|
| `wsdm-03` | Delivered | 10 | Foundation Models and Agentic Systems → Retrieval, indexing, and ranking with foundation models |
| `wsdm-04` | Delivered | 7 | Foundation Models and Agentic Systems → Evaluation and benchmarking of foundation models in search/mining |
| `wsdm-06` | In progress; abstract provisional | 3 | Web Mining and Content Analysis → Web recommender systems and algorithms |
| `wsdm-09` | Delivered | 6 | Web Mining and Content Analysis → Web recommender systems and algorithms |
| `wsdm-02` | Delivered | 6 | Web Search → Algorithms for web-scale search, distributed search, metasearch, peer-to-peer search |

## 1. wsdm-03

**Status:** Delivered, Round 10

### Title

Computational Limits of Finite-Beam Generative Retrieval with Semantic IDs

### Subject Areas

- **Primary:** Foundation Models and Agentic Systems → Retrieval, indexing, and ranking with foundation models
- **Secondary:** Web Search → Algorithms for web-scale search, distributed search, metasearch, peer-to-peer search
- **Secondary:** Web Mining and Content Analysis → Web recommender systems and algorithms
- **Secondary:** Web Search → Search benchmarking and evaluation
- **Secondary:** Web Mining and Content Analysis → Scalable algorithms for mining web data, opinion mining and sentiment analysis

### Abstract

Semantic-ID retrieval replaces corpus-wide scoring with autoregressive trie search, mixing representation and search error. For canonical Gibbs distillation, we separate them exactly: every dense score vector has a unique positive trie-local factorization with the same exhaustive leaf order, while prefix log-mass equals best-descendant score plus log effective multiplicity. This yields an exact margin-mass boundary. For every fixed alphabet K and width b, an injective N = bK + 1 family makes all widths through b lose the unique optimum. The limit is conditional on this calibration, not universal over learned trees.

We then jointly train item tables, history GRUs, and rank-32 local decoders under bitwise-matched initialization. On Amazon Beauty with 12,101 items, five seeds, and 1,024 users, canonical exhaustive retrieval retains 67.35% teacher top-10 overlap, but width 10 preserves only 53.29% of its own exact top-10 set. Rank-preserving τ/2 sharpening raises this to 83.32% while retaining 67.03% exhaustive teacher overlap; exact max-node training and direct scoring reach 95.82%. Task intervals overlap, so the evidence establishes a finite-search mechanism and fidelity interventions, not a recommendation gain, production prevalence, or superiority over ANN, lookahead, or retention methods.

### Internal Automated Review — Do Not Paste into CMT

Round 10 panel score: **5/10 · soundness 3/4 · weak reject**.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 6/10 | 3/4 | 2/4 | 3/4 | Weak accept |
| Cursor Grok 4.5 | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |

## 2. wsdm-04

**Status:** Delivered, Round 7

### Title

Did the Judge See the Answer? A Crossed Dose–Response Audit of LLM Relevance Judgments

### Subject Areas

- **Primary:** Foundation Models and Agentic Systems → Evaluation and benchmarking of foundation models in search/mining
- **Secondary:** Web Search → Search benchmarking and evaluation
- **Secondary:** Foundation Models and Agentic Systems → Retrieval, indexing, and ranking with foundation models
- **Secondary:** Privacy, Fairness, Interpretability → Model and algorithm transparency
- **Secondary:** Foundation Models and Agentic Systems → LLMs and multimodal foundation models for web tasks

### Abstract

If relevance labels leak into an LLM judge, improved agreement can arise from learning passage-grade bindings or merely from absorbing a topic's label marginal. Held-out passages alone do not separate these mechanisms. We run a second-collection replication on all 50 TREC-COVID topics, constructing every train and held-out set to contain three grades. True-label exposure is compared with two zero-match wrong-label cycles that preserve the same passages and grade histogram. Two disjoint splits, two derangements, three optimizer seeds, and four fixed open judges yield 3,600 training trajectories, each measured after 5, 10, 20, and 40 updates.

At the prespecified 40-update endpoint, the held-out true-minus-wrong probability-weighted agreement contrast is 0.078 (95% CI [0.061, 0.094], p < 0.0001). The contrast grows from 0.011 at five updates to 0.078 at forty, with a log-dose slope of 0.022 [0.017, 0.027]. All four unadjusted model-specific intervals exclude zero, but effects range from 0.007 for SmolLM2-1.7B to 0.121 for Qwen2.5-7B, and the model-by-condition interaction is significant. These results establish dose-dependent passage-binding susceptibility under controlled LoRA exposure, not natural pretraining contamination, benchmark membership, or a system-ranking consequence.

### Internal Automated Review — Do Not Paste into CMT

Round 7 panel score: **5/10 · soundness 3/4 · weak reject**.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 6/10 | 3/4 | 3/4 | 2/4 | Weak accept |
| Cursor Grok 4.5 | 5/10 | 3/4 | 3/4 | 2/4 | Borderline |

## 3. wsdm-06

**Status:** Round 3 in progress. The abstract and review below are provisional.

### Title

Tokenizers That Peek: Test-Set Leakage in Semantic-ID Generative Recommendation

### Subject Areas

- **Primary:** Web Mining and Content Analysis → Web recommender systems and algorithms
- **Secondary:** Foundation Models and Agentic Systems → Retrieval, indexing, and ranking with foundation models
- **Secondary:** Foundation Models and Agentic Systems → Evaluation and benchmarking of foundation models in search/mining
- **Secondary:** Web Search → Search benchmarking and evaluation
- **Secondary:** Privacy, Fairness, Interpretability → Model and algorithm transparency

### Abstract

Semantic IDs replace atomic item labels with learned token sequences, making the tokenizer part of a recommender's fitted state. If its collaborative features consume held-out interactions, test labels can alter item-to-code assignments even when generator training remains clean. We isolate this channel under a global timeline: examples, targets, candidates, architecture, and seed are paired, and only tokenizer interaction scope changes.

Under equal-budget validation tuning, peeking raises Recall@10 by 0.589 percentage points (95% paired-seed interval [0.535, 0.642]) across three Amazon categories, two interaction-aware paths, and 15 seeds; this is 25.1% of clean performance. The content control changes by exactly 0.000, while a non-discretized Continuous-SVD control has an even larger positive gap, so the channel does not require tokenization. Removing scored target edges in all six cells leaves a macro interval spanning zero. The target component exceeds the pooled matched-removal null, but not its 90%-target-overlap stratum; the evidence supports overlap sensitivity, not exact-edge uniqueness. An immutable audit additionally finds one documented test-selected collaborative-feature path whose shipped tensor lineage is unresolved; we do not infer impact on a published score or prevalence.

### Internal Automated Review — Do Not Paste into CMT

Round 2 panel score: **5/10 · soundness 3/4 · weak reject**. Round 3 is still
running, so this score is provisional.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 6/10 | 3/4 | 3/4 | 3/4 | Weak accept |
| Cursor Grok 4.5 | 5/10 | 3/4 | 3/4 | 2/4 | Borderline |

### Registration Action Required

After `wsdm-06` is delivered, refresh its abstract, round, status, and automated
review before finalizing CMT registration.

## 4. wsdm-09

**Status:** Delivered, Round 6

### Title

Information Before Scale: Sample and Rank Frontiers for Walsh Collaborative Filtering

### Subject Areas

- **Primary:** Web Mining and Content Analysis → Web recommender systems and algorithms
- **Secondary:** Web Mining and Content Analysis → Scalable algorithms for mining web data, opinion mining and sentiment analysis
- **Secondary:** Privacy, Fairness, Interpretability → Model and algorithm transparency

### Abstract

Empirical recommender scaling curves do not distinguish insufficient output rank from insufficient information to identify a user's latent preference. We separate these resources on a synthetic Walsh collaborative-filtering family. For a revealed user-Walsh assignment, we derive an exact finite minimax rank rule. We then withhold that assignment while keeping the same signed permutation of the Walsh table.

Although the posterior now couples users through perfect matchings, we derive its exact finite conditional frontier and show that removing the assignment raises the fixed-accuracy sample scale from constant to logarithmic. Under binary-symmetric label noise, consistency has the sharp first-order threshold NpCq = log2 N, where Cq = 1 - h2(q). On matched sparse transcripts at N = 128, a validation-selected rank-N/2 matrix-factorization model reaches risk 0.964 against the 0.568 information frontier, exposing a substantial gap between optimization and information limits. These are architecture-relative results for a public Walsh dictionary, not an industrial scaling law.

### Internal Automated Review — Do Not Paste into CMT

Round 6 panel score: **5/10 · soundness 2/4 · weak reject**.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 6/10 | 3/4 | 3/4 | 3/4 | Weak accept |
| Claude Fable 5 | 6/10 | 3/4 | 3/4 | 2/4 | Weak accept |
| Cursor Grok 4.5 | 5/10 | 2/4 | 3/4 | 2/4 | Weak reject |

## 5. wsdm-02

**Status:** Delivered, Round 6

### Title

Risk-Sensitive Diversification Without an Oracle: Valid Certificates Need Not Identify Better Rankings

### Subject Areas

- **Primary:** Web Search → Algorithms for web-scale search, distributed search, metasearch, peer-to-peer search
- **Secondary:** Web Search → Search benchmarking and evaluation
- **Secondary:** Web Search → Query analysis and query processing
- **Secondary:** Privacy, Fairness, Interpretability → Model and algorithm transparency

### Abstract

Does a valid robust tail-risk certificate identify a better diversified ranking when the intent prior is estimated? Not necessarily. For finite-intent VRisk, fixed-ranking L1 error ε changes risk by at most min{1, ε/(2β)}, sharply, while a standard count radius can collapse robust CVaR to minimax. Even with a perfectly estimated prior and valid coverage, the resulting saturated minimizer and upper-bound gate can incur regret arbitrarily close to one. This separates certificate validity from decision usefulness.

A frozen-proposal audit across retrieval and recommendation benchmarks supports the distinction. Exact same-prior comparison accepts 17.9% of proposals in the primary NTCIR synthetic-prior experiment, while the evaluated real-estimator settings certify no intervention and matched robust-versus-minimax effects are mostly negligible. Validity, informativeness, and decision benefit are therefore distinct properties.

### Internal Automated Review — Do Not Paste into CMT

Round 6 panel score: **4/10 · soundness 3/4 · weak reject**.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 6/10 | 3/4 | 3/4 | 2/4 | Weak accept |
| Cursor Grok 4.5 | 4/10 | 3/4 | 2/4 | 2/4 | Weak reject |

## CMT Registration Checklist

For each paper:

- Copy the title exactly from the `Title` field.
- Copy both abstract paragraphs into the CMT abstract field.
- Select the listed primary subject area first, then the suggested secondary
  areas that CMT permits.
- Enter authors, affiliations, conflicts, and contact information separately.
- Do not paste the internal automated-review section into CMT.
- Refresh all `wsdm-06` fields after Round 3 delivery.
