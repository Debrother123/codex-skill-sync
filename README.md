# Skills 同步助手 / codex-skill-sync

在 Mac、Windows、Codex、WorkBuddy 等智能体环境之间，按勾选名单同步 skills。Python 3.9+、Git；图形界面还需 Tkinter，无 Tk 时可用 CLI。

支持顶层链接型 skill 识别与真实目录授权、保留链接的更新、名称/功能搜索、组合筛选、每次操作单独选择范围、再次提交更新、冲突比较与备份、独立环境状态及 Windows 运行时探测。

## 给另一个智能体的安装指令

复制以下内容给目标电脑的 Codex、WorkBuddy 或其他智能体：

> 请从 https://github.com/Debrother123/codex-skill-sync 获取同步助手，先阅读 skills/codex-skill-sync/SKILL.md，再完成本机安装或升级。识别你实际使用的 skills 目录与 Python/Git/Tkinter，复用已有环境和配置，保留本机改动及备份，在我指定的位置生成启动快捷方式。缺少快捷方式位置时再问我。公开仓库只用于获取工具；个人 skills 连接我自己的数据仓库，已有配置直接复用，未配置时询问仓库地址。完成后验证窗口、目录、状态根和勾选名单，不自动同步所有 skills。

工具目录：[skills/codex-skill-sync](skills/codex-skill-sync)。也可下载 GitHub ZIP，解压后将完整目录交给目标智能体。

## 工具与数据

- 本公开仓库：只保存工具、说明和测试，采用 MIT 许可证。
- 你的数据仓库：保存你选中的 skills，建议私有。每台电脑使用自己的 Git 认证。
- 本机状态：保存环境、勾选、基线和备份，不上传、不跨机器复制。

工具当前不会在 GUI 中自动同时连接公开上游和个人仓库。后续更新工具时，让智能体从本仓库获取完整新版，备份比较后更新；个人 skills 仍由原数据仓库管理。

## 验证和限制

运行 `python skills/codex-skill-sync/tests/test_regressions.py`。Mac 上 23 项回归测试通过，1 项 Windows 专用启动测试跳过；Mac GUI 的搜索、筛选和操作范围已测试。Windows 与 WorkBuddy 的真实界面及认证需目标环境验证。

支持 GitHub 仓库与一层 skill 目录。每个环境一个数据仓库/版本来源；不自动安装 Git/Python，不自动合并内容冲突，也不复制智能体登录凭据。敏感文件检查只能发现部分常见风险，上传前仍应查看内容。

详细说明见 [使用说明](skills/codex-skill-sync/使用说明.md) 和 [故障处理](skills/codex-skill-sync/references/troubleshooting.md)。
