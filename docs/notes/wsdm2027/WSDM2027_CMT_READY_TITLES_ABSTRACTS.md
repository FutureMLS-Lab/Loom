# WSDM 2027 CMT: Titles and Abstracts

Updated from all eight current WSDM manuscripts on August 17, 2026. Every paper
now has a plain-text, copy-paste-ready title and abstract below. Papers 1--7 are
delivered. Paper 8 (`wsdm-06`) is still in Round 3, so its title is ready but
its abstract is a current snapshot that should be refreshed after delivery.

These are concise CMT versions rather than raw LaTeX: commands have been
removed and each abstract retains the central claims and key quantitative
results. The review sections are internal automated-review results, not
official WSDM reviews; do not paste them into CMT.

## 1. wsdm-02

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

### Latest Automated Review

Round 6 panel score: **4/10 · soundness 3/4 · weak reject**. The panel uses the lowest reviewer rating as its decision score.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 6/10 | 3/4 | 3/4 | 2/4 | Weak accept |
| Cursor Grok 4.5 | 4/10 | 3/4 | 2/4 | 2/4 | Weak reject |

## 2. wsdm-05

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

Round 6 panel score: **4/10 · soundness 2/4 · weak reject**. The panel uses the lowest reviewer rating as its decision score.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 5/10 | 3/4 | 3/4 | 2/4 | Borderline |
| Cursor Grok 4.5 | 4/10 | 2/4 | 2/4 | 2/4 | Weak reject |

## 3. wsdm-09

### Title

Information Before Scale: Sample and Rank Frontiers for Walsh Collaborative Filtering

### Subject Areas

- **Primary:** Web Mining and Content Analysis → Web recommender systems and algorithms
- **Secondary:** Web Mining and Content Analysis → Scalable algorithms for mining web data, opinion mining and sentiment analysis
- **Secondary:** Privacy, Fairness, Interpretability → Model and algorithm transparency

### Abstract

Empirical recommender scaling curves do not distinguish insufficient output rank from insufficient information to identify a user's latent preference. We separate these resources on a synthetic Walsh collaborative-filtering family. For a revealed user-Walsh assignment, we derive an exact finite minimax rank rule. We then withhold that assignment while keeping the same signed permutation of the Walsh table.

Although the posterior now couples users through perfect matchings, we derive its exact finite conditional frontier and show that removing the assignment raises the fixed-accuracy sample scale from constant to logarithmic. Under binary-symmetric label noise, consistency has the sharp first-order threshold NpCq = log2 N, where Cq = 1 - h2(q). On matched sparse transcripts at N = 128, a validation-selected rank-N/2 matrix-factorization model reaches risk 0.964 against the 0.568 information frontier, exposing a substantial gap between optimization and information limits. These are architecture-relative results for a public Walsh dictionary, not an industrial scaling law.

### Latest Automated Review

Round 6 panel score: **5/10 · soundness 2/4 · weak reject**. The panel uses the lowest reviewer rating as its decision score.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 6/10 | 3/4 | 3/4 | 3/4 | Weak accept |
| Claude Fable 5 | 6/10 | 3/4 | 3/4 | 2/4 | Weak accept |
| Cursor Grok 4.5 | 5/10 | 2/4 | 3/4 | 2/4 | Weak reject |

## 4. wsdm-11

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

### Latest Automated Review

Round 5 panel score: **4/10 · soundness 3/4 · weak reject**. The panel uses the lowest reviewer rating as its decision score.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 2/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 5/10 | 3/4 | 2/4 | 2/4 | Weak reject |
| Cursor Grok 4.5 | 4/10 | 3/4 | 3/4 | 2/4 | Weak reject |

## 5. wsdm-12

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

### Latest Automated Review

Round 8 panel score: **4/10 · soundness 2/4 · weak reject**. The panel uses the lowest reviewer rating as its decision score.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Cursor Grok 4.5 | 4/10 | 2/4 | 2/4 | 2/4 | Weak reject |

## 6. wsdm-03

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

Round 10 panel score: **5/10 · soundness 3/4 · weak reject**. The panel uses the lowest reviewer rating as its decision score.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 6/10 | 3/4 | 2/4 | 3/4 | Weak accept |
| Cursor Grok 4.5 | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |

## 7. wsdm-04

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

Round 7 panel score: **5/10 · soundness 3/4 · weak reject**. The panel uses the lowest reviewer rating as its decision score.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 6/10 | 3/4 | 3/4 | 2/4 | Weak accept |
| Cursor Grok 4.5 | 5/10 | 3/4 | 3/4 | 2/4 | Borderline |

## 8. wsdm-06

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

### Latest Automated Review

Round 2 panel score: **5/10 · soundness 3/4 · weak reject**. Round 3 is still running, so this score and abstract are provisional.

| Reviewer | Rating | Soundness | Presentation | Contribution | Recommendation |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | 5/10 | 3/4 | 3/4 | 2/4 | Weak reject |
| Claude Fable 5 | 6/10 | 3/4 | 3/4 | 3/4 | Weak accept |
| Cursor Grok 4.5 | 5/10 | 3/4 | 3/4 | 2/4 | Borderline |
