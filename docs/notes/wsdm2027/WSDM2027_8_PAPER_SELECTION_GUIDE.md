# WSDM 2027 八篇论文选择指南

更新时间：2026-08-18（PDT）

## 这份文档怎么用

目标是从八篇论文中选出五篇优先投稿、三篇暂不优先。本文不替最终决策者
直接勾选 5/3，而是说明每篇论文在做什么、最强卖点、最可能的拒稿原因，
以及哪些补充证据会改变判断。

需要特别注意：

- 下文引用的是内部自动评审，不是 WSDM 官方评审。
- 自动评审采用通用顶会式严格标准，不能只看最低分决定去留。
- `wsdm-06` 仍在 Round 3，当前判断是暂定的；其 P5-CID 补跑可能显著改变
  论文质量判断。
- “质量好”不等于结果为正。严谨、重要且结论清楚的负结果也可能是好论文。
- 真正需要判断的是：核心结论是否可信、贡献是否足够新、是否适合 WSDM、
  以及剩余问题能否在投稿前修复。

## 八篇论文快速地图

| ID | 一句话内容 | 当前最强点 | 当前最大风险 | 内部面板 |
|---|---|---|---|---|
| `wsdm-02` | 研究估计意图先验时，稳健风险证书为何可能有效却不能选出更好的排序 | 数学严谨，负结果和匹配控制诚实 | 中心反例可能过于直接，真实估计器场景全部弃权 | 4/10，soundness 3/4 |
| `wsdm-05` | 用四道门审计扩散推荐器是否值得蒸馏成一步模型 | 全目录、九种子、延迟与多种控制都较完整 | 主要结论依赖自建 teacher；统计协议还有冲突 | 4/10，soundness 2/4 |
| `wsdm-09` | 在 Walsh 协同过滤模型中分离“输出秩不足”和“身份信息不足” | 匹配耦合 converse 和有限样本理论有技术内容 | 高度合成；经验 headline 与中心理论模型没有完全对齐 | 5/10，soundness 2/4 |
| `wsdm-11` | 测试弱结果卡重复查询词是否诱导 LLM selector 误选 | 配对设计、轮换和多重校正较规范 | 重复词与删除 filler 混杂，载体人工且贡献较窄 | 4/10，soundness 3/4 |
| `wsdm-12` | 给出保留推荐图谱子空间所需原始边数的谱下界 | 问题定义精确，定理和适用边界清楚 | 下界很松，上界只是弱启发式 witness，尚未逼近真正最优值 | 4/10，soundness 2/4 |
| `wsdm-03` | 解释 semantic-ID 生成检索中有限 beam 如何丢失模型自己的精确排序 | 理论与机制实验对应较好，主题非常契合 WSDM | 最坏情形是构造的；缺标准 Transformer 与 PAG/PRO 对照 | 5/10，soundness 3/4 |
| `wsdm-04` | 审计 LLM judge 接触 relevance label 后是否学习 passage-grade binding | 50 topics 的全交叉、直方图保持负控制很扎实 | 40-step 增长部分来自错误标签伤害，尚不能说明自然污染 | 5/10，soundness 3/4 |
| `wsdm-06` | 审计 semantic-ID tokenizer 使用测试期交互造成的指标泄漏 | clean/peek 配对干净，主题及时且实际风险明确 | 终稿未完成；已完成证据主要来自简化 tokenizer+GRU | 5/10，soundness 3/4（Round 2，暂定） |

## 1. `wsdm-02`

### 它在做什么

论文研究风险敏感搜索多样化中的一个基本问题：意图先验不是 oracle 给定，
而是从数据中估计时，一个统计上有效的 robust-CVaR/VRisk 证书，是否真的
能帮助系统选择更好的 ranking。

核心结论是：不一定。论文给出先验误差对风险的精确敏感度界，说明常见
置信半径会使 robust CVaR 退化成 minimax，并构造“证书覆盖正确、但决策
后悔接近 1”的例子。实验审计 NTCIR、TREC、MIMICS 和 MovieLens，真实
估计器设置基本都选择弃权。

### 为什么可能值得选

- 理论定义、证明和 claim boundary 比较严谨。
- 能明确区分“证书有效”“目标优化正确”和“决策有用”三个概念。
- 匹配 minimax control 和负结果披露较诚实。
- 对 Web Search、diversification 和评测方法有直接 WSDM 契合度。

### 为什么可能不选

- 中心 near-unit-regret 构造依赖饱和后目标退化为 minimax；评审认为它可能
  只是已知 robust-CVaR collapse 加一个简单两排序例子，新增理论量有限。
- 最强反例使用边界先验，尚未证明 full-support 且经过实际校准半径时仍有
  同样强的 separation。
- 真实估计器场景没有一次成功干预；论文更像“该方法为什么不工作”的诊断，
  而不是可用的新决策方法。

### 选择它时应接受的定位

把它当作一篇理论化的负结果/评测审计论文，而不是一种能提升搜索效果的新
算法。若你的组合需要一篇严谨的 search diversification theory paper，
它有价值；若你优先要明显的实证收益或工具可用性，它的风险较高。

## 2. `wsdm-05`

### 它在做什么

论文提出扩散推荐器一步部署的“四道门”：

1. 多步 teacher 本身是否足够强；
2. 多步采样是否真的优于一步 DDIM；
3. 一步 student 是否保留 teacher；
4. 质量和延迟合起来是否有部署价值。

在 MovieLens-1M 和 Steam 的 common harness 上，SASRec 在全部主要比较中
优于 audited teachers，DDIM-1 也几乎总是优于多步 endpoint。Endpoint
regression 有时保留平均指标，但 top-10 set identity 最高只有 20.5%。

### 为什么可能值得选

- 问题实用，推荐系统和高效生成模型都符合 WSDM。
- 全目录评测、九个 held-out seeds、训练曲线、延迟和参数匹配控制较完整。
- 将 teacher competence、iterative benefit、fidelity 和 serving value
  分开是一个清楚、可复用的审计框架。
- 论文没有把不利结果包装成算法胜利。

### 为什么可能不选

- 最关键的负结果来自自建 DiffuRec-style/DreamRec-style checkpoints，
  不一定代表官方实现或现代加速推荐器。
- 原生复现只覆盖 Amazon Beauty；TA-Rec port 失败，FlowRec/CDRec 没有成为
  有效主对照。
- 正文中 96-test family 与附录 20-test family 的描述冲突；5,000 bootstrap
  对极端 Bonferroni quantile 也可能不足。
- 论文没有展示任何一个真实系统完整通过四道门，贡献更像 checklist 加
  checkpoint-specific negative evidence。

### 选择它时应接受的定位

把它当作“如何审计扩散推荐部署 claim”的方法论文，而不是一步蒸馏算法。
若无法在投稿前消除统计协议冲突并补强官方 checkpoint 外部验证，拒稿风险
会主要集中在 external validity。

## 3. `wsdm-09`

### 它在做什么

论文用一个公开 Walsh 字典构造协同过滤问题，区分两个资源：

- 模型输出的 rank/capacity；
- 识别用户对应哪个 latent signature 所需的信息量。

当 user-to-row assignment 已知时，固定精度只需常数量级样本；隐藏同一个
assignment 后，样本阈值上升到对数级。论文给出有限样本 frontier、
matching-coupled posterior 和带噪声的一阶阈值，并比较一个训练得到的矩阵
分解模型与信息论 frontier。

### 为什么可能值得选

- 匹配约束只改变有限样本、不移动一阶阈值的 converse 是较清楚的新技术点。
- 有 exact finite rules、渐近结果和可计算审计，理论包比较完整。
- “先判断信息是否足够，再讨论模型 scale”是一个容易传播的观点。
- 论文对合成范围和非工业 scaling law 的限制写得较诚实。

### 为什么可能不选

- noisy revealed frontier 与主风险定义之间存在不完全一致，属于需要优先
  修正的 correctness 问题。
- 摘要中的 `0.964 vs 0.568` MF gap 来自 product-address benchmark，
  不是中心 hidden signed-permutation 模型。
- MF 最多只训练 400 updates，甚至差于 observed-zero+SVD，无法排除只是
  under-optimization。
- 所有核心证据都在特殊 Walsh 家族中，尚未展示如何在真实推荐数据上运行
  “information before scale”诊断。

### 选择它时应接受的定位

这是一篇偏理论、偏合成模型的论文。若组合需要理论多样性，它比纯经验审计
更独特；若你要求真实数据上的直接决策价值，则必须对其外推保持保守。

## 4. `wsdm-11`

### 它在做什么

论文测试一个具体 display intervention：在低相关结果卡的固定 metadata
区域重复查询词，是否会让 deterministic LLM selector 更容易误选该卡片。
在 ANTIQUE 的 493 个 paired slates 和四个 confirmatory models 上，重复
反而使误选率下降 2.3--6.2 个百分点；一句 warning 没有改变这个效果。

### 为什么可能值得选

- 配对卡片、完整 rank rotation、固定高相关卡和多重校正使主比较较干净。
- 四个 selector 方向基本一致，统计结果容易解释。
- 明确不声称 human clicks，也主动降级了没有独立 regrade 的 rewrite 结果。
- 主题属于 LLM search interaction/evaluation，WSDM fit 很直接。

### 为什么可能不选

- “重复查询词”同时替换掉 generic filler，改变了流畅度、词汇多样性和
  spamminess；当前实验不能把效果归因于 frequency 本身。
- 只报告差值，没有完整 arm-level absolute false-choice rates。
- 只有一个人工 carrier、一个 repetition intensity 和一个 benchmark。
- 结果是“明显 stuffing cue 会被模型惩罚”，可能被认为贡献窄且不意外。
- warning 实验没有在原来真正产生 lure 的 treatment 上交叉，不能解释旧结果。

### 选择它时应接受的定位

这是八篇里最窄的 controlled behavior audit 之一。优点是容易读、结论清楚；
缺点是机制混杂和贡献广度很难仅靠改写解决，通常需要新的 factorial control。

## 5. `wsdm-12`

### 它在做什么

论文研究：为了保持推荐图 normalized biadjacency 的 rank-\(r\) projector，
一个 unweighted、same-identity edge subset 至少需要保留多少原始边。

论文把 leverage support 下界和 component-multiplicity/identifiability 下界
结合起来，并在 block-complete 图家族上给出接近可达的构造。在三个真实推荐
图上，理论 floor 很低，但目前找到的可识别 witness 需要多得多的边。

### 为什么可能值得选

- access model、谱目标和不覆盖的 channel 定义得很清楚。
- 定理与 block-complete 构造组成完整、可检查的理论结果。
- 实验不隐藏 nonidentifiable checkpoints、非单调 crossing 或不利结果。
- 推荐图压缩和图谱分析与 WSDM 有合理契合。

### 为什么可能不选

- 理论 floor 忽略真实边可实现性和 projector orientation，实际很松。
- “上界”只来自 generic heuristics；论文自己定义的 greedies 和直接优化
  \(L_{\mathrm{sub}}\) 的搜索没有进入主 crossing audit。
- 因此目前的 10--100 倍 gap 不能说明真正 optimum 离 floor 很远，只能说明
  已测试 heuristics 较弱。
- 结论依赖单一 \(\tau=0.25\) 和 \(10^{-3}\) identifiability threshold，
  缺少 sensitivity。

### 选择它时应接受的定位

把它当作一个 valid exclusion lower bound，而不是已经解决“图能压到多小”。
如果无法补强直接优化 witness 或 feasibility-aware floor，标题问题与实际
回答之间会存在明显落差。

## 6. `wsdm-03`

### 它在做什么

论文研究 semantic-ID generative retrieval 中的有限 beam search error。
它先证明任何 dense score 都能被 canonical trie factorization 精确表示；
但 prefix 的 log-mass 等于最佳后代分数加 effective multiplicity，因此有限
beam 可能丢掉真实最优叶子。论文给出固定 alphabet 下需要线性 beam width
的构造，并在 MovieLens 和 Amazon Beauty 上测试 sharpening、max-node
training/scoring 等干预。

### 为什么可能值得选

- 将 representation error 与 search error 精确分开，问题定义清楚。
- margin--multiplicity boundary 和 exact beam threshold 可检查、可解释。
- Amazon 实验采用 matched initialization/minibatches、多个 seeds 和
  training-by-scoring factorial，机制验证较系统。
- `53.29% -> 83.32%/95.82%` 的 self-fidelity 改善是清楚、容易传播的结果。
- Semantic ID、generative retrieval、beam search 都是很强的 WSDM 主题。

### 为什么可能不选

- 线性 beam lower bound 是 adversarial trie 的 existence result，尚未证明
  学到的 RQ trees 经常接近该 hard regime。
- 实验主体是 GRU/local edge decoder；T5 control 很弱，不能代表标准
  Transformer generative retriever。
- 没有 PAG/PRO 等最近的 lookahead/retention baseline。
- task utility intervals 重叠；主要收益是模型对自己 exhaustive ranking 的
  fidelity，而不是推荐质量。
- 标题中的“computational limits”可能比证据覆盖范围更广。

### 选择它时应接受的定位

它最适合被定位为“存在性理论 + learned-tree mechanism + fidelity
interventions”，而不是普遍的生成检索 lower bound。若你重视主题热度、理论
与实验闭环，它值得重点阅读；若你要求最终任务收益，则需降低优先级。

## 7. `wsdm-04`

### 它在做什么

论文测试 LLM relevance judge 在接触 passage-grade pairs 后，是否学习了
具体 passage-grade binding，而不只是 topic 的 grade marginal。

实验覆盖全部 50 个 TREC-COVID topics，每个 topic 的 train/held-out 都含
三档 grade；true labels 与保持同一 passage 和 grade histogram 的 zero-match
wrong-label cycles 对比，并完整交叉两种 split、两种 derangement、三个 seeds、
四个模型和四个训练剂量，共 3,600 条训练 trajectory。

### 为什么可能值得选

- histogram-preserving negative control 直接处理了最重要的 marginal confound。
- 全交叉设计、剂量轨迹、manipulation checks 和模型异质性报告比较完整。
- 所有四个 model-specific intervals 都为正，主结果不是单个模型偶然现象。
- LLM judge、IR evaluation、benchmark contamination 都高度符合 WSDM。
- 对“不是自然预训练污染、不是 ranking utility”的边界说明很诚实。

### 为什么可能不选

- 40-update true-minus-wrong 增长很大一部分来自 wrong-label arm 变坏；
  true arm 在 20 updates 后并未继续上升，不能简单称为“正确 binding 随剂量
  单调增强”。
- 没有 correctly labeled cross-topic control，不能排除一般 relevance-task
  fine-tuning，而非 topic-specific passage binding。
- 只有一个 biomedical collection、一种 raw prompt、一套 LoRA 配置和四个
  小模型。
- 不能据此诊断自然 pretraining contamination，也没有证明会改变 system ranking。
- 相对 controlled memorization 既有工作，新增点主要是 IR-specific control
  refinement，novelty 可能被认为增量式。

### 选择它时应接受的定位

应以“controlled relevance-label exposure audit”投稿，而不是声称发现真实
benchmark contamination。论文设计强于其外部结论；是否选择主要取决于你
是否看重 evaluation methodology 本身。

## 8. `wsdm-06`（暂定）

### 它在做什么

论文审计 semantic-ID recommender 的 tokenizer fitting scope。如果协同特征
使用了 cutoff 之后的交互，测试期信息会进入 item codes，即使 generator 的
训练数据本身保持干净，也可能抬高最终指标。

已完成的 Round 2 在三个 Amazon categories、两个 interaction-aware paths
和 15 seeds 上做 clean/peek 配对；训练 histories、targets、candidates、
architecture 和 seed 都固定，只改变 tokenizer interaction scope。内容型
tokenizer 是精确的零变化控制。

### 为什么可能值得选

- 威胁模型具体、现实，且切中 semantic-ID recommendation 热点。
- clean/peek paired intervention 的识别逻辑比跨模型比较更强。
- 15 seeds、full-catalog evaluation、content-only negative control 和多种
  baseline sensitivity 提供了较扎实的窄结论。
- 论文没有把 release provenance 不明直接说成已发生泄漏。
- 如果当前 P5-CID released-stack 补跑成功，会直接解决评审最核心的
  external-validity 质疑。

### 为什么可能不选

- 当前终稿尚未完成，Round 3 的 released-stack 实验结果未知。
- Round 2 的正结果主要来自 residual k-means tokenizer 加小型 GRU，尚不能
  代表 TIGER/P5/LETTER 类真实 stack。
- 已审计的四个 release 中没有一个被证明存在污染，实际 prevalence 未建立。
- target-edge localization 不完整，随机移除约一半会碰到 targets，只有一个
  cell 在有限 null 的最小 p 值处显著。
- user-level inference 还面临所有用户共同拟合同一 tokenizer 所产生的依赖。

### 选择它时应接受的定位

在 Round 3 完成前，不应把它与七篇 delivered papers 当作同等成熟的候选。
若 P5-CID clean/peek replication 成功、结果稳定且终稿收紧 claim，它的上限
很高；若补跑为 null、失败或无法在 deadline 前整理完成，应显著提高风险权重。

## 建议怎样自己完成 5/3 选择

### 第一步：先做 hard-veto，而不是先看平均分

每篇先回答三个问题：

1. 核心结论有没有未解决的 correctness/identification 问题？
2. 最大贡献是否需要全新大实验才能成立？
3. 在投稿截止前，是否能把最可能的拒稿理由写清或修掉？

若任意一项答案是“问题严重且无法按时修复”，优先进入三篇暂不投稿候选。

### 第二步：按下面权重自己打 1--5 分

\[
\text{总分}
=0.30\times\text{核心可信度}
+0.25\times\text{贡献新颖性}
+0.20\times\text{WSDM 契合度}
+0.15\times\text{证据与外部有效性}
+0.10\times\text{投稿前可修复性}.
\]

| ID | 核心可信度 1--5 | 新颖性 1--5 | WSDM fit 1--5 | 外部有效性 1--5 | 可修复性 1--5 | 加权总分 | 最终选择 |
|---|---:|---:|---:|---:|---:|---:|---|
| `wsdm-02` |  |  |  |  |  |  |  |
| `wsdm-05` |  |  |  |  |  |  |  |
| `wsdm-09` |  |  |  |  |  |  |  |
| `wsdm-11` |  |  |  |  |  |  |  |
| `wsdm-12` |  |  |  |  |  |  |  |
| `wsdm-03` |  |  |  |  |  |  |  |
| `wsdm-04` |  |  |  |  |  |  |  |
| `wsdm-06` |  |  |  |  |  |  |  |

### 第三步：在同类论文中做 head-to-head

不要只按八篇总排序，还应做以下直接比较：

- **Semantic ID:** `wsdm-03`（search mechanism）对 `wsdm-06`
  （evaluation leakage）。前者已交付、理论闭环更完整；后者现实问题更强，
  但仍在等待关键 released-stack 结果。
- **LLM/IR audit:** `wsdm-04`（label-binding exposure）对 `wsdm-11`
  （query-term repetition）。前者设计更重、更广；后者更简单易读，但机制
  混杂和贡献宽度风险更高。
- **推荐理论:** `wsdm-09`（information frontier）对 `wsdm-12`
  （spectral subset floor）。前者技术新意可能更强但更合成；后者问题更直接，
  但当前 lower-to-witness gap 不够有信息量。
- **负结果审计:** `wsdm-02`（robust ranking certificate）对 `wsdm-05`
  （diffusion deployment gates）。前者理论更干净但 novelty/actionability
  受质疑；后者实验更大，但 official-system external validity 和统计协议风险更高。

### 第四步：不要在 `wsdm-06` 完成前锁定最后一个名额

`wsdm-06` 的 P5-CID clean/peek 补跑是八篇中最可能改变相对排序的单项结果。
建议先确定四个稳定候选和两个明确高风险候选，最后一个优先名额与最后一个
淘汰名额在该结果和终稿审计完成后再定。

## 最后检查清单

最终选择五篇前，对每篇勾选：

- [ ] 一句话贡献能在 20 秒内讲清楚。
- [ ] 摘要 headline 与真正被实验/定理识别的 estimand 一致。
- [ ] 最强 reviewer concern 在正文中有直接答案，而不只是 limitation。
- [ ] 主结果不是来自未完成、performance-gated 或弱 baseline 的比较。
- [ ] 与已有工作的差异不是只靠措辞，而有 theorem、control 或新 evidence。
- [ ] WSDM audience 能清楚理解它与 search/mining/recommendation 的关系。
- [ ] 论文在截止前可以达到模板、页数、匿名性和 artifact 完整要求。

满足项最少的三篇，才应进入“暂不优先”；不要简单把内部面板最低分的三篇
直接淘汰。
