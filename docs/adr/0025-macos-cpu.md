# ADR 0025：macOS CPU 新读、核数与 Mach 资源所有权

状态：源码 359af7e 已实现，Windows 纯逻辑/原生回归/八包独立验证及 macOS arm64 交叉检查通过；本轮没有 macOS 本机或 CI 运行证据，交叉编译不等于原生读取。见[验证](../macos-cpu-validation.md)。

锁定 sysinfo 0.39.6 的 Apple update_cpu_usage 在 host_processor_info 失败时仍写入初始 0%；init_cpus 的 HW_NCPU 查询失败还会使用 1。以上是源码确认的静默回退，未在实体 Mac 诱发故障。动态 CPU 与静态逻辑核数由新 MacosCpuBackend::new()/Default 直接处理，门面自动注册；保留原 MacosBackend 单元结构。Mac 的 SysinfoBackend 停止提供这两个字段，避免替代来源掩盖直接读取失败；品牌/架构/物理核数、内存与 uptime 保持原路线。

选择公开 host_processor_info(PROCESSOR_CPU_LOAD_INFO)，每次读一次所有处理器的 user/system/idle/nice 累计 tick。不采用 host_statistics(HOST_CPU_LOAD_INFO)：当前 Apple XNU 对该入口有第三方限流/缓存，不能据新调用承诺新计数。本库不绕过平台限制，不调用私有 API；公开接口被拒绝则返回受限/不可用。来源 AppleApi，两个字段声明 Partial；不承诺 App Sandbox、所有 CPU 配置或所有 macOS 版本可读。

仅成功后检查 MIG 返回的处理器数、integer_t 数量和数组；必须 1..1024 个处理器、每个恰好四个 32 位 word。失败时不消费输出，也不猜 errno。integer_t 中的计数按 natural_t 无符号位模式解释；高位不是负数错误。超过内部处理器上限返回不支持，不截断成部分整机。OS 先分配 out-of-line 数组，本库无法限制该系统分配，只限制后续复制为最多 16 KiB（基线另最多 16 KiB）。

mach_host_self 返回的 host send right 和成功返回的 VM 数组各有单一 RAII 所有者；VM 数组用 vm_deallocate，host right 用 mach_port_deallocate，借用的 mach_task_self_ 不释放。所有正常返回/验证失败/取消/展开路径清理；显式清理错误拒绝发布成功样本，不进行可能重复释放的无限重试。libc 已有读取/VM 绑定；缺失或已在 libc 弃用的公开 host-self/port 释放与 task-self 全局使用局部声明，不加 mach2 依赖，不把绑定弃用误写成系统 API 弃用。MIG 成功返回的内存有效性仍依赖 OS 契约，不能用畸形指针做安全测试。

首个动态样本或不足 300 ms 返回 TemporarilyUnavailable，快速轮询仍新读但保留基线以免饥饿。以各处理器、各状态增量求和，busy=user+system+nice；用 u64 累加，不用四类计数的平均比率。任一 32 位计数倒退（包括 wrap/reset）拒绝本次并清基线，不猜测绕回次数。失败、已进入 backend 的取消/超时清基线，恢复需新的两次有效样本；无增量暂不可用，真实全 idle 是可用 0%。时间使用 Instant 控制采样间隔，Observed 时间为读取完成后的系统时间。

逻辑核数静态缓存（成功与失败都缓存），不随动态刷新重读静态模型；动态接口本身返回的数量只做一致性检查。与缓存成功数量不同则暂不可用并清基线，要求重建 Hardware。静态核数失败不阻止动态成功恢复。数量相同的处理器替换/重新排序、ABA、睡眠/时钟边界和长时间 tick 绕回不能完全辨认，不宣称热插拔事务一致性。

无新包、feature、锁文件或许可证变化；公共模型、核心入口、C ABI 1、Schema 1 和 MIT 不变。开发版 macOS 两个字段来源由 Sysinfo 改为 AppleApi；单独 sysinfo 消费者须注册新 backend 或使用门面。回滚需同时恢复 sysinfo 的两个字段。核心合并器对 Unsupported 保留默认来源的现有边界不在本轮重构，调用方必须检查实际 Availability。

验收包括可注入错误、静态失败缓存/恢复、数量变化、合法 0/100、高位计数、单核回退、上限、取消与 RAII 的逐次释放；独立公开 SDK 探针与持久 Rust 进程只在 macOS 原生环境运行，不要求不同采样区间的百分比相同。本机 Windows 可执行纯逻辑/回归测试和 macOS 编译检查，真实 SDK/沙盒拒绝、Intel/Apple Silicon 实体机需要后续证据。

依据（2026-10-21 核对）：Apple [公开 Mach host 接口](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/mach/mach_host.defs)、[host 统计/限流实现](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/kern/host.c)、[处理器类型](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/mach/processor_info.h)。只参考公开契约/行为，没有复制 APSL 实现；仓库 MIT 不变。
