# Fuzz 目标

2026-10-25 Windows 硬件摘要扩展既有 `dmi_text`，复用生产 REG_SZ 严格 UTF-16 解析器，检查 Win32 来源、确定性、4096-byte 输入/输出上限、控制字符和占位词。两份自制合成种子，不读取注册表或真实设备。目标总数仍为 12，Windows 本地 harness 单测增至 4 项；本轮 CI 40145306966 已在 Linux 运行扩展 dmi_text：61 秒/6,509,574 次，全部十二目标各至少 60 秒，4 项 harness 守卫通过；解析器 fuzz 不证明真实注册表权限或数据来源，见[ADR 0030](../docs/adr/0030-windows-hardware-summary.md)。

2026-10-24 新增第 12 个目标 `windows_cpu_groups`：使用 Windows crate 默认关闭的 `fuzzing` feature，复用生产的 64 位 RelationGroup 字节解析器；1024-byte 上限、组数/稀疏 mask/状态/确定性检查和合成双组种子。不执行 Windows API，不能证明真实跨组切换。Windows 本地 fmt/check/严格 Clippy 与 3 项 harness 单测通过；CI 40046393393 在 Linux 实际运行 12 个目标，每个 61 秒，新目标 55,466,941 次，无崩溃正常完成。2026-10-25 [归档索引](../docs/evidence/windows-cpu-groups-ci-40046393393.json)记录逐目标计数和日志哈希，见[验证边界](../docs/windows-cpu-groups-validation.md)。

```sh
cargo +nightly-2026-10-08 fuzz run windows_cpu_groups -- -seed=20261024 -max_total_time=60 -max_len=1025 -timeout=2 -rss_limit_mb=512
```

2026-10-15 Linux GPU 增量复用 `dmi_text` 目标，另外调用生产 AMDGPU 产品文本和 NVIDIA 首行 Model 解析器，检查 4096 字节上限、UTF-8/控制字符及状态/来源/时间/原因。两个合成种子扩展该 corpus；默认关闭的 fuzzing 入口不读文件、不证明驱动或设备可用。目标总数仍为 11，不包含 DRM 枚举/权限 fuzz，见[ADR](../docs/adr/0017-linux-gpu.md)。

第十一个目标 `storage_capacity` 检查生产 sysfs size 的 512 字节换算、128 字节上限、零值与溢出，七个合成种子；不枚举设备或执行权限测试。来源固定 Sysfs，复用明确指定来源的共享检查。源码 2b19e8d 的 CI 38188243470 全部十一个目标各至少 60 秒通过；本目标为 61 秒、37,258,518 次，无崩溃正常结束。两项 harness 回归也通过；见[存储验证](../docs/storage-validation.md)和[契约](../docs/adr/0013-storage-capacity.md)。

```sh
cargo +nightly-2026-10-08 fuzz run storage_capacity -- -seed=20261012 -max_total_time=60 -max_len=512 -timeout=2 -rss_limit_mb=512
```

第十个目标 `macos_network` 复用生产 Darwin 路由字节解析器，检查消息边界、512 KiB/8192 消息/接口条数上限、默认脱敏和字段状态。四个合成种子覆盖有效 u64、截断、零索引和超大输入；不执行 macOS sysctl，Linux fuzz 不能代替 macOS 原生读取。首轮 CI 38095804975 在空输入时因共享断言误要求 Procfs 而失败；修复改为各目标显式要求自身来源，新增两项 harness 回归，保留全部断言。修复源码 d27e681 的 CI 38186025262 全部十个目标各至少 60 秒通过；macos_network 为 61 秒、5,057,654 次，无崩溃正常结束。两个 harness 回归也在 Linux CI 通过，见 [独立验收与失败记录](../docs/macos-network-validation.md)，契约见 [ADR 0012](../docs/adr/0012-macos-network-counters.md)。

```sh
cargo +nightly-2026-10-08 fuzz run macos_network -- -seed=20261011 -max_total_time=60 -max_len=524289 -timeout=2 -rss_limit_mb=512
```

2026-10-11 新增第九个目标 `network_dev`：生产 `/proc/net/dev` 解析、512 KiB 上限、1/128/1024 条数上限、默认/授权名称与字段状态不变量。六个种子覆盖有效/零值/溢出/重复/列损坏/合法空集合；执行证据见[网络验收](../docs/network-validation.md)。下文先前轮次的计数不代表本目标已运行。

```sh
cargo +nightly-2026-10-08 fuzz run network_dev -- -seed=20261011 -max_total_time=60 -max_len=524289 -timeout=2 -rss_limit_mb=512
```

原有三个目标：snapshot_json（1MiB JSON上限、不变量与往返）、dmi_text（损坏/过长/DMI占位字符串）、cli_args（换行拆分参数、数量/大小/敏感授权，不执行采集）。corpus提供合法快照、DMI合法/占位/非法UTF-8、CLI合法/授权/未授权种子。

固定nightly-2026-10-08、cargo-fuzz0.13.2。官方cargo-fuzz仅支持Unix类平台的x86_64/AArch64，Windows原生不受支持；六个harness在Windows编译通过，2026-10-10已在Linux x64 CI各完成60秒libFuzzer smoke，均正常结束，详见[最新验收](../docs/procfs-fuzz-validation.md)。

```sh
rustup toolchain install nightly-2026-10-08 --profile minimal
cargo +nightly-2026-10-08 install cargo-fuzz --version 0.13.2 --locked
cargo +nightly-2026-10-08 check --locked --manifest-path fuzz/Cargo.toml
cargo +nightly-2026-10-08 fuzz run snapshot_json -- -max_total_time=60 -max_len=1048577 -rss_limit_mb=512
cargo +nightly-2026-10-08 fuzz run dmi_text -- -max_total_time=60 -max_len=8192 -rss_limit_mb=512
cargo +nightly-2026-10-08 fuzz run cli_args -- -max_total_time=60 -max_len=8192 -rss_limit_mb=512
```

从仓库根运行；CI已远端执行通过。60秒smoke不能代表长期campaign或完整覆盖率。RSS上限是libFuzzer终止门限，不是硬内存沙箱；原三个目标2026-10-09首次运行最终RSS分别302/307/350Mb，最新六目标计数见验收表，包含libFuzzer运行开销，不作为采集库内存基准。变异后的corpus未单独上传，运行次数与覆盖计数不能保证逐次复现。

Windows确定性回归已随workspace tests运行：512个JSON变异、512个DMI样本、4096个CLI组合、256种重复字节参数。它们没有覆盖反馈，不属于libFuzzer campaign。8项FFI内存契约经Miri交叉解释通过，详见 [验收记录](../docs/input-ffi-validation.md)。

hwmon第8个目标hwmon_temperature复用生产有符号整数毫度解析器；12个种子（新增NVMe毫度值），128字节上限、物理下界与库接受上界、无NaN/钳制或缺失时间伪装。2026-10-11扩展同一harness，分别检查Composite/独立通道零Kelvin缺失策略与其他数值等价，执行状态见[NVMe验收](../docs/nvme-temperature-validation.md)。驱动枚举和真实权限由另外的fixture/容器验证；属性fuzz不证明硬件可读。

```sh
cargo +nightly-2026-10-08 fuzz run hwmon_temperature -- -seed=20261010 -max_total_time=60 -max_len=512 -timeout=2 -rss_limit_mb=512
```

本机Windows八个harness fmt/check/clippy通过；最终源码0fbc84a的CI38065295625全部八目标通过，新hwmon目标实际61秒/43,961,544次、cov113/ft313/RSS266Mb，无崩溃完成；2026-10-11归档于[hwmon验收](../docs/hwmon-validation.md)。计数/RSS不是覆盖百分比或库内存基准；上文七目标数据属于前轮电池源码。种子/日志与实际测试计数哈希见[汇总](../docs/evidence/hwmon-fuzz-38065295625.json)。

依据：[cargo-fuzz官方平台限制](https://github.com/rust-fuzz/cargo-fuzz#installation)。

新增三个procfs目标：cpu_stat（最多16帧的解析/采样状态与恢复）、meminfo（单位/总量/字段隔离）、uptime（小数截断与整数边界），25个合成种子。默认关闭的Linux fuzzing feature只提供隐藏测试入口，复用生产解析器，不读取真实设备或声明新平台支持；见[ADR](../docs/adr/0006-procfs-fuzz-hooks.md)和[独立验收](../docs/procfs-fuzz-validation.md)。本机Windows的check/clippy不是libFuzzer执行，实际Linux CI结果在验收中单列。

```sh
cargo +nightly-2026-10-08 fuzz run cpu_stat -- -seed=20261010 -max_total_time=60 -max_len=8192 -timeout=2 -rss_limit_mb=512
cargo +nightly-2026-10-08 fuzz run meminfo -- -seed=20261010 -max_total_time=60 -max_len=8192 -timeout=2 -rss_limit_mb=512
cargo +nightly-2026-10-08 fuzz run uptime -- -seed=20261010 -max_total_time=60 -max_len=512 -timeout=2 -rss_limit_mb=512
```

新增power_supply目标与10个合成种子，复用生产属性解析器的128字节限额和0..100/0..1严格整数规则；不执行sysfs枚举或权限测试。第7个harness本机fmt/check/clippy通过，2026-10-10修复源码15ef5c1的CI38047435339全部七目标各60秒正常结束；power_supply执行19,744,677次，cov140/ft395、最终RSS284Mb，不是覆盖百分比或采集库内存基准。原六目标上文记录属于先前运行，最新七目标计数见[电池验收](../docs/battery-validation.md)。

```sh
cargo +nightly-2026-10-08 fuzz run power_supply -- -seed=20261010 -max_total_time=60 -max_len=512 -timeout=2 -rss_limit_mb=512
```

2026-10-11 NVMe扩展源码9931cf9的CI38067341915全部八目标通过；同一hwmon目标增加生产零Kelvin策略，实际61秒/35,010,619次、cov154/ft343/RSS306Mb，无崩溃完成。12种子/日志/测试计数哈希见[NVMe汇总](../docs/evidence/nvme-fuzz-38067341915.json)与[验收](../docs/nvme-temperature-validation.md)；前一hwmon轮次是历史结果，不等于新harness执行。
