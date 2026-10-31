# Linux amdgpu 温度采集

本轮让 Linux hwmon 后端识别 `amdgpu` 实际提供的 1–3 号温度通道，并按毫摄氏度转换为摄氏度。没有这些通道时不会生成默认值；设备可能只提供部分通道。具体规则和来源见 [ADR 0047](adr/0047-linux-amdgpu-temperature.md)。

读取使用普通用户权限，不查询标签或设备标识。坏值、权限拒绝、未启用或故障通道分别处理，健康通道继续保留。amdgpu 读操作返回 EPERM 时存在驱动状态歧义，返回 Unavailable/Unknown，不能直接断言权限不足；打开文件时的权限拒绝仍正常报告。应用也不应把驱动报告的零值自动当作无设备。

## 已执行与待执行

Windows 本机新增两项合成 Rust 测试已通过，覆盖三通道单位、单字段错误、刷新/静态缓存、隐私、可选通道、标志位与条目上限。Linux 原始 errno 测试尚待原生 CI 执行。本机没有真实 Linux AMD GPU，不能把合成输入写成设备温度验证。

本机 `pwsh scripts/check.ps1 -Cross` 已通过 fmt、严格 Clippy、274 项 Rust 测试、无默认功能、严格文档、FFI/CLI 构建与 Linux x64/macOS ARM64 交叉 check。Python 全套 297 项中 292 通过、5 跳过；Ruff 与 mypy（73 文件）通过。`python scripts/check_schema.py` 的生成一致性、黄金样例、状态约束与版本检查通过；这些结果不代表 Linux errno 测试或容器已运行。

受限 Linux hwmon 脚本在原有 47 项观察后加入 12 项 amdgpu 观察，计划共 59 项：三通道、损坏值隔离、权限拒绝/恢复、禁用/故障、未支持通道 FIFO、可选通道缺失、零值、越界、负值与恢复。每次仍验证 Schema、默认隐私、健康内存字段与静态缓存。当前只是已实现的验证步骤，未运行前不视为通过。

Schema 的唯一变化是温度字段说明；[评审记录](evidence/amdgpu-schema-review-2026-10-31.json)确认全部校验约束不变，主版本维持 1。无公共 API 签名、依赖、features、MIT 或 C ABI 变化。原生 CI、八包和契约结果完成后追加；不发布软件。

## 使用和限制

已有 `hardware.refresh_dynamic()`、`dscope sensors` 和 JSON/C ABI 可消费这些温度，无需新选项。传感器顺序可能随重新枚举变化，匿名条目不能视为稳定设备身份，也不能据此确定某个 GPU 的物理位置。hwmon `sensors` 能力继续为 Partial。

只读查询可能使驱动恢复设备电源状态；本轮没有实体设备的功耗、准确度、GPU 重置或挂起验证。Windows/macOS 温度能力没有扩大，Linux 其他未知驱动和未列入的通道仍不作摄氏度推断。
