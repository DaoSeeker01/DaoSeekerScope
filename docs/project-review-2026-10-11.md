# 全项目检查与修复 · 2026-10-11

基线提交：`b26e298620cc0ace40dcfd4223514168bed0853a`。检查范围为 Git 跟踪的 231 个项目文件，以及本轮新增文件；不包含忽略的编译产物、下载工具或缓存。自动检查逐文件读取，验证结构化数据、Python 语法、文档本地链接与黄金样例；人工审查重点覆盖 8 个 crate、平台读取器、FFI、CLI、测试与 fuzz、脚本、CI 和文档。历史证据按对应提交保留，不改写成当前结果。这次检查不能证明不存在其他缺陷。

## 发现并修复的问题

P1 为数据/内存/资源契约问题，P2 为行为或验证入口问题，P3 为诊断与说明问题。下表均已完成实现或文档修正；最终平台执行结果单列。

| 编号 | 级别 | 问题及触发条件 | 修复与验证 |
|---|---|---|---|
| 01 | P1 | 自定义 backend 把零核数、零总内存返回为 Available，核心接受而 JSON 拒绝 | 核心逐字段转为 Unavailable/InvalidData；合法零运行时长保留 |
| 02 | P1 | 可用内存大于缓存总量可进入 Rust 快照，随后使整个 JSON 输出失败 | 在 backend 合并前校验，隔离坏字段；动态刷新同样生效 |
| 03 | P2 | 高优先级 Unsupported 能力擦除低优先级 Supported | 保留已存在的实现能力；构造前后均有回归 |
| 04 | P2 | 实际字段 Available，能力仍为 Unsupported/Restricted/NotApplicable | 更新为 Partial 并采用实际来源；不推断完整支持 |
| 05 | P3 | 同值仅来源或时间不同，也记录成值冲突 | 只比较值，来源仍按优先级选取 |
| 06 | P2 | 错误 backend 名称按字符截断，UTF-8 可超过 128 字节；空串/控制字符也可进入诊断 | 非法名称使用固定 custom；名称查询 panic 隔离，正常 fallback 不受影响 |
| 07 | P2 | JSON 诊断元数据允许空串及控制字符 | 编解码都校验非空、128 UTF-8 字节和控制字符；未来字段名仍可读取 |
| 08 | P1 | 紧凑 JSON 补齐默认字段后超过 1 MiB；解码成功但编码失败，fuzz 往返契约破坏 | 解码后有界计算编码大小，编码在分配前限制写入；加入紧凑输入回归及 fuzz 种子 |
| 09 | P2 | cpu 命令只有首次采样，正常机器也没有占用率 | 等待至少 300 ms 后第二次采集，静态数据继续用缓存；CLI 原生测试检查数值 |
| 10 | P2 | 输出管道接收端关闭，println panic，退出 101 | 有界缓冲后显式写出，BrokenPipe 正常结束，其他输出错误返回 3 |
| 11 | P2 | C 示例验证/输出失败路径直接返回，没有释放已分配 Buffer | 退出前释放；正常及陈旧复制契约继续验收 |
| 12 | P1 | Python 示例在 assert 中调用 free，python -O 会跳过释放及检查 | 采用显式检查和 finally 释放，接受合法不可用字段；普通与 -O 均运行 100 轮 |
| 13 | P2 | 三个 PowerShell 入口写死维护者工具、编译器和 SDK 路径，并依赖当前目录 | cargo 通过 PATH，MSVC/SDK 自动发现并允许显式参数；定位项目根目录，恢复环境和目录 |
| 14 | P2 | CI 只列举部分 Python 文件，Schema/许可证脚本和示例被遗漏；新文件也会漏检 | 按 scripts/tests 和示例目录检查全部 Python，单测发现所有 test_*.py；增加项目数据/链接检查 |
| 15 | P2 | Schema 检查用 assert，python -O 可跳过漂移和负面验证 | 显式 ValueError，优化模式也执行完整检查 |
| 16 | P2 | 门面 crate 测试 include_bytes 指向 crate 外部黄金样例，打包后找不到文件 | 测试使用 crate 内副本，项目检查防止三处黄金样例漂移；未宣称整组 crate 已发行打包 |
| 17 | P2 | benchmark 等待 250 ms，低于 Linux 300 ms 采样间隔 | 改为 300 ms，记录实际 CPU 状态，不将不可用值当成结果 |
| 18 | P3 | README 堆积验收历史、实现术语和本机绝对命令，首次访问难以上手 | 重写用途、能力表、可复制命令和短例子；技术契约移至使用指南 |
| 19 | P3 | GitHub 仓库简介偏术语，没有直接说明用途 | 改为“寻道者观微：跨平台硬件与系统信息库，支持 Rust、C 和命令行调用。” |
| 20 | P3 | 发布文档将旧 run 称作最新，文档缺少统一导航 | 当前入口指向工作流与本报告；新增文档目录，保留各日期原始记录 |

修复前，六项核心回归全部失败；修复后全部通过。旧 CLI 的关闭管道退出 101 且 panic，cpu JSON 状态为 unavailable。紧凑 JSON 在旧实现中被接受，新增回归复现失败；修复后返回 ResourceLimit。JSON 元数据校验与编码上限补充了负面测试。

README 结构参考 [fd](https://github.com/sharkdp/fd#readme) 和 [sysinfo](https://github.com/GuillaumeGomez/sysinfo#readme)：先说明用途，再给上手命令，把深入细节链接到专门文档；没有复制原文。CI action 固定版本已核实均使用 Node 24，保留现有 pin，没有为本轮无关升级增加变量。

## 验证结果

修复提交：`4ec4360a2cae1ab56f7218a3142444dd64217ee1`。对应 [CI 38070151022](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38070151022) 的 8 个任务均成功；[汇总证据](evidence/project-review-38070151022.json)记录测试数、锁文件和日志哈希，[CI 元数据](evidence/ci-run-38070151022.json)绑定 source commit。后续归档提交仅修改文档及脱敏证据，不能将其当成另一次源码运行。

| 实际执行 | 结果与边界 |
|---|---|
| 本地 `pwsh -NoProfile -File scripts/check.ps1 -Cross`，从项目外目录启动 | fmt/clippy、82 个 Rust 测试及 1 个 doctest、无默认 feature、doc（warnings 为错误）、CLI/FFI build，以及 Linux x64/macOS arm64 check 通过；交叉 check 不是原生读取 |
| Windows x64 / Linux x64 / macOS arm64 原生 CI | 分别 82/85/84 个 Rust 测试及各 1 个 doctest；CPU/内存/OS、C/Python smoke 通过 |
| `ruff format --check`、`ruff check`、`mypy --no-incremental --ignore-missing-imports` | scripts/tests 与 Python 示例全部 17 个文件通过 |
| `python -m unittest discover -s tests -p "test_*.py"` | 34 项通过，三个原生 CI 均实际执行 |
| `python scripts/check_project.py` | 修复提交的 241 个文件逐一读取，194 个本地链接检查；后续归档文件再检查，不覆盖历史源统计 |
| `python -O scripts/check_schema.py` | 生成 Schema/黄金样例无漂移，状态负面测试、版本拒绝和未知字段通过；CI 普通模式也执行 |
| MSVC C 示例、Python 示例普通及 -O 模式 | C collect/free、清零、空释放、陈旧复制通过；Python 两种模式各 100 次真实 collect/free；[本地原生证据](evidence/windows-native-review-2026-10-11.json)绑定干净提交 |
| `cargo fmt --manifest-path fuzz/Cargo.toml --check`、`cargo check --locked --manifest-path fuzz/Cargo.toml` | 本地格式和编译通过；Linux CI 八个独立 fuzz 目标各执行配置 60 秒并到达 DONE，含 compact-expansion 新种子 |
| Miri / Rust FFI ASan | 8/10 项通过；Miri 同时在本地通过，C/Python 例子不属于 ASan 覆盖范围 |
| Linux 非 root 容器 | 7 个退化场景、15 个 CPU 观测、26 个内存/uptime 观测、30 个电池、47 个 hwmon 观测通过；完整 /proc 替换仍被 OCI 拒绝且进程未启动 |
| `cargo bench --locked -p daoseeker-scope --bench collect` | Windows 优化 profile 单进程结果：首次 402089µs，100 次刷新 p50 40µs/p95 106µs/max 477µs，CPU 状态 Available；合成 100 传感器/1024 接口采集 505µs、JSON 366287 bytes；不是 Linux 驱动或峰值分配结论 |
| 其他文件/配置 | actionlint 通过；独立研究 probe 的 locked 读取通过；`cargo package --locked -p daoseeker-scope --list` 包含 crate 内黄金样例，未宣称完整发行打包通过；`cargo deny check` 在 CI 通过 |

执行中的修正与限制也保留：首次全门禁被新测试的 err().expect() clippy 提示阻断，改为显式匹配后完整重跑通过；首次本地 Python unittest 未加载 jsonschema，属于开发环境缺依赖，使用已固定开发依赖后 34 项通过。自动审批服务曾因额度未执行命令，用户继续后重试成功，没有将未执行写为验证。nightly Miri 对 stable 1.96 的 fetch_update 给出弃用提示；它不是错误，也未压低门禁或更改 MSRV。供应链允许项与锁不变。

## API、依赖与兼容性

8 个 crate 不变，无新增运行依赖、feature、公共签名或结构布局；MIT OR Apache-2.0 不变，C ABI 1 和 Schema 1 不变，两个主锁文件保持。新增项目检查脚本仅用 Python 标准库。

行为收紧：坏零值及不一致内存现在按字段隔离；空/控制字符诊断和展开超限 JSON 被拒绝。能力/冲突修正不会改变模型布局。JSON 解码增加一次有界编码大小遍历，有 CPU 开销，不承诺性能不变。cpu 命令增加至少 300 ms 采样等待，JSON 仍是完整快照；默认 --json 不增加这项等待。这些开发版本行为调整应由调用者注意，不能当成对所有原来输入的无条件兼容。

## 仍有边界与后续任务

- GPU、存储、网络、显示器，以及 Windows/macOS 温度、macOS 电池尚未实现；这不是已完成能力。
- Linux 电池、hwmon/NVMe 有模拟输入与内核权限证据，仍需真实设备读取及校准；原生 runner 无条目不算设备验证。
- Windows/macOS sysinfo 的失败/缓存表达仍为 Partial；阻塞系统调用无法安全强杀，超时只限制等待且保留 worker 配额。
- ABI v1 无 shutdown/排空接口，默认 worker 常驻；首次采集后共享库应保持加载至进程结束，动态卸载/热重载不属于支持契约。
- 正式 ADR/Schema 评审、逐 crate 发行打包、长期 fuzz、峰值分配 profiling 和发行/回滚演练尚未完成。各 crate 依赖尚未发布，完整 cargo package 验证需按依赖顺序执行。
- 完整 /proc 替换探针曾被 OCI 运行时拒绝，属于 not_run；移动、Web、no_std 和 MCU 不在当前已支持范围。

下一步优先在真实 Linux 电池与温度设备补采集证据，并按依赖顺序验证发行包。本文列出的修复不扩大平台支持声明。
