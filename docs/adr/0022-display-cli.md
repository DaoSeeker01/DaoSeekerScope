# ADR 0022：显示器命令行文本

状态：开发版实施；本轮本机验证及未执行项见[验证记录](../display-text-validation.md)。

增加 `dscope display`。解析、限额、隐私选项、退出码沿用已有命令；`display --json` 仍输出完整 Schema v1 快照。文本只消费 `Snapshot.static_info.displays`，不查询原生 API、不读取 EDID、不改变缓存或采集范围。

集合输出条目数及来源，随后逐条输出名称、宽高的值或状态/原因。空集合明确表示本次 backend 可见集合为空；集合不可用时不输出虚构的零条目。条目序号仅表示本次顺序，不是稳定标识或物理显示器数量。字段失败保留其他字段与条目。

宽高标签按各字段的 Source 决定，而不是按 CLI 编译平台猜测：Win32 为 Signal width/height pixels，AppleApi 为 Mode width/height pixels，其他来源为 Width/Height pixels。这些来源的语义沿用 ADR 0019/0020/0021；不计算新分辨率、不使用候选模式、不宣称面板原生像素。Linux 默认名称继续 PrivacyRedacted、宽高继续 Unsupported；双重显式隐私授权及 stderr 警告沿用既有路径。

文本供人阅读，保留现有缺失值格式，不作为机器解析契约；采集时间、完整状态及程序处理使用 JSON。内部 native_smoke 的文本守卫仅用于回归，保存计数/状态/摘要哈希，不归档名称或原始文本。不同进程不比较拓扑/数值，避免热插拔造成假失败。

兼容性：CLI 子命令是新增；`daoseeker-scope-cli` 的公开 `Command` 枚举增加 `Display`，直接依赖该开发版 crate 并穷举匹配的调用方须增加 `Command::Display` 分支。这是尚未发行的 0.1 API 草案变更，不宣称源代码完全兼容；不顺带修改既有枚举的 non_exhaustive 策略。核心 Rust 模型/入口、C ABI 1、Schema 1、依赖、公开 feature 与 MIT 许可证不变。回滚删除新增命令和分支，既有 JSON 无需迁移。

验收：解析与隐私、文本状态/来源、跨来源像素标签、空/缺失集合、字段隔离、完整 JSON 往返、实际 CLI 文本、八 crate 打包及交叉编译。既有 cli_args fuzz 增加 display 种子；没有增加 fuzz 目标。实体 Mac/Linux 显示器验证仍按设备安排延期。
