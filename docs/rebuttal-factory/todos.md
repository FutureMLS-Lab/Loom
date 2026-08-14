# Rebuttal Factory — TODOs 与技术债

更新于 2026-08-13。死代码条目**只列不删**，等 operator 逐项定夺。

## 死代码 / 遗留路径候选（等定夺）

| # | 位置 | 说明 | 现状 |
|---|---|---|---|
| 1 | headless `analyze`/`draft` 整条链：web.py 路由 `("analyze","draft")`、`_rebuttal_analyze_job`、`_rebuttal_draft_job`、`auto_draft` 状态接链、`JOB_ANALYZE/JOB_DRAFT` | 早期的无 tmux 版本（模型一次性产 concerns/responses），已被 live tmux Response Agent 取代 | API 仍可达，但前端 `rebuttal_factory.js` 从不调用 |
| 2 | `rebuttal_task.update_studio` / `update_state` | 产线代码直接 read/write state | 仅测试与外部运维脚本使用（`update_state` 建议保留给脚本） |
| 3 | 状态字段 `execution_mode` | 只在 `_rebuttal_start_agent` 写死 `"tmux"`，无任何读方 | 佐证 #1 的双模式残留 |

## 已知缺陷 / 改进项

1. **图片验收没有产品入口**：`approve_delivery` 强制要求三模型验收通过且
   绑定当前 PDF，但触发 `verify_delivery_figures` 目前只能靠外部脚本
   （`/data/shared/zhizhousha/.cursor-runtime/scripts/delivery_monitor.py`）。
   应加 `POST /api/rebuttal/projects/<id>/verify-figures` + UI 按钮，
   preflight 通过后自动触发更佳。
2. **失败迭代回路未产品化**：preflight/验收失败后"报告喂回同一 Agent pane、
   删 marker、置回 running、等新 marker 再 ingest"这套循环目前活在运维脚本里；
   watcher 原生支持多轮迭代会更稳。
3. **仅 WACV/PDF 路径被实战验证**：政策里 `rebuttal_format` 支持 text box
   （OpenReview markdown）场景，但 delivery harness 只实现了 PDF 产物链；
   接非 PDF 会议前需要补 text 模式的构建与校验。
4. **supplement 声明易漏**（2237 事故）：Agent 编译了 supplement 却漏填
   marker 的 `supplement` 字段导致产物缺失。技能已写明，但 harness 可以更硬：
   工作区存在 `supplement.pdf` 而 marker 未声明时直接报错而不是默默忽略。
5. **政策时效**：Studio 政策一次冻结长期使用，CFP 页面改版不会被发现；
   可加"重新抓取并 diff"入口，变更时提示重新人工批准。
6. **删除语义不对称**：删 Studio 要求先删光子项目；删项目保留磁盘产物但
   UI 无从再挂回（重新 import 会生成新 project id、旧 attempts 变孤儿）。
7. **NFS 临时目录竞态**：`verify_delivery_figures` 已加
   `ignore_cleanup_errors`；`run_reviewer`（ar_task）同模式未加，同样跑在
   共享盘 TMPDIR 时理论上有同类风险。
8. **一页 rebuttal 的"满页"无确定性检查**：正文满页有 References 起始页
   检查兜底，rebuttal 是否写满整页目前只靠 Agent 自检 + 人审；可考虑
   渲染末页做墨迹覆盖率启发式。
