# ADR 0027：Windows uptime 的直接来源与刷新契约

状态：已实现并通过 Windows x64 本机门禁与 SDK 夹取；本机验证见 [验收记录](../windows-uptime-validation.md)，三平台 CI 尚未执行。

核对 Cargo.lock 的 sysinfo 0.39.6：Windows `System::uptime()` 每次调用 `GetTickCount64() / 1000`。原实现没有缓存或隐藏失败，本轮不把迁移描述为修复已知错误。将相同读取移入现有 WindowsBackend，来源由 Sysinfo 改为 Win32，能力仍为 Partial；不新增 backend 类型、模型或默认 feature。单独 SysinfoBackend 不再提供 Windows uptime，用户需注册 WindowsBackend 或使用门面。

`runtime.uptime_seconds` 是 GetTickCount64 的毫秒数向下取整为秒，包含睡眠/休眠时间，独立于墙钟调整；不是仅工作状态时长、启动日期或应用运行时间。零为合法值，u64 全域可安全除以 1000，不进行 u32 截断、浮点转换或饱和运算。约 10–16 ms 的系统计时粒度和秒取整允许连续相同值。Windows checked build 的约 49 天偏移由 OS 决定，不尝试猜测或修正。因此保持 Partial，不承诺精确启动经过时间、跨机器/跨平台完全一致、墙钟反推或重启/快速启动行为。

API 无失败返回约定，不读取无关 GetLastError，也不制造 PermissionDenied、Sandbox 或零值失败。取消/截止时间在调用前后检查；若检查失败，返回结构化错误，不发布该次样本。采集时间在成功调用后取得，仅代表本次调用完成；无动态值缓存或基线，静态采集不调用该计时 API。保留 WindowsBackend 单元构造及现有组合优先级。合作式检查不能强制中断阻塞的 OS 调用。

验证使用可注入调用计数/边界/取消测试、真实 Windows SDK C 探针和持久 Rust 进程的 SDK 前后夹取。不能要求短间隔值严格递增；延迟跨秒后检查增长，不以 CPU 使用量或墙钟计算 uptime。无需管理员、压力、系统睡眠、重启、API 拦截或设备标识。睡眠/休眠、checked kernel、快速启动及长期运行只作文档边界，未实验验证。

项目 MIT、ABI 1、Schema 1、锁文件及依赖 feature 不变。开发版行为迁移只涉及 Windows uptime 来源和独立 sysinfo backend 能力。

依据（2026-10-22）：Microsoft [GetTickCount64](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-gettickcount64)、[Windows Time](https://learn.microsoft.com/en-us/windows/win32/sysinfo/windows-time)；锁定 sysinfo 0.39.6 `src/windows/system.rs` 的 uptime 实现。文档依据不替代实际运行证据。
