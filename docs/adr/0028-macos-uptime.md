# ADR 0028：macOS uptime 的失败隔离与时间口径

状态：实现 bfd28d5 及 Windows 本机/交叉门禁、干净源码八包/CLI/C/Python 通过；macOS 原生 SDK/链接/采样尚未执行，本地/交叉验证不能证明原生行为，见[本轮记录](../macos-uptime-validation.md)。

核对锁定 sysinfo 0.39.6：Apple `boot_time()` 在 sysctl 失败时返回 0，`uptime()` 用 `difftime(time(NULL), boot_time)` 转 u64。适配层无法区分正常 uptime、启动时间失败后的 epoch 级大数和负差被转换成零。本轮改由现有 MacosBackend 直接采集，保留单元构造，不增加 backend 类型。单独 SysinfoBackend 的 macOS 用户需补 MacosBackend 或使用门面。

来源 Sysctl、能力 Partial。以 `sysctl(CTL_KERN, KERN_BOOTTIME)` 的 timeval 和 `time(NULL)` 的整秒值计算 `now_seconds - boot_seconds`，保持现有正常数据的整秒口径；微秒只检查有效性与两次启动时间的一致性，不参与减法。它是 OS 日历时间推导的粗粒度 uptime，不是单调时钟、仅清醒时长、精确经过时间或启动日期。与减完整微秒再取整可能差一秒；不改变为 Mach 时钟以免静默更换口径。墙钟/OS 调整、睡眠/休眠及跨平台一致性不能由此保证；没有重启/调时实验。

每次动态刷新执行 boot-before → time → boot-after；每个调用前后合作式检查取消/截止时间，无重试循环、旧值或动态基线。boot 两次不同则 TemporarilyUnavailable；两次相同只能检出部分变化，不证明原子快照或无 ABA/时钟调整。静态不调用这些 API，动态不修改静态模型。后续读取可直接恢复，不需 CPU 式预热。

固定栈 timeval，严格检查 sysctl 成功和实际长度等于本地 SDK 类型大小，不消费失败输出；秒非负、微秒在 0..999999。当前时间负值或早于启动秒为 InvalidData；合法零 uptime 保留，不用浮点、饱和或人为最大 uptime 截断。boot epoch 0 在成功且有效的回复中允许，不把它当作 API 失败哨兵。sysctl errno 即时捕获，仅明确 EPERM/EACCES 映射权限拒绝，不猜 sandbox；ENOENT 为 NotPresent、ENOTSUP 为 Unsupported、EINVAL/长度/数据错误为 InvalidData、EINTR/ENOMEM/EBUSY/EAGAIN 为 TemporarilyUnavailable，其余 Unknown。time() 的 -1 哨兵单独返回 Unavailable/Unknown，Apple 文档说明其不保证 errno，不能误读残留权限码。

macOS native 使用已锁定 libc 0.2.190，核对实际依赖及 LP64 timeval/time_t 布局；不从旧缓存版本推断。无需额外资源句柄、堆分配、管理员或私有 API；合作式检查不能强制中断 OS 调用。单位/状态/失败恢复/调用顺序/静态缓存/取消通过注入测试；C SDK 持久探针与 Rust 刷新、native SDK 布局/真实读取测试由 macOS CI 执行。独立进程只比较相应 SDK 区间，不要求数值必须相等，也不返回原始 boot epoch、路径或设备标识。

模型和公共签名、ABI 1、Schema 1、MIT、默认 feature、依赖和两个锁文件不变。开发版迁移：macOS uptime Source 从 Sysinfo 改为 Sysctl，失败返回缺失而非伪成功；回滚需同时恢复 sysinfo 字段。不支持状态经现有合并器可能保留默认 Custom 来源，消费方仍须检查 Availability。

依据（2026-10-22）：Apple [sysctl(3)](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/sysctl.3.html)、[time(3)](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/time.3.html)；sysinfo 0.39.6 `src/unix/apple/system.rs`。只参考接口/语义，不复制系统实现；原生实验结果另记。
