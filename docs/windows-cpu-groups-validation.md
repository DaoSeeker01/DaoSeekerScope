# Windows 多处理器组 CPU 验证

契约见 [ADR 0029](adr/0029-windows-cpu-groups.md)。单组沿用已有直接路径；64 位多组通过每次新建、必定 join 的专用线程枚举实际活动 mask，逐组切换该线程的亲和性并读取 GetSystemTimes，最后复核拓扑。逐组检查差值后用 u128 加权，避免平均各组百分比或总和掩盖单组复位。能力仍为 Partial，失败不提供子集或旧值，恢复后重新预热。

2026-10-24 本地验证在 Windows x64 笔记本完成。实际只有 **1 个活动组、12 个 logical processors**。内部原生测试强制执行同一 helper/组枚举路径，检查 GetThreadGroupAffinity 返回的调用线程主组/mask 前后一致；独立 C SDK 探针也使用自有线程，检查布局、实际 mask、计数和退出。这项查询不是 Windows 11 全部跨组亲和性的枚举；实现本身没有对调用者或进程设置亲和性。它们证明本机单组可执行该路径，不证明真实跨组切换或 >64 CPU 的采样正确。

可复现命令：

```powershell
pwsh -NoProfile -File scripts/check.ps1 -Cross
cargo clippy --locked --workspace --all-targets --all-features --target aarch64-apple-darwin -- -D warnings
cargo clippy --locked --workspace --all-targets --all-features --target x86_64-unknown-linux-gnu -- -D warnings
pwsh -NoProfile -File scripts/build_c_example.ps1 -CpuGroupsProbe
python scripts/windows_cpu_groups_smoke.py
python -m unittest discover -s tests -p "test_*.py"
python scripts/check_schema.py
python scripts/check_project.py
cargo fmt --manifest-path fuzz/Cargo.toml --check
cargo test --locked --offline --manifest-path fuzz/Cargo.toml --lib
cargo check --locked --offline --manifest-path fuzz/Cargo.toml
cargo clippy --locked --offline --manifest-path fuzz/Cargo.toml --all-targets -- -D warnings
python scripts/check_packages.py --offline
python scripts/native_smoke.py --output target/windows-cpu-groups-native-clean.json
```

完整 Rust 门禁通过：fmt、严格 Clippy、252 项测试含 doctest、无默认 feature、文档和 FFI/CLI 构建，另有 Linux x64/macOS ARM64 交叉检查及两目标的全 target 严格 Clippy。纯逻辑用例覆盖稀疏 mask、16 组上限、截断/计数/布局损坏、u64 以上加总、逐组复位、同数量 mask 变化、任意调用失败与取消/超时检查。SDK 持久进程对照完成首次预热、三次刷新、重建预热和静态 CPU 缓存检查；不同进程的区间不同，不要求百分比相等，也未注入可控 CPU 负载。

Python Ruff/mypy 46 文件、112 项单测及 Schema 守卫通过。新增守卫拒绝布尔伪整数、错误布局/掩码/计数、单组复位被总和掩盖、同数量 mask 变化；失败报告覆盖旧成功记录，不记录原始系统错误。具体干净源码的打包与跨语言结果将在本轮归档中记录。

新增第 12 个 fuzz 目标 `windows_cpu_groups`，调用生产纯解析器，使用合成双组种子。Windows 本地格式、全部目标 check/严格 Clippy 和 3 项 harness 单测通过；尚未执行实际 libFuzzer campaign。新增默认关闭的 Windows `fuzzing` feature，fuzz 锁文件只增加直接依赖边，第三方版本和许可证不变；根锁、公共消费模型/签名、MIT、ABI 1、Schema 1 不变。

尚未验证：本轮三平台原生 CI、新目标实际 fuzz、真实多组/CPU hotplug/Job 限制/OS API 失败、32 位多组（明确不支持）、长期泄漏与峰值内存、组切换性能。合作式取消无法中断阻塞的 OS 调用；core 的 16 worker 限额约束并发任务，每个多组任务至多再产生一个 helper，不声称无线程成本。顺序读取不是原子全机快照；同拓扑 ABA 不能检测。实体 Linux/macOS 按维护者安排延期。
