# glibc 2.34 候选运行验证

本轮补测产物声明的 `GLIBC_2.34` 要求。这里的用户空间是容器中的系统库与运行时，内核仍沿用 CI 宿主。现有 Debian 12 / glibc 2.36 成功和 Debian 11 / glibc 2.31 拒绝的历史记录仍保留在[较低版本环境验证](linux-runtime-container-validation.md)。

## 实施与复现

新增固定摘要的 UBI 9 / Python 3.12 场景；选择与边界见 [ADR 0043](adr/0043-linux-glibc234-runtime.md)。在已有本地 Docker 的 Linux x64 主机上，从干净提交运行：

```sh
cli=$(python scripts/cli_bundle.py)
sdk=$(python scripts/cli_bundle.py --product ffi_sdk)
python scripts/linux_runtime_container_smoke.py "$cli" "$sdk"
```

不安装 Docker、不更改 context、PATH 或系统库。测试拉取的镜像不随项目分发。报告为 `target/linux-runtime-container-evidence.json`；当前私有报告格式为 2，硬件 Schema 和 ABI 仍为 1。

三个场景使用同一组已构建的 CLI、共享库和 C 消费者；输入和完整安装文件均检查哈希，容器内不重编译。显式 Python 入口绕过镜像初始化脚本，实际 Docker 配置与运行身份须相符；原有断网、非 root、只读根目录、资源上限和退出清理保留。

## 当前状态

冻结提交 `ebb056d` 的[三平台 CI 40854571297](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40854571297)八项任务全部成功。[容器报告](evidence/glibc234-runtime-40854571297.json)记录三个场景的运行状态；[验收索引](evidence/glibc234-ci-40854571297.json)保存来源、哈希、七份报告及全部门禁结果。

| 固定用户空间 | 实际版本 | 结果 |
|---|---|---|
| UBI 9 | glibc 2.34，发行版本 9.8，Python 3.12.15 | CLI 版本/JSON、C 采集、Python 100 次 collect/free、Schema 与默认隐私通过 |
| Debian 12 | glibc 2.36，Python 3.13.13 | 同样的正面运行检查通过 |
| Debian 11 | glibc 2.31，Python 3.13.5 | CLI/C/ctypes 按预期报告缺失 GLIBC 版本，未开始采集 |

三个场景的 CLI、共享库和预编译 C 消费者哈希完全一致；未在容器内重建。容器均以 UID/GID 65534、断网、只读根目录运行；实际入口、64 MiB 工作区及 256 MiB 内存限制核验通过，三个容器均已移除。UBI 使用宿主内核 `7.0.0-1017-azure`，这不是最低内核证据。

Windows 本机仅运行配置、解析与负面回归：Python 274 项中 269 通过、5 跳过，包含 26 项容器回归；前后均绑定同一干净提交，未启动 Docker 或 Linux 二进制。首轮有一处 mypy 类型收窄标注遗漏，提交前已修正；记录保留，不当作成功门禁。

| CI 环境 | 八包隔离 Rust 测试 | Python 通过 / 跳过 |
|---|---:|---:|
| Windows x64 | 269 | 269 / 5 |
| Linux x64 | 261 | 274 / 0 |
| macOS ARM64 | 266 | 273 / 1 |

CI 的 fmt、严格 Clippy/文档、无默认功能编译、Schema、冻结契约检查、Ruff/mypy 与独立八包验收通过；各平台还有五组原生 CLI/C/Python 检查、16 次顶层调用。Linux 原有 CLI 七次、SDK 15 次调用及 300 次 Python collect/free 回归通过，不与新增容器运行混计。

Miri 8 项、ASan 11 项、12 个至少 60 秒的短 fuzz 目标及依赖安全检查通过。完整空 `/proc` 挂载仍被 OCI 在采集进程启动前拒绝，保持 `not_run`。小时／天级运行、长期 fuzz、实体 Linux/macOS 与多处理器组 Windows 均未执行。本轮未在本机重跑 Rust 门禁；上述 Rust 结果来自本轮原生 CI。

无 Rust 公共 API、生产行为、crate/features、依赖/锁、MIT、ABI 1 或硬件 Schema 1 变更，没有正式发布。

## 结论边界

这项测试只验证指定二进制在固定用户空间中的加载与采集。容器共享宿主 CPU/内核；它不验证实体 RHEL 设备、最低内核、所有 glibc 2.34 安装或其他发行版，也不把 UBI 9 自身的 CPU 要求当作本库最低指令集。
