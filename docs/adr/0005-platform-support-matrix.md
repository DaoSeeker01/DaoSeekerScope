# 0005 平台能力矩阵

以下为实现路线/权限预期，运行证据单列于 docs/validation.md。D=普通用户直接读取、P=可能权限/沙盒受限、A=增强需管理员（不选默认路径）、U=本切片未实现、N=平台无此通用语义。不是设备上所有字段可用的保证。

2026-10-09实际验收：Windows x64（windows-2025-vs2026）、Linux x64（ubuntu-24.04）、macOS arm64（macos-26-arm64）原生CI均完成CPU/内存/OS最小读取、Rust门禁及C/Python调用，见[CI证据](../ci-validation.md)。Windows安装内存来自win32、macOS安装内存来自sysctl，Linux该字段仍Unsupported。这些托管runner结果不证明所有发行版、架构、硬件字段或受限容器可用；下表仍为字段能力路线。

2026-10-09运行、2026-10-10归档的[Linux容器证据](../linux-container-validation.md)增加7个真实production CLI场景：非root内核权限拒绝、DMI缺失/损坏、serial授权与权限分离、三个proc输入为空。DMI内容为合成Fixture，不是实际硬件识别。缺失DMI字段为Unavailable/NotPresent、能力Supported且附原因；拒绝权限为Restricted/PermissionDenied；空proc输入为Unavailable/Unknown，sysinfo能力Partial。完整/proc覆盖被OCI拒绝、进程未运行，不能宣称完全缺失procfs可用。当前仅覆盖Ubuntu24.04/Docker28.0.4 x86_64配置；更多安全策略与动态刷新仍待验证。

| 字段 | Windows | Linux | macOS | 本切片路线 |
|---|---|---|---|---|
| OS/静态CPU摘要 | D/P | D/P，procfs容器可缺 | D/P | sysinfo system；错误模型 Partial |
| OS可用总量/可用内存/uptime | D/P，sysinfo Partial | D/P，procfs Supported | D/P，sysinfo Partial | Linux有界读取并区分失败；总量缓存、总量变化时动态暂不可用 |
| 动态CPU占用率 | D/P，sysinfo Partial | D/P，procfs Supported | D/P，sysinfo Partial | Linux直接有界两样本采集；故障清基线，独立于静态CPU |
| 安装物理内存 | D，SMBIOS可损坏 | U | D/P hw.memsize | Win32 / sysctl；与 OS 可用总量分开 |
| 设备model/vendor、主板、固件 | U，WMI/SMBIOS候选 | D/P sysfs DMI | D/P hw.model（仅model） | Linux 固定 DMI 文件；macOS sysctl |
| 设备serial | U | P，显式授权后 sysfs | U（IOKit候选） | 默认 Restricted/PrivacyRedacted |
| 电池 | D/N GetSystemPowerStatus | D/P power_supply、Partial，CI枚举/权限fixture通过 | U，IOKit候选 | Linux capacity/Mains online受控枚举；原生runner无条目，USB拓扑/真实电池未验 |
| 温度 | U，WMI质量不一 | D/P hwmon、Partial | U，公开接口不足 | coretemp、k10temp Tdie；NVMe1..9路由本机/三平台CI和47项合成内核观察通过，原生runner无条目，设备计算值不等于物理点；[验收](../nvme-temperature-validation.md) |
| GPU/独占显存 | D/P，Partial DXGI | D/P，Partial DRM 视图；部分 AMD/NVIDIA 名称，显存 U | U，Metal/IOKit候选 | 不是物理卡数；Linux 不覆盖未绑定 DRM 的 GPU，不将 VRAM/GTT 推断成独占显存 |
| 存储设备容量 | D/P Setupapi/Win32、Partial | D/P Sysfs、Partial | D/P Iokit、Partial | 整块设备含虚拟对象，不代表文件系统可用空间或物理总量；[Linux 契约](0013-storage-capacity.md)与[验证](../storage-validation.md)、[Windows 契约](0014-windows-storage-capacity.md)与[验证](../windows-storage-validation.md)、[macOS 契约](0015-macos-storage-capacity.md)与[验证](../macos-storage-validation.md)，名称默认脱敏、serial/UUID不查询 |
| 网络累计字节数 | D/P Win32、Partial | D/P procfs、Supported | D/P Sysctl、Partial | Windows 有界枚举、不保证所有逻辑接口；[Windows 验证](../windows-network-validation.md)。Linux 仅当前网络命名空间；[Linux 验证](../network-validation.md)。macOS 可能取整/回绕；[契约](0012-macos-network-counters.md)。名称默认脱敏；Windows/macOS 临时原始缓冲仍含未解析保存的标识 |
| 显示器 | U，SetupAPI/Win32候选 | U，DRM候选 | U，公开Apple API候选 | 后续 |
| 原始SMBIOS/磁盘底层探测 | A/P | A/P | P/U | 不选默认路径 |
| 移动/Web/no_std/MCU | U | U | U | 独立后续发布计划，无crate空壳 |

2026-10-11 网络切片源码 `7f08ac0` 的 CI 38092523723 全部 8 个任务成功：Linux CLI/C 实读 4 条 Procfs 接口统计且名称脱敏，普通用户权限拒绝/恢复 fixture 通过，新解析器 fuzz 实跑 61 秒。Windows/macOS 网络仍 Unsupported；[独立证据与范围](../network-validation.md)不把虚拟接口数量当作物理网卡数量。

2026-10-11 Windows 网络切片源码 `5e43fdd` 的 CI 38094160512 全部 8 个任务成功：Windows CLI/C 各实读 18 条 Win32 统计且名称脱敏，能力 Partial；本机未提升权限进程读到 43 条，并实际验证 1 条限额拒绝、CPU/内存隔离。三平台源码及独立消费者各 97/95/94 项 Rust 测试（Windows/Linux/macOS）通过；macOS 网络仍 Unsupported。系统临时缓冲确实含标识，不解析保存不等于从未进入内存，详见 [Windows 契约与证据](../windows-network-validation.md)。

2026-10-12 macOS 网络最终修复源码 `d27e681` 的 CI 38186025262 全部 8 个任务成功：macOS CLI/C 各实读 11 条 Sysctl 统计且名称脱敏，能力 Partial；公开统计对普通应用可能取整和回绕。三平台源码及独立消费者各 105/103/102 项 Rust 测试（Windows/Linux/macOS）、十个各至少 60 秒 fuzz 通过。首轮 CI 的 harness 来源断言失败与修复分别保留，见 [macOS 验证](../macos-network-validation.md)。

2026-10-12 Linux 存储切片源码 `2b19e8d` 的 CI 38188243470 全部 8 个任务成功：CLI/C 各读 9 个整块对象（含虚拟设备），一项正容量及八项内核报告零值，名称全部脱敏；21 项非 root 合成 sysfs/缓存观察通过。三平台源码与独立消费者各 111/109/108 项测试，十一个各至少 60 秒 fuzz 通过。Windows/macOS 存储仍 Unsupported；[验证范围](../storage-validation.md)不将虚拟对象相加为物理容量。

2026-10-13 Windows 存储切片源码 `ecf4a4c` 的 CI 38324105182 全部 8 个任务成功：Windows CLI/C 各读 2 个 Setupapi 整盘对象，容量 Source Win32、能力 Partial、名称脱敏；本机 token 未提升实读一个对象，100 次新 Hardware 查询句柄无净增长。三平台源码及独立消费者各 119/109/108 项测试，十一已有 fuzz 目标各至少 60 秒通过，Linux 存储和容器回归不变，macOS storage 仍 Unsupported。详见[Windows 契约](0014-windows-storage-capacity.md)与[验收范围](../windows-storage-validation.md)，不承诺所有驱动、沙盒、热插拔或长期泄漏已验证。

2026-10-13 macOS 存储切片源码 `99e9479` 的 CI 38326748121 全部 8 个任务成功：macOS CLI/C 各读 7 个 Iokit Whole 对象，名称脱敏、能力 Partial；普通账户 SDK 探针完成 110 次扫描，末次 23 个媒体/7 个整盘，CF 类型转换原生测试通过。三平台源码及独立消费者各 127/117/117 项测试，十一既有 fuzz 目标各至少 60 秒通过；Windows 2/Linux 9 个存储对象及容器回归通过。见[macOS 契约](0015-macos-storage-capacity.md)与[范围](../macos-storage-validation.md)，虚拟 runner 不是实物盘、sandbox、热插拔或原生长期泄漏证明。

增强研究依据：[Win32安装内存](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getphysicallyinstalledsystemmemory)、[电源状态](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getsystempowerstatus)、[WMI Next timeout](https://learn.microsoft.com/en-us/windows/win32/api/wbemcli/nf-wbemcli-ienumwbemclassobject-next)、[DXGI适配器](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/nf-dxgi-idxgifactory-enumadapters)、[Linux sysfs ABI](https://docs.kernel.org/admin-guide/abi-testing.html)、[hwmon单位](https://docs.kernel.org/hwmon/sysfs-interface.html)、[Apple sysctl](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/sysctlbyname.3.html)、[IOKit](https://developer.apple.com/documentation/iokit)。文档是选型依据，不能代替编译或设备实验。

选择普通用户的小范围增强以避免WMI永久阻塞；不引入wmi/udev/Metal依赖。Linux无DMI、WSL、容器、安全策略按真实ErrorKind降级；不根据文件exists断言能力。macOS仅公开sysctl只读查询。后续引入扫描器必须加资源/权限/错误隔离测试。

2026-10-10 [CPU刷新切片](../cpu-refresh-validation.md)将Linux CPU动态来源改为procfs。源码3ec5f6e的非root容器完成15个连续观测，涵盖损坏、权限拒绝、恢复后重新采样、无增长、计数回退及真实0%；原7个DMI/proc场景也重新通过。计数为合成Fixture，真实CPU读取由原生desktop测试独立验证；不推断Windows/macOS或其他动态字段已解决新鲜度问题。仅注册SysinfoBackend的Linux消费者需注册LinuxBackend或使用门面。

2026-10-10 [内存/uptime切片](../memory-refresh-validation.md)实际CI运行38008554490对源码6d0a377全部8任务成功。Linux非root容器26个连续观测验证清空、损坏、内核权限拒绝/恢复、合法0及总量变化；数据为合成Fixture，真实最小读取由三平台desktop独立验证。当前Linux内存/uptime来源Procfs、Supported，空meminfo为InvalidData；此前历史sysinfo Partial描述保留为当轮结果。Windows/macOS不增加新鲜度声明，完全缺失procfs的运行时探针仍not_run。

2026-10-10 [电池切片](../battery-validation.md)源码15ef5c1的CI38047435339全部8任务成功，Linux非root内核权限/热插拔/两类资源限额等30个生产观测通过；新属性fuzz执行19,744,677次正常结束。Linux实际原生枚举Available空集合，Windows runner仍NotApplicable/NotPresent，macOS仍Unsupported；不把空集合当作真实电池字段成功。原生Windows本机Win32电量100%/AC=true是独立机器读值。Linux能力Partial、SourceSysfs，128字节属性/256个供应设备上限、默认128电池上限；USB充电不推断AC，未验证真实Linux电池或完整电源拓扑。
