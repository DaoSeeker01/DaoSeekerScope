# Windows 候选包 PE 验证

本轮补充 Windows EXE/DLL 的架构、直接依赖和版本声明检查，帮助维护者明确发布前还缺哪些运行环境证据。检查规则见 [ADR 0035](adr/0035-windows-pe-candidate-checks.md)。

## 复现

在 Windows x64、项目 Python 开发环境和 MSVC 工具链可用时运行：

```powershell
python -m unittest discover -s tests -p test_pe_inspect.py -v
$cli = python scripts/cli_bundle.py
python scripts/cli_bundle_smoke.py $cli
$sdk = python scripts/cli_bundle.py --product ffi_sdk
python scripts/ffi_bundle_smoke.py $sdk
```

在干净提交上构建；如确需检查未提交源码，构建工具的 `--allow-dirty` 会如实标记。报告仍为 `target/cli-bundle-evidence.json` 和 `target/ffi-bundle-evidence.json`，失败会覆盖旧成功结果。候选仅保存在本地，不修改 PATH，不正式发布。

## 本轮状态

实现已接入原有 CI 的 Windows CLI/SDK 步骤。原生 Release 候选与三平台回归尚待本轮验收，完成后在此记录实际源码、命令、报告与限制。测试中生成的 PE 只作为字节输入，不是 Windows 加载或设备验证证据。

## 如何解读报告

`direct_imports`、`delay_imports` 是二进制声明的直接模块名，统一小写；API-set 名称不等于磁盘上的同名 DLL。`declared_os_version` 和 `declared_subsystem_version` 是链接产物的头部字段，不能据此写成“已支持 Windows 6.0”。微软 [PE 规范](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)定义了这些结构，但实际可运行范围还取决于函数、运行库、驱动与 OS 行为。

CLI 检查一次已验证归档中的 EXE。SDK 检查一次归档 DLL，另在三个安装阶段检查各自的 C EXE 和 DLL，共六次已安装文件检查；顶层调用仍为 CLI 六进程、SDK 九次。报告没有硬件快照、DLL 完整路径或用户目录。

最低 Windows 版本、传递/运行期依赖、签名、没有 VC Runtime 的全新系统及旧正式版升级均未验证。当前检查也不读取导入函数或替代供应链、许可证和系统安全检查。实体 Linux/macOS 与多处理器组验证继续延期。
