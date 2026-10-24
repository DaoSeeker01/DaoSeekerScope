# Windows CPU 刷新验证

本页为单组首轮历史验收。2026-10-24 多组增量见[独立记录](windows-cpu-groups-validation.md)，不可用下文历史 CI 证明新多组路径。

本轮实现：直接检查公开 GetSystemTimes 的成功状态，每次刷新重新读计数；失败清除基线，恢复需要新的 300 ms 有效采样对。仅支持单活动处理器组；多组返回 Unsupported，不将组内用量当成整机用量。决策与迁移见 [ADR 0024](adr/0024-windows-cpu.md)。

2026-10-20 开发验证：本机 Windows x64，1 组 / 12 个逻辑处理器，独立公开 C SDK 探针与持久 Rust 进程完成初始预热、三次有效刷新、重建后重新预热。静态 CPU 信息保持缓存，动态来源 Win32、时间递增、范围 0..100；两进程采样区间不同，不要求数值相同，不制造负载或注入系统 API。开发报告位于忽略的 target/windows-cpu-local.json，明确 git_dirty=true；可归档的干净提交结果另列于后续验收章节。

测试覆盖合法 0/100 的合成计数、大整数求和、快速轮询、300 ms 边界、计数回退/无增长/异常 idle、处理器数量变化、多组拒绝、读取失败/恢复、取消前零次调用和调用后超时、能力限制/恢复、sysinfo 不再回退。SDK FILETIME 布局与高位无符号转换在 Windows 单独测试。注入错误是可复现单元输入，不代表真机触发了权限拒绝或满载。

本机最终 Rust 门禁通过：fmt、all-target/all-feature Clippy（拒绝 warning）、208 项测试、core/门面 no-default-features、doc（拒绝 warning）、CLI/FFI 构建、Linux x64/macOS arm64 交叉检查。Python Ruff/mypy 36 个文件及 94 项测试、Schema 检查通过。fuzz 格式与两个 harness 单元测试通过；本轮未在本机运行 libFuzzer campaign。C ABI collect/free、buffer 归零、空释放和旧副本拒绝通过，通用原生 CLI/C/Python 回归通过；干净提交的打包/采样归档另列。

复现命令（Windows，先准备 MSVC/Windows SDK）：

```powershell
pwsh -NoProfile -File scripts/check.ps1 -Cross
cargo build --locked -p daoseeker-scope --example dynamic_probe
pwsh -NoProfile -File scripts/build_c_example.ps1 -CpuProbe
python scripts/windows_cpu_smoke.py
python scripts/native_smoke.py
python scripts/check_packages.py --offline
```

Python 开发检查使用 jsonschema 4.25.1、Ruff 0.14.13、mypy 1.19.1；运行 `ruff format --check scripts tests examples/collect.py`、`ruff check`、`mypy --no-incremental --ignore-missing-imports`、`python -m unittest discover -s tests -p "test_*.py"`、`scripts/check_schema.py` 与 `scripts/check_project.py`。CPU 报告额外有三项负面测试，拒绝伪造成功、错误 SDK 覆盖与计数，失败/中断先覆盖旧 passed 并保留已完成观测。

以上为本机阶段记录；随后经维护者明确授权完成下述本轮推送和三平台原生 CI。原先的交叉编译证据与后续原生结果分别保留。未执行真实 API 失败、多处理器组、热插拔、长时间采样、峰值内存或专门 CPU 采样延迟 benchmark。文档中的百分比范围不是性能或精度保证；无法强制终止阻塞的内核调用。默认无标识采集，ABI 1、Schema 1、MIT 不变；只新增 windows-sys 的 Threading 绑定 feature，不增加依赖包或锁文件变化。

## 干净提交本机验收

源码 `17cdc547fc7557871ac5ab44b1857123cfdcd7b3`，工作区干净；[证据索引](evidence/windows-cpu-local-17cdc54.json)保存源码、命令、日志哈希、SDK 源文件 Git blob 及三个原始报告的 SHA-256。

- [CPU SDK/持久刷新](evidence/windows-cpu-sdk-windows-17cdc54.json)：1 组 / 12 个处理器，四次 SDK 计数、三次有效 Rust 刷新、初始及重建预热均通过。与本地打包编译并行，不作为负载或延迟 benchmark。
- [通用原生回归](evidence/windows-cpu-native-windows-17cdc54.json)：CLI、C ABI、Python FFI、存储文本与分类文本五组、16 个进程通过。新增 CPU 实验的两个进程另外计数。
- [八包独立验收](evidence/windows-cpu-packages-windows-17cdc54.json)：真实 Cargo 归档、原生验证、208 项独立测试、MIT/头文件和锁定依赖检查、安装 dscope 0.1.0 后完整 JSON 读取通过。未发布的兄弟包以本地 patch 解析，不是 registry 发布验证。

实现声明 Partial/Win32；现有核心合并器对 Unsupported 保留默认值，多组缺失字段可能显示 Unsupported/Custom/NotSupported。调用方须检查字段状态，不能以 Partial 推断多组可读。本轮保持核心合并规则，未扩大为全平台状态合并重构。


## 三平台 CI（2026-10-20）

[运行 39350478223](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/39350478223)，workflow_dispatch，源码 `fb729663bb8974c0159231106a4ce2accf112f64`，全部 8 个任务成功；一次运行通过，无修复或重跑。实现提交 17cdc54 至本次源码仅有本机验收文档和报告变更，采集代码/SDK/测试未变。

| 平台 | workspace / 八包独立测试（含 doctest） | Python 单测 | 通用原生 CLI/C/Python |
|---|---|---|---|
| Windows x64 | 208 / 208 | 94 | 五组、16 个进程通过 |
| Linux x64 | 201 / 201 | 94 | 五组、16 个进程通过 |
| macOS ARM64 | 201 / 201 | 94 | 五组、16 个进程通过 |

fmt、Clippy（拒绝 warning）、无默认 feature、doc（拒绝 warning）、Ruff/mypy（36 个源文件）、Schema/文档检查、实际 Cargo 归档、许可证/头文件、独立 CLI 安装均通过。Python 各执行 100 次默认 collect/free；未发布兄弟包使用本地 patch，不冒充 registry 发布验证。[完整证据索引](evidence/windows-cpu-ci-39350478223.json)保存十份报告、完整日志哈希、源码和逐项结果。

Windows 另外通过[公开 SDK 与持久刷新](evidence/windows-cpu-sdk-39350478223.json)：1 个处理器组、4 个活动逻辑处理器，四次 SDK 读取、三次有效 Rust 刷新、初始/重建预热正确。SDK FILETIME 为 8 字节；动态字段 Win32、时间递增、静态 CPU 保持缓存。三次观测如下，百分比是各自采样区间的结果，不要求相等：

| 观测 | Rust CPU % | 独立 SDK 区间 % |
|---|---|---|
| 1 | 0.000000 | 1.086957 |
| 2 | 3.260870 | 3.260870 |
| 3 | 2.272727 | 2.272727 |

此成功路径不证明真实 API 拒绝、计数故障、多处理器组或热插拔；错误恢复证据来自可注入测试。多组仍 Unsupported，能力 Partial 不表示本次可读，默认 Custom 缺失来源的核心兼容边界保持前述说明。

原有 [Windows 内存 SDK/64 MiB 实验](evidence/windows-cpu-pressure-39350478223.json)也重新通过；不能把瞬时可用内存变化当固定分配效果。Linux 八份容器报告全部通过，包含 CPU 15、内存/uptime 26、电池 30、hwmon 47、存储 21、GPU 20、显示器 26 项和既有 DMI/输入检查；完全空 `/proc` 挂载仍被 OCI 拒绝，保留 not_run。

11 个实际 libFuzzer 目标各运行至少 60 秒；Miri 8 项、Linux Rust FFI ASan 10 项、cargo-deny 通过。它们不直接验证 Win32 API 指针边界，不是长期无漏洞/泄漏证明。Linux/macOS 常规整库基准已执行，环境及原始日志见[性能记录](benchmarks.md)，不是 Windows CPU 采样延迟测量或物理设备验证。

验收归档不改变运行时代码。新增公开 WindowsCpuBackend、来源/多组迁移及 windows-sys Threading 绑定 feature 维持原决策；无新增依赖包/版本/锁文件，核心模型、C ABI 1、Schema 1、MIT 不变。macOS CPU/内存新鲜度、实体 Linux/macOS、真实 API 故障、多组机器、长期 native/峰值内存验证仍待后续；未发布 registry 或 release 制品。
