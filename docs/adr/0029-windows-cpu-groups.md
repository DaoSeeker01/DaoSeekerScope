# ADR 0029：Windows 多处理器组的 CPU 时间采样

状态：已实现并完成 Windows 本地门禁；三平台 CI 与真实多组硬件尚未验证，验收边界见[记录](../windows-cpu-groups-validation.md)。

GetSystemTimes 在多组系统仅返回调用线程主组的时间。保持单组现有路径；多组使用新建的专用 scoped 采样线程，读取 GetLogicalProcessorInformationEx(RelationGroup) 的活动掩码，逐组 SetThreadGroupAffinity(GetCurrentThread()) 后读取 GetSystemTimes，最后复核完整活动拓扑。调用线程不改变亲和性；专用线程退出即回收，不尝试把 Windows 11 默认跨组亲和性错误地恢复成单组掩码。不使用私有 NT 查询、PDH/频率周期换算、管理员或重启设置。

固定上限 16 活动组、每组 64 位掩码（至多 1024 logical processors）、1024-byte 拓扑缓冲。组掩码 popcount 必须等于报告的活动数，活动数不超过最大数，记录长度/类型/数组容量严格验证；只消费成功 API 的输出。越界不截断成功，不无界分配。多组采集只在 64 位进程启用；32 位多组明确不支持，普通单组路径不变。逐组使用实际活动 mask，不能根据处理器数量假设低位连续。

保留每组 idle/kernel/user 累积值和 mask。两帧拓扑一致后逐组 checked 相减，任何组回退、idle>kernel 或失败都丢弃全帧并清基线；不能先求累积总和以掩盖某组计数复位。kernel 已含 idle。用 u128 累加各组差值，计算 `100 * (sum(kernel_delta + user_delta - idle_delta) / sum(kernel_delta + user_delta))`，不平均各组百分比。异步顺序的组读取不是原子全机快照，不作频率归一化或 Task Manager 数值等同承诺；能力保持 Partial、来源 Win32。

首次/失败恢复需新 300 ms 有效采样对；快速轮询保留有效基线但不返回旧百分比，零/100% 合法。组数量、mask 或处理器数变化重新预热；同 mask 的 ABA 仍不可检出。取消/截止时间检查包围每个 native 操作，任何一个组失败不发布子集。scoped helper 无后台脱离存活，父采样线程等待退出；合作式取消不能中断阻塞 OS 调用。core 既有最多 16 个工作线程限额包含等待 helper 的工作线程，因此该入口最多再产生每任务一个 helper；不声称额外线程无成本或已测峰值内存。

保持 WindowsCpuBackend::new()/Default、门面注册、既有公共消费模型/签名、C ABI 1、Schema 1 和 MIT。Windows crate 新增默认关闭的 `fuzzing` feature，仅开放隐藏的不稳定纯解析测试入口；fuzz workspace 增加该直接依赖边，fuzz/Cargo.lock 只增加该边，第三方包/版本/checksum 与根 Cargo.lock 不变。多组字段由 Unsupported 转为尝试采集；若受 Job/进程约束不能切换组，按真实 API 错误降级，不绕过限制。只切换自有线程，不修改进程或调用者线程的亲和性。

验证包含多组加权、组内回退、非连续 mask、拓扑损坏/变化、失败短路、取消、线程回收和调用线程亲和性检查。单组本机可通过内部原生测试强制执行同一组枚举/helper 路径，独立 C SDK 验证；它不证明真实跨组切换成功。真实多组机器缺少时明确留待验证，不修改启动配置来伪造多组。

依据（2026-10-24）：Microsoft [GetSystemTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getsystemtimes)、[SetThreadGroupAffinity](https://learn.microsoft.com/en-us/windows/win32/api/processtopologyapi/nf-processtopologyapi-setthreadgroupaffinity)、[GROUP_RELATIONSHIP](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-group_relationship)、[PROCESSOR_GROUP_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-processor_group_info)。锁定 windows-sys 0.61.2 已有 SystemInformation/Threading 绑定；文档和编译不是多组真机证据。
