# AIGC 全链路 Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Follow the user-authorized continuous execution; preserve original checkout and preview before pushing. No recursive deletion.

**Goal:** 建立可安装、可衔接、经过行为演练的 AI 视频创作 skill 套件，并交付完整预览。

**Architecture:** 一个总控、10 个共享节点、9 个类型模块；共享规则只维护一处，包清单记录依赖。原项目作品契约保持兼容。

**Tech Stack:** Markdown、YAML、JSON；必要的安装/检查工具只用 Python 标准库。

**Spec:** [设计与原始要求](2026-10-16-AIGC全链路Skill设计.md)。

## Global Constraints

- 只在已授权工作树写入；不创建新作品冒充测试产物；训练材料放复盘目录。
- 用户规则如需改意先询问；推送前预览并等待确认；不做外部媒体生成。
- 总控保留单图/续作/不保存/不入库行为；CSV 字段和作品状态语义不变。
- 每个文件只有一个写入者；源文件/安装副本不得无条件覆盖用户修改。
- 无真实媒体证据的输出不称平台或媒体通过。

## Review Focus

| 条件 | 预期行为 | 归属 |
|---|---|---|
| 只有一句想法 vs 已有完整PRD | 选择访谈/校验，不重复全问卷 | 任务2/5 |
| 多角色、移动机位、前段实际状态不同 | 区分空间/画面坐标，继承真实状态 | 任务2/5 |
| 混合类型或无人物/无故事 | 选主模块并裁剪节点，不套用剧情模板 | 任务3/5 |
| 平台/参考素材未知 | 通用正文可交付，依赖未满足正文标草案，不伪造平台能力 | 任务1/2/5 |
| 安装同名目录被用户改过 | 计划显示冲突，不默默覆盖或删除 | 任务4 |

## Task 1：共同协议与研究资源

**Files:** 总控 references/handoff.md、prompt-language.md、screenshot-analysis.md、film-cases.md、model-adaptation.md、lexicon.md；assets/reference-screenshots；本轮研究记录。

**Interfaces:** 消费本轮用户规则、截图、基线输出、官方资料；产出统一交接字段、可发送文本规范、已验证的来源边界。

- [x] 保存行为基线与截图结构拆解。
- [x] 写明确交接与镜头三要素、时长、张力和表演规范。
- [x] 写电影案例和模型适配记录；核查实际来源。
- [x] 独立审阅来源与规则的对应关系。

## Task 2：10 个核心节点

**Files:** skills/core/aigc-{prd,script,visual-assets,blocking,storyboard,keyframes,video-prompts,audio,editing,review}/SKILL.md、agents/openai.yaml，必要的少量具体例子。

**Interfaces:** 共同协议；每个节点产出上游可追溯的创作结果及下游输入。只通过总控依赖引用公共资源。

- [x] 读取基线，确定需要改善的具体行为。
- [x] 建立明确触发边界、输入、工作方法、输出与验收标准。
- [x] 按环节加入原截图的有效结构和“争吵到委屈哭泣”翻译方法。
- [x] 独立行为执行/审查，按实际问题修订；v002及3题构图回归已复审，无未解决确定问题。

## Task 3：9 个类型模块

**Files:** skills/modules/<module>/README.md、aigc-<module>/SKILL.md、agents/openai.yaml。

**Interfaces:** 接收类型/目的/素材条件；选择核心节点、注入类型约束；不重写已确认设定。

- [x] 根据9类基线创建专属路线、判断方法与合格例子。
- [x] 区分用途与风格/载体；定义混合类型优先级。
- [x] 每模块实际演练一个代表请求和一个边界变化。
- [x] 独立审查与修订。

## Task 4：索引与安全分发

**Files:** skills/catalog.json、skills/README.md、scripts/skill_bundle.py、scripts/tests/test_skill_bundle.py、使用说明。

**Interfaces:** catalog version=1；skill name/source/group/dependencies；flat user installation。默认只预览安装计划，明确 --apply 后才复制，覆盖前备份且必须使用显式更新选项；不删除文件。测试目标使用临时隔离目录。

- [x] 先编写有意义反例：重复名称、缺依赖/环、越界/重解析引用、冲突文件、缺少资源；运行确认失败。
- [x] 实现清单检查、计划/安装和可回溯备份；不执行未知脚本。
- [x] 验证首次安装、幂等、保护同名改动、显式更新与复制完整性。
- [x] 独立代码审查，运行相关测试与项目61项回归。新增40项，总101项通过。

## Task 5：总控、README、AGENTS 与整体演练

**Files:** skills/aigc-creator/SKILL.md、其必要旧refs、README.md、AGENTS.md、spec/plans/README.md、06_实验与复盘/2026-10-16_Skill链训练/。

**Interfaces:** 已完成核心/类型清单；流程与文档链接；所有行为测试和预览记录。

- [x] 改总控选择规则，完整保留旧功能，支持完整PRD、单节点、续作、变更影响。
- [x] README 编写主流程图、完整分类、使用示例、衔接、逐节点打磨方法及真实状态。
- [x] 项目级 AGENTS 写入用户核心逻辑及6条共同规则。
- [x] 核心完整文字链、类型模块、陌生题材、状态变更演练；不把检查表存在当作已通过。
- [x] 全部检查、全量独立审查与修订，制作预览入口。
- [x] 提供明确文件范围和用户预览；收到明确确认后发布87文件至codex/aigc-skill-chain，远程核心提交与本地一致。

## 验证命令

`python -X utf8 scripts/validate_project.py`

`python -X utf8 -m unittest discover -s scripts/tests -v`

`python -X utf8 scripts/skill_bundle.py validate`

逐skill运行系统 skill-creator 的 quick_validate.py；安装工具在隔离目标进行演练。

## 当前进度

- 工作树 codex/aigc-skill-chain 已建立；继承3个相关现有文件；基线结构与61项测试通过。
- 20个skill源包与公共资源、README/流程图、AGENTS、使用说明已完成；包格式20/20通过，隔离安装20包54文件一致。
- 12个现有基线、28个前向实际案例已保存；唯一确定文字裁切冲突已作v002修订，3题针对性复测与最后局部复核均完成。31个新套件实际文字案例全部已审，当前无未解决确定P0/P1/P2/P3。
- 根代理已实际运行101项回归并全部通过；Chrome已查看README流程图19节点与分类表，无横向溢出/相关控制台错误。
- 用户已预览通过并授权发布。87文件核心提交dc3b4b83ac6879159f0420cf92a06c79dd9e59b6已推送codex/aigc-skill-chain并核验远程；发布状态文档同步到同一分支。
- 原目录另有持续迭代流程和作品资料并行改动，未带入本发布范围。工作树只将作品索引“暂无作品”的过时文字改为指向已有WORK-001，未修改任何作品内容。原目录51个未提交文件发布前后摘要一致；main未合并，真实全局安装未执行。
