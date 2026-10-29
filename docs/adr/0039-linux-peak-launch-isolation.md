# ADR 0039：隔离 Linux 峰值测量的启动阶段

状态：已实现并完成 Windows 编译与回归；Linux 原生对照待 CI，结果另存[性能报告](../benchmarks.md)。

## 问题

上一轮 Linux 报告在采集前已有 30375936 字节的历史峰值，后续调用均未超过它。`ru_maxrss` 可保留 exec 前的资源计账，直接从 Python 启动 C 程序会把启动阶段的内存带入结果。旧报告保留，不把平坦计数解释为零分配。

## 实现

Linux C 探针在输出和任何 Rust 调用之前 fork。父进程只保留小型 C 程序的当前映像，子进程重新建立资源计账，再执行原有采集。父进程等待并传递子进程退出码；失败不得回退到直接测量并冒充隔离成功。Windows/macOS 仍直接执行。

fork 只发生在开发探针的单线程启动阶段，不在已运行采集器的应用中 fork。子进程设置 `PR_SET_PDEATHSIG=SIGKILL`，并复核父 PID，覆盖父进程提前退出的竞态。父进程另有 170 秒 alarm，Python 最多等待 180 秒；测量进程不会因外层超时而永久存活。

探针私有 JSON 格式升至 2，增加启动方式、父子 PID 和父退出信号。Python 仍能校验旧格式 1，但本轮验收必须是格式 2，Linux 必须显示独立父子进程。Rust API、C ABI 1、硬件快照 Schema 1 和候选包格式不变。

## 验证

- 保留原有独立 64 MiB 校准、300 次缓存调用、30 次重建调用及 buffer 释放检查。
- Python 父进程额外持有并逐页写入 128 MiB，同时分别运行直接和隔离路径。要求直接路径基线至少 128 MiB，隔离基线至少低 64 MiB；这是启动污染对照，不是性能改善或库内存上限。
- Linux 生命周期探针输出父子身份后等待。验证程序终止自己创建的父进程，要求测量进程五秒内不再运行；僵尸状态单独记录，不宣称已被外部 reaper 回收。探针自身还有 15 秒兜底 alarm。
- 失败清理使用 pidfd 定位原进程，不向可能复用的数字 PID 发送信号。pidfd 始终关闭；读取 `/proc/<pid>/stat` 有大小上限，并检查父 PID、启动时刻与状态。

生命周期验证需要 Python 的 pidfd API、Linux 5.3+ 与可读的自身子进程 `/proc`。这是开发验证工具的要求，不是核心库的新最低内核声明。限制或接口缺失时如实失败，不提高权限或跳过后宣称通过。

## 结果边界

新基线仍包括 C 映像、动态库和线程，不是 allocator 用量。fork 后的当前映像仍会计入基线；小于该基线的变化仍可能不可见。旧结果与新结果的启动方式不同，不能作性能提升比较。持续增长、合成大规模设备和长期 fuzz 继续单独验证。

## 官方依据

- [fork](https://man7.org/linux/man-pages/man2/fork.2.html)：子进程的资源计账与单线程要求。
- [getrusage](https://man7.org/linux/man-pages/man2/getrusage.2.html)：Linux 单位和 exec 保留计账的规则。
- [PR_SET_PDEATHSIG](https://man7.org/linux/man-pages/man2/PR_SET_PDEATHSIG.2const.html)：父线程退出、设置竞态与信号语义。
- [pidfd_open](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)：进程身份句柄及内核版本要求。
