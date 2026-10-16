# macOS GPU 验证

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

## 三平台原生 CI

源码实现为 `2b0ea7604ca64684d6693459ef81e070516f2c19`；用户授权推送后，手动工作流运行于 `9d30f3b1489502fbb199812d527bb79708651dda`，两者之间仅有本地验证文档/报告变更，没有采集代码变化。[CI 38826444216](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38826444216) 的最终状态和报告绑定见下文汇总。

macOS ARM64 托管 VM 的 Rust CLI/C 各读取 1 个 Metal 可见设备，名称 Available/AppleApi；统一内存为 true，独占显存 NotApplicable/NotPresent。独立 Objective-C 公开 SDK 探针得到相同设备数、可用名称数和内存状态计数。报告只保存名称可用性和计数，不保留产品名称或设备标识；两个顺序快照吻合，不承诺跨调用原子性。不是实体 Mac 或完整物理显卡清单，旧系统/独立显存设备与多 GPU 仍待验证。

独立探针由 `clang -Wall -Wextra -Werror -fobjc-arc docs/research/metal_probe.m -framework Metal -framework Foundation` 编译，只调用公开 Metal/Foundation 接口；一次枚举并正常退出不构成原生 heap/leak 证明。Rust 字符串严格 UTF-8/UTF-16 长度及 NUL 校验、默认 128/最大 1024 条目、静态成功/失败缓存、动态不重扫和同步驱动不能强制中止的边界见 [ADR 0018](adr/0018-macos-gpu.md)。


[最终汇总](evidence/macos-gpu-ci-38826444216.json)验证 **8/8 个 CI 任务全部成功**，绑定九份报告及完整运行日志哈希：三平台原生报告、三平台八包报告、独立 SDK 探针、Linux GPU 容器回归和 macOS 基准样本。原生报告分别绑定干净 CI 源码；较早的两份本地报告仍绑定实现提交，不混用 source commit。

| 门禁 | 实际结果 |
|---|---|
| Windows x64 / Linux x64 / macOS ARM64 | 源码与独立消费者各 157 / 153 / 153 项 Rust 测试（含 doctest）通过；fmt/Clippy/doc 拒绝警告及 no-default-features 通过 |
| 三平台八个 crate / CLI 安装 | 原生 Cargo 验证、MIT/头文件、独立消费者与安装通过；隔离构建的第三方锁定内容未变 |
| 三平台 CLI/C/Python | 各五组检查、15 个进程通过，Python 默认 collect/free 100 次通过 |
| Python / Schema | 各平台 Ruff、mypy --no-incremental（27 文件）、70 项 unittest、Schema generated/golden 及项目链接检查通过 |
| Linux 非 root GPU 回归 | 20 项合成 DRM/驱动文件/权限/缓存场景通过；完整 /proc 覆盖的旧探针仍 not_run |
| fuzz | 11 个既有目标各至少 60 秒并正常 DONE；新增 Metal 名称仅通过纯解析入口，不测试原生 ObjC 调用 |
| 内存与供应链 | Miri 8 项、Linux FFI ASan 10 项和 cargo-deny 通过；不是 macOS 原生堆泄漏证明 |

[macOS 原生报告](evidence/macos-gpu-native-darwin-38826444216.json)、[SDK 探针](evidence/macos-gpu-sdk-probe-38826444216.json)与[macOS 包报告](evidence/macos-gpu-package-evidence-macos-arm64-38826444216.json)对应同一 CI 源码。Windows CI 实读一条 DXGI 设备名称，独占显存报告 0 字节；Linux CI 实读一条 DRM 视图，名称/显存仍 Unsupported，均不推断物理硬件数量或真实容量。

## 兼容与未覆盖边界

公共 Rust 模型和签名、Schema 1、C ABI 1 不变。macOS GPU 能力改为 Partial/AppleApi，新增 macOS 专用 objc2 0.6.5、objc2-encode 4.1.0、objc2-foundation/metal 0.3.2；均可选择 MIT。两个 Cargo.lock 的原有第三方包版本及 checksum 未变。既有隐藏 fuzzing feature 新增测试函数，默认关闭，非稳定消费 API。

初次本地记录时这些 CI 项目尚未运行，自动审批曾拒绝推送；2026-10-16 用户明确授权两次提交推送 main 并启动 CI，现已完成并通过上述全部门禁。实体 Mac、多 GPU、热插拔、sandbox、长期原生泄漏/峰值分配测试仍待后续设备或专项验证。平台内部枚举分配不受库的投影条目上限控制，同步驱动调用不能强制终止。

下一步：推进显示器最小采集的公开 API/权限评估；GPU 后续完善 Linux 独占显存及更多可靠名称来源，实体设备测试按维护者安排延期。本轮验收归档仅为文档与报告，没有新增采集代码或发布 registry。
