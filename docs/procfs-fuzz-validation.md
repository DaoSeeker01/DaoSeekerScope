# procfs 解析器独立 fuzz 验收（2026-10-10）

2026-10-26 Linux SDK 轮次回归：源码 `af312da` 的[CI 40304816716](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40304816716)重跑 12 个既有目标，每个至少 60 秒，4 项 harness 通过；未修改解析器、目标或 fuzz features。实际次数/日志哈希见[索引](evidence/linux-ffi-sdk-ci-40304816716.json)，不是长期 fuzz 或完整内存证明。

2026-10-26 Windows SDK 轮次回归：源码 `ba11807` 的[CI 40249181949](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40249181949)重跑 12 个现有目标，每个至少 60 秒、4 项 harness 通过；未改解析器、目标或 fuzz features。实际次数与日志哈希见[索引](evidence/windows-ffi-sdk-ci-40249181949.json)，不作为长期 fuzz 或完整内存证明。

2026-10-26 Linux CLI 制品轮次回归：源码 `98172d0` 的[CI 40245533279](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40245533279)全部 12 个现有目标各至少 60 秒、4 项 harness 通过，没有修改解析器、种子或 fuzz features。实际次数与日志哈希见[索引](evidence/linux-cli-bundle-ci-40245533279.json)；不作为长期 campaign 或完整泄漏/峰值内存证明。

2026-10-25 回归：源码 `2d0a8a1` 的[CI 40183166615](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40183166615)完成全部 12 个现有 fuzz 目标，每个至少 60 秒，4 项 harness 守卫通过；没有新增/修改解析器、种子或 fuzz feature。逐目标实际计数与日志哈希见[本轮索引](evidence/windows-cli-bundle-ci-40183166615.json)。这仍是短 campaign，不代表长期 fuzz 或完整内存证明。以下许可证/API 描述属于各自历史日期；当前项目采用 MIT。

本切片为已实现的Linux CPU、内存、uptime解析器增加独立覆盖反馈fuzz；没有修改默认采集行为或增加设备类别。入口与输入格式见[ADR0006](adr/0006-procfs-fuzz-hooks.md)。CPU有界read_line/observe与内存/uptime parse函数均为真实backend使用的实现，没有复制另一套解析逻辑。此前26项内存/uptime、15项CPU内核故障注入证据仍见[内存刷新验收](memory-refresh-validation.md)。

## 修改与兼容性

Linux crate新增默认关闭的内部`fuzzing` feature、隐藏模块三个函数cpu_stat/meminfo/uptime，及三项确定性测试；CPU/内存模块只增加feature门控的测试入口。标准Hardware/Backend/Observed契约、主门面feature、ABI1、SnapshotSchema1、0.1.0不变；内部入口不作为稳定消费者API。没有新增crate、unsafe或第三方依赖，两份Cargo.lock与MIT OR Apache-2.0许可证不变。

fuzz/Cargo.toml启用Linux内部feature，新增三个harness和共享观测断言；25个合成种子覆盖合法/0/最大整数、溢出、UTF-8、超长、错误单位、缺项/重复、快速刷新、计数回退、guest/iowait和合成IO失败。CPU每次任意序列后检查失败清基线和新采样对、50/0/100%区分；内存检查KiB换算/total与available关系、坏字段隔离和重复键；uptime检查小数截断/真实0/最大u64/附加字段拒绝。循环次数、时间步长、输出集合与格式化长度有界，不读取设备或敏感数据。

CI fuzz-smoke扩展至六个目标；原三个目标命令保留，新三个各60秒、固定seed20261010、单输入2秒timeout、RSS终止门限512MiB，max_len分别8192/8192/512。job整体15分钟；pipefail保留实际fuzzer失败退出，日志及存在的失败reproducer always上传14天。不会把忽略的fuzz退出码或空日志当通过。已核验本次产物、步骤退出结果和正常完成标记。

## 可复现命令

```sh
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features -- --test-threads=1
cargo test --locked -p daoseeker-scope-linux --no-default-features -- --test-threads=1
cargo fmt --manifest-path fuzz/Cargo.toml --check
cargo check --locked --manifest-path fuzz/Cargo.toml
cargo clippy --locked --manifest-path fuzz/Cargo.toml --all-targets -- -D warnings
rustup toolchain install nightly-2026-10-08 --profile minimal
cargo +nightly-2026-10-08 install cargo-fuzz --version 0.13.2 --locked
cargo +nightly-2026-10-08 fuzz run cpu_stat -- -seed=20261010 -max_total_time=60 -max_len=8192 -timeout=2 -rss_limit_mb=512
cargo +nightly-2026-10-08 fuzz run meminfo -- -seed=20261010 -max_total_time=60 -max_len=8192 -timeout=2 -rss_limit_mb=512
cargo +nightly-2026-10-08 fuzz run uptime -- -seed=20261010 -max_total_time=60 -max_len=512 -timeout=2 -rss_limit_mb=512
```

本机Windows只编译harness、运行确定性回归和静态门禁，不声称执行libFuzzer。实际campaign在Linux x64 CI运行；平台限制依据[cargo-fuzz官方说明](https://github.com/rust-fuzz/cargo-fuzz#installation)，2026-10-10核验。

早期本地CPU边界测试错误把重复'x'首字节作为控制字节，返回合成NotPresent而不是超长InvalidData；已将首字节明确设为读取控制2，保留超长断言并重跑整套Rust门禁。这是测试输入格式修正，没有修改生产解析器或降低门禁。

## 执行结果

六个harness在Windows稳定工具链1.96.0实际check/clippy/fmt通过，默认关闭feature的Linux crate20项测试通过（fuzz hooks测试因feature关闭运行0项）。本机完整scripts/check.ps1 -Cross重跑通过：fmt、clippy -D warnings、56项Rust测试+1doctest、core/门面no-default-features、doc -D warnings、CLI/FFI build及Linux/macOS交叉类型检查。actionlint1.7.12通过（shellcheck/pyflakes未启用）。

被测源码`4eb7e971cb43e8996487feed98c7de039a147ade`，[运行38044730604](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38044730604)全部8个任务成功。UTC2026-10-10 10:23:30–10:31:49（北京时间18:23:30–18:31:49）。下表计数由实际任务日志核验，未用文档推断代替执行。

| job / ID | 实际结果 |
|---|---|
| desktop Linux / 114191852094 | Rust1.96.0：57项Rust测试+1doctest、20项Python守卫；fmt/clippy/doc/no-default-features/build、Schema、Ruff/mypy及原生CLI/C/Python100次collect/free通过 |
| desktop Windows / 114191852123 | 同上，56项Rust测试+1doctest、20项Python守卫；Windows C例子编译/调用通过 |
| desktop macOS arm64 / 114191852128 | 同上，56项Rust测试+1doctest、20项Python守卫；macOS C例子编译/调用通过 |
| linux-container / 114191852176 | 7个原降级场景、15个CPU观测、26个内存/uptime观测全部passed；过程退出0，默认隐私及字段状态检查通过 |
| miri / 114191852001 | 固定nightly执行FFI `memory_contracts` 8项；不是解释执行全部OS采集 |
| ffi-asan / 114191852099 | 固定nightly、`-Zbuild-std`、address sanitizer及泄漏检查，10项Rust FFI测试通过；未对C例子插桩 |
| supply-chain / 114191852126 | cargo-deny0.20.2，advisories/bans/licenses/sources通过；既有syn重复版本警告保留 |
| fuzz-smoke / 114191852163 | 固定nightly与cargo-fuzz0.13.2，六个独立libFuzzer目标正常结束；新增目标步骤10/11/12均success |

三平台构建/文档和实际读取已分别执行，不把本机交叉类型检查当作原生运行。完整/proc替换探针仍在OCI挂载阶段被拒绝，进程未启动、`not_run`；没有因整个job成功而改成backend通过。原生字段与隐私观测见下列JSON报告，容器输入的硬件名称与CPU/内存数字是合成fixture。

| 目标 | runs / 实际时间 | 最终cov / ft | 最终RSS |
|---|---|---|---|
| snapshot_json | 2,009,513 / 61秒 | 4243 / 9543 | 351Mb |
| dmi_text | 19,959,199 / 61秒 | 152 / 535 | 337Mb |
| cli_args | 18,868,701 / 61秒 | 144 / 248 | 372Mb |
| cpu_stat | 1,263,006 / 61秒 | 201 / 803 | 410Mb |
| meminfo | 4,324,530 / 61秒 | 247 / 978 | 296Mb |
| uptime | 19,206,072 / 61秒 | 148 / 413 | 293Mb |

`cov/ft`是插桩反馈计数，不是源代码覆盖百分比。新三个目标的日志有seed20261010、DONE和Done完成标记，与成功步骤相互核验；上传产物只有三个日志，没有崩溃reproducer。25个初始种子的字节长度及SHA256与被测Git对象比对一致。CPU最终libFuzzer增长限额7134不是配置max_len8192，两个数字在证据中分别记录。没有发现新的生产解析器回归；有限执行不能证明没有缺陷。

归档8份JSON：[运行元数据](evidence/ci-run-38044730604.json)、[新fuzz汇总](evidence/procfs-fuzz-38044730604.json)、[Linux原生](evidence/linux-native-38044730604.json)、[Windows原生](evidence/windows-native-38044730604.json)、[macOS原生](evidence/macos-native-38044730604.json)、[容器降级](evidence/linux-container-38044730604.json)、[CPU动态](evidence/linux-dynamic-38044730604.json)、[内存/uptime动态](evidence/linux-memory-38044730604.json)。六份采集报告均核验overall=passed、被测提交、git_dirty=false和Cargo.lock哈希；fuzz汇总保存命令、种子、日志SHA256与反馈统计。原始日志保留于本地忽略目录target/ci-evidence/38044730604，未把完整runner日志提交仓库。GitHub产物保留14天，归档汇总不是签名或供应链认证。

推送首次TLS握手失败、完整日志下载和部分单任务下载出现EOF；在不改变TLS校验的情况下重试推送、逐任务下载后全部取得并核验。watch因网络EOF退出，最终运行元数据和步骤结果才是CI结论。这些是基础设施读取失败，没有被记为backend失败或测试通过。

本次源码提交40个文件（含25个种子），后续仅更新README、fuzz README、验收/交付文档和证据，以`[skip ci]`归档；不把归档提交当成新源码验证。依赖锁、库版本、ABI和Schema不变，增加的隐藏测试feature见上文，尚未发布。

## 未验证范围

60秒smoke不能证明无漏洞/全覆盖/长期稳定；RSS读数包含libFuzzer和ASan开销，终止门限不是硬内存沙箱或采集库benchmark。CPU的合成时钟/IO标志不验证真实内核权限、OS读取硬取消、并发或调度；MemTotal缓存和热插拔不在这三个parser harness内。生成corpus不保证逐次复现，失败必须保留并重放具体输入。没有执行新平台、长期campaign、benchmark、峰值分配profiling、打包或发布。下一独立功能可进入Linux电池受控枚举，继续按字段记录来源、权限和隐私。

归档检查：8份新增JSON可解析，76个本地文档链接存在；全部测试计数与日志一致，git diff --check通过。被测提交之后源码/工作流/绑定/脚本/测试/种子及两份锁均无差异；仅文档与证据增量无需重复相同源码门禁。
