# macOS uptime 验证

契约见 [ADR 0028](adr/0028-macos-uptime.md)。以下首先保留 2026-10-22 Windows 本机阶段记录，当时 macOS SDK/链接/采样未执行；2026-10-23 原生 CI 已通过，详见下节。交叉编译仍不等于原生成功。

现有 MacosBackend 每次动态采集 boot-before → time → boot-after，来源 Sysctl/Partial；sysctl 失败不回退 epoch 0，长度/数据不合格不发布值，time 的 -1 哨兵映射 Unknown 而非残留 errno。两次启动时间不同为暂不可用，失败后无旧值，可在后续直接恢复。保留原来的整秒差口径，不承诺单调/精确 elapsed 或仅清醒时长。静态不查询 uptime，动态保持静态缓存；现有单元构造不变，单独 SysinfoBackend 用户须补 MacosBackend 或用门面。

可复现本地门禁：

```powershell
pwsh -NoProfile -File scripts/check.ps1 -Cross
cargo clippy --locked --workspace --all-targets --all-features --target aarch64-apple-darwin -- -D warnings
python -m unittest discover -s tests -p "test_*.py"
python scripts/check_schema.py
python scripts/check_project.py
cargo fmt --manifest-path fuzz/Cargo.toml --check
cargo test --locked --manifest-path fuzz/Cargo.toml --lib
pwsh -NoProfile -File scripts/build_c_example.ps1
python scripts/check_packages.py --offline
python scripts/native_smoke.py --output target/macos-uptime-native-clean.json
```

2026-10-22 Windows x64 本机门禁通过：fmt、严格 Clippy、240 项 Rust 测试含 doctest、无默认 feature、doc、FFI/CLI 构建、Linux x64/macOS ARM64 交叉检查及 macOS 全 target 严格 Clippy；Ruff 0.14.13 format/check、mypy 1.19.1（44 文件）、109 项 Python 测试、jsonschema 4.25.1 Schema 与项目/链接检查通过。原生 Windows C ABI 收集/释放/清零/重复空释放/旧副本拒绝通过；fuzz 入口 fmt 和两个共享守卫单元测试通过。本机阶段 macOS ARM64/Intel 原生、独立 C SDK、持续刷新及三平台 CI 尚未执行；随后 ARM64 原生 CI 结果见下节，Intel 原生仍未验证。实体 Mac 按维护者设备安排延期。

实现源码 `bfd28d57729c8e70da57d92623b582623cd7c386` 的工作区干净，已完成以下归档，均不作为 macOS 原生成功证据：

- [完整索引](evidence/macos-uptime-local-bfd28d5.json)：源码、命令、日志/报告哈希和明确的 not_run 项。
- [八包报告](evidence/macos-uptime-packages-windows-bfd28d5.json)：八个实际归档、原生 Cargo 验证、提取后的独立 workspace 240 项测试及 release profile CLI 安装；本地 patch 解决未发布的相邻 crate，不是 registry 发布验收。
- [Windows 原生报告](evidence/macos-uptime-native-windows-bfd28d5.json)：CLI/C/Python 五组、16 个进程通过，含 100 次 Python collect/free。

完整 Rust 和 Python 门禁在实现提交前执行，提交后运行代码和守卫未改变；原生与八包报告均绑定同一干净实现提交。随后本轮归档提交只改文档/证据，不追加运行时代码或平台声明。

macOS 原生复现入口（后续 ARM64 CI 已执行）：

```sh
mkdir -p target
cc -Wall -Wextra -Werror -std=c11 docs/research/macos_uptime_probe.c -o target/macos-uptime-probe
target/macos-uptime-probe < /dev/null
cargo test --locked -p daoseeker-scope-macos public_boot_time_and_time_match_native_sdk_contract -- --nocapture
cargo build --locked -p daoseeker-scope --example dynamic_probe
python scripts/macos_uptime_smoke.py
```

探针以两进程检查 collect、三次间隔 1.1 秒 refresh 和 rebuild；SDK 在 Rust 每次调用前后采样，区间比较以整数秒为单位，不要求两个进程相等。静态模型保持缓存、刷新采集时间前进；受控不调时的测试检查跨秒增长，不能据此宣称字段在调时或睡眠等场景下单调。命令有界、行上限 1 MiB、读/退出等待 5 秒，失败先覆盖旧成功报告；只保留 uptime、类型大小、次数、来源/制品哈希，不输出原始 boot epoch 或系统错误。C SDK 与 Rust 固定 LP64 timeval/time_t 大小和字段偏移，原生实际读取的后续 CI 结果见下节。

八项可注入测试已通过，覆盖长度/符号/微秒验证、合法零与 i64 大数精确整数差、Darwin errno 和时间哨兵分离、每个失败位置短路、启动时间秒/微秒变化、成功→失败→恢复、每个调用前后的取消/超时，以及 Hardware 静态缓存/字段失败隔离。它们不是实际设备权限或系统时钟故障实验。

无新解析器或输入格式，本轮不增加 fuzz target。本机阶段未执行真实 fuzz campaign、Miri、ASan 或 benchmark；随后 CI 的短期回归与整库基准见下节；没有睡眠/休眠/重启/调时/沙盒/真实 API 故障、长期泄漏或强制取消 OS 调用证明。两次启动时间一致不排除 ABA 或读间时钟变化。

项目 MIT、ABI 1、Schema 1、公共类型/签名、依赖、feature 与两个锁文件不变；未发布 registry 或 release。


## 三平台原生 CI 验收（2026-10-23）

[运行 39878588965](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/39878588965)，源码 `8500cc848a72fed9994e7e51bcf7e46db4503bf1`，八个任务全部成功，无需 CI 运行时代码修复。[完整索引](evidence/macos-uptime-ci-39878588965.json)绑定十四份报告、源码与 SHA-256；本轮验收归档仅修改文档。

| 平台 | workspace / 八包独立测试（含 doctest） | Python 单测 | 原生 CLI/C/Python |
|---|---|---|---|
| Windows x64 | 240 / 240 | 109 | 五组、16 个进程通过 |
| Linux x64 | 233 / 233 | 109 | 五组、16 个进程通过 |
| macOS ARM64 | 238 / 238 | 109 | 五组、16 个进程通过 |

各平台 fmt、Clippy（拒绝 warning）、无默认 feature、doc（拒绝 warning）、Ruff/mypy（44 文件）、Schema/项目检查、八包原生 Cargo 验证和提取后独立测试/CLI 安装均通过。Python 各执行 100 次 collect/free；兄弟包使用本地 patch，不代表 registry 发布验收。macOS uptime 定向原生读取测试在 workspace 前另执行一次，已包含在 workspace 的 238 项中，不重复加计。

macOS [SDK 夹取与持久刷新](evidence/macos-uptime-sdk-39878588965.json)报告确认两个独立进程的五帧读取通过；C SDK time_t 为 8 bytes，timeval 为 16 bytes，boot 复核稳定。Rust 原生布局编译检查和真实读取测试通过。初次 collect、三次刷新和重建来源均为 Sysctl、Available、无缺失原因；刷新保持完整静态缓存。

| 操作 | Rust uptime seconds | SDK 前 / 后 seconds |
|---|---|---|
| collect | 539 | 539 / 539 |
| refresh 1 | 541 | 541 / 541 |
| refresh 2 | 542 | 542 / 542 |
| refresh 3 | 543 | 543 / 543 |
| rebuild | 543 | 543 / 543 |

逐项满足 `before <= value <= after`，不要求不同进程的值相等。受控测试跨秒增长不证明日历时间推导量在调时/睡眠等场景下单调；两次启动时间一致也不能排除 ABA。保持 Partial，不改变原整秒差或 time(-1) 的 Unknown 策略。原始 boot epoch 未写入报告。

Windows [uptime SDK](evidence/macos-uptime-windows-uptime-sdk-39878588965.json)、[CPU SDK](evidence/macos-uptime-windows-cpu-sdk-39878588965.json)、[64 MiB 内存实验](evidence/macos-uptime-windows-memory-sdk-39878588965.json)，macOS [CPU SDK](evidence/macos-uptime-macos-cpu-sdk-39878588965.json)与[内存 SDK](evidence/macos-uptime-macos-memory-sdk-39878588965.json)回归通过。CPU 独立采样区间和内存值允许不同；macOS VM 缓存/限流及估计口径不变。

Linux 八份容器报告通过：CPU 15、内存/uptime 26、电池 30、hwmon 47、存储 21、GPU 20、显示器 26 项及既有 DMI/输入检查；完全空 `/proc` 被 OCI 拒绝，进程未执行，仍为 not_run。

11 个实际 fuzz 目标各运行至少 60 秒；Miri 8 项、Linux Rust FFI ASan 10 项及 cargo-deny 通过。它们不是 macOS 系统调用的真实故障实验或长期无漏洞证明。Linux/macOS 常规整库基准见[性能记录](benchmarks.md)，不等于单次 sysctl/time 调用性能或配对改善。

MIT、依赖/features/两个锁文件、公共类型/签名、C ABI 1、Schema 1 不变。仍待实体 Mac/Linux、Intel 原生、真实权限/时间 API 故障、沙盒、调时/睡眠/重启、长期 fuzz/泄漏/峰值内存与发行验证。动态数据可靠性工作包仍有 Windows 多处理器组覆盖，其他首版任务见[剩余工作](progress.md)。
