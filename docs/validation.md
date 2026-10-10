# 2026-10-08 验证记录（Asia/Shanghai）

本文保留各轮执行时的历史状态。最新三平台原生、Miri、ASan、供应链及fuzz结果见[2026-10-09 CI验收](ci-validation.md)，此前“未执行”条目不代表当前状态。

环境：Microsoft Windows 10.0.26300，x86_64，CPU 主机读取 Intel Core i7-9750H（12逻辑/6物理），安装内存17,179,869,184字节。Rust/Cargo 1.96.0，MSVC14.51.36231，Windows SDK10.0.28000.0。命令由固定 mise 环境执行；构建目录 target，最终完整门禁使用普通主机权限、CARGO_INCREMENTAL=0、RUSTDOCFLAGS=-D warnings。

| 检查 | 实际结果 |
|---|---|
| Phase0 docs/research/probe cargo run | Windows CPU/memory/OS真实读取成功；OS可用总内存17,009,004,544字节 |
| cargo fmt --all --check | 通过 |
| cargo clippy --locked --workspace --all-targets --all-features -- -D warnings | 通过，零代码警告 |
| cargo test --locked --workspace --all-features -- --test-threads=1 | 26项测试 + 1项doctest全部通过 |
| core / 门面 cargo check --no-default-features | 通过 |
| cargo doc --locked --workspace --all-features --no-deps | 通过，RUSTDOCFLAGS=-D warnings |
| cargo build --locked -p daoseeker-scope-ffi -p daoseeker-scope-cli | Windows原生链接通过 |
| cargo check --locked --workspace --all-features --target x86_64-unknown-linux-gnu | 通过（仅交叉类型检查） |
| 同上 --target aarch64-apple-darwin | 通过（仅交叉类型检查） |
| python examples/collect.py target/debug/daoseeker_scope_ffi.dll | 100次真实collect/free、默认隐私、错误副本拒绝通过 |
| scripts/build_c_example.ps1 | MSVC /W4 /WX 编译通过，真实调用/释放/清零/陈旧副本拒绝通过 |
| uv run --no-project --with jsonschema==4.25.1 python scripts/check_schema.py target/real-snapshot.json | Schema自身、黄金样例、生成漂移、负面观测状态、未知字段、版本、实时JSON通过 |
| .tools/bin/cargo-deny.exe check（0.20.2） | advisories/bans/licenses/sources通过；一项syn2/3重复版本警告，未忽略漏洞 |
| cargo bench --locked -p daoseeker-scope --bench collect | 实测 + 100传感器/1024网络条目合成压力完成，见benchmarks |
| cargo check --locked --manifest-path fuzz/Cargo.toml | 两个fuzz harness在Windows编译通过；没有campaign/coverage/sanitizer证据 |

所有最终检查由 scripts/check.ps1 遇错即停运行。早期失败及处理：测试曾错误断言所有冲突总数等于CPU冲突数，已改为按字段计数；Schema生成器曾误写anyOf:null，已修复并经元Schema验证；Clippy发现样式/unsafe注释位置问题，已修复；一次沙箱doctest无法写临时exe，不能算门禁通过，最终在普通主机权限整套重跑通过；PowerShell函数曾吞掉--，已改为显式数组转发。构建缓存在沙箱中曾报告hard-link回退复制，最终关闭增量缓存后检查无此警告。

权限证据：沙箱实际安装内存返回Restricted/PermissionDenied、value=null，电池可读100%/AC=true；普通主机权限安装内存返回Available/17,179,869,184。这是两种执行权限下的直接API结果，不推断所有Windows设备/沙箱都相同。sysinfo对内存/CPU失败没有结构化错误，因此能力Partial，未猜测权限原因。

负面/契约测试覆盖：缺失/占位/损坏UTF-8/超长DMI、DMI缺失、权限与不存在区分、状态反序列化不变量、Schema版本、异常百分比/NaN/超大数组、静态缓存/动态刷新、同级/跨级优先级、缺失增强回退、自定义backend、隐私出口、panic隔离、超时/取消/Busy、FFI重复/篡改/空释放、64buffer上限与注册表恢复、线程局部错误、初次构造资源不足后可重试、CLI退出码/默认脱敏/高级敏感警告。最终审阅发现FFI曾永久缓存构造错误，已改为只缓存成功Hardware并增加回归测试。

首次交付时尚未执行：Linux/macOS原生链接与运行、原生容器/WSL/沙盒验证、长期libFuzzer campaign、ASan/Miri/Valgrind、驻留/峰值分配profiling、macOS Intel、Windows32/ARM64、release制品验签/打包/发布。GitHub CI文件已写但未执行；查询目标仓库404不等同证明全局不存在。静态失败字段缓存、sysinfo不可硬取消和内部集合分配不能由本库严格限制仍是正式发布限制。

## 2026-10-09 输入/FFI增量验证

当前代码完整check.ps1 -Cross通过37项测试+1项doctest，fmt/clippy/doc/no-default-features/build与两平台交叉检查通过；固定Miri执行8项纯内存契约通过。Windows C、Python100次实际调用及实时Schema复验通过。Miri发现原Box导出指针后移动所有者导致别名失效，已改Arc并验证；先前普通测试通过不足以排除此问题。

新增512个JSON变异、512个DMI样本、4096个CLI组合、256种重复字节参数及Windows非法UTF-16参数测试；fuzz三个harness仅编译。nightly弃用提示、失败运行及恢复、ASan/原生平台待验清单见 [完整增量记录](input-ffi-validation.md)。此轮未重跑benchmark、未执行远端CI或libFuzzer campaign。

## 2026-10-09 原生证据入口

新增原生smoke脚本与4项守卫测试，Ruff格式/lint、mypy、actionlint语义检查通过。Windows CLI/C/Python100次真实调用、Schema、默认隐私和最小读取通过；缺失产物实测返回1、failed/not_run。结果保留于docs/evidence/windows-native-2026-10-09.json。Rust代码未改，本轮未重跑完整Rust门禁/Miri/fuzz/benchmark。目标仓库仍无法解析，WSL服务仍禁用，未执行Linux/macOS或远端CI。详见 [原生验收记录](native-validation.md)。

## 2026-10-09 私有仓库与三平台CI

用户明确授权创建私有DaoSeeker01/DaoSeekerScope并推送、执行CI。被测提交a0acc060381fc3e9a68eb1ff48a8f5c379f92058，运行37864529108，7个job全部success。Windows x64、Linux x64、macOS arm64分别fmt/clippy/test/doc/no-default-features/build、Schema及原生CLI/C/Python通过；各37项Rust测试+1doctest及4项Python守卫。Miri8项、Rust FFI ASan10项、供应链审计及3个60秒fuzz目标通过。完整命令、实际字段、保留报告和未验证范围见[CI验收](ci-validation.md)。本轮未重跑benchmark，未发布任何crate或release。

## 2026-10-10 归档：Linux容器与CI复验

实际运行日期2026-10-09，被测源码8e0e7d941c876f7d3a0a951772912acb0ceedefd，运行37867335002全部8个job success。新增非root、只读、断网、资源受限的Ubuntu24.04/Docker28.0.4 x86_64验收：可读/缺失/权限拒绝/损坏DMI、授权serial/serial拒绝、空proc输入共7个production CLI场景passed。DMI是合成Fixture，chmod拒绝是内核真实权限结果；默认隐私及字段隔离均检查。完整/proc覆盖额外探针被OCI挂载阶段拒绝、进程未启动、not_run，不能算作backend成功。

三平台原生门禁重跑通过各37项Rust测试+1doctest、12项Python守卫、Schema与CLI/C/Python；Miri8项、Rust FFI ASan10项、cargo-deny及三个60秒fuzz通过。完整文件/命令/读值、失败尝试、哈希和5份归档报告见[最新验收](linux-container-validation.md)。归档提交仅文档/证据，未重新执行相同源码门禁；未重跑benchmark。公共API、feature、运行依赖及许可证、ABI1、Schema1不变。未验证完全缺失procfs、其他安全策略或动态源中途失效；长期fuzz、分配profiling、打包与发布仍未完成。

## 2026-10-10 Linux CPU刷新与恢复

旧源码448dd81在真实非root容器中复现/proc/stat变空后仍Available/50%并打新时间。修复将Linux CPU使用率移至LinuxBackend直接procfs两样本采集，读取失败清基线，恢复首读暂不可用；sysinfo在Linux不再提供该字段fallback。源码3ec5f6e容器15个连续观测与原7个DMI/proc场景通过。Linux单独SysinfoBackend消费者需注册LinuxBackend或使用门面，公共签名、feature、运行依赖、ABI1及Schema1不变。详情与失败/成功原始报告见[CPU刷新验收](cpu-refresh-validation.md)。本地主机44项Rust测试+1doctest、fmt/clippy/doc/no-default-features/交叉检查、16项Python守卫、Schema和actionlint通过；最终CI结论见该报告。没有重复benchmark或声称所有动态字段已保证新鲜度。

## 2026-10-10 Linux 内存与 uptime 刷新

源码6d0a377的运行38008554490全部8个job成功。本地主机53项Rust测试+1doctest、fmt/clippy/doc/no-default-features/build/交叉检查，8份Python检查与20守卫、Schema/actionlint通过；CI Linux54、Windows/macOS53项Rust测试+各1doctest，原生CLI/C/Python100次collect/free、Miri8、Rust FFI ASan10、审计及既有3个60秒fuzz通过。非root容器26项内存/uptime、15项CPU及原7场景通过，完整/proc探针仍not_run。旧源码64e65c0先复现缓存内存与静默uptime回退并按预期失败；报告保留于[内存刷新验收](memory-refresh-validation.md)。Linux直接Procfs、总量缓存/变化检测、移除sysinfo fallback；公共签名/feature/运行依赖/许可证/ABI1/Schema1不变，单独Linux sysinfo消费者需补LinuxBackend。新解析器未执行libFuzzer，未重跑benchmark/峰值profiling/打包/发布。

## 2026-10-10 procfs独立fuzz

源码4eb7e971的运行38044730604全部8任务成功，详细命令/计数/8份证据见[验收](procfs-fuzz-validation.md)。本机check.ps1 -Cross与六个harness的fmt/check/clippy通过；CI Linux57、Windows/macOS56项Rust测试+各1doctest、20项Python守卫、Schema/原生CLI/C/Python、Miri8、ASan10和审计通过。CPU/内存/uptime三个新目标与原三个各60秒覆盖反馈执行正常结束；新目标25个种子和日志完成标记/哈希已核验。默认关闭的Linux内部fuzzing feature复用生产解析器，未改默认采集、运行依赖/许可证、ABI1或Schema1。此前记录中的“未执行新解析器libFuzzer”保留为历史状态；本次不声称长期fuzz、真实OS硬取消或性能验收。7个原容器场景、15/26个动态观测仍通过，完整/proc探针仍not_run。

## 2026-10-10 Linux电池

源码15ef5c1的CI38047435339全部8任务success；Linux66、Windows64、macOS65项Rust测试+各1doctest及26项Python守卫，全部格式/Clippy/类型/文档/no-default-features/原生build、Schema、CLI/C/Python、Miri8、Rust FFI ASan10与审计通过。电池30观测、既有26内存/uptime/15CPU/7容器场景均passed；完整/proc额外探针仍not_run。七个各60秒fuzz正常结束，新power_supply执行19,744,677次，无崩溃。初版控制器恢复文件权限失败保留，未记为backend回归或整切片成功。12份原生/容器/运行/fuzz/失败证据与实际命令见[电池验收](battery-validation.md)。

新功能Linux能力Partial，SourceSysfs，128字节属性/256设备/调用方电池上限，不能以USB充电推断AC；原生Linux仅验证无条目，真实Linux电池设备、更多权限环境、OS硬取消、长期fuzz、benchmark/峰值profiling和发布未验。ABI1/Schema1、依赖/许可证与feature集合不变，Schema仅补说明元数据。

## 2026-10-11：hwmon温度切片归档

LinuxBackend实现Partial/SourceHwmon的动态温度枚举，仅路由coretemp与k10temp的Tdie；其他单位/驱动保持Unsupported，标签默认不采集。最终源码0fbc84a的CI38065295625八任务成功、36项合成输入/实际内核权限和恢复观测通过；最终Linux原生无条目，Windows/macOS Unsupported。未验证真实温度、数值文本的真机路径、新benchmark、长期fuzz或发行制品。测试计数、资源边界、失败准备阶段与11份源码绑定证据见[独立hwmon报告](hwmon-validation.md)；公共模型/签名、ABI1/Schema1、feature及锁不变。

## 2026-10-11：NVMe hwmon增量验收

源码9931cf9的[CI38067341915](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38067341915)八任务success。Linux仅增加nvme通道1..9路由，零Kelvin不发布为温度，Composite是设备报告计算值；默认标签/标识采集边界不变。71项本机Rust+1doctest、fmt/clippy/doc/no-default-features/build/cross check、八harness fmt/check/clippy、32项Python守卫/修改脚本Ruff/mypy、Schema/actionlint、C重建与CLI/C/Python实际调用通过。CI Linux74/Windows71/macOS73项Rust各+1doctest、12份Python静态检查/32守卫、Miri8、Rust FFI ASan10、审计和八个60秒fuzz通过；47项hwmon（11项NVMe）、30电池/26内存/15CPU/7容器通过，完整proc替换仍not_run。属性hwmon fuzz 35,010,619次/61秒正常结束。

11份源码绑定JSON、任务ID/日志和12种子哈希见[NVMe验收](nvme-temperature-validation.md)。原生Linux无传感器条目，Windows/macOS Unsupported，未验证真实NVMe温度、校准、新benchmark、长期fuzz或打包/发布。公共稳定模型/签名、0.1.0、ABI1/Schema1、feature集合、锁与MIT OR Apache-2.0不变，仅Schema说明元数据及默认关闭隐藏fuzz hook增加；后续真实设备验收与性能/打包门禁独立推进。
