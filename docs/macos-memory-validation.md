# macOS 内存读取验证

2026-10-22 本机为 Windows x64；本轮 macOS 原生 SDK 编译、符号链接和运行均未执行。实现与字段口径以 [ADR 0026](adr/0026-macos-memory.md) 为准，不能用交叉编译或历史 macOS CI 替代本轮证据。

MacosMemoryBackend 接管总量和可用估计。静态成功/失败均缓存；动态每次重新查询总量并读取公开 VM 统计，错误没有旧值/旧时间。总量变化暂不可用，需重建 Hardware。静态失败仍可在动态恢复；一个字段失败不令整份快照失败。

两项能力均 Partial：总量的 hw.memsize 是物理代理；可用内存是 active+inactive+free 页的非压缩估计，并不保证立即可分配。OS VM 入口可限流并返回缓存，本库不识别其确切年龄，不保证刷新得到新计数或不同数字。Observed 时间只标成功调用完成，不是 OS 统计更新时间；本轮解决显式读取错误，不声称消除系统缓存。

十项可移植 Rust 测试覆盖：截短/超长 VM 回复和 sysctl 长度、逐次读与静态缓存、重复值/真实零、失败无旧值及恢复、静态失败缓存/动态恢复、总量变化阻断、4/16 KiB 单位及 speculative 不重复计数、unsigned 上界/溢出/超过总量拒绝、errno 与 Mach 命名空间、取消/超时前后边界、host right 的释放失败/展开不重复释放。其中形状边界与其他相关断言合并于十个测试函数；不注入畸形指针。

独立公开 C SDK 探针只请求 rev1 的 38 words（152-byte 前缀），允许当前 SDK 完整结构更大；与 Rust libc 请求一致。检查页大小、返回形状、无符号计数、总量及释放状态。最多八条命令、固定栈缓冲，不采集标识或制造内存压力。Python 仅启动两个子进程，单行 1 MiB、读/退出 5 秒；失败覆盖旧 passed，保留过滤后的未完成观测，错误日志不带原始路径。

原生复现入口（待 macOS 执行）：

```sh
cargo build --locked -p daoseeker-scope --example dynamic_probe
cc -Wall -Wextra -Werror -std=c11 docs/research/macos_memory_probe.c -o target/macos-memory-probe
python scripts/macos_memory_smoke.py
```

持久进程计划验证初始值、三次刷新、总量缓存及重建；只要求成功调用时间递增，不要求动态值变化或与另一个进程相等。SDK 与 Rust 都使用公开入口，不能据相同数字证明数据新鲜度、没有 OS 缓存或可立即分配。

公开增加 MacosMemoryBackend::new()/Default，门面自动注册，MacosBackend 单元构造不变。总量/动态来源改为 Sysctl/AppleApi；单独 macOS SysinfoBackend 消费者须迁移。无新依赖、feature、锁文件或许可证，模型、C ABI 1、Schema 1、MIT 不变。

待验证：macOS 原生 SDK/链接/读取、真实 errno/Mach/清理故障、App Sandbox、Intel 原生、实体 Mac、VM 缓存年龄、长期端口/内存增长和峰值内存。按维护者设备安排延期实体验证；协作式取消不能强制终止阻塞内核调用。


## 本机门禁（2026-10-22）

Windows x64 实际执行 `pwsh -NoProfile -File scripts/check.ps1 -Cross`：229 项 Rust 测试（含 doctest）通过，fmt、all-target/all-feature Clippy 拒绝 warning、core/门面无默认 feature、doc 拒绝 warning、CLI/FFI 构建及 Linux x64/macOS arm64 编译通过。额外 `cargo clippy --locked --workspace --all-targets --all-features --target aarch64-apple-darwin -- -D warnings` 通过；它不链接或执行 Mach。

Python 固定 Ruff 0.14.13/mypy 1.19.1 检查 40 个源文件，103 项单测和 jsonschema 4.25.1 Schema 回归通过。四项新增内存报告测试覆盖字段状态/值域、SDK rev1 与完整结构差异、unsigned/页单位/资源释放状态、重复值可接受、失败/中断覆盖旧 passed；另有一项 CLI 代理/估计标签守卫。负面测试故意输出 failed，不能把它写成 Mac 原生读取。

CLI 按来源展示 `Physical total proxy bytes` / `Non-compressed estimate bytes`，memory 与 system 总量一致，不把 macOS 估计标成普通立即可用量；缺失状态仍原样保留。文本不是稳定程序协议，JSON 字段名保持 Schema 1。

现有 Windows C ABI collect/free、归零/空释放/旧副本拒绝通过；fuzz 格式和两个现有 harness 单元测试通过。没有执行本轮实际 libFuzzer、Miri、ASan、性能基准或 macOS C SDK。一次沙盒 doctest 因临时目录拒绝写 executable 失败，正常本机权限重跑成功；新 Python 测试的嵌套字典类型标注已修正，最终静态检查没有放宽。
