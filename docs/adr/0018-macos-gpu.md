# ADR 0018：macOS Metal 设备名称与显存状态

状态：开发版实现契约，维护者最终公共 API 评审仍待完成。

## 决定

通过公开 Metal `MTLCopyAllDevices` 枚举 Metal 可见设备，读取 `MTLDevice.name`。gpus 能力 Partial，集合与字段来源 AppleApi；不是所有显示控制器或物理显卡数量，不保证包含不支持 Metal 的设备，也不创建默认 GPU 或图形工作负载。

在系统支持公开 `hasUnifiedMemory` 属性时查询内存架构；true 表示全部内存与 CPU 共享，此时 dedicated_memory_bytes 为 NotApplicable/NotPresent，绝不伪造为零。false 或属性不可调用时，当前实现没有独占容量来源，返回 Unsupported/NotSupported。recommendedMaxWorkingSetSize 是性能相关估算，currentAllocatedSize 是进程资源分配量，二者均不映射成显存容量。

依据 Apple [设备枚举](https://developer.apple.com/documentation/metal/mtlcopyalldevices())、[设备名称](https://developer.apple.com/documentation/metal/mtldevice/name)、[统一内存](https://developer.apple.com/documentation/metal/mtldevice/hasunifiedmemory)与[工作集预算](https://developer.apple.com/documentation/metal/mtldevice/recommendedmaxworkingsetsize)。使用 objc2 生态的生成 SDK 绑定，目标仅为 macOS，关闭默认 features 并仅开启必要模块。锁定 objc2 0.6.5、objc2-encode 4.1.0、objc2-foundation/metal 0.3.2；均可选择 MIT，清单见依赖文档，不手写 objc_msgSend 或私有 IOKit 显存属性。

## 所有权、状态与边界

在单次采集 worker 内创建 autorelease pool；数组、设备与字符串由 Retained 所有权包装管理，不跨线程缓存 Objective-C 指针，不把 SDK 类型暴露到公共 API。只读取名称和内存架构，不查询 registryID、设备位置、UUID 或序列号。

读取设备数量后先检查 Options.max_entries（默认 128，最大 1024），超限返回 Unavailable/InvalidData，不返回成功前缀。平台 API 创建的整个数组受系统实现控制，不能声称库在调用前限制了平台内部枚举分配。名称使用固定缓冲区转换，严格验证 UTF-8、非空和控制字符；名称失败只影响该字段。完整空数组为 Available 空集合，不证明机器没有 GPU。

Metal 枚举 API 没有权限错误 out 参数；不通过 errno 或空数组猜测权限拒绝。不虚构 Metal API 未提供的权限错误；绑定层非空契约触发的 Rust panic 沿用 worker Panic 错误隔离。取消和截止时间与字段不可用分开；进程级内存耗尽不承诺恢复。检查围绕平台调用，沿用既有等待超时与 worker 配额，不能强制中止同步驱动或捕获任意 Objective-C/原生异常。

名称和内存架构属于静态缓存，动态刷新不重读，变化或静态失败恢复后需新建 Hardware。FFI NULL options 复用缓存，非 NULL 有效 options 每次独立采集。

## 兼容与验收

沿用 GpuInfo/Observed/Source/ReasonCode，不改 Rust 模型、C ABI 1 或 Schema 1。macOS GPU 从 Unsupported 转为有限 Metal 视图；调用方需处理字段 Unsupported 和 NotApplicable。Windows/Linux 行为不变；移动、Web 和 no_std 不扩展。

通过可替换的私有采集接口测试空集合、上限、异常名称、字段隔离、取消、所有权释放与静态缓存。macOS 原生 CI 验证真实 Metal 读取、C/Python/CLI 与独立 SDK 探针；虚拟 runner 的结果不替代实体 Mac 验证。长期泄漏、热插拔和实体多 GPU 验证仍待后续设备与专项验收。
