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

跨语言及打包的本轮结果在完成后补充。本轮没有启动新的 GitHub CI；Linux/macOS 原生运行、长期 fuzz、Miri/ASan 未重新执行，实体设备验证仍延期。不能引用上一轮通过结果代替本轮验收。

无依赖或许可证变化；C ABI 1、Schema 1 形状不变。CLI crate 的 `Command::Display` 开发版源兼容性变化见 ADR；核心 API 不变。
