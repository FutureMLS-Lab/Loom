# Rebuttal Factory — TODOs 与技术债

更新于 2026-08-14。

## 死代码清理（2026-08-14 已执行）

经 operator 批准后已删除：headless `analyze`/`draft` 整条链（web.py 路由、
`_rebuttal_analyze_job`、`_rebuttal_draft_job`、`analyze_project`、
`draft_project` 及其专属辅助 `_pdf_text`/`_paper_material`/`_review_material`/
`_evidence_material`/`_strip_markdown_fence`、`JOB_ANALYZE/JOB_DRAFT` 常量、
`auto_draft`/`execution_mode` 状态字段写入）、`rebuttal_task.update_studio`。
按计划保留：`rebuttal_task.update_state`（测试与运维脚本在用）。
注：注册接口的 `auto_draft` 请求参数仍在——它现在的语义是"导入后自动启动
live tmux Agent"，与已删的 headless draft 无关。

## 已知缺陷 / 改进项

1. ~~**图片验收没有产品入口**~~：已修（2026-08-14）——新增
   `POST /api/rebuttal/projects/<id>/verify-figures` 路由与 UI 按钮，
   且 delivery preflight 通过后 watcher **自动触发**三模型验收；
   最终批准按钮在全票通过前保持禁用。
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
