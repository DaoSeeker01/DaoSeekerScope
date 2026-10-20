# 0002 sysinfo 适配层

日期：2026-10-08。调研使用 cargo info、下载的 crate 源码与 [0.39.6 官方文档](https://docs.rs/sysinfo/0.39.6/sysinfo/)。当前版本 0.39.6、MIT、MSRV 1.95，维护者 Guillaume Gomez；本机 Rust 1.96.0。近期版本与迁移文档说明仍维护，但不是维护 SLA。锁精确版本，Cargo.lock 固定传递依赖，许可证清单从 cargo metadata 生成。

system feature 提供 CPU、memory、OS、uptime；disk/network/component 可扩展但本切片不开启。关闭 default features，不开 process refresh、user、rayon、WMI component、disk/network 枚举，避免不必要隐私/资源路径。开启 apple-app-store（蕴含 apple-sandbox），不使用私有 Apple API。公共门面仅有自有 DTO；sysinfo 类型不导出。

真实探针位于 docs/research/probe；先运行 Windows CPU/memory/OS 最小读取，再实现公共类型。Linux/macOS 文档覆盖不能代替本项目运行证据。CPU 占用率需要两次、至少 MINIMUM_CPU_UPDATE_INTERVAL 间隔；首次与过早刷新返回 Unavailable/TemporarilyUnavailable，禁止把初始化 0 当测量。总内存 0、空 CPU brand、0 核数映射 unavailable，不以假 0 包装成功；uptime 合法 0 不视为失败，但上游无法报告读取错误，本字段能力为 Partial。

维护风险：上游整数/空值 API 隐藏权限与临时读取错误；因此这些能力为 Partial、失败 Unknown，不能猜 PermissionDenied。sysinfo 内部 OS 读取和分配不可被本库强制取消；工作线程只限制调用方等待与并发，本库不承诺硬终止或 sysinfo 内部内存上限。增强层只使用固定大小/有界读取。替换路线：Windows API、Linux procfs、macOS sysctl 定向读取与独立测试；升级需锁文件、Schema、单位、CPU 采样与平台矩阵回归。

sysinfo字段observed_at指适配层读值的时间，无法证明上游内部每次刷新都取得新OS样本（刷新失败可能保留内部缓存）；Partial不承诺设备原始采样时刻或失败后的新鲜度。需要严格新鲜度与错误状态的后续切片应改为可报告错误的直接平台查询。

2026-10-10决策增补：Linux CPU使用率移至LinuxBackend直接有界读取/proc/stat，来源procfs、Supported，失败清基线并要求新的300ms有效采样对。非root容器已复现旧sysinfo路径在输入变空后保留50%并打新时间；因此Linux SysinfoBackend停止提供CPU使用率，避免旧值作为通用fallback掩盖增强层失败。静态CPU仍sysinfo，内存/uptime及Windows/macOS动态路径不变。门面签名、Schema/ABI仍1；Linux单独SysinfoBackend消费者应改用门面或同时注册LinuxBackend。完整语义、回归与剩余风险见[CPU刷新切片](../cpu-refresh-validation.md)。

## 2026-10-10 Linux 内存与 uptime 决策补充

内存与uptime由LinuxBackend直接有界procfs读取，SysinfoBackend在Linux不再提供总内存/可用内存/uptime；门面自动组合，单独sysinfo消费者需迁移注册。上游缓存及静默回退实查、字段级错误、合法零值、旧内核缺MemAvailable、总量变化与静态缓存契约见[内存刷新报告](../memory-refresh-validation.md)。公共类型/feature/依赖/ABI1/Schema1不变。Windows/macOS保持Partial路线。旧源码回归已失败，新源码6d0a377的运行38008554490全部8任务成功，原生与容器报告单列归档，不以文档替代验收。

2026-10-19 Windows 内存增量：停止在 SysinfoBackend 提供 total_usable_bytes / memory_available_bytes，由门面注册的 WindowsMemoryBackend 直接检查 GlobalMemoryStatusEx 返回值和错误码。上游 Windows 代码实际为每次清零后忽略 BOOL，并非本轮证明了旧值缓存；CPU/uptime 与 macOS 动态路径仍 Partial、待独立验收。单独 sysinfo 消费者须注册新 backend 或使用门面；见 [ADR 0023](0023-windows-memory.md) 和[验证](../windows-memory-validation.md)。

2026-10-20 Windows CPU 增量：SysinfoBackend 停止提供 Windows CPU 用量，由门面自动注册 WindowsCpuBackend 直接检查 GetSystemTimes。首样本/过早刷新暂不可用，读取失败清基线；只覆盖单活动处理器组，多组明确不支持。静态 CPU 与 Windows uptime 不变；包/锁/ABI1/Schema1 不变，Windows 绑定增加 Threading feature。见 [ADR 0024](0024-windows-cpu.md) 和[本轮验证](../windows-cpu-validation.md)。
