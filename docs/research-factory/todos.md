# Research Factory — TODOs 与技术债

更新于 2026-08-13。死代码条目**只列不删**，等 operator 逐项定夺。

## 死代码 / 无引用候选（等定夺）

| # | 位置 | 说明 | 产线引用 |
|---|---|---|---|
| 1 | `ar_task.paper_source_text` | 旧"评审读 LaTeX 源码"输入路径，PDF 评审上线后废弃 | 仅测试 |
| 2 | `ar_task.ARXIV_CATEGORIES`（`= DEFAULT_ARXIV_CATEGORIES` 别名） | 无人引用 | 无 |
| 3 | `ar_task.store_stats` | 论文缓存计数器 | 仅测试 |
| 4 | `ar_task.loop_is_complete` | 循环驱动器不用它判停 | 仅测试 |
| 5 | `rud_task.ensure_cursor_default_model_config` | 改用显式 `--model` 传参后废弃 | 仅测试 |
| 6 | `rud_task.load_default_skills` | 全仓无调用 | 无 |
| 7 | `web._kernel_record_path` | 全仓无调用 | 无 |
| 8 | `web._paste_prompt_and_watch_session` | 被现行 watcher 流程取代 | 无 |

相邻发现（factory 范围外）：`app.js`（classic 任务台）有 5 个未调用函数
（`clearPaneDraftForTask` / `formatMonitorTime` / `saveTemplate` /
`scrollTmuxOutputToBottom` / `writeInterviewToPlan`）。

## 已知缺陷 / 改进项

1. **重启清扫漏掉 link 作业**：`sweep_stale_jobs` 清 `search_suggest/papers/
   ideas/review/venue`，不含 `link_status`——重启时正在 grounding 会把按钮
   永久卡在 running。一行修复，待做。
2. **Studio 删除的残留**：真删除 `.RUD/<slug>`，但 (a) Studio 的 tmux
   interview 会话会变孤儿；(b) 已孵化 paper 失去 Studio 分组后在 Factory
   fleet 的展示路径需要确认（目前依赖 ideas.child_slug 反查）。
3. **venue 报告无"重新调研"入口**：报告存在时按钮直接用旧报告生成 idea；
   想强制重跑只能改状态。加一个小的 re-research 控件。
4. **方向约束太宽的教训**（MCD 漂到 audio 的根因）：`direction=multimodal`
   一词种出 omnimodal 选题。改进：建 Studio 时鼓励 custom_direction 写排除
   条件；孵化前 UI 高亮 idea 的 `derived_from` 锚点论文供人扫一眼。
5. **Round-0 的 "Human input needed" 无人消费**：作者骨架稿里的举手警告
   应在 Draft Gate 界面顶部显式展示，而不是埋在 author.md。
6. **venue-informed ideas 与 link 的衔接**：venue 报告里的论文常无 arXiv id，
   `link_ideas` 接地会更依赖标题匹配，验真通过率待观察。
7. **多模型评审成本记账**：Cursor fast 模型 cost 恒为 0（CLI 不回报），
   `cost_usd` 只反映 claude 侧，报表口径要么补齐要么标注。
