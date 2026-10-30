# 定时 C ABI 采集试验

这项试验在一个 C 进程中持续采集、检查并释放 Buffer，每分钟记录一次内存与累计调用数。它补充已有[固定轮次测量](benchmarks.md)，并不等于长期稳定性或无泄漏证明。规则见 [ADR 0045](adr/0045-timed-cached-sampling.md)。

在干净提交上，准备项目 Python 开发环境、锁定的 Rust 工具链及平台 C 编译器后运行：

```sh
python scripts/timed_soak.py --seconds 600
```

支持 120–3600 秒、60 秒的整数倍。默认 120 秒用于 CI；3600 秒选项只是工具能力，未执行时不能声称已有一小时证据。Windows 需要 MSVC/Windows SDK 和 PowerShell 7；Linux/macOS 需要 C11 编译器。工具不安装系统软件、不改 PATH、不发布产物。

报告写入 `target/timed-soak-evidence.json`，逐分钟检查点写入同名 `.ndjson`，开始前作废旧结果。只有完成全部计划、校准、预算与来源核对才写入 `passed`。超时、错误或中断不能使用旧通过报告；部分观测可用于诊断，不算验收。试验会调用普通用户可读的硬件接口，默认脱敏。

600 秒试验预先设置 300 秒热身，此后六个分钟检查点的驻留范围不得超过 16 MiB；120 秒试验只有两个热身后检查点，证据更有限。每次调用后请求休眠 100 ms，实际频率受采集耗时与调度影响。当前驻留值允许下降；历史峰值不应下降，二者不能互换。

冻结提交 `3d17320` 的本机 600 秒试验与[三平台 CI 40976829533](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40976829533)八项任务已完成；四份试验报告与来源/哈希见[验收索引](evidence/timed-soak-ci-40976829533.json)。每组均通过独立 64 MiB 驻留计量校准、完成标记、时间/单位/计数、事前预算和源码/二进制一致性核对。

| 环境 | 计划秒数 | 实际 collect/free 次数 | 热身后采样数 | 驻留范围 bytes |
|---|---:|---:|---:|---:|
| Windows 本机 | 600 | 5441 | 6 | 180224 |
| Windows x64 CI | 120 | 1105 | 2 | 184320 |
| Linux x64 CI | 120 | 1190 | 2 | 0 |
| macOS ARM64 CI | 120 | 674 | 2 | 0 |

各环境硬件与时长不同，表内结果仅用于各自的预算核对。范围为 0 只表示这些采样点相同，不表示没有分配或泄漏。原始报告包含 CPU、内存、OS、Rust/C 编译器、release/default serde、每个检查点的原始单位和历史峰值；没有把峰值与当前驻留值互换。C 编译沿用开发探针的优化 C11 配置（Windows `/W4 /WX /O2 /std:c11`；Linux/macOS `-O2 -Wall -Wextra -Werror -std=c11`）。

采样前另行运行一次 CLI，检查 Schema、最低读取和默认隐私；计时循环逐次检查返回码、Buffer 长度/指针/token 和释放清零结果。原始 NDJSON 有界保留，非固定探针诊断脱敏；stderr 摘要覆盖最多 4097 字节的诊断前缀。此试验不分析 FD/句柄数或 allocator。

新增 8 项 Python 协议回归；本机全套 290 项中 285 通过、5 跳过。首轮发现一个未使用的测试 import，已在提交前修正；一次补丁上下文不匹配在应用前失败，修正后重新验证。MSVC 严格编译同时覆盖普通与合成探针；Ruff、mypy（71 文件）、文档和 actionlint 检查通过。

CI 各八包独立 Rust 测试为 Windows 269、Linux 261、macOS 266，Python 通过/跳过分别为 285/5、290/0、289/1；fmt、严格 Clippy/doc、无默认功能、Schema、原生 C/Python、候选安装回滚及原有固定轮次内存回归通过。Miri 8、ASan 11、12 个短 fuzz 目标至少各 60 秒通过；完整空 `/proc` 挂载仍为 `not_run`。这些结果不替代延期设备验证。

未执行的小时／天级运行、长期 fuzz、实体 Linux/macOS 和 allocator 归因继续保留为待办。正式 API、ABI 1、硬件 Schema 1、依赖/features、MIT 不变；未发布软件。
