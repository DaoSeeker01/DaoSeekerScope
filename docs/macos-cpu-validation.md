# macOS CPU 采样验证

新增 MacosCpuBackend，直接处理逻辑核数和动态 CPU。公开接口、所有权、错误/计数语义与迁移见 [ADR 0025](adr/0025-macos-cpu.md)。品牌/架构/物理核数、内存及 uptime 不属于本轮；内存的新鲜度问题仍待后续。

2026-10-21 本机为 Windows x64。本轮通过 218 项 Rust 测试（含十项可在 Windows 执行的 macOS CPU 纯逻辑测试），fmt、all-target/all-feature Clippy、no-default-features、doc、CLI/FFI 构建及 Linux x64/macOS arm64 交叉检查；macOS arm64 的 all-target/all-feature Clippy 额外以 `-D warnings` 通过。后者只编译库/测试，不证明 Mach 符号链接、SDK 探针或真实读取。

Python Ruff/mypy 38 个文件、98 项测试、Schema 检查通过。新增四项报告守卫测试覆盖缺失/预热、无符号值域、数组形状、两个资源释放状态、逐核回退、加权求和、失败/中断覆盖旧 passed 并保留安全的未完成观测。负面测试故意输出 failed，不是执行了 macOS 采样。fuzz 格式与两个现有 harness 单元测试通过，没有运行实际 libFuzzer、Miri、ASan 或新的性能基准。

本机 C ABI collect/free、归零/空释放/旧副本拒绝通过；通用 Windows CLI/C/Python 五组原生回归通过。这些结果是 Windows 回归证据，不是 macOS 原生证据。

纯逻辑验证包括 300 ms 精确边界、快速轮询不饥饿、0/100/nice 与不同核的加权增量、1024 核整数上界、逐核 32 位 wrap/reset、不增长、数量变化与静态失败缓存、Mach 错误码隔离、错误恢复、调用前取消/调用后超时、RAII 反序释放及释放失败不重复尝试。注入计数/错误不是实体故障复现；没有读取畸形内存指针。

macOS 原生复现入口（本轮待执行）：

```sh
cargo build --locked -p daoseeker-scope --example dynamic_probe
cc -Wall -Wextra -Werror -std=c11 docs/research/macos_cpu_probe.c -o target/macos-cpu-probe
python scripts/macos_cpu_smoke.py
```

SDK 探针每帧获取/释放 host right 和 OOL VM 数组，固定 1024×4 栈副本；先检查成功/形状，再复制无符号 tick，释放均成功才输出。最多八条 stdin 指令；不采集标识，不制造负载。Python 只启动两个子进程，单行 1 MiB、每次读取/退出 5 秒，异常终止自己创建的进程；计划验证初始预热、三次至少 350 ms 的有效刷新、静态核数缓存及重建后重新预热，SDK 独立计算区间百分比。两进程采样窗口不同，不要求同值。

CI 已准备公开 SDK 编译、持久刷新及 artifact 保留步骤，**尚未运行本轮远程 CI**。macOS SDK C 编译/符号链接、原生读取/释放、App Sandbox、真实拒绝/故障、处理器数量变化、Intel/Apple Silicon 实体机、长期 tick 绕回与峰值内存均未验证。macOS 物理设备按维护者决定延期；不能用交叉编译替代。sysinfo 仍为静态品牌等字段内部枚举，本轮不承诺其内部 OS 分配有硬上限；新 backend 自有复制/基线分别最多 16 KiB，MIG 的先行 OS 分配不能被本库强行限定。

公共模型、ABI 1/Schema 1、依赖包/版本/features/锁文件与 MIT 不变。新增公开 MacosCpuBackend::new()/Default，门面自动注册；macOS 单独 SysinfoBackend 用户需补注册。核数/利用率来源从 Sysinfo 改为 AppleApi，能力 Partial；不能再依赖失败时的 1 核/0%。
