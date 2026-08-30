# Researcher Profile 使用指南

Researcher Profile 用研究者已有的工作背景约束 Loom 的选题过程。Loom 从一份本地
Google Scholar Profile PDF 中提取研究主题、方法、领域、优势和兴趣；创建 Studio
时可以选择这份 Profile，让检索词和 Idea 更贴近研究者真正熟悉且有条件完成的方向。

Profile 目前主要影响：

- Studio 的 arXiv 检索词建议；
- Studio 的 Idea 生成；
- Studio 交互 Agent 对研究背景的理解；
- Idea 卡片中的背景匹配度、匹配理由、新概念和资源可行性说明。

它不会替代研究方向说明，也不会直接证明某个 Idea 新颖或可行。最终仍需检查文献、
实验资源和 Idea 内容。

## 1. 准备 Google Scholar PDF

1. 在浏览器中打开研究者的 Google Scholar Profile。
2. 尽量展开需要纳入的完整论文列表。
3. 使用浏览器的 **Print / 打印 → Save as PDF / 另存为 PDF**。
4. 打开保存后的 PDF，确认姓名、研究兴趣和主要论文标题清晰可见。

单个 PDF 不得超过 20 MB。文本型 PDF 和由页面截图组成的 PDF 都可以使用；清晰、
带文本层且包含完整论文列表的 PDF 通常提取效果更好。

## 2. 创建 Profile

1. 打开 Paper Factory 的 `/paper-factory` 页面。
2. 点击顶部的 **Manage researcher profiles**。
3. 点击 **New profile**。
4. 在 **Google Scholar profile PDF** 中选择本地 PDF。
5. 按需填写 **Extra note**。
6. 点击一次 **Generate profile**，等待状态变为 **Ready · active**。

生成期间页面显示 `generating`，按钮会暂时锁定。不要重复点击或重复上传。Loom 会依次：

1. 私下保存 PDF；
2. 读取 PDF 的文本和可视内容；
3. 生成结构化研究背景；
4. 检查是否提取到了有效的研究主题、方法或证据；
5. 检查通过后自动启用 Profile。

如果模型只返回泛化摘要、没有结构化研究内容，Profile 不会被误标为 Ready，而会显示
`needs attention`。

## 3. Extra note 怎么写

Extra note 是可选的，适合补充 PDF 中没有明确表达的当前偏好和现实约束，例如：

```text
Current priority: efficient multimodal and generative-model research.
Prefer projects that can be validated within one month.
Available compute: one 8-GPU node.
Avoid projects that require collecting a large new human-annotated dataset.
```

建议只写会影响选题的事实：

- 当前想重点发展的方向；
- 熟悉但没有出现在 Scholar 页面上的方法；
- 可用算力、数据、时间和工程条件；
- 希望避开的主题或实验形式；
- 对新领域探索程度的偏好。

Extra note 会作为上下文和约束进入模型提示词，但不会被当作论文发表记录的证据。不要在
这里填写密码、Token、私有凭据或其他不希望发送给模型服务的敏感信息。

## 4. 审核生成结果

生成完成后，页面会显示只读的结构化结果：

- `Summary`：研究背景概述；
- `Topics` / `Domains`：主要研究主题和应用领域；
- `Methods` / `Tools` / `Datasets`：已有方法、工具和数据经验；
- `Strengths`：从论文记录中归纳的研究优势；
- `Interests` / `Avoid`：适合优先考虑或避开的方向；
- `Resources`：来源明确支持的资源条件；
- `Evidence`：结论对应的 PDF 文件和简短依据。

重点检查三件事：

1. 是否识别到了正确的研究者；
2. 核心研究方向和方法是否准确；
3. 是否出现了 PDF 和 Extra note 都不支持的推断。

结构化字段目前不能逐项手工编辑。需要调整时，修改 Extra note 后重新 Generate；如果
原 PDF 不完整或过期，则选择一份新 PDF 再 Generate。

## 5. 在 Studio 中使用

### 创建新 Studio 时

在创建 Studio 的 **Researcher background** 区域：

1. 从 **Active profile** 中选择已经 Ready 的 Profile；
2. 选择 **Fit mode**；
3. 正常创建 Studio。

只有 `Ready · active` 的 Profile 会出现在选择列表中。

### 已有 Studio

进入 Studio 后，在 **Researcher profile** 区域选择 Profile 和 Fit mode，然后点击
**Attach**。点击 **Clear** 可以移除背景约束。

Attach 时，Loom 会把一份有长度限制的结构化 Profile 快照写入 Studio 状态，而不是把
整个 PDF 复制进去。因此：

- 后续修改原 Profile 不会悄悄改变已有 Studio，保证同一次研究过程可复现；
- 想让已有 Studio 使用新版本时，需要重新选择并点击 **Attach**；
- 已经生成的检索词和 Idea 不会被自动重写，需要重新运行相应步骤。

## 6. Fit mode

| 模式 | 适用场景 | 选题约束 |
|---|---|---|
| **Strict** | 希望快速产出、最大限度复用现有积累 | 主要复用熟悉的方法或领域，通常最多引入一个新概念 |
| **Balanced** | 默认选择，在熟悉基础上寻找适度创新 | 每个 Idea 至少锚定一项已有优势，最多引入两个有明确桥梁的新概念 |
| **Exploratory** | 有意进入新领域 | 可以跨到陌生领域，但必须说明它与已有优势的连接，并满足资源约束 |

Fit mode 是对 Idea Agent 的明确约束，不是对最终结果的数学保证。生成后仍应阅读 Idea
卡片中的 `Background fit`、`Background match`、`New concepts` 和 `Resource fit`。

## 7. 更新、复用与删除

### 只修改 Extra note

选择已有 Profile，修改 Extra note，不必重新选择 PDF，直接点击 **Generate profile**。
Loom 会复用已保存的 PDF。

### 替换 PDF

选择已有 Profile，再选择一份新 PDF 并点击 **Generate profile**。新 PDF 会替换旧的
Profile 来源，避免新旧论文列表混在一起。

### 删除 Profile

点击 **Delete** 会删除这份 Profile 及其保存在主机上的来源 PDF。生成过程中不能删除。
已有 Studio 内保存的快照不会被追溯删除；如不再希望 Studio 使用它，需要在 Studio 中
点击 **Clear**。

## 8. 数据与隐私

- Profile 和来源 PDF 默认保存在主机的 `~/.loom/researcher-profiles/`，不在项目 Git
  仓库中；
- Web API 和页面不会展示主机绝对路径或文件哈希；
- Studio 只保存有长度限制的结构化快照，不保存整份 PDF；
- Generate 时，提取 Agent 会读取 PDF；Profile Attach 后，结构化快照和 Extra note
  会进入相关 Studio 模型提示词；
- PDF 内容始终按不可信数据处理，提取 Agent 使用只读工作区，不执行 PDF 中的指令。

因此，Profile 是“主机本地存储”，但不是“从不发送给模型”。上传前应确认 PDF 和
Extra note 可以用于所配置的模型服务。

## 9. 常见问题

### Generate profile 按钮不可用

新 Profile 必须先选择一份 `.pdf` 文件。确认文件不超过 20 MB。

### 一直显示 generating

正常生成通常需要几十秒到几分钟，最长超时为 15 分钟。生成期间不要重复操作。可以刷新
页面或重新打开 Profile 查看状态；后台任务不会因为关闭弹窗而停止。

### 显示 needs attention

查看页面上的错误信息，并确认：

- 文件确实是有效 PDF，而不是只修改了扩展名；
- PDF 未损坏且不超过 20 MB；
- 页面中能看到研究者姓名和足够的研究内容；
- 论文列表没有被登录页、验证码页或空白页替代。

修复后选择新 PDF，再点击 **Generate profile**。

### 结果太泛或遗漏很多论文

先检查导出的 PDF 是否只包含 Scholar 当前可见的少量条目。展开更多论文后重新导出，
并在 Extra note 中简洁说明当前重点、资源和限制，然后重新 Generate。

### 新 Profile 在 Studio 中看不到

只有 `Ready · active` Profile 可以使用。等待生成完成；如果状态是
`needs attention`，需要先修复并重新生成。

### 更新后 Studio 仍使用旧背景

这是快照机制的预期行为。回到该 Studio，重新选择 Profile 和 Fit mode，然后再次点击
**Attach**；如需更新已有结果，再重新生成检索词或 Idea。
