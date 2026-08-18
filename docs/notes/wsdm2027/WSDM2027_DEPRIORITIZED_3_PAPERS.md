# WSDM 2027：当前建议暂不优先的三篇论文

更新时间：2026-08-18（PDT）

## 结论

在必须从八篇中只保留五篇的约束下，我建议当前暂不优先：

1. `wsdm-05`
2. `wsdm-11`
3. `wsdm-12`

“暂不优先”表示它们相对于另外五篇具有更难在投稿前消除的核心风险，不表示
研究工作没有价值，也不表示内部自动评分就是最终结论。

## 1. `wsdm-05`

### Title

When Does One Step Suffice? A Four-Gate Audit of Diffusion Recommendation Distillation

### 论文在做什么

论文用 teacher competence、iterative benefit、one-call fidelity 和 serving
value 四道门，审计扩散推荐器是否值得蒸馏成一步模型。实验发现 audited
teachers 普遍不如 SASRec 和 DDIM-1；endpoint regression 有时保留平均指标，
但无法复制 teacher 的具体 top-10 lists。

### 为什么当前暂不优先

- 主要负结论来自 common-harness 的 DiffuRec-style/DreamRec-style teachers，
  不是经过验证的官方 checkpoints，容易被认为是 reimplementation artifact。
- 原生 DiffuRec 只在 Amazon Beauty 上复现；现代 one-step 方法没有形成有效
  的主对照。
- 主文的 96-test family 与附录 20-test family 相互冲突，直接影响论文最重视
  的 simultaneous decision counts。
- 5,000 bootstrap resamples 对 96-test Bonferroni 极端 quantiles 可能不足。
- 论文没有展示任何真实系统完整通过四道门，最终贡献主要是审计 checklist
  和 checkpoint-specific negatives。

### 什么情况可以重新进入五篇

- 明确并修复 20/96-test protocol 冲突，重新生成稳定的 simultaneous intervals；
- 在官方/原生 DiffuRec、DreamRec 或 TA-Rec 类系统上完成至少一个可验证审计；
- 证明主要 Gate 1/2 结论不是弱 teacher search 或 harness instability 造成的。

### 替补顺序

如果 `wsdm-06` Round 3 不能完成或其 released-stack 结果使中心 claim 不再成立，
`wsdm-05` 是当前三篇中的第一替补，因为其问题重要、实验投入大，而且部分统计
问题仍可通过重新分析修复。

## 2. `wsdm-11`

### Title

Query-Term Repetition Repels LLM Selectors from Weak Result Cards: A Controlled Audit

### 论文在做什么

论文在 ANTIQUE 的弱结果卡中增加查询词重复，测试 deterministic LLM selector
是否更容易误选。四个模型上观察到的结果方向相反：重复使误选率下降
2.3--6.2 个百分点。

### 为什么当前暂不优先

- 核心 treatment 同时用重复查询词替换 generic fillers，改变了 fluency、
  lexical diversity 和 spamminess，尚未识别纯 frequency effect。
- 只有一个人工 carrier、一个 repetition intensity 和一个 benchmark。
- 没有完整报告每个 arm 的 absolute false-choice rates，实际效应大小难判断。
- Warning 没有与原来真正产生 lure 的 same-query treatment 交叉，因此无法
  支持对旧 hardened-prompt 结果的解释。
- 在去掉未经独立 regrade 的 rewrite 结果后，剩余贡献是一项较窄且可能被认为
  不意外的 synthetic display-cue negative finding。

### 什么情况可以重新进入五篇

- 增加 filler-preserving、non-query repetition 和多剂量 factorial controls；
- 报告所有模型与条件的 absolute arm levels；
- 在自然 snippets 或第二个 collection 上复现；
- 将 warning 与原 same-query lure treatment 直接交叉。

### 当前判断

三篇暂不优先论文中，它最需要新的实验才能解决核心 identification 与贡献宽度
问题，单靠改写难以显著降低风险。

## 3. `wsdm-12`

### Title

How Small Can You Go? Spectral Bounds for Recommendation Subsets

### 论文在做什么

论文给出 unweighted、same-identity recommendation graph edge subset 保持
rank-\(r\) normalized-biadjacency projector 时必须保留的边数下界，并在真实
图上比较该 floor 与启发式找到的 first identifiable witnesses。

### 为什么当前暂不优先

- 理论 floor 独立选择 user/item leverage support，忽略真实边可实现性和
  projector orientation，因此在真实图上非常松。
- 主实验没有运行论文自己定义的 attainability greedies，也没有直接优化
  \(L_{\mathrm{sub}}\) 的 local search 或 exact/certified optimizer。
- 所谓 lower-to-upper interval 的 upper endpoint 只是若干 generic heuristics
  的最好结果，并不能有意义地 bracket 真正 optimum。
- 所有核心比例依赖单一 \(\tau=0.25\) 与 \(10^{-3}\) identifiability threshold，
  缺少敏感性分析。
- 定理本身可能正确，但当前实证没有回答标题中的“实际能压到多小”。

### 什么情况可以重新进入五篇

- 将 RANK-\(r\)-COVER-GREEDY、DEGREE-LOSS-GREEDY 和直接 projector-loss
  optimization 纳入同一 crossing audit；
- 在小图上给出 exact 或 certified optimum；
- 构造 feasibility-aware lower bound，限制为图中实际存在的边；
- 报告多组 \(\tau\) 和 identifiability threshold 下的完整曲线。

### 当前判断

它有一项定义清楚的理论下界，但论文当前最显眼的 10--100 倍 gap 更可能说明
floor 和 tested heuristics 都不够强，而不是揭示真实 graph-subset complexity。

## 三篇的相对顺序

若只能从这三篇中恢复一篇：

1. 首先重新考虑 `wsdm-05`，前提是 `wsdm-06` 条件推荐失败，且统计协议能够修复；
2. 其次考虑 `wsdm-12`，前提是能快速补上真正的 attainability attack；
3. 最后考虑 `wsdm-11`，因为它的核心混杂和贡献宽度都依赖新的 factorial/
   cross-collection experiments。

完整的八篇比较依据见 `WSDM2027_8_PAPER_SELECTION_GUIDE.md`。
