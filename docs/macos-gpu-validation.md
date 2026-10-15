# macOS GPU 本地验证与待验收项

2026-10-16 实现 [ADR 0018](adr/0018-macos-gpu.md)，源码 `2b0ea7604ca64684d6693459ef81e070516f2c19`。仅枚举 Metal 可见设备名称；统一内存的独占显存为 NotApplicable/NotPresent，其他设备为 Unsupported/NotSupported，不读取或推断工作集预算、共享容量或稳定设备标识。

## 已运行

- Windows x64 `pwsh -NoProfile -File scripts/check.ps1 -Cross`：fmt、Clippy 全 workspace/all-target/all-feature、157 项 Rust 测试（含 doctest）、no-default-features、doc 拒绝警告、CLI/FFI 构建及 Linux x64/macOS ARM64 cross-check 通过。
- macOS ARM64 backend all-target/all-feature Clippy 拒绝警告通过；没有在 Windows 执行原生 Metal。
- Ruff format/check、mypy --no-incremental（27 文件）、70 项 Python unittest、Schema generated/golden/不变量及项目链接检查通过。
- fuzz fmt 及 `cargo test --offline --manifest-path fuzz/Cargo.toml --lib` 两项 harness 回归通过；dmi_text 扩展 Metal 名称解析，增加 Unicode/NUL seed。实际 libFuzzer smoke 尚未运行。
- 重新编译 C 示例；干净源码的 Windows native smoke 五组检查、15 个进程均 passed，包含 Rust CLI、C ABI、Python 100 次默认 collect/free、文本元数据。先前系统 Python 缺少验证依赖导致 prerequisite_failed，改用固定 jsonschema 4.25.1 的 uv 环境通过，没有改变系统 Python 或运行时依赖。

新增七项纯 Rust 测试覆盖名称 UTF-8/UTF-16/NUL/上限、统一内存状态、空集合、枚举失败、字段隔离、取消/截止时间、模拟对象释放和静态成功/失败缓存；这些 mock 不验证 Objective-C 对象的原生堆泄漏。

- 干净源码 `python scripts/check_packages.py --offline`：八个实际 crate 归档、原生 Cargo 校验、157 项独立消费者测试、MIT/头文件和 CLI 安装通过。首次受限执行出现 Cargo 临时 registry 的 `no hash listed` 内部错误；使用所需缓存权限完整重跑通过，没有关闭原生验证。

[本地汇总](evidence/macos-gpu-local-2b0ea76.json)绑定源提交、两份报告与日志 SHA-256：[原生报告](evidence/macos-gpu-native-local-windows-2b0ea76.json)、[包报告](evidence/macos-gpu-package-local-windows-2b0ea76.json)。报告归档使用 LF，汇总同时记录原始报告字节与归档字节哈希。后续文档提交未重跑源码门禁。

## 兼容与待运行

公共 Rust 模型和签名、Schema 1、C ABI 1 不变。macOS GPU 能力改为 Partial/AppleApi，新增 macOS 专用 objc2 0.6.5、objc2-encode 4.1.0、objc2-foundation/metal 0.3.2；均可选择 MIT。两个 Cargo.lock 的原有第三方包版本及 checksum 未变。既有隐藏 fuzzing feature 新增测试函数，默认关闭，非稳定消费 API。

三平台原生 CI、独立 Objective-C SDK 探针、cargo-deny、11 个实际 fuzz smoke 及 Miri/ASan 回归尚未在本源码运行。推送 main 被自动审批拒绝，等待用户明确授权；不引用旧 CI 作为本次验收。实体 Mac、多 GPU、热插拔、sandbox、长期原生泄漏/峰值分配测试仍待后续设备或专项验证。平台内部枚举分配不受库的投影条目上限控制，同步驱动调用不能强制终止。

下一步：获得推送授权后运行并归档三平台 CI，核对 Metal SDK 与 CLI/C 的脱敏计数/内存状态，再推进显示器最小采集。
