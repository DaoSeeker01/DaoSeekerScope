# Linux 内存与 uptime 刷新验收（2026-10-10）

本切片只处理 Linux 内存与运行时长的新鲜度、结构化错误与缓存一致性。Windows/macOS 保持 sysinfo 路径及 Partial 能力，未据此宣称它们的读取错误已修复。

## 先复现旧实现

仅回归探针提交 `64e65c0ed1c9b59f455432b657dd3678522298f4` 的[运行38008139512](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38008139512)中，非root容器首次从合成 meminfo/uptime 得到524,288字节和123秒；宿主将两个只读挂载的文件原inode清空后，production Hardware.refresh_dynamic 仍返回 Available/524,288字节，时间从1791591272412更新为1791591272508。uptime 返回 Available/68秒：结合上游源码判断进入了 sysinfo 的 libc::sysinfo 回退路径，不能把它描述为默认0或旧123秒。容器job因观测断言失败，[失败报告](evidence/linux-memory-before-38008139512.json)overall=failed；不是挂载失败或未运行。该运行最终7个job成功、仅linux-container按预期失败。

上游0.39.6源码实查：refresh_memory_specifics保留已有内存字段，并在MemAvailable缺失时由其他缓存字段估算；uptime先读取procfs，失败转入系统调用，最终错误没有结构化出口。这些数值型接口不能满足本项目当前的失败语义。研究依据：[内核procfs说明](https://docs.kernel.org/filesystems/proc.html)、[内核meminfo实现](https://raw.githubusercontent.com/torvalds/linux/master/fs/proc/meminfo.c)、[内核uptime实现](https://raw.githubusercontent.com/torvalds/linux/master/fs/proc/uptime.c)（2026-10-10核验；未复制或链接内核代码）。研究不代替运行证据。

## 实现与契约

LinuxBackend直接读取/proc/meminfo与/proc/uptime，来源Procfs，能力Supported表示当前实现能解释读取结果，不保证每台机器字段可用。meminfo最多4096字节、uptime最多256字节，各读取上限+1以识别超长；整数转换checked，不饱和、不以浮点解析。meminfo的kB按1024字节换算；MemTotal必须非零，MemAvailable可真实为零且不能超过本次MemTotal。缺少键NotPresent；无MemAvailable的旧内核不以MemFree估算冒充同一字段。损坏UTF-8、空文件、重复关键键、错误单位、负数、溢出及超长InvalidData。MemAvailable损坏不丢弃有效静态MemTotal。

uptime要求两个无符号十进制数，第一项取整数秒；第二项为累计CPU idle，只校验格式而不要求小于uptime。0.00为合法0，损坏/缺项不返回Available/0，也不切换到未标注的其他来源。PermissionDenied返回Restricted/PermissionDenied；NotFound返回Unavailable/NotPresent；其他IO错误保守Unknown。无值时无采集时间。内存和uptime独立失败，CPU/DMI继续采集。

总内存静态属性仍首次缓存，包括失败状态；动态刷新重读MemTotal只为校验MemAvailable。若初次总量有效且本次总量变化，动态可用内存为Unavailable/TemporarilyUnavailable，静态值/时间不变。重建Hardware可重新采集静态总量；恢复原总量后动态可恢复。初次静态读取失败时，后续有效动态读可恢复，但失败静态字段继续缓存。没有引入新的缓存刷新API。

Linux SysinfoBackend停止提供总内存、可用内存及uptime，避免低优先级缓存有效值掩盖增强backend的失败；此前CPU使用率亦已委托。仅注册SysinfoBackend的Linux调用方需注册LinuxBackend或使用门面Hardware::new，相关字段将Unsupported。这是0.1开发版行为兼容变化，公共签名、模型、feature、ABI1及Schema1不变；procfs为既有Source枚举。没有新增crate、运行依赖、unsafe或许可证变化。

## 验证入口与本地结果

新增私有procfs.rs的7项解析/IO/上限测试、LinuxBackend的2项缓存/字段隔离/恢复测试；Linux sysinfo单独注入测试扩展到四字段；desktop真实读取测试增加内存/uptime及Linux来源检查。Windows本地主机完整scripts/check.ps1 -Cross通过：fmt、clippy -D warnings、53项Rust测试+1doctest、core/门面no-default-features、doc -D warnings、CLI/FFI build、Linux/macOS交叉类型检查。交叉检查不代表原生链接或设备读取。

新scripts/linux_memory_smoke.py复用linux_dynamic_smoke.py的受限Docker控制器与dynamic_probe，不向生产库增加Fixture路径参数。两个合成文件只读挂载到真实/proc路径；宿主只更改自己创建的inode和权限。容器非root65534、断网、只读root、cap-drop ALL、no-new-privileges、256MiB/无额外swap、1CPU、32进程、nofile64。响应10秒/1MiB有界，Docker命令60秒、清理15秒；正常结束还检查进程真实启动/退出0及非OOM。报告只保留相关观测，失败/中断先写failed/incomplete，不能复用旧passed。

26项连续观测：初读、两源清空与恢复、各源权限拒绝与恢复；内存损坏UTF-8、超长、错误单位、溢出、重复、超过总量、缺少MemAvailable、真实0、恢复、总量变化/恢复；uptime损坏UTF-8、超长、NaN、负数、溢出、缺idle、真实0及最终恢复。每步检查Schema、精确状态/原因/值/时间、能力恢复、静态缓存不变、默认隐私与backend错误隔离。合成输入验证采集路径，不能描述为物理内存或真实启动时间；真实读值由独立desktop门禁提供。

```sh
cargo build --locked -p daoseeker-scope --example dynamic_probe
python -m pip install jsonschema==4.25.1
python scripts/linux_memory_smoke.py
```

Ruff0.14.13格式/lint、mypy1.19.1 --no-incremental --ignore-missing-imports检查8份Python脚本通过；20项报告守卫、Schema黄金/生成漂移/负面不变量与actionlint1.7.12通过（外部shellcheck/pyflakes未启用）。本机未执行Linux Docker或WSL；新源码的实际原生/容器执行来自下列CI。

## 最终CI与保留证据

被测源码 `6d0a37703ad46ed859562752b7f21fae2dbcfeae` 的[运行38008554490](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38008554490)已completed/success，8/8 job成功。UTC 2026-10-10 00:19:36–00:24:36，即北京时间08:19:36–08:24:36。[元数据](evidence/ci-run-38008554490.json)记录各job/step结论；条件平台步骤skipped不算执行。

| job | ID | 实际结果 |
|---|---|---|
| desktop Linux x64 / ubuntu-24.04 | 114082955697 | 54项Rust测试+1doctest、20项Python守卫；[原生报告](evidence/ci-linux-x64-38008554490.json) |
| desktop Windows x64 / windows-latest | 114082955689 | 53项Rust测试+1doctest、20项Python守卫；[原生报告](evidence/ci-windows-x64-38008554490.json) |
| desktop macOS arm64 / macos-latest | 114082955721 | 53项Rust测试+1doctest、20项Python守卫；[原生报告](evidence/ci-macos-arm64-38008554490.json) |
| linux-container x64 / ubuntu-24.04 | 114082955658 | [26个内存/uptime观测](evidence/linux-memory-38008554490.json)、[15个CPU观测](evidence/linux-dynamic-38008554490.json)、[原7场景](evidence/linux-container-38008554490.json)均passed |
| miri | 114082955707 | 8项纯内存契约通过，2项OS测试过滤 |
| ffi-asan | 114082955770 | 10项Rust FFI测试通过，无ASan错误 |
| supply-chain | 114082955536 | cargo-deny advisories/bans/licenses/sources通过 |
| fuzz-smoke | 114082955691 | 既有三个60秒目标正常结束 |

三平台实际执行：cargo fmt --all --check；cargo clippy --locked --workspace --all-targets --all-features -- -D warnings；cargo test --locked --workspace --all-features -- --test-threads=1；core/门面 --no-default-features check；cargo doc --locked --workspace --all-features --no-deps（RUSTDOCFLAGS=-D warnings）；CLI/FFI build；8份Python格式/lint/mypy和20守卫；scripts/check_schema.py；Windows cl /W4 /WX或Unix cc -Wall -Wextra -Werror；scripts/native_smoke.py实际CLI/C/Python100次collect/free。各原生报告三个检查均passed、git_dirty=false、源码SHA及Cargo.lock哈希匹配。公开desktop集成测试实际读取并刷新内存/uptime，Linux另断言Procfs来源；保留的原生JSON仅存最小字段，未把未归档的实时动态数值写成报告中的读值。

原生CLI读值：Linux CPU品牌AMD EPYC 9V74 80-Core Processor、2逻辑CPU、OS可用总内存8,323,969,024字节/Procfs；Windows AMD EPYC 7763 64-Core Processor、2逻辑CPU、8,584,425,472字节/Sysinfo；macOS Apple M2 Pro (Virtual)、5逻辑CPU、15,032,385,536字节/Sysinfo。托管runner读值和品牌字符串不能认证物理硬件。CLI/C各自采集，不称原子快照。

26项报告全为Procfs，清空后两个字段均无值/无时间；各源chmod拒绝为Restricted/PermissionDenied，健康另一个字段继续Available；恢复后能力不滞留Restricted。合法0与读取失败明确分开，总量变化为TemporarilyUnavailable，静态总量1,048,576字节及时间不变。Docker28.0.4、固定Ubuntu镜像/资源配置、源码与锁哈希一致，probe实际启动、进程与Docker退出0。原7场景空meminfo现在InvalidData/Procfs/Supported，静态CPU仍Unknown/Sysinfo/Partial；原完整/proc挂载探针仍运行时拒绝、process_started=false、not_run，未当作backend通过。

Miri/ASan/cargo-deny/cargo-fuzz命令及参数沿用[首次CI门禁](ci-validation.md)与现有workflow，nightly固定2026-10-08，cargo-deny0.20.2、cargo-fuzz0.13.2。ASan范围仍是Rust FFI测试，C例子未插桩；Miri不进行OS查询。stable无代码警告，nightly仍有AtomicUsize::fetch_update弃用提示，审计仍有syn重复版本警告，没有忽略漏洞或升级依赖。

| 既有fuzz目标 | 实际runs / 时间 | 最终cov / ft | 最终RSS |
|---|---|---|---|
| snapshot_json | 2,804,091 / 61秒 | 4428 / 10318 | 317Mb |
| dmi_text | 28,979,167 / 61秒 | 152 / 516 | 288Mb |
| cli_args | 25,656,599 / 61秒 | 145 / 249 | 310Mb |

无崩溃或超限终止；这些目标不覆盖私有procfs解析器，插桩计数不是源代码覆盖百分比，RSS包含fuzzer开销。报告共8份保存仓库（旧失败1、修复容器3、原生3、CI元数据1），不依赖14天artifact保留期；原始日志放忽略目录target/ci-evidence/38008554490。一次只读GitHub运行查询EOF后重试成功，属于基础设施读取失败，不改变backend验收结论。最终归档只修改文档/JSON、使用[skip ci]，代码与被测提交相同。

## 边界与下一阶段

procfs内存表示其提供的系统视图，不能当作容器cgroup配额；uptime遵循其时间命名空间。没有确认所有Linux内核/发行版、SELinux策略、完全缺失procfs、真实热插拔或WSL。静态失败继续缓存，OS读取仍无法强制取消；4096/256字节以上内容诚实拒绝。没有新增解析器libFuzzer目标或长期campaign，本轮负面证据是确定性测试和真实内核权限/合成文件注入。未重跑benchmark、峰值内存profiling、cargo package或发布；移动/Web/no_std/MCU及设备枚举不增加支持声明。下一独立切片可开始Linux电池受控枚举，或先补procfs解析器的独立fuzz验证。

后续独立切片已于2026-10-10执行[procfs解析器fuzz](procfs-fuzz-validation.md)：源码4eb7e971、CI38044730604全部8任务成功，三个新目标各60秒正常结束，原有内存/uptime26个观测也重验通过。上文未执行清单描述本次内存修复的历史范围；后续仍未运行长期campaign、benchmark或发布。
