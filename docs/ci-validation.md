# 三平台CI验收（2026-10-09，Asia/Shanghai）

本文保留首次7任务运行的历史证据。最新源码3ec5f6e已在[运行38006382007](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38006382007)通过全部8任务（含7容器场景及15个连续CPU观测），各平台44/45项Rust测试+1doctest、16项Python守卫；详情见[CPU与最新CI验收](cpu-refresh-validation.md)。此前8e0e7d9证据保留于[容器验收](linux-container-validation.md)。新CI已更新Node24 actions；下文首次运行的Node20提示仍作为历史记录保留。

用户已明确授权创建**私有**DaoSeeker01/DaoSeekerScope、推送与运行CI。[仓库](https://github.com/DaoSeeker01/DaoSeekerScope)已建立，main首次源码提交为`a0acc060381fc3e9a68eb1ff48a8f5c379f92058`。[运行37864529108](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/37864529108)在UTC 00:23:30开始、00:28:47完成（北京时间08:23:30–08:28:47），最终conclusion=success，7个job全部success。

## 原生平台与真实读取

| job / 实际runner镜像 | 架构 | CLI实际CPU/逻辑数 | OS可用总内存（字节） | 安装内存（字节/来源） | 原始报告 |
|---|---|---|---|---|---|
| 113607980674 / windows-2025-vs2026 | x86_64 | AMD EPYC 7763 64-Core Processor / 2 | 8,584,425,472 | 8,589,934,592 / win32 | [Windows](evidence/ci-windows-x64-37864529108.json) |
| 113607980676 / ubuntu-24.04 | x86_64 | AMD EPYC 9V74 80-Core Processor / 2 | 8,323,960,832 | Unsupported / NotSupported | [Linux](evidence/ci-linux-x64-37864529108.json) |
| 113607980572 / macos-26-arm64 | arm64 | Apple M2 Pro (Virtual) / 5 | 15,032,385,536 | 15,032,385,536 / sysctl | [macOS](evidence/ci-macos-arm64-37864529108.json) |

三个报告overall及CLI/C/Python检查均passed，git_revision均为上述源码提交，git_dirty=false，Cargo.lock SHA256均为`e04239561667b4f20152f0fe6b80aaafeb483e7ad8fea41f8c3aaadd76c177a9`，下载后与本地锁再次比对。报告保留CLI/C各自独立采集的值、状态、来源、时间、原因和二进制SHA256；不含序列号、主机名或账号。

Linux API报告Ubuntu24.04/kernel6.17.0-1022-azure，macOS报告Darwin26.6.2/kernel25.6.0，Windows API报告11(26100)/kernel26100。Windows runner镜像标识是windows-2025-vs2026，不能把sysinfo返回字符串当成独立验证的OS产品版本。CPU品牌是虚拟环境读值，其中“64/80-Core”是型号字符串，不等于runner分配核数；逻辑计数实际为2。以上均为托管runner原生OS读取，不是裸机硬件认证。

三个平台序列号均Restricted/PrivacyRedacted/value=null/observed_at=null；首次CPU使用率均Unavailable/TemporarilyUnavailable，未填0。Linux安装内存明确Unsupported，没有把空值算成功。GPU、存储、网络、传感器、显示器仍为当前未实现能力。原生smoke强制验证CPU/OS/内存最小摘要与隐私，不要求所有可选增强字段可用。

## 实际执行的门禁

三个desktop job均在Rust1.96.0上通过：

| 命令/步骤 | 实际结果 |
|---|---|
| cargo fmt --all --check | 三平台通过 |
| cargo clippy --locked --workspace --all-targets --all-features -- -D warnings | 三平台通过，无stable代码警告 |
| cargo test --locked --workspace --all-features -- --test-threads=1 | 各37项测试+1项doctest，0失败/忽略；包含各OS非法参数编码测试 |
| cargo check --locked -p daoseeker-scope-core --no-default-features | 三平台通过 |
| cargo check --locked -p daoseeker-scope --no-default-features | 三平台通过 |
| cargo doc --locked --workspace --all-features --no-deps，RUSTDOCFLAGS=-D warnings | 三平台通过 |
| cargo build --locked -p daoseeker-scope-ffi -p daoseeker-scope-cli | 三平台原生链接通过 |
| ruff format --check / ruff check / mypy --ignore-missing-imports，native_smoke.py及test_native_smoke.py | 三平台通过；jsonschema外部类型缺失允许 |
| python -m unittest discover -s tests -p test_native_smoke.py | 各4项守卫通过 |
| python scripts/check_schema.py | 三平台元Schema、黄金样例、生成漂移与负面契约通过 |
| Windows cl /W4 /WX /std:c11；Unix cc -Wall -Wextra -Werror | C例子三平台编译通过，链接当前FFI |
| python scripts/native_smoke.py | 三平台CLI/C实际读取、实时Schema及Python100次collect/free通过 |

Python分别为Windows3.12.10、Linux3.12.3、macOS3.14.7。开发工具固定jsonschema4.25.1、Ruff0.14.13、mypy1.19.1；没有修改本机全局环境。

其余实际执行命令：

| job | 命令与范围 | 结果 |
|---|---|---|
| supply-chain / 113607980352 | cargo install cargo-deny --version 0.20.2 --locked；cargo deny check | advisories/bans/licenses/sources全通过；syn2.0.119/3.0.6重复版本警告保留 |
| miri / 113607980569 | cargo +nightly-2026-10-08 miri test --locked -p daoseeker-scope-ffi --target x86_64-unknown-linux-gnu memory_contracts -- --test-threads=1 | 8项纯内存契约通过，2项实际OS测试过滤；不是Miri执行全部系统采集 |
| ffi-asan / 113607980615 | cargo +nightly-2026-10-08 test --locked -Zbuild-std --target x86_64-unknown-linux-gnu -p daoseeker-scope-ffi --lib -- --test-threads=1 | 10项Rust FFI测试通过，RUSTFLAGS=-Zsanitizer=address，ASAN_OPTIONS=detect_leaks=1:halt_on_error=1；本次未发现ASan错误 |
| fuzz-smoke / 113607980619 | 固定cargo-fuzz0.13.2；fuzz workspace fmt/check及以下3个libFuzzer命令 | 全通过，实际有覆盖反馈 |

ASan覆盖Rust测试调用ABI，不声称C例子的C代码也经ASan插桩。普通C编译/调用在三个desktop job独立通过。Miri和ASan结果不保证任意无效调用方指针安全。

```sh
cargo +nightly-2026-10-08 fuzz run snapshot_json -- -max_total_time=60 -max_len=1048577 -rss_limit_mb=512
cargo +nightly-2026-10-08 fuzz run dmi_text -- -max_total_time=60 -max_len=8192 -rss_limit_mb=512
cargo +nightly-2026-10-08 fuzz run cli_args -- -max_total_time=60 -max_len=8192 -rss_limit_mb=512
```

| 目标 | libFuzzer实际runs / 时间 | 最终cov / ft | 最终RSS（libFuzzer报告） |
|---|---|---|---|
| snapshot_json | 1,919,805 / 61秒 | 4270 / 9751 | 302Mb |
| dmi_text | 21,867,756 / 61秒 | 149 / 480 | 307Mb |
| cli_args | 20,656,957 / 61秒 | 145 / 249 | 350Mb |

全部正常结束，无崩溃或超限终止。cov/ft是本次插桩计数，不是源代码覆盖百分比；60秒smoke不证明长期安全。RSS包含libFuzzer开销，512Mb是终止门限而非硬沙箱。CI变异后的corpus未单独上传；随机过程的次数/计数不能保证逐次复现。

## 证据、变更与限制

[CI元数据](evidence/ci-run-37864529108.json)保留URL、被测提交、7个job与各步骤结果。原生报告从官方artifact下载，已核验成功/提交/锁哈希并保存仓库；GitHub artifact原保留14天。原始job日志另下载到本地忽略目录target/ci-evidence/37864529108，未提交含runner路径的完整日志。报告不是签名或供应链证明，产物SHA256用于绑定文件。

本轮初始提交82文件/8404行，加入.gitattributes文本LF和忽略开发缓存，清除多余文件尾空行。后续只更新README、验证/交付/发布/能力/fuzz文档及4份JSON证据。8个crate、feature、公共API、版本0.1.0、C ABI1、Snapshot Schema1及Cargo.lock均未变化；没有新增依赖或许可证变化。证据归档提交使用[skip ci]，避免仅文档变更重复运行相同源码；上述结果始终绑定a0acc06。本轮未重跑benchmark，已有Windows性能结果仍见[性能基线](benchmarks.md)。没有发布crate、release或安装制品。

归档后实际检查：全部文档40个本地链接存在，4份新增JSON可解析，git diff --check通过；三个原生报告成功状态、被测提交和锁哈希再次比对通过。此处文档检查不替代上述CI源码测试。

保留的警告：固定nightly上AtomicUsize::fetch_update有改名弃用提示，为兼容stable1.96暂保留；stable Clippy门禁零警告。checkout/upload-artifact固定旧action提交，CI提示Node20已弃用并强制Node24运行；本次通过不等于未来兼容承诺。ubuntu-latest提示10月19起迁移Ubuntu26，macOS有容量提示；当前runner镜像已在上表记录，发布前需单独维护固定runner/action路线并重验。

未执行：Linux受限容器/真实DMI权限场景、更多发行版、macOS Intel、Windows32/ARM64、长期fuzz、C侧sanitizer、Valgrind、驻留/峰值分配profiling、cargo package/发行制品回滚。维护者ADR/Schema正式发布评审仍待完成。阻塞OS调用无法强杀、静态失败字段缓存、sysinfo内部资源/错误限制仍是已知约束。

下一独立切片：Linux容器/DMI缺失/权限降级原生测试与CI环境维护，之后再选有界电池/hwmon或存储/网络增强。移动、Web、no_std、MCU保持独立后续路线，不属于此次支持声明。

2026-10-10后续：[内存/uptime与最新CI验收](memory-refresh-validation.md)，源码6d0a377、运行38008554490，8/8任务成功；Linux54、Windows/macOS53项Rust测试+各1doctest及20项Python守卫，26项内存/uptime、15项CPU和7个原容器场景通过。本文首次CI计数是历史记录，不覆盖后续实现变化。

2026-10-10后续：[procfs独立fuzz验收](procfs-fuzz-validation.md)，源码4eb7e971、运行38044730604，8/8任务成功。Linux57、Windows/macOS56项Rust测试+各1doctest及20项Python守卫；原生CLI/C/Python、Schema、Miri8、Rust FFI ASan10、审计及7/15/26个容器场景/观测通过。六个libFuzzer目标各60秒正常结束，新cpu_stat/meminfo/uptime分别1,263,006/4,324,530/19,206,072次输入执行；新增默认关闭的Linux内部fuzzing feature和25个种子，不改变默认采集、ABI1/Schema1/锁/许可证。完整/proc探针仍not_run；未执行长期campaign或新benchmark。

2026-10-10后续：[Linux电池验收](battery-validation.md)，修复源码15ef5c1、CI38047435339全部8任务成功。Linux66/Windows64/macOS65项Rust测试+各1doctest及26项Python守卫；Miri8、Rust FFI ASan10、审计、Schema/原生CLI/C/Python和七个60秒fuzz通过。电池30观测、既有26/15/7观测或场景通过，完整/proc仍not_run；原生Linux电池Available空集合，Windows runnerNotApplicable，macOSUnsupported。初版CI38047029198控制器权限恢复失败及修复证据保留，未证明真实Linux笔记本电池可读。ABI1/Schema1/feature集合/锁/许可证不变，Schema仅增加description元数据。

## 2026-10-11：hwmon最终源码验证

最终源码0fbc84ae445c9c2f717ac29c12da0a2bc512c4bf的[运行38065295625](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38065295625)8任务全部success，UTC2026-10-10 15:51:24–16:01:17。三平台门禁/CLI/C/Python、Miri8、Rust FFI ASan10、供应链以及八fuzz完成标记已从实际日志核验；Linux73/Windows70/macOS72项Rust各+1doctest、各31项Python守卫。新增36个非root hwmon观测通过，原电池30/内存26/CPU15/容器7场景保持通过。完整/proc覆盖仍为运行时拒绝/not_run。

最终原生Linux sensors为Available空集合、Windows/macOS Unsupported；并非实际温度读取成功。前一backend源码3c04fd3的CI38064696284也8/8通过，获分配的不同Linux runner为1个Unsupported温度条目。最终字段状态、任务ID、日志/种子哈希及11份持久JSON见[hwmon验收](hwmon-validation.md)与[元数据](evidence/ci-run-38065295625.json)；不把旧源码日志移到新源码名下。

## 2026-10-11：NVMe hwmon增量验收

源码9931cf9的[CI38067341915](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38067341915)八任务success。Linux仅增加nvme通道1..9路由，零Kelvin不发布为温度，Composite是设备报告计算值；默认标签/标识采集边界不变。71项本机Rust+1doctest、fmt/clippy/doc/no-default-features/build/cross check、八harness fmt/check/clippy、32项Python守卫/修改脚本Ruff/mypy、Schema/actionlint、C重建与CLI/C/Python实际调用通过。CI Linux74/Windows71/macOS73项Rust各+1doctest、12份Python静态检查/32守卫、Miri8、Rust FFI ASan10、审计和八个60秒fuzz通过；47项hwmon（11项NVMe）、30电池/26内存/15CPU/7容器通过，完整proc替换仍not_run。属性hwmon fuzz 35,010,619次/61秒正常结束。

11份源码绑定JSON、任务ID/日志和12种子哈希见[NVMe验收](nvme-temperature-validation.md)。原生Linux无传感器条目，Windows/macOS Unsupported，未验证真实NVMe温度、校准、新benchmark、长期fuzz或打包/发布。公共稳定模型/签名、0.1.0、ABI1/Schema1、feature集合、锁与MIT OR Apache-2.0不变，仅Schema说明元数据及默认关闭隐藏fuzz hook增加；后续真实设备验收与性能/打包门禁独立推进。
