# 接入、冲突与验收

## 运行时与独立状态根

初始化优先验证运行 bootstrap 的 `sys.executable`，不要求系统安装 `py` 或 `python` 命令。如果当前 Python 无 Tkinter，会在 PATH、常见 Codex 缓存和 WorkBuddy runtime 目录内寻找可用 Python；找不到时明确生成 CLI 入口。可以指定 `--python-exe` 和 `--git-exe`，指定路径无效时停止，不静默换用其他路径。

推荐 Codex 和 WorkBuddy 分别使用独立状态根（例如各自用户目录的 `.codex-skill-sync`、`.workbuddy-skill-sync`）；通过 `--state-home` 或 `SKILL_SYNC_HOME` 设置。程序不会自动迁移已有状态。一个状态根内仍可以登记多个 profile，但不同宿主沙箱建议使用不同状态根和对应启动器。GUI 显示状态根与 profile 状态目录。

生成的入口写入实际 Python、Git 和状态根路径，支持空格/中文，Windows 使用 UTF-8 代码页，不依赖 `py -3`。Windows 的 `/c/Users/...` 输入会规范为 `C:/Users/...`。现有入口有变化时，重新初始化相同环境并显式使用 `--refresh-launcher`，先备份后更新；不要直接覆盖未知快捷方式。

## 私有仓库首次认证

私有仓库无任何授权时，单给 URL 不可能绕过身份认证。先使用本机 Git 已有的凭据管理器；不要求 gh，不复制别的电脑的认证文件，不索要聊天中的令牌，不把仓库改为公开。

以下命令中的 Python 应使用已发现的实际解释器：

```text
python scripts/skill_sync.py --profile <id> auth --url https://github.com/OWNER/YOUR-SKILLS-REPO.git
python scripts/skill_sync.py --profile <id> auth --device --url https://github.com/OWNER/YOUR-SKILLS-REPO.git
```

`--device` 会检测 Git Credential Manager 是否提供设备登录；如有，由本人完成 GitHub 页面授权。缺少 GCM 时让当前智能体配置官方凭据管理器或复用已有登录。设备登录不是“无人参与获取权限”。

错误会区分认证不可用、访问被拒绝、网络/证书错误、远端变化。404 可能表示未认证、无权限或地址错误，工具不会伪称能确定是哪一种。读取成功只证明可读；写权限由实际推送及独立 SHA 核验确认。

本机环境变量中的 GH_TOKEN/GITHUB_TOKEN 可能覆盖已有登录。由当前智能体检查这一点，必要时在该仓库的 credential helper 中明确使用已授权登录；不要输出或覆盖令牌，不修改其他仓库认证。

## 无头同步与名单

```text
python scripts/skill_sync.py --profile <id> connect --url <仓库URL>
python scripts/skill_sync.py --profile <id> select --skills skill-a skill-b
python scripts/skill_sync.py --profile <id> sync --direction download
python scripts/skill_sync.py --profile <id> sync --direction download --yes
```

无 `--yes` 仅预览（完全一致的所选项可登记基线）。`--skills` 显式设置本次及后续名单；`--all` 显式选择当前可见全部项，只有用户确实要求全部时使用。GUI 与 CLI 共用 config.selected，离线 selection.json 在连接时迁入。`last_run.applied` 只表示实际改动，不等同于勾选名单，也不代表全部已安装的 skills。

## 冲突处理

GUI 的“差异与冲突处理”提供逐文件 unified diff、保存双方副本、采用本机、采用 GitHub、登记已合并目录。

```text
python scripts/skill_sync.py --profile <id> diff --skill <name>
python scripts/skill_sync.py --profile <id> resolve --skill <name> --take export
python scripts/skill_sync.py --profile <id> resolve --skill <name> --take local --yes
python scripts/skill_sync.py --profile <id> resolve --skill <name> --take remote --yes
python scripts/skill_sync.py --profile <id> resolve --skill <name> --take merge --merged-dir <完整合并目录> --yes
```

采用 GitHub 版会备份双方、安装远端版并登记一致基线。采用本机/合并版只记录对双方确切版本的明确决策，随后再上传；不会提前伪造一致基线。远端或本机再次变化时重新停止。已合并目录由当前智能体比较、修改、验证，工具不擅自自动合并文本。完全相同或所选行尾策略下等价的首次同名项可自动登记。

冲突副本在 profile 的 `conflicts/`，覆盖备份在 `backups/`，每次成功同步回执在 `receipts/`。新增没有旧版备份，会明确打印“新增，无旧版”，回执记录新增文件哈希。回执不是可以无条件删除文件的授权。

## 文本、依赖和平台配置

新配置默认 `comparison=lf`：已知文本类型、UTF-8 且无 NUL 的内容比较时将 CRLF 等价为 LF；二进制仍按字节。不会为了比较改写本机文本。旧配置保留 byte 策略，可通过 GUI 或 `policy --comparison lf` 启用。

仓库通过 .gitattributes 将 Markdown/Python/YAML/JSON 等共享源码按 LF 检出。安装始终验证实际文件字节，LF 比较只用于判断差异和冲突。

可在 skill 内添加 `sync-dependencies.json`：`{"skills":["grilling"]}`。工具校验声明依赖，并识别 `Call the Skill tool with "..."` 这种明确入口。下载时依赖必须已经在本机或同时被勾选；上传时依赖必须已在仓库或同时被勾选。不会悄悄扩大名单。自然语言、动态工具调用的所有依赖无法静态穷尽，仍由接入智能体核验。

共享周报 skills 使用 `OBSIDIAN_VAULT_DIR`、`WEEKLY_REPORT_SITE_DIR`、`WEEKLY_REPORT_BASE_URL`。其他工作流可使用 `ZOTERO_DATA_DIR`、`CODEX_PROJECTS_DIR` 等自己的配置。实际路径仅保存在当地环境/配置，不上传一台电脑的绝对路径替换另一台。当前工具没有任意文件 overlay 功能；需要专用逻辑时使用既有 variants，并由智能体维护。

## 验收界限

工具会检查被同步 Python 脚本的语法，不导入、不执行业务代码，不生成 __pycache__。若脚本要求更高 Python 版本，应换用该版本验证。成功表示文件落地/上传和哈希核验，业务调用仍由宿主智能体验证。

在 Mac 的隔离测试可模拟 Windows 路径、无 PATH Python、无 Tk 的候选筛选及启动器内容，但不能代替 Windows 双击和真实 GCM 授权测试。最终 Windows/WorkBuddy 验收由对应电脑完成。
