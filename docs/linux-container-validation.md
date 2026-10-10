# Linux容器与文件系统降级验收（2026-10-09，Asia/Shanghai）

此独立切片增加真实CLI的Linux容器负面验收，不新增硬件字段、Rust公共API或运行依赖。原Linux backend及sysinfo适配代码不变，0.1.0、C ABI1、Snapshot Schema1、Cargo.lock和feature保持不变。[运行37867335002](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/37867335002)已完成，8个job全部success，7个backend容器场景全部passed。实际运行日期为2026-10-09，证据于2026-10-10归档；此前证据保留于[首次CI](ci-validation.md)。

## 实施与边界

新增scripts/linux_container_smoke.py，通过Docker运行已构建的production dscope，以只读bind覆盖其固定/sys路径，必要时覆盖/proc。DMI输入全部是明确的合成Fixture，CPU/内存来自容器可见OS；不把Fixture内容宣称为真实主板/固件信息，也不读主机真实序列号。没有公开可重定向生产backend的路径选项，没有启动本机Docker/WSL服务。

| 场景 | 真实内核/进程操作 | 验收要求 |
|---|---|---|
| readable_dmi | 6个普通可读Fixture文件 | Available/sysfs及正确Fixture值；能力Supported |
| missing_dmi | /sys覆盖为空目录 | 6字段Unavailable/NotPresent；能力仍Supported且携带原因，不冒充Unsupported |
| denied_dmi | DMI目录chmod000；CLI为非root | 6字段Restricted/PermissionDenied；对应能力Restricted |
| mixed_dmi | 非法UTF-8、chmod000文件、缺失文件、OEM占位、4097字节文件与可读字段混合 | 分字段InvalidData/PermissionDenied/NotPresent，可读board_vendor仍成功，快照不整体失败 |
| authorized_serial | 显式--include-sensitive --authorized，只读合成serial | 值必须与合成Fixture匹配；证据不保存该值 |
| denied_serial | 同样显式授权，但合成serial文件chmod000 | Restricted/PermissionDenied，授权不能绕过OS权限 |
| empty_proc_inputs | 额外以空文件覆盖/proc/stat、/proc/cpuinfo、/proc/meminfo，保留运行时所需/proc/self | CPU型号/逻辑数、总内存/可用内存Unavailable/Unknown/null；不接受虚构0或正值；OS名称和DMI仍成功 |

七个backend场景验证JSON Schema、状态/来源/时间/原因、能力语义及CLI实际退出状态，不把docker start命令退出0直接算作CLI成功。默认serial始终Restricted/PrivacyRedacted。字段失败不是进程失败，因此测试要求CLI退出0且提供正确降级快照。使用参数数组启动Docker，不向Shell插入路径或原始输出。

额外empty_proc运行时探针完整覆盖/proc。实际Docker28.0.4在OCI挂载阶段拒绝启动，进程未运行、exit128、固定分类runtime_mount_error。该项单列runtime_probes/status=not_run，绝不算作backend读取成功；实际数据缺失降级由上面的empty_proc_inputs验证。没有为运行探针解除权限限制或开放privileged。此结果不证明库能在完全没有procfs的OS进程环境启动。

容器由Docker配置非root65534:65534，cap-drop ALL、no-new-privileges、只读根与bind、network none，限制256MiB内存/无额外swap、32进程、1 CPU、nofile64。运行前读取docker inspect核对配置，只保留脱敏配置值；不记录bind源路径或容器ID。每个Docker命令最长60秒，finally强制清理本脚本创建的随机名称容器，清理最长15秒；恢复自建Fixture权限便于移除临时目录。未开放privileged、Docker socket或宿主源码/凭据挂载给容器。

这些限制针对测试进程；sysinfo报告的内存/CPU是容器可见系统信息，不能默认解释为cgroup限额。普通只读Fixture不能证明真实sysfs驱动、SELinux/AppArmor规则或所有容器类型一致。Docker daemon本身仍由CI宿主提供；脚本必须在有权限使用该daemon的Linux amd64环境运行。

官方Ubuntu24.04 linux/amd64镜像固定manifest：`ubuntu@sha256:f610ab94648195aa356059f5b41d6085c9d4d903c072430cdd1af7bdb646106b`。2026-10-09从官方registry取得24.04 index `sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55`后确认该平台manifest。运行报告再记录实际image ID；digest固定文件内容，不是签名保证。依据[Docker运行/资源/权限文档](https://docs.docker.com/engine/containers/run/)和[只读bind文档](https://docs.docker.com/engine/storage/bind-mounts/)。

## CI环境维护

同一CI文件新增linux-container job，固定ubuntu-24.04及10分钟job timeout，构建CLI、安装既有jsonschema4.25.1、执行7场景并保留报告14天。既有Linux job也固定ubuntu-24.04，避免ubuntu-latest即将迁移影响本次复现；Windows/macOS标签保留并记录实际镜像。

checkout改为官方v5提交`fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09`，upload-artifact改为官方v6提交`b7c566a772e6b6bfb58ed0dc250532a479d7789f`，官方action.yml均已核验node24，解决首次CI记录的Node20弃用提示。两者仍MIT开发工具；Ubuntu测试镜像包含其各组件许可证，不作为本项目发行制品，不改变Rust依赖许可证。

## 本地实际检查与复现

Windows本机只检查脚本及CI语义，不冒充容器执行：Ruff0.14.13格式/lint、mypy1.19.1 --no-incremental --ignore-missing-imports、12项Python守卫（原4+新增8）、actionlint1.7.12（外部shellcheck/pyflakes未启用）、cargo fmt --all --check、git diff --check均通过。本地实际启动容器脚本返回1/platform: linux_amd64_required，七场景not_run，没有启动Docker/WSL服务。

首次本地增量mypy成功未反映最终提交中的类型问题，CI从干净环境揭示str/None未注解；随后采用独立expected_value:str|None、禁用增量缓存并复查提交内容。第一次CI还有cargo-deny下载HTTP/2 framing错误，改为Cargo HTTP非multiplexing，未关闭TLS验证。后续Docker inspect遗漏Mounts曾导致KeyError/incomplete，已补字段及固定错误分类；复验明确完整/proc覆盖是OCI挂载拒绝，改为保留失败探针并新增可执行的空proc输入场景。被替代的运行保留原结论，后续运行全套门禁重新验证，未弱化状态或退出码检查。

新增tests/test_linux_container_smoke.py覆盖7场景观测语义、错误原因不可互换、健康字段隔离、能力状态、空proc输入伪造值拒绝、serial精确授权/权限、容器资源配置、失败与中断不得复用成功报告。它们是验收脚本的Fixture守卫，不是实际Linux读取证据。完整Rust门禁和容器运行通过推送后的8个CI job执行；本轮不重跑benchmark。该入口采集初始CLI快照，尚未验证采样就绪后或采集中途源消失时的动态刷新。

```sh
cargo build --locked -p daoseeker-scope-cli
python -m pip install jsonschema==4.25.1
python scripts/linux_container_smoke.py
```

从仓库根在Linux x86_64、有Docker daemon的环境执行。可通过--cli指定Linux构建产物、--output指定报告文件；不支持在Windows运行Linux二进制。报告执行前覆盖为incomplete，失败为failed，所有7场景passed才可overall=passed，未执行项保留not_run。报告记录源码commit、CLI/锁SHA256、实际Docker/image与脱敏字段；不是制品签名。超时或清理失败不能宣称成功。

## 最终CI与归档证据

被测源码为`8e0e7d941c876f7d3a0a951772912acb0ceedefd`，UTC 00:56:58开始、01:02:14完成（北京时间2026-10-09 08:56:58–09:02:14）。[CI元数据](evidence/ci-run-37867335002.json)保留8个job、各步骤结论和时间；条件不匹配的其他OS编译步骤为skipped，不冒充执行。文档归档使用[skip ci]，没有把归档提交描述成新一轮源码验证。

| job | ID | 实际结果 |
|---|---|---|
| desktop Windows | 113617084719 | windows-2025-vs2026 / x86_64，37测试+1doctest，CLI/C/Python通过 |
| desktop Linux | 113617084627 | ubuntu-24.04 / x86_64，同上 |
| desktop macOS | 113617084542 | macos-26-arm64 / arm64，同上 |
| linux-container | 113617084533 | Docker28.0.4，7场景passed；完整/proc探针not_run |
| supply-chain | 113617084238 | cargo-deny0.20.2 advisories/bans/licenses/sources通过 |
| miri | 113617084522 | nightly-2026-10-08，8内存契约通过，2个OS测试过滤 |
| ffi-asan | 113617084634 | 同一nightly，10个Rust FFI测试通过，无ASan错误 |
| fuzz-smoke | 113617084555 | cargo-fuzz0.13.2，三个60秒目标正常结束 |

三平台重新执行cargo fmt、clippy -D warnings、workspace全feature test、core/门面no-default-features check、doc -D warnings、CLI/FFI build、Schema检查、C编译及native_smoke。具体Rust/C/ASan/Miri/fuzz命令与[首次门禁](ci-validation.md)相同；Python门禁扩展为四份脚本的Ruff format/check、mypy --no-incremental --ignore-missing-imports和`python -m unittest discover -s tests -p "test_*smoke.py"`，各平台12项全部通过。Python实际版本分别Windows3.12.10、Linux3.12.3、macOS3.14.7。

| 原生CLI读值 | CPU型号 / 实际逻辑数 | OS可用总内存（字节） | 安装内存（字节/来源） | 原始报告 |
|---|---|---|---|---|
| Windows | INTEL(R) XEON(R) PLATINUM 8573C / 2 | 8,584,425,472 | 8,589,934,592 / win32 | [Windows](evidence/ci-windows-x64-37867335002.json) |
| Linux | AMD EPYC 7763 64-Core Processor / 2 | 8,323,960,832 | Unsupported / NotSupported | [Linux](evidence/ci-linux-x64-37867335002.json) |
| macOS | Apple M2 Pro (Virtual) / 5 | 15,032,385,536 | 15,032,385,536 / sysctl | [macOS](evidence/ci-macos-arm64-37867335002.json) |

三个原生报告CLI/C/Python检查全部passed，git_revision一致、git_dirty=false；下载后与本地Cargo.lock SHA256 `e04239561667b4f20152f0fe6b80aaafeb483e7ad8fea41f8c3aaadd76c177a9`再次核对。CPU型号字符串不是runner分配核数或裸机认证。

[容器原始报告](evidence/linux-container-37867335002.json)与Linux原生报告的CLI SHA256均为`7fd7e10a481fdce7ec111cc05bcb37f964bbe3eda7298e9b89a9e1ac87a77dd9`；实际镜像ID为`sha256:69f919497cada9a8611f3de61df902d9f94bf20f84552ef5bd93125c38608ef9`。七场景的实际进程均启动且退出0，完整/proc探针进程未启动、退出128，单列运行时挂载错误。报告已保存在仓库，不依赖14天artifact有效期；合成serial值未写入证据。原始日志只保留本地忽略目录target/ci-evidence/37867335002，报告哈希不是签名。

| fuzz目标 | runs / 实际时间 | 最终cov / ft | 最终RSS |
|---|---|---|---|
| snapshot_json | 1,934,463 / 61秒 | 4228 / 9668 | 322Mb |
| dmi_text | 17,266,736 / 61秒 | 149 / 471 | 264Mb |
| cli_args | 19,322,624 / 61秒 | 145 / 248 | 304Mb |

无崩溃或超限终止。cov/ft不是代码覆盖百分比，RSS包含libFuzzer开销，512Mb为终止门限，变异corpus未单独上传；这些smoke不代替长期campaign。ASan仅插桩Rust FFI测试，不声称C例子也被插桩。stable门禁无代码警告，固定nightly仍报告AtomicUsize::fetch_update弃用提示；cargo-deny保留syn2.0.119/3.0.6重复版本警告。未为消除警告升级工具链或改变生产代码。

被替代运行保留真实结论：37866353767（6ae0b55）failure，揭示干净mypy、HTTP/2下载及完整/proc问题；37866876885（69f4df3）cancelled，发现inspect遗漏Mounts；37867070152（cc59637）cancelled，确认OCI拒绝完整/proc覆盖；最终37867335002（8e0e7d9）success。修复经过全套门禁复验，没有将前次失败改写成成功。

本轮没有改动crate、feature、公共API、运行依赖及许可证、C ABI1或Schema1；修改范围为两个Python文件、CI及文档/证据。未新增移动/Web/no_std/MCU支持，也未打包或发布。仅证实上述Ubuntu24.04/Docker28.0.4 x86_64配置，未验证其他容器、安全策略、完全缺失procfs、动态源中途消失、峰值分配或硬件传感器超时。静态失败缓存与不可强杀阻塞OS调用的既有边界仍适用。

下一独立切片优先验证CPU采样就绪、动态源中途失效及刷新语义，再扩展Linux电池/hwmon；长期fuzz、内存profiling、cargo package与维护者发行评审仍待完成。
