# Windows uptime 验证

本轮契约见 [ADR 0027](adr/0027-windows-uptime.md)。现有 sysinfo Windows 路径已经逐次读取相同 API；迁移目的为显式平台来源和可复现刷新验收，不声称修复缓存错误。

实现：现有 WindowsBackend 动态读取 GetTickCount64，整数毫秒向下取秒，来源 Win32、能力 Partial。静态不读取该计时器；不缓存动态值。取消检查包围调用，合法零保留，无 GetLastError 或虚构 API 失败。单独 SysinfoBackend 的 Windows 用户需补 WindowsBackend 或使用门面。

可复现命令：

```powershell
pwsh -NoProfile -File scripts/check.ps1 -Cross
cargo build --locked -p daoseeker-scope --example dynamic_probe
pwsh -NoProfile -File scripts/build_c_example.ps1 -UptimeProbe
python scripts/windows_uptime_smoke.py
python -m unittest discover -s tests -p "test_*.py"
python scripts/check_schema.py
python scripts/check_project.py
python scripts/check_packages.py --offline
python scripts/native_smoke.py --output target/windows-uptime-native-clean.json
cargo fmt --manifest-path fuzz/Cargo.toml --check
cargo test --locked --manifest-path fuzz/Cargo.toml --lib
```

2026-10-22 Windows x64 笔记本本机通过：完整 Rust 门禁（fmt、严格 Clippy、232 项测试含 doctest、无默认 feature、doc、FFI/CLI 构建）、Linux x64/macOS ARM64 交叉检查及 macOS 全 target 严格 Clippy；Python ruff/mypy 42 文件、106 项测试、Schema 和项目文档守卫；原生 C ABI 及独立 uptime SDK 探针。fuzz 入口 fmt 和两个共享守卫单元测试通过，未运行 campaign。以下为推送前本机结果；后续三平台 CI 已通过，详见下节。C 探针为公开 Windows SDK 编译，两进程用有界命令/1 MiB 行上限/5 秒读与退出等待，报告仅保留 uptime 元数据、来源版本和制品哈希。初次 collect、三次间隔 1.1 秒 refresh、重建 collect 均检查 C SDK 前后毫秒夹取；刷新时完整静态模型保持不变，间隔跨秒后计数增长。短间隔相同秒数是合法结果。失败先覆盖旧成功报告并最终保留 failed，不输出原始系统错误或设备标识。

实现提交 `7b79a17c1476beda09c4ae100685f7ca1ef1c5c0` 的工作区干净，已完成：

- [本机索引](evidence/windows-uptime-local-7b79a17.json)：命令、来源与日志/报告哈希，明确未运行项。
- [八包验收](evidence/windows-uptime-packages-7b79a17.json)：实际归档、原生 Cargo 验证、提取后的独立 workspace 232 项测试及 release profile CLI 安装；本地 patch 解决未发布的相邻 crate，不是 registry 发布验收。
- [原生报告](evidence/windows-uptime-native-7b79a17.json)：5 组、16 个进程通过，含 CLI/C/Python 与 100 次 Python collect/free。
- [SDK 夹取报告](evidence/windows-uptime-sdk-7b79a17.json)：两进程五次观测均通过，细节如下。

| 操作 | Rust seconds | SDK 前 / 后 milliseconds |
|---|---|---|
| collect | 1174 | 1174093 / 1174125 |
| refresh 1 | 1175 | 1175234 / 1175234 |
| refresh 2 | 1176 | 1176343 / 1176343 |
| refresh 3 | 1177 | 1177437 / 1177453 |
| rebuild | 1177 | 1177453 / 1177453 |

每项检查 `floor(before/1000) <= value <= floor(after/1000)`，不要求两个进程毫秒数严格相等。通用门禁在实现提交前执行，提交后运行代码和守卫未改变；八包、原生与 SDK 报告均绑定同一干净实现提交。后续本轮归档提交仅修改文档/证据。

纯逻辑测试覆盖零、999/1000 ms 取整、超过 32 位、u64 最大值、重复/重新开始的计数域、每次调用次数与取消前后检查。Python 守卫拒绝 bool/浮点伪整数、越界、错误来源/状态/原因/时间、逆序 SDK 区间和错误调用计数。模拟检查失败不冒充真实 OS API 故障。

未实验验证：系统睡眠/休眠、重启/快速启动、checked kernel 偏移和长期运行。微软说明计时包含睡眠/休眠且受系统粒度影响；不能据此声称这些场景已由本机测试。Windows 之外的交叉编译不能替代原生运行；macOS uptime 路线本轮不变。本机阶段未执行 benchmark 或实际 fuzz campaign；随后 CI 的整库基准和短 fuzz 见下节，长期 campaign 仍未执行。

ABI 1、Schema 1、MIT、锁文件、依赖版本与 feature 不变；本轮无新增发行或 registry 安装声明。


## 三平台 CI 验收（2026-10-22）

[运行 39755735940](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/39755735940)，源码 `8fce1893765436c57313634fde55c1ea79d6f7da`，八个任务全部成功，无需本轮 CI 运行时代码修复。[完整索引](evidence/windows-uptime-ci-39755735940.json)保存十三份报告、源码与 SHA-256；归档仅修改文档。

| 平台 | workspace / 八包独立测试（含 doctest） | Python 单测 | 原生 CLI/C/Python |
|---|---|---|---|
| Windows x64 | 232 / 232 | 106 | 五组、16 个进程通过 |
| Linux x64 | 225 / 225 | 106 | 五组、16 个进程通过 |
| macOS ARM64 | 229 / 229 | 106 | 五组、16 个进程通过 |

各平台 fmt、Clippy（拒绝 warning）、无默认 feature、doc（拒绝 warning）、Ruff/mypy（42 文件）、Schema、项目守卫、八包原生 Cargo 验证/提取后的独立测试及 CLI 安装均通过。Python 各执行 100 次 collect/free。兄弟包用本地 patch，不等于 registry 发布或 release 分发。macOS 定向 VM SDK preflight 也通过，其测试已包含在 workspace 229 项中，不重复加计。

Windows [独立 SDK 夹取](evidence/windows-uptime-sdk-39755735940.json)确认两进程的五次读取均在相应区间，三次刷新保持完整静态缓存：

| 操作 | Rust seconds | SDK 前 / 后 milliseconds |
|---|---|---|
| collect | 499 | 499593 / 499625 |
| refresh 1 | 500 | 500718 / 500734 |
| refresh 2 | 501 | 501828 / 501828 |
| refresh 3 | 502 | 502937 / 502937 |
| rebuild | 502 | 502937 / 502937 |

来源均为 Win32、状态 Available、无缺失原因。以 SDK 前后计数作边界，不比较不同进程值必须相等，不通过墙钟反推启动时刻。Capability 仍 Partial，秒取整/OS 粒度、包含睡眠/休眠及 checked build 偏移边界不变。没有睡眠、休眠、重启或快速启动实验。

Windows [CPU SDK](evidence/windows-uptime-windows-cpu-sdk-39755735940.json)、[64 MiB 内存实验](evidence/windows-uptime-windows-memory-sdk-39755735940.json)，macOS [CPU SDK](evidence/windows-uptime-macos-cpu-sdk-39755735940.json)和[内存 SDK](evidence/windows-uptime-macos-memory-sdk-39755735940.json)回归通过。不同进程的 CPU 区间和内存值允许不同；macOS VM 统计的 OS 缓存/限流与估计口径不变。这些回归不扩展本轮 Windows uptime 声明。

Linux 八份容器报告通过：CPU 15、内存/uptime 26、电池 30、hwmon 47、存储 21、GPU 20、显示器 26 项及既有 DMI/输入检查。完全空 `/proc` 仍被 OCI 拒绝，进程未执行，保留 not_run。

11 个实际 fuzz 目标各运行至少 60 秒，Miri 8 项、Linux Rust FFI ASan 10 项及 cargo-deny 通过。它们不是 Windows API 的真实失败实验，也不是长期无漏洞证明。Linux/macOS 常规整库基准见[性能记录](benchmarks.md)，不宣称 uptime 单次调用性能或有配对的改善。

无依赖/feature/锁变更，MIT、公共类型/签名、C ABI 1、Schema 1 不变。仍待验证实体 Linux/macOS、Windows 多处理器组、睡眠/休眠/checked kernel、长期 fuzz/泄漏/峰值内存和正式发行；下一独立切片为 macOS uptime 可靠性。
