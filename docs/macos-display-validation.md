# macOS 活动显示与模式像素验证

2026-10-18 实现 [ADR 0021](adr/0021-macos-display.md)，源码 `2cf273658cec2993b9c85cb2a1d1f4cf6f4b44cf`。通过公开 Core Graphics 返回 active-for-drawing 视图与当前显示模式的 pixelWidth/pixelHeight。它不是物理显示器计数、面板原生分辨率、逻辑 points 或 Windows CCD 信号 activeSize；硬件镜像可能只列主显示。名称保持 Unsupported/NotSupported，不查询名称、EDID、序列号或 UUID。

## 本地验证

- Windows x64 执行 `pwsh -NoProfile -File scripts/check.ps1 -Cross`：fmt、workspace/all-target/all-feature Clippy、184 项 Rust 测试（含 doctest）、core/门面 no-default-features、doc 拒绝警告、CLI/FFI 构建及 Linux x64/macOS ARM64 cross-check 通过。首次交叉编译发现私有重导出范围错误，修复后完整重跑，未放宽门禁。
- macOS crate 的 31 项并行单测通过，其中新增 8 项显示器测试覆盖真实空列表复核、默认不伪造名称、1025/溢出计数、零/重复 ID、输出限额、成对非零 u32 尺寸、字段隔离、CGError 映射、列表重排/三轮拓扑变化/恢复、调用前后取消和静态成功/空/失败缓存。
- 固定版本 Ruff format/check、mypy --no-incremental --ignore-missing-imports（32 文件）、86 项 Python unittest、Schema generated/golden/不变量与项目链接检查通过。新增 6 项 Python 守卫测试，包含 SDK 数量/像素/缺失状态对照、错误类型/元数据及失败覆盖旧成功。单测日志中的 SDK comparison: failed 是刻意错误路径回归，不是实际 macOS 探针结果。
- `cargo fmt --manifest-path fuzz/Cargo.toml --check` 及 `cargo test --locked --offline --manifest-path fuzz/Cargo.toml --lib`（2 项）通过。本地没有执行实际 libFuzzer；没有新建 fuzz 目标，既有 JSON/CLI/平台原始文本回归继续在 CI 运行，不把它们当作 Core Graphics 原生指针/驱动 fuzz。
- 重建 C 示例，通过 collect/free、清零、空释放与陈旧 buffer 拒绝；干净源码 Windows native smoke 的五组检查、15 个进程及 Python 默认 100 次 collect/free 通过。这是 Windows 回归，不是 macOS 设备读取。
- 干净源码 `python scripts/check_packages.py --offline`：八个实际归档、原生 Cargo 验证、184 项隔离消费者测试及 CLI 安装通过，MIT/头文件与第三方锁定内容未变；不是 registry 发布验收。

[本地汇总](evidence/macos-display-local-2cf2736.json)绑定源码、日志哈希及两份报告：[Windows 原生](evidence/macos-display-native-windows-local-2cf2736.json)、[八包](evidence/macos-display-packages-windows-local-2cf2736.json)。报告记录干净源码，归档 LF 并保留原始/归档字节 SHA-256。

## 待执行与限制

本轮尚未执行三平台原生 CI、实际 fuzz/Miri/ASan/cargo-deny、macOS 基准与独立 C SDK 探针。已准备 `cc -Wall -Wextra -Werror -std=c11 docs/research/macos_display_probe.c -framework CoreGraphics`，SDK static_assert 检查标量宽度/错误码，运行后与同源码 CLI/C 的数量、模式像素与缺失状态多重集合比较；顺序调用不是原子拓扑证明。SDK 报错、空视图或无模式时保留状态，不能称作尺寸读取成功。

枚举固定 1025 槽位，1025 条拒绝，以便检测截断；另受默认 128/最大 1024 输出限额限制。前后 ID 集合变化最多重试三轮，失败为 TemporarilyUnavailable；模式 Copy 为 NULL 只影响该条目的尺寸对，不猜权限错误。零或溢出像素 InvalidData。通用 WindowServer 错误不等于 PermissionDenied 或 Sandbox，不读取残留 errno。

Copy 模式对象由私有 NonNull RAII Release，不缓存原生对象/ID；同步 SDK/WindowServer 不能强制中止或限制其内部全部内存。成功、空集合与失败均静态缓存，动态刷新不重扫，模式/连接变化后需新建 Hardware。前后复核不能排除 ABA 或同一 ID 的模式变化，不承诺跨调用原子快照。

Rust 模型/签名、C ABI 1/Schema 1 形状、默认/公开 features、两个 Cargo.lock 和依赖许可证不变，项目仍 MIT。Schema 只补充模式像素描述；macOS 内部链接 CoreGraphics，五个私有 C 声明不进入公共契约，没有新 Rust 包或 Apple 实现代码。CLI 使用既有 --json，不新增命令枚举变体。

实体 Mac、Retina/缩放、多屏、镜像、热插拔、远程/沙盒、原生长期泄漏与峰值内存按设备安排待验证；CI 或纯接口测试不替代它们。Linux 当前像素与真实名称阳性仍待验证。下一步评估显示器的 CLI 文本展示；移动/Web/no_std/MCU 仍独立后续路线。
