# macOS 网络验证

首轮源码 `69b9c4ef7eed97fdad7951983c6cb84fe4ddedc6` 的 [CI 38095804975](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38095804975) 为 **7/8 成功，整体失败**。三个原生平台、容器、Miri、ASan 与供应链通过；前九个 fuzz 目标运行完成，新 macOS fuzz 在空输入时失败：共享检查错误地硬编码 Source::Procfs，实际应为 Sysctl。这是 harness 接入错误，不是解析器崩溃或基础设施故障。修复使每个目标显式传入预期来源，保留状态/时间/原因不变量，并增加空输入、二进制种子及错误来源拒绝的两项回归；完整修复 CI 待汇总。实现契约见 [ADR 0012](adr/0012-macos-network-counters.md)。

macOS 26.6.2 / Darwin 25.6.0、arm64 CI 虚拟机（系统报告 Apple M2 Pro (Virtual)、5 逻辑核、14 GiB）通过 CLI/C 各读取 11 条 Sysctl 统计，所有名称 Restricted/PrivacyRedacted，计数有来源与采集时间。实际原生读取不是合成解析测试；虚拟接口数量不是物理网卡数量。Python FFI 100 次 collect/free 通过。

能力 Partial：Apple 当前公开源码会对普通应用的字节数按 1 KiB 取整并转换为 uint32_t；保留 OS 返回值，不承诺精确或完整 64 位累计量。当前样本不验证回绕实际发生。临时路由缓冲包含未解析/保存的链路元数据；默认不调用名称查询。系统内部内存分配及已阻塞调用不在调用方缓冲/取消保证范围内。

本轮修改 macOS crate 的采集与安全解析模块、默认关闭的 fuzzing 验证入口、CLI/C 原生验收脚本、fuzz harness/种子、CI 与相关文档。MacosBackend 仍为原有 unit struct；公共 DTO/消费签名、Schema 1、C ABI 1 不变，无新增依赖或版本/许可证变化，项目仍 MIT。

本机已执行 `pwsh -NoProfile -File scripts/check.ps1 -Cross`：Windows fmt/Clippy、105 项 Rust 测试（含 1 doctest）、doc 拒绝警告、no-default-features、CLI/FFI build、Linux x64/macOS arm64 cross-check。另行两目标 all-target/all-feature Clippy 拒绝警告、fuzz fmt/稳定版 Clippy/nightly check 通过。nightly check 有既存 fetch_update 重命名弃用警告；稳定版门禁无警告。交叉构建不能替代 macOS 原生读取。

2026-10-12 修复 harness 后本机执行 `cargo test --locked --manifest-path fuzz/Cargo.toml --lib`，两项回归通过；fuzz fmt/Clippy 拒绝警告/nightly check 也通过。此前尝试 `--test observation_contract` 会顺带链接 fuzz 二进制，在不支持原生 libFuzzer 的 Windows 上报 LNK1561；回归改为仅构建 library test，CI 同样使用 `--lib`，不跳过任何 fuzz 目标。Windows 两项普通测试不等于实际 libFuzzer campaign。

Ruff 格式/检查、mypy --no-incremental（18 文件）、36 项 Python unittest、Schema 黄金样例/未知字段/版本与项目检查通过。本机干净提交完成 8 个实际 crate 归档、MIT/头文件检查、原生 Cargo 验证、105 项独立消费者测试与 CLI 安装；未发布 registry。macOS CI 独立包也完成 8 个归档与 102 项消费者测试，第三方锁文件未变。

新增 8 项合成测试验证消息截断/版本/索引/边界、完整 u64 传输转换、默认不查询名称、授权/名称失败隔离、失败恢复和取消。名称函数没有真实授权路径的设备测试；合成取消/超时不证明可硬中断 sysctl。macOS 真机权限拒绝、沙盒、热插拔、泄漏分析、x64 设备运行和长期 fuzz 本轮未执行。Linux Miri/ASan/fuzz 不执行 macOS 原生 unsafe。

原生基准实际执行 `cargo bench --locked -p daoseeker-scope --bench collect`，首次 collect 136 µs，100 次动态刷新 p50/p95/max 19/24/35 µs，第二次 CPU 样本 Available。合成 100 传感器/1024 接口另为 515 µs、JSON 373541 bytes。共享 runner、单进程、完整 collector 的样本，不是单独网络 syscall 延迟、内存基准或 SLA，参数见[性能记录](benchmarks.md)。
