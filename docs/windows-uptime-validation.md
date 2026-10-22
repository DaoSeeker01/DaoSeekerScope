# Windows uptime 验证

本轮契约见 [ADR 0027](adr/0027-windows-uptime.md)。现有 sysinfo Windows 路径已经逐次读取相同 API；迁移目的为显式平台来源和可复现刷新验收，不声称修复缓存错误。

实现：现有 WindowsBackend 动态读取 GetTickCount64，整数毫秒向下取秒，来源 Win32、能力 Partial。静态不读取该计时器；不缓存动态值。取消检查包围调用，合法零保留，无 GetLastError 或虚构 API 失败。单独 SysinfoBackend 的 Windows 用户需补 WindowsBackend 或使用门面。

可复现命令：

```powershell
pwsh -NoProfile -File scripts/check.ps1 -Cross
cargo build --locked -p daoseeker-scope --example dynamic_probe
pwsh -NoProfile -File scripts/build_c_example.ps1 -UptimeProbe
python scripts/windows_uptime_smoke.py
python -m unittest discover -s tests -p "test_*.py"
python scripts/check_schema.py
python scripts/check_project.py
python scripts/check_packages.py --offline
python scripts/native_smoke.py --output target/windows-uptime-native-clean.json
cargo fmt --manifest-path fuzz/Cargo.toml --check
cargo test --locked --manifest-path fuzz/Cargo.toml --lib
```

2026-10-22 Windows x64 笔记本本机通过：完整 Rust 门禁（fmt、严格 Clippy、232 项测试含 doctest、无默认 feature、doc、FFI/CLI 构建）、Linux x64/macOS ARM64 交叉检查及 macOS 全 target 严格 Clippy；Python ruff/mypy 42 文件、106 项测试、Schema 和项目文档守卫；原生 C ABI 及独立 uptime SDK 探针。fuzz 入口 fmt 和两个共享守卫单元测试通过，未运行 campaign。干净源码的八包/原生报告将在实现提交后另行归档；三平台 CI 尚未执行。C 探针为公开 Windows SDK 编译，两进程用有界命令/1 MiB 行上限/5 秒读与退出等待，报告仅保留 uptime 元数据、来源版本和制品哈希。初次 collect、三次间隔 1.1 秒 refresh、重建 collect 均检查 C SDK 前后毫秒夹取；刷新时完整静态模型保持不变，间隔跨秒后计数增长。短间隔相同秒数是合法结果。失败先覆盖旧成功报告并最终保留 failed，不输出原始系统错误或设备标识。

纯逻辑测试覆盖零、999/1000 ms 取整、超过 32 位、u64 最大值、重复/重新开始的计数域、每次调用次数与取消前后检查。Python 守卫拒绝 bool/浮点伪整数、越界、错误来源/状态/原因/时间、逆序 SDK 区间和错误调用计数。模拟检查失败不冒充真实 OS API 故障。

未实验验证：系统睡眠/休眠、重启/快速启动、checked kernel 偏移和长期运行。微软说明计时包含睡眠/休眠且受系统粒度影响；不能据此声称这些场景已由本机测试。Windows 之外的交叉编译不能替代原生运行；macOS uptime 路线本轮不变。未执行本轮 benchmark 或长期 fuzz campaign；已有仓库结果属于各自来源版本。

ABI 1、Schema 1、MIT、锁文件、依赖版本与 feature 不变；本轮无新增发行或 registry 安装声明。
