# 0012 macOS 网络统计与精度限制

日期：2026-10-11。状态：实现决策；原生验证结果另列，不以 SDK 类型或交叉构建代替设备读取。

## 公开 API 与数据含义

使用只读 `sysctl(CTL_NET, PF_ROUTE, 0, AF_LINK, NET_RT_IFLIST2, 0)`，解析 [if_msghdr2](https://developer.apple.com/documentation/kernel/if_msghdr2) 的接口索引及 if_data64 的接收/发送字节字段。包含回环和系统可枚举的虚拟接口，不表示物理网卡数量、网速或进程流量。AF_LINK 过滤 IP 地址记录；不调用 getifaddrs 或私有 NetworkStatistics API。

[Apple XNU 实现](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/net/rtsock.c)在 sysctl_iflist2 对非 platform binary 使用 ALIGN_BYTES；截至本决策日期，该宏按 1024 字节向下取整，并转换为 uint32_t。因此即使传输字段是 64 位，也不能承诺普通应用取得精确或完整 64 位累计量，值可能回绕。能力为 **Partial/Sysctl**，原样保留 OS 返回值，不补算高位、不恢复精度、不规避平台签名规则。此源码观察不等于已证明所有 macOS 版本均采用相同处理；具体系统版本见原生报告。

接口重建、统计重置及上述处理均可能导致数值下降，零是合法系统值。当前 API 没有逐字段精度元数据；消费者应结合平台能力与本契约使用这些计数，不能把它们当作精确计费依据。公共 DTO、Schema 1、C ABI 1 不变。

## 隐私

OS 会向临时路由缓冲写入链路地址和接口名称。实现只读取消息边界、索引和两个计数，不解析、缓存或输出附带 sockaddr/MAC；不能声称标识从未进入进程内存，也不承诺释放即安全擦除。默认不查询或解码名称，返回 Restricted/PrivacyRedacted。只有两个隐私选项同时授权才通过固定 IFNAMSIZ 缓冲调用 if_indextoname；名称失败不影响计数，索引不暴露为身份。枚举与名称查询并非原子操作，条目顺序也不稳定。

## 资源与失败

- 一次 sysctl 调用，调用方预分配 512 KiB，不按 OS 返回大小扩容或重试。OS 内部临时分配不受此限制，阻塞中的系统调用不能强制取消，继续使用核心 worker 与等待上限。
- 最多 8192 条路由消息、max_entries 条接口（默认 128，上限 1024）；越界、截断、版本/类型异常、重复或零索引返回 Unavailable/InvalidData，不截取前缀为成功。成功返回零字节才表示 Available 空集合。
- 安全字节解析不强转结构体、不借用未对齐字段。macOS 编译时断言 libc SDK 的尺寸、字段偏移和消息常量；其他平台运行相同解析器的合成测试及 fuzz。
- 权限拒绝 Restricted/PermissionDenied；不支持 Unsupported/NotSupported；接口不存在 Unavailable/NotPresent；系统缓冲/内存错误 Unavailable/TemporarilyUnavailable；其他错误 Unavailable/Unknown。立即捕获 errno，不输出原始错误文本。缓冲超限的成功响应为 InvalidData。
- 每次刷新重新枚举，失败不保留旧值，不重复读取静态信息。读取前后、解析后及每个名称查询前后检查取消/超时。计数时间为 sysctl 返回时刻，名称时间为该查询返回时刻，集合时间为组装结束时刻。

## 验证要求

合成测试覆盖消息边界、资源上限、未对齐数据、完整 u64 转换、隐私、名称失败隔离与采集失败/恢复。fuzz 只执行纯字节解析，不证明 macOS 原生调用内存安全。原生 macOS CI 必须经 CLI 与 C 各读取非空 Sysctl 统计、名称脱敏，且独立 crate 消费者通过。权限拒绝、热插拔、OS 阻塞和长期资源行为须另有真实测试，不能用模拟用例替代。

不新增第三方依赖，不复制 Apple 源码；沿用 libc 的公开 SDK 绑定。项目 MIT、依赖许可证及锁定版本不变。新增默认关闭的 fuzzing feature 仅供验证，不是稳定消费 API。
