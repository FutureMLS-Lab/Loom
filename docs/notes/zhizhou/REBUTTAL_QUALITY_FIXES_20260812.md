# 问题与解决方案提纲（2026-08-12）

操作人反馈的质量问题、根因、最终解决方法与当前状态。截至 2026-08-12 10:50 AM (UTC-7)。

## 快速状态总览

| 事项 | 状态 |
|---|---|
| Reviewer 面板还原为 Cursor 三模型 | 已完成，已 commit + push |
| Rebuttal 2240 重做 | 全部门禁通过，等人工最终批准 |
| Rebuttal 2237 重做 | 三模型图片验收进行中，通过后等人工批准 |
| GUI paper 图片修复 | Fig1/Fig3 已确认修好，Round 4 进行中 |
| MCD paper 图片修复 | Fig1 已确认修好，正文 analysis 图待本轮产出 |
| Delivery 质量门禁代码 | 已实现并测试通过，**尚未 commit** |

---

## 一、Reviewer 面板漂移

- **问题**：Cursor 账号不可用期间，三模型评审面板被临时换成三个 Fable 档位（走 `claude -p`），且改动一直未提交地留在工作区。
- **解决**：
  - 还原 `CURSOR_REVIEWER_MODELS` 为 `gpt-5.6-sol-max-fast` + `claude-fable-5-thinking-max` + `cursor-grok-4.5-high-fast`，面板名还原为 `cursor-reviewer-panel`，全部走 Cursor CLI（已确认三个型号在恢复后的账号目录中可用）。
  - 两篇 WACV3 AR paper 的 `ar.json` 里的 `reviewer_models` 同步换回。
  - 同期被改掉的 Rebuttal/Delivery Agent 后端（Cursor → Claude 的应急方案）一并还原为 Cursor fast 模型。
- **入库**：已 commit + push 到 `rebuttal-factory` 分支（PR #6：https://github.com/FutureMLS-Lab/Loom/pull/6）。

## 二、Rebuttal 2240（Where Continual Diffusion Models Forget）

新交付 run：`20260812T083046Z-9df0b63d`，产物目录：

```text
/data/shared/zhizhousha/workspace/loom-project/claude-paper/wacv2027/paper-2240/rebuttal-output/delivery/attempts/20260812T083046Z-9df0b63d/deliverables/
```

| 反馈的问题 | 根因 | 最终解决 |
|---|---|---|
| Figure 2 文字不对齐、溢出面板边框 | 图片验收门只在"用户要求过重画"时生效，2240 走自动流程从未被任何模型或人视觉审查过 | 图已重画；三模型验收迭代 6 轮后全票通过 |
| 没写满 8 页（正文第 7 页结束，第 8 页只有半栏 references） | 无任何满页检查 | 决策：正文满 8 页、References 从第 9 页起。新版共 9 页、正文满 8 页（第 8 页已目检满页） |
| Table 1 末行 "Estimated FLOPs / unmeasured / Not inferred from band count" | Agent 想诚实声明 FLOPs 未测量，但把 "unmeasured" 当数据写进了结果表 | 该行删除；表格改为完整实测资源核算（invocations / payload 字节 / 耗时）；模板明令禁止占位值 |
| Appendix 整个消失（原稿 inline appendix 被砍且未产出 supplement） | Delivery Agent 执行"分离 supplement"政策时只删不建 | 决策：做成单独 supplement。新版附 6 页 `supplement.pdf`，恢复完整协议、表格、审计与负面结果 |
| rebuttal.pdf 只写了约 2/3 页 | 无满页要求 | 新版双栏写满整页（已目检） |

- **状态**：preflight + 三模型图片验收全部通过，停在 `await_delivery_approval`，等人工点击 Final artifact approval 后生成 bundle。

## 三、Rebuttal 2237（Curvature-Budgeted Quantization）

新交付 run：`20260812T083053Z-3de8dddc`，产物目录：

```text
/data/shared/zhizhousha/workspace/loom-project/claude-paper/wacv2027/paper-2237/rebuttal-output/delivery/attempts/20260812T083053Z-3de8dddc/deliverables/
```

- **反馈的问题与解决**：
  1. 没有 page-one teaser、没有方法流程图（全文只有两张小结果图）→ 已要求按修订后的诊断框架重画 teaser 与方法总览图（参考原始提交的 `teaser.pdf` / `method_figure.pdf` 但不复活已撤回的主张）；最终以三模型验收为准。
  2. 没写满 8 页 → 新版共 10 页、References 第 9 页起，正文满 8 页。
  3. rebuttal 只写了约半页 → 新版双栏写满整页（已目检）。
- **过程中的两个事故**：
  1. 凌晨三模型验收在临时目录清理时被 NFS 竞态（`Directory not empty`）搞崩，评审结果丢失 → `verify_delivery_figures` 的临时目录加 `ignore_cleanup_errors=True` 容错。
  2. Agent 编译好了 `supplement.pdf` 却忘在完成标记的 `supplement` 字段声明，导致产物缺 supplement → 已令 Agent 补声明并重新走 ingest。
- **状态**：流水线已恢复，正在跑三模型图片验收；全票通过后停在等人工批准。

## 四、AR 生成 paper：GUI Blindness Audit

路径：`research-factory/.RUD/wacv3-how-much-of-gui-agent-benchmark-performance-survives-blindness-an-input-a/work/manuscript/main.pdf`

| 反馈的问题 | 最终解决 | 复检结果 |
|---|---|---|
| Figure 1 teaser 变形（整体被纵向拉伸，圆形图标成椭圆） | 要求按原生宽高比嵌入（只锁宽度），装不下就按目标宽高比重新生成或改版式 | 已重画，比例正常（已目检） |
| Figure 2 太稀疏 | 要求压缩图块、收紧边距 | 本轮重构中被信息更密的新证据图整体替换 |
| Figure 3 图例压住 "normalized x" 轴标签 | 要求图例完全避开坐标轴 | 已替换为干净的水平条形图（log 轴生存率图，已目检） |

- **状态**：Round 4 进行中；收尾时还有 readiness gate（合并 main 后新增"必须有 page-one 总览图"检查）+ 三模型评审把关。

## 五、AR 生成 paper：MCD（Direction Matters）

路径：`research-factory/.RUD/wacv3-modality-contrastive-decoding-removing-dominant-modality-bias-in-omnimoda/work/manuscript/main.pdf`

| 反馈的问题 | 最终解决 | 复检结果 |
|---|---|---|
| Figure 1 文字太多、配色丑（纯红/纯绿/灰） | 每个 panel 只留一句主张，解释性文字移到 caption；换色盲友好的低饱和配色 | 已重画为 Okabe-Ito 风格三 panel，文字大减（已目检） |
| 正文没有 analysis 图（唯一分析图埋在附录 C.6） | 要求：附录任务分层图重设计后提升到正文；新增机制诊断图（成功/失败分支 margin 不对称）与 λ 剂量响应/gate 行为图 | Round 5 进行中，正文分析图尚未出现在当前中间版本，待本轮完成后复检 |

## 六、防复发的制度性修改（代码层）

改动位于 `loom/rebuttal_delivery.py`、`loom/web.py`、`tests/test_rebuttal_delivery.py`：

1. **强制图片验收**：任何含 revised paper 的交付，最终批准前必须三模型全票通过，且验收报告绑定当前 PDF 的 SHA-256（换 PDF 必须重新验收；旧报告一律视为 stale）。
2. **确定性满页检查**：delivery policy 恢复 `paper_body_page_limit`（WACV 默认 8）；preflight 检查 References 起始页必须晚于正文页限，页数不足直接打回。
3. **Agent 指令模板固定质量条款**：满页正文、满页 rebuttal、结果表禁止 "unmeasured"/"TBD" 等占位值、保留 teaser + 方法图、编译后逐页按印刷尺寸目检。
4. **`rerun-delivery` API 支持自定义反馈**（本次两篇 paper 的重做即通过该通道下发详细修改要求）。
5. **验收临时目录清理容错**（NFS 竞态不再导致整轮评审结果丢失）。
6. 回归测试：`tests/test_rebuttal_delivery.py` 等 32 项全部通过。

> 注意：第六节这批改动**尚未 commit**（第一节的 Reviewer 还原已提交）。需要入库请告知。
