# 0015 macOS 整盘容量

日期：2026-10-13。状态：已实现；源码 99e9479 的原生 CLI/C/Python、普通账户 SDK 探针和三平台 CI 通过，[验收范围另列](../macos-storage-validation.md)，不将虚拟设备或文档推测当作实物 Mac 证明。

## 接口与语义

沿用 [ADR 0013](0013-storage-capacity.md) 的 StorageInfo，枚举公开 IOMedia 对象，仅保留 Whole=true 的整盘对象，Size 是字节数。包括虚拟媒体，不能相加推断物理磁盘总量，也不是分区或文件系统空闲空间。

依据：[Apple IOMedia Whole](https://developer.apple.com/documentation/kernel/kiomediawholekey)、[IOMedia 属性定义](https://github.com/apple-oss-distributions/IOStorageFamily/blob/main/IOMedia.h)、[IOKitLib 的所有权与迭代语义](https://github.com/apple-oss-distributions/IOKitUser/blob/main/IOKitLib.h)。只调用 IOServiceMatching/GetMatchingServices、IOIteratorNext/IsValid、IORegistryEntryCreateCFProperty 和 IOObjectRelease；不打开磁盘、不连接用户客户端、不读取 SMART、不递归搜索、不复制全部属性表。

集合、容量及能力 Source Iokit，能力 Partial：设备、沙盒及当前 registry 可见性不完整，成功空枚举只代表当前可见集合没有条目。不通过 shell/ioreg 命令解析输出。匹配失败有明确 IOReturn 时区分权限、不支持、无设备、暂不可用、超时与未知；单属性 API 返回 NULL 不提供错误码，不猜测无权限或不存在，返回 Unavailable/Unknown。类型不符合公开属性定义则 InvalidData。

## 资源、隐私和生命周期

- 最多扫描 4096 个 IOMedia 对象（包含非整盘），最多保留 max_entries 个整盘（默认 128、最大 1024）。探测一条超限后拒绝整个集合，不返回成功前缀，不无限重试。Whole 缺失/坏类型无法确定整盘成员，拒绝集合；单个 Size 失败保留条目，不影响其他容量及系统字段。
- IOIteratorNext 返回零后检查 IOIteratorIsValid；失效返回 TemporarilyUnavailable，不冒充空集合或完成枚举。先完成成员枚举，再查询容量；不承诺跨属性/设备原子一致性。
- matching 字典的一个引用交给 GetMatchingServices 消费（包括错误路径）；迭代器及每个对象独占持有，RAII 调用 IOObjectRelease。CreateCFProperty 返回值和属性 key 用 CFRetained 自动释放；类型检查后才转换 CFNumber/CFBoolean/CFString，不做未验证指针转换。
- Size 仅接受整数 CFNumber 的精确 i64 转换，再检查非负转为 u64；合法零保留，浮点、负值、失败转换拒绝。超过 i64::MAX 不猜测无符号值。模型仍为 u64，未修改公共 Schema。
- 默认只查询 Whole 和 Size，name Restricted/PrivacyRedacted。双重显式授权后才查询 BSD Name；UTF-16 长度最多 255、UTF-8 输出固定 256 bytes，拒绝空白、控制字符、嵌入 NUL/损坏转换。不请求 UUID、serial、卷标、registry ID 或路径；不把授权名称写入默认诊断报告。
- Rust 集合、字符串转换及循环有界；CoreFoundation/IOKit 可在返回属性或匹配结果前分配内部内存，该公开 API 没有调用方缓冲区配额。固定键/类型检查不能硬限制失控驱动/框架内部分配，不宣称全进程分配硬上限。
- 每次系统调用/迭代/属性查询前后检查上下文；同步调用不能硬中断。沿用 core 等待截止时间和最多 16 worker。首次静态 collect 缓存所有容量/成员/失败及原时间；动态刷新不扫描，权限恢复、扩容、插拔后重建 Hardware。

## 依赖与验收

复用锁文件内的 objc2-core-foundation 0.3.2 和 objc2-io-kit 0.3.2，增加 macOS crate 的显式 target 依赖（关闭 default-features，仅 std/CFBase/CFDictionary/CFNumber/CFString、IOKit libc），不新增包或版本。两者许可证 Zlib OR Apache-2.0 OR MIT，项目仍 MIT；不复制 Apple APSL 实现。公开 Rust 类型/签名、Schema 1、C ABI 1 不变。

要求：纯 mock 验证分类/坏输入/限额/空与失败/隔离/授权/取消/资源释放/静态缓存；macOS 原生 CF 类型测试和公开 SDK C 探针；Rust CLI/C/Python 原生报告至少一项正容量、名称脱敏；三平台源码、隔离八包消费者及既有 fuzz/容器回归。Windows 本机 cross-check 不是 macOS 原生证据。真实 Mac 实物磁盘、沙盒、热插拔、失控驱动及长期 native heap/leak 尚待独立验证。
