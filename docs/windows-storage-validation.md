# Windows 整盘容量验证

2026-10-13 源码 `ecf4a4c3f7cbc5a2f07248ec4b72470c0496fd92` 实现 [ADR 0014](adr/0014-windows-storage-capacity.md)：SetupAPI 有界 present disk 接口枚举，Win32 零读写权限元数据句柄读取 DiskSize；集合 Source Setupapi、容量 Source Win32、能力 Partial。不改变 StorageInfo 或公开签名、Schema 1、C ABI 1，MIT 不变；现有 windows-sys 0.61.2 增加仅 Windows 启用的 SDK features，Cargo.lock 未变。

[CI 38324105182](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38324105182) **全部八个任务成功**。[汇总](evidence/windows-storage-ci-38324105182.json)绑定源提交、实际测试数、原始日志和十份归档报告哈希；后续文档归档提交不是新一次源码 CI。

| 本轮门禁 | 实际结果 |
|---|---|
| Windows x64 / Linux x64 / macOS arm64 | 源码及独立消费者各 119 / 109 / 108 项 Rust 测试（含 1 doctest），fmt/Clippy/doc 拒绝警告与 no-default-features 通过 |
| 三平台八包与安装 | 原生 Cargo 验证、MIT/C 头文件、独立消费者及 CLI 安装通过；第三方锁文件未变 |
| 原生 CLI/C/Python | Windows 各 2 个整盘对象、名称脱敏；Linux 各 9 个对象；macOS storage Unsupported；已有 CPU/内存/OS/网络及 Python 100 次 collect/free 回归通过 |
| Python / Schema | 各平台 Ruff/mypy --no-incremental（20 文件）、40 项 unittest、generated/golden、Schema 和项目检查通过 |
| 受限 Linux 容器 | 21 项非 root 合成 sysfs 存储/缓存观察及既有场景通过；完整 /proc 替换仍为 runtime_mount_error/not_run |
| 十一个已有 fuzz 目标 | 每个至少 60 秒、正常 DONE；storage_capacity 61 秒、29,681,182 次；两项 harness 回归通过，不是 Windows 原生 unsafe fuzz |
| 内存与供应链 | Miri 8 项 memory_contracts、Linux FFI ASan 10 项及 cargo-deny 通过；不验证 Windows SDK unsafe 调用 |

Windows CI 的 CLI/C 各实读 161061273600 和 118111600640 bytes，均带 Win32 来源、采集时间，无伪造零或空成功；名称全部脱敏。它们是虚拟 runner 的 OS 设备对象，不是实物磁盘数量或物理总容量，不相加计算。详见 [Windows 原生报告](evidence/windows-storage-native-windows-38324105182.json)。[Linux 报告](evidence/windows-storage-native-linux-38324105182.json)仍保留一项正容量及八项真实零；[macOS 报告](evidence/windows-storage-native-macos-38324105182.json)保留 Unsupported/NotSupported，不能称为无设备。

本机 Windows x64、i7-9750H、12 逻辑 CPU，在 token 未提升的进程中，CLI/C 各实读一个对象、1000204886016 bytes，默认 name Restricted/PrivacyRedacted；Python 默认采集器 100 次 collect/free、空释放和陈旧副本拒绝通过。CLI 单独请求敏感字段但未声明授权被拒绝；双重授权路径实际读到设备编号名称，并输出警告，不保存该名称到默认报告。受限执行环境中的同一探针打开句柄返回 access denied，沙盒外成功；不能将沙盒拒绝推断为系统要求管理员。

另一个非提升权限 Python FFI 进程用非 NULL options 每次新建 Hardware，先预热 10 次、再真实重新查询 100 次，容量/脱敏检查通过。干净提交复测 GetProcessHandleCount 269 → 269（0 增长）；此前未提交版本短测为 268 → 268。这是短时全进程句柄观察，不是长期 native heap/leak 验收；默认 NULL options 的重复调用缓存静态容量，不能用它证明重复磁盘扫描。

新增八项 Windows Rust 测试：SDK 布局与 8192-byte 路径边界、截断/负容量/合法零、整盘编号响应、1/128/1024 枚举限额及不返回前缀、权限/不支持/暂不可用等状态、单字段隔离与授权名称、取消、RAII 失败与 unwind、静态缓存及重建。模拟 API 不等于原生权限拒绝、真实热插拔或故障驱动测试。

本机执行 `pwsh -NoProfile -File scripts/check.ps1 -Cross`，fmt、Clippy 拒绝警告、119 项 Rust 测试（含 1 doctest）、no-default-features、doc 拒绝警告、CLI/FFI 构建与 Linux/macOS cross-check 通过；两个 cross target 的 all-target/all-feature Clippy、fuzz fmt/Clippy 与两项 harness 回归通过。Python Ruff、mypy --no-incremental（20 文件）、40 项 unittest、Schema/generated/golden 与项目链接检查通过。`scripts/build_c_example.ps1`、`scripts/native_smoke.py` 和真实 C/Python 路径通过。干净提交执行 `python scripts/check_packages.py --offline`：八包 MIT/头文件、原生 Cargo 验证、119 项独立消费者测试及 CLI 安装通过，锁文件未变、未上传 registry。

[本机原生报告](evidence/windows-storage-local_native-windows-38324105182.json)、[独立包报告](evidence/windows-storage-package-local-windows-38324105182.json)及[非提升权限新采集器句柄短测](evidence/windows-storage-local_ffi-windows-38324105182.json)均绑定干净源提交。短测复现条件：按 C 头文件创建非 NULL dsc_options（size=20、version=1、flags=0、timeout_ms=2000、max_entries=128），每次 collect 后 free；先做 10 次预热，再在 100 次新 Hardware 调用前后用 GetProcessHandleCount 观察同一进程，同时检查 TokenElevation=0、容量为正且名称脱敏。不能替换成 NULL options 的缓存路径。

优化 profile 的整库基准首次 collect 444645 µs，100 次刷新 p50/p95/max 2222/2910/3470 µs；存储静态缓存，不代表每次扫描或驱动 SLA。详见[性能记录](benchmarks.md)。

默认名称不查询设备编号；临时 OS 路径缓冲仍含未解析标识。详情固定 8192 bytes、几何固定 1024 bytes，不按系统请求大小扩容。每次同步 API 前后检查取消，但不能硬终止驱动；core 只限制调用方等待及 worker 数。没有读写内容、SMART、serial、卷/文件系统空间。虚拟对象不能相加为物理总量；静态失败、容量和成员缓存，访问恢复/设备变更需新建 Hardware。

Windows x86/ARM64 原生、原生长期泄漏/峰值分配、坏驱动阻塞和真实热插拔未执行。macOS 存储仍 Unsupported；后续独立验证 IOMedia 公开属性与 CF/IOKit 所有权，不扩大 GPU、移动/Web/MCU。

报告归档采用 LF；汇总 sha256 对应实际 Git 报告字节，original_report_sha256 对应原始生成/下载字节，日志哈希对应捕获日志。Windows 无实际 libFuzzer，十一目标在 Linux CI 执行；不将短 smoke、RSS 或模拟 API 计数当作覆盖率、原生内存占用或长期验收。
