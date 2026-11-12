# Rust 公共 API 基线

这里保存 Core 与主库编译后的公开接口，供变更评审使用。每个包分别检查默认、关闭默认、仅 `serde`、仅 `schema` 四种配置。索引记录生成设置和八份文件的 SHA-256。

## 运行检查

在项目根目录安装固定的开发工具：

```sh
rustup toolchain install nightly-2026-10-08 --profile minimal
cargo install cargo-public-api --version 0.52.0 --locked --root target/public-api-tools --target-dir target/public-api-tool-build
python scripts/check_public_api.py --offline
```

需要干净的 Git 提交及本机目标依赖缓存；首次缺少项目依赖时去掉 `--offline`。工具通过 `cargo rustdoc --locked` 生成 JSON，再交给固定版本的 cargo-public-api 格式化。检查保留自动 trait 和派生实现，省略 blanket implementations（对一类类型普遍适用的泛型实现），不比较参数名称。

接口变化会使检查失败，可读差异保存在 `target/public-api-diffs/`。结果写入 `target/public-api-evidence.json`，包含源码提交、目标、工具链、配置及实际输出哈希。失败或中断不会沿用旧的成功报告。桌面 CI 在 Windows、Linux 和 macOS 原生执行并上传结果。

## 接口有意变更时

先说明兼容性影响，并同步测试和相关文档，再运行：

```sh
python scripts/check_public_api.py --offline --update
git diff -- docs/contracts/public-api
```

更新命令允许工作区有改动。评审八份接口及索引后提交，再在干净提交上重新检查；更新基线本身不算验收。普通检查不会改写基线。

这项检查覆盖上述两个包与四种配置中工具可提取的接口，不覆盖其他 backend 包、所有 feature 组合或运行行为，也不自动判断变更是否符合语义化版本要求。版本与行为仍需按[契约评审表](../../v0.1-contract-review.md)核对。
