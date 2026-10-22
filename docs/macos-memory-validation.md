# macOS 内存读取验证

以下首先保留 2026-10-22 Windows x64 本机阶段记录，当时 macOS 原生 SDK 编译、链接与运行未执行；后续原生 CI 与修复结果另列。实现与字段口径以 [ADR 0026](adr/0026-macos-memory.md) 为准，不能用交叉编译或历史 macOS CI 替代本轮证据。

MacosMemoryBackend 接管总量和可用估计。静态成功/失败均缓存；动态每次重新查询总量并读取公开 VM 统计，错误没有旧值/旧时间。总量变化暂不可用，需重建 Hardware。静态失败仍可在动态恢复；一个字段失败不令整份快照失败。

两项能力均 Partial：总量的 hw.memsize 是物理代理；可用内存是 active+inactive+free 页的非压缩估计，并不保证立即可分配。OS VM 入口可限流并返回缓存，本库不识别其确切年龄，不保证刷新得到新计数或不同数字。Observed 时间只标成功调用完成，不是 OS 统计更新时间；本轮解决显式读取错误，不声称消除系统缓存。

十项可移植 Rust 测试覆盖：截短/超长 VM 回复和 sysctl 长度、逐次读与静态缓存、重复值/真实零、失败无旧值及恢复、静态失败缓存/动态恢复、总量变化阻断、4/16 KiB 单位及 speculative 不重复计数、unsigned 上界/溢出/超过总量拒绝、errno 与 Mach 命名空间、取消/超时前后边界、host right 的释放失败/展开不重复释放。其中形状边界与其他相关断言合并于十个测试函数；不注入畸形指针。

独立公开 C SDK 探针只请求 rev1 的 38 words（152-byte 前缀），允许当前 SDK 完整结构更大；与 Rust libc 请求一致。检查页大小、返回形状、无符号计数、总量及释放状态。最多八条命令、固定栈缓冲，不采集标识或制造内存压力。Python 仅启动两个子进程，单行 1 MiB、读/退出 5 秒；失败覆盖旧 passed，保留过滤后的未完成观测，错误日志不带原始路径。

原生复现入口（本机阶段待执行，后续 CI 结果见下节）：

```sh
cargo build --locked -p daoseeker-scope --example dynamic_probe
cc -Wall -Wextra -Werror -std=c11 docs/research/macos_memory_probe.c -o target/macos-memory-probe
python scripts/macos_memory_smoke.py
```

持久进程计划验证初始值、三次刷新、总量缓存及重建；只要求成功调用时间递增，不要求动态值变化或与另一个进程相等。SDK 与 Rust 都使用公开入口，不能据相同数字证明数据新鲜度、没有 OS 缓存或可立即分配。

公开增加 MacosMemoryBackend::new()/Default，门面自动注册，MacosBackend 单元构造不变。总量/动态来源改为 Sysctl/AppleApi；单独 macOS SysinfoBackend 消费者须迁移。无新依赖、feature、锁文件或许可证，模型、C ABI 1、Schema 1、MIT 不变。

本机阶段尚未验证的范围：macOS 原生 SDK/链接/读取、真实 errno/Mach/清理故障、App Sandbox、Intel 原生、实体 Mac、VM 缓存年龄、长期端口/内存增长和峰值内存。按维护者设备安排延期实体验证；协作式取消不能强制终止阻塞内核调用。


## 本机门禁（2026-10-22）

Windows x64 实际执行 `pwsh -NoProfile -File scripts/check.ps1 -Cross`：229 项 Rust 测试（含 doctest）通过，fmt、all-target/all-feature Clippy 拒绝 warning、core/门面无默认 feature、doc 拒绝 warning、CLI/FFI 构建及 Linux x64/macOS arm64 编译通过。额外 `cargo clippy --locked --workspace --all-targets --all-features --target aarch64-apple-darwin -- -D warnings` 通过；它不链接或执行 Mach。

Python 固定 Ruff 0.14.13/mypy 1.19.1 检查 40 个源文件，103 项单测和 jsonschema 4.25.1 Schema 回归通过。四项新增内存报告测试覆盖字段状态/值域、SDK rev1 与完整结构差异、unsigned/页单位/资源释放状态、重复值可接受、失败/中断覆盖旧 passed；另有一项 CLI 代理/估计标签守卫。负面测试故意输出 failed，不能把它写成 Mac 原生读取。

CLI 按来源展示 `Physical total proxy bytes` / `Non-compressed estimate bytes`，memory 与 system 总量一致，不把 macOS 估计标成普通立即可用量；缺失状态仍原样保留。文本不是稳定程序协议，JSON 字段名保持 Schema 1。

现有 Windows C ABI collect/free、归零/空释放/旧副本拒绝通过；fuzz 格式和两个现有 harness 单元测试通过。没有执行本轮实际 libFuzzer、Miri、ASan、性能基准或 macOS C SDK。一次沙盒 doctest 因临时目录拒绝写 executable 失败，正常本机权限重跑成功；新 Python 测试的嵌套字典类型标注已修正，最终静态检查没有放宽。


## 干净源码验收归档

实现源码 `57500a6f1e6fde0b98cc3258919cb88bcf5cf87d`，执行时工作区干净。[完整本机索引](evidence/macos-memory-local-57500a6.json)绑定命令、日志哈希、源码与明确的 not_run 项。

- [Windows 原生回归](evidence/macos-memory-native-windows-57500a6.json)：五组、16 个 CLI/C/Python 进程通过，Python 100 次默认 collect/free。它验证 Windows 回归，不是 Mac 内存读取或 Mach 资源实测。
- [八包独立验收](evidence/macos-memory-packages-windows-57500a6.json)：实际 Cargo 归档/原生验证、提取后独立 workspace 的 229 项 Rust 测试、MIT/头文件/锁文件及 dscope 0.1.0 安装/完整 JSON 通过。第三方锁不变，未发布兄弟包由本地 patch 提供，不代表 registry 发布验收。

以上为远程 CI 前的本机归档；随后原生 CI 结果见下节，实体设备仍按既定安排延期。

## 首轮 CI 失败（后续已定位修复）

运行 39695461224，源码 cd06481：macOS 的 desktop_minimum_real_read_and_refresh 在动态内存缺值断言失败。保留严格最小读取要求，不改为允许缺失；补充失败字段及独立 SDK 的安全状态/形状/单位诊断，并提前执行 SDK preflight，使测试失败仍保留观测。首轮其余未完成任务已申请停止，不能记为全套验收通过。具体原因与修复后的完整验收见下节。


## CI 定位与固定前缀修正

后续诊断 39695983577 / 39696262794 复现：独立 C SDK 请求 38 words，返回 38，页大小 16384，完整 SDK 结构 248 bytes；Rust 实际绑定缓冲 416 bytes、以完整大小请求 104 words，内核按当前支持返回 62，随后被硬编码 38 的校验拒绝。不是权限拒绝或单位溢出，也不是全库支持失败。

根因是实现读取了缓存中的 libc 0.2.186 源码，却未核对已锁定的 0.2.190；原本机记录/索引关于绑定缓冲为 152 bytes 的描述不成立，保留历史报告并在此更正，它们从未构成 Mac 原生验收。本轮没有升级 libc 或修改锁文件。

修正明确设置请求为 38，容纳它的绑定缓冲允许更大；编译期验证容量和字段偏移，运行时仍严格要求返回 38，拒绝 62/104 等不同形状。增加原生 Rust SDK 定向读测试并在完整 workspace 测试前执行。主桌面成功读取断言保持严格；诊断只记录数字/安全状态，不包含设备标识或路径。三个失败运行的剩余任务均已取消，最终验收必须来自修复后的完整新运行。


## 修复后的三平台 CI（2026-10-22）

[运行 39696658516](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/39696658516)，源码 `b8b6383b007a7efe56f4513e3fc786e0406a3901`，全部 8 个任务成功。此前三个失败/诊断运行及取消范围见[失败证据](evidence/macos-memory-initial-failures-39696658516.json)，不能把它们计为成功，也不能称本轮一次通过。

| 平台 | workspace / 八包独立测试（含 doctest） | Python 单测 | 原生 CLI/C/Python |
|---|---|---|---|
| Windows x64 | 229 / 229 | 103 | 五组、16 个进程通过 |
| Linux x64 | 222 / 222 | 103 | 五组、16 个进程通过 |
| macOS ARM64 | 226 / 226 | 103 | 五组、16 个进程通过 |

fmt、Clippy（拒绝 warning）、无默认 feature、doc（拒绝 warning）、Ruff/mypy（40 个源文件）、Schema/链接检查、八包 Cargo 归档及独立 CLI 安装通过。Python 各执行 100 次 collect/free。兄弟包用本地 patch，不代表 registry 发布验收。[完整索引](evidence/macos-memory-ci-39696658516.json)保存十三份报告、来源和日志哈希。

macOS 定向 Rust SDK 测试先于 workspace 执行一次，并在 workspace 的 226 项中正常包含，不能额外算成第 227 项。日志确认：Rust 绑定缓冲 416 bytes / 104 words，明确请求 38，实际返回 38；编译期容量/偏移检查及原生实际读取均通过。C SDK 完整结构在本次为 248 bytes，仅请求相同 152-byte 前缀，页大小 16384 bytes。

[公开 SDK 与持久刷新报告](evidence/macos-memory-sdk-39696658516.json)确认总量为 7516192768 bytes、Source Sysctl；动态为 AppleApi，三次刷新时间递增，静态总量的完整 Observed 保持缓存，重建后仍可读。四帧 C SDK 的 host right 显式释放均成功；没有测量 Rust Mach 端口的长期净增长。

| 观测 | Rust 非压缩估计 bytes | 独立 SDK 估计 bytes |
|---|---|---|
| 初始 | 6275465216 | 6275465216 |
| 1 | 6274908160 | 6274744320 |
| 2 | 6277464064 | 6277349376 |
| 3 | 6277464064 | 6277464064 |

不同进程的读取时间不同，允许数值相同或不同。上述成功不证明计数无缓存或立即可分配；系统缓存/限流边界、物理总量代理和非压缩估计定义仍保持 Partial。Observed 时间是成功调用完成时间，不是内核更新时刻。

Windows [CPU SDK](evidence/macos-memory-windows-sdk-39696658516.json)、[64 MiB 内存 SDK 实验](evidence/macos-memory-pressure-39696658516.json)和既有 macOS CPU SDK 回归通过。Linux 八份容器报告通过，含 CPU 15、内存/uptime 26、电池 30、hwmon 47、存储 21、GPU 20、显示器 26 项及既有 DMI/输入检查；完全空 `/proc` 仍被 OCI 拒绝，保留 not_run。

11 个实际 fuzz 目标各运行至少 60 秒，Miri 8 项、Linux Rust FFI ASan 10 项及 cargo-deny 通过；不是 Mach 原生指针或长期无漏洞证明。Linux/macOS 常规整库基准及原始日志见[性能记录](benchmarks.md)，没有旧版配对，不宣称性能改善。

实际锁定 libc 0.2.190，本轮没有包/版本/features/锁文件升级；先前依据缓存旧源码的缓冲描述已更正。新增 MacosMemoryBackend 和来源/CLI 标签迁移维持 ADR 0026；公共模型、C ABI 1、Schema 1、MIT 不变。验收归档只改文档。

剩余边界：实体 Mac、Intel 原生、App Sandbox、真实 API/清理失败、总量变化、缓存最大年龄、长期泄漏/峰值内存和内核强制中止未验证。故障注入测试不等于设备故障实验；未发布 registry 或 release 制品。Windows/macOS uptime 可靠性留给下一独立切片。
