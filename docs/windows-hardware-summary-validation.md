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

四项新增 Python 测试拒绝假成功状态、布尔伪整数、错误长度/类型/来源/能力/值、意外标识字段及失败后保留旧成功；失败报告只输出固定错误分类。fuzz 复用 dmi_text，新增两份 UTF-16 合成种子；Windows 本地 4 项 harness 单测、fmt 和全部目标严格 Clippy 通过，目标总数仍为 12。本轮解析器尚未运行实际 libFuzzer campaign，上一轮的 CI 不能证明新路径。

尚未验证：本轮三平台原生 CI、实际新解析路径 fuzz、真实 ACL 拒绝/BIOS 键缺失、UWP/沙盒、不同 OEM/虚拟机、运行时并发修改注册表和固件更新场景、32 位与 Windows ARM64 原生、长期泄漏/峰值内存/专用基准。实体 Linux/macOS 按维护者安排延期。取消检查无法强制中断阻塞的 OS 调用；core 既有 worker 限额/等待边界不变。

只增加 Windows target 的既有 windows-sys Registry feature，无第三方包/版本、两个锁文件、消费类型/签名、JSON 形状或许可证变化。复用默认关闭的 fuzzing feature，MIT、ABI 1、Schema 1 不变；尚未发布 registry/release。
