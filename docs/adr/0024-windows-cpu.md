# ADR 0024：Windows CPU 直接采样与失败恢复

状态：源码 17cdc54 已通过本机 SDK/完整门禁/八包独立验收；本轮尚未执行三平台原生 CI。验证边界见[记录](../windows-cpu-validation.md)。

sysinfo 0.39.6 的 Windows PDH 路径在 Query::get 格式化失败时返回 Some(0)，refresh 失败也没有向适配层返回状态。这里是源码确认的错误传播缺口，不是真机复现了 PDH 故障。

采用公开 GetSystemTimes 的 idle/kernel/user 累计 100 ns 计数。kernel 已包含 idle，区间利用率为 `100 * (delta_kernel + delta_user - delta_idle) / (delta_kernel + delta_user)`；这不是频率加权的任务管理器 Processor Utility，也不是单进程用量。以 u128 求和，保留真实 0/100；拒绝计数倒退、idle 大于 kernel、无效增量。首样本和间隔不足 300 ms 返回 TemporarilyUnavailable，快速轮询仍读取当前计数但保留原基线，避免长期无法就绪。任何失败、取消或超时清除基线；恢复必须重新取得两次有效样本。不得给旧值加新时间。

每次读取前后查询活动处理器组数和组 0 处理器数，必须都是一个组、1..64 个活动处理器且前后相同；数量变化要求重新建立基线。组数大于一明确 Unsupported/NotSupported，不修改线程亲和性，不声称统计整机多组 CPU。查询组数返回零没有文档保证的扩展错误，不使用可能陈旧的 GetLastError，返回 Unknown。GetSystemTimes 和 GetActiveProcessorCount 的失败则立即捕获文档支持的 GetLastError。拓扑查询不是原子快照，不能识别同数量替换或 ABA。

新增 WindowsCpuBackend::new()/Default，保留原 WindowsBackend 单元结构；门面自动注册。Windows sysinfo 不再提供动态 CPU，以免覆盖直接采样失败；静态 CPU 型号/架构/数量仍由 sysinfo 负责。单独注册 sysinfo 的用户需同时注册该 backend 或改用门面。声明 Partial/Win32，表示仅覆盖单组；当前字段状态说明预热、失败和不支持。现有组合器跳过 Unsupported 更新，最终缺失字段可能保留 Unsupported/Custom/NotSupported，能力仍是 Partial；不能据此认定多组支持。此兼容限制不在本轮修改核心合并策略。

无第三方新包，windows-sys 增加 Win32_System_Threading 绑定 feature；Cargo.lock 和面向用户的 feature 集合不变。无标识、文件读取、后台计时线程或无限重试；固定栈结构，最多两次拓扑查询（各含组数/处理器数）和一次 GetSystemTimes，调用前后检查取消/超时，不能强行终止 Windows 内核调用。ABI 1、Schema 1、MIT 不变；开发版 Windows CPU 来源从 Sysinfo 改为 Win32，多处理器组不再给出未经完整覆盖验证的数值。

验收：注入接口证明调用次数、300 ms 边界、0/100、错误/无效增量恢复、取消/超时、多组和数量变化、能力/静态缓存；本机持久进程多次刷新与独立公开 SDK 计数对照。跨进程采样区间不同，不要求百分比相同；合成错误不当作真实权限拒绝，多组服务器/热插拔需要后续设备。

依据（2026-10-20 核对）：[GetSystemTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getsystemtimes)、[GetActiveProcessorGroupCount](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getactiveprocessorgroupcount)、[GetActiveProcessorCount](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getactiveprocessorcount)。
