# 剩余工作

按可独立验收的工作包统计，首版还有 7 组主动任务。每组包含多个平台子项，不换算为代码完成百分比。

| 工作包 | 已完成部分 | 剩余部分 |
|---|---|---|
| GPU | Windows DXGI、Linux 有限 DRM 枚举/名称已验收；macOS Metal 名称/内存状态通过三平台 CI 与独立 SDK 探针 | Linux 独占显存及更多名称来源；实体 Mac/AMD/NVIDIA 验证延期 |
| 显示器 | Windows 活动路径/信号像素通过本机 SDK 与 CI；Linux 连接视图通过原生 CLI/C、授权合成名称和 26 项权限/缓存容器验证；macOS 活动视图/模式状态通过原生 CI 与 SDK 对照；CLI 文本通过本机和三平台原生 CI，见 [记录](display-text-validation.md) | Linux 当前像素、真实名称阳性；实体多屏等验证 |
| 平台增强 | Linux 部分 DMI/电池/温度、macOS 设备型号、Windows 电池摘要；Windows 设备/主板/固件六值本机与 CI SDK/缓存通过，[记录](windows-hardware-summary-validation.md) | 更多设备/OEM 与主板/固件来源，其他平台电池/传感器可靠来源评估 |
| 动态数据可靠性 | Linux CPU/内存/网络读取与失败回归；Windows/macOS 网络；Windows 内存与单组 CPU 通过本机和三平台 CI；macOS CPU/内存/uptime、Windows uptime 已通过原生 SDK/CI/八包；Windows 多组采样实现通过三平台 CI，单组 helper/SDK 在本机和 CI 通过，[记录](windows-cpu-groups-validation.md) | Windows 真实多组、Job/hotplug/真实故障覆盖 |
| 深入质量验证 | 单元、负向、原生 CI、容器、短 fuzz、Miri/ASan | 长期 fuzz、更多故障场景、峰值内存与性能测量 |
| 发行制品 | 8 crate 的归档与独立构建检查；Windows CLI ZIP/checksum/隔离安装回滚通过本机六进程验收，[记录](cli-bundle-validation.md) | Windows 候选包新增 CI 验收；Linux/macOS 与 FFI 制品、运行时/许可最终评审、旧版回滚；registry 验收另需发布授权 |
| 最终评审与发布准备 | ADR、Schema、头文件与许可证资料 | API/ABI/Schema 最终评审、首版验收收口；公开发布另需授权 |

延期验证：维护者目前只有 Windows 笔记本与 Android 手机，实体 Linux/macOS、电池/温度等缺少设备的真机验证留到有设备后。CI 和模拟测试继续执行；它们不能替代延期的设备证据。

后续阶段：Android、iOS、Web、no_std 与 MCU 路线分别开发验收，不计入桌面首版的 7 组主动任务。持有 Android 手机不表示当前已支持 Android。

已有基础：Core、sysinfo、三平台 backend 组合、静态缓存、取消/等待边界、隐私控制、JSON/Schema、CLI、C ABI/C/Python 示例和持续集成。逐次实测以[验证目录](README.md)和[发布路线](release.md)为准。
