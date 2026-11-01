# 0049 macOS 内置电池

日期：2026-11-01。状态：实施决定，原生与设备结果待验证。

在现有 MacosBackend 的动态刷新中增加 `batteries`，能力为 Partial、来源为 Iokit。只接受公开 IOPowerSources 接口中类型为 InternalBattery、Is Present 为真的条目；UPS 与明确不存在的电池跳过。成功返回空列表只说明本次 API 视图没有可返回的条目，不证明机器物理上没有电池。未知分类、损坏枚举或超过 256 个电源条目使集合不可用；已识别电池的属性失败按字段隔离。

依据 Apple 公开的 [IOPowerSources.h](https://github.com/apple-oss-distributions/IOKitUser/blob/main/ps.subproj/IOPowerSources.h) 和 [IOPSKeys.h](https://github.com/apple-oss-distributions/IOKitUser/blob/main/ps.subproj/IOPSKeys.h)。电量使用同一描述中的 Current Capacity / Max Capacity × 100；二者必须是整数，最大值大于零，当前值在零至最大值之间，不假设最大值总是 100。供电状态仅把 AC Power 映射为 true、Battery Power 映射为 false；Off Line 暂不可用，不根据充电状态或 USB 连接猜测。

沿用现有 BatteryInfo、JSON 和 C ABI，不增加字段。每次动态刷新获取一次新的 API 快照，静态缓存不重读。只访问分类、存在、电量和供电状态键，不提取名称、序列号、适配器标识、循环次数或健康推断。调用前后及枚举循环检查取消/期限，输出受 Options.max_entries 限制；不能强行中止系统调用，既有 worker 和共享库生命周期限制不变。

沿用已锁定的 objc2-io-kit 0.3.2，启用其 ps 模块，不新增包或升级依赖。Copy 结果由 CFRetained 持有；Get 描述的绑定会额外 retain，再由 Rust 自动释放。列表先于不透明快照释放，借用只在其所有者存活期间使用。不读取不透明快照的内部布局，不用私有 API，不注册通知、runloop 或后台服务。

验收包括纯 Rust 的单位、缺失/错误状态、UPS/不存在过滤、真实零值、刷新、静态缓存、上限及取消回归；macOS 原生 CF 类型与公开 SDK 对照另行执行。CI 若只有空列表，只验收空视图路径，真实电池读数和 AC 切换留待实体 Mac，不把合成输入写成设备成功。

Rust API、公开 features、MIT、C ABI 1 与硬件 Schema 1 不变；macOS backend 目标依赖的 feature 增加 ps，需检查实际依赖闭包与许可材料。原有 macOS 分发缺口不因本轮功能而放行。回退可移除动态电池路由与能力声明，恢复原 Unsupported，历史证据保留。
