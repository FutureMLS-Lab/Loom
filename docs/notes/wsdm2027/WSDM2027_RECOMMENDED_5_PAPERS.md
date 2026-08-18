# WSDM 2027：建议优先的五篇论文

更新时间：2026-08-18（PDT）

## 结论

基于核心结论可信度、贡献新颖性、WSDM 契合度、证据完整性和当前投稿风险，
我建议优先保留以下五篇：

1. `wsdm-03`
2. `wsdm-04`
3. `wsdm-06`（有条件推荐，Round 3 尚未交付）
4. `wsdm-09`
5. `wsdm-02`

该选择针对“当前八篇中相对更值得投入投稿资源的五篇”，不是对录用概率的
保证。内部自动评审不是 WSDM 官方评审，也不能单独作为去留依据。

## 1. `wsdm-03`

### Title

Computational Limits of Finite-Beam Generative Retrieval with Semantic IDs

### 为什么优先

- Semantic ID、generative retrieval 和 beam search 都是非常直接的 WSDM 主题。
- 论文把 representation error 与 finite-search error 精确分开，核心
  margin--multiplicity 机制清楚。
- 理论、构造和 Amazon/MovieLens 机制实验形成了相对完整的闭环。
- Sharpening 与 max-node 干预把 width-10 self-fidelity 从 53.29% 提升到
  83.32%/95.82%，结果明确且容易解释。
- 最新三位内部 reviewer 给出 5/6/5，最低 soundness 为 3/4。

### 投稿前必须处理

- 把“computational limits”严格限定为 canonical calibration 下的存在性和
  机制结果，不要暗示 learned RQ trees 普遍需要线性 beam。
- 明确 task utility 没有显著改善，主贡献是 search fidelity。
- 尽可能补充 PAG/PRO 对照；若来不及，必须清楚解释缺失。
- 收紧主文篇幅并修复标题/正文中比证据更宽的表述。

## 2. `wsdm-04`

### Title

Did the Judge See the Answer? A Crossed Dose–Response Audit of LLM Relevance Judgments

### 为什么优先

- 50 个 TREC-COVID topics、两种 split、两种 derangement、三个 seeds、
  四个模型和四个剂量组成了较强的全交叉设计。
- Histogram-preserving zero-match wrong-label control 直接处理了
  topic-grade marginal 这个关键混杂。
- Manipulation checks、arm decomposition 和 model heterogeneity 都有报告，
  证据链比一般 LLM judge audit 更完整。
- LLM relevance judgment 与 IR evaluation 对 WSDM 高度相关。
- 最新三位内部 reviewer 给出 5/6/5，最低 soundness 为 3/4。

### 投稿前必须处理

- 不要把 rising true-minus-wrong curve 写成正确 binding 单调增强；40-step
  增长有相当部分来自 wrong-label arm 变坏。
- 将 true-vs-unadapted 与 wrong-vs-unadapted 分解放到核心结果中。
- 明确 controlled LoRA susceptibility 不能诊断自然 pretraining contamination。
- 若可行，增加 correctly labeled cross-topic control；否则将其列为最核心的
  未识别替代解释。

## 3. `wsdm-06`（有条件推荐）

### Title

Tokenizers That Peek: Test-Set Leakage in Semantic-ID Generative Recommendation

### 为什么优先

- Tokenizer fitting scope 是 semantic-ID recommendation 中具体、及时且容易
  被社区忽略的泄漏面。
- Clean/peek paired intervention 固定 histories、targets、candidates、
  architecture 和 seed，只改变 tokenizer interaction scope，识别逻辑清楚。
- 三个 Amazon categories、两个 interaction-aware paths、15 seeds 和
  content-only exact-zero control 提供了可信的窄结论。
- 主题同时覆盖 recommender systems、generative retrieval 和 evaluation
  leakage，WSDM 契合度很高。
- Round 2 三位内部 reviewer 给出 5/6/5，最低 soundness 为 3/4。

### 推荐条件

该论文目前仍在 Round 3，尚未交付。只有满足以下条件时才保留在五篇中：

- P5-CID clean/peek released-stack 补跑完整结束；
- 不丢失 seed、不用不透明恢复值，结果和 provenance 可复核；
- 无论结果为正、为 null 或方向变化，终稿都按实际结果收紧 claim；
- PDF、摘要、评审分数和 CMT 材料在交付后同步更新。

### 如果条件不满足

若 Round 3 未按时完成、实验失败且无法形成可解释结果，或 released-stack
结果推翻当前中心 claim，则将 `wsdm-05` 作为第一替补重新比较。

## 4. `wsdm-09`

### Title

Information Before Scale: Sample and Rank Frontiers for Walsh Collaborative Filtering

### 为什么优先

- Matching-coupled converse 和隐藏 assignment 的 logarithmic information
  threshold 是八篇中较独特的理论贡献。
- Exact finite rules、渐近结果和可计算审计使理论包具有一定完整性。
- “先判断身份信息是否足够，再解释模型 scaling”是清晰、有传播性的观点。
- 与另外几篇 audit papers 相比，它为五篇组合提供理论多样性。
- 最新三位内部 reviewer 给出 6/6/5。

### 投稿前必须处理

- 统一 noisy revealed frontier 与主 clean-target risk 的定义。
- 摘要中的 `0.964 vs 0.568` 必须明确属于 product-address benchmark，不能把它
  当作 hidden signed-permutation 中心理论的直接实证。
- 降低对弱 MF baseline 的依赖；至少补训练收敛证据，避免 400-update
  under-optimization 成为替代解释。
- 将外推限制在 dictionary-style synthetic family，不要包装成普遍工业
  recommendation scaling law。

## 5. `wsdm-02`

### Title

Risk-Sensitive Diversification Without an Oracle: Valid Certificates Need Not Identify Better Rankings

### 为什么优先

- 理论定义和证明整体较严谨，最低 reviewer soundness 为 3/4。
- 论文清楚区分 certificate validity、optimization 与 decision usefulness。
- Matched minimax control、coverage diagnostics 和不利/弃权结果都有披露。
- Search diversification、risk-sensitive ranking 和 evaluation methodology
  与 WSDM Web Search track 直接相关。
- 与 `wsdm-05`、`wsdm-11`、`wsdm-12` 相比，当前中心结论的正确性风险较低。

### 投稿前必须处理

- 正面回应中心 regret construction 是否只是已知 robust-CVaR collapse 加
  简单两排序例子；必须更清楚地界定新增理论。
- 不要用 synthetic-prior acceptance 暗示真实 estimator 下方法有实用收益。
- 将真实场景“全部不认证干预”明确作为主要发现，而不是附带 limitation。
- 若无法补 full-support/calibrated-radius separation，应主动缩小 theorem claim。

## 五篇之间的资源优先级

若修改时间有限，建议按以下顺序投入：

1. 完成并审计 `wsdm-06` Round 3，决定其推荐条件是否成立；
2. 修正 `wsdm-09` 的风险定义和 empirical-headline 对齐；
3. 收紧 `wsdm-04` 的 arm-decomposed dose claim；
4. 收紧 `wsdm-03` 的存在性范围和缺失 baseline 表述；
5. 重写 `wsdm-02` 的 novelty boundary 与 real-estimator headline。

完整的八篇比较依据见 `WSDM2027_8_PAPER_SELECTION_GUIDE.md`。
