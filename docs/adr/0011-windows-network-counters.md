# 0011 Windows 网络累计字节数

日期：2026-10-11。状态：实现决策；[运行验证](../windows-network-validation.md)另列，文档不是设备证据。

## 选择与范围

使用 [GetIfTable](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getiftable) 在调用方提供的有界缓冲区中枚举接口索引，再用 [GetIfEntry2](https://learn.microsoft.com/en-us/windows/win32/api/netioapi/nf-netioapi-getifentry2) 读取固定大小的行。只转换 [MIB_IF_ROW2](https://learn.microsoft.com/en-us/windows/win32/api/netioapi/ns-netioapi-mib_if_row2) 的 InOctets/OutOctets，保留真实 64 位值，不使用 GetIfTable 的 32 位流量字段补算或推测累计值。包括软件回环，数值来自 OS 接口统计，接口移除/重建或计数重置后可能下降；不计算网速，不表示进程流量或物理网卡数量。

Microsoft 文档明确 GetIfTable2 增强枚举还包含逻辑隧道接口，但它由系统分配整个表，调用方不能预先限定分配大小。本轮选择有界路线，`networks` 能力为 **Partial/Win32**：不承诺 GetIfTable2 的完整接口覆盖、多个 compartment 的聚合或条目顺序/索引的稳定身份。GetIfEntry2 最低 API 版本为 Vista，不代表项目已经验证旧 Windows；真实版本见运行报告。

不启用 sysinfo network feature，它会刷新 MAC/IP 并保留接口对象。本轮无新 crate、无第三方版本变化，仅在 Windows target 的 windows-sys 增加 IpHelper/Ndis feature；其他平台不编译这些接口。项目许可证仍 MIT，上游 windows-sys 仍 MIT OR Apache-2.0。

## 隐私边界

原生 API 没有只返回流量的字段选择参数，系统会向临时缓冲写入 MAC、GUID、描述、名称等元数据。实现只访问 GetIfTable 的接口索引，以及 GetIfEntry2 的两个字节计数；不访问、解码、缓存、记录或输出 MAC/GUID/描述，不调用地址枚举 API。默认路径不访问 Alias，返回 Restricted/PrivacyRedacted；只有 include_sensitive 与 caller_authorized 同时开启才解码 Alias。不存在名称时不回退 GUID、索引或 Description。调用方授权不改变 OS 权限。

不能将此实现描述成“标识从未进入进程内存”：临时原始缓冲确实由 OS 写入这些字段，释放内存也不等于安全擦除。该边界与本库不建立标识模型或持久保存标识的行为分别说明。对原始内存有更严格要求的消费者应通过 HardwareBuilder 仅注册符合自身策略的 backend；本轮不新增公共选项。

## 资源、失败与刷新

- 枚举缓冲恰为 MIB_IFTABLE 行偏移 + max_entries × sizeof(MIB_IFROW)（默认 128、最大 1024 条），编译时断言不超过 1 MiB、u32 对齐及字段偏移。一次调用，不使用 OS 返回的所需大小扩大分配或重试。GetIfEntry2 每次只使用一个初始化固定行，Vec 负责释放枚举缓冲，无系统分配表及手动 FreeMibTable。
- 仅在 API 成功、返回大小与行数均在缓冲边界内时读取索引；索引 0 或重复、计数/大小异常、缓冲不足均为 Unavailable/InvalidData，不截断成成功。合法零行是 Available 空集合。采集期间出现的新接口留待下一次刷新；删除导致的逐行失败按字段报告。
- 权限拒绝 Restricted/PermissionDenied，接口不存在 Unavailable/NotPresent，不支持 Unsupported/NotSupported，系统内存不足 Unavailable/TemporarilyUnavailable，其他错误 Unavailable/Unknown。使用 API 返回码而非 GetLastError，不输出原始错误文本。
- 单个接口失败保留该枚举条目，并将它的字段标为缺失，不影响其他接口；集合 Available 仅表示枚举完成，各字段可分别失败。名称无终止符、非法 UTF-16、控制字符或纯空白仅使名称 InvalidData，不影响计数；合法空名称为 NotPresent。
- 每次 refresh 重新枚举和查询，不缓存旧值，也不回退 sysinfo。每个接口的采集时间为其查询完成时刻；集合时间为整次读取结束时刻，不保证所有接口同时采样。
- 枚举前后、每次逐行调用前后及结束时检查截止时间/取消。仍遵循 worker/等待上限；无法强制中断已阻塞的 Windows API，OS 内部临时分配不在调用方缓冲限额的保证范围内。

## 兼容与验证

复用 NetworkInfo / DynamicSnapshot，无公共签名或字段变化，Schema 1、C ABI 1 不变。Windows 网络从 Unsupported 变为 Partial，程序必须继续判断字段 Availability，不能把 Partial 解释为所有接口/字段都可读。macOS 不增加网络实现。

模拟 API 覆盖零/最大计数、失败/恢复、逐接口隔离、资源边界、索引合法性、名称授权及 UTF-16、取消/超时。原生验收要求 Windows CLI/C 实际返回 Win32 计数且名称脱敏；模拟用例不证明真实热插拔、权限拒绝或 API 超时。Linux Miri/ASan 不运行 Windows 原生 unsafe 边界，不能作为该边界的执行证据。
