# 原生验收失败诊断

2026-10-14，修复 `scripts/native_smoke.py` 的诊断缺口：八个文本命令不再共用 `cli_text` 标签，改为固定的 `cli_text_cpu`、`cli_text_memory` 等标签；逐条保存已完成的呈现检查，后续失败不丢弃前面结果。主报告仍使用 report_version 1，增加可选的 processes 和 failure_detail，不修改硬件 Snapshot Schema 1、C ABI 1 或 Rust 公共 API。

每个子进程记录状态、固定命令标签、实际退出码、输出字节数；失败另记录固定类别及能确认的库错误码。CLI 只有退出 3 且完整 stderr 匹配 `dscope: collection error: <已知错误码>` 才识别；C 示例只有退出 2 且 stderr 完整匹配 ABI 已知错误文字才识别。超过 512 字节、额外行、未知文字、不同退出码或 Python traceback 均不猜测错误码。scope_error 是子进程报告的库错误，不是驱动/API 根因证明。60 秒子进程超时与库内 Timeout 分开记录，原超时预算不变。

不保存原始 stdout/stderr、命令参数、路径、错误文本或设备标识。OSError/TimeoutExpired 转换在退出异常处理块后进行，不在新异常的 context/cause 中保留带原始信息的异常。stdout 保留既有 1 MiB 加换行上限，stderr 增加 1 MiB 事后检查；捕获后的长度检查不是恶意程序的硬内存沙箱，只运行受信任的项目产物。

失败时命令只执行一次，返回非零，后续命令保持 not_run；中断时 finally 保存部分进度及 interrupted 子进程状态，overall 仍为 incomplete。不会用自动重试覆盖失败，也不能从这次增强倒推出上次未保存的 stderr 或失败命令；上次原因未定位的记录继续保留。

新增七项测试，覆盖全部九个 CLI/C ABI 固定错误码、完整匹配与不同退出码、坏编码/超长消息、未知 stderr 脱敏、超时/缺失程序及异常上下文、stdout/stderr 超限、未知标签拒绝、实际 Python 子进程的模拟失败、部分进度、后续未执行和中断覆盖旧成功。模拟 Timeout 消息不代表真实硬件超时，也不属于真机证据。Ruff format/check、mypy（23 文件）、54 项 Python unittest 已通过；完整本机 smoke、干净源码及 CI 结果完成后补充。

Rust、采集器、CLI 命令与输出、FFI、Cargo 依赖/锁、feature、MIT 均未改变。本轮不重复运行本机 Rust/Miri/fuzz/性能门禁；三平台现有 CI 保留全部回归任务。设备测试按维护者安排：现有 Windows 笔记本可继续验收，Android 后续适配；其他实体设备测试延期，保持待验证，不冒充通过。
