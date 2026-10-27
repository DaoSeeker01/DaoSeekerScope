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

干净源码 `5da6c39eaa3512b1406a8c92f27a1188812c53df` 已在本机 Windows 11 build 26300 x64 完成原生 Release 验收。CLI 为 73 项载荷、六进程演练；SDK 为 78 项载荷、九次顶层调用、300 次 Python collect/free，归档 PE 检查与三阶段六次已安装文件检查全部通过。

| 本机产物 | 普通直接导入数 | 延迟导入数 | 子系统声明 |
|---|---:|---:|---|
| CLI EXE | 21 | 0 | 控制台 |
| SDK DLL | 18 | 0 | GUI（DLL 头部声明） |
| 独立重编译的 C EXE | 2 | 0 | 控制台 |

三个产物的模块名清单均与 Microsoft DUMPBIN 逐项一致；CLI/DLL 的对照文件哈希与已验候选一致。C EXE 直接导入包内 `daoseeker_scope_ffi.dll` 和 `kernel32.dll`。CLI/DLL 均直接导入 `vcruntime140.dll`，当前候选不附带它；尚未在缺少该运行库的全新系统验收。若消费者遇到缺失运行库，应使用微软[受支持的 Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)，不从第三方下载单个 DLL；此处未执行任何运行库安装。

Rust 264 项测试通过，fmt、严格 Clippy/文档、无默认 feature 与 Linux x64/macOS ARM64 交叉检查通过。Python 178 项中 174 项通过、4 项 POSIX 测试跳过；新增 PE 测试 12 项，包含 256 个固定种子的有界变异输入，这不是长期 fuzz。Ruff 与 mypy 的 58 个文件检查通过。初次沙箱临时目录失败、类型注解和 DLL 子系统判断的修正保留在[本机验收索引](evidence/windows-pe-local-acceptance-5da6c39.json)。

原始结果：[CLI](evidence/windows-pe-local-cli-5da6c39.json)、[SDK](evidence/windows-pe-local-sdk-5da6c39.json)、[DUMPBIN 对照](evidence/windows-pe-local-dumpbin-5da6c39.json)。合成 PE 不作为 Windows 加载或设备证据。

## 三平台 CI

源码 `ee3721fb5bd6fe906ea91510e7b2d2f748bd0605` 的 [CI 40483692144](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40483692144)八项任务全部通过。本轮只触发这一次 CI，没有失败或取消记录。它与本机实现提交的四个受测脚本/测试文件逐字节一致，新增提交仅归档本机结果和文档。

| 原生 runner | 八个实际归档的独立 Rust 测试（含 doctest） | Python 通过 / 跳过 |
|---|---:|---:|
| Windows x64 | 264 | 174 / 4 |
| Linux x64 | 256 | 178 / 0 |
| macOS ARM64 | 261 | 178 / 0 |

三平台 fmt、严格 Clippy/文档、workspace 测试、无默认 feature、Schema、Ruff/mypy、项目守卫均通过。每个平台另完成五组原生 CLI/C/Python 检查、16 项顶层进程；两平台 CLI 和 SDK 候选都通过。Windows CLI 一次归档 PE 检查，SDK 一次归档及六次已安装 PE 检查已在报告中确认；顶层调用仍为 CLI 六次、SDK 九次，SDK Python 合计 300 次 collect/free。

供应链、Linux 容器、Miri、FFI ASan 和既有短 fuzz 门禁通过。空 `/proc` 容器场景仍是 OCI 在库进程启动前拒绝，不能算作该场景通过；长期 fuzz 与峰值内存仍待完成。CI 的 SDK/CLI 报告由 runner 产生，本轮下载核查的是报告，没有二次下载并检查其候选 ZIP。

源码、任务、十份归档/原生/候选报告和哈希见[CI 验收索引](evidence/windows-pe-ci-40483692144.json)。本轮没有 Rust 公共 API、C ABI 1、硬件 JSON Schema 1、crate、feature、锁文件、依赖或 MIT 变化；候选验收报告只增加字段，既有 ZIP 格式保持不变。

## 故障定位

这些错误只来自候选维护工具，不是新的 C ABI 错误码：

| 检查码 | 含义与下一步 |
|---|---|
| `pe_machine` / `pe_optional_magic` | 产物不符合 x64 PE32+ 契约；检查构建目标，不能改名冒充目标文件。 |
| `pe_debug_runtime` | 直接导入了已知调试运行库；检查编译 profile 和链接选项后重新构建。 |
| `pe_truncated` / `pe_unmapped_rva` | 字节或地址范围不完整；重新核对来源和校验和，不要执行该候选。 |
| `pe_import_limit` / `pe_module_name` | 导入表超限或模块名不符合本候选规则；检查实际链接输出，确认原因后再评审工具边界。 |
| `pe_sdk_dependency` | 新编译 C 消费者没有直接导入包内 SDK DLL；检查实际使用的导入库。 |

若需独立对照，在 Visual Studio 开发者终端对已经校验、解压的文件运行 `dumpbin /nologo /dependents <文件>`。本轮实际产物没有延迟导入，因此 DUMPBIN 对照只验证普通导入清单；延迟导入仅有纯字节测试。

截至本轮查阅，Rust 的 [Windows MSVC 目标要求](https://doc.rust-lang.org/rustc/platform-support/windows-msvc.html)为 Windows 10 / Server 2016 或更高。这是上游目标要求，不是本项目已经完成相应最低版本验收的证据；不能根据 PE 头部的 6.0 声明倒推旧系统支持。

## 如何解读报告

`direct_imports`、`delay_imports` 是二进制声明的直接模块名，统一小写；API-set 名称不等于磁盘上的同名 DLL。`declared_os_version` 和 `declared_subsystem_version` 是链接产物的头部字段，不能据此写成“已支持 Windows 6.0”。微软 [PE 规范](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)定义了这些结构，但实际可运行范围还取决于函数、运行库、驱动与 OS 行为。

CLI 检查一次已验证归档中的 EXE。SDK 检查一次归档 DLL，另在三个安装阶段检查各自的 C EXE 和 DLL，共六次已安装文件检查；顶层调用仍为 CLI 六进程、SDK 九次。报告没有硬件快照、DLL 完整路径或用户目录。

最低 Windows 版本、传递/运行期依赖、签名、没有 VC Runtime 的全新系统及旧正式版升级均未验证。当前检查也不读取导入函数或替代供应链、许可证和系统安全检查。实体 Linux/macOS 与多处理器组验证继续延期。
