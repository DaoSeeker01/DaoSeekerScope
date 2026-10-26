# Linux FFI SDK 候选包验证

Linux SDK 将共享库、C 头文件、C/Python 示例、Schema 和许可材料打包，便于其他语言接入。设计见 [ADR 0034](adr/0034-linux-ffi-sdk.md)。这不是正式发布。

## 使用入口

在干净 GNU/Linux x86_64 工作区，准备固定 Rust 工具链、GNU 兼容 C 编译器/链接器、readelf、Python 与开发依赖 jsonschema 4.25.1：

```sh
set -eu
sdk=$(python3 scripts/cli_bundle.py --product ffi_sdk --offline)
python3 scripts/ffi_bundle_smoke.py "$sdk"
```

依赖或工具链许可尚未缓存时去掉 `--offline`。产物保存在 target/cli-bundles 的新 candidate 目录，演练只写 target 下临时目录；未提交修改可用 `--allow-dirty` 调试，不能作为干净提交验收。默认报告为 target/ffi-bundle-evidence.json。

归档内 README 给出独立消费命令。C 使用包内 .so 和头文件；Python 示例仅需标准库并显式接收 .so 绝对路径。验证器额外使用 readelf 和 jsonschema，不要求 SDK 使用者安装 Rust 或项目源码。

## 验证边界

Linux SDK 使用格式 4，其他三个包格式不变；ABI 1、硬件 Schema 1、Rust API、依赖/features/锁和 MIT 不变。每个 Linux 演练执行 15 个顶层调用（含 6 次 ELF 检查）、300 次 Python collect/free，并检查同候选安装、损坏更新拒绝和回滚；本轮 CI 40304816716 已完成这些检查，见下节。

Windows 主机只能验证共享格式/负向守卫和既有 Windows SDK 回归，不能执行 Linux SDK。本轮原生 Linux CI 40304816716 已通过；新增两项 POSIX 权限用例也在 Linux/macOS 执行通过，不以 Windows 模拟模式作为权限证据。

最低 glibc/发行版/内核版本、系统传递依赖闭包、签名、旧正式版升级和正式分发尚未验收；不宣称 musl、ARM、macOS SDK 或静态链接支持。用户延期的实体 Linux/macOS 设备验证保持待办。

## 本机检查（2026-10-26）

实现源码 `f2620951be1a6e42921768772451d8419505f2ed` 在 Windows x64（系统报告 10.0.26300/AMD64）完成以下检查。Windows 消费者使用该干净提交新构建的实际 ZIP；没有生成或执行 Linux 二进制。

| 检查 | 实际结果 |
|---|---|
| 共享工具负向与格式守卫 | Python 总计 161 项，157 通过、4 项 POSIX 权限测试跳过；新增 Linux SDK 用例 12 项，其中 10 通过、2 项权限用例跳过 |
| Windows SDK 回归 | 格式 3、78 项载荷；3 次 C 编译与执行、3 次 Python 执行，共九项顶层调用、300 次 collect/free；Schema/默认隐私/空释放/stale copy/损坏更新/同候选回滚通过 |
| 默认 Windows CLI 回归 | 格式 1、新构建实际 ZIP 的六进程安装/采集/回滚通过 |
| Rust 门禁 | fmt、严格 Clippy、262 项测试含 doctest、无默认 feature、严格 doc、构建和 Linux x64/macOS ARM64 cargo check 通过；执行于实现提交前的工作树，Rust 输入与该提交一致 |
| 脚本静态检查 | 55 文件 Ruff 0.14.13、mypy 1.19.1 通过；四个变更脚本/测试额外通过 `mypy --strict` |
| Schema 与项目检查 | 黄金样例/生成漂移/负向状态/未知字段/版本、项目文件与文档链接、actionlint 1.7.12 通过 |
| Linux 许可材料预检 | 目标过滤的 FFI 依赖闭包中，缓存可收集到 25 份上游许可文件；不是 Linux 原生构建、Linux Rust 工具链许可或最终许可评审 |

[本机索引](evidence/linux-ffi-sdk-local-f262095.json)绑定命令、源码与日志/报告哈希；[Windows SDK](evidence/linux-ffi-sdk-windows-sdk-regression-f262095.json)、[Windows CLI](evidence/linux-ffi-sdk-windows-cli-regression-f262095.json)与[许可材料预检](evidence/linux-ffi-sdk-notice-materials-f262095.json)分别归档。两个实际 ZIP 另经校验，并逐字节核对 SDK 的头文件、示例与 Schema 和提交内维护来源；归档统一 LF、保留原始报告哈希，二进制仅留在 target。

本机裸 Python 不含这些开发包，检查使用现有 uv 离线缓存中的 jsonschema 4.25.1、Ruff 0.14.13、mypy 1.19.1，没有全局 pip 安装。Rust 代码、依赖/features/锁、MIT、ABI 1/硬件 Schema 1 均未改动。本机验收阶段未运行新三平台 CI、八包、fuzz、Miri、ASan 或 benchmark；随后由本轮 CI 重跑并在下节独立归档，不挪用上一轮结果。

## 三平台 CI 验收（2026-10-26）

源码 `af312dad99abcbfc8fe2becd8a2fc209fca85f90` 的[运行 40304816716](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40304816716)全部 8 个任务通过；只手动启动一次，无运行时修复。Linux x86_64 原生 release SDK 格式 4、47 个载荷文件，安装、切换、回滚三个阶段均使用包内头文件/.so/C/Python 示例验证：3 次 C 编译、3 次 C 执行、3 次 Python 执行及 6 次 readelf，共 15 项顶层调用，300 次 Python collect/free；不包含编译器/链接器子孙进程。

消费者的 NEEDED 为 `libdaoseeker_scope_ffi.so`、`libc.so.6`，RUNPATH 仅 `$ORIGIN/../lib`；库的直接 NEEDED 为 `libgcc_s.so.1`、`libc.so.6`、`ld-linux-x86-64.so.2`，无嵌入 RPATH/RUNPATH。三个阶段一致。该结果记录直接依赖名称，不是完整系统依赖闭包或最低运行环境证明。SDK 权限、子进程 loader 环境清理、包内 Schema/默认隐私/最低读取、空释放/stale copy 拒绝、损坏更新拒绝与同候选回滚通过。

| 原生平台 | workspace Rust 含 doctest | 八包独立消费者测试 | Python 通过 / 跳过 |
|---|---|---|---|
| Windows x64 | 262 | 262 | 157 / 4 |
| Linux x64 | 254 | 254 | 161 / 0 |
| macOS ARM64 | 259 | 259 | 161 / 0 |

Windows SDK 格式 3、78 项载荷的九项顶层调用/300 次 Python 循环回归通过；Windows/Linux CLI 格式 1/2 各六进程回归通过。三平台 CLI/C/Python 原生 smoke 各 5 组/16 进程通过；4 项 POSIX 权限用例在 Linux/macOS 执行通过，在 Windows 保留 skipped。

fmt、严格 Clippy/doc、无默认 feature、55 文件 Ruff/mypy、Schema/项目检查、cargo-deny 通过。12 个 fuzz 目标各至少 60 秒、4 项 harness、Miri 8 项、Linux ASan 10 项通过。8 类 Linux 容器报告包含 7 项基础场景及 CPU 15、内存 26、电池 30、hwmon 47、存储 21、GPU 20、显示器 26 项样本；完整空 /proc 仍被 OCI 在启动前拒绝，保持 not_run。整库基准另见[基线](benchmarks.md)，不作为 SDK 打包或加载性能。

[验收索引](evidence/linux-ffi-sdk-ci-40304816716.json)绑定同一干净源码，保存 28 份报告及原始/归档哈希，包括 [Linux SDK](evidence/linux-ffi-sdk-sdk-linux-40304816716.json)、[Windows SDK 回归](evidence/linux-ffi-sdk-sdk-windows-40304816716.json)、三平台包/原生、8 份容器报告与两份基准。头文件哈希另与提交内维护来源核对；ZIP 留在 runner，仅下载并核验报告，未二次检查 ZIP 成员，也未上传二进制或发布。

MIT、Rust API、依赖/features/锁、C ABI 1、硬件 Schema 1 不变。Linux/Windows SDK 分别格式 4/3，CLI 仍 2/1。macOS 分发材料、旧正式版兼容、最低 glibc/发行版/系统依赖、签名与最终许可评审继续待办。托管 CI 不替代延期实体设备；300 次调用与短 fuzz 不是完整泄漏、峰值内存或长期 campaign 证明。
