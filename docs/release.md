# 发布与迁移

当前为未发布的 0.1.0 开发版。交付状态统一维护在 [v0.1 清单](v0.1-checklist.md)，本页说明验收、发布顺序和迁移要求。历史测试、失败与来源见[专项验收文档](README.md)和 Git 历史。

## 已验证范围

| 目标 | 已有证据 | 发布前仍需处理 |
|---|---|---|
| Windows x64 / MSVC | 本机和原生 CI；Rust 源码包、CLI/FFI SDK 候选安装与回滚 | 最低 Windows、全新系统运行库及最终分发评审 |
| Linux x64 / GNU | 原生 CI、受限容器；Rust 源码包、CLI/FFI SDK 候选；固定 glibc 2.34/2.36 用户空间运行，2.31 预期拒绝 | 最低内核、承诺的发行版/运行库范围及最终分发评审 |
| macOS ARM64 | 原生 CI 的源码构建、Rust 源码包、SDK 对照与 C/Python 调用 | 六项依赖许可材料及 CLI/FFI SDK 候选打包、安装与回滚 |

表中是已有验收范围，最终支持承诺仍待确认。架构、CI 与容器结果不能外推到全部同版本系统。实体 Linux/macOS、多处理器组等设备测试按维护者设备安排延期，见[剩余工作](progress.md)。Android、iOS、Web、no_std 和 MCU 属于后续独立路线。

macOS 的源码构建结果与二进制分发分别判断。[许可材料预检](notice-preflight.md)尚有缺口，不能用通用许可证文本补位，也不能据此认定上游 SPDX 声明无效。首发制品范围仍需维护者决定。

## 准备候选版本

1. 确认本次要交付的目标、制品和限制，核对 [API/ABI/Schema 契约](v0.1-contract-review.md)、[依赖许可证](dependencies.md)与[更新日志](../CHANGELOG.md)。保留未验证和不适用项。
2. 冻结待验收提交，记录 `git rev-parse HEAD` 与 `git status --porcelain`。正式候选要求工作区干净；需要并行开发时，使用独立检出目录。
3. 按[贡献指南](../CONTRIBUTING.md)运行相关本机检查和完整三平台 CI。核对每项任务和报告，不只查看工作流总状态。定向 CI 的跳过项不能补作完整通过。
4. 执行下列契约、许可材料和源码包检查。构建环境需要项目固定的 Rust、Python 3.12+ 及本机 C 编译器；Windows 还需要 MSVC/Windows SDK。

```sh
python scripts/check_contract.py
python scripts/notice_audit.py
python scripts/check_packages.py
```

依赖已缓存时，后两项可加 `--offline`。许可审计完成后还须检查 `products.*.packager_notice_gate` 与 `errors`；扫描成功不代表分发材料完整。源码包报告写入 `target/package-evidence.json`，包含八个归档和 core/门面的八种独立消费者配置。未发布的相邻 crate 使用本地 patch，不能据此声称 crates.io 下载或安装通过。具体过程见[打包指南](packaging.md)。

5. 为拟分发的 CLI/SDK 构建候选，验证实际安装、切换、回滚及默认隐私。Windows x64 的入口如下，两个产品分别执行并保存报告。

```sh
python scripts/cli_bundle.py --product cli
python scripts/cli_bundle.py --product ffi_sdk
```

Linux x64 使用已验收的构建用户空间，运行 `bash scripts/build_linux_candidate.sh cli` 和 `bash scripts/build_linux_candidate.sh ffi_sdk`。环境要求与报告边界见[打包指南](packaging.md)、[Linux CLI](linux-cli-bundle-validation.md)及[Linux SDK](linux-ffi-sdk-validation.md)。不要把宿主直接链接的产物当作经过相同用户空间验收的候选。

上述命令只构建并校验归档。随后在对应原生平台，分别把输出的实际 ZIP 路径传给演练脚本；与 ZIP 同目录的 `SHA256SUMS` 必须保留。

归档中所有文件都必须非空，包括清单、许可证、说明与 SDK 材料。安装校验会在读取文件内容前检查大小；空文件返回 `file_limit`，即使归档和载荷哈希匹配也不接受，且不创建安装目录。文件非空仅是格式要求，不代替许可证内容与适用性评审。

提交 `88dcac3` 的四种候选格式空文件回归及三平台工具 CI 已通过，Windows 正常候选的安装和回滚也通过。[验收记录](evidence/empty-bundle-ci-43332120977.json)保留修复前的失败与实际范围；这些归档格式测试不等同于 Linux 原生候选安装验收。

```sh
python scripts/cli_bundle_smoke.py <CLI归档路径>
python scripts/ffi_bundle_smoke.py <SDK归档路径>
```

演练报告分别写入 `target/cli-bundle-evidence.json` 与 `target/ffi-bundle-evidence.json`。CLI 的版本、JSON 和隔离 JSON 调用还要求 stderr 为空；非空或超限时只记录固定错误，不保存原始内容。构建成功不代表安装/回滚演练已通过。

SDK 的 C/Python 消费者及 ELF 检查同样要求 stderr 为空。编译器可输出正常诊断，仍须成功退出；所有 SDK 子进程的 stderr 读取上限为 1 MiB，超限则失败，原始内容不写入报告。

启动和退出失败使用固定标识，前缀表示调用方（`cli`、`c`、`python` 或 `compile`）：

| 后缀 | 含义与下一步 |
|---|---|
| `windows_dependency_missing` | Windows 返回依赖缺失状态。检查候选目录是否完整，以及系统运行库是否齐全；该状态不指明缺少哪一个 DLL。 |
| `windows_invalid_image` | Windows 拒绝二进制格式。核对架构、文件完整性及目标系统。 |
| `start_failed` | 进程未能创建。核对文件是否存在、访问权限及执行环境。 |
| `timeout` | 子进程超过本次等待期限，已请求终止并等待直接子进程退出；不表示运行库缺失。 |
| `exit` | 进程已启动并非正常退出，原因未进一步归类。保留报告并按失败阶段排查。 |

分类依据为微软的 [NTSTATUS 定义](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55)；程序也可主动返回相同数值，因此不能只据退出状态确定根因。

Windows 可另外运行 `python scripts/windows_loader_smoke.py <SDK归档路径>`。它在临时安装中先运行真实 C/Python 消费者，再分别移走和损坏 DLL，验证拒绝加载，恢复原文件后复验 C 输出。报告写入 `target/windows-loader-evidence.json`，包含源码与载荷哈希。故障实验只改变该诊断进程的错误弹窗设置，结束时恢复；子进程继承规则见[微软文档](https://learn.microsoft.com/en-us/windows/win32/api/errhandlingapi/nf-errhandlingapi-seterrormode)。它不证明全新系统具备所有运行库，也不确定最低 Windows 版本。

提交 `2251884` 已在本机和 Windows 原生 CI 通过该实验及两产品安装回滚；[验收记录](evidence/windows-loader-ci-43131273622.json)保留三平台 Python 定向检查、首次失败及修复后的结果。本轮按工具变更范围验证，完整 Rust 与发布矩阵仍按上述步骤执行。

候选构建和演练不上传制品、不安装到全局 PATH。macOS 尚未开放该打包入口。同候选两槽位切换只验证恢复机制，旧正式版存在后再验证跨版本升级与回滚。

6. 对照同一提交核对源码、归档/二进制哈希、平台、退出码、完成标记与原始报告。`failed`、`incomplete`、`not_run` 和跳过结果分别保留，不能以旧 pass 覆盖。

## 正式发布

确认最终候选、许可证材料、支持范围、变更日志与待发布清单后，再取得正式发布授权。日常提交、推送、CI 和候选构建的授权不包含标签、GitHub Release 或 registry 发布。仓库当前没有自动正式发布工作流。

Rust 包按依赖顺序发布：core → sysinfo 与三个平台 crate → 门面 → CLI/FFI。每一层须确认 registry 已可解析再发布依赖它的包；发布后，在全新目录从 registry 安装并运行消费方，另记录结果。本地 patch 验收保留原结论。

二进制发布须附对应候选、校验和、适用目标、运行要求、第三方许可材料和恢复说明。校验和用于检测文件变化，不能单独证明发布者身份。失败时停止后续分发并保留报告，不覆盖已发布版本的内容。

## 开发版消费者迁移

使用门面 `daoseeker_scope::Hardware` 会自动组合所需 backend。单独注册 backend 的应用需留意下列变化，详细来源与行为见对应验收文档。

| 原用法或假设 | 当前用法与限制 |
|---|---|
| 单独 SysinfoBackend 读取 Linux CPU 用量、内存和 uptime | 注册 LinuxBackend 或改用门面；新读取失败不返回旧值。见[CPU](cpu-refresh-validation.md)、[内存](memory-refresh-validation.md) |
| 单独 SysinfoBackend 读取 Windows 内存、CPU 用量和 uptime | 分别注册 WindowsMemoryBackend、WindowsCpuBackend、WindowsBackend，或使用门面。多组 CPU 为有界尝试，实体多组仍待验。见[内存](windows-memory-validation.md)、[CPU 多组](windows-cpu-groups-validation.md)、[uptime](windows-uptime-validation.md) |
| 单独 SysinfoBackend 读取 macOS 逻辑核数、CPU 用量、内存和 uptime | 注册 MacosCpuBackend、MacosMemoryBackend、MacosBackend，或使用门面。见[CPU](macos-cpu-validation.md)、[内存](macos-memory-validation.md)、[uptime](macos-uptime-validation.md) |
| CLI crate 穷举匹配 Command | 已增加 Display 分支。见[显示器 CLI](display-text-validation.md) |
| 根据错误文字分支或重试 | 改为判断 ScopeError.code；显示文字已澄清，CLI 退出码和 C ABI 错误契约保留。见[错误处理](usage.md#处理操作错误) |
| Drop 后立即卸载库，或把超时当作原生任务已结束 | Rust 可消费式 shutdown 等待 backend 释放；超时后工作仍可能继续。C ABI 采集后保持库加载到进程结束。见[资源与超时](usage.md#资源与超时) |

新增 GPU、存储、显示器、电池和温度来源时，已有模型的值与状态可能从 Unsupported 变为可用或受限。继续逐字段检查 Observed；空集合不证明物理设备不存在，列表下标也不是稳定身份。当前语义以[能力矩阵](adr/0005-platform-support-matrix.md)和[使用指南](usage.md)为准。

## 兼容性规则

Rust 包版本由 workspace 统一管理。0.1 系列优先保持源码和行为兼容，破坏性 Rust 变更使用 0.2 并提供迁移说明。C ABI 1、硬件 Schema 1 与候选包格式分别编号，不随 Rust 版本自动变化。

JSON 未知对象字段可忽略；新增旧解码器不认识的枚举、删除字段或改变单位/语义，需要评审 Schema 主版本与迁移方式。C ABI 已有布局、所有权及错误码不得静默改变或复用。sysinfo 升级仍须经过字段映射、Schema、平台行为与依赖许可回归，不能只以构建通过验收。

具体承诺及尚待维护者确认的事项只在[契约评审表](v0.1-contract-review.md)维护。整理本页不改变既有支持范围、许可、ABI/Schema 或发布状态。
