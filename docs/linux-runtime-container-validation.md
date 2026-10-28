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

## 本轮状态

首轮 CI 40609811580 在启动任何容器前因 `runtime_payload_limit` 失败：完整候选总载荷超出工具写死的 32 MiB 门槛。该轮没有用户空间运行证据，失败报告保留；不能算作 Debian 兼容性失败或成功。本轮修正为按 64 MiB 实际工作区计算完整安装预算并保留 16 MiB 余量，额外核对容器内复制前后真实空间。许可证、二进制、镜像及隔离限制保持原样，修正后的原生结果仍待 CI。

已实现两项固定摘要的环境检查，原生结果待本轮 CI：

| 环境 | 验收条件 | 不能据此得出的结论 |
|---|---|---|
| Debian 12 / glibc 2.36 | 相同哈希的 CLI、C 和 Python 正常运行；CLI/C Schema、最低读取和默认隐私通过；Python 完成 100 次 collect/free | 所有 Debian 12 设备、精确最低 glibc、最低内核或所有硬件字段均可用 |
| Debian 11 / glibc 2.31 | CLI/C 和 ctypes 仅因已声明的更高 GLIBC 版本缺失而加载失败 | 该环境受支持或库已经成功采集 |

本机 Windows 没有启动容器或 Linux 程序；单元测试只证明守卫逻辑、报告校验及异常清理路径。镜像摘要来源见[记录](evidence/linux-runtime-images-2026-10-28.json)，它不是镜像运行证据。

源码 `2f0c90009ba148e66e97b9247b443736a76647e5` 已完成本机门禁：Python 208 项中 203 项通过、5 项既有平台测试跳过，新增容器守卫 15 项全部通过；Rust 264 项、fmt、严格 Clippy/文档、无默认 feature 及 Linux x64/macOS ARM64 交叉检查通过。Ruff/mypy 检查 63 个文件，actionlint 与项目守卫通过，见[本机记录](evidence/linux-runtime-container-local-2f0c900.json)。本轮原生容器仍待 CI，不采用上一轮的运行结果。

正面场景中，候选先复制到容器内 `/work` 的新目录，再按 manifest 检查完整文件和执行文件的哈希；Rust 二进制与 C 消费者均不会在该环境重新编译。报告只保存结果、运行环境、哈希和受控配置，原始默认脱敏快照在宿主验证后丢弃。

报告的 `payload_bytes`、`work_budget` 和各环境的 `installation_storage` 分别记录载荷、按分配单元估算的安装占用及真实可用空间。预算不包含删除或共享许可证文件的优化；若容量或余量不足，应记录失败并检查产物规模，不得降低检查标准。

内核与 CPU 来自 CI 宿主。实体 Linux/macOS、多组 CPU、更低 glibc 区间、最低内核及正式发布仍待单独验收。当前没有新增公共 API、依赖、feature 或许可证变化。
