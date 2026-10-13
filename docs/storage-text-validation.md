# 存储 CLI 文本输出验证

2026-10-13，`dscope disk` 从计数摘要扩展为逐条名称状态、容量和来源。保留现有命令/退出码/隐私警告；JSON 仍为完整 Schema 1 快照。容量按 1024 换算 IEC 单位、两位小数舍入，并同时保留精确 u64 字节数；不使用浮点整数转换。近单位边界可能显示 1024.00 KiB，精确字节数优先。真实零为 0 B，缺失/受限字段保持各自状态与原因，不补零；空集合只说明当前可见列表没有条目。条目编号是当前顺序，OS 对象包含虚拟层，容量不可相加为物理总量。

发现主 crate 漏重导出 core 已有 StorageInfo，补齐 `daoseeker_scope::StorageInfo`，属于兼容 API 新增；没有重命名或修改模型字段，Schema 1、C ABI 1 和 MIT 不变，无依赖/feature/锁文件变更。

新增三个渲染单元测试与一个真实 CLI/JSON 集成测试，涵盖零、1023/1024、舍入、u64::MAX、全部缺失状态与空列表、权限/坏数据隔离及受允许的名称。集成测试不跨两次 CLI 采集比较容量/成员，避免热插拔导致不成立的断言。原生验收增加 storage_text gate，独立检查格式、默认名称脱敏、精确字节数、来源和至少一个正容量；只存统计/字节值及输出哈希，不存原始文本或名称。三个 Python 负向测试拒绝名称泄漏、错误来源/编号、溢出/负值、坏格式、零/空/缺失冒充真实读取，以及超限输出。

本机执行 `scripts/check.ps1 -Cross` 的 fmt/Clippy、131 项 Rust 测试（含 1 doctest）、no-default-features、doc 拒绝警告、CLI/FFI 构建及两个 cross-check 通过；Linux/macOS all-target/all-feature Clippy、fuzz fmt/Clippy 与两项 harness 回归通过。Python Ruff/mypy --no-incremental（21 文件）、44 项 unittest、Schema/generated/golden 和项目检查通过。`scripts/build_c_example.ps1` 与 `scripts/native_smoke.py` 验证实际 CLI 文本/C/Python；本机实读 1000204886016 bytes，显示 931.51 GiB，名称 Restricted/PrivacyRedacted。

2026-10-14 核对并归档干净源码提交 `c65b0a3bd1b78f4242fd58d429010c0b17c2bc6a` 的 [CI 38329245146](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38329245146)（运行于 10 月 13 日），8 个任务全部成功。三平台 fmt/Clippy、测试/doc、Schema、CLI/C/Python 原生验收及独立打包通过；Rust 测试含 doctest 分别为 Windows 131、Linux 121、macOS 121，Python 每平台 44 项。Miri 8 项、AddressSanitizer 10 项及 fuzz harness 两项回归通过。11 个 fuzz 目标各完成至少 60 秒，存储解析器完成 29,637,380 次/61 秒；这是短时回归证据。非 root 容器的 21 项存储异常场景使用模拟 sysfs；完整挂载空 `/proc` 的探针被容器运行时拒绝挂载，进程没有启动，仍为 `not_run / runtime_mount_error`，不能据此声称该探针通过。

原生 CLI 与 C ABI 均有正容量读取，文本 gate 独立通过：Windows 2 个条目（Win32），Linux 9 个条目（Sysfs，8 个内核返回零、1 个正容量），macOS ARM64 7 个条目（Iokit）。名称全部默认脱敏。CI 为 runner/虚拟环境证据，不替代实体 Mac、sandbox 或热插拔验收；两个独立采集之间不要求设备顺序、数量和容量一致。

本机及三平台均独立生成 8 个可验证 crate 归档，使用原生 Cargo 验证和隔离消费者测试/CLI 安装，第三方锁定版本不变；未发布到 registry。[证据索引](evidence/storage-text-ci-38329245146.json)绑定源码提交、10 份报告及日志哈希。归档报告以 LF 保存，索引分别记录归档与原始报告的 SHA-256；提交前后核对 Git blob 哈希、7 个存储 fuzz 种子及独立 macOS SDK 探针源码。证据归档提交不代表重新运行硬件验收。

既有 macOS 整体采集 benchmark 本次为首次 401 µs、100 次动态刷新 p50/p95/max 21/24/40 µs；模拟 100 传感器和 1024 网络接口为 549 µs、JSON 373541 bytes。它反映共享 CI runner 中的整体采集，不是磁盘 IO、文本格式化/CLI 启动延迟或峰值内存测量。

硬件采集仍遵守原有静态缓存与调用方超时边界，未新增设备扫描。文本供人阅读，自动化使用 `--json`。本轮未新增原生热插拔、长期 fuzz 或实体 Mac 测试；既有硬件及 sandbox 限制继续见 [macOS 存储](macos-storage-validation.md)、[Windows 存储](windows-storage-validation.md)与 [Linux 存储](storage-validation.md)。后续独立任务是核对其余 CLI 文本命令的状态/来源表达一致性。
