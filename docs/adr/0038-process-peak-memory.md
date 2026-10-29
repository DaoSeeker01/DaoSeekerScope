# ADR 0038：C ABI 进程峰值内存基线

状态：Windows 本机与三平台原生 CI 40669330970 校准、采样及既有门禁通过，结果见[性能报告](../benchmarks.md)。

## 为什么增加这个检查

现有 Rust benchmark 测量采集和刷新耗时，没有进程内存数据。为 C/Python 集成评估资源开销，需要可重复运行的本机消费者，同时避免将整个进程的内存误称为库的分配量。

## 决定

增加开发用 C11 探针，链接 release C ABI，不修改库、头文件、依赖或 feature。用独立进程执行三种固定规模的工作：

- `calibrate`：分配并逐页写入 64 MiB，记录写入前、写入后和释放后的峰值。它不调用采集接口。
- `cached`：传入 NULL options，首次调用后继续复用默认采集器；累计记录 1、100、300 次 collect/free。
- `fresh`：传入显式 options，每次创建采集器；累计记录 1、10、30 次 collect/free。

两种采集均使用 2000 ms 超时、max_entries=128、默认脱敏；逐次检查成功状态、buffer 范围和释放清零。JSON 内容与默认隐私另由同构建 CLI 的 Schema/语义检查和现有原生 C/Python 门禁验证。每批耗时包含 collect、JSON 序列化和 free，第二批以后不包含此前调用的耗时。

Windows 读取 `PeakWorkingSetSize`（字节）；Linux 读取 `RUSAGE_SELF.ru_maxrss`（KiB，乘 1024）；Darwin 读取 `ru_maxrss`（字节）。保留原值、单位与换算结果。三个进程互不继承校准分配；进程内峰值不可重置，释放后峰值也不会下降。

校准要求峰值增加 32–128 MiB：允许初始峰值和 OS 噪声，但拒绝没有明显增加或多/少乘 1024 的结果。校准失败表示本轮测量未被接受，不能降低检查标准或改写为通过。该区间不是分配器精度保证。

Python 入口要求干净源码；构建前后核对 HEAD/工作区，并核对探针、共享库和 CLI 的 SHA-256。先作废旧成功报告，失败或中断不得保留旧 `passed`。每个测量进程最多等待 180 秒，CI 步骤最多 10 分钟；探针不输出快照、原始系统错误或设备标识。

## 结果的边界

报告含 C 进程、动态库、工作线程、缓存和 OS 计账开销。它不是 allocator profiling、瞬时 RSS、持续增长检测、真实设备规模或长期无泄漏证明。Linux 资源计账可跨 execve 保留，启动阶段峰值会遮住采集阶段较小变化；基线不增加不能证明零分配，该初始样本未隔离启动阶段；后续方案及验收见 [ADR 0039](0039-linux-peak-launch-isolation.md)。不同 OS 的内存口径和运行环境不完全一致，不作跨平台性能排名；长期 fuzz 和更多资源故障仍单独跟踪。

## 官方依据

- [Microsoft PROCESS_MEMORY_COUNTERS](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters)：峰值工作集单位。
- [Linux man-pages getrusage](https://man7.org/linux/man-pages/man2/getrusage.2.html)：Linux 的 KiB 单位与 SELF 范围。
- [Apple 当前 XNU 手册源码](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/man/man2/getrusage.2)：Darwin 的字节单位。旧 [Apple 归档页](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/getrusage.2.html)仍写 KB，不能直接照搬；本轮原生校准用于检验实际口径。
