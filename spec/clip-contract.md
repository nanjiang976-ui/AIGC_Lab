# Clip 与 Shot 数据契约

此契约是现有作品 `schema_version: 1` 的可选扩展，不批量迁移旧作品。Shot 表示连续的设计镜头；Clip 表示一次模型输入与生成的片段。一条 Clip 可以含多个 Shot，一个连续 Shot 也可以因生成时长限制分成多条 Clip。镜头切点与生成分段分别记录，不能为了通过校验把同一完整 Clip 正文复制到每个 Shot。

原有文件、状态、版本、证据与路径规则继续遵循 [Harness 规则](harness-engineering.md)。本文件规定自动可检查的结构；调度内容、输入图是否合格、模型能力、声画同步和成片质量仍按 [验收标准](acceptance.md) 检查。

## 作品选择发送布局

在 `project.json` 中使用以下可选字段：

```json
{
  "schema_version": 1,
  "prompt_layout": "clips",
  "clips_file": "04_生成提示词/clips.json"
}
```

以上是字段摘录，不能代替完整作品 manifest。

| 字段 | 约束 |
|---|---|
| `prompt_layout` | 缺省为 `per_shot`，保持旧作品逐镜发送规则；`clips` 仅用于 `video` / 有时间轴的 `comic` |
| `clips_file` | `clips` 布局中可省略，缺省为 `04_生成提示词/clips.json`；自定义时须为作品目录内相对路径。`per_shot` 不携带此字段，避免留下未校验的 Clip 台账 |

`03_分镜表.csv` 保留原表头与 `EP01_SH001` 格式的 Shot ID。在 `clips` 布局的提示词就绪门禁中，每个 Shot 的编号、正时长、场景与完整画面描述仍须填写；`image_prompt`、`video_prompt` 列保留，但可为空，因为对应正文集中在 Clip 包中。静态起点、完整调度、入口与出口由设计稿交接并人工检查；留空这些列不表示可以省掉必要画面信息。

## Clip 台账

```json
{
  "schema_version": 1,
  "revision": "v001",
  "clips": [
    {
      "clip_id": "EP01_CL001",
      "duration_seconds": 8,
      "entry_mode": "text_to_video",
      "references": [],
      "segments": [
        {
          "shot_id": "EP01_SH001",
          "shot_start_seconds": 0,
          "shot_end_seconds": 3,
          "clip_start_seconds": 0,
          "clip_end_seconds": 3
        },
        {
          "shot_id": "EP01_SH002",
          "shot_start_seconds": 0,
          "shot_end_seconds": 5,
          "clip_start_seconds": 3,
          "clip_end_seconds": 8
        }
      ]
    }
  ]
}
```

此例为结构示例，假设 CSV 中两个 Shot 的时长分别为 3 秒、5 秒；不代表已有作品、参考图或生成结果。

| 项目 | 自动校验 |
|---|---|
| 台账版本 | `schema_version` 为整数 `1`，`revision` 精确匹配当前作品版本；JSON 重复键、非法数值拒绝 |
| Clip 编号 | 格式 `EP` + 至少两位数字 + `_CL` + 至少三位数字，例如 `EP01_CL001`；全作品唯一 |
| Clip 时长 | JSON 数值，有限且大于零；字符串、布尔值、负数、零、NaN、Infinity 拒绝 |
| `entry_mode` | 仅接受下表列出的已定义路线，不能把其他模式随意填写成已实现能力 |
| `references` | 对象数组，缺省视为空数组；每项的 `label`、`role`、`file` 在就绪时完整 |
| `segments` | 按 Clip 内时间顺序排列的对象数组；就绪时至少一个区间 |

每个 `segments` 条目的四个秒数字段均为有限 JSON 数值，起点非负，终点大于起点。所有 `shot_id` 必须在 CSV 内存在。

## 映射与时间检查

1. 单区间的 `shot_end_seconds - shot_start_seconds` 等于 `clip_end_seconds - clip_start_seconds`。这表示等速映射；慢放、快放、回放或叠化需另外设计，目前不能用本契约伪装成普通等速片段。
2. 同一 Clip 的区间按数组顺序无重叠地衔接；就绪时从 `0` 连续覆盖到 `duration_seconds`，不留空段。区间不得超出 Clip 时长。
3. 汇总一条 Shot 在全部 Clip 中出现的区间，按 Shot 局部起点排序后，须无重叠；就绪时从 `0` 完整覆盖到 CSV 中该 Shot 的计划时长。不能漏掉整个 Shot，也不能重复生成同一 Shot 时间区间冒充新增内容。
4. 一个 8 秒连续 Shot 可映射为 Clip 1 的 Shot 区间 `0–3` 对应 Clip 局部 `0–3`，以及 Clip 2 的 Shot 区间 `3–8` 对应 Clip 局部 `0–5`；两条 Clip 保留同一个 Shot ID。真实成片剪辑需要额外重叠素材时，单独记录制作余量与剪辑入出点，不把重叠写进本计划覆盖台账。
5. 数值比较使用 `0.000001` 秒的绝对容差，仅吸收浮点运算误差；不是模型控制精度承诺。台账为计划时间，真实生成的时间点与剪辑结果另外回填。

## 输入路线与实际参考

`references` 只记录本 Clip 实际准备上传或绑定的文件，示例：

```json
{
  "label": "@Image1",
  "role": "identity",
  "file": "参考资产/人物A四宫格.png"
}
```

`label` 是本 Clip 内唯一的单个标识，不得含空白；`@Image1` 只是示例，最终标签必须与目标平台真实输入槽核对。正文的引用完整性、平台语法及绑定是否被接受由人工/工具检查，结构校验不声称通用平台支持该语法。

`role` 取 `identity`、`scene`、`first_frame`、`last_frame`、`style`、`audio`。同一张图若确实有两个输入用途，分别登记并使用各自唯一标识，不默认扩大身份图的控制范围。

| `entry_mode` | 提示词就绪所需引用 |
|---|---|
| `text_to_video` | `references` 为空；创作时看过的参考另放设计稿，不伪称已上传 |
| `reference_to_video` | 至少一份 `identity` / `scene` / `style` 图像引用；仅有音频或首帧用途不算此路线的身份/场景参考 |
| `first_frame` | 至少一份 `first_frame` 图像引用 |
| `first_last_frames` | 分别至少一份 `first_frame` 和 `last_frame` 图像引用；身份图不代替末帧 |

每个已填 `file` 必须真实存在且非空，位于当前作品目录内；禁止绝对路径、驱动器相对路径、`..`、符号链接与 Windows reparse point。即使仍为草案，也不接受已填但不存在的参考文件。无实际素材时留空并保持草案，不写假路径。

除 `audio` 外的用途要求图像扩展名 `.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp`、`.tif`、`.tiff`、`.avif`。此检查只确认路径、非空与文件名声明，**不解码图像，不证明文件内容是真图、不证明四宫格合格、不证明平台支持该格式**。音频的解码、时长、版权和平台能力同样另验。

## 可发送文件

`clips` 布局下的 `04_生成提示词/本次发送.md` 按 Clip ID 建标题，每条包含非空正文；例如：

````markdown
### EP01_CL001

```text
此处放一条完整、自足且已经适配目标入口的 Clip 正文。
```
````

台账中每条 Clip 必须恰好有一个标题组。缺标题、重复标题、额外 Clip 标题、一个标题写多个 Clip ID、未闭合代码块、空代码块均失败；在正文、代码块或 HTML 注释中提到编号不能代替标题。不得夹入 `EP01_SH001` 形式的逐 Shot 发送标题；Clip 内的 `Shot 1`、`Shot 2` 和时序写在可复制正文内。上传说明、内部版本、文件路径与审核记录保存在稿件外部或独立设计记录中。

结构校验只核对编号组与非空文本；对完整描述、否定词处理、实际素材绑定、声音路线及平台可读性的判断继续人工核验。通用 Clip 创作包和最终平台发送版须分开保存，不能让仅有通用包的状态冒充已完成平台适配。

## 草案与就绪

- `DRAFT` / 未完成的 `ARCHIVED` 在 `structure` 检查中可暂缺 Clip 台账，可有空 Clip 数组，可暂缺 Clip ID、模式、时长、参考字段或区间字段，也可留覆盖缺口。已创建台账仍必须提供正确的台账 schema 和当前 revision。
- 草案中已填写的 ID、类型、数值、引用路径、参考用途、重复项、已知区间越界和重叠仍检查；不能以草案状态掩盖明确错误。
- 草案中必需的 `本次发送.md` 等文件仍须存在且不是零字节，正文可以是尚未完成的说明或空白；这是原项目文件存在规则。
- `PROMPT_READY` / `GENERATED` / `ACCEPTED`，或显式 `--phase prompts` / `--phase delivery`，启用完整字段、区间覆盖、输入依赖及发送标题门禁。当前需图路线缺图时不能标为提示词就绪。
- 旧作品未声明 `prompt_layout` 时继续逐 Shot 校验。新增 Clip 模式不改变历史生成或审查结果；改动已准备/已验收内容仍升作品 revision 并重置受影响状态。

## 验证边界

运行 `python -X utf8 scripts/validate_project.py --work 04_作品项目/作品目录 --phase prompts` 检查指定作品。相关自动测试为 `scripts/tests/test_clip_validation.py` 与原项目校验测试。

自动通过只证明计划数据与引用结构一致，**不证明调度六维已完整、不证明数值有依据、不证明多 Shot 单次生成受当前模型支持，也不证明生成、完整播放或人工验收成功**。参考路线、模型时长、原生声音、真实画面连续性、实际 Clip 时间与用户接受分别记录证据。
