# macOS CPU 采样验证

新增 MacosCpuBackend，直接处理逻辑核数和动态 CPU。公开接口、所有权、错误/计数语义与迁移见 [ADR 0025](adr/0025-macos-cpu.md)。品牌/架构/物理核数、内存及 uptime 不属于本轮；内存的新鲜度问题仍待后续。

2026-10-21 本机为 Windows x64。本轮通过 218 项 Rust 测试（含十项可在 Windows 执行的 macOS CPU 纯逻辑测试），fmt、all-target/all-feature Clippy、no-default-features、doc、CLI/FFI 构建及 Linux x64/macOS arm64 交叉检查；macOS arm64 的 all-target/all-feature Clippy 额外以 `-D warnings` 通过。后者只编译库/测试，不证明 Mach 符号链接、SDK 探针或真实读取。

Python Ruff/mypy 38 个文件、98 项测试、Schema 检查通过。新增四项报告守卫测试覆盖缺失/预热、无符号值域、数组形状、两个资源释放状态、逐核回退、加权求和、失败/中断覆盖旧 passed 并保留安全的未完成观测。负面测试故意输出 failed，不是执行了 macOS 采样。fuzz 格式与两个现有 harness 单元测试通过，没有运行实际 libFuzzer、Miri、ASan 或新的性能基准。

本机 C ABI collect/free、归零/空释放/旧副本拒绝通过；通用 Windows CLI/C/Python 五组原生回归通过。这些结果是 Windows 回归证据，不是 macOS 原生证据。

纯逻辑验证包括 300 ms 精确边界、快速轮询不饥饿、0/100/nice 与不同核的加权增量、1024 核整数上界、逐核 32 位 wrap/reset、不增长、数量变化与静态失败缓存、Mach 错误码隔离、错误恢复、调用前取消/调用后超时、RAII 反序释放及释放失败不重复尝试。注入计数/错误不是实体故障复现；没有读取畸形内存指针。

macOS 原生复现入口（本机阶段待执行，后续 CI 结果见下节）：

```sh
cargo build --locked -p daoseeker-scope --example dynamic_probe
cc -Wall -Wextra -Werror -std=c11 docs/research/macos_cpu_probe.c -o target/macos-cpu-probe
python scripts/macos_cpu_smoke.py
```

SDK 探针每帧获取/释放 host right 和 OOL VM 数组，固定 1024×4 栈副本；先检查成功/形状，再复制无符号 tick，释放均成功才输出。最多八条 stdin 指令；不采集标识，不制造负载。Python 只启动两个子进程，单行 1 MiB、每次读取/退出 5 秒，异常终止自己创建的进程；计划验证初始预热、三次至少 350 ms 的有效刷新、静态核数缓存及重建后重新预热，SDK 独立计算区间百分比。两进程采样窗口不同，不要求同值。

本机阶段仅准备了公开 SDK 编译、持久刷新及 artifact 保留步骤，当时尚未运行远程 CI；下列未验证项保留为该阶段记录，后续原生 CI 结果另列。macOS SDK C 编译/符号链接、原生读取/释放、App Sandbox、真实拒绝/故障、处理器数量变化、Intel/Apple Silicon 实体机、长期 tick 绕回与峰值内存均未验证。macOS 物理设备按维护者决定延期；不能用交叉编译替代。sysinfo 仍为静态品牌等字段内部枚举，本轮不承诺其内部 OS 分配有硬上限；新 backend 自有复制/基线分别最多 16 KiB，MIG 的先行 OS 分配不能被本库强行限定。

公共模型、ABI 1/Schema 1、依赖包/版本/features/锁文件与 MIT 不变。新增公开 MacosCpuBackend::new()/Default，门面自动注册；macOS 单独 SysinfoBackend 用户需补注册。核数/利用率来源从 Sysinfo 改为 AppleApi，能力 Partial；不能再依赖失败时的 1 核/0%。

## 干净源码本机归档

源码 `359af7e3008a285154255925182644589728e1aa`，工作区干净。完整[本机证据索引](evidence/macos-cpu-local-359af7e.json)记录上述命令、日志哈希和明确的 not_run 项；不含伪造的 macOS 读取报告。

- [Windows 原生回归](evidence/macos-cpu-native-windows-359af7e.json)：五组、16 个进程通过；CPU/内存仍为本机已有 Win32 路线。这不是 Mac 的 SDK 或资源释放实测。
- [Windows 八包独立验证](evidence/macos-cpu-packages-windows-359af7e.json)：实际 Cargo 归档、原生验证、218 项独立 Rust 测试、MIT/头文件/锁检查及 dscope 0.1.0 安装/完整 JSON 通过。兄弟包用本地 patch，不代表 registry 验收，更不代表 Mach 符号链接成功。

以上为远程 CI 前的本机归档。随后经维护者明确授权完成下述推送与三平台 CI；实体机验证继续延期。


## 三平台原生 CI（2026-10-21）

[运行 39518381989](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/39518381989)，workflow_dispatch，源码 `ac9baff0d90b59c3639ae49e3dbd782a9c024b03`，全部 8 个任务成功；一次运行通过，无修复或重跑。实现提交 359af7e 至本次源码仅增加本机验收文档和报告，采集代码、SDK 与测试未变。

| 平台 | workspace / 八包独立测试（含 doctest） | Python 单测 | 通用原生 CLI/C/Python |
|---|---|---|---|
| Windows x64 | 218 / 218 | 98 | 五组、16 个进程通过 |
| Linux x64 | 211 / 211 | 98 | 五组、16 个进程通过 |
| macOS ARM64 | 213 / 213 | 98 | 五组、16 个进程通过 |

fmt、Clippy（拒绝 warning）、无默认 feature、doc（拒绝 warning）、Ruff/mypy（38 个源文件）、Schema/文档检查、实际 Cargo 归档、MIT/头文件/锁文件与独立 CLI 安装均通过。Python 各执行 100 次默认 collect/free；未发布兄弟包用本地 patch，不代表 registry 发布验收。[完整证据索引](evidence/macos-cpu-ci-39518381989.json)保留十一份报告、源码与日志哈希。

macOS 的[独立公开 SDK 与持久刷新报告](evidence/macos-cpu-sdk-39518381989.json)验证了 SDK 编译、Mach 符号链接和原生成功读取：3 个逻辑处理器，每个四个 32 位 tick，64 位指针。四帧 SDK 都确认 VM 数组和 host right 释放成功；三次 Rust 刷新均为 AppleApi/Available，采集时间递增，静态逻辑核数保持缓存，初始与重建后均重新预热。静态核数与 SDK 返回数量相同。

| 观测 | Rust CPU % | 独立 SDK 区间 % |
|---|---|---|
| 1 | 49.612403 | 51.851852 |
| 2 | 76.470588 | 76.470588 |
| 3 | 75.675676 | 75.675676 |

两个进程的区间不同，不要求百分比相等。SDK 的释放状态是独立 C 探针的直接结果；Rust 成功样本要求显式清理成功，但没有在本轮计量 Mach 端口/VM 长期净增长。不能据四次调用宣称长期无泄漏。

既有 Windows [CPU SDK](evidence/macos-cpu-windows-sdk-39518381989.json)与[内存 SDK/64 MiB 实验](evidence/macos-cpu-pressure-39518381989.json)重新通过。Linux 八份容器报告通过：CPU 15、内存/uptime 26、电池 30、hwmon 47、存储 21、GPU 20、显示器 26 项和既有 DMI/输入检查；完全空 `/proc` 的挂载仍被 OCI 拒绝，保留 not_run。

11 个实际 libFuzzer 目标各运行至少 60 秒，Miri 8 项、Linux Rust FFI ASan 10 项及 cargo-deny 通过。它们不是 Mach 原生指针边界或长期无漏洞证明。Linux/macOS 整库基准已执行，[参数与原始日志](benchmarks.md)单独保存，没有旧版配对或性能改善结论。

macOS ARM64 托管环境已验证成功路径；App Sandbox、真实 Mach 拒绝/损坏输出/释放失败、处理器数量变化、Intel 原生和 Intel/Apple Silicon 实体机仍未验证。注入错误与 RAII 单测不冒充这些设备实验。MIG 先行系统分配无法由本库限额，长间隔 tick 绕回、同数量拓扑变化及强制终止阻塞内核调用仍有限制。macOS 内存新鲜度属于下一独立切片。

验收归档只改变文档。新增公开 MacosCpuBackend 及两个字段的来源迁移维持 ADR 0025；无新依赖包、版本、feature 或锁文件变化，公共模型、C ABI 1、Schema 1、MIT 不变。未发布 registry 或 release 制品。
