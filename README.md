# AIGC_Lab · AI 影像创作实验室

将想法转化为剧情脚本、角色与场景设定、分镜，以及可直接发送的 AI 图片/视频提示词。覆盖单张图片、图片系列、短片和 AI 漫剧。

提供 [aigc-creator 创作 Skill](skills/aigc-creator/SKILL.md)、分段视频连续性模板和 [12 类、60 条提示词模块](02_提示词库/分类模块/00_使用索引.md)。当前尚无真实作品，初始模块均未实测；检查结果见 [验收记录](06_实验与复盘/2026-09-30_AIGC创作Skill验收.md)。

## 从这里开始

首次使用按 [安装与使用说明](05_工具与模型适配/AIGC创作Skill使用说明.md) 安装 Skill，在 Codex 中打开本仓库，然后输入：

```text
请使用 $aigc-creator。我想做【图片/视频/漫剧】，大体想法是【内容】。
请每次问我一个关键问题，逐步丰富内容，最后生成可复制的提示词。
本轮只准备文字材料，并将可复用模块查重后归入提示词库。
```

也可以直接描述需求，由 Codex 自动匹配 Skill。续作、直接交付、不入库及更新方式见使用说明；手动建档见 [创建作品](04_作品项目/README.md)。

## 目录地图

| 位置 | 用途 |
|---|---|
| [AGENTS.md](AGENTS.md) | AI 每次进入项目时的工作地图 |
| [spec/](spec/harness-engineering.md) | Harness 管理规则、验收标准、决策与执行计划 |
| [01_创作模板](01_创作模板/README.md) | 需求卡、人设、分镜、提示词与完整作品模板 |
| [02_提示词库](02_提示词库/README.md) | 可复用模块；待测与实测结果分别记录 |
| [03_参考素材与风格](03_参考素材与风格/README.md) | 素材来源、风格参考和使用范围 |
| [04_作品项目](04_作品项目/README.md) | 每部真实作品的全部过程资料 |
| [05_工具与模型适配](05_工具与模型适配/README.md) | 经核验的模型能力、输入方式及版本差异 |
| [06_实验与复盘](06_实验与复盘/README.md) | 实测结果、失败原因和可复用经验 |
| [scripts/](scripts/validate_project.py) | 只读校验脚本；不调用生成平台 |
| [skills/aigc-creator/](skills/aigc-creator/SKILL.md) | 可安装的创作 Skill 源文件，随仓库版本管理 |

公共库保存通用方法，具体角色、剧情和发送提示词放在各自作品目录。

## 常用检查

在项目根目录运行，依赖 Python 3.10+ 标准库：

```powershell
# 结构检查
python -X utf8 scripts/validate_project.py

# 作品检查：替换为实际目录
python -X utf8 scripts/validate_project.py --work "04_作品项目/WORK-001_作品简称" --phase prompts
python -X utf8 scripts/validate_project.py --work "04_作品项目/WORK-001_作品简称" --phase delivery

# 修改校验脚本后运行回归测试
python -X utf8 -m unittest discover -s scripts/tests -v
```

无真实作品时仅检查结构。`scope=prompts` 验收文字材料；`scope=media` 还需当前版本的生成结果与实际画面检查。静态校验不证明媒体质量，完整要求见 [验收标准](spec/acceptance.md)。

## 版本与维护

Git 保存文本和小型参考图；大型媒体与工程文件默认忽略，需另行备份，迁移时补齐。每轮更新计划与复盘，通用经验按入库规范沉淀；当前无定时任务或自动发布。

管理方法参考 [OpenAI Harness Engineering](https://openai.com/index/harness-engineering/)，具体状态与验收规则见 [项目约定](spec/harness-engineering.md)。
