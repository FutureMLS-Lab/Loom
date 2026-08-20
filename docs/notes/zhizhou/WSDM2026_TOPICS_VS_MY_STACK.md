# WSDM 2026 火爆 Topic × 我的技术栈对照表

> 每个 topic 三段：**火爆证据**（该届实际发生了什么）、**我已有的**
> （哪些论文/技能直接对得上）、**要新学的**（写出这篇 paper 还缺什么）。
> 末尾有推荐优先级。studio 里的 `fit-XX` 卡片编号标在各 topic 后面。

---

## Topic 1 · LLM 判官与 LLM 生成内容冲击 IR 评测（自反性主题）
对应卡片：fit-01 / fit-14 / fit-20

**火爆证据**：该届新出现的成规模主题。TRUE 框架（LLM 做相关性标注的
可复现性）、threshold priming 效应、"LLM 生成文本对词法检索器无偏、
对神经检索器有偏"等多篇；keynote 也在敲 LLM 污染评测生态的警钟。

**我已有的**
- "No Hidden Prompts! 改排版就能骗 AI 审稿人"——攻击 LLM 判官的完整
  方法论，换个靶子（IR 相关性判官）几乎原样能用。
- ICML25 desk-rejection 公平性分析——学术评审生态的数学建模经验。
- LLM 文化偏差审计（urban perception 两篇）——大规模审计实验的操作经验。

**要新学的**
- IR 评测传统：TREC / Cranfield 范式、qrels 是怎么造出来的、
  评测者间一致性统计（Cohen's kappa 一类）。约 1-2 周文献量。
- 数据污染检测：n-gram 重叠、成员推断（membership inference）。
- （做防御篇才需要）鲁棒统计聚合：trimmed mean / median-of-means
  在排序聚合上的版本、breakdown point 理论。

**判断**：你所有选项里不对称优势最大、上手最快的 topic。域知识薄、
方法论你已经发过 paper。

---

## Topic 2 · 扩散模型做推荐（该届最大建模浪潮）
对应卡片：fit-02 / fit-05 / fit-07 / fit-12 / fit-19

**火爆证据**：≥7 篇 accepted full papers，覆盖序列推荐、下一篮预测、
冷启动、知识感知推荐——accepted list 上最显眼的单一建模趋势。

**我已有的**
- 扩散/流的方法工具箱：high-order matching、one-step shortcut 蒸馏、
  NRFlow 噪声鲁棒、force matching、HOFAR。
- 扩散理论：GMM 视角的 smoothness 分析（ICCV25）。
- 条件控制：TokenCompose token 级监督、OmniControlNet 双阶段条件。
- 这是你方法+理论双主场，迁移只是换数据域。

**要新学的**
- 序列推荐的标准实验体系：SASRec / BERT4Rec 基线，Amazon /
  MovieLens / KuaiRand 数据集，leave-one-out 评测协议，
  NDCG@K / Recall@K。约 1-2 周可上手。
- 隐式反馈的坑：负采样策略、位置偏置、曝光偏置（社区有一套约定俗成
  的争议和陷阱，踩错评测协议会被拒）。
- 离散空间怎么扩散：item 是离散的，社区有 embedding 空间扩散 vs
  离散扩散两条路线，要读透已有 7 篇的选择。

**判断**：性价比第二高。浪最大（审稿人多、关注度高），你带着别人
没有的蒸馏/鲁棒/理论工具进场。

---

## Topic 3 · 生成式推荐 / Semantic ID / Scaling Law（工业集群）
对应卡片：fit-03 / fit-04 / fit-09 / fit-15

**火爆证据**：阿里 7B 大用户模型（scaling law + 线上 A/B）、快手
OneLoc（geo 生成推荐，21% GMV）、MMQ（多模态量化 tokenization）、
CAT-ID² 等一串工业 paper。

**我已有的**
- AR/VAR/FlowAR 的表达力与细粒度复杂度分析（两篇）——直接对准
  "semantic ID 自回归解码"这个新架构做理论。
- looped MLP 可编程性——做"模型规模必要性"下界。
- HSR 稀疏注意力、近线性梯度近似——长序列用户模型的效率切口。

**要新学的**
- 生成式检索文献线：DSI → NCI → TIGER → MMQ 的演进和各自的坑。
- Semantic ID 怎么造：RQ-VAE / 残差量化 / 多模态量化。
- 工业推荐架构常识：召回-排序两段式、embedding 表、终身行为序列
  建模（SIM/TWIN）。不需要真实工业数据也能做理论+公开数据验证，
  但叙事要懂行。

**判断**：理论切口是你的护城河（这个社区缺会证下界的人），但要花
2-3 周啃工业文献才能讲对话。

---

## Topic 4 · LLM Agent + 工具使用 + RL
对应卡片：fit-06 / fit-10 / fit-17

**火爆证据**：TableMind（SFT+RL 表格推理 agent）、TOOL-CURE（课程
RL 选工具）、CoDA（层次 RL agent）、LLM agent 刷分攻击推荐系统；
Industry Day keynote 全在讲 agentic。

**我已有的**
- RLVR 理论与实践：off-principals 分析（43 引用）、ISO 优化栈。
- 多智能体：MEMO 记忆增强多轮博弈。
- RL 训练的直觉和踩坑经验是现成的。

**要新学的**
- Agentic search/RAG 训练管线：Search-R1 一类的环境搭建、
  rollout 基建（这块工程量不小）。
- 工具调用的数据构造与评测基准（HotpotQA、多跳 QA、工具链任务）。
- 推荐系统安全文献（若走刷分攻防线：shilling attack 的经典设定）。

**判断**：能力对口，但工程基建成本是四个高优 topic 里最重的，
适合愿意搭环境的时候做。

---

## Topic 5 · 受限图学习：压缩 / 遗忘 / 对抗鲁棒
对应卡片：fit-08 / fit-18

**火爆证据**：GCTD（张量分解图压缩）、离散域多面压缩、GNN 遗忘
反演攻击、Forget-and-Explain 遗忘验证——一整簇。

**我已有的**
- DP-NTK（WACV25）——接"可认证遗忘"正合适（遗忘 ≈ 隐私的孪生问题）。
- DPBloomFilter——隐私数据结构。
- rank-1 矩阵感知样本复杂度——接"图压缩能压到多小"的下界问题。

**要新学的**
- **GNN 基础全套**：GCN / GAT / LightGCN、消息传递框架、图上的
  评测协议。你的发表列表里没有图学习工作，这是真正要补的课
  （约 3-4 周）。
- 图压缩方法线和遗忘的定义谱系（exact / approximate / certified）。

**判断**：理论接口漂亮，但 GNN 是从零学。适合作为第二梯队。

---

## Topic 6 · 可信 LLM：RAG 鲁棒、事实核查、引用归因

**火爆证据**：KnowFC / DagFC（知识冲突下的事实核查）、C²-Cite
（引用归因）、检索增强生成的抽取-生成对齐。

**我已有的**
- 审计方法论和理论功底可以泛化，但**没有直接对口的论文**——这是
  六个热点里你接口最薄的。

**要新学的**
- RAG 全栈（检索器 + 生成器 + 知识冲突处理）、FEVER 线的事实核查
  数据集、归因评测协议。基本等于进一个新领域。

**判断**：除非有特别想做的角度，否则不推荐从这里进。

---

## Topic 7 · 冷启动与工业转化建模（CVR）

**火爆证据**：约 8 篇冷启动（bundle / app / podcast / 序列），
Best Paper Runner-Up（TemporalExpertNet，大促 CVR）也在这条线，
Spotify 案例研究——工业气息最重的主题。

**我已有的**
- RichSpace 的 embedding 插值思路可做冷启动数据增广；理论功底可
  做 delayed feedback 建模。接口偏弱。

**要新学的**
- CTR/CVR 建模全套：特征工程、多任务学习、延迟转化、在线学习；
  外加大促业务理解。没有工业数据和线上 A/B，这个主题很难写出该届
  获奖那种说服力。

**判断**：不推荐。你的比较优势在理论和生成模型，不在工业经验。

---

## Keynote 开放方向（可做故事加成，不建议单独立项）

- **Worst-case 而非平均**（Best Paper 的精神）：任何 topic 里加一层
  "最差情况分析"都会讨喜——你的理论功底正好干这个（fit-13/16 用了）。
- 信息茧房突破（fit-19）、System-1/2 统一助手、情绪动态——故事好听，
  单独做风险高，适合当某个 idea 的动机段。

---

## 推荐优先级（综合"你的接口厚度 × 浪的大小 × 新学成本"）

| 优先级 | Topic | 接口厚度 | 新学成本 | 一句话 |
| --- | --- | --- | --- | --- |
| 1 | LLM 判官 / 评测审计 | 极厚（原样迁移） | 低（1-2 周） | 不对称优势最大 |
| 2 | 扩散推荐 | 厚（方法+理论） | 低（1-2 周） | 最大的浪，带工具进场 |
| 3 | Semantic ID / 生成式推荐 | 厚（理论切口） | 中（2-3 周） | 缺理论的社区，你是稀缺供给 |
| 4 | LLM Agent + RL | 中 | 高（基建重） | 对口但费工程 |
| 5 | 图压缩 / 遗忘 | 中（DP+复杂度） | 高（GNN 从零） | 第二梯队 |
| 6 | 可信 RAG | 薄 | 很高 | 不推荐进场 |
| 7 | 冷启动 / CVR | 薄 | 很高（要工业数据） | 不推荐 |
