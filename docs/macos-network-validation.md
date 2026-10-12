# macOS 网络验证

2026-10-12 最终修复源码 `d27e681b87cc64f5ed55c11218752b3c70268f0a` 的 [CI 38186025262](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38186025262) **全部 8 个任务成功**。[汇总证据](evidence/macos-network-ci-38186025262.json)绑定源码、实际测试数、原生报告及日志哈希；[首轮失败报告](evidence/macos-network-failure-previous-run-38186025262.json)保留失败原因与空输入复现信息。后续文档归档提交不是另一次源码 CI。

首轮源码 `69b9c4ef7eed97fdad7951983c6cb84fe4ddedc6` 的 [CI 38095804975](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38095804975) 为 **7/8 成功，整体失败**。三个原生平台、容器、Miri、ASan 与供应链通过；前九个 fuzz 目标运行完成，新 macOS fuzz 在空输入时失败：共享检查错误地硬编码 Source::Procfs，实际应为 Sysctl。这是 harness 接入错误，不是解析器崩溃或基础设施故障。修复使每个目标显式传入预期来源，保留状态/时间/原因不变量，并增加空输入、二进制种子及错误来源拒绝的两项回归。实现契约见 [ADR 0012](adr/0012-macos-network-counters.md)。

macOS 26.6.2 / Darwin 25.6.0、arm64 CI 虚拟机（系统报告 Apple M2 Pro (Virtual)、5 逻辑核、14 GiB）通过 CLI/C 各读取 11 条 Sysctl 统计，所有名称 Restricted/PrivacyRedacted，计数有来源与采集时间。实际原生读取不是合成解析测试；虚拟接口数量不是物理网卡数量。Python FFI 100 次 collect/free 通过。

能力 Partial：Apple 当前公开源码会对普通应用的字节数按 1 KiB 取整并转换为 uint32_t；保留 OS 返回值，不承诺精确或完整 64 位累计量。当前样本不验证回绕实际发生。临时路由缓冲包含未解析/保存的链路元数据；默认不调用名称查询。系统内部内存分配及已阻塞调用不在调用方缓冲/取消保证范围内。

本轮修改 macOS crate 的采集与安全解析模块、默认关闭的 fuzzing 验证入口、CLI/C 原生验收脚本、fuzz harness/种子、CI 与相关文档。MacosBackend 仍为原有 unit struct；公共 DTO/消费签名、Schema 1、C ABI 1 不变，无新增依赖或版本/许可证变化，项目仍 MIT。

本机已执行 `pwsh -NoProfile -File scripts/check.ps1 -Cross`：Windows fmt/Clippy、105 项 Rust 测试（含 1 doctest）、doc 拒绝警告、no-default-features、CLI/FFI build、Linux x64/macOS arm64 cross-check。另行两目标 all-target/all-feature Clippy 拒绝警告、fuzz fmt/稳定版 Clippy/nightly check 通过。nightly check 有既存 fetch_update 重命名弃用警告；稳定版门禁无警告。交叉构建不能替代 macOS 原生读取。

2026-10-12 修复 harness 后本机执行 `cargo test --locked --manifest-path fuzz/Cargo.toml --lib`，两项回归通过；fuzz fmt/Clippy 拒绝警告/nightly check 也通过。此前尝试 `--test observation_contract` 会顺带链接 fuzz 二进制，在不支持原生 libFuzzer 的 Windows 上报 LNK1561；回归改为仅构建 library test，CI 同样使用 `--lib`，不跳过任何 fuzz 目标。Windows 两项普通测试不等于实际 libFuzzer campaign。

Ruff 格式/检查、mypy --no-incremental（18 文件）、36 项 Python unittest、Schema 黄金样例/未知字段/版本与项目检查通过。本机干净提交完成 8 个实际 crate 归档、MIT/头文件检查、原生 Cargo 验证、105 项独立消费者测试与 CLI 安装；未发布 registry。macOS CI 独立包也完成 8 个归档与 102 项消费者测试，第三方锁文件未变。

新增 8 项合成测试验证消息截断/版本/索引/边界、完整 u64 传输转换、默认不查询名称、授权/名称失败隔离、失败恢复和取消。名称函数没有真实授权路径的设备测试；合成取消/超时不证明可硬中断 sysctl。macOS 真机权限拒绝、沙盒、热插拔、泄漏分析、x64 设备运行和长期 fuzz 本轮未执行。Linux Miri/ASan/fuzz 不执行 macOS 原生 unsafe。

原生基准实际执行 `cargo bench --locked -p daoseeker-scope --bench collect`，首次 collect 136 µs，100 次动态刷新 p50/p95/max 19/24/35 µs，第二次 CPU 样本 Available。合成 100 传感器/1024 接口另为 515 µs、JSON 373541 bytes。共享 runner、单进程、完整 collector 的样本，不是单独网络 syscall 延迟、内存基准或 SLA，参数见[性能记录](benchmarks.md)。

最终修复源码的 macOS 基准首次 167 µs、刷新 33/50/65 µs、合成 124 µs/373541 bytes；与首轮属于两次共享 runner 样本，不代表性能变化因果。[原生 macOS 报告](evidence/macos-network-native-macos-38186025262.json)记录系统版本与脱敏值；[本机独立包报告](evidence/macos-network-package-local-windows-38186025262.json)记录干净提交、105 项测试与八个实际归档。

| 最终修复 CI / 回归门禁 | 实际结果 |
|---|---|
| Windows x64 / Linux x64 / macOS arm64 源码 | 105 / 103 / 102 项 Rust 测试，均含 1 doctest；fmt、Clippy、doc 拒绝警告及 no-default-features 通过 |
| 三平台独立归档/安装 | 各八个实际 crate 归档，原生 Cargo 验证、MIT/头文件检查、消费者测试及 CLI 安装通过；测试数仍为 105 / 103 / 102，第三方锁文件未变 |
| 三平台 CLI/C/Python | CPU/内存/OS 通过；网络 Win32 18 / Procfs 4 / Sysctl 11 条，名称全部脱敏；Python 100 次 collect/free 通过 |
| 三平台 Python / Schema | Ruff、mypy --no-incremental（18 文件）、36 项 unittest、Schema 无漂移与项目检查通过 |
| 十个 fuzz 目标 | 每个实际执行至少 60 秒并到达 DONE；macos_network 为 61 秒、5,057,654 次，无崩溃正常结束；两个 harness 回归也在 Linux CI 通过 |
| Miri / FFI ASan / 供应链 | 8 / 10 项 FFI 测试与 cargo-deny 通过；Linux 执行不覆盖 macOS 原生 unsafe |
| Linux 容器回归 | 通过；完整 /proc 替换仍为 OCI runtime_mount_error / not_run，不当作后端执行成功 |

归档报告使用 Git 的 LF 换行。汇总 `sha256` 对应仓库报告字节，`original_report_sha256` 对应原始下载/生成字节；Windows CRLF 两者可不同。日志哈希对应原始日志，首轮与修复轮分开记录。未做长期 campaign、覆盖率验收、macOS 原生泄漏 profiler 或正式 registry 发布。下一阶段先调研存储容量的有界读取与隐私范围，再实现一个独立切片。
