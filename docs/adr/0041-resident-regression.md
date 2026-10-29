# ADR 0041：固定重复轮次的驻留内存回归

状态：固定源码的 Windows 本机与三平台原生 CI 40801172470 验收通过，见[性能报告](../benchmarks.md)。

## 问题与选择

历史峰值只会上升，无法说明释放后的当前驻留情况；一次短样本也不能证明长期无泄漏。因此保留原峰值测量，另加固定调用规模、固定检查点的当前驻留内存回归，不增加 allocator 或公共 API。

两个独立进程执行不同工作：

- 原生缓存采集：5000 次默认 C ABI collect/free；在 0、1、100、1000、2000、3000、4000、5000 次后采样。热身点为第 1000 次。
- 合成重建：60 批，每批重建采集器，执行 1 次 collect 和 100 次动态刷新，逐次 JSON 往返。共 60 次 collect、6000 次 refresh；在 0、1、10、20、30、40、50、60 批后采样。热身点为第 10 批。

第二种工作复用 [ADR 0040](0040-synthetic-memory.md) 的两个 Custom backend、100 个传感器和 1024 个网络条目。它不是生产 FFI 的执行路径，也不是实体设备观测。

## 计量口径

| 平台 | 当前驻留数据 | 原始单位 |
|---|---|---|
| Windows | `GetProcessMemoryInfo.WorkingSetSize` | bytes |
| Linux | `/proc/self/statm` 第二列 resident | pages，乘 sysconf 页面大小 |
| macOS | `task_info(MACH_TASK_BASIC_INFO).resident_size` | bytes |

Linux 的 statm 是内核近似计账，不能当作精确 allocator 用量；不读取更慢的 smaps 以改变原采样负载。其他平台也可能受共享页、工作集调整和后台活动影响，三者不作为跨平台排名。计量代码只查询自身；Linux 文件读取有长度、字段、符号和溢出检查，文件句柄必定关闭；Mac self-task port 为借用，不释放它。

原始数值、单位、换算倍数和历史峰值均保留。当前驻留值可以下降，不要求等于或小于另外一次 API 调用取得的历史峰值。每个驱动程序都有独立的 64 MiB 分配并逐页写入校准；当前驻留增量须为 32–128 MiB，换算单位须与工作负载一致。释放后的驻留内存可保留在系统或 allocator 缓存中，不强制回到起点。

## 预先固定的回归规则

预算为热身点及其后所有采样的 `max - min <= 16 MiB`。同时记录首尾差、最小值、最大值和实际样本数。中间升高后回落也会纳入范围，不能只用首尾两点掩盖超预算。

16 MiB 是有限 fixture 的回归门槛，不是库内存占用承诺或泄漏判定标准。超预算或校准失败时保留原始观测与分析，验收失败；不修改预算、缩短工作量或移走不利采样来获得通过。固定轮次不保证持续某个时长，报告保留实际批次耗时。

Linux 沿用 fork 启动隔离、父退出信号与有限等待。C 父进程最多等待 170 秒，Python 单进程等待上限 180 秒；CI 步骤仍为 10 分钟。Windows/macOS 为单个测量进程，超时后由调用脚本终止。原有源码/产物哈希、旧成功报告作废和失败记录规则继续适用。

## 未涵盖内容

这不是小时级或天级运行、allocator 归因、任意设备规模、驱动阻塞或长期无泄漏证明。真实 Linux/macOS 设备、长 fuzz 和正式发布仍单独跟踪。开发探针格式 2 仅增加新 profile 和相应字段；原 profile、正式 C ABI 1、硬件 Schema 1、Rust API、依赖和 feature 不变。

## 官方依据

- [Microsoft PROCESS_MEMORY_COUNTERS](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters)：当前与峰值工作集。
- [Linux proc_pid_statm](https://man7.org/linux/man-pages/man5/proc_pid_statm.5.html)：页面单位与近似计账限制。
- [Apple XNU task_info.h](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/mach/task_info.h)：MACH_TASK_BASIC_INFO 的 resident_size 单位。
