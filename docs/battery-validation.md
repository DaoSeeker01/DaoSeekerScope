# Linux 电池受控枚举验收（2026-10-10）

实现依据与固定契约见[ADR0007](adr/0007-linux-power-supply.md)。本次仅增加LinuxBackend动态电池读取及验证，不扩大移动/Web/no_std/MCU支持。Schema1原有BatteryInfo两个字段复用，核心类型不增加字段；on_ac_power的Linux含义是系统Mains聚合，不是逐电池布线或所有USB电源状态。

## 修改

- Linux crate私有battery.rs与power_root，固定生产路径/sys/class/power_supply；每刷新重新扫描，256个供应设备硬上限、Options.max_entries电池上限、128字节属性上限。只读type/present/capacity/Mains online，拒绝非普通属性，不采集名称/序列号/uevent；class symlink仍允许。
- 完整无电池是Available空集合；缺目录、受限分类/存在状态、损坏或超限各有明确状态/原因，无截断前缀。坏电量/AC字段独立，不复用旧值，不把零值当缺失；没有Mains不能填false。能力Partial、SourceSysfs。
- 新增7个跨平台fixture测试、Unix额外class/attribute symlink测试、1个默认关闭fuzzing feature下的512输入变异测试。已有fuzzing feature增加隐藏power_supply函数及独立harness、10个种子；入口不承诺稳定消费者API，不访问文件。
- 新增scripts/linux_battery_smoke.py和6项证据/控制器守卫；复用动态probe控制器，测试用/sys只读合成目录挂载。30个连续生产Hardware观测覆盖热插拔、电量/AC损坏和权限/恢复、FIFO拒绝、缺失/受限目录、默认128电池上限与256供应设备上限。修改清理逻辑以处理缺失目录，并始终尝试删除自己创建的容器；其他控制器默认挂载不变。
- 原生报告额外保留电池实际Observed状态，不要求有设备。CI电池步骤与产物归档、Python门禁及第7个fuzz目标接入。核心字段文档与生成Schema仅增加description元数据；ABI1/Schema1、0.1.0、feature集合、依赖/两份锁和MIT OR Apache-2.0不变，未增加unsafe。

## 已执行本机验证

Windows Rust1.96.0实际执行scripts/check.ps1 -Cross通过：fmt、clippy -D warnings、64项Rust测试+1doctest、core/门面no-default-features、doc -D warnings、CLI/FFI build、Linux/macOS交叉类型检查。Linux crate单独all-features检查先通过30项测试（后续新增power_supply hook测试包含在完整门禁），属于合成文件测试，不能据此声称读取过Linux电池设备。7个fuzz harness的fmt/check/clippy通过，不是Windows libFuzzer运行。

固定Ruff0.14.13、mypy1.19.1、jsonschema4.25.1：10份Python脚本/测试的格式、lint、类型检查和最初25项守卫通过，修复控制器后26项通过；Schema元模型、黄金样例、生成漂移、未知字段与版本负面检查通过；actionlint1.7.12通过（shellcheck/pyflakes未启用）。两份锁与上次提交比对一致。

本机Windows当前Rust实现（源码fd18b29）的C例子重新编译、CLI/C实时JSON/Schema及Python100次collect/free通过，[报告](evidence/windows-native-battery-2026-10-10.json)记录Win32电量100%、AC=true，默认serial为Restricted/PrivacyRedacted。该报告绑定修复控制器之前的提交；修复不改Rust，但不把旧报告重标成新提交。

最初PyPI TLS握手EOF，使用现有固定版本缓存offline运行成功，没有改变TLS校验。Windows mypy不提供os.mkfifo定义，改为显式检测可调用性，缺失时失败，重跑10份类型检查通过；没有ignore掉该检查。早期单crate未关闭增量缓存出现hard-link复制提示，完整门禁禁用增量后通过；不是生产代码Clippy警告。

## 可复现命令

```sh
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features -- --test-threads=1
cargo check --locked -p daoseeker-scope-core --no-default-features
cargo check --locked -p daoseeker-scope --no-default-features
RUSTDOCFLAGS='-D warnings' cargo doc --locked --workspace --all-features --no-deps
cargo build --locked -p daoseeker-scope-cli -p daoseeker-scope-ffi
cargo fmt --manifest-path fuzz/Cargo.toml --check
cargo check --locked --manifest-path fuzz/Cargo.toml
cargo clippy --locked --manifest-path fuzz/Cargo.toml --all-targets -- -D warnings
python -m unittest discover -s tests -p 'test_*smoke.py'
python scripts/check_schema.py
cargo build --locked -p daoseeker-scope --example dynamic_probe
python scripts/linux_battery_smoke.py
cargo +nightly-2026-10-08 fuzz run power_supply -- -seed=20261010 -max_total_time=60 -max_len=512 -timeout=2 -rss_limit_mb=512
```

## 远端结果

首版源码fd18b29的[运行38047029198](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38047029198)电池步骤失败，[失败报告](evidence/linux-battery-failed-38047029198.json)保留overall=failed、13个已通过的观测及prerequisite_or_cleanup_failed。停止点为online_denied之后，恢复控制器在文件仍为000时write_bytes，非root所有者无法写入；本机Windows使用相同只读fixture复现PermissionError。改为仅对自己构造的fixture先chmod0600、写入后设置目标读权限；新增实际文件权限恢复回归与26项守卫通过。没有修改生产Rust、放宽权限预期或把未执行的后续场景改成成功。这个失败是验证控制器缺陷，不是已观察到的backend字段读取回归。

修复源码`15ef5c10dc99307501bf617f57779905cc1f50d6`的[运行38047435339](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38047435339)全部8个任务success，UTC2026-10-10 11:09:54–11:19:34（北京时间19:09:54–19:19:34）。实际日志计数如下，均含原有回归：

| job / ID | 实际结果 |
|---|---|
| desktop Linux / 114199689383 | Rust1.96.0，66项Rust测试+1doctest、26项Python守卫；fmt/clippy/doc/no-default-features/build、Ruff/mypy、Schema和原生CLI/C/Python100次collect/free通过 |
| desktop Windows / 114199689519 | 同上，64项Rust测试+1doctest及26项Python守卫 |
| desktop macOS arm64 / 114199689317 | 同上，65项Rust测试+1doctest及26项Python守卫 |
| linux-container / 114199689432 | 30项电池观测、26项内存/uptime、15项CPU及7个原降级场景passed，所有生产探针退出0 |
| miri / 114199689254 | 固定nightly-2026-10-08，8项FFI memory_contracts通过；不是全部OS采集 |
| ffi-asan / 114199689624 | 固定nightly、-Zbuild-std、address sanitizer与detect_leaks=1，10项Rust FFI测试通过；C例子未插桩 |
| supply-chain / 114199689567 | cargo-deny0.20.2，advisories/bans/licenses/sources通过，既有syn重复版本警告保留 |
| fuzz-smoke / 114199689392 | cargo-fuzz0.13.2、固定nightly，7目标各60秒，成功退出及完成标记核验通过 |

电池Docker配置实际验证：UID/GID65534、只读rootfs/挂载、断网、cap-drop ALL、no-new-privileges、内存/交换总量256MiB、PID32、CPU1及nofile64。输入为合成sysfs，不是实际电池认证；权限拒绝、FIFO与挂载视图由真实内核执行。30项含缺失/拒绝目录及分类、坏电量与AC字段隔离、真实0/100%、present默认/无设备、USB不推断AC、热插拔、两类超限与恢复。所有观测Schema有效、能力/原因/来源匹配、静态缓存不变且无额外backend issues。完整/proc替换额外探针仍为runtime_rejected_mount/process_started=false/not_run，没有改写成backend通过。

三平台原生报告的电池实际状态：Linux为Available/空集合/SourceSysfs；Windows为NotApplicable/NotPresent/SourceWin32/value=null（现有Win32无电池语义）；macOS为Unsupported/NotSupported/SourceCustom。没有把三个状态统一改写成无设备成功，或把Linux runner无条目当作真实笔记本读取。Windows本机结果另列上文，不与托管runner合并为相同机器。

| fuzz目标 | runs / 实际时间 | 最终cov / ft | 最终RSS |
|---|---|---|---|
| snapshot_json | 2,253,735 / 61秒 | 4304 / 10192 | 266Mb |
| dmi_text | 20,749,902 / 61秒 | 152 / 492 | 261Mb |
| cli_args | 19,178,097 / 61秒 | 144 / 248 | 275Mb |
| cpu_stat | 1,074,281 / 61秒 | 201 / 794 | 410Mb |
| meminfo | 4,685,965 / 61秒 | 247 / 985 | 287Mb |
| uptime | 20,955,969 / 61秒 | 148 / 413 | 310Mb |
| power_supply | 19,744,677 / 61秒 | 140 / 395 | 284Mb |

新目标10种子与被测Git对象字节/哈希比对一致，seed20261010、输入最大512字节、单输入2秒/RSS终止门限512MiB。日志无崩溃或超限终止；产物只有4份属性/procfs日志，无失败reproducer。新目标只验证128字节属性限制、类型文本与数值不变量，枚举/权限/热插拔由容器另验。cov/ft不是覆盖百分比，RSS包含libFuzzer/ASan，不是采集库benchmark或硬沙箱。变异后的corpus未归档，固定seed不能保证限时运行逐次一致。

本轮共12份持久JSON证据：失败[CI元数据](evidence/ci-run-failed-38047029198.json)/[电池报告](evidence/linux-battery-failed-38047029198.json)，修复[CI元数据](evidence/ci-run-38047435339.json)、[Linux](evidence/linux-native-38047435339.json)/[Windows](evidence/windows-native-38047435339.json)/[macOS](evidence/macos-native-38047435339.json)原生、[原容器](evidence/linux-container-38047435339.json)/[CPU](evidence/linux-dynamic-38047435339.json)/[内存](evidence/linux-memory-38047435339.json)/[电池](evidence/linux-battery-38047435339.json)动态、[fuzz汇总](evidence/power-supply-fuzz-38047435339.json)，及上文本机报告。核验源提交/git_dirty=false/锁哈希、步骤与完成标记；汇总保存种子/日志SHA256，原始日志保留于忽略目录target/ci-evidence，GitHub产物保留14天。报告不是签名或供应链认证。

推送首次TLS握手失败后重试成功；watch、部分日志/产物读取EOF，重试最终全部取得，未改变TLS校验。默认沙箱拒绝本机临时复现文件写入，改在工作区自有临时目录以普通主机权限复现；不是Linux backend失败或自动审批拒绝。最终归档仅修改文档与证据，使用[skip ci]，被测源码仍15ef5c1，不重复运行相同源码门禁。

## 限制

能力Partial不承诺完整电源拓扑；USB/Wireless/UPS、电池健康/寿命/温度/估算续航/充电控制不在本切片。集合模型无法表达不完整枚举，classification/present失败会让该集合不可用，不影响其他类别；没有稳定设备ID，不保证索引跨热插拔稳定。sysfs多文件读取非原子，驱动读取仍不能强制取消，文件类型检查不消除本机恶意替换竞态。128字节、256设备或调用方条目限额以上内容诚实拒绝，不截断。

60秒fuzz只覆盖属性解析，反馈计数不是覆盖百分比；未验证真实电池驱动/笔记本、更多发行版、安全策略、长期campaign、OS硬取消、分配profiling、benchmark、打包或发布。下一独立切片可推进Linux hwmon传感器，必须继续有界枚举、字段级失败与实际验证。
