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

## 本轮状态

干净提交 `0adb8ed6f4d1283cc508240a6f8b7c9c236ccf59` 的本机 Windows 回归已通过：Python 共 192 项，187 项通过、5 项跳过（4 项既有 POSIX 权限测试和 1 项新增 Linux 原生编译测试）；新增 ELF 测试共 14 项。Rust 264 项测试、fmt、严格 Clippy/文档、无默认 feature 和 Linux x64/macOS ARM64 交叉检查通过。Ruff 与 mypy 的 60 个文件检查通过，[本机记录](evidence/linux-runtime-local-0adb8ed.json)保存来源和日志哈希。

本机没有执行 Linux readelf、原生编译或候选安装。真实 Linux CLI/SDK 的符号版本读取与三平台 CI 尚待本轮验收，没有把上一轮结果作为本轮原生证据。

首轮 CI 40604102386 在独立复核发现弱版本分类问题后主动取消，不作最终验收。上述 `0adb8ed` 本机记录保留为修正前的守卫结果；后续验收必须绑定修正后的源码，不能覆盖或改写首轮历史。

修正后干净提交 `c19d6c8950ac949ca9ef5f19e7b96d831f9703a8` 再次通过本机完整门禁：Python 193 项中 188 项通过、5 项跳过，新增 ELF 测试共 15 项；Rust 264 项及上述构建/静态门禁通过。弱版本和超长数字段的回归已加入，原生 Linux 与最低运行环境仍未由本机验证。详见[最终本机记录](evidence/linux-runtime-local-c19d6c8.json)。

最低 glibc/内核/发行版、传递和运行期依赖、实体 Linux/macOS、多组 CPU、长期 fuzz 和峰值内存仍待独立验证。Windows PE 检查沿用[上轮结果](windows-pe-validation.md)，本轮仍需共享工具回归。
