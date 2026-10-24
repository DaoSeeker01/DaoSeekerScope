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

Python Ruff/mypy 46 文件、112 项单测及 Schema/项目守卫通过。新增守卫拒绝布尔伪整数、错误布局/掩码/计数、单组复位被总和掩盖、同数量 mask 变化；失败报告覆盖旧成功记录，不记录原始系统错误。

实现提交 `7fbb19e379e373cd19f3a997f706046b9a566385` 的干净工作区完成：

- [验收索引](evidence/windows-cpu-groups-local-7fbb19e.json)：命令、来源、日志/报告哈希，明确单组与未运行边界。
- [八包报告](evidence/windows-cpu-groups-packages-7fbb19e.json)：8 个实际归档、原生 Cargo 验证、解包后独立 workspace 252 项测试及 CLI 安装；未发布的相邻 crate 使用本地 patch，不等于 registry 发布。
- [原生报告](evidence/windows-cpu-groups-native-7fbb19e.json)：CLI/C/Python 等 5 组、16 个进程通过，包括 100 次 Python collect/free。
- [SDK 报告](evidence/windows-cpu-groups-sdk-7fbb19e.json)：C SDK 自有线程读取和 Rust 持久刷新通过；`actual_groups=1`、`real_multi_group_device=false`、`facade_group_path_exercised=false`。内部原生单测另外强制执行 Rust helper，两帧有效，主组/mask 不变。

通用门禁在实现提交前执行；运行和守卫源码随后未改变。实现提交后重建探针并运行原生、SDK、helper 与八包，报告均绑定同一干净提交。后续本地验收归档仅修改文档和证据。

新增第 12 个 fuzz 目标 `windows_cpu_groups`，调用生产纯解析器，使用合成双组种子。Windows 本地格式、全部目标 check/严格 Clippy 和 3 项 harness 单测通过；实际 Linux CI campaign 见下节。新增默认关闭的 Windows `fuzzing` feature，fuzz 锁文件只增加直接依赖边，第三方版本和许可证不变；根锁、公共消费模型/签名、MIT、ABI 1、Schema 1 不变。

尚未验证：真实多组/CPU hotplug/Job 限制/OS API 失败、32 位编译与多组（多组明确不支持）、长期泄漏与峰值内存、组切换性能。合作式取消无法中断阻塞的 OS 调用；core 的 16 worker 限额约束并发任务，每个多组任务至多再产生一个 helper，不声称无线程成本。顺序读取不是原子全机快照；同拓扑 ABA 不能检测。实体 Linux/macOS 按维护者安排延期。

## 三平台 CI 验收

[运行 40046393393](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40046393393)，2026-10-24 执行、2026-10-25 归档，源码 `bedd8a7f96403020ee5492ab9cbe7221fc5ecff8`。仅启动一次 workflow_dispatch，八个任务全部成功，无需本轮运行时代码修复。[验收索引](evidence/windows-cpu-groups-ci-40046393393.json)保留十五份报告、源码与 SHA-256，新目标原始 fuzz 日志也保存在索引中。

| 平台 | workspace / 八包独立测试（含 doctest） | Python 单测 | 原生 CLI/C/Python |
|---|---|---|---|
| Windows x64 | 252 / 252 | 112 | 五组、16 个进程通过 |
| Linux x64 | 244 / 244 | 112 | 五组、16 个进程通过 |
| macOS ARM64 | 249 / 249 | 112 | 五组、16 个进程通过 |

各平台 fmt、严格 Clippy、无默认 feature、doc（拒绝 warning）、Ruff/mypy（46 文件）、Schema/项目守卫、八包原生 Cargo 验证、提取后的独立 workspace 测试及 CLI 安装均通过。每个平台 Python 执行 100 次 collect/free。归档消费者用本地 patch 提供尚未发布的相邻 crate，不等于 registry 发布或正式制品分发。

Windows [组 SDK 报告](evidence/windows-cpu-groups-sdk-40046393393.json)实际为 **1 个活动组、4 个 logical processors**；48-byte PROCESSOR_GROUP_INFO、组数组偏移 32、活动 mask=15 均通过独立 SDK 检查。C 自有线程四帧有效，调用线程主组/mask 前后一致；Rust 内部 helper 原生单测也通过。公共门面在该主机仍执行单组快速路径，`real_multi_group_device=false`、`facade_group_path_exercised=false`。因此没有真实多组/>64 CPU 成功声明。

| 动态刷新 | Rust CPU % | 独立 SDK CPU %（不同采样区间） |
|---|---|---|
| 1 | 0 | 1.0869565217391304 |
| 2 | 3.260869565217391 | 3.260869565217391 |
| 3 | 3.260869565217391 | 3.260869565217391 |

首次和重建均按预热暂不可用，三次刷新检查静态 CPU 缓存、采集时间和有效范围；零用量合法，区间不同允许结果不同，不检查跨进程百分比相等。单组 CPU、Windows 内存/64 MiB 实验、uptime，以及 macOS CPU/内存/uptime 的 SDK 回归也通过；报告均绑定本轮干净源码，不能由此扩大真实多组或故障注入声明。

12 个 libFuzzer 目标各运行 **61 秒**，新目标 `windows_cpu_groups` 为 **55,466,941 次**，无崩溃正常结束，固定 seed=20261024/max_len=1025/timeout=2 秒/RSS limit=512 MiB。3 项 harness 守卫回归、Miri 8 项、Linux Rust FFI ASan 10 项和 cargo-deny 通过。这些短测试不是长期无漏洞、真实 Windows API 故障或泄漏证明；纯解析器在 Linux 执行不代表 Windows 原生跨组采样。

Linux 容器八份报告通过：CPU 15、内存/uptime 26、电池 30、hwmon 47、存储 21、GPU 20、显示器 26 项及既有 DMI/权限检查；完全空 `/proc` 仍被 OCI 拒绝，进程未启动，明确为 not_run。Linux/macOS 整库回归基准见[性能记录](benchmarks.md)，没有 Windows 组切换或 helper 的性能测量。

本次 CI 验收归档只更新文档和证据；不再修改实现、feature、锁或许可证。公共消费 API、ABI 1/Schema 1、MIT 保持原契约，实际多组、真实故障及实体设备边界仍如上文。
