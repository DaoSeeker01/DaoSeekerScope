# C ABI 句柄与文件描述符检查

这项检查在单个 C 进程中反复采集并释放 Buffer，观察进程持有的句柄或文件描述符数量。它补充[内存采样](timed-soak-validation.md)，不用于证明长期无泄漏。决策见 [ADR 0046](adr/0046-resource-count-regression.md)。公共 API、ABI 1、硬件 Schema 1 与依赖不变。

准备项目 Python 环境、锁定工具链与 C 编译器，在干净提交上运行：

```sh
python scripts/resource_regression.py
```

报告位于 `target/resource-evidence.json`。工具离线构建 release/default serde 共享库，绑定提交、工作树状态、编译器和二进制哈希；开始即作废旧成功结果。子进程等待上限为 210 秒，构建上限为 900 秒。失败或中断不能算通过，不发布任何产物。

## 计数范围

| 平台 | 方法 | 边界 |
|---|---|---|
| Windows | `GetProcessHandleCount` | 当前进程内核句柄；不包含 GDI/USER 对象 |
| Linux | 枚举 `/proc/self/fd` | 排除枚举目录自身的描述符，不读取链接目标或文件路径；扫描超过 65536 项即失败 |
| macOS | `fcntl(F_GETFD)` | 只检查编号 0–65535；不声称覆盖更高编号、Mach port 或完整资源表 |

Windows 语义依据 [Microsoft 文档](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesshandlecount)，Linux 目录语义依据 [内核文档](https://www.kernel.org/doc/html/latest/filesystems/proc.html)，`fcntl` 依据 [POSIX](https://pubs.opengroup.org/onlinepubs/9799919799/functions/fcntl.html)。macOS 使用公开 POSIX 接口，不使用标为私有的 libproc 接口。枚举不是原子快照；后台活动和驱动可能影响观测，不据此比较各平台优劣。

## 事前规则

1. 独立进程先计数，再打开 32 个事件句柄（Windows）或 `/dev/null` 描述符（Unix）。计数必须恰增 32，全部关闭后必须回到基线。
2. 正常进程执行 1000 次默认缓存 collect/free。每次检查状态、Buffer 长度/指针/token 和释放清零；不输出设备快照。第 100 次作为热身后的首个采样，此后每 100 次采样，共十个点。
3. 事前固定十个点的最大值减最小值不得超过 8。计数下降允许，但中途增长不能被末尾下降掩盖。
4. 另一个对照进程在第 100 次采样后故意保留 16 个资源，完成同一工作量后关闭。分析必须发现它超出同一预算；这是对检测能力的阳性对照，不是项目发生泄漏。

预算不是允许每次调用泄漏 8 个资源，也不是长期稳定承诺。固定轮次、采样间隔、Windows 句柄类型和 macOS 编号边界均有限；硬件变化、长时间运行、线程/端口/GDI 对象与 allocator 分析仍需独立验证。校准与阳性对照只使用临时本地资源，不改变系统配置。

## 验证状态

新增七项协议测试，覆盖各平台计量约定、坏校准、改动计划、缺失/乱序/非法样本、下降/中途增长、预算边界及失败/中断作废。MSVC 优化 C11 严格编译、Ruff、mypy（73 文件）与 actionlint 已通过。本机首轮临时目录测试受沙盒权限限制，原测试在现有非沙盒环境通过；一次补丁上下文不匹配未应用，修正后继续验证。

本机 Python 全套 297 项中 292 通过、5 跳过。提交前的 C 预检中，校准恰增 32，关闭后回到基线；正常十个点不变，阳性对照恰增 16。该预检未绑定干净提交，与下面的正式验收分开记录。

冻结提交 `29cab6e` 的本机与[三平台 CI 41036279407](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/41036279407)已完成，八项任务全部成功。四份原始报告、源码/二进制哈希与任务来源见[验收索引](evidence/resources-ci-41036279407.json)。

| 环境 | 正常组首点→末点 | 正常组十点范围 | 对照组十点范围 | 校准增量/关闭后增量 |
|---|---:|---:|---:|---:|
| Windows 本机 | 151→151 | 0 | 16 | 32/0 |
| Windows x64 CI | 149→149 | 0 | 16 | 32/0 |
| Linux x64 CI | 3→3 | 0 | 16 | 32/0 |
| macOS ARM64 CI | 3→3 | 0 | 16 | 32/0 |

每个正常组和对照组均完成 1000 次真实缓存 collect/free。正常组符合事前范围预算 8；故意保留 16 个资源的对照按预期被判为超预算，所有校准通过。范围为零只表示十个采样点相同，不能排除采样间隔内变化、范围外资源或长期泄漏。

三平台各八包独立 Rust 测试为 Windows 269、Linux 261、macOS 266；Python 通过/跳过分别为 292/5、297/0、296/1。fmt、严格 Clippy/doc、无默认功能、Schema、契约、许可清单生成、原生 C/Python、候选安装回滚及原有峰值/驻留/定时采样回归通过。Miri 8、ASan 11 与 12 个短 fuzz 目标至少各 60 秒通过。许可清单生成不表示分发获准，macOS 材料缺口仍未解决。

完整空 `/proc` 挂载仍被 OCI 拒绝，保留 `not_run`。实体 Linux/macOS、多处理器组 Windows、小时／天级、长期 fuzz、Mach port、GDI/USER 对象与 allocator 分析未执行。本轮没有改变 Rust API、依赖/features/锁文件、ABI 1、硬件 Schema 1 或 MIT，未正式发布。
