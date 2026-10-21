# ADR 0026：macOS 内存错误隔离与公开统计边界

状态：源码 57500a6 已实现并通过 Windows 完整门禁、干净源码原生/八包独立验收及 macOS arm64 交叉 Clippy；尚无本轮 macOS 原生证据，见[记录](../macos-memory-validation.md)。

锁定的 sysinfo 0.39.6 Apple refresh_memory_specifics 在 host_statistics64 失败时不清除 mem_available，且仅在 mem_total<1 时重读总量。适配层无法区分失败与旧成功值。本轮新增 MacosMemoryBackend::new()/Default，门面自动注册；保留 MacosBackend 单元构造，sysinfo 在 macOS 停止提供这两个字段。单独 SysinfoBackend 用户需补注册或使用门面。CPU、installed_bytes 与 uptime 路线不变。

total_usable_bytes 延续原 macOS hw.memsize 口径，改为检查返回值/长度的固定 u64 sysctl 读取，Source Sysctl、Partial。它是 OS 报告的物理内存代理值，不证明扣除所有硬件保留、等于可分配量或进程配额；与 installed_bytes 的现有独立读取可能相同，不能相减推导保留量。当前公共字段名不改，限制在使用说明与矩阵明确。

memory_available_bytes 使用公开 host_page_size + host_statistics64(HOST_VM_INFO64)，来源 AppleApi、Partial。沿用原 active+inactive+free 页乘页大小口径，是非压缩 working-set/reclaimable 估计，包含 active 页，不表示立即可分配、仅空闲内存、Activity Monitor Memory Used 的补集、进程上限或内存压力。SDK free_count 已含 speculative，不能重复加。逐次检查状态、返回 word 数、正且二次幂页大小、speculative<=free、checked 加乘和 available<=本次总量；合法零保留，不截断、不饱和、不过量夹取。

每次刷新发起新 API 调用，不保存上次动态值；公开 Mach 入口受 OS 统计缓存/限流，不能保证新内核计数、不同数值或最大陈旧时间。Observed 时间仅表示本次成功调用完成；不提升为 Supported，不绕过限流或使用私有接口。没有 kernel 时间可供本模型标注。若调用方需要严格新计数，此字段无法满足。

libc 0.2.186 的 VM 结构为 rev1 前缀（152 bytes / 38 integer_t），较新 SDK 可能多 swapped_count；仅申请精确前缀并验证返回 count，不请求比 Rust 缓冲更大的结构。保留完整初始化、对齐和有效范围的 unsafe 注释。host send right 单所有权，所有退出/展开路径释放；显式释放失败拒绝成功样本，不无限重试。借用 task-self 不释放。固定栈缓冲，无自有设备/页面列表分配，不承诺 OS 内部分配上限或阻塞内核强制取消。

静态只读总量并缓存成功/失败；动态重新读取总量仅做一致性校验，不更改静态字段/时间。与成功缓存不同则 TemporarilyUnavailable，重建 Hardware 获取新静态视图。静态总量失败不阻止后续动态恢复。sysctl errno 与 Mach kern_return_t 分开映射：只把明确权限码记 PermissionDenied，不猜 Sandbox；未知码（含失败时的零）Unknown。取消/超时前后检查，不发布失败输出。

CLI 按字段来源标为 Physical total proxy / Non-compressed estimate，避免把这两个 macOS 口径当立即可用量；JSON 字段保持兼容。核心合并器对 Unsupported 可能保留默认 Custom 来源的既有边界不在本轮改变，调用方仍须检查实际 Availability。

无新依赖、feature 或锁文件；模型、ABI 1、Schema 1、MIT 不变。macOS 两字段来源和失败行为是开发版迁移，回滚需同时恢复 sysinfo 字段。验收使用可注入计数/错误、缓存/恢复/单位/整数界限/取消测试；原生 C SDK 和持久 Rust 进程验证留给 macOS CI，允许相同计数与不同进程值，不制造内存压力，不用合成故障冒充实体实验。实体 Mac、Intel 原生、沙盒、真实 API/清理故障、长期泄漏与缓存最大年龄均待验证。

依据（2026-10-22 核对）：Apple [Mach 公开接口](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/mach/mach_host.defs)、[VM 结构与 speculative 口径](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/mach/vm_statistics.h)、[非压缩内存定义](https://github.com/apple-oss-distributions/xnu/blob/main/doc/vm/memorystatus_notify.md)、[第三方统计缓存入口](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/kern/host.c)。只参考接口与语义，不复制 APSL 内核实现。
