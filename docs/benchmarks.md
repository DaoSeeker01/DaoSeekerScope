# 性能基线

## C ABI 进程峰值内存

复现：在干净工作区运行 `python scripts/peak_memory.py`。脚本构建 release CLI/FFI 与优化 C11 探针，保存源码、产物哈希、硬件摘要、原始计数和各批耗时。三平台 CI 同样执行；结果写入 `target/peak-memory-evidence.json`，随 native-evidence 保留。

测量分为三个进程：64 MiB 校准；默认采集器累计 1/100/300 次 collect/free；显式 options 累计 1/10/30 次 collect/free。首次调用包含构造，后续默认调用复用缓存，显式调用仍重建。两者均默认脱敏、max_entries=128、超时 2000 ms。每批耗时不累计前批；峰值则是整个进程运行以来的最大值，不能相减解释为每次分配。

内存包含 C 进程、依赖库、缓存和线程，并非 allocator 用量。CPU/内存摘要是系统报告值，CI 不等于实体设备。单位、校准和失败规则见 [ADR 0038](adr/0038-process-peak-memory.md)。本轮实测完成后在此归档，不以已加入 CI 作为通过证据。

### Windows 本机（2026-10-28）

干净源码 `caa3443055baaa6cd3ed9f87882a57902e9e9875`，Windows 11 x64，系统报告 i7-9750H、12 逻辑 CPU、17009004544 字节总可用内存；Rust 1.96.0、MSVC 19.51.36260、release、默认 serde 和 Windows backend。校准峰值从 8605696 增至 75718656 字节，增加 67112960 字节（约 64 MiB）。

| 调用方式 | 首次 collect/free | 最后一批调用 / 耗时 | 最后一批后进程峰值 |
|---|---|---|---|
| 默认缓存 | 36.64 ms | 第 101–300 次 / 646.51 ms | 11960320 bytes（11.41 MiB） |
| 每次重建 | 37.04 ms | 第 11–30 次 / 88.47 ms | 12017664 bytes（11.46 MiB） |

这是单次、有限调用样本，调用数量也不同，不能据此比较两种方式的长期增长或作性能排名。[原始计数与哈希](evidence/process-peak-memory-windows-local-caa3443.json)、[本机验收索引](evidence/process-peak-memory-local-caa3443.json)包含三个独立进程的全部阶段；八包和原生 CLI/C/Python 检查另存报告。Linux/macOS 原生峰值测量待本轮 CI，交叉检查不代替原生执行。

## v0.1 审计修复回归（2026-10-27）

源码 `d5d1e3b94b52b543e1b43aeb203fe8e6d9f7d7c7`，[CI 40423886083](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40423886083)执行 `cargo bench --locked -p daoseeker-scope --bench collect`；Rust 1.96、bench 优化、默认 serde，原生 max_entries=128/100 次刷新，合成 100 传感器/1024 网络条目、max_entries=1024。环境和原始日志在记录中。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs | 合成 collect µs / JSON bytes | 环境与日志 |
|---|---|---|---|---|
| Linux x64 | 860 | 108 / 126 / 156 | 283 / 373541 | [记录](evidence/v01-audit-benchmark-linux-40423886083.json) |
| macOS ARM64 | 36635 | 81 / 181 / 219 | 143 / 373541 | [记录](evidence/v01-audit-benchmark-darwin-40423886083.json) |

这是托管 runner 的整库回归，不是 SDK 打包/加载性能、配对改进、峰值内存或最低运行环境证明。


## Linux FFI SDK 轮次的整库回归（2026-10-26）

源码 `af312dad99abcbfc8fe2becd8a2fc209fca85f90`，[CI 40304816716](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40304816716)运行 `cargo bench --locked -p daoseeker-scope --bench collect`；Rust 1.96、bench 优化、默认 serde，原生 max_entries=128/100 次刷新，合成 100 个传感器和 1024 个网络条目/max_entries=1024。实际环境和原始日志见记录。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs | 合成 collect µs / JSON bytes | 环境与日志 |
|---|---|---|---|---|
| Linux x64 | 689 | 97 / 139 / 709 | 514 / 373541 | [记录](evidence/linux-ffi-sdk-benchmark-linux-40304816716.json) |
| macOS ARM64 | 46414 | 27 / 53 / 445 | 108 / 373541 | [记录](evidence/linux-ffi-sdk-benchmark-darwin-40304816716.json) |

这是托管 runner 的整库回归，不是 SDK 打包、加载或 C/Python 调用性能；不声明配对提升、最低系统版本、实体设备、峰值内存或 SLA。


## Windows FFI SDK 轮次的整库回归（2026-10-26）

源码 `ba11807b4cc04046f9e3a966ccb58c51dcd23a92`，[CI 40249181949](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40249181949)运行 `cargo bench --locked -p daoseeker-scope --bench collect`；Rust 1.96、bench 优化、默认 serde，原生 max_entries=128/100 次刷新，合成 100 个传感器和 1024 个网络条目/max_entries=1024。实际 OS/CPU/内存和原始日志在记录中。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs | 合成 collect µs / JSON bytes | 环境与日志 |
|---|---|---|---|---|
| Linux x64 | 1195 | 263 / 309 / 326 | 229 / 373541 | [记录](evidence/windows-ffi-sdk-benchmark-linux-40249181949.json) |
| macOS ARM64 | 36423 | 37 / 84 / 193 | 355 / 373541 | [记录](evidence/windows-ffi-sdk-benchmark-darwin-40249181949.json) |

这是托管 runner 的整库回归，不是 Windows SDK 构建、加载或 collect/free 延迟基准；不声明配对改进、最低运行环境、实体设备、峰值内存或 SLA。


## Linux CLI 制品轮次的整库回归（2026-10-26）

源码 `98172d0afe77f53a8e108d5f02f2b7275ce0f25c`，[CI 40245533279](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40245533279)运行 `cargo bench --locked -p daoseeker-scope --bench collect`，Rust 1.96、bench 优化、默认 serde。原生 max_entries=128、100 次刷新；合成 100 个传感器和 1024 个网络条目、max_entries=1024。OS、CPU、内存及原始日志保存在各记录中。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs | 合成 collect µs / JSON bytes | 环境与日志 |
|---|---|---|---|---|
| Linux x64 | 1107 | 262 / 322 / 355 | 188 / 373541 | [记录](evidence/linux-cli-bundle-benchmark-linux-40245533279.json) |
| macOS ARM64 | 71466 | 48 / 91 / 207 | 142 / 373541 | [记录](evidence/linux-cli-bundle-benchmark-darwin-40245533279.json) |

托管 runner 的整库采样，不是 ZIP 构建/安装性能或最低发行版兼容性测量；不声明配对性能变化、实体设备、峰值内存或 SLA。


## CLI 候选包轮次的整库回归基准（2026-10-25）

源码 `2d0a8a1b5ac3f1fb9755f2ff21cfc5674e8b692d`，[CI 40183166615](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40183166615)运行 `cargo bench --locked -p daoseeker-scope --bench collect`。Rust 1.96、bench 优化、默认 serde，原生 max_entries=128；合成 100 个传感器与 1024 个网络条目、max_entries=1024。实际 OS/CPU/内存和原始日志在各记录内。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs（100 次） | 合成 collect µs / JSON bytes | 环境与日志 |
|---|---|---|---|---|
| Linux x64 | 1255 | 345 / 411 / 485 | 188 / 373541 | [完整记录](evidence/windows-cli-bundle-benchmark-linux-40183166615.json) |
| macOS ARM64 | 13669 | 40 / 56 / 71 | 529 / 373541 | [完整记录](evidence/windows-cli-bundle-benchmark-darwin-40183166615.json) |

这是托管 runner 整库回归采样，不是 CLI ZIP 构建/安装性能；无旧版配对、峰值分配或物理设备/SLA 结论。


## Windows 硬件摘要切片的整库回归基准（2026-10-25）

源码 `01d222f242d3f4254ed87ecbfe937e929389cb33`，命令 `cargo bench --locked -p daoseeker-scope --bench collect`，Rust 1.96、bench 优化 profile、默认 serde 与对应平台增强。原生 max_entries=128；合成为 100 个传感器和 1024 个网络条目，max_entries=1024。仅托管 Linux/macOS 整库回归，不是 Windows 注册表六值查询、CLI 启动或物理设备性能。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs（100 次） | 合成 collect µs / JSON bytes | 环境和原始日志 |
|---|---|---|---|---|
| Linux x64 | 1175 | 318 / 374 / 399 | 180 / 373541 | [完整记录](evidence/windows-hardware-summary-benchmark-linux-40145306966.json) |
| macOS ARM64 | 30635 | 36 / 59 / 79 | 280 / 373541 | [完整记录](evidence/windows-hardware-summary-benchmark-darwin-40145306966.json) |

首次 collect 不含构造，刷新使用静态缓存；环境、系统报告的 CPU/内存和原始日志在记录中。没有旧版配对、峰值内存或长期泄漏测量，不声明性能改善/退化或 SLA；macOS VM 计数仍可能由 OS 缓存。

## Windows CPU 多组切片的整库回归基准（2026-10-24）

源码 `bedd8a7f96403020ee5492ab9cbe7221fc5ecff8`，2026-10-25 归档。命令 `cargo bench --locked -p daoseeker-scope --bench collect`，Rust 1.96、bench 优化 profile、默认 serde 与对应平台增强。原生 max_entries=128；合成为 100 个传感器和 1024 个网络条目，max_entries=1024。仅托管 Linux/macOS 整库回归，没有 Windows 多组/helper 性能测量。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs（100 次） | 合成 collect µs / JSON bytes | 环境和原始日志 |
|---|---|---|---|---|
| Linux x64 | 870 | 111 / 145 / 173 | 328 / 373541 | [完整记录](evidence/windows-cpu-groups-benchmark-linux-40046393393.json) |
| macOS ARM64 | 25463 | 41 / 137 / 197 | 285 / 373541 | [完整记录](evidence/windows-cpu-groups-benchmark-darwin-40046393393.json) |

Linux 为 Ubuntu 24.04 / 6.17.0-1022-azure，OS 报告 AMD EPYC 7763、4 逻辑 CPU、16766414848 字节可用总内存；macOS 26.6.2 / Darwin 25.6.0 报告 Apple M1 (Virtual)、3 逻辑 CPU、7516192768 字节。首次 collect 不含构造，刷新使用静态缓存。没有旧版配对，不声明性能改善/退化、峰值内存、物理设备性能或 SLA；macOS VM 统计仍可能由 OS 缓存。

## 2026-10-15 Linux DRM 视图切片原生 CI

源码 `b039c18da4521cde087e8e3d76f1c69b40c0c7dd`，Ubuntu 24.04 / Linux 6.17.0-1022-azure x64 runner；OS 报告 AMD EPYC 7763、2 逻辑 CPU、8323969024 字节可用总内存。Rust 1.96、bench 优化 profile，默认 serde/sysinfo system/apple-app-store 和 Linux procfs/sysfs/DRM 增强；max_entries=128，敏感字段默认脱敏。真实视图包含 1 个 DRM 设备，名称和独占显存均 Unsupported，不是 AMD/NVIDIA 名称读取基准。复现 `cargo bench --locked -p daoseeker-scope --bench collect`。

| 单进程样本 | 实际结果 |
|---|---|
| 首次完整 collect（不含 Hardware 构造） | 731 µs |
| 100 次动态刷新 p50 / p95 / max | 113 / 146 / 160 µs |
| 等待采样间隔后的 CPU 状态 | Available |
| 合成 100 传感器、1024 网络条目 collect / JSON | 267 µs / 373541 bytes |

共享 CI 上的一次完整采集测量，不是独立 DRM/驱动延迟、峰值分配或性能提升证明。动态刷新不重扫 GPU；合成条目规模不代表实体硬件数量。来源与验证边界见[Linux GPU 验收](linux-gpu-validation.md)。

## 2026-10-15 Windows GPU 切片本机

源码 `19f20a53a1293fd4de0b8ed585c2615bf1499fe4`，干净工作区，Windows 11 build 26300 x64、i7-9750H、12 逻辑 CPU/6 物理核、安装 16 GiB；Rust 1.96/MSVC、bench 优化 profile、默认 serde/sysinfo system/apple-app-store、Windows SDK 增强，max_entries=128、敏感字段脱敏；DXGI 返回 2 个非软件适配器。复现 `cargo bench --locked -p daoseeker-scope --bench collect`。

| 单进程样本 | 实际结果 |
|---|---|
| 首次完整 collect（不含 Hardware 构造） | 434116 µs |
| 100 次动态刷新 p50 / p95 / max | 2230 / 2705 / 3159 µs |
| 等待采样间隔后的 CPU 状态 | Available |
| 合成 100 传感器、1024 网络条目 collect / JSON | 393 µs / 373541 bytes |

完整 collector 的单次基线，不是独立 DXGI 延迟、GPU 吞吐、峰值分配或性能提升证明；动态刷新不重新枚举 GPU。原生上下文与投影见[GPU 验收](windows-gpu-validation.md)，其 benchmark 与合成模型不能混为真实设备规模。

## 2026-10-13 macOS 存储切片原生 CI

源码 `99e9479829283fcfee91ef102e6b8fd348b37e96`；macOS 26.6.2 / Darwin 25.6.0 arm64 虚拟 runner，OS 报告 Apple M2 Pro (Virtual)、5 逻辑 CPU、14 GiB 可用总内存。Rust 1.96、bench 优化 profile、门面默认 serde、sysinfo system/apple-app-store 与公开 IOKit 增强，默认 max_entries=128、名称脱敏。实际扫描 23 个媒体并返回 7 个 Whole 对象，容量静态缓存；不推断底层物理磁盘数量。

复现 `cargo bench --locked -p daoseeker-scope --bench collect`，单进程首次 collect 不含 Hardware 构造，100 次动态刷新、300 ms 后检查 CPU；合成部分另外注入 100 传感器/1024 网络条目并使用 max_entries=1024。

| 样本 | 实际结果 |
|---|---|
| 首次完整 collect | 474 µs |
| 100 次刷新 p50 / p95 / max | 28 / 62 / 123 µs |
| CPU 二次样本 | Available |
| 合成 collect / JSON | 114 µs / 373541 bytes |

完整 collector 的共享 CI 样本，不隔离 IOKit/属性查询时间，不是磁盘吞吐、峰值分配或延迟 SLA；动态刷新不重新扫描存储。独立 C SDK 的 110 次扫描没有记录单次时间或分配，不能冒充 Rust/native heap/leak 基准。见[存储验证](macos-storage-validation.md)。

## 2026-10-13 Windows 存储切片本机

源码 `ecf4a4c3f7cbc5a2f07248ec4b72470c0496fd92`，干净工作区；Windows 11 build 26300 x64、OS 报告 i7-9750H、12 逻辑 CPU/6 物理核、安装 16 GiB，非提升权限。Rust 1.96/MSVC、bench 优化 profile、门面默认 serde、sysinfo system/apple-app-store、Windows SDK 增强；默认 max_entries=128、名称脱敏，一项整盘对象容量 1000204886016 bytes。复现 `cargo bench --locked -p daoseeker-scope --bench collect`。

| 单进程样本 | 实际结果 |
|---|---|
| 首次完整 collect（不含 Hardware 构造） | 444645 µs |
| 100 次动态刷新 p50 / p95 / max | 2222 / 2910 / 3470 µs |
| 等待 300 ms 后 CPU 状态 | Available |
| 合成 100 传感器、1024 网络条目 collect | 344 µs |
| 合成快照 JSON | 373541 bytes |

存储仅首次静态读取并缓存，动态刷新不重复扫描。该样本测量整个 collector，不隔离 SetupAPI/驱动耗时，不是磁盘吞吐、峰值分配或延迟 SLA；首次采集明显慢于动态刷新。合成部分单独注入自定义 backend/max_entries=1024，不能当作 100 个真实传感器。另有 10 次预热后的 100 次新 Hardware 原生 FFI 查询，进程句柄 269 → 269，仅说明此短测无句柄净增长，不是内存/长期泄漏证明。证据见 [Windows 存储验证](windows-storage-validation.md)。

## Linux 存储容量切片（2026-10-12）

源码 `2b19e8d1cd50c9277753941a16807e1143a97c35`；Ubuntu 24.04 x64 CI 虚拟机，kernel 6.17.0-1022-azure，OS 报告 AMD EPYC 7763 64-Core Processor、2 逻辑 CPU、可用总内存 8328298496 bytes（不推断物理核数或安装内存）。Rust 1.96、bench 优化 profile、门面默认 serde、sysinfo system/apple-app-store，普通用户默认隐私/max_entries=128，9 个整块对象含虚拟设备；容量静态缓存。

复现 `cargo bench --locked -p daoseeker-scope --bench collect`；首次不含 Hardware 构造、100 次动态刷新、300 ms 后检查 CPU。合成测试另外注入 100 传感器/1024 网络条目并用 max_entries=1024。

| 指标 | 单进程共享 runner 样本 |
|---|---|
| 首次 collect | 687 µs |
| 100 次动态刷新 p50 / p95 / max | 114 / 139 / 151 µs |
| CPU 样本状态 | Available |
| 合成 collect / JSON | 278 µs / 373541 bytes |

完整 collector 包含 CPU/内存/网络等路径；存储首次采集后缓存，不能将刷新延迟描述为磁盘扫描或 IO 性能。没有测峰值分配、硬件插拔或坏驱动阻塞；不能与其他平台/旧版非配对样本比较为性能提升，见[验证范围](storage-validation.md)和[原始日志哈希/参数](evidence/storage-ci-38188243470.json)。

## macOS 网络切片基准（2026-10-12 修复验收）

修复源码 `d27e681b87cc64f5ed55c11218752b3c70268f0a`，macOS 26.6.2 / Darwin 25.6.0 arm64 CI 虚拟机；OS 报告 Apple M2 Pro (Virtual)、5 逻辑核、14 GiB。Rust 1.96，bench 优化 profile，门面默认 serde、sysinfo system/apple-app-store；原生默认 max_entries=128、11 条 Sysctl 网络统计、名称脱敏，macOS 能力 Partial（数值可能取整/回绕）。

复现 `cargo bench --locked -p daoseeker-scope --bench collect`；单进程首次 collect 不含 Hardware 构造，100 次动态刷新，300 ms 后检查 CPU，合成部分另外用 max_entries=1024。

| 指标 | 原生 macOS CI 样本 |
|---|---|
| 首次 collect | 167 µs |
| 100 次动态刷新 p50 / p95 / max | 33 / 50 / 65 µs |
| CPU 样本状态 | Available |
| 合成 100 传感器、1024 网络条目 collect | 124 µs |
| 合成快照 JSON | 373541 bytes |

首轮源码 `69b9c4e` 的 macOS 原生任务成功，基准为首次 136 µs、刷新 19/24/35 µs、合成 515 µs/373541 bytes；该轮整体 CI 因新 fuzz harness 来源断言错误失败，不能作为完整验收。[修复轮汇总](evidence/macos-network-ci-38186025262.json)与[首轮报告](evidence/macos-network-failure-previous-run-38186025262.json)均保留来源与日志哈希，不用一次结果替代另一次。

这是共享 runner 上完整 collector 的单进程样本，包含 sysinfo，不是独立 sysctl 延迟。没有记录峰值分配、真实 100 个传感器或坏驱动阻塞，也未在同条件下与旧版配对比较；不能宣称跨系统性能提升或 SLA。[本轮验证](macos-network-validation.md)区分原生与合成证据。以下各轮历史基线保留原日期与平台。

日期：2026-10-08 Asia/Shanghai。硬件：主机读取i7-9750H，12逻辑CPU/6物理核，安装内存16GiB；OS Microsoft Windows10.0.26300 x86_64。Rust1.96.0 / MSVC14.51.36231，bench优化profile，门面默认serde；sysinfo0.39.6 default-features=false + system/apple-app-store。普通主机权限，采集不含敏感标识。

复现：cargo bench --locked -p daoseeker-scope --bench collect。每次进程首次collect（不含Hardware构造）计时，然后100次动态刷新，等待250ms检查CPU有效样本，再读取100个合成传感器与1024个合成网络条目（max_entries=1024）。实际OS数据与注入的合成数据明确分开。最终可执行文件另外启动5次，原始输出见benchmark-native-runs.txt。

| 指标 | 5次进程范围 |
|---|---|
| 首次collect | 369.462–376.903ms |
| 100次refresh p50（每次进程各计算一次） | 34–35µs |
| refresh p95 | 36–69µs |
| refresh max | 239–438µs |
| 合成100传感器/1024网络条目collect | 313–628µs |
| 合成完整快照UTF-8 JSON | 366,287字节（不是heap/RSS） |

之前一次沙箱测量首次collect770µs，但安装内存API被权限拒绝，不能与普通主机权限结果当成同一采集范围比较。首次采集目前约0.37秒；未做采样器逐API成本剖析，不能把它归因于某一API，更不能宣称低于1ms。默认2秒调用方等待上限，应用可设置1..60000ms；超短预算会返回Timeout。

资源上限：每Hardware一worker，进程最多16；每类别最多1024条目，默认128；DMI单文件最多4097字节读取（超过4096拒绝）；FFI最多64个1MiB buffer；JSON输入最多1MiB。core测试证明100限额下101条传感器数据会Unavailable/InvalidData，而成功空列表仍Available。增强读取/输出受控，sysinfo内部CPU列表/平台分配无法保证同等限制，trusted自定义backend也必须履约。

尚未测：Linux/macOS延迟、实际传感器查询（当前Unsupported）、多backend峰值heap/RSS、CPU热点/分配计数和长时间并发。当前fake超时测试只验证调用方等待有界，不测真实OS调用强制终止。此基线不是发布性能SLA。

2026-10-10追加：Linux电池枚举切片未重跑性能benchmark。上文数据是2026-10-08 Windows历史基线，不是Linux电池扫描延迟或新源码SLA；256个供应设备/128字节属性/调用方条目限制经测试，不替代峰值分配与真实驱动超时测量。fuzz RSS284Mb包含libFuzzer/ASan，不能作为库的内存占用。
# hwmon切片的性能证据边界（2026-10-10）

本轮未运行新采集延迟/分配benchmark；以上历史Windows数据不验证Linux hwmon的SLA。枚举限额为256类入口、每芯片1024/合计4096目录条目、默认128输出，超限拒绝前缀而不截断。容器限额/恢复测试验证拒绝行为，不等于真实100传感器性能测量。60秒属性fuzz的RSS包含libFuzzer/ASan运行时，不能作为采集库峰值内存。后续实机基准须记录驱动/通道数量、系统、profile和feature，见[hwmon验收](hwmon-validation.md)。

2026-10-11 NVMe路由增量没有新benchmark。不发ioctl，但Linux hwmon驱动读取仍可能查询SMART并阻塞；现有timeout限制调用方等待，不能硬取消驱动。零Kelvin策略与47项合成容器观察验证单位/错误/恢复，不能给出真实SSD读取延迟或分配SLA，见[NVMe验收](nvme-temperature-validation.md)。

## 全项目审查后的 Windows 基准（2026-10-11）

源码 `4ec4360a2cae1ab56f7218a3142444dd64217ee1`；复现 `cargo bench --locked -p daoseeker-scope --bench collect`。i7-9750H、12 逻辑/6 物理核、安装 16 GiB；Windows 11 (26300) x64，Rust 1.96/MSVC，bench 优化 profile，门面默认 serde，max_entries=1024 仅用于合成采集。CPU 等待已改为 300 ms。本轮只测一次进程，范围与旧五进程统计不同。

| 指标 | 本次结果 |
|---|---|
| 首次 collect（不含构造） | 402089 µs |
| 100 次动态刷新 p50 / p95 / max | 40 / 106 / 477 µs |
| CPU 样本状态 | Available |
| 合成 100 传感器、1024 网络接口 collect | 505 µs |
| 合成快照 JSON | 366287 bytes |

这是当前 Windows 基础路径的延迟样本，不测 Linux 电池/hwmon 驱动、真实 100 个传感器或峰值内存。JSON 解码现在有一次额外的有界编码大小遍历，其成本未在此采集基准中独立测量。[审查证据](evidence/project-review-38070151022.json)保存参数和原始日志哈希；已有历史数据保留。

## Windows 网络切片基准（2026-10-11）

源码 `5e43fdde5df11fbaa9b6590414de7ef7d88010e9`，干净工作区；复现 `cargo bench --locked -p daoseeker-scope --bench collect`。同一本机 i7-9750H、12 逻辑/6 物理核、安装 16 GiB，Windows 11 (26300) x64、Rust 1.96/MSVC、bench 优化 profile、门面默认 serde。默认 max_entries=128，原生网络有 43 条 Win32 统计，含回环/虚拟接口，不等于物理网卡数；合成测试单独使用 max_entries=1024。

| 指标 | 打包结束后单进程样本 |
|---|---|
| 首次 collect（不含构造） | 379910 µs |
| 100 次动态刷新 p50 / p95 / max | 2078 / 2464 / 3319 µs |
| CPU 样本状态 | Available |
| 合成 100 传感器、1024 网络接口 collect | 440 µs |
| 合成快照 JSON | 373541 bytes |

首次样本与本机打包构建并行：首次 539955 µs，刷新 p50/p95/max 3283/4127/11038 µs。为减少并发编译的干扰，在打包结束后重新执行，表格采用后一次结果，[两个日志哈希及参数](evidence/windows-network-extra-local-windows-38094160512.json)均保留。没有与旧版本在相同条件下做配对测试，不能据此宣称总体性能提升或退化；逐接口原生查询增加了工作量。没有测原生峰值内存、Windows 泄漏、坏驱动的阻塞时长，或 Linux/macOS 性能；这是单机样本，不是性能 SLA。


## macOS Metal GPU 切片基准（2026-10-16）

CI 源码 `9d30f3b1489502fbb199812d527bb79708651dda`（实现 `2b0ea76`，两者之间只有验证文档/报告）；复现 `cargo bench --locked -p daoseeker-scope --bench collect`，Rust 1.96、bench 优化 profile、门面默认 serde。托管 macOS ARM64 VM 报告 Apple M2 Pro (Virtual)、5 逻辑/物理核、OS 26.6.2/内核 25.6.0、15032385536 bytes OS 可用总内存。它是 runner 自报的虚拟环境摘要，不代表实体 Mac 配置。

| 指标 | 单进程样本 |
|---|---|
| 首次 collect（不含构造） | 7220 µs |
| 100 次动态刷新 p50 / p95 / max | 19 / 26 / 51 µs |
| CPU 第二样本状态 | Available |
| 合成 100 传感器 / 1024 网络条目 collect | 172 µs |
| 合成快照 UTF-8 JSON | 373541 bytes |

[环境、参数、原始输出及日志 SHA-256](evidence/macos-gpu-benchmark-38826444216.json)与[同轮原生报告](evidence/macos-gpu-native-darwin-38826444216.json)绑定。默认原生 max_entries=128；合成 backend 另设 1024。原生 CLI/C 读到一个 Metal 可见设备，名称可用且统一内存；基准为整个采集调用，不单独测 Metal 枚举、系统 API 预算或峰值内存。动态刷新使用静态 GPU 缓存，没有重扫；未与旧代码做配对性能测量，不据此宣称性能改善/退化或提供 SLA。单次探针与短 fuzz 不验证原生长期泄漏、失控驱动或实体多 GPU 延迟。


## Windows 显示器切片基准（2026-10-16）

源码 `7bd5b197b11d2c7b1010391f902b61e9a3af7ee3`，干净工作区，打包结束后单进程执行 `cargo bench --locked -p daoseeker-scope --bench collect`；Rust 1.96/MSVC、bench 优化 profile、门面默认 serde，原生 max_entries=128；合成 backend 单独设 1024。

本机环境自报：Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz，12 逻辑/6 物理核，x86_64；Windows 11 (26300)、内核 26300；OS 可用总内存 17009004544 bytes，安装内存 17179869184 bytes。本机 CLI/C 与 C SDK 均读一条活动路径、1920×1080，名称 NotPresent；该结果不证明面板原生分辨率、多个实体显示器或 EDID 名称的可用性。

| 指标 | 单进程结果 |
|---|---|
| 首次 collect（不含构造） | 436664 µs |
| 100 次动态刷新 p50 / p95 / max | 2255 / 3058 / 3938 µs |
| CPU 第二样本状态 | Available |
| 合成 100 传感器/1024 网络条目 collect | 360 µs |
| 合成快照 UTF-8 JSON | 373541 bytes |

[参数、环境、原始指标与日志 SHA-256](evidence/windows-display-benchmark-local-7bd5b19.json)对应本轮实现。该基准为整个后端组合，未隔离显示器 API 开销，也未与旧版本做配对测量；不宣称性能改善/退化，不测峰值内存、长期泄漏或驱动强制中止。显示器属于静态缓存，动态刷新不重新读取显示路径。


## Linux 显示连接视图切片基准（2026-10-17）

CI 源码 `a348614c3256f11b0af18678323bb578d37673fa`，实现 `cac0191`，中间仅文档/报告变更。命令 `cargo bench --locked -p daoseeker-scope --bench collect`；Rust 1.96、bench 优化 profile、门面默认 serde；原生 max_entries=128，合成 backend 另设 1024。托管 Linux x64 runner 自报的硬件和系统摘要见[完整环境及原始指标](evidence/linux-display-benchmark-38983994614.json)。该环境不是维护者的实体 Linux 电脑。runner 自报 Ubuntu 24.04、内核 6.17.0-1022-azure，AMD EPYC 9V74 80-Core Processor、2 逻辑核、x86_64，OS 可用总内存 8323969024 bytes；CPU 产品字符串不代表 runner 获配了 80 个核。

| 指标 | 单进程样本 |
|---|---|
| 首次 collect（不含构造） | 911 µs |
| 100 次动态刷新 p50 / p95 / max | 105 / 129 / 169 µs |
| CPU 第二样本状态 | Available |
| 合成 100 传感器、1024 网络条目 collect | 238 µs |
| 合成快照 UTF-8 JSON | 373541 bytes |

同轮 CLI/C 各确认一条 connected 连接视图，默认名称 PrivacyRedacted、宽高 Unsupported。基准为整个组合采集器，不是显示器枚举/EDID 的单独延迟，且默认不读取 EDID。动态刷新使用静态缓存，不重扫连接器。未与旧代码做配对测量，不据此宣称性能改善/退化，不测驱动强制中止、峰值内存、真实显示器热插拔或长期泄漏；这不是性能 SLA。


## macOS 活动显示切片基准（2026-10-18）

CI 源码 `1231088bc97d005a7e3c516d865db14362baf8ed`，采集实现 `2cf2736`；中间增加本地归档和验收守卫修正，底层采集与基准代码未变。命令 `cargo bench --locked -p daoseeker-scope --bench collect`；Rust 1.96、bench 优化 profile、门面默认 serde；原生 max_entries=128，合成 backend 另设 1024。托管 runner 自报 Darwin 26.6.2、内核 25.6.0，CPU Apple M2 Pro (Virtual)、5 逻辑核、arm64，OS 可用总内存 15032385536 bytes。它不是维护者的实体 Mac 环境。

| 指标 | 单进程样本 |
|---|---|
| 首次 collect（不含构造） | 12509 µs |
| 100 次动态刷新 p50 / p95 / max | 24 / 28 / 76 µs |
| CPU 第二样本状态 | Available |
| 合成 100 传感器、1024 网络条目 collect | 447 µs |
| 合成快照 UTF-8 JSON | 373541 bytes |

[环境、参数及原始日志](evidence/macos-display-benchmark-39081392549.json)与[原生报告](evidence/macos-display-native-darwin-39081392549.json)绑定。该基准为整个组合采集器，不隔离 Core Graphics 的 Copy/Get/Release、WindowServer IPC 或真实多屏时延；动态刷新使用静态缓存，不重扫显示器。未与旧代码做配对测量，不据此宣称性能改善/退化，不测驱动强制中止、峰值内存、长期原生泄漏或实体面板效果；这不是性能 SLA。


## 显示器 CLI 切片的整库回归基准（2026-10-19）

源码 `7da6f60c836ade85c70604215e3f0a79ad44bcff`，命令 `cargo bench --locked -p daoseeker-scope --bench collect`；Rust 1.96、bench 优化 profile、门面默认 serde；原生 max_entries=128，合成 backend 另设 1024、100 个传感器/1024 个网络条目。两个托管 runner 各执行一次采集基准；没有测量 CLI 启动或文本渲染。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs（100 次） | 合成 collect µs / JSON bytes | 环境和原始日志 |
|---|---|---|---|---|
| Linux x64 | 1141 | 298 / 364 / 901 | 234 / 373541 | [完整记录](evidence/display-text-benchmark-linux-39178858567.json) |
| macOS ARM64 | 12830 | 24 / 38 / 95 | 371 / 373541 | [完整记录](evidence/display-text-benchmark-darwin-39178858567.json) |

上述为整个组合采集器，首次 collect 不含构造、动态刷新不重扫静态显示器。完整环境见各报告，CPU 产品字符串不是 runner 获配核数的证明。没有旧版配对样本，不据此宣称性能改善/退化；不测峰值内存、长期泄漏、原生调用强制中止或实体显示器，不是 SLA。


## Windows 内存切片的常规整库回归基准（2026-10-20）

源码 `d7d30f27ac646d35a03d316b16ed29a4fc6a6f3f`，命令 `cargo bench --locked -p daoseeker-scope --bench collect`；Rust 1.96、bench 优化 profile、默认 serde；原生 max_entries=128，合成单独设 1024（100 传感器/1024 网络）。只有 Linux/macOS 托管 runner 执行该基准，不用于说明 Windows 内存 API、CPU 或文本输出性能。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs（100 次） | 合成 collect µs / JSON bytes | 完整环境及原始日志 |
|---|---|---|---|---|
| Linux x64 | 886 | 107 / 144 / 174 | 280 / 373541 | [完整记录](evidence/windows-memory-benchmark-linux-39347249649.json) |
| macOS ARM64 | 15705 | 25 / 46 / 79 | 385 / 373541 | [完整记录](evidence/windows-memory-benchmark-darwin-39347249649.json) |

首次 collect 不含构造；动态刷新使用静态缓存。未做旧版配对，不宣称性能改善/退化，也未测峰值内存、长期泄漏、内核调用强制中止或物理设备效果，不是 SLA。独立 Windows 64 MiB 实验为功能验证，存在其他进程干扰，不是该表中的合成基准或精确可用内存因果测量。


## Windows CPU 切片的常规整库回归基准（2026-10-20）

源码 `fb729663bb8974c0159231106a4ce2accf112f64`，命令 `cargo bench --locked -p daoseeker-scope --bench collect`，Rust 1.96、bench 优化 profile、默认 serde。原生 max_entries=128；合成独立设置 1024，包含 100 个传感器和 1024 个网络条目。仅 Linux/macOS 托管 runner 执行，不是 Windows CPU API 或 CLI 延迟测量。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs（100 次） | 合成 collect µs / JSON bytes | 完整环境与原始日志 |
|---|---|---|---|---|
| Linux x64 | 1165 | 344 / 394 / 590 | 240 / 373541 | [完整记录](evidence/windows-cpu-benchmark-linux-39350478223.json) |
| macOS ARM64 | 54648 | 41 / 91 / 1021 | 154 / 373541 | [完整记录](evidence/windows-cpu-benchmark-darwin-39350478223.json) |

首次 collect 不含构造，动态刷新使用静态缓存。没有旧版配对，不宣称性能改善/退化；没有峰值内存、长期泄漏、内核调用强制中止或物理设备测量，不是 SLA。Windows CPU SDK 实验是功能验证，不作为该表的性能样本。


## macOS CPU 切片的整库回归基准（2026-10-21）

源码 `ac9baff0d90b59c3639ae49e3dbd782a9c024b03`，命令 `cargo bench --locked -p daoseeker-scope --bench collect`，Rust 1.96、bench 优化 profile、默认 serde。原生 max_entries=128；合成独立设置 1024，包含 100 个传感器和 1024 个网络条目。以下来自托管 runner，不是物理设备、Mach 单次调用或 CLI 启动延迟。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs（100 次） | 合成 collect µs / JSON bytes | 完整环境与原始日志 |
|---|---|---|---|---|
| Linux x64 | 1254 | 348 / 542 / 843 | 227 / 373541 | [完整记录](evidence/macos-cpu-benchmark-linux-39518381989.json) |
| macOS ARM64 | 42576 | 36 / 135 / 232 | 119 / 373541 | [完整记录](evidence/macos-cpu-benchmark-darwin-39518381989.json) |

首次 collect 不含构造，刷新使用静态缓存。没有旧版配对，不宣称性能改善/退化；没有峰值内存、长期泄漏、内核调用强制中止或实体设备测量，不是 SLA。SDK 短采样是功能证据，不并入本表作为性能样本。


## macOS 内存切片的整库回归基准（2026-10-22）

源码 `b8b6383b007a7efe56f4513e3fc786e0406a3901`，命令 `cargo bench --locked -p daoseeker-scope --bench collect`，Rust 1.96、bench 优化 profile、默认 serde。原生 max_entries=128；合成另设 1024，含 100 个传感器和 1024 个网络条目。仅托管 Linux/macOS runner，不是 Mach 单次调用、CLI 启动或物理设备测试。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs（100 次） | 合成 collect µs / JSON bytes | 环境和原始日志 |
|---|---|---|---|---|
| Linux x64 | 993 | 268 / 302 / 369 | 150 / 373541 | [完整记录](evidence/macos-memory-benchmark-linux-39696658516.json) |
| macOS ARM64 | 33392 | 39 / 55 / 68 | 172 / 373541 | [完整记录](evidence/macos-memory-benchmark-darwin-39696658516.json) |

首次 collect 不含构造，刷新使用静态缓存。没有旧版配对，不宣称性能改善/退化；没有峰值内存、长期泄漏、强制中止或物理设备测量，不是 SLA。VM 统计可由 OS 缓存，该表也不能证明每次调用得到新内核计数。


## Windows uptime 切片的整库回归基准（2026-10-22）

源码 `8fce1893765436c57313634fde55c1ea79d6f7da`，命令 `cargo bench --locked -p daoseeker-scope --bench collect`，Rust 1.96、bench 优化 profile、默认 serde。原生 max_entries=128；合成为 100 个传感器、1024 个网络条目，max_entries=1024。仅托管 Linux/macOS runner 的整库回归；没有 Windows benchmark，不是 GetTickCount64 单次调用或 CLI 启动性能。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs（100 次） | 合成 collect µs / JSON bytes | 环境和原始日志 |
|---|---|---|---|---|
| Linux x64 | 619 | 67 / 107 / 146 | 231 / 373541 | [完整记录](evidence/windows-uptime-benchmark-linux-39755735940.json) |
| macOS ARM64 | 38357 | 77 / 122 / 327 | 158 / 373541 | [完整记录](evidence/windows-uptime-benchmark-darwin-39755735940.json) |

首次 collect 不含构造，刷新使用静态缓存；没有旧版配对，不声明性能改善/退化、峰值内存或 SLA。macOS VM 统计仍可由 OS 缓存，本表不能证明每次得到新内核计数。


## macOS uptime 切片的整库回归基准（2026-10-23）

源码 `8500cc848a72fed9994e7e51bcf7e46db4503bf1`，命令 `cargo bench --locked -p daoseeker-scope --bench collect`，Rust 1.96、bench 优化 profile、默认 serde。原生 max_entries=128；合成为 100 个传感器和 1024 个网络条目，max_entries=1024。仅托管 Linux/macOS 整库回归，不是单次 sysctl/time 调用、CLI 启动或物理设备基准；本轮没有 Windows benchmark。

| 平台 | 首次 collect µs | 刷新 p50 / p95 / max µs（100 次） | 合成 collect µs / JSON bytes | 环境和原始日志 |
|---|---|---|---|---|
| Linux x64 | 1150 | 266 / 301 / 458 | 206 / 373541 | [完整记录](evidence/macos-uptime-benchmark-linux-39878588965.json) |
| macOS ARM64 | 20983 | 36 / 52 / 130 | 480 / 373541 | [完整记录](evidence/macos-uptime-benchmark-darwin-39878588965.json) |

首次 collect 不含构造，刷新使用静态缓存。没有旧版配对，不声明性能改善/退化、峰值内存或 SLA；macOS VM 统计仍可缓存，该表不能证明每次获得新内核计数。
