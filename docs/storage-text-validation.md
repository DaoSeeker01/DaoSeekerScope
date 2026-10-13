# 存储 CLI 文本输出验证

2026-10-13，`dscope disk` 从计数摘要扩展为逐条名称状态、容量和来源。保留现有命令/退出码/隐私警告；JSON 仍为完整 Schema 1 快照。容量按 1024 换算 IEC 单位、两位小数舍入，并同时保留精确 u64 字节数；不使用浮点整数转换。近单位边界可能显示 1024.00 KiB，精确字节数优先。真实零为 0 B，缺失/受限字段保持各自状态与原因，不补零；空集合只说明当前可见列表没有条目。条目编号是当前顺序，OS 对象包含虚拟层，容量不可相加为物理总量。

发现主 crate 漏重导出 core 已有 StorageInfo，补齐 `daoseeker_scope::StorageInfo`，属于兼容 API 新增；没有重命名或修改模型字段，Schema 1、C ABI 1 和 MIT 不变，无依赖/feature/锁文件变更。

新增三个渲染单元测试与一个真实 CLI/JSON 集成测试，涵盖零、1023/1024、舍入、u64::MAX、全部缺失状态与空列表、权限/坏数据隔离及受允许的名称。集成测试不跨两次 CLI 采集比较容量/成员，避免热插拔导致不成立的断言。原生验收增加 storage_text gate，独立检查格式、默认名称脱敏、精确字节数、来源和至少一个正容量；只存统计/字节值及输出哈希，不存原始文本或名称。三个 Python 负向测试拒绝名称泄漏、错误来源/编号、溢出/负值、坏格式、零/空/缺失冒充真实读取，以及超限输出。

本机执行 `scripts/check.ps1 -Cross` 的 fmt/Clippy、131 项 Rust 测试（含 1 doctest）、no-default-features、doc 拒绝警告、CLI/FFI 构建及两个 cross-check 通过；Linux/macOS all-target/all-feature Clippy、fuzz fmt/Clippy 与两项 harness 回归通过。Python Ruff/mypy --no-incremental（21 文件）、44 项 unittest、Schema/generated/golden 和项目检查通过。`scripts/build_c_example.ps1` 与 `scripts/native_smoke.py` 验证实际 CLI 文本/C/Python；本机实读 1000204886016 bytes，显示 931.51 GiB，名称 Restricted/PrivacyRedacted。

干净提交八包与三平台 CI 尚待本轮执行；以上是本机与交叉检查结果，不冒充原生 Linux/macOS 验收。硬件采集仍遵守原有静态缓存与调用方超时边界，未新增设备扫描。文本供人阅读，自动化使用 `--json`。本轮未新增硬件性能 benchmark、原生热插拔或长期 fuzz；既有硬件及 sandbox 限制继续见 [macOS 存储](macos-storage-validation.md)、[Windows 存储](windows-storage-validation.md)与 [Linux 存储](storage-validation.md)。
