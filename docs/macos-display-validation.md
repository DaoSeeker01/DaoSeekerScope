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

## 三平台 CI（2026-10-18）

用户授权本轮提交、必要修复与验收归档后，工作流运行于 `1231088bc97d005a7e3c516d865db14362baf8ed`，包含实现 `2cf2736`、本地归档和 Unsupported/Custom 严格缺失状态的验收守卫修正。底层采集、SDK C 源码、核心模型与 Schema 描述没有在守卫修正中改变。[CI 39081392549](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/39081392549) 最终 8/8 个任务全部成功，[汇总](evidence/macos-display-ci-39081392549.json)绑定源码、实际变更列表与完整日志哈希。

独立 C SDK 探针返回 status=0、活动条目 1、有效模式尺寸 1。Rust CLI/C 的数量及像素/缺失状态多重集合与 SDK 相同。本轮可读模式像素为 1024×768。这是托管 runner 的活动模式，不能推断实体面板原生分辨率。

名称保持 Unsupported/NotSupported、Source AppleApi；宽高使用同一模式对象且成对验证。SDK/CLI/C 为顺序调用、按像素与缺失状态多重集合对照，不证明原子拓扑、物理设备数量、镜像关系或 ID 稳定性。不捕获屏幕、不请求权限、不读取名称/EDID/稳定标识。

| 门禁 | 实际结果 |
|---|---|
| Windows x64 / Linux x64 / macOS ARM64 | 源码与隔离消费者各 184 / 180 / 180 项 Rust 测试（含 doctest），fmt/Clippy/doc 拒绝警告与 no-default-features 通过 |
| 三平台八包 / CLI 安装 | 实际归档、原生 Cargo 验证、MIT/头文件、隔离消费者与安装通过，第三方锁定内容未变 |
| 三平台 CLI/C/Python | 各五组检查、15 个进程通过，含 Python 默认 100 次 collect/free |
| Python / Schema | 各平台 86 项 unittest、32 文件 Ruff/mypy、Schema generated/golden/不变量与项目检查通过 |
| macOS C SDK | cc C11/Wall/Wextra/Werror、公开头文件 static_assert、CoreGraphics 链接、原生执行及同源码 SDK/CLI/C 对照通过 |
| Linux 回归 | 显示器 26、GPU 20、存储 21、hwmon 47、电池 30、内存 26、CPU 15 及 DMI/输入 7 场景通过；完整 /proc 覆盖仍由 OCI 拒绝、not_run |
| 实际 fuzz | 11 个既有目标各至少 60 秒并正常 DONE；不覆盖 Core Graphics 原生内存或驱动边界 |
| 内存与供应链 | Miri 8 项、Linux FFI ASan 10 项和 cargo-deny 通过；不是原生 CGMode 长期泄漏证明 |

[macOS 原生报告](evidence/macos-display-native-darwin-39081392549.json)、[独立 C SDK 探针](evidence/macos-display-sdk-probe-39081392549.json)、[对照结果](evidence/macos-display-sdk-comparison-39081392549.json)及[macOS 八包报告](evidence/macos-display-package-evidence-macos-arm64-39081392549.json)属于同一 CI 源码。汇总绑定九份报告的原始/归档 SHA-256、SDK C 源码 Git blob 与完整工作流日志哈希。较早本机两份报告仍绑定实现提交，不混作 macOS 原生结果；随后纯文档归档提交没有重跑源码 CI。

同轮基准首次 collect（不含构造）12509 µs，100 次动态刷新 p50/p95/max 24/28/76 µs。这是整个采集器，环境、参数、profile 和原始输出见[性能报告](benchmarks.md)及[基准归档](evidence/macos-display-benchmark-39081392549.json)，不作为 CG 枚举专项性能或 SLA。


授权启动的先行 [CI 39080974981](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/39080974981) 运行于 `5af71a1`，其中 macOS 原生任务及 SDK/CLI/C 对照成功，观察到一条活动视图、1024×768 模式像素。错误路径复核随后发现新守卫未兼容既有组合器保留 Unsupported/Custom 的行为；修正仅限严格缺失状态，不接受 Available/Custom 或伪造数值，也不修改采集代码/组合策略。先行 CI 的剩余任务被主动取消，由修正后源码的完整 CI 取代；不把先行任务成功当作整轮 CI 验收。

## 兼容与验证边界

枚举固定 1025 槽位，1025 条拒绝，以便检测截断；另受默认 128/最大 1024 输出限额限制。前后 ID 集合变化最多重试三轮，失败为 TemporarilyUnavailable；模式 Copy 为 NULL 只影响该条目的尺寸对，不猜权限错误。零或溢出像素 InvalidData。通用 WindowServer 错误不等于 PermissionDenied 或 Sandbox，不读取残留 errno。

Copy 模式对象由私有 NonNull RAII Release，不缓存原生对象/ID；同步 SDK/WindowServer 不能强制中止或限制其内部全部内存。成功、空集合与失败均静态缓存，动态刷新不重扫，模式/连接变化后需新建 Hardware。前后复核不能排除 ABA 或同一 ID 的模式变化，不承诺跨调用原子快照。

Rust 模型/签名、C ABI 1/Schema 1 形状、默认/公开 features、两个 Cargo.lock 和依赖许可证不变，项目仍 MIT。Schema 只补充模式像素描述；macOS 内部链接 CoreGraphics，五个私有 C 声明不进入公共契约，没有新 Rust 包或 Apple 实现代码。CLI 使用既有 --json，不新增命令枚举变体。

实体 Mac、Retina/缩放、多屏、镜像、热插拔、远程/沙盒、原生长期泄漏与峰值内存按设备安排待验证；CI 或纯接口测试不替代它们。Linux 当前像素与真实名称阳性仍待验证。下一步评估显示器的 CLI 文本展示；移动/Web/no_std/MCU 仍独立后续路线。
