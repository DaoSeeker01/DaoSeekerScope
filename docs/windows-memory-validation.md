# Windows 内存刷新验证

契约见 [ADR 0023](adr/0023-windows-memory.md)。本轮只实现 Windows 总内存和动态可用内存的直接 Win32 路径；CPU 和 macOS 内存仍是未完成的新鲜度/失败验收项，不以旧轮次的 CI 代替。

2026-10-19 实现及首次本机检查，2026-10-20 继续完成干净提交的运行/打包验收。Windows x64 已执行：

| 命令 | 实际结果与边界 |
|---|---|
| `pwsh -NoProfile -File scripts/check.ps1 -Cross` | fmt、all-target/all-feature clippy（拒绝警告）、199 项 Rust 测试、无默认 feature、doc（拒绝警告）、CLI/FFI 构建通过；Linux x64/macOS ARM64 交叉 check 通过，仅证明编译 |
| 固定版本 Ruff format/check、mypy、Python unittest | 34 个源文件静态检查、91 项测试通过；故意失败的 macOS SDK 比较负例不算本轮平台执行 |
| `scripts/check_schema.py`、`scripts/check_project.py` | Schema/黄金样例、观测不变量、未知字段/版本及文档检查通过 |
| `cargo fmt --manifest-path fuzz/Cargo.toml --check`、`cargo test --locked --offline --manifest-path fuzz/Cargo.toml --lib` | 两项 harness 回归通过；不是实际 libFuzzer campaign |
| `cargo build --locked -p daoseeker-scope --example dynamic_probe`、`pwsh -NoProfile -File scripts/build_c_example.ps1 -MemoryProbe` | Rust 持久刷新探针和 MSVC `/W4 /WX /std:c11` C SDK 探针构建通过；C ABI 实际 collect/free、清零、空释放和陈旧副本拒绝通过 |
| `python scripts/windows_memory_smoke.py` | 同一 Rust Hardware 实例在 baseline/held/released 三阶段刷新可用内存；C 进程最多分配 64 MiB，触页后释放。静态总量及时间缓存不变，动态成功字段为 Win32、新采集时间；不要求可用内存与 C 顺序读数相等或固定下降 |

新增八项可注入读取的纯 Rust 测试，以及 Windows SDK 布局、sysinfo 无内存 fallback 两项测试；覆盖逐次调用、错误清值、恢复后的真实零、静态失败缓存、总量变化、u64 边界、取消/超时和字段级能力变化。这些错误码是合成输入，没有在本机制造真实权限拒绝或 API 故障。

干净提交下的原生、压力实验、八包报告将在完成后补充。本轮三平台原生 CI、实际 fuzz、Miri/ASan 尚未执行；macOS 内存和 Windows/macOS CPU 新鲜度未解决。没有 registry 或 release 发布。

新增公开 backend `WindowsMemoryBackend::new()` / `Default`，主库 Hardware API 与公共模型不变。Windows 两个内存字段来源迁至 Win32，单独 SysinfoBackend 消费方需注册新的 backend 或使用门面；既有 `WindowsBackend` 构造不变。C ABI 1/Schema 1、依赖、锁、feature 与 MIT 不变。
