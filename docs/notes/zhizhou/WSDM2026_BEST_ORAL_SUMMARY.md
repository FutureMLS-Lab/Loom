# WSDM 2026 获奖与代表性论文的共通点

> 数据来源：wsdm2027 studio 的 venue 深度调研报告（Claude agent 从你给的
> WSDM 官网 URL 开始爬取），存于 `.RUD/wsdm2027/ar.json` 的 `venue_report`。
>
> **可信度说明**：WSDM 2026（第 19 届，Boise, Idaho，2026 年 2 月，录取率约
> 16%）**没有公开单独的 oral 名单**。官方可确认的只有 Best Paper 和
> Runner-Up 两篇；下文"代表性论文"是该届被广泛引用/讨论的 accepted
> papers，oral 身份未经证实。投稿数在不同来源间有出入（799 vs 613）。

## 一、两篇获奖论文（官方认证）

### Best Paper（唯一）：Diversification as Risk Minimization

- 早稻田大学 Rikiya Takehi（本科生一作）等，arXiv 2510.22681。
- 用人话说：搜索结果多样化（diversification）研究了二十年，大家默认它能
  "照顾到小众意图"。这篇 paper 实测发现：**经典多样化算法对小众意图的保护
  并不比不做多样化更好**——平均指标在涨，最差情况的用户体验没人管。
- 他们提出 VRisk（衡量"最差意图"风险的指标）和 VRisker（带近似保证的贪心
  重排器），把最差情况的失败率降低最多 33%，代价只是平均性能掉 ~2%。

### Best Paper Runner-Up：TemporalExpertNet

- 天津大学 + 快手工业数据，ACM DOI 10.1145/3773966.3777956。
- 用人话说：电商大促（618、黑五）期间用户转化行为会突变，常规 CVR 模型
  在大促时失灵。这篇把模型拆成"稳定编码器 + 大促敏感专家"两部分，让平时
  学到的知识在大促期间**跨时间复用**，而不是每次大促都从头学。

## 二、该届代表性论文（oral 身份未证实）

| 论文 | 主题 |
| --- | --- |
| MMQ: Multimodal Mixture-of-Quantization | Semantic ID / 生成式推荐的物品 token 化 |
| Unlocking Scaling Law in Industrial RecSys (Alibaba, 7B) | 推荐系统的 scaling law，已部署 A/B |
| OneLoc (Kuaishou, ~21% GMV 提升) | 地理感知生成式推荐，已部署 |
| TableMind | SFT+RL 训练的表格推理工具智能体 |
| Dual Conditional Diffusion Models | 扩散模型做序列推荐（该届最大建模潮流，≥7 篇） |
| How Do LLM-Generated Texts Impact Term-Based Retrieval? | LLM 生成内容对检索器的偏置（发现词法模型无偏，神经检索器有偏） |
| Multi-view Graph Condensation via Tensor Decomposition | 图压缩 / GNN 训练效率 |

## 三、共通点（核心结论）

1. **"一篇理论 + 一篇工业"的双主线，正是整个 program 的缩影。**
   Best Paper 是有近似保证的原理性 IR 工作，Runner-Up 是快手验证的工业系
   统。WSDM 的口味不是二选一，而是两条腿都要硬。

2. **质疑"平均指标"，关心最差情况。** Best Paper 的整个立论就是"社区优化
   了二十年平均值，小众意图在静默失败"。这种 **审视既有共识/评测方式**
   的角度是该届最受奖励的姿态（LLM 判官可靠性、LLM 生成内容偏置这些自反
   性主题同理）。

3. **简单方法 + 可证明保证，胜过复杂堆料。** VRisker 只是一个贪心重排器，
   但带近似保证；获奖靠的是问题定义的新颖和理论的干净，不是模型的大。

4. **真实部署与 A/B 证据是硬通货。** 快手（两篇）、阿里（7B 大用户模型）、
   Spotify（播客冷启动）都带线上数据。纯离线 benchmark 的工作在这届明显
   弱势。

5. **分布偏移 / 时间维度是共同的敌人。** 大促偏移（Runner-Up）、冷启动
   （约 8 篇）、时间上的知识复用——"世界会变，模型怎么办"是贯穿获奖和热点
   的底层问题。

6. **自反性主题崛起：一边用 LLM，一边审计 LLM。** LLM 生成文本污染检索
   语料怎么办？LLM 相关性判官能不能替代人？这些"用 AI 研究 AI 带来的问
   题"是该届新出现的成规模主题，且 keynotes（个性化是否只会强化习惯、
   情绪操纵）也在同一方向上敲警钟。

一句话版本：**WSDM 2026 奖励的是"用干净的理论工具，去戳一个大家习以为常
的假设，并且最好带真实系统的证据"。**

## 四、为什么 swarm 生成的 idea 长那个样子

评委面板是拿着上面这份报告给 206 个候选打分的，所以最终 top 20 几乎全是
"审计/复核/戳假设"式的标题——这正是该届 venue 的口味，但标题确实不说人话。
翻译几个高分的：

- **swarm-01 "Structure or Semantics?"**：Semantic ID 让生成式推荐变好，
  到底是因为它编码了语义，还是只是给了模型更好用的结构先验？拆开验证。
  （对应共通点 2 + 该届最热的 Semantic ID 主题）
- **swarm-02 "Is Source Bias Mismeasured?"**：大家说神经检索器偏爱 LLM
  生成文本，但这些 benchmark 的标签本身是怎么迁移的？审计测量方法。
  （对应共通点 6）
- **swarm-05 "Risk-Sensitive Diversification Without an Oracle"**：Best
  Paper 的 VRisk 假设意图分布已知，真实系统里意图是估计出来的——估计误差
  会不会把 worst-case 保证吃掉？（直接接着 Best Paper 的开放问题做）

如果你想要更"正向建方法"而不是"审计别人"的 idea，可以调整生成器的 persona
配比重跑一轮 swarm，或者在报告的 gaps（个性化突破信息茧房、System-1/2 统
一助手、情绪动态建模）里挑方向定向生成。
