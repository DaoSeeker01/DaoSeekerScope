# 剩余工作

2026-11-03 CLI 隔离批次：新增可选 `--isolate` 与 `--timeout-ms=N`，超时后终止并确认子进程退出，限制结果为 1 MiB；父管道监测启动后可随管道关闭退出。本机完整 Rust 门禁 302 项通过、1 项夹具由监督测试启动，严格 Clippy、文档、无默认功能和 Linux/macOS 交叉 check 通过；三平台原生 CI 待验收。覆盖实际文本/JSON、默认脱敏、挂起、超时、超大输出、异常退出及满 1 MiB JSON 往返。接口与限制见[使用指南](usage.md#在独立进程中采集)，不增加 Rust/C ABI 的强终止或卸载能力。

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
| GPU | Windows DXGI、Linux 有限 DRM 枚举/名称已验收；macOS Metal 名称/内存状态通过三平台 CI 与独立 SDK 探针 | Linux 独占显存及更多名称来源；实体 Mac/AMD/NVIDIA 验证延期 |
| 显示器 | Windows 活动路径/信号像素通过本机 SDK 与 CI；Linux 连接视图通过原生 CLI/C、授权合成名称和 26 项权限/缓存容器验证；macOS 活动视图/模式状态通过原生 CI 与 SDK 对照；CLI 文本通过本机和三平台原生 CI，见 [记录](display-text-validation.md) | Linux 当前像素、真实名称阳性；实体多屏等验证 |
| 平台增强 | Linux 部分 DMI/电池/温度、macOS 设备型号、Windows 电池摘要；Windows 设备/主板/固件六值本机与 CI SDK/缓存通过；macOS 内置电池原生类型测试与空视图通过，[记录](macos-battery-validation.md) | 更多设备/OEM 与主板/固件来源、实体电池与其他传感器可靠来源评估 |
| 动态数据可靠性 | Linux CPU/内存/网络读取与失败回归；Windows/macOS 网络；Windows 内存与单组 CPU 通过本机和三平台 CI；macOS CPU/内存/uptime、Windows uptime 已通过原生 SDK/CI/八包；Windows 多组采样实现通过三平台 CI，单组 helper/SDK 在本机和 CI 通过，[记录](windows-cpu-groups-validation.md) | Windows 真实多组、Job/hotplug/真实故障覆盖 |
| 深入质量验证 | 单元、负向、原生 CI、容器、短 fuzz、Miri/ASan，以及有限轮次的句柄/描述符校准与增长对照 | 长期 fuzz、更多故障场景、小时／天级运行与 allocator 归因；已有三平台峰值、固定轮次驻留回归 |
| 发行制品 | 8 crate 的归档与独立构建检查；Windows CLI ZIP/checksum/隔离安装回滚通过本机与 CI 六进程验收，[记录](cli-bundle-validation.md)；Linux ZIP v2/权限与六进程安装回滚通过原生 CI，[记录](linux-cli-bundle-validation.md)；Windows FFI SDK 本机及 CI C/Python 与回滚通过，[记录](windows-ffi-sdk-validation.md)；Linux SDK v4 原生构建/C/Python/权限与回滚通过三平台 CI，[记录](linux-ffi-sdk-validation.md) | macOS CLI 许可材料、macOS FFI 制品、运行时/许可最终评审和旧版回滚；registry 验收另需发布授权 |
| 最终评审与发布准备 | ADR、Schema、头文件与许可证资料 | API/ABI/Schema 最终评审、首版验收收口；公开发布另需授权 |

延期验证：维护者目前只有 Windows 笔记本与 Android 手机，实体 Linux/macOS、电池/温度等缺少设备的真机验证留到有设备后。CI 和模拟测试继续执行；它们不能替代延期的设备证据。

后续阶段：Android、iOS、Web、no_std 与 MCU 路线分别开发验收，不计入桌面首版交付门槛。持有 Android 手机不表示当前已支持 Android。

已有基础：Core、sysinfo、三平台 backend 组合、静态缓存、取消/等待边界、隐私控制、JSON/Schema、CLI、C ABI/C/Python 示例和持续集成。逐次实测以[验证目录](README.md)和[发布路线](release.md)为准。
