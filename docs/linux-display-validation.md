# Linux 显示连接视图验证

2026-10-17 实现 [ADR 0020](adr/0020-linux-display.md)，源码 `cac01919f8df9747c78a76ae97645b3a67df8a9d`。只返回 DRM class 中 status=connected 的连接器，不代表物理显示器总数、正在扫描输出或桌面布局。当前像素宽高为 Unsupported/NotSupported；不把 modes、EDID 时序或虚拟帧缓冲尺寸当作当前分辨率。

## 本地验证

- Windows x64 执行 `pwsh -NoProfile -File scripts/check.ps1 -Cross`：fmt、workspace/all-target/all-feature Clippy、176 项 Rust 测试（含 doctest）、core/门面 no-default-features、doc 拒绝警告、CLI/FFI 构建以及 Linux x64/macOS ARM64 cross-check 全部通过。完整检查之后只增加了一段 1025 个断开候选条目的限额断言，随后重跑 fmt、Linux all-target/all-feature Clippy、57 项并行单测及 6 项集成测试；最终源码另由隔离打包测试覆盖。
- 8 项新增 Rust 测试覆盖 EDID 产品名投影、校验/版本/冲突名称、默认不读 EDID、授权条件、状态失败不返回成功前缀、空集合、扫描/候选/输出限额、取消、两次新鲜状态读取与静态缓存。修复既有内存测试 fixture 使用毫秒命名导致的并发碰撞，增加原子序号，没有放宽门禁。
- 按 CI 的固定版本执行 Ruff format/check、mypy --no-incremental --ignore-missing-imports（30 文件）、80 项 Python unittest、Schema generated/golden/不变量和项目链接检查，全部通过。新增 5 项 Python 负向守卫测试，报告只保留名称可用性，不保存名称或原始 EDID。
- `cargo fmt --manifest-path fuzz/Cargo.toml --check` 与 `cargo test --locked --offline --manifest-path fuzz/Cargo.toml --lib`（2 项）通过。这是本地 harness 检查，不是实际 libFuzzer campaign；既有 dmi_text 目标扩展 EDID 纯解析，增加两个合成种子，没有新建目标。
- 重建 C 示例，通过 collect/free、释放后清零、空释放和陈旧 buffer 拒绝；干净源码的本机 CLI/C/Python 五组检查与 15 个进程通过，含 Python 默认 100 次 collect/free。执行平台是 Windows，不能作为 Linux 显示器或权限验证。
- `python scripts/check_packages.py --offline`：八个真实归档、原生 Cargo 验证、176 项隔离消费者测试及 CLI 安装通过，MIT/头文件和第三方锁定内容未变；不是 registry 发布验收。

[本地汇总](evidence/linux-display-local-cac0191.json)绑定源码、日志哈希及两份报告：[Windows 原生](evidence/linux-display-native-windows-local-cac0191.json)、[八包](evidence/linux-display-packages-windows-local-cac0191.json)。报告均记录干净源码，归档统一 LF 并保留原始/归档字节 SHA-256。

## 三平台 CI（2026-10-17）

用户授权推送与后续验收归档后，工作流运行于 `a348614c3256f11b0af18678323bb578d37673fa`，与实现 `cac0191` 之间只有本地验收文档/报告。[CI 38983994614](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38983994614)和[汇总](evidence/linux-display-ci-38983994614.json)绑定同一源码，最终 8/8 个任务全部成功。

托管 Linux runner 的 CLI 与 C ABI 各读取一条 connected 连接器，名称均 Restricted/PrivacyRedacted、Source Sysfs；宽高由原生守卫验证为 Unsupported/NotSupported、Source Drm。不是实体显示器计数或实际扫描输出证明，没有读取真实 EDID 名称。与合成名称阳性场景分开记录。

Linux 非 root 容器的 26 个场景全部 passed：默认名称始终脱敏，坏 EDID、权限拒绝和 FIFO 不影响默认读取；显式授权后可解析合成产品名称，拒绝校验错误、FIFO 和属性链接。名称失败保留连接条目、宽高始终 Unsupported；状态未知、损坏或拒绝时不会返回成功前缀。静态成功与失败缓存、重新构造恢复、没有名称描述符的基础块及 129 条输出限额均通过。正常内存读值与 Schema 同时检查，合成数字序列号/0xff 描述符没有被导出。合成名称阳性证据不等于实体 Linux 显示器读取。

容器实际配置为 UID/GID 65534:65534、只读 rootfs/fixture、禁网、drop ALL capabilities、no-new-privileges、256 MiB 内存、1 CPU、32 PID、64 FD。[原始容器报告](evidence/linux-display-container-38983994614.json)保留配置、镜像、进程退出码、状态与名称可用性，不保存名称或原始 EDID。

| 门禁 | 实际结果 |
|---|---|
| Windows x64 / Linux x64 / macOS ARM64 | 源码与隔离消费者各 176 / 172 / 172 项 Rust 测试（含 doctest），fmt/Clippy/doc 拒绝警告与 no-default-features 通过 |
| 三平台八包与安装 | 真实归档、原生 Cargo 验证、MIT/头文件、隔离消费者与 CLI 安装通过，第三方锁定内容未变 |
| 三平台 CLI/C/Python | 各五组检查、15 个进程通过，含 Python 默认 100 次 collect/free |
| Python / Schema | 各平台 80 项 unittest、30 文件 Ruff/mypy、Schema generated/golden/不变量与项目检查通过 |
| Linux 容器回归 | 本轮显示器 26 项及既有 CPU 15、内存 26、电池 30、hwmon 47、存储 21、GPU 20 和 DMI/输入 7 场景通过；完整 /proc 覆盖仍由 OCI 拒绝，not_run |
| 实际 fuzz | 11 个既有目标各至少 60 秒并正常 DONE；dmi_text 含 EDID 纯解析及合成种子，不覆盖原生驱动边界 |
| 内存与供应链 | Miri 8 项、Linux FFI ASan 10 项、cargo-deny 通过；不是 Linux 真实显示设备长期泄漏证明 |

[Linux 原生报告](evidence/linux-display-native-linux-38983994614.json)、[Linux 八包报告](evidence/linux-display-package-evidence-linux-x64-38983994614.json)及本轮其他平台报告由汇总绑定原始/归档 SHA-256。汇总另保留完整工作流日志哈希与同源码的基准。文档归档提交不重跑源码 CI；本地 Windows 报告仍绑定实现提交，不能混作本轮 Linux 原生结果。


同轮 Linux 基准首次 collect（不含构造）911 µs，100 次动态刷新 p50/p95/max 105/129/169 µs；合成 100 传感器/1024 网络条目 collect 238 µs、JSON 373541 bytes。环境、profile、参数和边界见[性能报告](benchmarks.md)与[原始基准](evidence/linux-display-benchmark-38983994614.json)，不当作 EDID 专项耗时或性能 SLA。

## 兼容与验证边界

默认名称 Restricted/PrivacyRedacted，不检查/打开 EDID。仅 `PrivacyOptions` 的 include_sensitive 与 caller_authorized 同时为 true 才读取缓存 EDID 基础块；操作系统权限仍然生效。只解析 EDID 1.3/1.4 header/checksum 及 0xfc 名称，忽略扩展块和序列号，不能称为完整 EDID 验证或物理身份认证。项目采用独立解析和合成 fixture，没有复制 GPL 内核实现。

成功、空集合和失败均静态缓存，refresh_dynamic 不重扫；连接/权限恢复后新建 Hardware。两次状态读取不是原子拓扑快照，不能排除 ABA；同步 sysfs/驱动不能强制中止，属性类型检查不构成恶意文件系统 TOCTOU 沙箱。名称失败隔离到字段；状态未知/失败则拒绝完整集合，不返回成功前缀。

公共模型与签名、默认/公开 features、C ABI 1、Schema 1、两个锁文件及依赖许可证不变，项目仍 MIT。Linux backend 继续 forbid(unsafe_code)，无新依赖。动态 probe 的 authorize 命令只用于合成测试，不是生产授权协议。

实体 Linux、多显示器、MST、热插拔、当前模式、原生长期泄漏/峰值内存与 macOS 真机均待验证，按维护者设备安排延期。macOS 显示器尚未实现；下一片评估公开 API 的最小采集，实体测试和后续移动/Web 另行验收。
