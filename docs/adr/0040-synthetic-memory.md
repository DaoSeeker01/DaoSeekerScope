# ADR 0040：合成设备规模的进程峰值测量

状态：固定源码的 Windows 本机及三平台原生 CI 40796845854 验收通过，见[性能报告](../benchmarks.md)。

## 目的

已有整库 benchmark 包含合成数据耗时，但没有覆盖大集合的进程峰值。真实机器未必有足够设备，不能把设备数量不足当作上限行为已验证。因此使用明确标注的固定 fixture，单独测量组合、缓存、隐私、序列化与超限字段隔离。

## 选择

为门面 crate 增加仅开发使用的 `synthetic_memory` cdylib 示例，调用现有公共 `HardwareBuilder` 和 Backend API。一个 backend 返回 100 个合成传感器，另一个返回 1024 个合成网络条目；max_entries=1024。不调用系统 backend，不把 fixture 当作设备支持证据。

第二个 profile 将网络条目改为 1025。已有 core 规则会将该字段置为 Unavailable/InvalidData，整个网络列表不再保留；100 个健康传感器仍应可用。它不是“只保留前 1024 项”的截断成功，也不是整个 backend 失败。

示例只导出 `scope_probe_synthetic(u32, u32) -> u64`，供开发 C 探针调用。返回最大 JSON 字节数，0 是开发协议的失败标记；不传递指针、布局或字符串，不属于正式 `dsc_` ABI。所有工作在 panic 捕获边界内，数据及 buffer 均由 Rust 管理。唯一 unsafe 标记是有安全说明的私有符号导出属性；生产库与安装头文件不变。

复用原 C 内存探针，通过 `DSCOPE_SYNTHETIC` 编译出单独的程序，链接该示例库。每个 profile 一个进程，记录采集前、首批、第二批峰值。首批构造采集器、collect 并 JSON 往返一次；第二批重建采集器，再 collect 一次和 refresh_dynamic 100 次，每次均往返 JSON 并校验语义。每批每个 backend 的静态读取必须为 1，动态读取必须为 1 加刷新次数。

这两个批次不是同一个采集器的连续调用，计时包含构造和 JSON 编解码。峰值是整进程运行历史，不能相减视作每次分配，也不能与旧单 backend 延迟 benchmark 直接比较。

## 验证与资源

- Rust 每次检查集合规模、温度值、Custom 来源、网络名称脱敏、设备序列号脱敏、无 backend 错误、JSON 往返和静态缓存计数。参数超过固定 profile 或 100 次刷新立即拒绝。
- C 端检查非零结果、1 MiB JSON 上限和计时。共享 OS 计量代码和独立 64 MiB 校准；Linux 沿用 [ADR 0039](0039-linux-peak-launch-isolation.md) 的 fork 隔离，不在已经调用 Rust 的线程环境中 fork。
- Python 明确记录合成规模与每批刷新次数，并核对 C 程序、示例库和正式 CLI/FFI 的哈希及源码状态；失败、中断不得保留旧成功。
- 示例仅通过 `cargo build -p daoseeker-scope --example synthetic_memory` 构建，不增加 crate、依赖、feature、正式 ABI 或候选包内容。源码打包与独立构建仍须通过。

这里只证明有限 fixture 的行为与进程峰值。它不覆盖真实 100 个传感器、1024 个接口、驱动阻塞、持续内存增长或 allocator 归因。正常与超限 profile 的有效输出量不同，耗时和峰值差异不是性能优化幅度。

## 官方依据

[Cargo 示例目标](https://doc.rust-lang.org/cargo/reference/cargo-targets.html#examples)允许开发示例编译为库；[Rust cdylib 说明](https://doc.rust-lang.org/reference/linkage.html)定义了供其他语言加载的动态库形式。此处只用于开发测量，正式 FFI 仍按既有 ABI 契约管理。
