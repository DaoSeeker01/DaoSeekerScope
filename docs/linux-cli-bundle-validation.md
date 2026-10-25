# Linux CLI 候选包验证

范围见 [ADR 0032](adr/0032-linux-cli-candidate.md)。当前为 GNU/Linux x86_64 候选包的实现阶段，原生构建、链接和实际安装/回滚尚待 CI；不能把 Windows 上的格式测试当作 Linux 执行证据。

## 原生执行入口

在干净的 Linux x86_64 GNU Rust 主机上运行，Python 开发依赖为既有 jsonschema 4.25.1：

```sh
set -euo pipefail
bundle=$(python scripts/cli_bundle.py --offline)
python scripts/cli_bundle_smoke.py "$bundle"
```

`--offline` 要求依赖及 Rust 工具链许可文件已缓存；调试未提交修改可加 `--allow-dirty`，报告会记录 dirty，不能作为干净提交验收。输出位于 `target/cli-bundles/candidate-*/dscope-0.1.0-x86_64-unknown-linux-gnu.zip`，附 SHA256SUMS；报告为 `target/cli-bundle-evidence.json`。

Linux ZIP 的 bundle_format=2，记录并验证 CLI 的 0755、普通文件的 0644，以及 ZIP 的 Unix 普通文件类型。解包工具可能丢弃权限；共享演练工具在验证后显式 chmod，并在选择槽位前复核。Windows v1 格式保持不变。

包内包括 CLI、说明、项目 MIT 和目标依赖/Rust 许可文件。只在新目录安装，保留原完整目录以便回滚；不修改全局 PATH，不需要 root。两槽位使用同候选版本，不能声称旧版本升级兼容。校验和不能证明发布者身份；没有签名或正式发布。

## 当前验收状态

新增 11 项测试：Linux v2 往返及权限字段、缺失/危险权限、ZIP 权限和系统标记、普通文件类型、降级拒绝、主机选择、执行前主机拒绝，以及两个 POSIX 文件系统测试。Windows 上后两项明确跳过；未执行不是通过。

本机验证记录将绑定干净提交单独归档。Linux 原生候选步骤已加入 CI 配置，但尚未运行。不能从交叉 cargo check 或合成 ZIP 声称原生链接、Linux 动态库依赖或最低 glibc/发行版兼容性已验证。macOS、musl、其他架构与 FFI 发行包不属于本轮范围。
