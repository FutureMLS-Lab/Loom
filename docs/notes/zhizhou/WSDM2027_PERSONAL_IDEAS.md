# WSDM 2027 个人定制 Idea 池（20 个）

> 生成逻辑：你的发表记录（`my-google-scholar.pdf`）× WSDM 2026 热点
> （`WSDM2026_BEST_ORAL_SUMMARY.md`）。每个 idea 标注了三件事：
> **你的接口**（你哪篇工作/哪项技能接得上）、**要新学的**（这个 idea
> 里对你是新东西的部分）、**WSDM 对接点**。
> 排序按"桥的牢固程度"（fit 分）降序，和 studio 里的卡片一一对应
> （`fit-01` ~ `fit-20`）。
>
> 你的能力圈速写：① 扩散/流生成模型的方法与理论（TokenCompose、
> smoothness/GMM、high-order matching、NRFlow）；② AR/VAR/FlowAR 的
> 表达力与细粒度复杂度（VAR limits、FlowAR、looped MLP、HSR 稀疏注意
> 力、近线性梯度）；③ 差分隐私（DP-NTK、DPBloomFilter）；④ RLVR 与
> 多智能体（off-principals、ISO、MEMO）；⑤ 评审生态审计（ICML25
> desk-rejection 公平性、"No Hidden Prompts" 攻击 AI 评审）；⑥ LLM
> 城市/文化偏差（UrbanAlign、culturally uneven perception）。

---

## 直接迁移带（你的方法 → 推荐/检索的新战场）

### fit-01 · Presentation-Only Gaming of LLM Relevance Judges（0.95）
- **人话**：你证明过"只改排版不改内容就能骗过 AI 审稿人"。IR 社区正在
  大规模用 LLM 当相关性判官（标注 qrels）。同样的攻击在这里成立吗——
  一篇网页只靠改格式、加小标题、换措辞，能不能骗 LLM 判官给出更高相关
  性？如果能，这就是"针对 LLM 判官的 SEO"，整个评测生态都有问题。
- **你的接口**：arXiv 2606.13044 的攻击方法论几乎原样可用。
- **要新学的**：IR 评测体系（TREC qrels、Cranfield 范式）、WSDM26 的
  TRUE 框架和 priming-effect 论文。
- **WSDM 对接点**：热点 E（LLM 判官重塑 IR 评测），该届自反性主题的
  正中心。

### fit-02 · One-Step Diffusion Recommenders via High-Order Shortcut Distillation（0.92）
- **人话**：WSDM26 最大的建模潮流是扩散推荐（≥7 篇），但都要几十步采
  样，线上根本部署不起。你做过 one-step shortcut diffusion 的高阶匹配
  蒸馏——把它搬过来，把扩散推荐器蒸成一步出结果，延迟直接对齐工业上线
  标准。
- **你的接口**：High-order matching for one-step shortcut diffusion
  (2502.00688)、HOFAR。
- **要新学的**：序列推荐的标准 setup（SASRec/BERT4Rec 基线、
  Amazon/MovieLens 协议）、线上延迟预算怎么算。
- **WSDM 对接点**：热点 A（扩散推荐）+ 工业口味（部署可行性）。

### fit-03 · Computational Limits of Generative Retrieval over Semantic IDs（0.90）
- **人话**：生成式检索/推荐把物品编成 semantic ID 序列，然后自回归解
  码。你对 VAR/FlowAR 做过的"表达力 + 细粒度复杂度"分析，在这个新架构
  上没人做过：什么条件下生成式检索能被证明匹配稠密检索？beam search
  在 ID 树上的复杂度下界是什么？
- **你的接口**：VAR computational limits (2501.04377)、FlowAR
  expressivity (AISTATS26)。
- **要新学的**：生成式检索这条线（DSI、NCI、TIGER、MMQ）。
- **WSDM 对接点**：热点 B（semantic ID / 生成式推荐）。

### fit-04 · Provable Sparse Attention for Lifelong User-Behavior Sequences（0.88）
- **人话**：工业推荐要在十万级的用户终身行为序列上做注意力，现在的做
  法（先检索再注意力，如 SIM/TWIN）没有理论保证、可能漏掉关键历史。
  你的 HSR 稀疏注意力加速自带"可证明不漏"的结构——搬到终身序列建模，
  给出第一个带 recall 保证的长序列用户模型。
- **你的接口**：HSR-enhanced sparse attention（CPAL25）。
- **要新学的**：终身序列建模的工业方案与数据集。
- **WSDM 对接点**：热点 B（大用户模型）+ 工业口味。

### fit-05 · Noise-Robust Diffusion Recommendation for Implicit Feedback（0.86）
- **人话**：推荐的训练信号是隐式反馈（点击），里面全是噪声：误点、位
  置偏置、从众。你做过噪声鲁棒的生成建模（NRFlow 的高阶机制），把"标
  签噪声下的扩散训练"搬到交互噪声下的扩散推荐，直接回答"扩散推荐器对
  脏数据到底稳不稳"。
- **你的接口**：NRFlow（UAI25）、force matching（CIKM25）。
- **要新学的**：隐式反馈去偏那套文献（position bias、exposure bias）。
- **WSDM 对接点**：热点 A + 工业数据现实。

### fit-06 · Do RL-Trained Search Agents Learn Off the Principals?（0.85）
- **人话**：现在流行用 RL 训练会搜索的 LLM agent（Search-R1 一类）。
  你的 RLVR 理论说：RL 更新其实避开了主参数方向、走的是"偏离主成分"
  的路径。把这个分析工具对准搜索 agent：它们学到的是"怎么搜"的通用能
  力，还是过拟合了训练用的那个检索器？换个检索器还行不行？
- **你的接口**：RLVR off-principals (2511.08567)、ISO (2607.19331)。
- **要新学的**：agentic search/RAG 的训练管线和评测。
- **WSDM 对接点**：热点 C（RL 训练的 LLM agent）。

### fit-07 · A Multimodality Criterion for When Diffusion Beats AR in Recommendation（0.84）
- **人话**：什么时候值得用扩散做推荐、什么时候自回归就够了？你的
  ICCV25 论文用高斯混合视角刻画了扩散模型的平滑性。用户偏好分布天然
  是多峰混合（一个人同时喜欢好几类东西）——把你的分析搬过来，给出一个
  可检验的判据：后验多峰性强到什么程度，扩散才开始赢。
- **你的接口**：Smoothness of diffusion via Gaussian mixture（ICCV25）。
- **要新学的**：推荐里的多兴趣建模文献（multi-interest retrieval）。
- **WSDM 对接点**：热点 A 的"何时该用"元问题，评委最爱的戳假设角度。

### fit-08 · Certified Machine Unlearning for Recommenders via NTK Regression（0.82）
- **人话**：用户行使"被遗忘权"后，推荐模型真的忘了他吗？WSDM26 有一
  簇图遗忘/遗忘验证的 paper，但基本是启发式。你的 DP-NTK 工作正好提供
  了带证书的工具：在 NTK 回归视角下做可认证的推荐模型遗忘，给出"忘没
  忘"的数学保证而不是经验检查。
- **你的接口**：DP mechanisms in NTK regression（WACV25）。
- **要新学的**：unlearning 的定义谱系和图遗忘验证（该届的
  Forget-and-Explain 等）。
- **WSDM 对接点**：热点 F（图遗忘/可信）。

---

## 半迁移带（你带一半工具，另一半要新学）

### fit-09 · Expressivity Lower Bounds: What User-Model Scale Is Actually Necessary?（0.80）
- **人话**：阿里的 7B 大用户模型宣称推荐有 scaling law。但没人问下界：
  协同过滤这个任务本身需要多大的模型才能表达？你的 looped-MLP"可编程
  计算机"和表达力分析可以构造：什么规模以下必然表达不了某类用户-物品
  结构。给 scaling 狂热泼一盆有定理的冷水。
- **你的接口**：Looped ReLU MLPs（AISTATS25）、复杂度分析全家桶。
- **要新学的**：推荐 scaling law 的实证结果与协同过滤的谱结构。
- **WSDM 对接点**：热点 B（scaling law），戳假设角度。

### fit-10 · Multi-Agent LLM Shilling: Coordinated Attacks and Provable Detection（0.78）
- **人话**：WSDM26 已有"LLM agent 刷分攻击推荐系统"的 paper，但都是单
  agent。你做过多智能体记忆协作（MEMO）：一群带记忆、会协调的 LLM
  agent 能把刷分攻击做到多隐蔽？反过来，协调性本身是不是可检测的指纹？
  攻防两端都做。
- **你的接口**：MEMO (2603.09022)、多智能体博弈经验。
- **要新学的**：推荐系统安全/托攻击（shilling）的经典文献。
- **WSDM 对接点**：热点 C（agent）× 可信推荐，该届已有先例文章。
- **注意**：安全攻防题，写作要走"红队为了防御"的框架。

### fit-11 · Differentially Private Sketches for Streaming Recommendation Infrastructure（0.76）
- **人话**：工业推荐的底层全是流式频率结构：频控（frequency capping）、
  去重、热门统计，而这些 sketch 会泄露用户行为。你做过 DPBloomFilter，
  往前推一步：一整套带 DP 保证的流式 sketch（Bloom/CountMin/HLL）用于
  推荐基础设施，量化"隐私预算 vs 推荐质量"的真实代价。
- **你的接口**：DPBloomFilter (2502.00693)。
- **要新学的**：工业推荐的流式架构（谁在什么环节用什么 sketch）。
- **WSDM 对接点**：工业口味 + 可信；WSDM 一直收系统向 paper。

### fit-12 · Controllable Diffusion Recommendation with Token-Level Supervision（0.75）
- **人话**：TokenCompose 用 token 级监督让文生图听话；ControlNet 加条
  件控制。推荐这边的对应问题是"可控推荐"：运营要保量、多样性要保底、
  类目要平衡。把条件控制机制搬进扩散推荐器，让一个模型在推理时接受可
  调的控制信号，而不是训练 N 个模型。
- **你的接口**：TokenCompose（CVPR24）、OmniControlNet（CVPR24）。
- **要新学的**：可控推荐/约束重排的业务设定。
- **WSDM 对接点**：热点 A + 工业可用性。

### fit-13 · Exposure Fairness Under Submission Constraints: A Mechanism-Design View of Ranking（0.74）
- **人话**：你在 ICML25 用数学分析过"投稿限额政策对谁不公平"。同一套
  机制设计+公平性数学，换个对象：平台的曝光分配政策（限流、频控、创作
  者配额）对小创作者是否系统性不公平？给出可证明的机制设计改进。这也
  接上了 Best Paper 的 worst-case 精神——平均曝光在涨，尾部创作者在死。
- **你的接口**：Desk-rejection fairness（ICML25）的分析框架。
- **要新学的**：创作者经济/曝光公平的文献（two-sided marketplace）。
- **WSDM 对接点**：Best Paper 的风险敏感精神 × web 平台机制。

### fit-14 · Manipulation-Resistant LLM Judge Panels with Provable Breakdown Points（0.72）
- **人话**：fit-01 证明单个 LLM 判官可被排版攻击。防御端：怎么组一个
  判官面板（多模型+聚合规则），使得"被操纵的判官不超过 k 个时，最终判
  决可证明不变"？借鉴鲁棒统计的 breakdown point，把你攻击论文的对抗视
  角转成防御设计。
- **你的接口**："No Hidden Prompts" 的攻击模型 + 理论功底。
- **要新学的**：鲁棒统计聚合（trimmed mean、median-of-means 在排序上
  的版本）。
- **WSDM 对接点**：热点 E，攻防成对投稿的防御篇。

### fit-15 · Almost-Linear-Time Training for Billion-Parameter User Models（0.70）
- **人话**：推荐大模型（7B 用户模型）的训练成本是工业最痛的账单。你证
  明过多层 transformer 梯度可以近线性时间近似。把这个理论结果落到用户
  模型训练上做系统实现：什么近似精度下 A/B 指标不掉？第一个把"近似梯
  度理论"带进推荐训练的工作。
- **你的接口**：Almost-linear gradient (2408.13233)、async SGD。
- **要新学的**：推荐训练 infra（embedding 表、流式训练）的工程现实。
- **WSDM 对接点**：热点 B（scaling）× 工业效率。

---

## 探索带（你只带入场券，主体是新领域——想学新东西选这几个）

### fit-16 · Worst-Case Regional Fairness Auditing of Geo-Aware Recommenders（0.68）
- **人话**：快手 OneLoc 用地理感知生成推荐拿了 21% GMV，但没人问：小
  城市/少数族裔社区拿到的推荐质量是不是系统性更差？你有"LLM 城市感知
  的文化不均"审计经验 + Best Paper 的 VRisk 最差情况度量——合起来做地
  理维度的 worst-case 公平审计。
- **你的接口**：Culturally uneven urban perception (2604.20048)、
  UrbanAlign。
- **要新学的**：本地生活推荐的业务与数据。
- **WSDM 对接点**：Best Paper 的 worst-case 精神 × 热点 B 的地理生成
  推荐 × keynote 的社会关切。

### fit-17 · RLVR for Tool-Use Retrieval Agents: Verifiable Rewards from Retrieval Outcomes（0.66）
- **人话**：RLVR 火是因为奖励可验证（对/错）。检索恰好天然可验证：文
  档里有没有答案、引用对不对。把你的 ISO 优化栈的经验搬到"检索工具使
  用 agent"的 RL 训练上，设计一套以检索结果为可验证奖励的训练配方，对
  比 TOOL-CURE 那类课程学习。
- **你的接口**：ISO RLVR stack、RLVR 训练直觉。
- **要新学的**：工具调用 agent 的数据构造与评测（这块对你基本全新）。
- **WSDM 对接点**：热点 C 正中心。

### fit-18 · Sample-Complexity Limits of Graph Condensation for Recommendation（0.64）
- **人话**：图压缩（把大图缩成小图训练）在 WSDM26 是一簇热点，但全是
  "怎么压"，没人回答"最多能压到多小"。你的 rank-1 矩阵感知样本复杂度
  技术正好是这个问题的工具：保住协同过滤谱结构所需的最小交互数是多少？
  给这个热门方向立一块理论界碑。
- **你的接口**：Rank-1 matrix sensing 样本复杂度。
- **要新学的**：图压缩方法这条线（GCTD、离散域压缩）。
- **WSDM 对接点**：热点 F，为方法潮流补理论下界（评委最吃这套）。

### fit-19 · Serendipity by Diffusion: Escaping Filter Bubbles with Controlled Noise（0.62）
- **人话**：Caverlee 的 keynote 问"个性化能不能带来真正的新发现而不是
  强化旧习惯"。扩散模型天然有一个被忽视的旋钮：注入噪声的幅度控制探
  索半径。做一个"意外但连贯"的推荐生成器——用噪声调度控制新颖度，用
  worst-case 意图覆盖评估（接 VRisk），回答信息茧房这个 keynote 级问题。
- **你的接口**：扩散模型的噪声机制理解。
- **要新学的**：serendipity/diversity 的评测传统（这块很成熟，坑也多）。
- **WSDM 对接点**：keynote gap × 热点 A，故事性最强的一个。

### fit-20 · Knowledge-Cutoff Contamination in LLM Relevance Judgments（0.60）
- **人话**：LLM 判官的训练语料可能见过评测集的文档和查询——它给的"相
  关性判断"到底是判断还是背诵？设计截断日期前后的对照实验，量化污染对
  qrels 质量的影响。这是 swarm-10 的题，但从你的"评审生态审计"视角切
  入你完全能驾驭，且和 fit-01 共享实验基建。
- **你的接口**：评测审计的方法论嗅觉（ICML25 + 攻击 AI 评审）。
- **要新学的**：数据污染检测技术（n-gram 重叠、成员推断）。
- **WSDM 对接点**：热点 E，和 fit-01/fit-14 构成一个投稿集群。

---

## 怎么用

- 20 张卡已写入 wsdm2027 studio（`fit-01` ~ `fit-20`，分数即上面的
  fit 值），原 swarm 池备份在 `.RUD/wsdm2027/swarm-pool.json`。
- 建议的组团方式：**评测审计团**（fit-01/14/20，共享基建，你最有不对
  称优势）、**扩散推荐团**（fit-02/05/07/12/19，蹭最大浪）、**理论界
  碑团**（fit-03/09/18，你最难被抄袭的护城河）。
