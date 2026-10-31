# Linux amdgpu 温度采集

Linux hwmon 后端现可读取 `amdgpu` 实际提供的 1–3 号温度通道，按毫摄氏度转换为摄氏度。设备可能只提供部分通道；缺少的通道不会生成默认值。实现为 `33433c1`，[三平台 CI 41190519410](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/41190519410)的八项任务均已通过。[验收索引](evidence/amdgpu-ci-41190519410.json)绑定源码、原始报告和哈希；规则与来源见 [ADR 0047](adr/0047-linux-amdgpu-temperature.md)。

## 采集行为

坏值、权限拒绝、未启用或故障通道分别处理，健康通道继续保留。amdgpu 读取阶段的 EPERM 也可能来自驱动重置或挂起，因此报告 Unavailable/Unknown，不直接断言权限不足；打开文件时的权限拒绝仍正常报告。驱动提供的合法零值仍为 0 °C。

默认不查询标签或设备标识，条目上限和超时等待边界沿用现有规则。通过 `hardware.refresh_dynamic()`、`dscope sensors` 或 JSON/C ABI 读取，无需新选项。匿名传感器顺序可能随枚举变化，不能据此确定 GPU 身份或物理位置；sensors 能力仍为 Partial。

## 实际验证

| 环境 | Rust（含文档测试） | Python | 其他结果 |
|---|---:|---|---|
| Windows 本机 | 274 通过 | 292 通过、5 跳过 | 完整 Rust 门禁、Linux x64/macOS ARM64 交叉 check、八包与 C/Rust 契约通过 |
| Windows 原生 CI | 274 通过 | 292 通过、5 跳过 | 八包、CLI/SDK 候选、原生 C/Python、契约与资源回归通过 |
| Linux 原生 CI | 267 通过 | 297 通过、0 跳过 | 包含新增 errno 分类测试；八包、候选与原生回归通过 |
| macOS 原生 CI | 271 通过 | 296 通过、1 跳过 | 八包、公开 SDK、契约与原生回归通过；没有 macOS 预编译分发验收 |

新增两项跨平台 Rust 合成测试覆盖通道/单位、刷新与静态缓存、字段隔离、隐私、缺失通道、enable/fault、零值和上限。Linux 另验证 EPERM、EACCES、EAGAIN、EBUSY、ENODATA、EOPNOTSUPP、ETIMEDOUT 与未知错误分类。

受限 Linux 容器共 59 项观察全部通过，其中新增 12 项 amdgpu 观察涵盖三通道、坏值隔离、权限拒绝/恢复、禁用/故障、未支持通道 FIFO、可选通道缺失、零值、越界、负值与恢复。每项均检查 Schema、默认隐私、健康内存字段和静态缓存；[原始报告](evidence/amdgpu-hwmon-linux-container-41190519410.json)保留每次结果。输入是合成温度，权限与 FIFO 由非 root 文件系统实际执行，不能写成真实 GPU 测温。

fmt、严格 Clippy、严格文档、无默认功能、Schema、项目链接、Ruff 与 mypy（73 文件）检查通过。CI 另通过 8 项 Miri、11 项 FFI ASan、依赖安全检查和 12 个各至少 60 秒的短 fuzz 目标。

本机两分钟 C ABI 回归完成 1057 次采集/释放，实际 120.100 秒；热身后两个采样点相差 4096 字节，符合预先固定的 16 MiB 预算。三平台 CI 的两分钟采样及句柄/描述符有限轮次回归也通过。这些是有限采样，不是长期无泄漏结论，原始数据见验收索引。

## 兼容性与未验证范围

Rust 公共字段、枚举和签名、features、依赖、MIT 和 C ABI 1 不变。Schema 仅更新温度字段说明；[单独评审](evidence/amdgpu-schema-review-2026-10-31.json)确认校验约束逐项相同，主版本仍为 1。冻结哈希已对应更新，不需要数据迁移。

尚无真实 Linux AMD GPU 的准确度、功耗、GPU 重置或挂起验证。只读 sysfs 查询可能使驱动恢复设备电源状态；库不写电源、时钟、风扇或性能策略，也不承诺读取不唤醒设备。Windows/macOS 温度能力没有扩大，Linux 未列出的驱动和通道仍不作摄氏度推断。本轮没有正式发布软件；macOS 分发材料及首版最终评审仍待完成。
