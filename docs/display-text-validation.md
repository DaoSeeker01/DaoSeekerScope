# 显示器 CLI 文本验证

本轮新增 `dscope display`，契约见 [ADR 0022](adr/0022-display-cli.md)。实现仅在 CLI 展示层与测试守卫，不修改任何平台采集器、核心模型、ABI/Schema 或隐私规则。

2026-10-19（Asia/Shanghai），Windows x64 本机已执行：

| 命令 | 结果及边界 |
|---|---|
| `pwsh -NoProfile -File scripts/check.ps1 -Cross` | fmt、workspace/all-target/all-feature clippy（拒绝警告）、189 项测试、无默认 feature、doc（拒绝警告）、CLI/FFI 构建通过；Linux x64/macOS ARM64 交叉 check 通过，只代表编译 |
| 固定开发工具运行 Ruff format/check、mypy、`python -m unittest discover -s tests -p "test_*.py"` | 32 个 Python 源文件静态检查、88 项测试通过；包含故意失败的 SDK 比较负例，其输出不代表实际 macOS 验证失败 |
| `python scripts/check_schema.py`、`python scripts/check_project.py` | Schema/黄金样例、观测不变量、版本/未知字段策略及本地文档检查通过 |
| `cargo fmt --manifest-path fuzz/Cargo.toml --check`、`cargo test --locked --offline --manifest-path fuzz/Cargo.toml --lib` | harness 的 2 项回归通过；不是实际 libFuzzer campaign |
| `target/debug/dscope.exe display`、`--help`、`--version` | 一条 Win32 活动路径；名称 Unavailable/NotPresent，信号宽高分别为 1920/1080；帮助包含 display，版本仍 0.1.0 |

本轮新增五项 Rust 测试和两项 Python 测试，既有全命令集成回归也加入 display。合成跨来源文本覆盖 Win32、AppleApi、Drm/Custom 的标签和缺失状态，只证明展示，不证明对应实体设备读取。默认文本与 JSON 不跨进程比较设备数或尺寸。

实现提交为 `560e6f16dd324df30c864988583f0b11a8ea17a3`。后续在该提交的干净工作区完成：

- `pwsh -NoProfile -File scripts/build_c_example.ps1`：MSVC 严格警告构建通过；实际 C collect/free、清零、空释放和陈旧副本拒绝通过。
- 固定 Python 开发环境运行 `scripts/native_smoke.py`：五组检查、16 个进程通过，包括新的 display 文本守卫；Python 100 次 collect/free 沿用既有 smoke 契约。默认文本有两个可用尺寸字段和一个缺失名称字段，不保存名称/原始文本。CLI 与 C JSON 各自记录状态，不要求不同进程设备数/尺寸相同。
- `python scripts/check_packages.py --offline`：八个实际 crate 归档、MIT/C 头文件、解包后 189 项测试、独立 CLI 安装和完整 JSON 通过；第三方锁文件保持不变。使用本地 patch 解析未发布的兄弟 crate，不代表 registry 发布验收。

脱敏[原生报告](evidence/display-text-native-windows-560e6f1.json)、[打包报告](evidence/display-text-packages-windows-560e6f1.json)及[本轮索引和哈希](evidence/display-text-local-560e6f1.json)保留原始 source commit。归档时仅补充文档/证据，并移除新增 cli_args 种子的尾换行，避免解析出额外空参数；没有修改已验证的 Rust/平台采集代码。种子最终为 `display\n--json`，与解析单测覆盖的参数相同；这不算实际 fuzzer 运行证据。

以上是推送前的本机阶段记录；随后经维护者明确授权推送并执行了下述本轮 CI。实体设备验证仍按设备安排延期。

无依赖或许可证变化；C ABI 1、Schema 1 形状不变。CLI crate 的 `Command::Display` 开发版源兼容性变化见 ADR；核心 API 不变。

## 三平台 CI（2026-10-19）

[运行 39178858567](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/39178858567)，事件 workflow_dispatch，源码 `7da6f60c836ade85c70604215e3f0a79ad44bcff`，全部 8 项任务通过；没有 CI 修复或重跑。实现至 CI 之间只有本地验证归档和 cli_args 种子尾换行修正，Rust 展示/采集代码不变。

| 平台 | Rust workspace / 八包独立测试（含 doctest） | Python 单测 | 原生 CLI/C/Python |
|---|---|---|---|
| Windows x64 | 189 / 189 | 88 | 五组检查、16 个进程通过 |
| Linux x64 | 185 / 185 | 88 | 五组检查、16 个进程通过 |
| macOS ARM64 | 185 / 185 | 88 | 五组检查、16 个进程通过 |

三平台 fmt、clippy、无默认 feature、doc、Ruff/mypy（32 源文件）、Schema、文档、归档许可/头文件及安装均通过。Python 各执行 100 次默认 collect/free。记录见[本轮证据索引](evidence/display-text-ci-39178858567.json)，保留源码、各报告 SHA-256、完整工作流日志 SHA-256 和实际命令结果。

显示器文本每平台成功展示一条 OS 视图，既不是实体显示器计数，也不代表所有字段都可用：

- Windows：文本可用字段 1、缺失字段 2；CLI JSON 集合为 available/win32，名称状态单独保留于[原生报告](evidence/display-text-native-windows-39178858567.json)。本轮名称 Available，信号宽高均 Unavailable/InvalidData；不将缺失值补零，也不猜具体原生失败条件。不同进程的 JSON、文本和 SDK 是独立观测，不承诺拓扑原子一致。
- Linux：文本可用字段 0、缺失字段 3；CLI JSON 集合为 available/drm，名称状态单独保留于[原生报告](evidence/display-text-native-linux-39178858567.json)。默认名称 Restricted/PrivacyRedacted；当前宽高 Unsupported，不把 modes/EDID 时序当作成功尺寸。不同进程的 JSON、文本和 SDK 是独立观测，不承诺拓扑原子一致。
- macOS：文本可用字段 2、缺失字段 1；CLI JSON 集合为 available/apple_api，名称状态单独保留于[原生报告](evidence/display-text-native-darwin-39178858567.json)。本轮模式像素 1024×768，名称 Unsupported；[独立 C SDK 比较](evidence/display-text-sdk-comparison-39178858567.json)通过。不同进程的 JSON、文本和 SDK 是独立观测，不承诺拓扑原子一致。


Linux 的八份容器回归报告通过，覆盖 CPU 15、内存/运行时长 26、电池 30、hwmon 47、整块存储 21、GPU 20、显示器 26 项及既有 DMI/输入检查。完整空 `/proc` 挂载仍被 OCI 拒绝，明确为 not_run，不是该场景已通过。

本轮 11 个实际 libFuzzer 目标各运行至少 60 秒，包含新增 display 参数种子；Miri 8 项、Linux Rust FFI ASan 10 项和 cargo-deny 通过。短 campaign 不证明长期无漏洞，也不直接验证 Core Graphics/Win32 驱动内存边界。

CI 还执行了 Linux/macOS 的整库采集基准；[性能记录](benchmarks.md)与索引中的原始日志保留实际参数和结果，不将它称为 CLI 启动/渲染性能。

实体 Linux/macOS、多屏/镜像/Retina/热插拔、长期 fuzz/原生泄漏及峰值内存验证仍未完成；托管 runner 与合成容器不能替代这些设备证据。本轮没有 registry 发布或 release 制品分发。
