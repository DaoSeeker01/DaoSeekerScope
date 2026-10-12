# Linux 存储容量验证

2026-10-12 源码 `2b19e8d1cd50c9277753941a16807e1143a97c35` 的 [CI 38188243470](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38188243470) **全部 8 个任务成功**。[汇总](evidence/storage-ci-38188243470.json)绑定源提交、报告及日志哈希、实际测试数。设计见 [ADR 0013](adr/0013-storage-capacity.md)；后续归档提交不是新一次源码 CI。

Linux x64 CI 的 CLI/C 各实读 9 个 Sysfs 整块对象；一个有正容量，其余保留内核报告的零。名称全部 Restricted/PrivacyRedacted，容量带来源与采集时间。它们包含虚拟块设备，不是 9 个物理磁盘，也不计算可相加的总容量；这不是文件系统空闲空间或硬件标称容量核验。

非 root 只读容器（65534:65534、cap-drop ALL、网络关闭、no-new-privileges、256 MiB、1 CPU、32 PID）内 21 项合成 sysfs 观察通过：空集合、512 字节单位、合法零、负值/小数/混合单位/溢出/超长/非法 UTF-8、缺失与真实内核权限拒绝、FIFO 拒绝、单字段隔离、目录拒绝/恢复/缺失、129 条超限及空恢复。真实驱动坏数据、设备插拔与物理容量未在此测试。首次 capacity 4096 bytes 后改为 8192：同一 Hardware 的动态刷新仍保留容量及原时间，新建 Hardware 才读到 8192；权限恢复也使用新对象，不能称为动态 storage 恢复。

新增 5 项 Linux 模块测试及 1 项 core 自定义后端隐私测试。本机执行 `pwsh -NoProfile -File scripts/check.ps1 -Cross`：fmt/Clippy、111 项 Rust 测试（含 1 doctest）、doc 拒绝警告、no-default-features、CLI/FFI build 和两个 cross-check 通过；Linux x64/macOS arm64 all-target/all-feature Clippy 通过。另执行 fuzz fmt/Clippy 与 `cargo test --locked --manifest-path fuzz/Cargo.toml --lib` 两项 harness 回归；Windows 没有执行实际 libFuzzer。Python Ruff、mypy --no-incremental（20 文件）、39 项 unittest、Schema 兼容和项目检查通过。

本机干净提交八个实际 crate 归档、MIT/头文件检查、原生 Cargo 验证、111 项独立消费者测试与 CLI 安装通过，未上传 registry。公开模型/签名、Schema 1、C ABI 1 和 MIT 许可证不变，无新依赖、版本或默认 feature；现有 Linux fuzzing feature 增加容量转换入口。默认 storage.name 对自定义 backend 也强制脱敏，是隐私行为收紧，迁移见[使用指南](usage.md)。Windows/macOS 存储仍 Unsupported。

本次 Linux 基准首次 collect 687 µs，100 次动态刷新 p50/p95/max 114/139/151 µs，CPU 二次样本 Available；合成 100 传感器/1024 网络条目另为 278 µs，JSON 373541 bytes。完整 collector 在共享 runner 的单进程样本；存储只在首次读取，不代表每次扫描、磁盘吞吐、物理设备延迟或峰值内存，详见[性能记录](benchmarks.md)。

没有新增 unsafe；sysfs 文件类型预检不能防止恶意 TOCTOU 替换，core 超时只限制调用方等待，不能终止阻塞的驱动。长期 fuzz、原生泄漏/峰值分配、真实存储热插拔和坏驱动超时尚未执行。首次 Git 推送遇到 TLS 握手失败，重试成功；不是 CI/后端故障。

| 本次源提交门禁 | 实际结果 |
|---|---|
| Windows x64 / Linux x64 / macOS arm64 | 源码各 111 / 109 / 108 项 Rust 测试，含 1 doctest；fmt/Clippy/doc 拒绝警告、no-default-features 通过 |
| 三平台八包 / 独立安装 | MIT/头文件、原生 Cargo 验证、独立消费者各 111 / 109 / 108 项测试及 CLI 安装；第三方锁文件未变 |
| 原生 CLI/C/Python | CPU/内存/OS 与现有网络回归通过；Linux storage 各 9 条，名称脱敏；Windows/macOS storage Unsupported；Python 100 次 collect/free 通过 |
| Python / Schema | 三平台 Ruff/mypy --no-incremental（20 文件）、39 项 unittest、Schema 无漂移与项目检查通过 |
| 非 root 存储容器 | [21 项合成观察](evidence/storage-container-linux-38188243470.json)通过；缓存与新建 Hardware 清楚区分 |
| 十一个 fuzz 目标 | 每个实际运行至少 60 秒并到达 DONE；storage_capacity 为 61 秒、37,258,518 次，无崩溃正常结束；两项 harness 回归通过 |
| Miri / FFI ASan / 供应链 | 全部通过；Linux 内存门禁不验证 Windows/macOS 原生 unsafe 边界 |
| 已有 Linux 受限容器 | 全部回归通过；完整 /proc 替换仍为 runtime_mount_error / not_run，不当作后端执行成功 |

[Linux 原生报告](evidence/storage-native-linux-38188243470.json)保留零容量和缺失元数据的真实状态；[本机包报告](evidence/storage-package-local-windows-38188243470.json)绑定干净源提交。报告归档用 LF，汇总 sha256 对应实际 Git 报告字节；original_report_sha256 对应原始下载/生成字节，日志哈希对应原始捕获日志。计数/RSS不表示覆盖百分比、采集库内存或长期 campaign。

下一阶段验证 Windows 整盘容量的普通用户权限、枚举与查询边界；macOS 待独立公开 API 与所有权验证。本轮不扩大 GPU、移动/Web/MCU 范围。
