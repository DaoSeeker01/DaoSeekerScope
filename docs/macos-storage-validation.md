# macOS 整盘容量验证

2026-10-13 实现 [ADR 0015](adr/0015-macos-storage-capacity.md)。公开 IOMedia Whole 分类、Size 字节容量、Source Iokit、能力 Partial；默认不查询 BSD Name、UUID、序列号或属性表，双重授权才读名称。静态缓存、动态不扫描，重建 Hardware 才观察设备变更及访问恢复。

源码 `99e9479829283fcfee91ef102e6b8fd348b37e96` 的 [CI 38326748121](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38326748121) **全部八个任务成功**。[汇总](evidence/macos-storage-ci-38326748121.json)绑定源提交、九份报告和运行日志哈希、实际测试数；后续文档归档提交不是新一次源码 CI。macOS 真实 Rust CLI/C 各读 7 个 Iokit Whole 对象，所有容量为正、来源/采集时间完整、名称全部 Restricted/PrivacyRedacted；CF 类型转换测试通过，Python 默认 collect/free 100 次通过。CI 是 macOS arm64 虚拟机，不是实物磁盘或 sandbox 验证，整盘对象可包含虚拟层，不能求和作为物理总容量。

| 本轮门禁 | 实际结果 |
|---|---|
| Windows x64 / Linux x64 / macOS arm64 | 源码与独立消费者各 127 / 117 / 117 项 Rust 测试（含 1 doctest），fmt/Clippy/doc 拒绝警告、no-default-features 通过 |
| 三平台八包 / CLI 安装 | MIT/C 头文件、原生 Cargo 验证及独立安装通过；第三方锁定版本未变，workspace 仅增加 macOS 依赖边 |
| 原生 CLI/C/Python | 存储各 2 / 9 / 7 个对象、默认名称全部脱敏；既有 CPU/内存/OS/网络与 Python 100 次 collect/free 回归通过 |
| 普通账户 SDK / CF 测试 | 110 次 C 扫描、23 个媒体/7 个 Whole，CF 类型及精确整数转换原生测试通过 |
| Python / Schema | 各平台 Ruff/mypy --no-incremental（20 文件）、41 项 unittest、generated/golden、Schema 与项目检查通过 |
| 受限 Linux 存储 | 21 项非 root 合成 sysfs/缓存观察及已有容器回归通过，完整 /proc 覆盖仍 runtime_mount_error/not_run |
| 十一个已有 fuzz 目标 | 每个至少 60 秒、正常 DONE；storage_capacity 61 秒/28,095,696 次，两项 harness 回归通过；不测试原生 CF/IOKit unsafe |
| 内存与供应链 | Miri 8 项 memory_contracts、Linux FFI ASan 10 项与 cargo-deny 通过，不将 Linux 内存门禁当作 macOS 框架验收 |

[macOS 原生报告](evidence/macos-storage-native-macos-38326748121.json)保留所有真实容量/来源/时间及脱敏状态；[Linux](evidence/macos-storage-native-linux-38326748121.json)保留真实零容量，[Windows](evidence/macos-storage-native-windows-38326748121.json)保持 Source Setupapi/Win32。[普通账户探针](evidence/macos-storage-sdk-probe-macos-38326748121.json)没有设备标识，报告通过 CI artifact 绑定源提交；[本机包报告](evidence/macos-storage-package-local-windows-38326748121.json)绑定干净提交，不声称 Windows 能原生读取 IOMedia。

[独立 C SDK 探针](research/iomedia_probe.c)由原生 SDK 编译（cc -Wall -Wextra -Werror -std=c11，链接 IOKit/CoreFoundation），在 geteuid 非 0 下完成 110 次完整枚举、查询和释放；末次扫描 23 个媒体、7 个 Whole 对象及 7 个正容量，未查询名称。它验证接口、普通账户读取及自身释放路径，不测量泄漏或验证 Rust 句柄释放。

本机执行 `scripts/check.ps1 -Cross`：fmt、Clippy、127 项 Rust 测试（含 1 doctest）、no-default-features、doc 拒绝警告、CLI/FFI 构建及两目标 cross-check 通过；Linux/macOS all-target/all-feature Clippy、fuzz fmt/Clippy 和两项 harness 回归通过。Python Ruff/mypy --no-incremental（20 文件）、41 项 unittest、Schema/generated/golden 和项目链接检查通过。Windows 无原生 macOS 或实际 libFuzzer；八项纯 mock 测试可在 Windows/Linux 运行，不冒充设备证据。干净提交 `python scripts/check_packages.py --offline` 八个实际归档、MIT/头文件、原生 Cargo 验证、127 项独立消费者测试及 CLI 安装通过，未发布 registry；macOS 隔离消费者为 117 项。

Rust 限制最多 4096 个媒体对象扫描、默认最多 128/可配 1024 个整盘对象、名称转换 256 bytes；超限拒绝前缀，迭代器失效返回暂不可用。Whole 无法分类时拒绝集合，单项 Size 失败按字段隔离。CF API 的 NULL 没有错误码，返回 Unavailable/Unknown；不能猜测权限或设备不存在。IOIterator/对象 RAII、matching 引用消费和 CFRetained 释放见决策。

macOS crate 新增两项显式 target 依赖，复用锁定 0.3.2 绑定，包版本和许可证未变；Cargo.lock 仅增加依赖边。MIT、公共 API/模型形状、Schema 1、C ABI 1 不变。新读取会让此前 Unsupported 的 macOS storage 返回实际逐字段状态，消费方仍须检查 Availability。

优化 profile 首次完整 collect 474 µs，100 次动态刷新 p50/p95/max 28/62/123 µs，合成 100 传感器/1024 网络条目另为 114 µs/373541 bytes；不隔离属性读取或峰值分配，详见[性能记录](benchmarks.md)。

公开 CF/IOKit 在返回属性前可分配内部内存，无法由调用方硬限制；同步调用不能强制终止，沿用 core 调用方超时/有界 worker。Mac 实物磁盘、sandbox 权限、原生长期泄漏/峰值分配、热插拔、失控驱动未验证。C 探针 110 次完整扫描检验普通用户读取与释放路径，不能当作 Rust native heap/leak 证明。Windows/Linux 存储回归需要同轮证据，GPU/移动/Web/MCU 不扩大范围。

本轮没有单独在真实 registry 验证授权后的 BSD Name；该路径由 mock 和 CF 类型检查覆盖，不把默认容量读值当作名称读取证明。报告归档采用 LF；汇总 sha256 对应实际 Git 报告字节，original_report_sha256 对应原始下载/生成字节，日志哈希对应捕获日志。fuzz 为 Linux CI smoke，不是长期 campaign，RSS 不代表采集库内存。

下一步完善 CLI 存储容量的文本展示；真实 Mac/sandbox/热插拔、授权名称及 native heap/leak 需要独立验收，不把覆盖空缺写成支持保证。
