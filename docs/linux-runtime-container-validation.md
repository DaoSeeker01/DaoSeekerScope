# Linux 候选包的较低版本环境验证

这项验收直接运行现有 CLI 和 SDK 候选，回答它们能否在指定的较低版本用户空间中安装、加载和采集。它与[符号版本清单](linux-runtime-validation.md)互补；规则见 [ADR 0037](adr/0037-linux-candidate-older-userlands.md)。

## 复现

在有既有本地 Docker、GNU readelf、C 编译器和项目 Python 开发环境的 Linux x64 主机上，使用干净源码运行：

```sh
cli=$(python scripts/cli_bundle.py)
sdk=$(python scripts/cli_bundle.py --product ffi_sdk)
python scripts/linux_runtime_container_smoke.py "$cli" "$sdk"
```

脚本不安装或启动 Docker，不使用远程 daemon，不更改系统库或 PATH。报告写入 `target/linux-runtime-container-evidence.json`；任一步失败都不能沿用旧成功报告。镜像仅用于测试，不随项目分发。

## 已验证结果

干净源码 `a5ae6fe799bfb899de8d1b4a44408905cc6d6c15` 的 [CI 40664519934](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40664519934)八项任务全部通过，受测文件与最终本机实现提交 `7c3e90a` 逐字节一致。完整报告见[容器结果](evidence/older-runtime-containers-linux-40664519934.json)，来源、哈希和门禁汇总见[验收索引](evidence/older-runtime-ci-40664519934.json)。

| 固定镜像中的环境 | 实际结果 | 结论范围 |
|---|---|---|
| Debian 12 / glibc 2.36 / Python 3.13.13 | CLI 版本与 JSON、C 采集、Python 100 次 collect/free 通过；Schema、最低读取和默认隐私通过 | 当前候选在此用户空间可运行 |
| Debian 11 / glibc 2.31 / Python 3.13.5 | CLI/C 报告缺少 GLIBC_2.32、2.33、2.34，ctypes 报告缺少 GLIBC_2.32；未开始采集 | 当前候选在此环境被 loader 拒绝；“通过”只指预期拒绝检查通过 |

两次运行使用相同 CLI、SDK 库和宿主预先编译的 C 消费者哈希；容器内没有重新编译它们。完整复制并校验 CLI 43 项与 SDK 47 项载荷，另有两个 manifest 和一个 C 消费者，共 93 个安装文件。两个容器均以 UID/GID 65534、只读根目录、无网络和固定资源限制运行，结束后均已移除。

## 容量修复与资源证据

完整安装逻辑大小为 34442903 bytes（约 32.85 MiB），按分配单元和目录估算为 34832384 bytes。64 MiB 工作区保留 16 MiB 余量；复制前后通过 statvfs 核对，复制后还剩 32432128 bytes（约 30.93 MiB）。内存上限仍为 256 MiB，没有扩大容器资源或删除、共享许可证文件。

首轮 [CI 40609811580](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40609811580)因工具写死的 32 MiB 载荷门槛失败，未启动任何测试容器，不能当作兼容性结果。[原始失败报告](evidence/linux-runtime-container-failed-40609811580.json)和七项成功、一项失败的状态保留。修复后按实际工作区预算完整安装，并检查复制前后真实余量；超限仍必须失败。

另补齐 C loader 诊断的已知依赖范围：C EXE 的错误可以来自包内 SDK 库，二者的强制版本表共同校验；CLI 和 ctypes 仍分别检查自身。此次 C 诊断实际包含 SDK 声明的 GLIBC_2.32、2.33，相关回归通过；未知版本、崩溃、权限错误或普通非零退出不能冒充预期拒绝。

## 回归门禁

| 原生 runner | 八个实际归档的独立 Rust 测试（含 doctest） | Python 通过 / 跳过 |
|---|---:|---:|
| Windows x64 | 264 | 207 / 5 |
| Linux x64 | 256 | 212 / 0 |
| macOS ARM64 | 261 | 211 / 1 |

三平台 fmt、严格 Clippy/文档、workspace 测试、无默认 feature、Schema、Ruff/mypy（63 文件）和项目守卫通过；各平台五组原生 CLI/C/Python 检查、16 项顶层进程通过。两平台既有 CLI/SDK 安装回滚与 ELF/PE 门禁也通过。Linux 新增用户空间场景单独记录，不与既有 CLI 七次、SDK 15 次调用/300 次 Python 循环混计。

供应链、既有 Linux 容器、Miri 8 项、FFI ASan 10 项及 12 个 Rust 短 fuzz 目标通过。完整空 `/proc` 仍被 OCI 在库进程启动前拒绝，记录为未运行；长期 fuzz 与峰值内存尚未完成。本轮下载核查的是 runner 产生的报告，没有二次下载候选 ZIP 重新验收。

本机 Windows 的[初次守卫](evidence/linux-runtime-container-local-2f0c900.json)和[修复后守卫](evidence/linux-runtime-container-local-7c3e90a.json)分别保留。最终本机 Python 207 项通过、5 项平台跳过，容器守卫共 19 项；Rust 264 项及 Linux x64/macOS ARM64 交叉检查通过。本机没有启动 Docker 或 Linux 程序。

## 尚未证明的内容

容器共享 CI 宿主内核 `7.0.0-1017-azure` 和宿主 CPU，不能当作实体 Debian 设备或最低内核测试。glibc 2.31 被拒绝、2.36 可运行，并不能推出 2.32–2.35 区间的精确下限，更不能推出所有发行版或所有硬件字段可用。当前结论只针对这次构建的二进制候选，不等同于判定整个源码库在 Debian 11 不可构建。

实体 Linux/macOS、多组 CPU、更多用户空间版本、最低内核、macOS 分发材料和正式发布仍待单独验收。公共 Rust API、C ABI 1、硬件 JSON Schema 1、ZIP 格式、依赖、feature、锁文件和 MIT 未变。
