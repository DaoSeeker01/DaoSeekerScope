# Windows 整盘容量验证

2026-10-13 实现 [ADR 0014](adr/0014-windows-storage-capacity.md)：SetupAPI 有界 present disk 接口枚举，Win32 零读写权限元数据句柄读取 DiskSize；集合 Source Setupapi、容量 Source Win32、能力 Partial。不改变 StorageInfo 或公开签名、Schema 1、C ABI 1，MIT 不变；现有 windows-sys 0.61.2 增加仅 Windows 启用的 SDK features，Cargo.lock 未变。

本机 Windows x64、i7-9750H、12 逻辑 CPU，在 token 未提升的进程中，CLI/C 各实读一个对象、1000204886016 bytes，默认 name Restricted/PrivacyRedacted；Python 默认采集器 100 次 collect/free、空释放和陈旧副本拒绝通过。CLI 单独请求敏感字段但未声明授权被拒绝；双重授权路径实际读到设备编号名称，并输出警告，不保存该名称到默认报告。受限执行环境中的同一探针打开句柄返回 access denied，沙盒外成功；不能将沙盒拒绝推断为系统要求管理员。

另一个非提升权限 Python FFI 进程用非 NULL options 每次新建 Hardware，先预热 10 次、再真实重新查询 100 次，容量/脱敏检查通过，GetProcessHandleCount 268 → 268（0 增长）。这是短时全进程句柄观察，不是长期 native heap/leak 验收；默认 NULL options 的重复调用缓存静态容量，不能用它证明重复磁盘扫描。

新增八项 Windows Rust 测试：SDK 布局与 8192-byte 路径边界、截断/负容量/合法零、整盘编号响应、1/128/1024 枚举限额及不返回前缀、权限/不支持/暂不可用等状态、单字段隔离与授权名称、取消、RAII 失败与 unwind、静态缓存及重建。模拟 API 不等于原生权限拒绝、真实热插拔或故障驱动测试。

本机执行 `pwsh -NoProfile -File scripts/check.ps1 -Cross`，fmt、Clippy 拒绝警告、119 项 Rust 测试（含 1 doctest）、no-default-features、doc 拒绝警告、CLI/FFI 构建与 Linux/macOS cross-check 通过；Python Ruff、mypy --no-incremental（20 文件）、40 项 unittest、Schema/generated/golden 与项目链接检查通过。`scripts/build_c_example.ps1`、`scripts/native_smoke.py` 和真实 C/Python 路径通过。干净提交的八包隔离验证与三平台原生 CI 尚待本轮执行，后续证据需绑定源提交，不把本机结果写成三平台验收。

默认名称不查询设备编号；临时 OS 路径缓冲仍含未解析标识。详情固定 8192 bytes、几何固定 1024 bytes，不按系统请求大小扩容。每次同步 API 前后检查取消，但不能硬终止驱动；core 只限制调用方等待及 worker 数。没有读写内容、SMART、serial、卷/文件系统空间。虚拟对象不能相加为物理总量；静态失败、容量和成员缓存，访问恢复/设备变更需新建 Hardware。

Windows x86/ARM64 原生、原生长期泄漏/峰值分配、坏驱动阻塞和真实热插拔未执行。macOS 存储仍 Unsupported；后续独立验证 IOMedia 公开属性与 CF/IOKit 所有权，不扩大 GPU、移动/Web/MCU。
