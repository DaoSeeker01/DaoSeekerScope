# 0003 能力、错误、组合和资源

能力查询描述 backend 当前实现的字段（稳定点分隔 field ID），不是机器上必然存在设备。Supported=实现来源明确且有结构化错误；Partial=只能返回来源的一部分或上游隐去错误；Restricted=当前隐私策略禁止；Unsupported=未实现；NotApplicable=明确无此语义。字段状态区分：NotPresent 对应 Unavailable（型号/路径不存在）或 NotApplicable（Windows 明确无电池），PermissionDenied 对应 Restricted，故障/坏数据/超时对应 Unavailable。集合成功枚举无条目可以 Available([])，无法枚举则不能成功空列表。结构化失败不携带系统原始错误/路径。

collect 前 capabilities 为当前编译实现与隐私策略；成功 collect 后，快照及 Hardware 查询以实际来源更新，并把本次 Restricted/NotApplicable 原因反映到对应能力。CLI capabilities 执行一次采集获得当前限制。动态刷新可更新动态限制；静态失败随缓存保留，重建 Hardware 才重新查询，不承诺权限变化自动失效。

注册顺序同级后注册覆盖，priority 更高覆盖；Available 可覆盖已有 Available 并记录字段、前后 Source、priority；增强层缺失不覆盖已有有效值；隐私 Restricted 始终阻止敏感值，即使自定义 backend 违规。Capabilities 同字段最高优先级；遇到增强缺失仍保留实际字段来源。Backend panic 被隔离，添加健康 issue；所有 backend 均失败则 BackendFailure。HardwareBuilder::with_backend<B> 提供泛型注入。collect 与 refresh_dynamic 通过同一个缓存 worker，工作超时后缓存仅在完整成功和未取消时提交。

Options：timeout 1..60000ms、条目上限 1..1024、字符串/单文件上限 4096bytes。每 Hardware 一个线程、全进程最多16个存活 worker，队列容量1；调用并发返回 Busy。collect_with/refresh_dynamic_with 支持调用方 CancelToken，平台循环逐次检查 deadline。调用方等待有硬上限；超时不杀死 Rust 线程/OS 调用，正在阻塞的 worker 继续占额度，不能用无限重新 spawn 绕过。Drop 不 join 阻塞线程。需要强终止的消费者应使用独立进程；未来 WMI/设备扫描必须进程隔离或原生可取消 API。当前方案有资源边界但不是硬取消完整 DoD。

敏感采集要求 include_sensitive 与 caller_authorized 同时 true；后者是调用方声明，不是本库获取 OS 授权。默认不读取序列号。自定义 Backend 被信任且需遵守契约；出口再次脱敏。日志不保存完整原始错误。

2026-10-31 取消检查修正：每次 backend 返回后，先检查调用上下文，再处理返回值或记录 backend 错误。这样，调用期间发生的取消/到期不会因最后一个 backend 失败而被合并为 BackendFailure。正常故障隔离、缓存提交条件及原生阻塞调用的限制不变，见[本轮审查](../project-review-2026-10-31.md)。

2026-10-11 审查修正：增强层 Unsupported 不覆盖已注册的实现能力；出现 Available 而声明为 Unsupported/Restricted/NotApplicable 的字段，能力降为 Partial 并采用实际来源。冲突只比较值，不把时间戳或来源变化当作值冲突。核心出口对零核数/零容量及可用内存大于缓存总量按字段返回 InvalidData；诊断 backend 名称按 UTF-8 字节限制且拒绝控制字符。签名、布局和 ABI/Schema 主版本不变。见[检查报告](../project-review-2026-10-11.md)。
