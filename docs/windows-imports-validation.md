# Windows 导入符号验证

候选包检查现可列出具体导入名称和序号，包括普通与延迟导入。既有 DLL 名单保留，新增清单只供兼容性评审使用，不表示已支持某个最低 Windows 版本。规则、数量上限及来源见 [ADR 0048](adr/0048-windows-import-symbols.md)。

## 复现

需要 Windows x64、MSVC、Windows SDK、PowerShell 7 和项目 Python 开发环境。在干净提交运行：

```powershell
$cli = python scripts/cli_bundle.py --offline
if ($LASTEXITCODE -ne 0) { throw 'CLI build failed' }
python scripts/cli_bundle_smoke.py $cli
if ($LASTEXITCODE -ne 0) { throw 'CLI rehearsal failed' }
$sdk = python scripts/cli_bundle.py --offline --product ffi_sdk
if ($LASTEXITCODE -ne 0) { throw 'SDK build failed' }
python scripts/ffi_bundle_smoke.py $sdk
if ($LASTEXITCODE -ne 0) { throw 'SDK rehearsal failed' }
python scripts/windows_imports_smoke.py $cli $sdk
if ($LASTEXITCODE -ne 0) { throw 'DUMPBIN comparison failed' }
```

CLI/SDK 演练运行真实消费者；最后的 DUMPBIN 对照不执行图像。它重新编译 C 消费者与一个只用于检查的 USER32 延迟导入样例，报告写到 `target/windows-imports-evidence.json`。没有全局安装、PATH 修改或制品发布。离线构建要求依赖已缓存。

## 已验证与待验证

本机 Python 全套 315 项中 309 通过、6 跳过。PE 定向测试 19 项通过，含新增 7 项符号回归；独立对照工具新增 5 项测试通过。覆盖名称大小写、序号全范围、保留位、普通/延迟分离、未绑定回退、截断/终止符、单表/合计上限、工具文本解析、图像变化、旧候选及失败/中断报告作废。

真实 MSVC 延迟导入样例已完成编译，其名称清单与 DUMPBIN 一致，样例没有运行。最初把最简合成 PE 交给 DUMPBIN 时触发了工具的 LNK1000/C0000094 内部错误；这不是通过记录。正式对照只接收当前源码编译的候选与样例，损坏字节测试由自有解析器完成。另对真实 PE 的副本作静态序号变异，确认 DUMPBIN 用十进制显示序号；变异文件未运行，不能当作真实加载验证。

准备阶段发现一处 Windows SHA256SUMS 的 CRLF 兼容问题、一个未用导入与一个类型收窄遗漏，已修正。最早的新清单测试因缺少 `direct_symbols` 报 KeyError，日志保留为未实现时的对照。上轮额度曾阻止自动审批，未执行的命令未计入结果；额度恢复后沿原审批流程继续。

干净源码的四图像完整对照、候选安装回归和三平台 CI 尚待执行，完成后追加原始报告。本轮未修改 Rust，也未在本机重跑 Rust 全套。最低 Windows、缺少 VC Runtime 的全新系统、转发/动态依赖、签名及旧正式版兼容仍待验证；macOS 分发材料缺口没有变化。
