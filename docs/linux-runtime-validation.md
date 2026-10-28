# Linux 候选包运行库要求

本轮补充 CLI 和 SDK 的 ELF 符号版本记录，并让 CLI 验收摆脱开发者加载器覆盖变量的影响。规则见 [ADR 0036](adr/0036-linux-symbol-version-requirements.md)。

## 复现

需要 GNU/Linux x64、项目 Python 开发环境、GNU readelf 和 C 工具链。在干净源码目录运行：

```sh
python -m unittest discover -s tests -p test_elf_inspect.py -v
cli=$(python scripts/cli_bundle.py)
python scripts/cli_bundle_smoke.py "$cli"
sdk=$(python scripts/cli_bundle.py --product ffi_sdk)
python scripts/ffi_bundle_smoke.py "$sdk"
```

CLI 报告为 `target/cli-bundle-evidence.json`，SDK 为 `target/ffi-bundle-evidence.json`。失败或中断不能保留上次成功结果。候选保存在项目内，不安装系统运行库、不修改 PATH、不正式发布。

## 如何读取结果

- `direct_dependencies`：ELF 声明的直接库名，不是所有传递依赖。
- `required_symbol_versions`：按库记录的强制版本要求，包含数值和非数值名称。
- `weak_symbol_versions`：弱版本引用，单独保留，不计入最高强制 GLIBC 要求。
- `direct_dependencies_without_version_entries`：没有 version needs 条目的直接依赖；不能理解为它不受兼容性约束。
- `highest_glibc_numeric_requirement`：当前产物声明的最高数值 GLIBC 要求。它没有涵盖内核、其他库、CPU 指令、驱动和运行期加载路径，也不是最低发行版保证。

检查依据是 [GNU readelf 的动态和版本信息](https://sourceware.org/binutils/docs/binutils/readelf.html)。当 `elf_version_section`、`elf_version_entry` 或 `elf_version_count` 失败时，应先核对工具输出、版本和链接产物，不能把解析失败改成空列表。`elf_private_glibc` 表示直接引用了私有 glibc 版本，需检查构建和链接来源。

CLI 现在有七次顶层调用：六次实际 CLI 运行和一次 readelf。SDK 仍为 15 次：三次编译、三次 C、三次 Python、六次 readelf；Python 合计 300 次 collect/free。没有把编译器和链接器的子孙进程计入这个数字。

## 本轮验收

修正后源码 `46bd67ca6bd7a94c98c373b25616f6fe92d1f797` 的 [CI 40604554378](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40604554378)八项任务全部通过。四个受测脚本/测试文件与本机最终实现提交 `c19d6c8` 逐字节一致。

Linux CI 的 CLI、SDK 共享库和实际 C 消费者均声明最高强制数值要求 `GLIBC_2.34`，本次产物没有 WEAK 版本条目。CLI/SDK 库直接依赖 `libgcc_s.so.1`、`libc.so.6` 和 `ld-linux-x86-64.so.2`；C 消费者直接依赖包内 SDK 库和 libc。完整名称与版本清单见[CLI 报告](evidence/linux-runtime-cli-linux-40604554378.json)和[SDK 报告](evidence/linux-runtime-sdk-linux-40604554378.json)。

这个结果只描述当前构建产物。它没有证明在 glibc 2.34 上可运行，也没有建立最低内核或发行版保证；后续应在选定的较低版本环境实际安装运行，不能只看 Rust 目标本身的支持范围。GLIBC 的数字最大值也没有替代 GCC 和非数值 ABI 条件。

| 原生 runner | 八个实际归档的独立 Rust 测试（含 doctest） | Python 通过 / 跳过 |
|---|---:|---:|
| Windows x64 | 264 | 188 / 5 |
| Linux x64 | 256 | 193 / 0 |
| macOS ARM64 | 261 | 192 / 1 |

Linux 新增的原生格式测试实际用系统 C 编译器创建共享库，再读取 GNU readelf 输出；没有加载该测试库。Windows 跳过它和四项 POSIX 权限测试，macOS 只跳过这个 Linux 测试。纯文本/逻辑测试不能替代此原生证据，也不证明最低 glibc。

三平台 fmt、严格 Clippy/文档、workspace 测试、无默认 feature、Schema、Ruff/mypy（60 文件）和项目守卫通过。各平台另完成五组原生 CLI/C/Python 检查、16 项顶层进程。Linux CLI 七次调用和 SDK 15 次调用/300 次 Python collect/free 均通过，三阶段 SDK ELF 报告一致；Windows 原有 CLI 六次、SDK 九次及 PE 检查回归通过。

供应链、Linux 容器、Miri 8 项、FFI ASan 10 项和既有 12 个 Rust 短 fuzz 目标通过。新增 Python ELF 解析器不在这些 Rust fuzz 目标中；空 `/proc` 容器仍在库进程启动前被 OCI 拒绝，记录为未运行。任务、测试数量、十份报告、实际版本清单、前一轮取消状态和哈希见[CI 验收索引](evidence/linux-runtime-ci-40604554378.json)。本轮下载核查的是 runner 报告，没有二次下载候选 ZIP 重新检查。

## 本机与修正记录

- `0adb8ed` 的[初次 Windows 守卫结果](evidence/linux-runtime-local-0adb8ed.json)：Python 187 项通过、5 项跳过，Rust 264 项通过；这是弱版本分类修正前的记录。
- `c19d6c8` 的[最终 Windows 守卫结果](evidence/linux-runtime-local-c19d6c8.json)：Python 188 项通过、5 项跳过，ELF 测试共 15 项；Rust 264 项及交叉/静态门禁通过。
- 首轮 CI 40604102386 因独立复核发现弱版本可能被误计为强制要求而主动取消，没有接受为最终验收。后续修正还覆盖有界名称中的大数字版本，原始记录保留。

本机 Windows 没有执行 Linux readelf、原生编译或 Linux 候选安装，Linux 证据来自上述原生 CI。公共 Rust API、C ABI 1、硬件 JSON Schema 1、ZIP 格式、依赖、feature、锁文件和 MIT 不变；候选报告新增版本字段，旧 SDK `elf_needed` 字段保留。

最低 glibc/内核/发行版、传递和运行期依赖、实体 Linux/macOS、多组 CPU、长期 fuzz 和峰值内存仍待独立验证。没有正式发布软件。
