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

Windows FFI SDK 格式为 3、product 为 ffi_sdk；Windows CLI v1 与 Linux CLI v2 保留，C ABI 1、硬件 Schema 1 和 MIT 不变。新增 SDK 产品负向测试和 Windows CI 入口；新增 CI 尚未运行。Linux/macOS FFI 包、签名、最终许可评审、最低运行环境和正式发布不在已验收范围。

2026-10-26 干净源码 `b3b47b100fca6d71796af70f84f49e9aa849e4ec` 在 Windows x64（系统报告 10.0.26300/AMD64）的本机验收：

| 项目 | 结果 |
|---|---|
| SDK ZIP | 859377 字节，78 个载荷文件及 manifest；DLL/导入库/头文件逐文件校验通过 |
| C 消费者 | 3 次以包内 C 源码、头文件和导入库编译，3 次实际执行；包内 Schema、最低读取、默认隐私和释放契约通过 |
| Python 消费者 | 3 次运行包内 ctypes 示例，合计 300 次 collect/free、空释放和 stale copy 拒绝通过 |
| 安装与回滚 | 9 个顶层子进程调用（不含编译器子孙进程）；同候选两槽位、损坏更新拒绝和回滚通过 |
| CLI 回归 | 新构建默认 Windows v1 CLI 包的六进程演练通过；此前真实 cdd8760 CLI ZIP 用新读取器验证通过，未重新执行旧程序 |
| Rust 门禁 | fmt、严格 Clippy、262 项测试含 doctest、无默认 feature、严格 rustdoc、构建及 Linux x64/macOS ARM64 cargo check 通过 |
| Python 门禁 | 149 项中 147 项通过、2 项 POSIX 权限测试跳过；9 项新增 SDK 守卫通过，54 文件 Ruff 0.14.13/mypy 1.19.1 通过 |
| 其他检查 | Schema 黄金样例/状态、项目文件/链接和 actionlint 1.7.12 通过 |

[本机验收索引](evidence/windows-ffi-sdk-local-b3b47b1.json)、[SDK 原始报告](evidence/windows-ffi-sdk-native-b3b47b1.json)、[包内 manifest](evidence/windows-ffi-sdk-manifest-b3b47b1.json)与 [CLI 回归报告](evidence/windows-ffi-sdk-cli-regression-b3b47b1.json)分别保存源码、命令和哈希。归档再次读取两个实际 ZIP，比较 SDK 内头文件、C/Python 示例和 Schema 与维护来源及提交字节。JSON 统一 LF，同时记录原文件和归档哈希；ZIP 仅在本地 target，未提交或上传。

本轮未重新运行三平台 CI、八 crate 归档、fuzz、Miri、ASan 或 benchmark；Rust crate 代码未变，此前结果保持独立。300 次 Python 调用与三次 C 执行不等于完整内存泄漏证明。

macOS CLI 分发包仍未完成：[调查索引](evidence/macos-license-research-2026-10-26.json)仅记录完整许可材料缺口，不声称已获分发许可或现有 SPDX 声明无效。没有替换声明、虚构版权或绕过原有打包检查。
