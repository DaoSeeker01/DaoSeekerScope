# CPU动态刷新与恢复（2026-10-10，Asia/Shanghai）

本切片仅修复Linux CPU占用率新鲜度，不扩展电池/hwmon、内存或uptime采集。真实非root容器回归在旧源码448dd81上复现：有效计数获得50%，随后/proc/stat合成输入为空，旧实现仍返回Available/50%及新observed_at。[失败证据](evidence/linux-dynamic-before-38005835576.json)保留该现象；托管CI运行38005835576中的linux-container job实际失败，不将其算成功。

## 实现与契约

LinuxBackend新增私有cpu.rs，固定/proc/stat路径，每次最多读取4097字节、只解析首个aggregate cpu行，有效行最多4096字节。不提供生产路径重定向或原始计数公共API。接受4–10个无符号整数列，拒绝损坏UTF-8、负数/小数/溢出、缺列/多列及累加溢出；集合大小固定8项。guest/guest_nice已计入user/nice，不重复累加。定义CPU使用率为100×(总增量−idle增量−iowait增量)/总增量，包含steal，不解释为容器CPU配额。[Linux内核proc文档](https://docs.kernel.org/filesystems/proc.html)说明计数与iowait局限；iowait可能合法回退，本实现保守拒绝该区间，不将其解释成硬件损坏。

两个有效计数样本相隔至少300ms且总增量>0才Available。首次、过早刷新、计数无增长均Unavailable/TemporarilyUnavailable，不填0。快速轮询不替换尚未就绪的基线，避免一直无法就绪。纯idle增量是有效0%，纯busy增量可为100%。任何计数下降返回Unavailable/InvalidData并建立新基线；下一完整有效区间可恢复。读取/解析失败清除基线，恢复后的首读重新等待，而不跨错误区间计算或保留旧百分比。

PermissionDenied→Restricted/PermissionDenied，NotFound→Unavailable/NotPresent，其余IO错误→Unavailable/Unknown，坏输入→Unavailable/InvalidData；不可用值和时间均null。Linux CPU来源改为procfs，能力Supported，当前权限拒绝时Restricted，权限恢复时恢复Supported。错误逐字段隔离，内存等健康字段仍可返回；静态信息继续使用已有缓存，refresh_dynamic不重读DMI或CPU静态项。没有新增unsafe。

sysinfo在Linux不再声明或提供动态CPU占用率，防止组合时其旧Available值覆盖增强层的诚实失败。门面Hardware自动注册LinuxBackend，公共签名与模型不变。仅单独注册SysinfoBackend的Linux调用方现在得到Unsupported CPU占用率，需同时注册LinuxBackend或使用门面；这是开发版的行为兼容变化。Windows/macOS CPU仍用原sysinfo采样路径与Partial能力，未声称解决它们的上游缓存问题。

0.1.0、ABI1、Snapshot Schema1、Cargo.lock、依赖许可证与feature保持不变。source和状态行为改变已有文档说明，不改变交换格式；源名称procfs是Schema1已有枚举。没有新增运行依赖、crate或发布制品。

## 可复现验证

新增dynamic_probe Rust示例调用公开Hardware.collect/refresh_dynamic，一进程最多32条、每条最多16字节stdin命令，仅输出版本化Snapshot，不接受采集路径。scripts/linux_dynamic_smoke.py运行此示例，宿主只修改自己创建的合成stat文件，原inode只读bind到容器/proc/stat。容器与此前测试同样非root65534、只读、cap-drop ALL、no-new-privileges、断网、256MiB/无额外swap、32进程、1CPU、nofile64；不挂载源码、凭据或Docker socket。并非修改宿主真实/proc/stat。

15个连续观测：initial、ready、empty、recovery_baseline、recovery_ready、permission_denied、permission_recovery、permission_ready、unchanged、counter_reset、reset_ready、invalid_utf8、oversize、final_baseline、genuine_zero。验证精确百分比/状态/原因/时间、实时能力恢复、Schema与默认脱敏；健康内存必须可用。每个管道响应有10秒deadline、1MiB上限，Docker普通命令60秒上限、清理15秒，最终独立检查Docker与进程退出状态。中断先写incomplete，失败不得沿用旧passed。

```sh
cargo build --locked -p daoseeker-scope --example dynamic_probe
python -m pip install jsonschema==4.25.1
python scripts/linux_dynamic_smoke.py
```

须在Linux x86_64且可使用Docker daemon的环境运行；Windows本机只进行Rust/Python门禁，Linux真实执行由CI提供。新增7个Rust采样/解析测试在三平台可编译运行，另有Linux专用sysinfo单独注入回归。Python新增4项报告守卫，不把它们当内核执行证据。真实procfs读取由已有desktop_minimum_real_read_and_refresh验证，受控失效/恢复由合成挂载验证；两者证据分开。

## 尚未验证或改变的边界

不将合成计数称为真实硬件负载。完全缺失procfs、其他容器、安全策略、CPU热插拔与所有内核版本未验。读取字节/分配有界不意味着File::open/OS读取可硬取消；沿用worker等待上限和不可强杀边界。sysinfo内存与uptime仍Partial，刷新失败可能保留缓存或返回默认值，不能把此次CPU修复扩大为所有动态字段的新鲜度保证。静态失败继续缓存。未重跑benchmark，没有新CPU解析器长期fuzz campaign、内存profiling、cargo package或发布。

## 已取得的本地与容器证据

本地主机执行scripts/check.ps1 -Cross：fmt、clippy -D warnings、44项Rust测试+1doctest、core/门面no-default-features、doc -D warnings、CLI/FFI build及Linux/macOS交叉类型检查全部通过。首次沙箱执行在doctest写入临时exe时被OS拒绝，普通主机权限重试全套通过；未修改测试门禁。早期直接clippy曾产生incremental hard-link环境警告，完整门禁使用CARGO_INCREMENTAL=0后消失。交叉类型检查不能代替原生链接/读取。

Ruff0.14.13检查六份验收/守卫脚本，mypy1.19.1 --no-incremental --ignore-missing-imports六文件通过，Python16项守卫通过，actionlint1.7.12通过（外部shellcheck/pyflakes未启用），Schema黄金样例/生成漂移/负面不变量检查通过。Windows没有运行Docker/WSL服务；本轮未本地重复C/Python原生采集，三平台CI负责重新执行该门禁。

修复后源码`3ec5f6e949889b4df95df5bb171f09fc0eeeb9bb`的[运行38006382007](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38006382007)容器job114076023077已success。[CPU连续观测报告](evidence/linux-dynamic-38006382007.json)15项全passed，均procfs；进程实际启动，Docker与进程均退出0。[原7场景报告](evidence/linux-container-38006382007.json)也passed，完整/proc探针仍not_run。两个报告git_dirty=false，锁哈希与本地一致，Docker28.0.4及固定Ubuntu24.04镜像保持不变，分别记录示例/CLI二进制哈希。

## 最终CI：8/8成功

[运行38006382007](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38006382007)已completed/success，8个job全部success，被测源码仍3ec5f6e。UTC 2026-10-09 23:50:42开始、23:56:11完成，即北京时间2026-10-10 07:50:42–07:56:11。[CI元数据](evidence/ci-run-38006382007.json)保留所有步骤及结论；其他OS的条件编译步骤skipped，不冒充执行。

| job / 实际runner | ID | 实际结果 / 原生证据 |
|---|---|---|
| desktop Linux / ubuntu-24.04 x64 | 114076023545 | 45 Rust测试+1doctest、16 Python守卫；[Linux](evidence/ci-linux-x64-38006382007.json) |
| desktop Windows / windows-2025-vs2026 x64 | 114076023076 | 44 Rust测试+1doctest、16 Python守卫；[Windows](evidence/ci-windows-x64-38006382007.json) |
| desktop macOS / macos-26-arm64 | 114076023052 | 44 Rust测试+1doctest、16 Python守卫；[macOS](evidence/ci-macos-arm64-38006382007.json) |
| linux-container / ubuntu-24.04 | 114076023077 | 7个原场景与15个CPU连续观测通过；完整/proc探针not_run |
| miri | 114076022966 | 8项纯内存契约通过，2项OS测试过滤 |
| ffi-asan | 114076022847 | 10项Rust FFI单元测试通过，未发现ASan错误 |
| supply-chain | 114076023079 | cargo-deny advisories/bans/licenses/sources通过 |
| fuzz-smoke | 114076023035 | 既有三个60秒目标正常结束 |

三平台实际执行：`cargo fmt --all --check`；`cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`；`cargo test --locked --workspace --all-features -- --test-threads=1`；core及门面`--no-default-features` check；`cargo doc --locked --workspace --all-features --no-deps`（RUSTDOCFLAGS=-D warnings）；CLI/FFI build；Schema检查；六份Python脚本的格式/lint/mypy及16守卫；Windows cl /W4 /WX、Unix cc -Wall -Wextra -Werror；`python scripts/native_smoke.py`的CLI/C/100次Python FFI collect/free。原生报告overall/三个检查均passed、源码SHA一致、git_dirty=false、锁哈希匹配；CLI及C各自采集，不能称原子快照。

原生CLI实际CPU品牌分别Linux/Windows AMD EPYC 7763 64-Core Processor（各2逻辑CPU）、macOS Apple M2 Pro (Virtual)（5逻辑CPU）。Linux初读CPU占用率procfs/TemporarilyUnavailable，Windows/macOS仍sysinfo/TemporarilyUnavailable；有效间隔后的真实刷新由desktop测试独立通过。品牌字符串和托管runner读值不是物理硬件认证。

Miri/ASan命令、nightly-2026-10-08、cargo-fuzz0.13.2、cargo-deny0.20.2及fuzz参数均沿用[首次CI门禁](ci-validation.md)。ASan只插桩Rust FFI测试，不声称C例子也经过插桩；Miri不执行OS采集。stable无代码警告，nightly仍有AtomicUsize::fetch_update弃用提示，cargo-deny仍有syn2/3重复版本警告。本轮未升级工具链、actions或依赖。

| 既有fuzz目标 | 实际runs / 时间 | 最终cov / ft | 最终RSS |
|---|---|---|---|
| snapshot_json | 2,002,676 / 61秒 | 4284 / 9813 | 350Mb |
| dmi_text | 22,142,295 / 61秒 | 149 / 518 | 378Mb |
| cli_args | 18,853,691 / 61秒 | 145 / 248 | 347Mb |

没有崩溃或超限终止；插桩计数不是源代码覆盖百分比，RSS包含libFuzzer开销，变异corpus未上传。这三个目标不覆盖新的私有CPU解析器，也不能替代其未来fuzz campaign；本轮CPU解析器负面验证来自7项确定性Rust测试及真实容器故障注入。

共7份本轮证据保存仓库：旧CPU失败1份，新CPU/容器2份，三平台原生3份，CI元数据1份；不依赖14天artifact期限。下载日志暂留忽略目录target/ci-evidence/38006382007，不提交原始runner路径。并发gh日志下载曾有一次缓存zip错误，单独重试成功后才核验ASan日志，不将下载失败当运行失败或通过。证据哈希不是签名。最终归档提交只修改文档/证据并用[skip ci]，其代码与3ec5f6e相同。

下一独立切片优先处理Linux内存/uptime的结构化失败与新鲜度，再扩展设备枚举。
