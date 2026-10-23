# 发布与迁移路线

2026-10-22 macOS uptime 开发增量：现有 MacosBackend 直接采集 KERN_BOOTTIME/time/启动时间复核；来源 Sysinfo -> Sysctl/Partial，失败返回缺失而非 epoch 级大数或默认零，不缓存动态值。保持现有日历时间整秒差，非单调 elapsed。单独 SysinfoBackend 用户需补 MacosBackend 或使用门面；回滚须同步恢复 sysinfo 字段。无新公共类型/签名、依赖/features/锁变化，MIT、ABI 1/Schema 1 不变。2026-10-23 CI 39878588965 全部八项、macOS ARM64 原生 SDK/链接/采样/持久刷新与三平台八包已通过，见[ADR 0028](adr/0028-macos-uptime.md)与[验证](macos-uptime-validation.md)。

2026-10-22 Windows uptime 开发增量：现有 WindowsBackend 直接读取 GetTickCount64，沿用 sysinfo 0.39.6 的计数与整数秒口径；Source 从 Sysinfo 改为 Win32，能力仍 Partial。单独 SysinfoBackend 不再提供 Windows uptime，需补 WindowsBackend 或使用门面。没有发现原实现缓存/吞错，本轮不声称修复此类缺陷。零合法，包含睡眠/休眠，不是工作时长或启动日期。无新公共类型/依赖/features/锁变更，ABI 1/Schema 1、MIT 不变；回滚须同步恢复 sysinfo 字段。见[ADR 0027](adr/0027-windows-uptime.md)和[验证](windows-uptime-validation.md)；CI 39755735940 全部八项、三平台原生/八包及 Windows SDK 夹取通过，睡眠/休眠等边界仍未实验验证。

2026-10-22 macOS 内存增量：新增 MacosMemoryBackend::new()/Default 并由门面注册，SysinfoBackend 停止提供两字段；总量改为 Sysctl/Partial、可用估计改为 AppleApi/Partial。API 失败不返回旧值；保持 hw.memsize 与非压缩估计口径，公开统计仍可能被 OS 缓存，不保证新内核计数。固定前缀请求修复后的三平台 CI 39696658516、ARM64 SDK/持久刷新与八包已通过，失败记录保留，见 [ADR 0026](adr/0026-macos-memory.md) 与[验证](macos-memory-validation.md)。无新增依赖/features/锁文件，模型、ABI 1/Schema 1、MIT 不变；回滚需同步恢复 sysinfo 字段。

2026-10-21 macOS CPU 开发增量：新增 MacosCpuBackend::new()/Default、门面自动注册，保留 MacosBackend 单元构造。逻辑核数与动态利用率转为直接 Mach 读取、AppleApi/Partial，拒绝静默 1 核/0% 回退；首次/失败恢复需两次 300 ms 有效样本，数量变化需重建 Hardware。单独 SysinfoBackend 用户须补注册。模型、ABI 1/Schema 1、包/版本/features/锁文件与 MIT 不变。见 [ADR 0025](adr/0025-macos-cpu.md) 和[本轮验证](macos-cpu-validation.md)，三平台 CI 39518381989、ARM64 原生 SDK/链接/持久刷新与八包验收已通过；实体 Mac、Intel 原生和真实 Mach 故障仍待验证。回滚须同步恢复 sysinfo 的两个字段。

2026-10-20 Windows CPU 开发增量：新增 WindowsCpuBackend::new()/Default，门面自动注册，既有 WindowsBackend 单元构造不变。CPU 动态来源由 Sysinfo 转为 Win32，失败后清基线、重新预热；仅覆盖一个活动处理器组，多组明确不支持，能力 Partial，单独 SysinfoBackend 用户须补注册。新增 windows-sys Threading 绑定 feature，包/版本/锁文件、公共模型、ABI 1/Schema 1 和 MIT 不变。见 [ADR 0024](adr/0024-windows-cpu.md) 与[本轮验证](windows-cpu-validation.md)；三平台原生 CI 39350478223、SDK/八包、短 fuzz/Miri/ASan 已通过。回滚必须同步恢复 Windows sysinfo CPU 字段，不能仅移除新 backend。

2026-10-19 Windows 内存增量：新加 `WindowsMemoryBackend::new()` / `Default`，门面自动注册；既有 `WindowsBackend` 单元构造不变。Windows 总内存/可用内存从 sysinfo Partial 迁至直接 Win32 读取，精确处理 BOOL/错误码与总量缓存变化。单独 SysinfoBackend 的 Windows 消费者需迁移。核心模型、C ABI 1/Schema 1、依赖/锁/features 与 MIT 不变；CPU 和 macOS 路径不变，见 [ADR 0023](adr/0023-windows-memory.md) 与[本轮验证](windows-memory-validation.md)；2026-10-20 三平台 CI、SDK/有界压力实验、八包、短 fuzz/内存回归通过。

2026-10-19 新增 `dscope display`：文本读取现有快照，区分 Windows 信号像素、macOS 模式像素与字段缺失状态；不改变采集或隐私规则。CLI crate 的公开 `Command` 新增 `Display`，开发版穷举匹配调用方须补分支；核心 Rust API、C ABI 1/Schema 1、依赖、feature 与 MIT 不变。见 [ADR 0022](adr/0022-display-cli.md) 和[本轮验证](display-text-validation.md)，三平台原生 CI、八包、短 fuzz 和内存回归已通过。仓库同日经维护者授权改为公开；这不等于 crates.io 或 release 制品已发布。

2026-10-18 macOS 显示器开发增量：通过公开 Core Graphics 枚举 active-for-drawing 视图和当前模式像素，名称 Unsupported，不查询名称/EDID/稳定标识。固定 1025 槽位防止截断成功、最多三轮拓扑复核、Copy/Release RAII 与字段隔离见 [ADR 0021](adr/0021-macos-display.md)。Rust 模型/签名、C ABI 1、Schema 1 形状不变，仅补充像素字段描述；无新依赖、锁或公开 feature 变化，仍 MIT。[本轮验证](macos-display-validation.md)完成独立 C SDK/CLI/C 对照、三平台 CI、八包、fuzz/内存与基准归档；实体 Mac 验证延期。

2026-10-17 Linux 显示器有限增量：提供 DRM connected 连接视图，默认不读取 EDID、名称为 PrivacyRedacted；仅双重显式授权后读取基础块产品名称。当前像素宽高仍 Unsupported，不使用 modes/EDID 时序冒充当前分辨率。静态缓存、错误/限额与隐私契约见 [ADR 0020](adr/0020-linux-display.md)。公共模型、Schema 1、C ABI 1、依赖和锁不变；隐藏 fuzzing 入口扩展既有 dmi_text。动态示例仅为合成 fixture 增加 authorize 指令，不是生产授权协议。测试临时目录加原子序号，修复并发毫秒命名碰撞。[本轮验证](linux-display-validation.md)完成三平台 CI、26 项非 root 显示器场景及既有 fuzz/内存/打包回归；原生 runner 只确认连接视图，实体 Linux/EDID 名称阳性仍待设备验证。

2026-10-16 Windows 显示器开发增量：通过公开 CCD API 提供活动路径的 EDID 友好名称及目标信号活动像素尺寸，能力 Partial/Win32。静态缓存、三次缓冲竞争重试、条目/模式上限及会话权限状态见 [ADR 0019](adr/0019-windows-display.md)。既有 `--json` 输出即可消费，没有增加 CLI 命令枚举变体。Rust 模型/签名、C ABI 1/Schema 1 形状不变；Schema 仅补充像素语义说明。windows-sys 0.61.2 增加 Windows target feature，包/锁定版本/许可证不变。名称不是稳定标识，信号尺寸不承诺面板原生分辨率。[本轮三平台验证](windows-display-validation.md)全部通过；本机与 CI 的尺寸/名称可用性分别保留，不用受限或无效字段伪造成功读取。

2026-10-16 macOS GPU 开发增量：通过公开 Metal API 读取设备名称，gpus 为 Partial/AppleApi；统一内存设备的独占显存为 NotApplicable，其他情况 Unsupported。名称、状态与静态失败均缓存，动态刷新不重扫。不使用工作集预算作为容量。沿用 Rust 模型、C ABI 1/Schema 1；新增四个 macOS 专用锁定依赖，许可证可选 MIT，默认公共 features 不变。扩展既有 dmi_text fuzz 目标和隐藏测试入口。见 [ADR 0018](adr/0018-macos-gpu.md)；[本轮三平台 CI 与 SDK 验证](macos-gpu-validation.md)已通过，实体 Mac 验证延期。

2026-10-15 Linux GPU 开发增量：gpus 从 Unsupported 转为有限 DRM 视图，Partial/Drm；card/render 节点按同一设备去重，名称只支持有文档的 AMDGPU product_name 和 NVIDIA 首行 Model。没有可靠名称的驱动保持字段 Unsupported，缺失/权限/格式失败单列；独占显存仍 Unsupported，不把 VRAM/GTT 填入。静态成功和失败均缓存。Rust 模型形状、签名、C ABI1/Schema1、依赖、锁、许可证与默认 features 不变；复用隐藏 fuzzing 入口扩展既有 dmi_text 目标。见[ADR](adr/0017-linux-gpu.md)，实体 GPU 验证仍延期。

2026-10-15 开发版 Windows GPU 增强：gpus 从默认 Unsupported 转为 Partial/Dxgi，采集非软件适配器名称与独占显存字节数。静态缓存不随动态刷新重扫；零值可为真实报告，空集合不证明物理无显卡。新增既有 SDK 的 Windows target 依赖边与 features，锁定包版本和许可证不变。Rust 模型形状、签名、ABI1/Schema1 不变，仅补充 Schema 描述；Windows 字段可用性行为改变，消费方仍须逐字段检查。见[ADR](adr/0016-windows-gpu.md)。

当前 0.1.0 为开发版本，尚未发布。当前构建与检查结果见[项目检查报告](project-review-2026-10-11.md)和 [CI 工作流](https://github.com/DaoSeeker01/DaoSeekerScope/actions/workflows/ci.yml)；下面的日期记录属于对应历史版本。创建私有仓库、推送和 CI 已获授权，crates.io 发布或 release 制品分发仍需单独授权。

2026-10-14 设备验证安排：维护者当前有 Windows 笔记本和 Android 手机。实体 Linux/macOS、真实 Linux 电池/温度及其他缺少设备的测试推迟到设备可用后，不阻塞当前开发；保持待验证状态，不能以 CI/模拟测试替代这些设备证据。三平台原生 CI、容器、Schema、FFI、fuzz 与打包门禁继续执行。Android 适配属于后续独立阶段，持有手机不代表当前库已经支持 Android。

打包准备的可复现入口与限制见[打包与安装验证](packaging.md)。它在新目录执行原生 Cargo package 验证，另验证实际归档和使用本地 patch 的独立构建；真实 registry 安装仍须单独验收，不以 `--list` 或本地 patch 宣称发布准备完成。

发布顺序：维护者ADR/Schema评审 → 三平台原生build/test/doc + C/Python契约 → Linux容器/DMI缺失/权限降级 → fuzz与sanitizer campaign → 依赖/许可证审计 → cargo package逐crate验证 → 制品checksum/安装/回滚演练 → 发布。先core，随后sysinfo及平台crate，再门面、CLI/FFI，避免依赖不存在的crate版本。此顺序是计划，未执行的步骤不算通过。

JSON v1：对象新增字段可向前兼容（未知字段忽略），新增枚举值要求Schema主版本协商；字段删除/语义/单位变化增加Schema主版本并提供v1读取迁移器。C ABI v1：不改变现有options/buffer布局，新增ABI主版本以新入口并存；错误码不复用。Rust0.1破坏变更提高minor，1.0后破坏变更提高major并附迁移说明。sysinfo升级固定版本并重跑状态/单位/CPU采样/黄金样例/Schema/三平台门禁。

回滚：保留上一版库与header、CLI及checksum；上层应用按ABI与Schema版本拒绝不兼容数据，恢复匹配版本，不能只替换DLL却保留不兼容header。静态失败重新构造Hardware刷新，当前无热插拔静态重扫API。

版本1首次发布，没有从旧ABI/Schema迁移。移动/Web/no_std/MCU独立能力矩阵与实际构建证据后再决定接入。

开发版Linux CPU行为迁移：CPU占用率来源改为procfs，失败清基线且恢复首读重新等待300ms采样对；仅单独SysinfoBackend注册者需补LinuxBackend或使用门面。既有Source枚举、Rust签名、ABI/Schema1与feature不变。实际故障回归、三平台及FFI门禁见[CPU刷新验收](cpu-refresh-validation.md)。Windows/macOS sysinfo路径的Partial新鲜度边界仍适用。


原生验收入口：scripts/native_smoke.py；先构建当前CLI/FFI/C例子，再执行。CI自动保留14天原生报告，报告overall及job/退出码共同判断，incomplete/failed/not_run不算通过。Windows x64、Linux x64、macOS arm64报告均已保存仓库，见[首次三平台CI验收](ci-validation.md)与[最新容器验收](linux-container-validation.md)。所列Ubuntu24.04/Docker28.0.4 x86_64权限和输入缺失场景已通过，完整/proc覆盖被运行时拒绝且未执行库。短期fuzz、Miri和Rust FFI ASan已通过；其他容器/安全策略、动态源中途失效、长期campaign、峰值分配profiling和发行制品验证仍待完成。

开发版Linux内存/uptime行为迁移：相关字段来源改为Procfs、实现能力Supported；SysinfoBackend在Linux不再提供总内存/可用内存/uptime，需补LinuxBackend或使用门面。错误不保留旧值，缺MemAvailable不估算，缓存MemTotal变化时动态暂不可用，重建Hardware刷新静态总量。既有字段/单位/签名/feature/ABI1/Schema1不变，尚未发布，因此记录为开发版backend行为修正；正式版本仍需按上述兼容规则评审。见[验收与限制](memory-refresh-validation.md)。

开发版Linux电池扩展：原Unsupported类别现在由LinuxBackend提供Partial、SourceSysfs的有界动态power_supply枚举。完整可读视图无Battery是Available空集合；缺路径、分类不完整/受限、数值错误或超限各按观察返回。仅Mains聚合提供AC状态，没有Mains不可推断false；不采集电池ID，不保证索引跨热插拔稳定。旧消费者应继续检查集合及字段Availability，不能把新空集合当作真实电池字段成功。公共类型/签名/feature集合、ABI1/Schema1和锁不变，仅增加Schema描述元数据；尚未发布。30项内核权限/合成观测与七目标短fuzz已验，真实Linux电池与发行性能仍待独立验证，见[报告](battery-validation.md)。

开发版Linux传感器扩展：sensors从Unsupported转为Partial/SourceHwmon。调用方仍需逐项检查温度状态，完整集合Available并不表示每个温度Available；未知单位/驱动和相对Tctl保持Unsupported，默认标签Restricted/PrivacyRedacted。仅coretemp与k10temp的Tdie路由，索引不保证跨热插拔稳定；不提供完整hwmon或主板校正能力。Rust模型形状、签名、依赖、feature、ABI1/Schema1不变，仅增加Schema description。实测与未验证范围见[hwmon验收](hwmon-validation.md)。

2026-10-11开发增量：NVMe hwmon通道1..9加入现有路由；独立通道零Kelvin返回NotPresent，Composite零Kelvin为InvalidData。Composite可为设备计算值，SensorInfo说明相应修正，Schema只改description；默认不采集磁盘标识，存储集合仍Unsupported。无版本/feature/依赖/许可证变化，非发行制品；[独立验收](nvme-temperature-validation.md)。
