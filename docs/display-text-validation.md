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

本轮没有启动新的 GitHub CI，也没有推送远程。Linux/macOS 原生运行、长期 fuzz、Miri/ASan 未重新执行，实体设备验证仍延期。不能引用上一轮通过结果代替本轮验收。

无依赖或许可证变化；C ABI 1、Schema 1 形状不变。CLI crate 的 `Command::Display` 开发版源兼容性变化见 ADR；核心 API 不变。
