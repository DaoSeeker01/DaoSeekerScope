# 使用指南

## Rust

当前尚未发布到 crates.io。克隆仓库后，使用本地路径依赖，按你的目录位置调整 `path`：

```toml
[dependencies]
daoseeker-scope = { path = "../DaoSeekerScope/crates/daoseeker-scope" }
```

```rust
let hardware = daoseeker_scope::Hardware::new()?;
let snapshot = hardware.collect()?;
let brand = &snapshot.static_info.system.cpu.brand;
println!("{:?} {:?} {:?}", brand.value(), brand.availability(), brand.reason());

// 占用率需要两次有效采样；首次或过早读取会返回暂不可用。
std::thread::sleep(std::time::Duration::from_millis(300));
let dynamic = hardware.refresh_dynamic()?;
println!("{:?}", dynamic.cpu_usage_percent.value());
```

`collect()` 首次采集静态信息，之后使用缓存并刷新动态字段。`refresh_dynamic()` 需要先成功调用一次 `collect()`。型号和核数属于静态信息；占用率、可用内存、运行时长、电量和温度属于动态信息。静态失败也会缓存；权限或内存容量变化后，重建 `Hardware` 重新采集。一次快照包含多个系统调用，不承诺所有字段同一时刻的原子一致性。

Windows 总内存和可用内存通过公开 Win32 API 读取，来源 `Win32`；每次动态刷新重新检查成功/失败。总量变化后可用内存为暂不可用，需重建 `Hardware`。直接使用 backend crate 时，需同时注册 `WindowsMemoryBackend::new()`，详见 [Windows 内存契约](adr/0023-windows-memory.md)。

Windows CPU 用量由 `WindowsCpuBackend::new()` 提供，门面自动注册，单独 `SysinfoBackend` 不再提供该字段。每次读取新计数；首次/过早刷新暂不可用，失败后重新预热。当前仅支持单活动处理器组，多组明确不支持；来源 `Win32`，能力 `Partial`，需要检查实际字段状态，见 [CPU 契约](adr/0024-windows-cpu.md)。

macOS 逻辑核数与 CPU 用量改由 `MacosCpuBackend::new()` 提供，门面自动注册，来源 `AppleApi`、能力 `Partial`；首次/失败恢复需重新取得 300 ms 有效采样对。核数仍静态缓存，数量变化需重建 `Hardware`。单独 `SysinfoBackend` 不再提供这两个 macOS 字段。当前实现已通过三平台 CI 与 macOS ARM64 公开 SDK/持久刷新；实体 Mac、Intel 原生和真实 Mach 故障仍待验证，见[验证边界](macos-cpu-validation.md)。Windows/macOS uptime 保持 sysinfo/Partial。

macOS 内存由 `MacosMemoryBackend::new()` 提供，门面自动注册；单独 `SysinfoBackend` 用户须补注册。总量 `Sysctl/Partial` 沿用 `hw.memsize` 物理内存代理口径，不保证扣除所有保留区域；动态 `AppleApi/Partial` 为 `(active+inactive+free) * page_size` 非压缩内存估计，含 active，free 已含 speculative，不是立即可分配量、进程配额或压力指标。每次刷新发起新调用，OS 仍可能返回缓存计数；采集时间是调用完成时间，不是内核计数更新时间。错误不保留旧值；总量变化需新建 `Hardware`。CLI 按来源标为 `Physical total proxy bytes` / `Non-compressed estimate bytes`；文本不作程序协议。本轮 macOS 原生 CI/SDK 待验，见[契约](adr/0026-macos-memory.md)与[验证](macos-memory-validation.md)。

## 如何判断一个字段

重要字段使用 `Observed<T>`，包含值、状态、来源、采集时间和原因。先检查状态，再使用值。

| 状态 | 含义 |
|---|---|
| `Available` | 成功得到值；集合可以合法为空 |
| `Unavailable` | 当前读不到，例如缺少设备、损坏输入或临时失败 |
| `Restricted` | 权限、沙盒或隐私策略限制 |
| `Unsupported` | 当前 backend 没有实现 |
| `NotApplicable` | 平台明确表明该项不适用 |

不要把 `None` 或不支持的集合当作设备不存在。`capabilities()` 描述实现及本次采集的限制，不能替代逐字段状态。字节为 bytes，时间为 seconds，百分比为 0..100，温度为摄氏度；真实的 0% 与不可用状态不同。

## CLI 与 JSON

`dscope` 提供 `cpu`、`memory`、`gpu`、`disk`、`display`、`network`、`battery`、`sensors`、`system` 和 `capabilities`。文本模式显示所选类别；所有 `--json` 命令输出完整快照。`cpu` 会等待至少 300 ms 完成第二次采样；其他命令保留首次 CPU 暂不可用状态。

退出码：0 表示命令成功（结果可以包含不可用字段），2 表示参数错误，3 表示采集或输出错误。输出管道接收端关闭时正常结束。

文本模式在每个可用值及集合数量后显示来源，例如 `Available bytes: 0 (Procfs)`；缺失字段显示状态、来源和原因，不补零。`capabilities` 同时显示能力等级、来源及模型已有的受限原因。GPU、网络、电池和传感器逐条显示字段并编号，编号只代表本次顺序，不是稳定设备标识；`0 entries` 只表示该次成功枚举的可见集合为空。Windows GPU 通过 DXGI 返回非软件适配器的产品描述和独占显存，属于静态缓存；不包含共享显存、实时使用量或物理显卡数量。Linux 目前提供有限 DRM 设备枚举及部分 AMD/NVIDIA 名称，独占显存仍 Unsupported；不覆盖未绑定 DRM 的 GPU，也不把驱动名当作型号。macOS 仅枚举 Metal 可见设备并读取名称；确认统一内存时独占显存为 NotApplicable，其他情况为 Unsupported，不把工作集预算当作显存容量。采集时间及完整元数据请使用 `--json`，文本格式不作为程序接口。

`dscope disk` 文本模式逐条显示名称状态、容量及来源。容量同时显示按 1024 换算的 IEC 单位（KiB/MiB/GiB 等，保留两位小数）和精确字节数；自动化处理使用 `--json`，不要解析文本。真实零显示 `0 B (0 bytes; ...)`，缺失或受限值显示状态/原因。条目编号只表示本次快照顺序，包含虚拟对象，不是物理盘编号，容量可能重叠，不能求和推断物理总量。空集合只表示当前可见列表没有条目。

Rust 使用 `to_json` / `from_json` 交换 Schema v1。输入和展开后的输出均限制为 1 MiB。未知对象字段忽略，未知枚举值或错误版本拒绝；字符串、集合、数值和内存关系还有领域校验。[JSON Schema](schema/snapshot-v1.schema.json)不能替代这些检查。

`dscope display` 逐条显示名称、像素字段及状态/来源。Windows 标为 Signal width/height pixels，macOS 标为 Mode width/height pixels；按字段来源选择标签，编号不代表物理显示器。空表和不可用状态分别展示。`display --json` 输出完整快照，含采集时间；文本不作为程序接口。Windows 的 `static_info.displays` 同时可通过 Rust API、C ABI JSON 或 `dscope --json` 查看。返回活动路径的 EDID 友好名称（可能 NotPresent）和当前目标信号活动像素宽高；不是面板原生/首选分辨率、DPI 逻辑尺寸或桌面旋转后的坐标。数据缓存到当前 Hardware，模式/连接变化后需新建实例；动态刷新不重扫。远程或无控制台访问时可 Restricted/PermissionDenied，不能据此认为没有显示器。Linux 的 displays 只统计 DRM status=connected 的连接视图，不保证当前活动，也不等于物理显示器数量。默认不读取含标识的 EDID，name 为 Restricted/PrivacyRedacted；显式 --include-sensitive --authorized 后仅解析 EDID 1.3/1.4 基础块的产品名称，OS 权限仍生效，序列号不导出。Linux 宽高仍 Unsupported，绝不把 modes 列表或 EDID 时序当作当前模式；状态 unknown/无法完整枚举时不会返回成功空表。Linux 同样静态缓存，变化后需新建实例。macOS 新增公开 Core Graphics 活动视图，宽高来自当前显示模式的 pixelWidth/pixelHeight，不是逻辑 points、面板原生分辨率或 Windows 信号尺寸。硬件镜像可能只列主显示，不作为物理显示器计数。名称保持 Unsupported，不查询 EDID/稳定标识；本轮原生 CI 与独立 SDK 对照已完成，实际状态见[验证记录](macos-display-validation.md)。文本命令契约见 [ADR 0022](adr/0022-display-cli.md)，[本轮验证](display-text-validation.md)与各平台历史设备证据分开记录。

## C 与 Python

构建共享库：`cargo build --locked -p daoseeker-scope-ffi`。从[头文件](../bindings/daoseeker_scope.h)和[C 示例](../examples/collect.c)开始。Windows 可以用 `pwsh -NoProfile -File scripts/build_c_example.ps1` 构建并验证示例；Linux/macOS 编译命令见[开发指南](../CONTRIBUTING.md)。

Windows：`python examples/collect.py target/debug/daoseeker_scope_ffi.dll`；Linux 改为 `target/debug/libdaoseeker_scope_ffi.so`，macOS 改为 `target/debug/libdaoseeker_scope_ffi.dylib`。

按 `len` 读取库分配的 UTF-8 Buffer，它没有 NUL 结尾。用 `dsc_buffer_free` 释放，释放后原结构清零，陈旧复制会被拒绝。最多保留 64 个未释放 Buffer。默认的 NULL options 复用采集器；非 NULL options 每次创建新采集器，因此重新读取静态项，CPU 占用率可能没有采样基线。不要并发读取正在释放的 Buffer。完整所有权、线程与错误契约见 [ABI ADR](adr/0004-c-abi.md)。

ABI v1 没有 shutdown 接口。首次采集后应保持共享库加载到进程结束，不能把 Buffer 全部释放等同于所有后台 worker 已停止；本版不支持运行中的共享库卸载或热重载。

## 隐私与限制

序列号默认不读取，网络接口名称默认隐藏。显式请求须同时声明调用方已获授权；CLI 使用 `--include-sensitive --authorized` 并向 stderr 输出警告。声明授权不会绕过系统权限。当前不解析、保存或输出 MAC、IP、UUID、磁盘序列号、用户、进程、主机名或个人文件。Windows 网络 API 向临时原始缓冲写入 MAC/GUID 等元数据，实现只访问索引、计数及授权后的名称；这不等于标识从未进入进程内存，详见 [Windows 契约](adr/0011-windows-network-counters.md)。

Linux 的 `dscope network` 显示当前网络命名空间内的累计接收/发送字节数（含回环、虚拟接口），不是网速或进程流量。每次刷新重新读 `/proc/net/dev`，接口重建后计数可以下降；数组顺序不是稳定身份。接口名称默认 Restricted/PrivacyRedacted，累计字节数仍可用。读取失败返回字段状态，不保留旧值；细节见[网络契约](adr/0010-linux-network-counters.md)。Windows 通过有界 GetIfTable 枚举和 GetIfEntry2 读取 64 位计数，能力 Partial，不保证所有逻辑隧道接口。

macOS 使用公开 Sysctl，能力 Partial：普通应用的值可能按 1 KiB 向下取整，并转换为 32 位有效范围，因此可回绕，不承诺精确或完整累计量。保留系统返回值，不补算。默认不查询名称；临时缓冲仍包含未解析的链路地址元数据。详见 [macOS 网络契约](adr/0012-macos-network-counters.md)，原生读取验证另列。

`dscope disk` 读取 OS 暴露的整块设备容量，包含虚拟设备，不表示文件系统可用空间、分区或可相加的物理总容量。Linux 读取 `/sys/block` 一级条目；Windows 通过 SetupAPI 枚举整盘接口，以零读写权限句柄查询 Win32 DiskSize；macOS 读取 IOMedia Whole/Size。三者都限制枚举并按字段返回失败，能力 Partial，沙盒或驱动可限制可见性及访问。容量在首次采集后缓存，扩容、插拔和失败恢复需新建 Hardware；动态刷新保留原值和原时间。默认名称隐藏，只有显式请求并声明授权才显示 OS 设备名；Windows 查询设备编号形成 PhysicalDriveN，macOS 才读取 BSD Name，均不查询磁盘序列号或 UUID。core 对自定义 backend 同样脱敏。Windows 临时接口路径缓冲含标识，但不保存到模型或日志；macOS 不复制全部属性表。字段/签名、Schema 1、C ABI 1 不变，详见[存储契约](adr/0013-storage-capacity.md)、[Windows 决策](adr/0014-windows-storage-capacity.md)和 [macOS 决策](adr/0015-macos-storage-capacity.md)。成功空枚举只表示当前可见集合没有条目，不证明机器不存在存储设备。

Linux 温度仅路由 coretemp、k10temp 的 Tdie 和 NVMe 通道 1..9，默认不读标签；NVMe Composite 可以是设备计算值。Windows/macOS 的 sysinfo 动态值仍有上游缓存与错误表达限制，能力标为 Partial。

每个采集器一个 worker，全进程最多 16 个。超时和取消限制等待，不能强杀阻塞的 OS 调用。自定义 backend 是受信任代码，应遵守有界、快速能力查询及上下文检查契约；通过 `HardwareBuilder::with_backend` 注册，更高优先级的有效值优先，缺失增强不会擦除已有有效值。

Android、iOS、Web、no_std 和 MCU 尚未实现。发布、长期 fuzz 和真实 Linux 电池/温度验证见[发布路线](release.md)与[验证目录](README.md)。

库不安装日志或 panic hook。catch_unwind 仍会调用宿主的 panic hook；宿主应对自定义 backend 的 panic 文本脱敏。C 调用方传入无效指针、OOM 或使用 panic=abort 构建时，不能依赖状态码保护进程。
