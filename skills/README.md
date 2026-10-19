# Skill 套件索引

本项目有1个总控、12个共享节点、9个类型专属模块。完整项目说明、主流程图、调用方式和逐节点打磨方法在[根README](../README.md)，此处只维护源文件导航。

- [总控](aigc-creator/SKILL.md)：选择当前阶段、主模块与节点，组织交接、续作和变更。
- [清单](catalog.json)：机器可检查的唯一名称、源路径、分类和安装依赖。
- `core/aigc-*/`：PRD、脚本、视觉资产、场面调度、分镜、关键帧、Clip提示词、声音、剪辑、审查、拉片复刻、持续迭代。
- `modules/<用途>/aigc-<用途>/`：类型专属skill；每个模块README只说明其定位和入口。

## 类型模块

[剧情与漫剧](modules/narrative/README.md) · [商业广告](modules/commercial/README.md) · [科普讲解](modules/explainer/README.md) · [数字人口播](modules/presenter/README.md) · [纪实](modules/documentary/README.md) · [音乐](modules/music/README.md) · [产品演示](modules/product-demo/README.md) · [氛围艺术](modules/visual-art/README.md) · [混剪预告](modules/montage/README.md)

## 公共资源

公共资料跟随总控一起分发：

- [选择路线](aigc-creator/references/routes.md)、[交接协议](aigc-creator/references/handoff.md)、[连续性](aigc-creator/references/continuity.md)。
- [参考资产规范](aigc-creator/references/reference-assets.md)、[完整调度](aigc-creator/references/director-dispatch.md)、[Clip编译](aigc-creator/references/clip-prompts.md)。
- [镜头术语](aigc-creator/references/shot-glossary.md)、[拉片](aigc-creator/references/shot-study.md)、[限定持续迭代](aigc-creator/references/iteration.md)。
- [导演语言](aigc-creator/references/prompt-language.md)、[修饰词与表演语言库](aigc-creator/references/lexicon.md)。
- [三张用户截图拆解与原件](aigc-creator/references/screenshot-analysis.md)、[真实电影案例](aigc-creator/references/film-cases.md)。
- [平台模型适配](aigc-creator/references/model-adaptation.md)、[项目文件映射](aigc-creator/references/project-integration.md)。

源目录按用途分组，安装时按skill唯一名称平铺，包内引用不变。叶节点通过已明确项目或配套安装根定位公共资源，不将新源文件与旧全局入口混用。

安装更新见[使用说明](../05_工具与模型适配/AIGC创作Skill使用说明.md)。历史1.0测试结果见[旧版训练记录](../06_实验与复盘/2026-10-16_Skill链训练/README.md)。

1.1.0的范围和实际验证见[本轮计划](../spec/plans/2026-10-19-Clip创作系统.md)。
