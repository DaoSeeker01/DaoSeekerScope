# macOS uptime 验证

契约见 [ADR 0028](adr/0028-macos-uptime.md)。本轮只在 Windows 开发；macOS 原生 SDK 编译、符号链接和实际读取尚未执行，不能把纯逻辑或交叉编译当作成功采样。

现有 MacosBackend 每次动态采集 boot-before → time → boot-after，来源 Sysctl/Partial；sysctl 失败不回退 epoch 0，长度/数据不合格不发布值，time 的 -1 哨兵映射 Unknown 而非残留 errno。两次启动时间不同为暂不可用，失败后无旧值，可在后续直接恢复。保留原来的整秒差口径，不承诺单调/精确 elapsed 或仅清醒时长。静态不查询 uptime，动态保持静态缓存；现有单元构造不变，单独 SysinfoBackend 用户须补 MacosBackend 或用门面。

可复现本地门禁：

```powershell
pwsh -NoProfile -File scripts/check.ps1 -Cross
cargo clippy --locked --workspace --all-targets --all-features --target aarch64-apple-darwin -- -D warnings
python -m unittest discover -s tests -p "test_*.py"
python scripts/check_schema.py
python scripts/check_project.py
cargo fmt --manifest-path fuzz/Cargo.toml --check
cargo test --locked --manifest-path fuzz/Cargo.toml --lib
pwsh -NoProfile -File scripts/build_c_example.ps1
python scripts/check_packages.py --offline
python scripts/native_smoke.py --output target/macos-uptime-native-clean.json
```

2026-10-22 Windows x64 本机门禁通过：fmt、严格 Clippy、240 项 Rust 测试含 doctest、无默认 feature、doc、FFI/CLI 构建、Linux x64/macOS ARM64 交叉检查及 macOS 全 target 严格 Clippy；Ruff 0.14.13 format/check、mypy 1.19.1（44 文件）、109 项 Python 测试、jsonschema 4.25.1 Schema 与项目/链接检查通过。原生 Windows C ABI 收集/释放/清零/重复空释放/旧副本拒绝通过；fuzz 入口 fmt 和两个共享守卫单元测试通过。实现提交后的干净源码原生和八包验收将另行归档。macOS ARM64/Intel 原生、独立 C SDK、持续刷新及三平台 CI 尚未执行。实体 Mac 按维护者设备安排延期。

macOS 原生复现入口（尚未执行）：

```sh
mkdir -p target
cc -Wall -Wextra -Werror -std=c11 docs/research/macos_uptime_probe.c -o target/macos-uptime-probe
target/macos-uptime-probe < /dev/null
cargo test --locked -p daoseeker-scope-macos public_boot_time_and_time_match_native_sdk_contract -- --nocapture
cargo build --locked -p daoseeker-scope --example dynamic_probe
python scripts/macos_uptime_smoke.py
```

探针以两进程检查 collect、三次间隔 1.1 秒 refresh 和 rebuild；SDK 在 Rust 每次调用前后采样，区间比较以整数秒为单位，不要求两个进程相等。静态模型保持缓存、刷新采集时间前进；受控不调时的测试检查跨秒增长，不能据此宣称字段在调时或睡眠等场景下单调。命令有界、行上限 1 MiB、读/退出等待 5 秒，失败先覆盖旧成功报告；只保留 uptime、类型大小、次数、来源/制品哈希，不输出原始 boot epoch 或系统错误。C SDK 与 Rust 固定 LP64 timeval/time_t 大小和字段偏移，原生实际读取尚待 CI。

八项可注入测试已通过，覆盖长度/符号/微秒验证、合法零与 i64 大数精确整数差、Darwin errno 和时间哨兵分离、每个失败位置短路、启动时间秒/微秒变化、成功→失败→恢复、每个调用前后的取消/超时，以及 Hardware 静态缓存/字段失败隔离。它们不是实际设备权限或系统时钟故障实验。

无新解析器或输入格式，本轮不增加 fuzz target。未执行本轮真实 fuzz campaign、Miri、ASan 或 benchmark；已有证据属于各自版本。后续 native CI 将运行已有回归；没有睡眠/休眠/重启/调时/沙盒/真实 API 故障、长期泄漏或强制取消 OS 调用证明。两次启动时间一致不排除 ABA 或读间时钟变化。

项目 MIT、ABI 1、Schema 1、公共类型/签名、依赖、feature 与两个锁文件不变；未发布 registry 或 release。
