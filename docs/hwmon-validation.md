# Linux hwmon 温度验证

2026-10-10实施、2026-10-11归档；本机与最终三平台CI通过。未发布；实机物理温度尚未验证。

## 契约与文件

[ADR0008](adr/0008-linux-hwmon.md)先于实现固定单位/隐私/资源策略。新增私有hwmon.rs并接入LinuxBackend动态采集，sensors能力Partial、SourceHwmon。core只增SensorInfo字段文档，Schema仅description元数据；公共结构/签名、ABI1/Schema1、0.1.0、运行依赖与MIT OR Apache-2.0不变。已有默认关闭fuzzing添加隐藏测试hook，新第8个fuzz目标与10个种子；没有新feature。

每次刷新重新枚举，不保存旧温度或设备列表，不读取静态模型字段。name仅供单位路由，不返回原始驱动字符串；不读取label/serial/device/uevent。所有条目label为Restricted/PrivacyRedacted，即便显式敏感选项也不增加此切片读取面。数组索引不是稳定设备标识。

只转换coretemp温度与k10temp temp2的Tdie，拒绝coretemp负值；其他通道不读input且温度Unsupported/NotSupported，不能把Tctl、毫伏或未知驱动当物理摄氏度。数值限于128字节有符号整数[-273150,1000000]毫度，除1000得到摄氏度；上界是库接受边界，不是传感器量程。可选enable/fault存在时严格0/1；禁用/故障返回TemporarilyUnavailable。不写任何真实sysfs控制项。

可读完整无温度输入为Available空集合；缺根目录Unavailable/NotPresent，权限拒绝Restricted/PermissionDenied。输入/name/flag错误局限于已枚举条目的温度字段，其他传感器及CPU/内存继续读取；枚举失败无法表达完整成员，则整个集合失败并丢弃前缀。

最多256类入口、1024个单芯片目录条目、4096合计条目，输出Options.max_entries（默认128）；超过即InvalidData，不返回截断成功。类链接允许，属性自身须普通文件，拒绝未变化的FIFO/设备/目录/属性链接；不消除恶意TOCTOU。上下文检查限制调用方等待，不能硬取消阻塞驱动。

## 已运行的本机命令

Windows x64、Rust1.96.0，通过mise；CARGO_INCREMENTAL=0。scripts/check.ps1 -Cross通过fmt、Clippy -Dwarnings、workspace全部feature测试、core/门面无默认feature、rustdoc -Dwarnings、CLI/FFI构建、Linux x64与macOS arm64交叉check。Windows实际70项Rust测试+1doctest（包含6项新增hwmon测试）；单Linux crate37项测试通过。这里的Linux crate名称不表示本机Linux运行。

八目标fuzz manifest fmt/check/clippy通过，是Windows编译；没有本机libFuzzer执行。Ruff格式/lint、mypy --no-incremental检查12份脚本/守卫通过，31项Python守卫通过；Schema生成/黄金样例/观测状态/未知字段/版本门禁通过，actionlint1.7.12与git diff --check通过。两份锁未变化。

首轮编译发现不存在Observed::unsupported构造器，改用现有missing契约；首轮3个fixture测试在collect前refresh，改为先建立初始快照，未改变API要求。这些失败发生在本机准备阶段，不作为实际Linux驱动故障。

## 远端验证与持久证据

scripts/linux_hwmon_smoke.py通过现有Docker生产Hardware探针连续验证36个观测；控制器只改自有合成fixture，容器非root/只读/断网/受限资源。场景包含真实0、坏数值、输入/name/flag权限、FIFO、相对Tctl拒绝、Tdie负值、单坏通道、目录失败/恢复、热插拔及四级枚举/输出限额。probe上限从32增到64，仍有界；现有CPU/内存/电池controller默认行为不变。

CI保留原8任务，新容器步骤与第8个独立60秒fuzz步骤，native_smoke额外保留实际sensors状态。最终源码`0fbc84ae445c9c2f717ac29c12da0a2bc512c4bf`的[运行38065295625](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38065295625)全部8任务success。UTC2026-10-10 15:51:24–16:01:17，北京时间10月10日23:51:24–10月11日00:01:17。未以旧源码结果代替最终源码验收。

CLI文本模式现在逐项显示Label与Temperature Celsius及缺失/限制状态，不只显示计数。三个desktop任务各实际运行dscope sensors；JSON/FFI结构没有变化。初版backend源码3c04fd3的[运行38064696284](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38064696284)也为8任务success、容器36项通过，Linux原生1条Unsupported温度。最终源码被分配到不同runner，Linux为Available/空集合/Hwmon，Windows/macOS为Unsupported/NotSupported/Custom，CLI与C报告一致；本机Windows也Unsupported。两个Linux runner结果并不矛盾，也不能推断同一机器的设备变化或物理温度已验证。最终原生文本步骤只命中空/Unsupported路径，数值文本分支尚未在真机命中。

| 最终job / ID | 实际结果 |
|---|---|
| desktop Linux / 114251596950 | 73项Rust+1doctest、31项Python；fmt/clippy/doc/no-default-features/build、Ruff/mypy、Schema、CLI文本及原生CLI/C/Python100次collect/free通过 |
| desktop Windows / 114251597051 | 同上，70项Rust+1doctest |
| desktop macOS arm64 / 114251596939 | 同上，72项Rust+1doctest |
| linux-container / 114251596953 | 36项hwmon、30项电池、26项内存/uptime、15项CPU与7个原降级场景passed；动态探针启动、进程/Docker退出0 |
| miri / 114251596900 | 固定nightly-2026-10-08，8项FFI memory_contracts通过，不是全部OS采集 |
| ffi-asan / 114251596993 | 固定nightly、-Zbuild-std、address sanitizer/detect_leaks=1，10项Rust FFI测试通过；C例子未插桩 |
| supply-chain / 114251597019 | cargo-deny0.20.2：advisories/bans/licenses/sources通过；既有syn重复版本警告保留 |
| fuzz-smoke / 114251596766 | cargo-fuzz0.13.2，八目标各配置60秒成功，实际8个DONE/完成行，无崩溃reproducer标记 |

hwmon容器配置实际核验UID/GID65534、只读rootfs/挂载、断网、cap-drop ALL/no-new-privileges、内存与交换总量256MiB、PID32、CPU1、nofile64。内容是合成fixture，权限拒绝/FIFO/挂载由真实Linux内核执行。36项全部Schema有效、健康内存未受影响、静态缓存保持、能力/来源/时间/原因匹配。完整/proc覆盖的既有额外探针仍runtime_rejected_mount、process_started=false、not_run，不能算backend通过。

新hwmon_temperature目标实际61秒执行**43,961,544次**，最终cov113/ft313、RSS266Mb，seed20261010、输入512字节、属性128字节、单输入2秒/RSS终止限512MiB。10个种子与源码Git对象一致；原始日志70,833字节、SHA256 `858626b12e181018d1cbae9d5d6084197563a874e5172e9cd520e3a61892eed4`。只测属性解析，不测目录/权限/热插拔；cov/ft不是覆盖百分比，RSS包括libFuzzer/ASan，不是库benchmark或硬沙箱。变异corpus未归档，固定seed不保证限时运行次数逐次一致。

共11份持久JSON：[CI元数据](evidence/ci-run-38065295625.json)、[原容器](evidence/linux-container-38065295625.json)/[CPU](evidence/linux-dynamic-38065295625.json)/[内存](evidence/linux-memory-38065295625.json)/[电池](evidence/linux-battery-38065295625.json)/[hwmon](evidence/linux-hwmon-38065295625.json)、[Linux](evidence/linux-native-38065295625.json)/[Windows](evidence/windows-native-38065295625.json)/[macOS](evidence/macos-native-38065295625.json)原生、[本机Windows](evidence/windows-native-hwmon-2026-10-10.json)、[fuzz汇总](evidence/hwmon-fuzz-38065295625.json)。全部绑定最终源码/git_dirty=false/锁哈希，并核验实际日志测试计数；本机CLI/C/Python成功独立于远端结果。原始日志在忽略目录target/ci-evidence，GitHub artifact保留14天；报告不是签名或供应链认证。

首次尝试下载单job日志时总run仍in_progress，gh拒绝提供日志；等待run完成后下载成功，不记录成backend失败。最终文档/证据归档使用[skip ci]，不改变被测源码、工作流、Schema或依赖。

## 未验证与下一步

未知驱动、k10temp Tctl/Tccd、热敏电阻校正、风扇/电压/阈值/告警结构、稳定设备标识、Windows/macOS传感器仍不支持。未做实机温度计比对、更多安全策略、长期fuzz、分配profiling、新benchmark或打包发布。先完成本轮CI与证据归档，再逐项扩展有资料和设备证据的驱动路由。
