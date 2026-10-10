# 0007 Linux power_supply 受控电池枚举

2026-10-10开发切片决策，正式发布评审仍待完成。沿用Schema1的BatteryInfo/Observed<Vec<BatteryInfo>>，不增加标识字段、crate、依赖、feature或ABI版本。当前只扩展LinuxBackend；Windows/macOS路线不变。

## 来源与字段

固定读取/sys/class/power_supply，每次动态刷新重新枚举，不缓存旧电量或成员。只读type、Battery的present/capacity、Mains的online；不打开uevent、serial_number、model_name、manufacturer、device或其他标识。class设备目录可为内核symlink，属性只接受普通文件；不递归、不接受生产自定义路径、不运行外部命令。每字段128字节上限，完整目录最多256条（第257条只用于判定超限）；电池条目另受Options.max_entries约束。目录名只用于有界排序，不输出，不作为稳定电池身份；索引跨热插拔不保证一致。

Battery/capacity严格ASCII整数0..100，无能量/电荷比值估算。Battery/present接受0/1；0跳过，属性不存在按ABI的默认present语义保留；权限失败或损坏不能当成无电池。Mains/online仅接受0/1；至少一个已知1则AC为true，所有Mains已知0才为false，否则返回明确失败原因；没有Mains为Unavailable/NotPresent。USB/Wireless/UPS不被当成Mains，Charging/Discharging/Full不能证明AC状态。不读取status或推断AC=false。

依据：[Linux power_supply ABI](https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-class-power)、[power_supply class](https://docs.kernel.org/power/power_supply_class.html)，2026-10-10核验。文档只确定类型/present/capacity语义，不替代设备实验。Mains聚合是本backend对on_ac_power的明确策略，不声称完整USB电源拓扑；能力声明Partial。

## 状态与边界

完整扫描可确定没有Battery（或均present=0）才为Available空集合、SourceSysfs及采集时间。目录不存在为Unavailable/NotPresent；目录/分类或present权限拒绝为Restricted/PermissionDenied；超限、异常类型文本/数值为Unavailable/InvalidData。分类不完整无法用当前集合模型表达未知成员，故丢弃已有前缀，整集合不可用而不伪造完整性；仅该集合失败，其他CPU/内存/系统字段继续采集。capacity/online字段失败独立于集合存在与其他电池，不导致快照失败。

Mains有读错而另一个已知online=1时仍可证明true；没有已知1时保留首个确定性错误（目录排序后顺序）。所有Unavailable/Restricted字段value/time均为空。新鲜度是每次独立读取的观测，不是内核原子快照；设备可能在读取中消失，下一刷新重新枚举。字段与sysfs结果不能当作容器cgroup、电池健康/寿命或充电控制信息。

上下文在枚举和每次metadata/open/read前后检查，使用现有有界worker等待/协作取消；无法强杀阻塞驱动调用，metadata检查也不消除本机恶意文件替换竞态。边界只读取固定系统路径的受信任内核文件，不作为任意不可信目录安全解析器。选择原始小范围sysfs避免udev/DBus守护进程与额外依赖；可回滚LinuxBackend电池接入，消费者类型不变。

验收要求：同生产实现的有界属性解析负面/变异fuzz，动态增删/错误/恢复的Rust测试，非root容器生产CLI对固定路径的权限与资源上限测试，Schema/JSON/CLI/FFI回归、三平台构建及实际最小读取。合成fixture不是实际笔记本电池认证；托管runner无电池只证明枚举结果，必须单独记录。性能、长期fuzz、真实电池设备和新平台未运行时保持未验证。
