# 在 Cursor Agent 中调用图片生成工具

本文记录本次生成 `elegant-woman-portrait.png` 的方法。

## 1. 这是什么接口

这里调用的是 Cursor Agent 运行时提供的 `GenerateImage` 工具，不是 Loom 接口，也不是直接向 OpenAI、Anthropic 或 Google 发送 HTTP 请求。

Cursor 不提供图片后端选择参数。切换主 Agent 的 GPT、Claude 或 Grok 模型，不会改变 `GenerateImage` 的底层图片模型。

官方参考：

- [Cursor Agent overview](https://cursor.com/docs/agent/overview.md)
- [Cursor ACP tools](https://cursor.com/docs/cli/acp.md#cursorgenerate_image)

## 2. 当前 Agent 调用格式

```json
{
  "description": "<完整图片 Prompt>",
  "filename": "output.png",
  "aspect_ratio": "3:4",
  "reference_image_paths": [
    "/absolute/path/to/reference.png"
  ]
}
```

字段：

| 字段 | 作用 |
|---|---|
| `description` | 图片内容、构图、风格、颜色、文字和限制 |
| `filename` | 生成文件名；不能包含目录 |
| `aspect_ratio` | `1:1`、`4:3`、`3:4`、`16:9` 或 `9:16` |
| `reference_image_paths` | 可选，提供本地参考图的绝对路径 |

`reference_image_paths` 不需要时可以省略。

## 3. 本次实际 Prompt

```text
Photorealistic editorial portrait of an adult East Asian woman in her late
twenties, elegant cream blazer over a simple dark top, natural makeup,
shoulder-length black hair, calm confident expression, standing beside a large
window in a minimalist modern art museum.

Soft golden-hour side lighting, subtle warm and cool color contrast, 85mm
portrait-lens look, shallow depth of field, realistic skin texture, refined
magazine composition, tasteful and non-sexualized.

No text, logos, borders, or watermark.
```

调用参数：

```json
{
  "filename": "elegant-woman-portrait.png",
  "aspect_ratio": "3:4"
}
```

## 4. Agent 中的调用示例

```text
GenerateImage(
  description=<上面的 Prompt>,
  filename="elegant-woman-portrait.png",
  aspect_ratio="3:4"
)
```

工具执行完成后会返回生成文件的绝对路径，例如：

```text
<Cursor session assets>/elegant-woman-portrait.png
```

这个 session assets 路径由 Cursor 管理，不应提前硬编码。

## 5. 保存到指定项目目录

`GenerateImage` 的 `filename` 不能携带目录，因此先让工具生成，再将返回的绝对路径复制到目标位置：

```bash
cp "<GenerateImage 返回的绝对路径>" \
  "/data/shared/zhizhousha/workspace/loom-project/loom-claude-paper/.RUD/figure-redraw-v2/elegant-woman-portrait.png"
```

验证：

```bash
file "/data/shared/zhizhousha/workspace/loom-project/loom-claude-paper/.RUD/figure-redraw-v2/elegant-woman-portrait.png"
```

本次输出：

```text
PNG image data, 1024 x 1536, 8-bit/color RGB
```

## 6. 使用参考图

如果希望接近某张论文图或视觉风格，传入参考图：

```json
{
  "description": "Generate a clean scientific method illustration inspired by the references. Do not copy logos, text, or exact composition.",
  "filename": "method-concept.png",
  "aspect_ratio": "16:9",
  "reference_image_paths": [
    "/absolute/path/reference-1.png",
    "/absolute/path/reference-2.png"
  ]
}
```

参考图用于风格和构图提示，不应要求模型逐像素复制受版权保护的作品。

## 7. 论文图片的推荐用法

图片模型适合生成：

- 插画和视觉隐喻
- 场景、人物和物体
- Teaser 中的装饰性素材
- 风格探索草图

不建议直接生成：

- 实验曲线和柱状图
- 必须精确的数字
- 公式、表格和坐标轴
- 大量论文文字

推荐混合流程：

```text
GenerateImage：生成插画素材
Python / SVG：添加文字、箭头、公式和真实实验数据
LaTeX：引用最终矢量图或高分辨率图片
```

这样可以避免图片模型写错论文数字、公式和标签。

## 8. 注意事项

- 只有用户明确要求生成图片时才调用。
- Prompt 应明确人物为成年人，避免年龄歧义。
- 明确写出 `No text, logos, or watermark`，减少伪文字。
- 生成后必须人工检查手指、面部、文字和局部结构。
- 图片生成成功不代表适合直接放入论文。
- 当前接口不能指定底层图片提供商或模型。
