# 剩余工作

首版交付门槛与近期修复分别见 [v0.1 清单](v0.1-checklist.md)和[核心取消与缓存审查](project-review-2026-10-31.md)。下面保留平台增强工作包，不将它们全部视作首版的必要阻塞项。

2026-10-31 核心取消修复：确认并修复静态/动态收集器可能把取消误报为 BackendFailure 的路径，补充三项回归；本机完整门禁、八包、原生契约与两分钟回归，以及三平台 CI 41146601854 八项任务已通过，见[审查记录](project-review-2026-10-31.md)。旧提交 b8930ac 的一小时基线仍独立运行，尚未验收，不与本轮修复结果混用。

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

按可独立验收的工作包统计，首版还有 7 组主动任务。每组包含多个平台子项，不换算为代码完成百分比。

| 工作包 | 已完成部分 | 剩余部分 |
|---|---|---|
| GPU | Windows DXGI、Linux 有限 DRM 枚举/名称已验收；macOS Metal 名称/内存状态通过三平台 CI 与独立 SDK 探针 | Linux 独占显存及更多名称来源；实体 Mac/AMD/NVIDIA 验证延期 |
| 显示器 | Windows 活动路径/信号像素通过本机 SDK 与 CI；Linux 连接视图通过原生 CLI/C、授权合成名称和 26 项权限/缓存容器验证；macOS 活动视图/模式状态通过原生 CI 与 SDK 对照；CLI 文本通过本机和三平台原生 CI，见 [记录](display-text-validation.md) | Linux 当前像素、真实名称阳性；实体多屏等验证 |
| 平台增强 | Linux 部分 DMI/电池/温度、macOS 设备型号、Windows 电池摘要；Windows 设备/主板/固件六值本机与 CI SDK/缓存通过，[记录](windows-hardware-summary-validation.md) | 更多设备/OEM 与主板/固件来源，其他平台电池/传感器可靠来源评估 |
| 动态数据可靠性 | Linux CPU/内存/网络读取与失败回归；Windows/macOS 网络；Windows 内存与单组 CPU 通过本机和三平台 CI；macOS CPU/内存/uptime、Windows uptime 已通过原生 SDK/CI/八包；Windows 多组采样实现通过三平台 CI，单组 helper/SDK 在本机和 CI 通过，[记录](windows-cpu-groups-validation.md) | Windows 真实多组、Job/hotplug/真实故障覆盖 |
| 深入质量验证 | 单元、负向、原生 CI、容器、短 fuzz、Miri/ASan，以及有限轮次的句柄/描述符校准与增长对照 | 长期 fuzz、更多故障场景、小时／天级运行与 allocator 归因；已有三平台峰值、固定轮次驻留回归 |
| 发行制品 | 8 crate 的归档与独立构建检查；Windows CLI ZIP/checksum/隔离安装回滚通过本机与 CI 六进程验收，[记录](cli-bundle-validation.md)；Linux ZIP v2/权限与六进程安装回滚通过原生 CI，[记录](linux-cli-bundle-validation.md)；Windows FFI SDK 本机及 CI C/Python 与回滚通过，[记录](windows-ffi-sdk-validation.md)；Linux SDK v4 原生构建/C/Python/权限与回滚通过三平台 CI，[记录](linux-ffi-sdk-validation.md) | macOS CLI 许可材料、macOS FFI 制品、运行时/许可最终评审和旧版回滚；registry 验收另需发布授权 |
| 最终评审与发布准备 | ADR、Schema、头文件与许可证资料 | API/ABI/Schema 最终评审、首版验收收口；公开发布另需授权 |

延期验证：维护者目前只有 Windows 笔记本与 Android 手机，实体 Linux/macOS、电池/温度等缺少设备的真机验证留到有设备后。CI 和模拟测试继续执行；它们不能替代延期的设备证据。

后续阶段：Android、iOS、Web、no_std 与 MCU 路线分别开发验收，不计入桌面首版的 7 组主动任务。持有 Android 手机不表示当前已支持 Android。

已有基础：Core、sysinfo、三平台 backend 组合、静态缓存、取消/等待边界、隐私控制、JSON/Schema、CLI、C ABI/C/Python 示例和持续集成。逐次实测以[验证目录](README.md)和[发布路线](release.md)为准。
