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

本轮增加归档负向单元测试和 Windows CI 步骤。干净提交的本机结果将单独归档；新增 CI 尚未执行。Linux/macOS 制品、FFI 动态库发行包、干净 Windows 镜像的运行时依赖、代码签名和正式发布尚未验收。
