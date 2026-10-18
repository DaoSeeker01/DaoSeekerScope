# ADR 0021：macOS 活动显示视图与模式像素

状态：开发版有限实现，本轮三平台原生 CI 与独立 C SDK 状态对照已完成，见[验证记录](../macos-display-validation.md)；实体 Mac 验证按设备安排延期。

使用公开 Core Graphics CGGetActiveDisplayList，只返回 active-for-drawing 视图。硬件镜像可能只列主显示，软件镜像可列多个活动对象；不把条目数称为物理显示器数量。能力 Partial/AppleApi。通过 CGDisplayCopyDisplayMode 和 CGDisplayModeGetPixelWidth/Height 取得当前模式的像素宽高，不使用 CGDisplayBounds、逻辑 width/height、毫米尺寸或候选模式来填充。它不是面板原生分辨率、Windows 的信号 activeSize 或最终物理扫描输出保证。

名称没有本切片认可的来源，保持 Unsupported/NotSupported、Source AppleApi，不用数字 display ID 或 Generic Monitor 填充。不查询名称、EDID、序列号、UUID、厂商/产品 ID；隐私授权不扩大本轮采集范围。不捕获屏幕、修改模式、请求屏幕录制/辅助功能权限或使用私有 API。

原生查询每次使用固定 1025 个 u32 槽位，返回计数先验证再访问；1025 条拒绝，防止把截断的 1024 条当完整结果。另受 Options.max_entries 默认 128/最大 1024 限制；零 ID、重复 ID、无效计数和超限拒绝整个集合，不返回成功前缀。即使空集合也实际查询并复核。前后列表比较集合，顺序改变可接受，拓扑变化最多尝试三轮，耗尽为 TemporarilyUnavailable；不保证跨模式/列表原子性，也不能排除 ABA 或同一 ID 的模式变化。

当前模式 Copy 返回 NULL 不能诊断权限；对于已枚举 ID，尺寸对为 Unavailable/TemporarilyUnavailable。零或超过 u32 的像素对为 InvalidData；不补零、不猜默认分辨率。一个对象尺寸失败不丢失其他条目，宽高成对使用同一时间/状态。枚举失败按 CGError 映射：IllegalArgument/RangeCheck/TypeCheck 为 InvalidData，InvalidConnection/InvalidContext/CannotComplete/InvalidOperation 为 TemporarilyUnavailable，NotImplemented 为 Unsupported，NoneAvailable 为 Unavailable/NotPresent，其余 Unknown。通用 WindowServer 错误不推断为 PermissionDenied/Sandbox，绝不使用 errno/GetLastError。数值映射由独立 C SDK static_assert 校验。

无新 Rust 包、feature 或锁变化。只有 macOS 编译链接 CoreGraphics 系统 framework，五个私有 C 声明只使用 u32/i32/size_t/opaque pointer，不暴露原生类型。Copy 模式对象以 NonNull RAII 成对 Release，取消检查位于原生调用前后，Mode 不进入缓存或跨线程；不在 Rust 布局中模拟原生结构。接口与像素转换采用可注入纯 Rust 内部 Api 验证，无 unsafe 扩散到 core。

成功、空集合和失败均静态缓存，refresh_dynamic 不重扫；模式/连接变化后新建 Hardware。同步 Core Graphics/WindowServer 的阻塞不能强制中止，库限制等待和后续调用，不能限制 OS 内部分配。Rust 模型/签名、C ABI 1、Schema 1 形状不变；只补充已有像素字段的平台语义。CLI 复用 --json，不新增命令变体。

验收包括纯接口的空集合、计数/限额、错误映射、成对尺寸、字段隔离、三次拓扑重试、取消与静态缓存；独立 C SDK 探针、三平台构建/CLI/C/Python、Schema、八包、fuzz/内存回归。C 探针仅输出数量、像素和缺失状态，不输出 ID。CI 无活动对象或无模式时如实记录，不冒充尺寸阳性；实体 Retina/缩放、多屏、镜像、热插拔、远程/沙盒、峰值内存和长期原生泄漏仍待验证。

统一组合器可能保留默认 Unsupported/Custom（例如原生返回 NotImplemented 时）；该状态没有列表/尺寸值，不代表成功调用或可用设备。守卫仅允许这种严格的缺失状态，拒绝 Available/Custom、伪造零值及错误元数据；不修改组合器优先级或公共 API。

## 官方依据

- [活动显示列表和镜像语义](https://developer.apple.com/documentation/coregraphics/cggetactivedisplaylist(_:_:_:))。
- [当前模式 Copy/Release 所有权](https://developer.apple.com/documentation/coregraphics/cgdisplaycopydisplaymode(_:))。
- [pixelWidth](https://developer.apple.com/documentation/coregraphics/cgdisplaymode/pixelwidth)、[pixelHeight](https://developer.apple.com/documentation/coregraphics/cgdisplaymode/pixelheight)。
- [CGError](https://developer.apple.com/documentation/coregraphics/cgerror) 与 [WindowServer 连接错误](https://developer.apple.com/documentation/coregraphics/cgerror/invalidconnection)。

2026-10-18 从 Apple 官方 Markdown 读取并核对接口契约；不复制 Apple 实现代码，项目仍 MIT。
