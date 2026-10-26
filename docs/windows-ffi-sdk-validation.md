# Windows FFI SDK 候选包验证

SDK 将 DLL、C 头文件、导入库、C/Python 示例、Schema 和许可材料放在一起，便于其他语言接入。设计与当前 macOS 材料缺口见 [ADR 0033](adr/0033-windows-ffi-sdk.md)。这不是正式发布。

## 使用和验证入口

在干净 Windows x64 MSVC Rust 工作区、MSVC/Windows SDK、PowerShell 7 和 Python 开发依赖 jsonschema 4.25.1 可用时：

```powershell
$sdk = python scripts/cli_bundle.py --product ffi_sdk --offline
if ($LASTEXITCODE -ne 0) { throw 'build failed' }
python scripts/ffi_bundle_smoke.py $sdk
if ($LASTEXITCODE -ne 0) { throw 'SDK validation failed' }
```

依赖或工具链许可尚未缓存时去掉 `--offline`。未提交修改的调试可加 `--allow-dirty`，报告不会冒充干净提交验收。产物和 SHA256SUMS 在 target/cli-bundles 的新 candidate 目录，报告默认 target/ffi-bundle-evidence.json。无全局安装或 PATH 修改。

SDK 的 README 给出 C 编译和 Python 调用命令。C 示例只使用包内头文件和导入库，执行时 DLL 与 exe 同目录；Python 示例只需标准库并使用 DLL 绝对路径。开发门禁额外使用 jsonschema 检查 C 输出。

每次演练实际编译并运行 C 三次、运行 Python 三次，覆盖安装、切换和回滚，Python 合计 300 次 collect/free，另测空释放与 stale copy 拒绝。两份 SDK 是同一个候选；旧版本兼容尚未验证。

## 当前状态

Windows FFI SDK 格式为 3、product 为 ffi_sdk；Windows CLI v1 与 Linux CLI v2 保留，C ABI 1、硬件 Schema 1 和 MIT 不变。新增 SDK 产品负向测试和 Windows CI 入口；干净提交本机结果将单独归档，新增 CI 尚未运行。Linux/macOS FFI 包、签名、最终许可评审、最低运行环境和正式发布不在已验收范围。

macOS CLI 分发包仍未完成：[调查索引](evidence/macos-license-research-2026-10-26.json)仅记录完整许可材料缺口，不声称已获分发许可或现有 SPDX 声明无效。没有替换声明、虚构版权或绕过原有打包检查。
