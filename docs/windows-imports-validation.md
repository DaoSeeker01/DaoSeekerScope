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

CLI/SDK 演练运行真实消费者；最后的 DUMPBIN 对照不执行被检查的文件。它重新编译 C 消费者与一个只用于检查的 USER32 延迟导入样例，报告写到 `target/windows-imports-evidence.json`。没有全局安装、PATH 修改或制品发布。离线构建要求依赖已缓存。

## 已验证与待验证

本机 Python 全套 315 项中 309 通过、6 跳过。PE 定向测试 19 项通过，含新增 7 项符号回归；独立对照工具新增 5 项测试通过。覆盖名称大小写、序号全范围、保留位、普通/延迟分离、未绑定回退、截断/终止符、单表/合计上限、工具文本解析、对照期间文件被修改、旧候选及失败/中断报告作废。

真实 MSVC 延迟导入样例已完成编译，其名称清单与 DUMPBIN 一致，样例没有运行。最初把最简合成 PE 交给 DUMPBIN 时触发了工具的 LNK1000/C0000094 内部错误；这不是通过记录。正式对照只接收当前源码编译的候选与样例，损坏字节测试由自有解析器完成。另对真实 PE 的副本作静态序号变异，确认 DUMPBIN 用十进制显示序号；变异文件未运行，不能当作真实加载验证。

准备阶段发现一处 Windows SHA256SUMS 的 CRLF 兼容问题、一个未用导入与一个类型收窄遗漏，已修正。最早的新清单测试因缺少 `direct_symbols` 报 KeyError，日志保留为未实现时的对照。

## 原生与 CI 验收

源码 `5ceba49` 的[三平台 CI 41257426560](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/41257426560)八项任务全部通过。[验收索引](evidence/pe-symbols-ci-41257426560.json)保存 15 份报告的来源、哈希与准备阶段的失败记录。

| 环境 | Python 通过 / 跳过 | 八包 Rust（含文档测试） |
|---|---:|---:|
| Windows 原生 CI | 309 / 6 | 274 通过 |
| Linux 原生 CI | 315 / 0 | 267 通过 |
| macOS 原生 CI | 314 / 1 | 271 通过 |

Windows 本机和 Windows CI 均完成四个文件的对照：CLI、SDK DLL、重新编译的 C 消费者及延迟导入样例。它们的名称、序号和所属模块清单均与 DUMPBIN 逐项一致。

本机结果如下；每个数字只属于该次构建，CI 工具链与 C 运行库的清单可能不同，原始清单各自保留。

| 本机文件 | 普通 DLL 数 | 普通名称数 | 延迟名称数 |
|---|---:|---:|---:|
| CLI | 21 | 142 | 0 |
| SDK DLL | 18 | 120 | 0 |
| C 消费者 | 2 | 75 | 0 |
| 延迟导入样例 | 1 | 73 | 1 |

四个本机文件均没有按序号导入。USER32 的 `GetSystemMetrics` 延迟名称已真实编译并静态对照；序号读取有字节测试和未执行的静态变异控制，尚无实际按序号链接的 DLL 消费者。静态对照不验证入口在旧系统能否运行。

本机和 CI 的候选安装、拒绝损坏更新、C/Python 调用、300 次 SDK Python collect/free 与同候选双槽位回滚通过；原生 C/Rust 契约、Schema、Ruff/mypy（75 文件）、actionlint、项目检查，以及三平台 fmt、Clippy、无默认功能和严格文档通过。本机未重跑 Rust 全套，表中 Rust 数量来自原生 CI 的八包验收。

Miri 8 项、FFI ASan 11 项与 12 个原有 Rust 短 fuzz 目标通过；每个 fuzz 目标至少 60 秒。这些不是 Python PE 解析器的长期 fuzz：PE 另有定向回归与原有 256 次有界字节变异。

Rust API、依赖/features、锁文件、MIT、C ABI 1、硬件 Schema 1 及 ZIP 格式不变。最低 Windows、缺少 VC Runtime 的全新系统、转发/动态依赖、签名及旧正式版兼容仍待验证；macOS 分发材料缺口保持不变。没有正式发布。
