# Windows 网络验证

本轮实现契约见 [ADR 0011](adr/0011-windows-network-counters.md)。原生运行与模拟测试分列；CI 结果待本轮源码运行后记录。

实现复用 NetworkInfo，Windows 能力 Partial/Win32。固定上限枚举和逐接口 64 位计数不覆盖全部逻辑隧道接口；系统缓冲包含未被读取/保存的标识，不能承诺标识从未进入进程内存。macOS 网络仍未实现。公共 API 形状、Schema 1、C ABI 1 与 MIT 许可证不变；仅增加 Windows target 的 windows-sys IpHelper/Ndis feature。

本机未提升权限的 Windows 进程通过 CLI/C 实读 43 条 Win32 接口计数，名称全部 Restricted/PrivacyRedacted；C 内存释放/清零/陈旧复制及 Python 100 次 collect/free 通过。报告在提交前生成，标记 git_dirty=true；干净提交的原生报告和跨平台 CI 待后续归档。条目数不是物理网卡数量。

已执行 `pwsh -NoProfile -File scripts/check.ps1 -Cross`：Windows fmt、Clippy、97 项 Rust 测试（含 1 doctest）、doc（拒绝警告）、no-default-features、CLI/FFI build、Linux/macOS cross-check 通过。另行执行 Linux x64/macOS arm64 全 target Clippy 拒绝警告。5 项新的模拟 API 测试验证资源/错误/刷新/授权转换，不是内核权限或真实热插拔证据。Python Ruff 格式/检查、mypy --no-incremental（18 文件）、36 项 unittest、Schema 无漂移与项目一致性检查通过。跨平台原生 CI、独立包验收尚待执行，不能按文档推定通过。

长期 Windows 原生模糊测试、泄漏检测、真实权限拒绝/接口热插拔、故障驱动阻塞及新 benchmark 本轮尚未执行。调用等待有界不等于能终止阻塞的 OS API。
