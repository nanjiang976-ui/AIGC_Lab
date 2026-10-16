# AIGC 全链路 Skill 安装与使用

版本：1.0.1 · 2026-10-16。套件包含总控 `aigc-creator`、10个共享节点、9个类型模块。项目介绍、流程图、节点衔接与训练方法以[根README](../README.md)为准，这里专门说明安装、更新和故障定位。

## 安装前

需要 Python 3.10+，工具仅使用标准库。先打开完整 AIGC_Lab 工作区，运行：

```powershell
git status --short
python -X utf8 scripts/validate_project.py
python -X utf8 scripts/skill_bundle.py validate
```

源目录按模块分类，安装目录按skill名称平铺；完整清单见[catalog](../skills/catalog.json)。只复制总控会缺少新节点，只复制叶节点会缺少共享协议。作品模板与公共提示词库仍在项目中，skill安装不会下载整个仓库。

已有本地修改先比较、保留，不运行强制重置，不假定新版本能覆盖用户自己的改动。尚未发布的工作树版本不能通过远程下载获得，应使用当前已审阅的本地源码。

## 提示词范围与制作路线

`prompts` 表示本轮只准备文字，不是纯文生视频路线。完整多镜头主流程仍准备所需角色、场景、道具参考图提示词和逐镜静态首帧提示词，再交动态正文；缺少真实图时用文字候选和待生成/审图/绑定清单承接。用户明确纯文生、只做当前节点或已有适用资产时，按该范围裁剪或复用。

```text
请使用 $aigc-creator，按主流程准备这部短片的角色/场景/道具参考图、逐镜首帧与视频动作提示词。
本轮只生成提示词，不调用媒体生成；尚无实际参考图，需将候选与真实资产依赖标清楚。
```

## 预览、安装与更新

本用户默认安装在 `C:\Users\NJ\.codex\skills`。下面命令尊重已设置的 CODEX_HOME；不覆盖该环境变量：

```powershell
$aigcSkillBase = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    Join-Path $env:USERPROFILE '.codex\skills'
} else {
    Join-Path $env:CODEX_HOME 'skills'
}

# 默认只预览，不写入
python -X utf8 scripts/skill_bundle.py install --target $aigcSkillBase

# 首次安装：存在内容冲突时整批不写
python -X utf8 scripts/skill_bundle.py install --target $aigcSkillBase --apply

# 已查看差异并决定更新：先备份将覆盖的文件，再复制
python -X utf8 scripts/skill_bundle.py install --target $aigcSkillBase --apply --update
```

JSON报告包含 `ok`、`errors`、`actions`、`extras_preserved`、`backup_dir`、`applied`、`written` 与 `attempted`：

- 无 `--apply` 的操作只显示计划。
- 同名目标文件与源码不同、未加 `--update`：报告冲突，整批不写。
- 更新先把所有将被覆盖的文件备份到目标目录旁的 `skills-backups/时间戳-随机ID/`，不放进会被当作skill扫描的目录。
- 未知额外文件只报告并保留；没有任何删除步骤。重复安装同内容是幂等操作。
- 备份失败会阻止安装写入；中途I/O失败会保留备份，并报告已完成和可能已触及的文件，不声称事务原子回滚。
- 安装期间不要让另一个进程同时改相同目录。路径引用、源文件/目标重解析跳转和冲突会被检查。

需要恢复时，先查看 `backup_dir` 和受影响文件清单，逐个检查再恢复；不要批量删除skill目录。备份里只含覆盖前的文件，不能把它当作整机快照。

## 怎样确认可用

1. 包工具验证名称、清单、依赖、资源及包内本地链接。
2. 安装后再次运行预览，应显示源码文件为 `unchanged`；未知额外文件仍会列出。
3. 在Codex技能列表确认20个名称。新技能没有出现在当前会话时重启，再明确指定一次，例如 `$aigc-prd`。
4. 执行一个有代表性的文字请求，检查真实输出与交接；允许自动调用的配置不能代替这一步。

各包 frontmatter 中 `metadata.bundle=aigc-lab`、`metadata.bundle_version=1.0.1` 标识配套版本。完整项目环境优先使用当前明确工作区的源码与共享资料，脱离项目再检查安装包是否配套；旧全局总控不能替代新工作树的公共协议。

技能包的结构和发现机制依据[OpenAI官方Skill说明](https://learn.chatgpt.com/docs/build-skills)；本机的实际加载还须按上面步骤验证。安装不需要媒体平台密钥，也不增加后台任务、定时任务或自动发布。

## 常见调用

| 目的 | 示例 |
|---|---|
| 从模糊想法开始 | `请使用 $aigc-creator。我想做两个人争执后和解的短片，每次问一个问题。` |
| 完整PRD直达调度 | `请使用 $aigc-blocking，读取这份PRD、脚本和场景布局，只补调度必要缺项。` |
| 广告 | `请使用 $aigc-commercial，为这个产品规划15秒广告，区分已证实卖点与创意建议。` |
| 首帧 | `请使用 $aigc-keyframes，将第3镜拆成确定瞬间的图片正文，动态过程交给视频节点。` |
| 视频正文 | `请使用 $aigc-video-prompts，给第3镜可复制正文，设置和素材映射放在代码块外。` |
| 局部修订 | `第2镜实际B已经站起来了，按真实状态修第3镜并列出受影响的后镜。` |
| 单图／不保存 | `只做一张产品图的提示词，不写故事，不保存文件。` |

不入库与不保存的区别、作品文件映射、六条共同规则、训练方式均见根README。媒体生成需要当前授权与真实工具能力，自动选择skill不等于自动花费或发布。

## 验证和维护

套件改动后运行包校验、逐skill quick_validate、相关行为题。脚本改动再跑项目tests；已有真实作品还按prompts/media范围检查。保留用户作品历史与当前状态，不为了套用新节点强制迁移旧CSV。

源与安装副本不是自动同步关系。新方法通过真实演练后再升套件版本并更新安装；新增词语/案例保留来源、用途和验证边界。测试报告、安装计划和媒体证据分别保存，不能互相替代。
