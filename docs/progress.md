# 剩余工作

2026-11-13 修复候选激活时对安装文件的无界读取，源码 `90b1857`。先核对类型和大小，再按预期大小加一字节读取并比较内容。新增两项回归覆盖大小不符时不读取、元数据检查后模拟内容增长，以及失败保留原活动选择。修复前两项失败，修复后本机 Python 375 项通过、6 项跳过；三平台工具 CI、Windows 正常候选安装回滚与 DLL 故障恢复均通过。本轮未执行完整 Rust/fuzz、内存峰值测试或 Linux 原生候选演练。[验收记录](evidence/activation-read-ci-43333156457.json)

2026-11-13 修复候选包空文件校验不一致，源码 `88dcac3`。安装校验与打包器统一拒绝零字节文件，即使归档和载荷哈希匹配，也在创建安装目录前返回 `file_limit`。Windows/Linux 的 CLI/SDK 四种格式通过 33 个空条目场景回归。本机 Python 373 项通过、6 项跳过，三平台工具 CI 全部通过，Windows 正常候选安装回滚和 DLL 故障恢复通过。空文件规则不代替许可正文评审，本轮未重跑完整 Rust/fuzz 矩阵或 Linux 原生候选演练。[验收记录](evidence/empty-bundle-ci-43332120977.json)

2026-11-13 修复 Linux CLI 的 readelf 诊断漏检，源码 `4d7c91a`。stderr 非空或超过 1 MiB 时，在激活和执行候选前失败，原始诊断不写入报告。修复前三项负向检查失败，修复后本机 Python 371 项通过、6 项跳过；三平台工具定向 CI 全部通过，含 Linux 实际 C 共享库/readelf 检查及 Windows 候选回归。本轮未重跑完整 Rust/fuzz 矩阵或 Linux 候选包演练。[验收记录](evidence/elf-stderr-ci-43330982074.json)

2026-11-12 修复 CLI/SDK 候选演练的进程错误处理，源码 `2251884`。启动、超时和退出异常使用脱敏标识，Windows 依赖缺失与无效二进制分别表达。本机与 Windows CI 均通过真实 C 消费者的 DLL 缺失、损坏和恢复，以及 CLI/SDK 安装回滚。新增按需 `candidate-tooling`，本轮三平台任务全部通过，Windows/Linux/macOS 的 Python 分别为 369/372/371 项通过、6/3/4 项跳过。首轮类型检查失败及修复记录已保留；本轮未重跑完整 Rust、ABI/Schema、fuzz 或资源矩阵。[验收报告](evidence/windows-loader-ci-43131273622.json)

2026-11-12 补齐 Core 与主库的编译后公共 API 检查，源码 `57742c2`。默认、关闭默认、仅 serde、schema 共八组接口，在本机 Windows 及 Windows/Linux/macOS 原生 CI 中与同一基线一致。独立真实编译的返回类型变更被拒绝并生成差异；10 项新增回归和本机 Python 362 项通过、6 项跳过。完整 CI 八项任务通过，各平台另通过 8 个源码包与 8 种消费者配置。基线只覆盖两个包的指定配置，最终兼容性评审仍待维护者确认。[验收报告](evidence/public-api-ci-43125279311.json)

2026-11-11 许可预检增加 `--verify-archives`，将缺少材料的包与锁定归档、发布提交和源码位置关联。源码 `afb9955` 的三平台 CI 八项通过，本机 Python 352 项通过、6 项跳过。修复了损坏 Deflate 流中断整份预检的问题，原失败与首轮取消的 CI 单独保留。macOS 原生及本机跨目标均核验六个归档，六项分发材料缺口仍存在。[验收报告](evidence/notice-archive-ci-42938039525.json)

2026-11-11 补齐 Xe 响应解析器 fuzz，源码 `a925ac8`。共用生产解析器，9 份种子及 6,847 次逐字节变异通过。三平台 CI 八项通过；包含 Xe 断言的 `dmi_text` 运行 61 秒、执行 6,799,822 次，全部 12 个 fuzz 目标通过。实体 Xe 和 Linux arm64 原生验证继续延期。[验收报告](evidence/linux-xe-fuzz-ci-42928665649.json)

2026-11-11 归档 Intel Xe 专用显存，源码 `fec8dca`。三平台 CI 八项任务通过，包含 Linux 四项新增测试和非 root 容器 23 项 DRM 场景。各平台通过 8 个源码包与 8 种独立消费者配置。Linux arm64 交叉 Clippy 通过，原生执行待验。实体 Xe 容量读数和二进制响应解析器专门 fuzz 待补齐。[验收报告](evidence/linux-xe-memory-ci-42726746876.json)

2026-11-10 修复 Linux GPU 扫描中设备路径消失时的恢复，并隔离并行 FFI 测试使用的共享缓冲区注册表。源码 `57d2e90` 的三平台 CI 八项任务通过。Ubuntu 原生热拔插模拟与取消用例、非 root 容器 20 项 DRM 场景、本机 8 线程 FFI 复验均通过。实体 GPU 热拔插待验证，Linux 独占显存待实现。[验收报告](evidence/linux-drm-retry-ci-42722683054.json)

2026-11-10 归档 NCT6775 系列温度支持，源码提交 `7be35bf`。完整 CI 的 8 项任务通过。Linux 非 root 容器通过 95 项合成观测，含新增 5 项。三平台源码包验证各通过 8 个归档和 8 种独立消费者配置。12 个短时 fuzz 目标共执行 196,057,051 次。实体 NCT6775 系列设备读数待验证。[验收报告](evidence/linux-nct6775-ci-42598192988.json)

2026-11-09 提交 `ef9d4a1` 补齐 Intel macOS 15.7.9 的 ABI 布局和资源检查。CI 的 Intel 桌面任务通过，另外 5 项按范围跳过。C/Rust 布局符合 ABI 1。120.002 秒完成 763 次采集释放，热身后两次驻留采样相同。描述符回归的缓存计数为 3 到 3，增长对照检出 16 个描述符，缓冲区饱和与恢复通过。两项资源检查使用同一动态库哈希。本机 Windows 契约、Python 340 项通过及 6 项跳过、Ruff、mypy 和 actionlint 已核对。[验收报告](evidence/macos-intel-contract-ci-42594542860.json)

2026-11-09 `macos-intel` 定向 CI 验证提交 `8c1b113`。macOS 15.7.9 x86_64 桌面任务通过，另 5 项任务按范围跳过。通过 8 个源码包、8 种独立消费者配置、304 项包内 Rust 测试、原生 CLI/C/Python、峰值内存和 Mach-O 对照。Python 343 项通过、3 项跳过。冻结 ABI 布局和两项资源检查留待 Intel 专项验收。原生与本机跨目标许可扫描均记录 6 个依赖缺口。[验收报告](evidence/macos-intel-ci-42544368733.json)

2026-11-09 新增 `windows-compat` 手动 CI，提交 `ac9168d`。Windows Server 2022 Datacenter x64（build 20348，镜像 `20261101.353.1`）完成同镜像构建与运行。桌面任务通过，另外 5 项按范围跳过。通过 8 个源码包、8 种独立消费者配置、307 项包内 Rust 测试及 C/Rust 原生契约。Python 340 项通过、6 项跳过。CLI 与 SDK 的系统 PATH 安装、切换和回滚通过，含 9 次 CLI 调用、3 次 C 编译运行和 300 次 Python 采集释放。[验收报告](evidence/windows-server-2022-ci-42542674302.json)

2026-11-09 提交 `f8e1876` 的 Windows CLI 和 SDK 候选通过系统 PATH 演练。CLI 完成 9 次调用，SDK 完成 3 次 C 编译运行和 300 次 Python 采集释放。两份 ZIP 的哈希均已核对。Python 340 项通过、6 项跳过，Ruff 和 mypy 通过。本次主机的 System32 有 `vcruntime140.dll` 14.51.36247.0。全新系统和最低 Windows 版本待验收。[本机报告](evidence/windows-candidate-path-f8e1876-2026-11-09.json)

2026-11-09 修复许可预检和打包对大小写冲突的判断差异，提交 `93b01a2`。Python 338 项通过、6 项跳过，Ruff 和 mypy 通过。干净提交在 Windows 本机完成三目标离线扫描。Windows 与 Linux 满足文件门槛，macOS 的 CLI 和 SDK 各涉及 6 个材料缺口。已核对六个实际 `.crate` 归档与锁文件的哈希，并记录上游发布提交和历史许可来源。[复核报告](evidence/notice-provenance-93b01a2-2026-11-09.json)

2026-11-09 对提交 `ab07073` 运行完整 CI，8 项任务全部通过。Windows、Linux 和 macOS 的源码包内 Rust 测试分别通过 307、299 和 304 项，含 doctest。各平台通过 8 个归档、8 种独立 Rust 消费者配置及原生 C/Rust 契约检查。Windows 与 Linux 的 CLI、SDK 均完成安装、切换和回滚。Linux 用相同归档在固定 glibc 2.34 和 2.36 用户空间运行，2.31 按预期在加载阶段拒绝。12 个短时 fuzz 目标共执行 201,654,833 次。本次 macOS 扫描记录 6 项二进制分发许可材料缺口。[验收报告](evidence/desktop-batch-42537187822.json)

2026-11-09 SDK 候选诊断检查已修复，提交 `165a67f`。C/Python 和 ELF 检查须保持 stderr 为空；编译器允许有界诊断。修复前复现 10 个漏检场景，修复后 12 项 SDK 定向测试与 Ruff/mypy 通过，完整 Python 337 项通过、6 项平台跳过。干净提交的 Windows SDK ZIP 共 78 项载荷，安装、切换与回滚完成 9 次顶层调用，含 3 次 C 编译运行及 300 次 Python 采集/释放。Linux ELF 仅新增子进程负向覆盖，本轮未重跑原生三平台 CI。[验收记录](evidence/sdk-stderr-165a67f-2026-11-09.json)

2026-11-09 CLI 候选诊断检查已修复，提交 `7663843`。此前演练忽略成功退出时的 stderr；现在拒绝非空和超过 1 MiB 的错误输出，只返回固定标识。15 项候选测试、完整 Python 334 项通过，另有 6 项平台跳过；新回归覆盖三个调用阶段的九种负向组合。当前 Windows debug CLI 的版本、JSON 和隔离 JSON 三次实跑通过，Ruff/mypy 通过。本轮未重跑 release 候选安装/回滚或原生三平台 CI，不作为这些验收结果。发布指南也已补齐构建后的两个演练入口。[本机报告](evidence/cli-stderr-7663843-2026-11-09.json)

2026-11-09 发布文档整理完成。[发布指南](release.md)改为当前验收步骤、已验证范围和消费者迁移表，移除重复的逐轮日志及已过时描述，原始验收文档与 Git 历史保留。贡献指南统一完整检查所需的 Python 3.12+；契约表明确 C ABI 无关闭入口、Rust 已有 shutdown。三个工具的帮助入口和项目文件/链接检查通过。本轮只改文档，未重跑 Rust、打包或 CI，不改变已有验收及发布状态。

2026-11-05 错误提示修复已完成本机验收，提交 `f98d4de`。Rust/CLI 说明具体失败原因，超时和取消提示后台工作可能继续；脱敏诊断同时识别新提示与旧候选包文字。307 项 Rust 和 333 项 Python 测试通过，另有 1 项 Rust 夹具忽略直接运行、6 项 Python 平台跳过。实际 CLI 超时返回 3、stdout 为空且正确归类；fmt、Clippy、严格文档、Ruff/mypy、静态契约和双平台交叉 check 通过。原生三平台 CI 留到下批集中回归，未将交叉 check 视为运行验证。[本机报告](evidence/error-messages-f98d4de-2026-11-05.json)

2026-11-05 独立 Rust 消费者检查已完成。源码包验收增加 core/门面各四种 feature 配置，验证实际归档中的自定义 backend、采集、刷新、取消、关闭及可选 JSON/Schema。修复 Cargo stderr 诊断可能污染 stdout JSON 的问题。本机 Python 333 项通过、6 项跳过；三平台 CI 41992365436 的每个平台均通过八种配置和八个源码包。未改变公共 API、依赖、features 或 ABI/Schema。[打包验收](packaging.md)

2026-11-05 Windows 一天试验已完成。冻结提交 `9536d54` 完成 787352 次 C ABI collect/free，实际 86400.072 秒；热身后驻留范围 360 KiB，符合既定 16 MiB 预算。1443 条记录、完成标记、两个退出码、源码和三个二进制哈希已复核。[一天验收](timed-soak-validation.md)

2026-11-05 Windows 电池摘要修复已完成。AC 未知值与非法数值分别返回 TemporarilyUnavailable 和 InvalidData，能力声明改为 Partial。Windows crate 79 项及门面/CLI 48 项测试通过，另有 1 项 CLI 夹具忽略直接运行；本机 SDK 对照为电量 100%、AC 在线。三平台定向 CI 41950968745 为 3 项成功、5 项按范围跳过。[Windows 电池验收](windows-battery-validation.md)

2026-11-04 候选包演练修复已完成。CLI/SDK 在演练前作废旧报告，强制退出回归通过。Windows 本机及 Windows/Linux CI 完成安装、切换和回滚，CLI 各九次调用含三次隔离 JSON，SDK 各三次 C 编译运行与 300 次 Python 采集/释放。本机 Python 330 项通过、6 项跳过，三平台定向 CI 为 3 项成功、5 项按范围跳过。[候选包验收](cli-bundle-validation.md)

2026-11-04 Linux AMD CCD 温度已接入 k10temp。Linux 后端本机 68 项 Rust 测试通过，原生 Linux 非 root 容器 90 项观察通过，新增 4 项覆盖稀疏通道、错误隔离、恢复和移除。修复后的完整 CI 41726560400 八项全部通过。实体 AMD CCD 温度待验。[hwmon 验证](hwmon-validation.md)

2026-11-04 C ABI 饱和验证。真实 C 调用持有 64 个缓冲区，验证第 65 次拒绝、释放后恢复和退役 token 拒绝，并逐字节比较仍持有的 63 个缓冲区。本机及三平台定向 CI 通过。[原生结果](evidence/buffer-limit-ci-41717899173.json)

2026-11-04 扩展 fuzz 验证。现有 12 个目标在四组 Linux CI 任务中各运行 301 秒，共执行 929160798 次。四组全部通过，另外五项任务按运行范围跳过。逐目标次数、实际随机种子和日志哈希已归档。[扩展 fuzz 记录](evidence/extended-fuzz-41714025797.json)

2026-11-04 长时验证批次：定时工具支持最长一天的有界记录、取消标记和直接探针退出确认。14 项定向测试、本机 334 项 Python（328 通过、6 跳过）、三平台目标类型检查与 MSVC 严格编译通过。本机两分钟试验完成 1090 次采集/释放；三平台原生 CI 的完整桌面任务及两分钟试验通过。macOS 首次因 ARM64 runner 容量不足未启动，单作业重试后通过；CI 41666171040 为 3 项通过、5 项按范围跳过，没有重复执行未改动的 Rust fuzz、Miri/ASan、供应链和容器任务。

冻结提交 `9536d54` 的首次一天试验在 6 小时 30 分钟、213384 次调用后中断，缺少完成标记和退出码。[中断记录](evidence/day-soak-interrupted-2026-11-04.json)单独保留，随后完成的一天重试按文首结果验收。停止方法与完整边界见[定时试验](timed-soak-validation.md)。

2026-11-03 CLI 隔离批次：新增可选 `--isolate` 与 `--timeout-ms=N`，超时后终止并确认子进程退出；保留 1 MiB 输出上限、默认脱敏和原有默认运行方式。本机完整 Rust 302 项、八包、契约、静态检查通过，Python 328 项中 322 通过、6 跳过；Release CLI 中文/空格路径三项运行通过。Windows/macOS 原生任务分别通过 302/300 项 Rust；Linux 修复后的定向任务 41660002663 通过 295 项及完整交付检查。每个平台均有 1 项夹具由监督测试单独启动。

两轮完整 CI 各七项成功，Linux 分别因 GLIBC_2.39 加载要求和构建镜像缺少 Git 失败；改用准备好工具的固定 Debian 12 用户空间链接后，CLI 符号要求恢复为 GLIBC_2.34。固定 glibc 2.34/2.36 的隔离采集及 2.31 的预期拒绝通过。代码、命令、失败及原始通过报告见[验收索引](evidence/cli-isolation-acceptance-2026-11-03.json)。库代码与三平台功能测试的源码一致，构建工具另行验收；不合并成“同一最终提交全 CI 通过”。接口与限制见[使用指南](usage.md#在独立进程中采集)，Rust/C ABI 的强终止与卸载仍待处理。

2026-11-02 macOS 制品批次：已实现 Mach-O 头、链接依赖和系统版本声明检查；8 项新增 Python 回归及本机全套通过，提交 `d76e8a9` 的 ARM64 原生 CLI/动态库与 otool/lipo 对照、三平台 CI 41368963038 全部八项通过。六项许可材料缺口不变，未开放 macOS 打包。[范围与复现](macos-binary-validation.md)。

2026-11-02 资源批次：提交 `12fbeff` 增加消费式 Rust `shutdown`，修复 backend 析构期间配额提前释放；本机完整 Rust 292 项与双平台交叉 check、三平台 CI 41367482127 全部八项通过。正常关闭与超时的区别见[资源与超时](usage.md)，C ABI 动态库卸载仍不支持。

2026-11-02 核心批次：提交 `50d220e` 修复缓存/能力提交和响应交付前的最终取消检查；本机 286 项 Rust 门禁与双平台交叉 check、三平台 CI 41365804046 全部八项通过。详见[核心审查](project-review-2026-10-31.md)。阻塞系统调用强终止与 FFI 动态库卸载仍未实现。

2026-11-02 开发批次：新增 JC42、SPD5118、LM75 系列单通道温度；受影响 crate 的 67 项本机 Rust 测试、相关静态检查与 86 项 Linux 原生容器观察通过，含新增 27 项；CI 41364482299 全部八项通过。记录见[hwmon 验证](hwmon-validation.md)。日常按变更运行相关检查，完整跨平台检查在批次交付节点集中执行，不再逐小改动重复归档整套旧报告。

首版交付门槛与近期修复分别见 [v0.1 清单](v0.1-checklist.md)和[核心取消与缓存审查](project-review-2026-10-31.md)。下面保留平台增强工作包，不将它们全部视作首版的必要阻塞项。

截至 2026-11-02：10 项首版验收项中，5 项已有验收依据，4 项部分完成，1 项正式发布未执行。剩余交付工作集中在 macOS 分发、运行范围、最终评审和深入验证；具体条件只在 [v0.1 清单](v0.1-checklist.md)维护，不按代码行数或测试数量计算完成百分比。

2026-11-01 macOS 内置电池（11-02 归档）：电量与供电状态已接入动态刷新；本机门禁、八包和三平台 CI 41294415147 八项任务通过。macOS 原生 CF 合成类型测试及 SDK/CLI/C ABI 空视图通过，实体电池读数仍待验，见[记录](macos-battery-validation.md)。

2026-11-01 Windows 导入符号：普通/延迟名称和序号读取已接入候选检查，本机与 Windows CI 的四个文件 DUMPBIN 对照、两平台候选回归及三平台 CI 41257426560 八项任务通过。静态清单不推断最低 Windows，见[记录](windows-imports-validation.md)。

2026-11-01 许可输入：预检与候选打包现拒绝链接、reparse 项和特殊文件，并在读取前核对身份、在异常时释放句柄。首轮 Unix 类型检查失败保留；修复后的三平台 CI 41254112803 八项任务通过，macOS 原有六项材料缺口不变，见[验收记录](notice-input-validation.md)。

2026-10-31 Linux amdgpu 温度：1–3 号实际通道读取、错误分类和字段隔离已实现，本机完整门禁、八包/契约与三平台 CI 41190519410 八项任务通过；Linux 59 项非 root hwmon 观察含新增 12 项 amdgpu 场景。合成输入不代表真实 GPU 测温，见[验收记录](amdgpu-temperature-validation.md)。

2026-10-31 一小时基线：冻结提交 `b8930ac` 在 Windows 本机完成 32523 次采集/释放，实际采集时长 3600.036 秒；5 分钟热身后 56 个采样点的进程驻留范围为 339968 字节，符合原定 16 MiB 预算，见[记录](timed-soak-validation.md)。该来源早于取消修复；其他平台长时、天级、长期 fuzz 与分配器分析仍未完成。

2026-10-31 核心取消修复：确认并修复静态/动态收集器可能把取消误报为 BackendFailure 的路径，补充三项回归；本机完整门禁、八包、原生契约与两分钟回归，以及三平台 CI 41146601854 八项任务已通过，见[审查记录](project-review-2026-10-31.md)。归档时尚未完成的旧提交 b8930ac 一小时基线已随后单独验收，来源仍与本轮修复分开。

2026-10-30 资源计数：本机及三平台 CI 41036279407 完成 1000 次缓存 collect/free、32 个资源校准与 16 个资源增长对照。有限采样符合事前规则；macOS 仅覆盖描述符编号 0–65535，见[记录](resource-validation.md)。不作为长期无泄漏结论。

2026-10-30 定时缓存采集：本机 600 秒与三平台 CI 120 秒试验完成并通过事前预算，逐分钟记录与退出标记、源码/二进制哈希已核对，见[验收记录](timed-soak-validation.md)。当时未覆盖 FD/句柄；本轮有限计数见上条，小时／天级与 allocator 分析仍待执行。

2026-10-30 许可材料预检：同一依赖闭包与文件发现规则现可一次列出全部缺口，本机与三平台 CI 40973873976 已验收。macOS 六项文件缺口仍阻止分发；具体来源与界限见[预检说明](notice-preflight.md)。

2026-10-29 glibc 2.34 验证：固定 UBI 9 用户空间已运行相同 CLI/SDK/C 消费者，Python 100 次 collect/free、Schema、隐私、实际入口和清理通过；[CI 40854571297](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40854571297)八项任务成功。Debian 2.36 成功与 2.31 拒绝回归保留，不据此建立所有发行版或最低内核保证，见[记录](linux-glibc234-validation.md)。

2026-10-29 发布前契约检查：安装头文件已同步共享库加载期限；本机与[三平台 CI 40807092742](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40807092742)的原生 C/Rust 布局、版本/features/Schema 基线及八包验收通过。已整理[维护者评审表](v0.1-contract-review.md)，V01-08 仍待最终确认；本轮无正式发布。

2026-10-29 固定轮次驻留回归：5000 次缓存 collect/free、60 批合成重建及当前驻留校准通过本机和三平台 CI 40801172470；热身后采样范围符合事前 16 MiB 预算。小时／天级运行与 allocator 归因仍未验证，见[性能报告](benchmarks.md)。

2026-10-29 合成规模峰值：100 个传感器、1024 条网络数据与 1025 条网络输入的字段隔离通过本机及三平台 CI 40796845854，包含两 backend 的静态缓存和每次 JSON 往返检查。合成结果不作为真实设备支持或长期无泄漏证据，见[性能报告](benchmarks.md)。

2026-10-29 Linux 启动计账隔离：已实现 fork 测量、128 MiB 父进程对照和父退出清理验证；三平台 CI 40792258046 八项任务通过；Linux 压力对照与进程退出已原生验收。旧计量结果保留，见[性能报告](benchmarks.md)。

2026-10-28 进程内存基线：新增 release C ABI 峰值探针和 64 MiB 校准，Windows 本机 300 次缓存调用及 30 次重建调用已通过；源码和产物哈希一致。三平台原生 CI 40669330970 全部八项通过；长期内存增长、allocator profiling 和合成规模峰值仍未验证，见[性能报告](benchmarks.md)。

2026-10-28 较低版本 Linux 用户空间验收：固定镜像的 Debian 12 / glibc 2.36 完成实际 CLI/C/Python 运行；Debian 11 / glibc 2.31 完成预期加载拒绝，未采集。修复后 CI 40664519934 全部八项通过，首轮容量失败保留。最低内核、精确 glibc 下限和实体设备仍待验证，见[记录](linux-runtime-container-validation.md)。

2026-10-28 Linux 候选增量：符号版本记录、强制/弱引用区分、CLI 加载器环境隔离通过本机守卫和三平台 CI 40604554378；Linux 原生 C/readelf、CLI/SDK 安装回滚通过。本次产物最高强制数值要求为 GLIBC_2.34，最低 glibc/发行版仍未验证，见[记录](linux-runtime-validation.md)。

2026-10-27 Windows 候选增量：PE 架构/直接依赖检查、Release CLI/SDK 安装回滚及本机三产物 DUMPBIN 对照通过；三平台 CI 40483692144 全部八项通过。最低 Windows 版本、全新系统运行库验证仍未完成，见[记录](windows-pe-validation.md)。

下面按 7 类整理平台增强和验证方向，每类都包含已完成与未完成子项。它们用于安排持续开发，不是“还剩七项首版门槛”；GPU 新来源、显示器扩展等是否进入首版，以 v0.1 清单为准。

| 工作包 | 已完成部分 | 剩余部分 |
|---|---|---|
| GPU | Windows DXGI、Linux DRM 枚举/部分名称和 Xe 专用显存通过 CI；Xe 解析器 fuzz 已验收；macOS Metal 名称/内存状态通过 CI 与 SDK 探针 | 其他 Linux 驱动的专用显存与名称来源；实体设备验证延期 |
| 显示器 | Windows 活动路径/信号像素通过本机 SDK 与 CI；Linux 连接视图通过原生 CLI/C、授权合成名称和 26 项权限/缓存容器验证；macOS 活动视图/模式状态通过原生 CI 与 SDK 对照；CLI 文本通过本机和三平台原生 CI，见 [记录](display-text-validation.md) | Linux 当前像素、真实名称阳性；实体多屏等验证 |
| 平台增强 | Linux 部分 DMI/电池/温度、macOS 设备型号、Windows 电池摘要；Windows 设备/主板/固件六值本机与 CI SDK/缓存通过；macOS 内置电池原生类型测试与空视图通过，[记录](macos-battery-validation.md) | 更多设备/OEM 与主板/固件来源、实体电池与其他传感器可靠来源评估 |
| 动态数据可靠性 | Linux CPU/内存/网络读取与失败回归；Windows/macOS 网络；Windows 内存与单组 CPU 通过本机和三平台 CI；macOS CPU/内存/uptime、Windows uptime 已通过原生 SDK/CI/八包；Windows 多组采样实现通过三平台 CI，单组 helper/SDK 在本机和 CI 通过，[记录](windows-cpu-groups-validation.md) | Windows 真实多组、Job/hotplug/真实故障覆盖 |
| 深入质量验证 | 单元、负向、原生 CI、容器、扩展 fuzz、Miri/ASan、三平台峰值与驻留回归，以及 Windows 一小时和一天试验 | 延长 fuzz、其他平台长时、更多故障场景和 allocator 归因 |
| 发行制品 | 8 crate 的归档与独立构建检查；Windows/Linux CLI 和 SDK 的候选安装、切换与回滚通过。CLI 包含隔离 JSON，SDK 包含 C/Python 调用，演练启动时作废旧报告。[候选验收](cli-bundle-validation.md) | macOS CLI 许可材料、macOS FFI 制品、运行时/许可最终评审和旧版回滚；registry 验收另需发布授权 |
| 最终评审与发布准备 | ADR、Schema、头文件与许可证资料 | API/ABI/Schema 最终评审、首版验收收口；公开发布另需授权 |

延期验证：维护者目前只有 Windows 笔记本与 Android 手机，实体 Linux/macOS、电池/温度等缺少设备的真机验证留到有设备后。CI 和模拟测试继续执行；它们不能替代延期的设备证据。

后续阶段：Android、iOS、Web、no_std 与 MCU 路线分别开发验收，不计入桌面首版交付门槛。持有 Android 手机不表示当前已支持 Android。

已有基础：Core、sysinfo、三平台 backend 组合、静态缓存、取消/等待边界、隐私控制、JSON/Schema、CLI、C ABI/C/Python 示例和持续集成。逐次实测以[验证目录](README.md)和[发布路线](release.md)为准。
