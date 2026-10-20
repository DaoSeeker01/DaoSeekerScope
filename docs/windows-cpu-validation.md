# Windows CPU 刷新验证

本轮实现：直接检查公开 GetSystemTimes 的成功状态，每次刷新重新读计数；失败清除基线，恢复需要新的 300 ms 有效采样对。仅支持单活动处理器组；多组返回 Unsupported，不将组内用量当成整机用量。决策与迁移见 [ADR 0024](adr/0024-windows-cpu.md)。

2026-10-20 开发验证：本机 Windows x64，1 组 / 12 个逻辑处理器，独立公开 C SDK 探针与持久 Rust 进程完成初始预热、三次有效刷新、重建后重新预热。静态 CPU 信息保持缓存，动态来源 Win32、时间递增、范围 0..100；两进程采样区间不同，不要求数值相同，不制造负载或注入系统 API。开发报告位于忽略的 target/windows-cpu-local.json，明确 git_dirty=true；可归档的干净提交结果另列于后续验收章节。

测试覆盖实际零/满载、大整数求和、快速轮询、300 ms 边界、计数回退/无增长/异常 idle、处理器数量变化、多组拒绝、读取失败/恢复、取消前零次调用和调用后超时、能力限制/恢复、sysinfo 不再回退。SDK FILETIME 布局与高位无符号转换在 Windows 单独测试。注入错误是可复现单元输入，不代表真机触发了权限拒绝。

本机最终 Rust 门禁通过：fmt、all-target/all-feature Clippy（拒绝 warning）、208 项测试、core/门面 no-default-features、doc（拒绝 warning）、CLI/FFI 构建、Linux x64/macOS arm64 交叉检查。Python Ruff/mypy 36 个文件及 94 项测试、Schema 检查通过。fuzz 格式与两个 harness 单元测试通过；本轮未在本机运行 libFuzzer campaign。C ABI collect/free、buffer 归零、空释放和旧副本拒绝通过，通用原生 CLI/C/Python 回归通过；干净提交的打包/采样归档另列。

复现命令（Windows，先准备 MSVC/Windows SDK）：

```powershell
pwsh -NoProfile -File scripts/check.ps1 -Cross
cargo build --locked -p daoseeker-scope --example dynamic_probe
pwsh -NoProfile -File scripts/build_c_example.ps1 -CpuProbe
python scripts/windows_cpu_smoke.py
python scripts/native_smoke.py
python scripts/check_packages.py --offline
```

Python 开发检查使用 jsonschema 4.25.1、Ruff 0.14.13、mypy 1.19.1；运行 `ruff format --check scripts tests examples/collect.py`、`ruff check`、`mypy --no-incremental --ignore-missing-imports`、`python -m unittest discover -s tests -p "test_*.py"`、`scripts/check_schema.py` 与 `scripts/check_project.py`。CPU 报告额外有三项负面测试，拒绝伪造成功、错误 SDK 覆盖与计数，失败/中断先覆盖旧 passed 并保留已完成观测。

CI 已增加 SDK 编译、Windows 持久刷新步骤与报告保留入口；本轮尚未运行远程 CI。Linux/macOS 交叉编译不能替代两平台原生测试。未执行真实 API 失败、多处理器组、热插拔、长时间采样、峰值内存或专门 CPU 采样延迟 benchmark。文档中的百分比范围不是性能或精度保证；无法强制终止阻塞的内核调用。默认无标识采集，ABI 1、Schema 1、MIT 不变；只新增 windows-sys 的 Threading 绑定 feature，不增加依赖包或锁文件变化。
