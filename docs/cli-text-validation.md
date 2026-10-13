# CLI 字段状态与来源验证

2026-10-14，本轮修复文本模式的四项问题：可用标量值缺少来源、成功集合数量缺少来源、能力列表丢失已有原因、多电池/传感器条目没有编号。GPU 原先只打印数量，现在可以逐条呈现公共模型已有的名称与专用显存字节数；默认 backend 的 GPU 采集仍为 Unsupported，渲染 fixture 不代表实现原生 GPU。

所有文本值保留来源，缺失值保留状态与原因；能力原因仅在模型提供时显示，不补猜测原因。真实零、false、负温度仍是可用值，单字段失败不会替换其他条目；成功空列表与缺失/受限列表分别表达。设备编号表示当前顺序，不承诺跨采集稳定身份。存储集合标题也增加来源，因此同步更新其原生文本 gate；精确容量、默认脱敏及容量重叠提示保持原语义。

将文本呈现提取为 CLI 内部函数，使用同一公共 Snapshot，不读取硬件，不新增公共 API。命令、参数、退出码、默认隐私和敏感访问警告保持现有契约。JSON 仍输出完整 Schema 1 快照；C ABI 1、MIT、依赖、feature 与锁文件均无变更。文本格式有兼容性变化，脚本应使用 `--json`。

新增三项 Rust fixture 测试覆盖标量来源、缺失原因、多条目失败隔离、零/false/负温度、五个能力等级及原因；新增一项集成测试运行全部九个文本命令及对应 JSON 命令，不跨独立采集比较值或成员。新增三项 Python 负向测试覆盖来源丢失/未知来源、溢出、坏值、错误编号、空/缺失区别、隐私标签泄漏和能力原因格式。原生验收新增 `cli_text` gate，运行 CPU、内存、系统、GPU、网络、电池、传感器和能力命令，保留字段数量、集合状态及输出哈希，不保存原始值/名称/文本；存储继续单独验收。空或 Unsupported 的输出只表示呈现正确，不计作该设备实际读取成功。

本机运行 `scripts/check.ps1 -Cross`，fmt/Clippy、135 项 Rust 测试（含 doctest）、no-default-features、doc 拒绝警告、CLI/FFI 构建和 Linux/macOS 交叉构建通过。Python Ruff format/check、mypy --no-incremental（22 文件）、47 项 unittest、Schema/generated/golden、项目数据与文档链接检查通过。`scripts/build_c_example.ps1` 的 C 生命周期检查及 `native_smoke.py` 的 CLI/C/Python、存储文本和新增 cli_text gate 通过；实际执行 `--help`、`--version`。这是本机工作区预检，三平台原生验收和干净提交打包尚待执行，完成后补齐绑定源码的报告。

本轮未改变采集器、超时或缓存语义，也未新增硬件性能、实体设备或长期 fuzz 验证。
