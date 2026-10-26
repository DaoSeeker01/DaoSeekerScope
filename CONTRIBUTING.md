# 贡献指南

欢迎修复问题、补充平台证据、改进文档或讨论功能。先搜索已有 Issue；较大的改动建议先说明使用场景和兼容性影响。安全漏洞按[安全政策](SECURITY.md)私密报告，交流请遵守[社区规范](CODE_OF_CONDUCT.md)。

一次提交尽量解决一个明确问题。保留现有架构和有效测试，为修复增加能复现问题的回归测试；不用为了增加字段数量而返回占位值。

需要 Rust 1.96、Python 3.11+；Windows 的 C 示例还需要 MSVC 和 Windows SDK。工具通过 PATH 调用，不依赖维护者的磁盘路径。`rust-toolchain.toml` 和 `mise.toml` 记录固定版本；CI 在三个原生桌面系统运行。

## Rust 检查

在项目根目录运行：

```sh
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features -- --test-threads=1
cargo check --locked -p daoseeker-scope-core --no-default-features
cargo check --locked -p daoseeker-scope --no-default-features
cargo doc --locked --workspace --all-features --no-deps
```

文档检查设置 `RUSTDOCFLAGS="-D warnings"`。PowerShell 可执行 `pwsh -NoProfile -File scripts/check.ps1`；加 `-Cross` 时，需要先安装 `x86_64-unknown-linux-gnu` 和 `aarch64-apple-darwin` 两个目标。交叉 check 只代表编译，不代表原生运行。

## 工具、Schema 与文档

建议创建项目内虚拟环境，避免修改全局 Python：

```sh
python -m venv .venv
```

PowerShell 执行 `.venv/Scripts/Activate.ps1`；Linux/macOS 执行 `. .venv/bin/activate`。随后运行：

```sh
python -m pip install -r requirements-dev.txt
ruff format --check scripts tests examples/collect.py
ruff check scripts tests examples/collect.py
mypy --no-incremental --ignore-missing-imports scripts tests examples/collect.py
python -m unittest discover -s tests -p "test_*.py"
python scripts/check_schema.py
python scripts/check_project.py
```

项目检查读取 Git 跟踪文件及未忽略的新文件，检查 JSON/TOML/YAML、重复 YAML 键、Python 语法、本地文档链接、版本号和黄金样例副本一致性。原始 fuzz 种子允许损坏字节。它不验证外部网站、Markdown 锚点，也不代替代码审查。工作流另外用 actionlint 1.7.12 检查。

打包与独立安装检查运行 `python scripts/check_packages.py`；已缓存依赖可加 `--offline`。它检查实际 crate 归档中的 MIT 和 FFI 头文件，再用解包后的文件运行测试、安装 CLI。依赖未发布时使用本地 patch，不能据此声称真实 registry 安装通过。完整命令和 Cargo 1.96 验证限制见[打包指南](docs/packaging.md)。

## 跨语言与负面测试

先构建 `cargo build --locked -p daoseeker-scope-ffi -p daoseeker-scope-cli`。Windows：`pwsh -NoProfile -File scripts/build_c_example.ps1`，可用 `-VcRoot`、`-SdkRoot`、`-SdkVersion` 指定安装。

Linux/macOS：

```sh
cc -Wall -Wextra -Werror examples/collect.c -Ltarget/debug -ldaoseeker_scope_ffi -Wl,-rpath,"$PWD/target/debug" -o target/debug/c-example
python scripts/native_smoke.py
```

`native_smoke.py` 验证 CLI、C 和 Python，并将脱敏执行证据写入 `target/native-evidence.json`。Linux 容器与内核权限检查需要 Docker，入口为 `scripts/linux_*_smoke.py`。失败、未运行和受限必须分别记录。

## Fuzz、内存与性能

Fuzz 目标与命令见 [fuzz 指南](fuzz/README.md)。Miri 使用 `nightly-2026-10-08` 的 miri/rust-src 组件：`pwsh -NoProfile -File scripts/check_miri.ps1`。它验证内存契约，不执行原生系统 API。

CI 另有 Rust FFI AddressSanitizer 和 cargo-deny 门禁。性能入口：`cargo bench --locked -p daoseeker-scope --bench collect`；记录平台、profile 和真实/合成数据范围，参考[性能报告](docs/benchmarks.md)。

## 提交变更

保持 `Observed<T>` 的状态、来源和原因语义；公共类型不要泄漏平台依赖。新增字段、能力和兼容性行为应更新 [ADR](docs/README.md)、Schema 与回归测试。不要将编译、模拟输入测试或空集合称作真实设备验收。历史证据保留原始 source commit 和失败记录；当前验证另存新报告。

PR 请说明问题、行为变化、实际测试和未验证范围；用户可见的变化记录到[更新日志](CHANGELOG.md)。文字要直接说明含义和限制，不把内部调试表示当作面向用户的解释。

版本号集中在 workspace；内部路径依赖随之更新，crate 继承 workspace 版本。C ABI、JSON Schema 和私有候选包格式分别管理，不随 Rust 包版本自动变更。正式发布前逐项核对 [v0.1 清单](docs/v0.1-checklist.md)，不自行创建发布标签或上传制品。
