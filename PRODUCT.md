# Skills 同步助手

面向在多个电脑和智能体之间维护 skills 的用户。任务是找到本机 skill，了解实际路径和同步状态，选择范围后上传或接收。保留 Python 标准库/Tk 桌面实现、现有 profile 和每次询问范围的约定。

## 本轮交互决定（product-design spec）

- 链接型 skill 默认可发现；第一次同步前明确批准“管理真实目录”，批准绑定当前解析路径，路径变化后失效。取消不写配置、不上传。rule/name-object-scope-consequence、rule/irreversible-action-safeguard。
- 下载备份并替换真实目录内容，入口链接不变；撤销目录授权只删本机授权记录，不删文件。rule/destructive-proportional。
- 指向相同实际目录的入口合并展示，批量同步拒绝重复/重叠目标，避免一次操作覆盖同一份文件。rule/smallest-intervention。
- 原环境内完成发现与同步，不要求为链接新建环境。rule/preserve-mental-model。
- 保留每次范围选择（全部勾选 / 可见勾选），两个选项均可见且初始不选；授权与同步确认分步且不嵌套。rule/control-matches-cardinality、rule/no-nested-modals。
- 列表显示路径与状态；断链、未授权、目标变化、冲突分别提示恢复动作。筛选空结果可清除筛选；忙碌有明确进度提示。rule/cover-reachable-states、rule/empty-state-action。
- 使用原生键盘可达控件；Tab 导航、Space 勾选、Escape 关闭对话框。rule/keyboard-complete-flow。

未决策：无。Windows junction 检测尽力识别，真实 Windows 验收单独记录。
