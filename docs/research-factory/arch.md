# Research Factory — Architecture

自动科研的选题与产文流水线：Studio（选题孵化）→ Paper（回合制写作循环）。
本文以代码为锚，配合总览文档 `docs/AUTO_RESEARCH_SYSTEM_DESIGN.md` 阅读。

## 入口与文件

| 层 | 位置 |
|---|---|
| 页面 | `/factory`（`loom/web_static/factory.html` + `factory.js` + `factory.css`）|
| API | `loom/web.py` 中 `/api/tasks/<slug>/ar*` 系列路由 |
| 领域逻辑 | `loom/ar_task.py`（状态、挖掘、ideation、readiness、评审面板）|
| 任务基建 | `loom/rud_task.py`（任务注册、worktree、tmux agent 命令）|
| 技能 | `loom/skills/ar/`（AR-STUDIO / AR-AUTHOR / AR-REVIEWER / GPU-RESOURCES / figures/*）|
| 实例存储 | `<factory-root>/.RUD/<slug>/`（`ar.json` 状态 + `rounds/` + `work/`）|

同一个 `ar.json` 按 `role` 字段区分两种实体：`studio` 与 `paper`。

## Studio（选题孵化）

状态要点（`new_studio_state`）：`direction/custom_direction/venue/mode/seed_idea`、
挖掘结果 `papers`、检索设置 `search_terms/search_categories`、上届调研
`venue_report`、idea 池 `ideas`，以及每个后台作业的 `<job>_status/<job>_error`。

后台作业（全部走 `_ar_run_async` 线程 + `ar-<job>.log` 进度日志 + 轮询）：

| 作业 | 路由 action | 实现 | 说明 |
|---|---|---|---|
| 检索词建议 | `search/suggest` | `suggest_search_settings` | headless claude 从 brief 生成关键词+类目，人可改 |
| arXiv 挖掘 | `mine` | `mine_papers` | arXiv API 按词+类目抓最新论文，`venue_only` 可过滤 |
| 上届调研 | `venue` | `research_venue_cycle` | headless claude 联网深调研 venue 上一届（best paper/oral/热点/gap），结果规范化后存 `venue_report` |
| idea 生成 | `ideas` | `propose_ideas` | 素材二选一：`source=papers`（挖掘列表）或 `source=venue`（上届报告）；也接受直接粘贴 idea 数组 |
| 引用接地 | `link` | `link_ideas` + OpenAlex | 把 novelty 文本读回结构化 `derived_from` 边并逐条验真 |
| 孵化 | `spawn` | `_ar_spawn_children` | 勾选的 idea 各自变成 paper 任务（独立 worktree + tmux Author）|

作业互斥由各路由的 busy 检查保证；服务重启时 `sweep_stale_jobs` 把卡在
`running` 的状态清成 error。前端"Ideas from last cycle"按钮做了自动接链：
报告缺失时先跑 `venue`，落地后自动以 `source=venue` 触发 `ideas`。

## Paper（回合制写作循环）

状态机：`draft → await_draft_review →(🧑)→ loop →(停止条件)→ await_final_review →(🧑)→ delivered`。

每轮节拍（`_ARLoopDriver`，`loom/web.py`）：

1. **Author**：Claude 常驻 tmux（`work/code` + `work/manuscript` 两个 worktree），
   收到 round prompt（上轮评审 + AR-AUTHOR 技能 + figure 技能菜单 + GPU 规范），
   做实验、改稿、重编译，写 `rounds/round-NN/author.md` 作为完成信号。
2. **Readiness Gate**（确定性，`review_readiness`）：编译干净、无占位符/TODO/`??`、
   章节实质完整、page-one 总览图存在、引用图文件齐全、无悬空引用。
   失败清单原样打回 Author 重做（`readiness_attempts`），不消耗评审。
3. **Reviewer Panel**（`run_reviewer`）：三个 Cursor 模型
   （`CURSOR_REVIEWER_MODELS`：GPT-5.6 Sol Max Fast / Fable 5 Thinking Max /
   Grok 4.5 High Fast）并行、只读隔离目录中的编译 PDF，产出结构化分数，
   **最低分定档**（`deciding_model`）。
4. **停止判定**：达到 `stop_rating`（默认 8）/ 跑满 `max_rounds` / 平台期
   （连续两轮结构性修复无提升）→ Final Human Gate。

停摆自愈：Author pane 空闲但未交 `author.md` 时按连续无效唤醒计数重发
prompt（来自 zhongzhu/dev 的 stall-recovery）。

## API 面（paper 常用）

`GET /ar`（全量 payload：state/loop/logs/actions/pane）、`POST /ar/loop/start|stop`、
`POST /ar/gate`（draft/final 批准）、`POST /ar/review`（手动触发一次评审）、
`POST /ar/build`、`GET /ar/pdf`、`DELETE /api/tasks/<slug>`（整任务真删除，
`rud_task.delete_task` 对 `.RUD/<slug>` 做 rmtree）。

## 前端结构（factory.js）

单文件三视图：`fleet`（全局统计 + Studio 列表）、`studio`（四步流水 +
idea 卡片 + 引用图）、`paper`（轮次时间线 + 评审分数 + Author pane 实时面板）。
6 秒轮询 `GET /ar`；列表/图仅在指纹变化时重建以保护滚动与选择。
