# macOS 整盘容量验证

2026-10-13 实现 [ADR 0015](adr/0015-macos-storage-capacity.md)。公开 IOMedia Whole 分类、Size 字节容量、Source Iokit、能力 Partial；默认不查询 BSD Name、UUID、序列号或属性表，双重授权才读名称。静态缓存、动态不扫描，重建 Hardware 才观察设备变更及访问恢复。

目前 Windows 本机通过 macOS 模块八项纯 mock 测试，以及 macOS arm64 all-target/all-feature Clippy；这些不能证明原生 IOMedia 能读取。原生 CI 将执行真实 Rust CLI/C/Python、CF 类型转换测试及[独立 C SDK 探针](research/iomedia_probe.c)；在拿到证据前，README 当前支持表仍保持 macOS 存储未实现，不以交叉检查宣称已支持。

Rust 限制最多 4096 个媒体对象扫描、默认最多 128/可配 1024 个整盘对象、名称转换 256 bytes；超限拒绝前缀，迭代器失效返回暂不可用。Whole 无法分类时拒绝集合，单项 Size 失败按字段隔离。CF API 的 NULL 没有错误码，返回 Unavailable/Unknown；不能猜测权限或设备不存在。IOIterator/对象 RAII、matching 引用消费和 CFRetained 释放见决策。

macOS crate 新增两项显式 target 依赖，复用锁定 0.3.2 绑定，包版本和许可证未变；Cargo.lock 仅增加依赖边。MIT、公共 API/模型形状、Schema 1、C ABI 1 不变。新读取会让此前 Unsupported 的 macOS storage 返回实际逐字段状态，消费方仍须检查 Availability。

公开 CF/IOKit 在返回属性前可分配内部内存，无法由调用方硬限制；同步调用不能强制终止，沿用 core 调用方超时/有界 worker。Mac 实物磁盘、sandbox 权限、原生长期泄漏/峰值分配、热插拔、失控驱动未验证。C 探针 110 次完整扫描检验普通用户读取与释放路径，不能当作 Rust native heap/leak 证明。Windows/Linux 存储回归需要同轮证据，GPU/移动/Web/MCU 不扩大范围。
