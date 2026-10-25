# Linux CLI 候选包验证

范围见 [ADR 0032](adr/0032-linux-cli-candidate.md)。GNU/Linux x86_64 候选包已通过 Ubuntu 24.04 的[原生 CI](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40245533279)构建、链接和安装/回滚。Windows 本机与 Linux CI 证据分别保留，不声明所有发行版或实体设备均已验证。

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

2026-10-26 干净源码 `cdd876046b5133d1ce7491c98c7e6d6bd563908a` 的本机记录：

| 项目 | 实际结果 |
|---|---|
| Rust 回归 | fmt、严格 Clippy、262 项测试含 doctest、无默认 feature、严格 rustdoc、构建及 Linux x64/macOS ARM64 cargo check 通过 |
| Python 回归 | 140 项中 138 项通过、2 项 POSIX mode/umask 测试跳过；52 文件的 Ruff 0.14.13、mypy 1.19.1 通过 |
| 新增 Linux 格式测试 | 11 项中 9 项通过、2 项跳过；合成字节从未作为 Linux 程序执行 |
| 真实 Windows v1 回归 | 新构建的包含 73 个载荷文件；六个包内 CLI 进程通过版本、Schema、基础读取、默认隐私、损坏更新拒绝和同候选回滚 |
| 旧 Windows v1 读取 | 真实旧源码 89fd2f9 的 ZIP 用新读取器校验通过；没有重新执行旧版本程序 |
| 结构与工作流 | Schema 黄金样例/状态守卫、项目文件/链接检查、actionlint 1.7.12 通过 |
| 本机 Linux 环境 | WSL 查询失败 Wsl/0x80070422，Docker CLI 不在 PATH；未修改服务或安装发行版 |
| Linux 原生执行 | 未执行，新增 CI 步骤尚未运行；未验证 chmod、链接器或发行版兼容性 |

[本机验收索引](evidence/linux-cli-bundle-local-cdd8760.json)的 overall 为 partial、local_checks 为 passed、native_linux_acceptance 为 not_run；明确保留两项跳过。另保存 [Windows 回归报告](evidence/linux-cli-bundle-windows-local-cdd8760.json)与[实际 Windows 包 manifest](evidence/linux-cli-bundle-windows-manifest-cdd8760.json)。归档 JSON 统一 LF，并分别记录原文件与仓库字节的 SHA-256；ZIP 留在本地 target，未提交或上传二进制。

本机阶段没有运行 Linux 原生候选步骤，随后原生 CI 验收见下节。不能从交叉 cargo check 或合成 ZIP 声称原生链接、Linux 动态库依赖或最低 glibc/发行版兼容性已验证。本机阶段未重新运行八 crate 打包、fuzz、Miri、ASan、benchmark 或三平台 CI；随后已由本轮 CI 重新运行并单独归档。此前证据保持独立。macOS、musl、其他架构与 FFI 发行包不属于本轮范围。

## 原生 CI 验收（2026-10-26）

源码 `98172d0afe77f53a8e108d5f02f2b7275ce0f25c` 的[运行 40245533279](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40245533279)全部 8 个任务通过；只手动启动一次，无运行时修复。Linux v2 候选在 Ubuntu 24.04 x86_64 完成原生 release 编译、链接、安装、模式恢复、切换、损坏更新拒绝和回滚，报告 43 个载荷文件及六个真实 CLI 进程。Windows v1 同轮回归为 73 个载荷和六个进程，通过同一版本/Schema/读取/隐私契约。

| 原生平台 | workspace Rust 含 doctest | 八个实际归档的独立测试 | Python 通过 / 跳过 |
|---|---|---|---|
| Windows x64 | 262 | 262 | 138 / 2 |
| Linux x64 | 254 | 254 | 140 / 0 |
| macOS ARM64 | 259 | 259 | 140 / 0 |

两项 POSIX 模式损坏/限制性 umask 测试在 Linux 和 macOS 实际执行并通过；macOS 的合成文件权限测试不等于 macOS 候选二进制验收。各平台 CLI/C/Python 原生检查各 5 组/16 进程，Python 含 100 次 collect/free。12 个 fuzz 目标各至少 60 秒、4 项 harness、Miri 8 项、Linux FFI ASan 10 项、cargo-deny 和 8 类容器报告通过。完整空 /proc 仍为 OCI 拒绝、进程未启动的 not_run。

[CI 验收索引](evidence/linux-cli-bundle-ci-40245533279.json)保存逐目标计数、SDK/原生/八包报告与原文件/归档哈希；[Linux 候选报告](evidence/linux-cli-bundle-candidate-linux-40245533279.json)与[Windows 回归报告](evidence/linux-cli-bundle-candidate-windows-40245533279.json)分别绑定干净源码。本机历史索引维持 partial 和两项 skipped，未用 CI 结果改写本机证据。

ZIP 留在各 runner，归档独立核验下载的报告，没有下载 ZIP 再做第二次成员校验。两槽位为同候选，旧版升级、最低 glibc/内核/发行版基线、musl、其他架构、macOS/FFI 包、签名、许可最终评审及正式发布均未验收。实体设备延期安排不变。MIT、Rust API/依赖/features/锁、C ABI 1 和硬件 Schema 1 不变；Windows bundle_format 1、Linux bundle_format 2。
