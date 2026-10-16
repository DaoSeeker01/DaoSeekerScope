# Windows 活动显示路径验证

2026-10-16 实现 [ADR 0019](adr/0019-windows-display.md)，源码 `7bd5b197b11d2c7b1010391f902b61e9a3af7ee3`。只读取当前活动路径，不枚举所有物理显示器；宽高为目标信号 activeSize 的像素数，不是原生面板/首选分辨率或 DPI 逻辑坐标。名称只采用带 EDID 友好名称标志的系统字符串，不使用设备路径或 Generic Monitor 填充。

## 已验证

- Windows x64 `pwsh -NoProfile -File scripts/check.ps1 -Cross`：fmt、workspace/all-target/all-feature Clippy、168 项 Rust 测试（含 doctest）、core/门面 no-default-features、doc 拒绝警告、CLI/FFI 构建及 Linux x64/macOS ARM64 cross-check 通过。
- Ruff format/check、mypy --no-incremental（28 文件）、75 项 Python unittest、Schema generated/golden/不变量与项目链接检查通过。
- 10 项新增纯 Rust 测试验证空集合、计数上限、返回计数、三次缓冲竞争重试、虚拟模式高 16 位索引、模式类型/目标匹配、非零尺寸、名称 UTF-16、重复目标、字段失败隔离、取消/截止时间及静态成功/失败缓存。另增 CLI JSON 集成测试和 5 项 Python 负向守卫测试。
- 重建 C ABI 示例并通过 collect/free、释放后清零、空释放及陈旧 buffer 拒绝检查；干净源码 native smoke 五组检查、15 个进程均 passed，包括 Python 默认 100 次 collect/free。
- 本机 Rust CLI 与 C ABI JSON 各读取一条活动路径、1920×1080 信号活动像素；来源 Win32，值/状态/时间完整。名称 Unavailable/NotPresent；没有可用 EDID 友好名称，不称为型号识别成功。
- 独立 C SDK 探针编译 `cl /W4 /WX /std:c11 docs/research/display_probe.c user32.lib` 并执行，QueryDisplayConfig 返回 0、路径 1、有效名称 0、有效尺寸 1、1920×1080，与 Rust CLI/C 的计数和尺寸一致。探针不打印名称、LUID、目标 ID、设备路径或原始 EDID；SDK 固定结构不可避免在临时内存带有这些元数据，库不缓存/导出它们。

- 干净源码 `python scripts/check_packages.py --offline`：八个实际归档、原生 Cargo 验证、168 项隔离消费者测试、MIT/头文件与 CLI 安装通过，第三方锁定内容未变。
- 打包结束后单进程 `cargo bench --locked -p daoseeker-scope --bench collect`：首次 collect 436664 µs、100 次动态刷新 p50/p95/max 2255/3058/3938 µs；合成 100 传感器/1024 网络条目 360 µs/373541 bytes。整个采集调用，不是 CCD 专项延迟或性能 SLA。

[本地汇总](evidence/windows-display-local-7bd5b19.json)绑定实现提交、四份报告及日志哈希：[原生](evidence/windows-display-native-local-7bd5b19.json)、[打包](evidence/windows-display-package-local-7bd5b19.json)、[SDK](evidence/windows-display-sdk-probe-local-7bd5b19.json)、[基准](evidence/windows-display-benchmark-local-7bd5b19.json)。SDK 探针源码 Git blob 与本机编译的工作区文件规范化字节一致，汇总另记二进制哈希；SDK 不是自带 Git 信息的测试报告，其来源绑定由汇总提供。较早 raw SDK 读数与源码提交后的 CLI/C 为顺序读值，没有把它们当成原子快照。归档使用 LF，保留原始字节及实际归档字节 SHA-256；本轮文档归档提交没有重跑源码门禁。

## 兼容与验证边界

公共模型/签名、C ABI 1、Schema 1 形状不变；Schema 仅增加像素字段语义说明。windows-sys 0.61.2 仅增加 Windows target 的 Win32_Devices_Display feature，两个 Cargo.lock、包版本、checksum、依赖边和许可证均未变；项目仍 MIT。没有增加 CLI 命令枚举变体，显示器通过既有 --json/Rust/C ABI 读取；专用文本命令仍待实现。

路径最多 1024、模式最多 4096；实际条目另受默认 128/最大 1024 限额约束，超限拒绝成功前缀。拓扑竞争重试耗尽为 TemporarilyUnavailable；ERROR_ACCESS_DENIED 为 Restricted/PermissionDenied，不绕过控制台权限。统一组合逻辑可能保留默认 Unsupported/Custom，不表示调用成功。无效模式仅影响尺寸对，名称失败不影响尺寸。

成功、空集合和失败均缓存到当前 Hardware；动态刷新不重扫，模式/连接变化后需新建实例。模式与名称是顺序 API 调用，不承诺拓扑变化期间的原子快照。取消/截止时间仅限制等待和后续调用，不能强制中止同步驱动或硬限制 OS 内部分配。

本次未执行三平台原生 CI、实际 libFuzzer smoke、Miri/ASan 与 cargo-deny 回归；上轮 CI 不替代本轮源码验收。Linux/macOS 显示器保持 Unsupported。本机名称阳性读取、实体多屏、镜像/旋转/DPI、热插拔、远程会话、受限桌面与原生长期泄漏/峰值内存仍未验，不把 mock 的权限/拓扑分支当作真实会话证据。

下一步：本轮源码的三平台原生回归与证据归档，再分别实现 Linux/macOS 显示器最小采集；实体设备测试按维护者安排延期。
