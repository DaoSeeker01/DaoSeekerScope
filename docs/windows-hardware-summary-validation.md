# Windows 硬件摘要验证

契约见 [ADR 0030](adr/0030-windows-hardware-summary.md)。2026-10-25 本机 Windows x64 的六个白名单值均存在，为 REG_SZ，字符长度分别为 14/9/8/9/12/12；只查询了六个固定名称，没有枚举键或设备标识。

现有 WindowsBackend 的静态入口只读六个固定名称，来源 Win32/Partial，不新增公共消费类型或序列号读取。4096-byte 固定缓冲、严格 REG_SZ/UTF-16、控制字符和占位词检查、错误隔离与合作式取消见 ADR。成功和缺失都由 Hardware 静态缓存；refresh_dynamic 不重读，重建 Hardware 后重新采集。注册表可缺失或修改，OEM 文字不是硬件真实性、固件安全或当前运行固件版本的证明。

可复现命令：

```powershell
pwsh -NoProfile -File scripts/check.ps1 -Cross
cargo clippy --locked --workspace --all-targets --all-features --target aarch64-apple-darwin -- -D warnings
cargo clippy --locked --workspace --all-targets --all-features --target x86_64-unknown-linux-gnu -- -D warnings
cargo build --locked -p daoseeker-scope --example dynamic_probe
pwsh -NoProfile -File scripts/build_c_example.ps1 -HardwareSummaryProbe
python scripts/windows_hardware_summary_smoke.py
python -m unittest discover -s tests -p "test_*.py"
python scripts/check_schema.py
python scripts/check_project.py
cargo fmt --manifest-path fuzz/Cargo.toml --check
cargo test --locked --offline --manifest-path fuzz/Cargo.toml --lib
cargo clippy --locked --offline --manifest-path fuzz/Cargo.toml --all-targets -- -D warnings
python scripts/check_packages.py --offline
python scripts/native_smoke.py --output target/windows-summary-native-clean.json
```

2026-10-25 Windows x64 本地 fmt、严格 Clippy、262 项 Rust 测试含 doctest、无默认 feature、文档（拒绝 warning）、FFI/CLI 构建及 Linux x64/macOS ARM64 交叉检查通过；两个交叉目标的全 target 严格 Clippy 也通过。Python Ruff/mypy 48 文件、116 项测试与 Schema 守卫通过。新增十项 Rust 测试覆盖类型/长度/Unicode/占位词、字段级错误隔离、错误缓冲不消费、取消/截止检查、成功/缺失缓存与重建，以及合成授权模式仍只查询六个白名单值。桌面集成断言六项能力为 Win32/Partial。

独立 C SDK 探针用公开 RegGetValueW 和 4096-byte WCHAR 缓冲，仅查询同一六值，输出字段级原始状态/类型/长度和摘要。另查本探针 token 是否提升，不读取账户、SID 或用户信息。当前本机六项均 Available，SDK `token_elevated=false`：证明本次未提升进程可读，不证明所有普通账户、ACL、OEM 或沙盒配置可读。持久 Rust 公共门面与 SDK 初次和重建逐字段对照；三次动态刷新检查完整静态模型/时间戳不变，设备序列号始终 PrivacyRedacted。SDK 与 Rust 顺序读取不是原子快照，未修改真实 BIOS 注册表模拟错误。

四项新增 Python 测试拒绝假成功状态、布尔伪整数、错误长度/类型/来源/能力/值、意外标识字段及失败后保留旧成功；失败报告只输出固定错误分类。fuzz 复用 dmi_text，新增两份 UTF-16 合成种子；Windows 本地 4 项 harness 单测、fmt 和全部目标严格 Clippy 通过，目标总数仍为 12。本地没有实际 libFuzzer campaign；随后本轮 Linux CI 已执行扩展解析路径，结果见下节，不能用上一轮 CI 替代。

实现提交 `82c6659898743fe2abcc6933d3eaaca97243220c` 的干净工作区完成：

- [本机索引](evidence/windows-hardware-summary-local-82c6659.json)：命令、来源、日志与报告哈希及未验证边界。
- [八包报告](evidence/windows-hardware-summary-packages-82c6659.json)：8 个实际归档、原生 Cargo 验证、解包后独立 workspace 262 项测试与 CLI 安装；第三方锁不变，未发布相邻 crate 使用本地 patch。
- [原生报告](evidence/windows-hardware-summary-native-82c6659.json)：CLI/C/Python 等五组、16 个进程通过，含 100 次 Python collect/free。
- [SDK 对照报告](evidence/windows-hardware-summary-sdk-82c6659.json)：初次与重建共两帧、12 次固定值查询；六项均 Available，探针 `token_elevated=false`；三次刷新静态模型和字段时间戳不变。

完整门禁在实现提交前运行；运行和测试源码随后未改变。实现提交后重建探针并运行八包、SDK 与原生验收，三个报告均绑定同一干净提交。之后归档只更新文档与证据。RegGetValueW 自身可能为缺少终止符的存储字符串补 NUL；本库严格校验的是 API 返回表示，不声称证明注册表原始存储编码完整。

尚未验证：真实 ACL 拒绝/BIOS 键缺失、UWP/沙盒、更多 OEM/虚拟机、运行时并发修改注册表和固件更新场景、32 位与 Windows ARM64 原生、长期泄漏/峰值内存/专用基准。实体 Linux/macOS 按维护者安排延期。取消检查无法强制中断阻塞的 OS 调用；core 既有 worker 限额/等待边界不变。

只增加 Windows target 的既有 windows-sys Registry feature，无第三方包/版本、两个锁文件、消费类型/签名、JSON 形状或许可证变化。复用默认关闭的 fuzzing feature，MIT、ABI 1、Schema 1 不变；尚未发布 registry/release。

## 三平台 CI 验收（2026-10-25）

[运行 40145306966](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40145306966)，源码 `01d222f242d3f4254ed87ecbfe937e929389cb33`，一次 workflow_dispatch 的八个任务全部成功，无需本轮运行时代码修复。[验收索引](evidence/windows-hardware-summary-ci-40145306966.json)保留十六份报告的来源与 SHA-256，以及扩展 dmi_text 的原始步骤日志。

| 平台 | workspace / 八包独立测试（含 doctest） | Python 单测 | 原生 CLI/C/Python |
|---|---|---|---|
| Windows x64 | 262 / 262 | 116 | 五组、16 个进程通过 |
| Linux x64 | 254 / 254 | 116 | 五组、16 个进程通过 |
| macOS ARM64 | 259 / 259 | 116 | 五组、16 个进程通过 |

各平台 fmt、严格 Clippy、无默认 feature、doc（拒绝 warning）、Ruff/mypy（48 文件）、Schema/项目守卫、八包原生 Cargo 验证、解包后独立 workspace 测试与 CLI 安装均通过。各平台 Python 另执行 100 次 collect/free。相邻未发布 crate 由本地 patch 提供，不是 registry 下载或 release 分发验收。

Windows [摘要 SDK 报告](evidence/windows-hardware-summary-sdk-40145306966.json)初次和重建的六项均为 Available、Win32，与独立 SDK 逐字段匹配；SDK 两帧共 12 次固定值查询，4096-byte 缓冲和类型/长度检查通过。三次动态刷新中的完整静态快照和字段采集时间不变，序列号仍 PrivacyRedacted。这里是虚拟机的 Windows/OEM 报告，不推断底层物理主板或固件。

CI SDK `token_elevated=true`、`ordinary_user_read_verified=false`。本机笔记本的未提升 token 六值成功是另一份独立证据；不能把 CI 的提升进程读取当作普通账户或任意 ACL 的成功。未修改真实注册表做拒绝/损坏/并发变动实验，接口仍可能自行补终止 NUL，多值顺序读取不具备原子性。

全部 12 个 libFuzzer 目标各运行 **61 秒**。扩展的 `dmi_text` 为 **6,509,574 次**，正常无崩溃结束；它在 Linux 执行生产 UTF-16 解析器和既有解析分支，不执行 Windows 注册表调用。4 项 harness 守卫、Miri 8 项、Linux Rust FFI ASan 10 项与 cargo-deny 均通过。短 fuzz 不代表完整覆盖或长期无漏洞，Linux 的内存安全检查也不是 Windows Registry API 的原生故障实验。

Windows CPU/多组 helper、内存 64 MiB 实验和 uptime，以及 macOS CPU/内存/uptime SDK 回归均通过，报告绑定本轮干净源码。Windows 实际仍只有一个处理器组，真实跨组仍未验证。Linux 容器八份报告完成 CPU 15、内存/uptime 26、电池 30、hwmon 47、存储 21、GPU 20、显示器 26 项及既有权限/DMI 检查；完全空 `/proc` 被 OCI 拒绝，进程未运行，保留 not_run。

Linux/macOS 的整库回归基准见[性能记录](benchmarks.md)，未测 Windows 六值查询的专用延迟/峰值内存。本轮归档只修改文档与证据，不再改变 feature、锁、公共 API、MIT 或 ABI 1/Schema 1；更多 OEM/ACL、实体设备、长期 fuzz 与正式发行仍待后续验收。
