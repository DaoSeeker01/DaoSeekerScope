# Windows 网络验证

源码 `5e43fdde5df11fbaa9b6590414de7ef7d88010e9` 的 [CI 38094160512](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38094160512) 全部 8 个任务成功。实现契约见 [ADR 0011](adr/0011-windows-network-counters.md)，[汇总证据](evidence/windows-network-ci-38094160512.json)绑定源码、报告/日志哈希及实际测试数。后续文档归档提交不是另一次源码 CI。

实现复用 NetworkInfo，Windows 能力 Partial/Win32。固定上限枚举和逐接口 64 位计数不覆盖全部逻辑隧道接口；系统缓冲包含未被读取/保存的标识，不能承诺标识从未进入进程内存。macOS 网络仍未实现。公共 API 形状、Schema 1、C ABI 1 与 MIT 许可证不变；仅增加 Windows target 的 windows-sys IpHelper/Ndis feature。

本机未提升权限的 Windows 进程通过 CLI/C 实读 43 条 Win32 接口计数，名称全部 Restricted/PrivacyRedacted；C 内存释放/清零/陈旧复制及 Python 100 次 collect/free 通过。[干净提交的本机报告](evidence/windows-network-native-local-windows-38094160512.json)和[进程权限/能力记录](evidence/windows-network-extra-local-windows-38094160512.json)均绑定上述源码。条目数不是物理网卡数量。

[真实 C ABI 限额探针](evidence/windows-network-limits-local-windows-38094160512.json)依次设 max_entries=128/1/128：网络 Available 43 条 → Unavailable/InvalidData → Available 43 条，CPU/内存始终 Available、ABI 状态 0、buffer 释放及清零通过。这是实际缓冲不足的拒绝证据；显式 options 每次创建新采集器，不是同一 collector 的热插拔或权限恢复测试。

已执行 `pwsh -NoProfile -File scripts/check.ps1 -Cross`：Windows fmt、Clippy、97 项 Rust 测试（含 1 doctest）、doc（拒绝警告）、no-default-features、CLI/FFI build、Linux/macOS cross-check 通过。另行执行 Linux x64/macOS arm64 全 target Clippy 拒绝警告。5 项新增模拟 API 测试验证资源、错误隔离、失败/恢复、授权与 UTF-16、取消/超时，不是内核权限或真实热插拔证据。

| 原生 CI / 回归门禁 | 实际结果 |
|---|---|
| Windows x64 / Linux x64 / macOS arm64 源码测试 | 各 97 / 95 / 94 项，均含 1 doctest；三平台 fmt/Clippy/doc/no-default-features 通过 |
| 三平台独立包/安装 | 各 8 个真实归档通过 MIT/头文件检查及原生 Cargo 验证；独立消费者测试数仍为 97 / 95 / 94，第三方锁文件未变 |
| 三平台 Python / Schema | Ruff 格式/检查、mypy --no-incremental（18 文件）、36 项 unittest、Schema 无漂移及项目一致性通过 |
| 三平台 CLI/C/Python 最小读取 | CPU/内存/OS 通过；Windows CLI/C 各 18 条 Win32 统计、Linux 各 4 条 Procfs 统计，名称全部脱敏；macOS 网络 Unsupported |
| Miri / FFI ASan / 供应链 | 8 / 10 项 FFI 测试通过、cargo-deny 通过；Linux 执行不覆盖 Windows 原生 unsafe |
| 9 个现有 fuzz 目标 | 每个实际运行至少 60 秒并到达 DONE，无崩溃；本轮没有 Windows 原生 fuzz 目标 |
| Linux 容器回归 | 通过，完整 /proc 替换仍为 runtime_mount_error / not_run；不推断已验证 Windows 权限或新命名空间 |

本机 `python scripts/check_packages.py --offline` 也完成原生 Cargo 验证、8 个实际归档、97 项独立 Rust 测试和 CLI 安装，[本机包报告](evidence/windows-network-package-local-windows-38094160512.json)记录锁未变、git_dirty=false，未发布 registry。`cargo bench --locked -p daoseeker-scope --bench collect` 实跑 43 条接口下 100 次刷新 p50/p95/max 为 2078/2464/3319 µs；两个运行样本与限制见[基准记录](benchmarks.md)和[原始日志哈希](evidence/windows-network-extra-local-windows-38094160512.json)。

长期 Windows 原生模糊测试、泄漏检测、真实权限拒绝/接口热插拔、故障驱动阻塞本轮尚未执行。调用等待有界不等于能终止阻塞的 OS API。

状态查询曾遭遇 EOF/TLS 超时，watch 进程因此失败；直接 API 及后续完整报告/日志确认任务全部成功。这是查询连接故障，没有重跑或跳过测试。下一步优先研究 macOS 同类网络计数的有界读取与隐私边界，不扩大 GPU、存储、移动/Web/MCU 的支持声明。
