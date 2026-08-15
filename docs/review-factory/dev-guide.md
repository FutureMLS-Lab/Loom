# Review Factory 开发指南（基于 Rebuttal Factory）

写给要在本仓库上开发 **Review Factory**（自动审稿工厂）的同学。Rebuttal
Factory 已经把"注册表 + 状态机 + tmux Agent + 确定性校验 + 人工 Gate + 前端
轮询页"这套骨架完整走通了一遍，AR 侧也有一个实战过几十轮的三模型评审面板。
你的工作大部分是**组装**，不是发明。

建议先通读：`docs/rebuttal-factory/arch.md`（带全链路流程图）、
`docs/research-factory/arch.md` 的评审面板部分、`docs/AUTO_RESEARCH_SYSTEM_DESIGN.md`。

## 0. 产品形态建议（可自行取舍）

```
Review Studio（一个 venue/rubric 一份配置，人工批准后冻结）
   └─ Review Task（一篇待审 paper）
        导入 PDF（manifest + SHA-256）
        → 三模型独立评审（只读隔离 PDF）
        → 结构化分数 + 逐条意见落盘
        →（可选）meta-review Agent 聚合成一份 AC 风格总评
        → 🧑 人工签发 → 导出报告
```

两级结构直接照抄 Rebuttal Factory 的 Studio/Project 模型：rubric、评分维度、
保密要求属于 Studio 层，一次人工批准、全部子任务继承。

## 1. 可直接复用的部件（先看这张表）

| 你需要的能力 | 已有实现 | 复用方式 |
|---|---|---|
| 三模型评审核心 | `ar_task.run_reviewer`（隔离临时目录只放编译 PDF、三模型并行、最低分定档）、`_run_cursor_headless`、`CURSOR_REVIEWER_MODELS`、`parse_review_scores` | **直接 import 调用**，别复制。想换 rubric 就换传入的 `skill_text` |
| 评审方法论 | `loom/skills/ar/AR-REVIEWER.md` | 作为默认 rubric；venue 定制 rubric 参照 `paper-rebuttal-delivery/WACV.md` 的"通用 SKILL + venue 伴随文件"模式 |
| 注册表（多 Studio 多任务） | `rebuttal_task.py` 的 `_registry_path`/`register_studio`/`register_project`/`list_*`/`read_*`/`write_*`（`LOOM_REBUTTAL_REGISTRY` 环境变量模式） | 抄结构建 `review_task.py`，注册表换名 `~/.loom/review-projects.json`（env：`LOOM_REVIEW_REGISTRY`） |
| 材料入库 | `rebuttal_task.py` 的 manifest 扫描（识别 PDF、逐文件 SHA-256） | 抄，砍掉 review-pdf 分类，只留 paper/材料 |
| headless 模型调用 | `ar_task._run_headless`（`claude -p` stream-json + 心跳 + 超时） | meta-review 聚合、rubric 抽取都用它 |
| 长任务后台化 | `web.py` 的 `_ar_run_async` + `<job>_status/<job>_error` 状态 + `ar-<job>.log` 进度日志 + `sweep_*` 重启清扫 | 照抄模式；**新 job 记得加进清扫列表**（我们漏过 `link`，修了一次） |
| tmux 常驻 Agent（若 meta-review 用交互 Agent） | `_rebuttal_start_agent` / `_rebuttal_watch_agent` / 完成标记文件协议（`agent-complete.json`）| 照抄；watcher 判断 Agent 退出用 pane 文本 `"Agent exited ("`，别依赖进程名 |
| 人工 Gate + 哈希绑定 | `rebuttal_task.approve_project`（`content_approval` 摘要）、`rebuttal_delivery.approve_delivery`（产物 SHA 绑定 + 漂移即失效） | 签发报告时抄这套：批准绑定报告文件哈希 |
| 前端页面骨架 | `web_static/rebuttal_factory.html/js/css`：三视图路由、6 秒轮询、`setButton` 门控、指纹比对防重建、toast | 复制成 `review_factory.*` 改造；入口加到 `index.html` |
| 部署 | `loom/skills/dev/loom-hot-restart/scripts/hot_restart.py` | 改完代码 `--port 8766` 热重启，公网 URL 和 token 不变 |

## 2. 里程碑切法（每步都可独立验收）

1. **M1 骨架**：`loom/review_task.py`（stage 常量、注册表、manifest 扫描、
   `sweep_interrupted_jobs`）+ `/api/review/*` 的注册/列表/详情路由 +
   空白页面能列出导入的 paper。测试仿 `tests/test_rebuttal_task.py` 的
   fixture（环境变量指向 tmp registry）。
2. **M2 单篇评审闭环**：`review` job 调 `ar.run_reviewer`（paper 已是 PDF 就
   直接给；是 LaTeX 源就先用 `ar_task.build_paper` 系列编译）→ 三份
   review md + 汇总分数写进任务目录 → 页面展示每个模型的分数卡（参照
   factory.js 的 reviewers 渲染）。
3. **M3 Studio/rubric 层**：Studio 建档 + rubric 草案（headless 模型从 venue
   审稿指南抽取，参照 `discover_studio_policy`）+ 人工批准冻结 + 子任务继承。
4. **M4 meta-review 与签发**：聚合 Agent 产出 AC 总评 → 确定性校验（分数与
   文字一致性、必填段落齐全、无占位符——参照 `validate_project` 的写法）→
   🧑 签发 Gate（绑定哈希）→ 导出。

## 3. 动手时的文件清单

```text
loom/review_task.py              # 领域逻辑（M1 起步 ~400 行足够）
loom/web.py                      # 挂 /api/review/* 路由；grep "path == \"/api/rebuttal" 找 dispatch 位置照抄
loom/web_static/review_factory.html/js/css
loom/web_static/index.html       # 加入口链接
loom/skills/ar/paper-review/SKILL.md        # rubric（可先直接引用 AR-REVIEWER.md）
tests/test_review_task.py        # 仿 test_rebuttal_task.py
tests/test_review_web_jobs.py    # 仿 test_rebuttal_web_jobs.py（monkeypatch 模型调用）
docs/review-factory/arch.md      # 写完后补一份，格式对齐另外两个 factory
```

## 4. 必须继承的四条设计纪律

1. **确定性与创造性分离**：模型只产内容；何时评审、能否签发、状态怎么走全部
   由 Python 决定，模型输出必须过确定性校验才能推进 stage。
2. **一切落盘、哈希绑定**：每份 review、每个分数都是磁盘文件；人工签发绑定
   SHA-256，之后任何改动自动作废批准。
3. **人只守关口**：rubric 批准一个 Gate、报告签发一个 Gate，其余全自动；
   绝不自动把 review 提交到任何外部系统。
4. **venue 参数不硬编码**：分数维度、字数、双盲要求全部进 Studio 的冻结
   配置，代码里只读配置（我们在 delivery policy 上验证过这条的价值）。

## 5. 前人踩过的坑（直接绕开）

- **NFS 临时目录**：`TemporaryDirectory` 清理在共享盘上会竞态崩溃，一律加
  `ignore_cleanup_errors=True`（`verify_delivery_figures` 的教训——一次崩溃
  丢掉了三次模型评审结果）。
- **OpenReview API 会拒爬**（403 挑战页），arXiv 有限速会"假死"；要外部数据
  就让模型自己 web search（参照 `research_venue_cycle`），代码只做规范化。
- **轮询会覆盖用户输入**：可编辑控件要有 dirty 标记（factory.js 的
  `S.searchDirty` 模式），否则 6 秒一刷用户改的东西就没了。
- **静态资源缓存**：改了 js/css 必须 bump `?v=` 版本号，两处（html 里的
  css 和 js 引用）都要改。
- **测试的临时目录**：登录节点根盘只有 124G，pytest 一律
  `--basetemp=/data/shared/.../tmp` 并设 `TMPDIR`，别写 `/tmp`。
- **模型成本记账**：Cursor CLI 不回报 cost（恒 0），claude 回报——报表口径
  要么注明要么只记 claude 侧。
- **删除要走 registry + 目录一起**：参照 `DELETE /api/rebuttal/projects` 的
  语义（注销注册、保留磁盘产物），并在 UI 上写清"删的是什么"。

## 6. 提交与部署流程

小步提交、每步全量 `pytest`（当前基线 306 个）、commit message 用一句话说清
"为什么"；上线用 hot restart，不要裸重启（会丢公网隧道和任务状态）。遇到与
Rebuttal Factory 共用代码要改动时（比如 `run_reviewer` 加参数），先跑
`tests/test_rebuttal_delivery.py` 和 `tests/test_ar_task.py` 确认无回归。
