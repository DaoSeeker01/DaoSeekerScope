# 0010 Linux 网络累计字节数

日期：2026-10-11。状态：本轮实现决策；运行验证另见[验收记录](../network-validation.md)。

## 来源与范围

LinuxBackend 每次动态刷新只读 `/proc/net/dev`，返回当前进程网络命名空间内各接口的累计接收/发送字节数，包含回环和虚拟接口。依据 [Linux 内核统计文档](https://docs.kernel.org/networking/statistics.html)，这是接口统计，不是进程流量、网速、物理网卡清单或机器终身累计量。接口删除、重建及计数器重置可能使数值下降，不保留旧值，也不计算差分。

不直接启用 sysinfo 0.39.6 network feature：源码中三个桌面实现的 refresh 都调用 `refresh_networks_addresses`，同时查询 MAC/IP。Linux disk 枚举还扫描 `/dev/disk/by-id`；这些路径需另行解决默认不读取稳定标识的问题。本轮不增加磁盘或 Windows/macOS 网络支持，不改变依赖/feature。

## 契约

- 复用 `DynamicSnapshot.networks` / `NetworkInfo`，公共模型形状、JSON Schema 1、C ABI 1 不变。`networks` 能力为 Supported/Procfs，仅表示此读取路径的实现能力。
- `received_bytes` / `transmitted_bytes` 为内核累计无符号字节数；合法 0 与 u64 最大值保留。采集时间是本次读取完成时刻。
- 接口名称可能包含自定义设备标识，默认 Restricted/PrivacyRedacted。只有显式请求且调用方声明获授权才输出；Core 对自定义 backend 同样执行该脱敏规则。不查询 MAC、IP、稳定设备 ID。
- 每次最多读取 512 KiB + 1 探测字节；最多 `Options.max_entries` 条（默认 128、最大 1024），不截断后宣称完整成功。超限返回 Unavailable/InvalidData，与现有集合上限规则一致。
- 严格验证两行列头、16 列、UTF-8、长度不超过 15 字节的接口名、重复名和完整结尾换行。无法确定行身份时整个集合 InvalidData；可确定接口且某个字节字段损坏时只拒绝该字段；列数损坏时该行两个字段 InvalidData，其余接口仍保留。
- 已成功读取的合法列头且没有接口行是 Available 空集合；空文件/缺少列头不是空集合。权限拒绝 Restricted/PermissionDenied，路径不存在 Unavailable/NotPresent，其余 I/O 错误 Unavailable/Unknown。失败后不回退至 sysinfo 或上次缓存。
- 读取前后检查取消/截止时间。普通 procfs 读取有字节上限；现有线程等待边界不能强行中断被异常挂载替换的阻塞文件读取。

## 兼容与验证

`NetworkInfo` 字段含义从未实现变为明确累计字节语义，不新增字段。接口名称默认脱敏也适用于注入的自定义 backend；此前依赖默认输出名称的消费者需明确设置 PrivacyOptions。受限环境可返回字段错误，不能把 Supported 当成读取成功。

单元/fixture 回归覆盖损坏字段隔离、头部/列数、超限、重复名、I/O 错误、清除旧值、热插拔、隐私与 JSON 往返；添加独立 fuzz 目标。真实 Linux 读取需独立运行，Windows 上的 fixture 不算 Linux 真机证据。
