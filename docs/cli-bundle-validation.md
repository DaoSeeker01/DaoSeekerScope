# Windows CLI 候选包验证

范围和限制见 [ADR 0031](adr/0031-windows-cli-candidate.md)。这是 Windows x64 CLI 的开发候选包，不是已发布版本。Rust 库、C ABI、Schema 和 MIT 许可证保持不变。

## 执行

在干净仓库内构建；第三方依赖和 Rust 文档组件已缓存时可加 `--offline`：

```powershell
$bundle = python scripts/cli_bundle.py --offline
if ($LASTEXITCODE -ne 0) { throw 'build failed' }
python scripts/cli_bundle_smoke.py $bundle
if ($LASTEXITCODE -ne 0) { throw 'rehearsal failed' }
```

ZIP 与 SHA256SUMS 位于脚本返回的 `target/cli-bundles/candidate-*/` 目录；报告默认为 `target/cli-bundle-evidence.json`。同一 ZIP 可再次验证，无需网络或重新构建。调试未提交修改需 `--allow-dirty`，此类报告不能当作干净提交验收。

归档包含 CLI、项目和上游许可正文、Rust 工具链版权/许可、说明及逐文件 manifest。只在新目录解包；原版完整目录保留以便重新选择。SHA256SUMS 用于检查传输损坏，不能证明下载来源可信；正式分发的来源、签名、运行时要求及许可覆盖仍需发布前审查。

演练为临时目录内的两槽位安装、切换、损坏更新拒绝和回滚。需要开发依赖 jsonschema 4.25.1。三次运行真实 CLI 的 `--version` 与 `--json`，检查 Schema、最低 CPU/内存/OS 读取与默认隐私；不在报告保存原始快照。两槽位为同一候选，旧版本升级兼容尚未验证。没有修改系统 PATH 或全局安装。

## 当前验收边界

2026-10-25 干净源码 `89fd2f9` 在 Windows x64（OS 报告 10.0.26300、AMD64）通过本机验收：

| 项目 | 结果 |
|---|---|
| release ZIP | 874211 字节；73 个载荷文件，另含 manifest |
| 许可文件 | 保守覆盖 28 个第三方 crate，55 份 crate 许可/版权/notice，14 份 Rust 工具链许可/版权 |
| 安装/切换/回滚 | 6 个包内 CLI 进程通过版本、Schema、最低读取和默认脱敏检查 |
| 损坏更新 | 创建安装目录前被拒绝，原选择保留 |
| Rust 门禁 | fmt、严格全目标/全 feature Clippy、262 项测试含 doctest、无默认 feature、严格 rustdoc、构建及 Linux x64/macOS ARM64 交叉检查通过 |
| Python 门禁 | 129 项测试通过，其中 13 项新增归档负向测试；51 文件的 Ruff 0.14.13 与 mypy 1.19.1 通过 |
| 数据与工作流 | Schema 黄金样例/状态守卫、项目文件与本地链接、actionlint 1.7.12 通过 |

[验收索引](evidence/windows-cli-bundle-acceptance-89fd2f9.json)记录报告哈希、命令及未执行项；[原始演练报告](evidence/windows-cli-bundle-local-89fd2f9.json)、[包内 manifest](evidence/windows-cli-bundle-manifest-89fd2f9.json)、[原始 SHA256SUMS](evidence/windows-cli-bundle-SHA256SUMS-89fd2f9.txt)保留源码与逐文件校验依据。ZIP 留在本地 target，未提交二进制或上传制品。归档流程再次核验 ZIP、全部成员及 Cargo.lock 哈希。

两份 Windows 原始报告通过精确 `.gitattributes -text` 规则保留 CRLF 字节，避免 Git 的 LF 规范化改变索引所记录的原文件哈希；同时核验已提交 blob 的哈希。

新增 Windows CI 步骤尚未执行。Linux/macOS 制品、FFI 动态库发行包、干净 Windows 镜像的运行时依赖、代码签名和正式发布尚未验收。本轮没有修改 Rust 采集/FFI 代码，未重跑八 crate 归档、fuzz、Miri、ASan 或 benchmark；上一轮证据继续保留，不能当作本轮新运行。三平台实体设备验证的延期安排不变。
