# WSDM 2027 CMT: Latest Three Delivered Papers

This file contains the three most recently delivered WSDM papers as of
August 17, 2026, 23:54 PDT, ordered by final approval time. Titles and
abstracts are plain-text, copy-paste-ready CMT versions. Subject areas are
suggested selections. Automated reviews are internal only and should not be
pasted into CMT.

## 1. wsdm-05

**Delivered:** August 17, 2026, 17:02 PDT  
**Final round:** 6

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

### Latest Automated Review

Round 6 panel score: **4/10 · soundness 2/4 · weak reject**. The panel score is the lowest reviewer rating.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 5/10 | 3/4 | 3/4 | 2/4 | Borderline |
| Cursor Grok 4.5 | 4/10 | 2/4 | 2/4 | 2/4 | Weak reject |

## 2. wsdm-03

**Delivered:** August 17, 2026, 22:02 PDT  
**Final round:** 10

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

### Latest Automated Review

Round 10 panel score: **5/10 · soundness 3/4 · weak reject**. The panel score is the lowest reviewer rating.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 6/10 | 3/4 | 2/4 | 3/4 | Weak accept |
| Cursor Grok 4.5 | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |

## 3. wsdm-04

**Delivered:** August 17, 2026, 22:28 PDT  
**Final round:** 7

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

### Latest Automated Review

Round 7 panel score: **5/10 · soundness 3/4 · weak reject**. The panel score is the lowest reviewer rating.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 6/10 | 3/4 | 3/4 | 2/4 | Weak accept |
| Cursor Grok 4.5 | 5/10 | 3/4 | 3/4 | 2/4 | Borderline |
