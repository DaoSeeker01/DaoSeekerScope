# ADR 0023：Windows 内存刷新与可报告错误的直接读取

状态：开发版实施，本轮验证见[记录](../windows-memory-validation.md)。

锁定的 sysinfo 0.39.6 Windows `refresh_memory_specifics` 每次将 MEMORYSTATUSEX 清零并调用 GlobalMemoryStatusEx，但忽略 BOOL 返回值后复制输出。这里没有证明 Windows 复用了旧内存值；实际缺口是调用成功/错误码被隐藏，适配层只能给 Unknown，不能证明字段对应一次成功读取。CPU 使用率和 macOS 路径另行验收，本轮不修改。

使用公开 GlobalMemoryStatusEx，成功后读取 ullTotalPhys / ullAvailPhys（已经是 bytes，无单位换算）。后者是可立即复用的 standby/free/zero 物理页，不是仅 free、进程可提交内存、交换空间或 Job/cgroup 配额。结果包括所有 NUMA 节点，由 Windows 报告，不等于 DIMM 标称安装容量；installed_bytes 仍走原有独立 API。

新增 `WindowsMemoryBackend::new()` / `Default`，保留现有无状态 `WindowsBackend` 构造方式；门面自动注册两个 Windows backend，字段互不重叠。该 backend 每次动态刷新恰好执行一次新的 API 调用，固定大小栈结构、无标识采集，无旧值回退。sysinfo backend 在 Windows 停止提供总内存/可用内存，避免组合器用替代来源覆盖直接读取失败；单独注册 sysinfo 的 Windows 调用方需改用门面或同时注册 WindowsMemoryBackend。CPU/uptime 继续 sysinfo/Partial。

total_usable_bytes 为静态缓存，包括静态失败；available 每次刷新。成功的总量必须大于零；available 可合法为零，但大于当前总量时仅 available 为 InvalidData。动态总量仅用于校验；与首次成功静态总量不同时 available 为 TemporarilyUnavailable，要求新建 Hardware，不能静默修改静态总量。如果静态总量失败，后续成功动态读取可以恢复 available，但静态失败仍缓存。

BOOL 为零时立刻捕获 GetLastError，绝不读取失败输出。5 对应 Restricted/PermissionDenied；13/87 为 InvalidData；8/14/170/1237 为 TemporarilyUnavailable；其他（含零）为 Unknown。只映射实际返回码，不用通用失败猜沙盒或权限。失败字段无值/时间；成功后新时间只代表 API 调用结束后的观测时刻，不承诺全系统快照原子性。前后检查取消/超时；无法强制终止内核调用，不承诺 OS 内部分配上限。

能力为 Supported/Win32（实现支持，不保证本次可读），采集后逐字段能力反映失败。公共模型、核心 API、C ABI 1、Schema 1、依赖/feature 与 MIT 不变；Windows 两个字段的来源和失败行为改变，是开发版行为迁移。回滚需同步恢复 Windows sysinfo 字段，不能只移除直接 backend。

验收包括可注入接口证明逐次调用/错误恢复、合法零/异常数值、静态缓存/总量变化、取消和失败字段隔离；本机公开 C SDK 探针和独立 Rust 持久进程在有限 64 MiB 内存分配/释放期间刷新。系统内存会受其他进程影响，不要求相邻读数相等或固定下降，不将压力实验当物理内存认证。合成错误不冒充真实权限拒绝；无需管理员或故障注入到系统 API。

官方依据：[GlobalMemoryStatusEx](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex)、[MEMORYSTATUSEX](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-memorystatusex)，2026-10-19 核对。
