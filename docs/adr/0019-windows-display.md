# ADR 0019：Windows 活动显示路径

状态：开发版实现契约，维护者最终公共 API 评审仍待完成。

## 决定

先实现 Windows 10+ 的有限活动路径视图，沿用 DisplayInfo 的 name/width_pixels/height_pixels，尝试能力 Partial/Win32，当前访问状态由运行结果更新。通过 GetDisplayConfigBufferSizes 与 QueryDisplayConfig（ONLY_ACTIVE_PATHS | VIRTUAL_MODE_AWARE）取得当前路径/模式；通过 DisplayConfigGetDeviceInfo 取得有 friendlyNameFromEdid 标志的名称。没有 EDID 名称时只返回字段 Unavailable/NotPresent，不用设备路径、Generic Monitor 或适配器名称填充。

宽高来自目标模式 targetVideoSignalInfo.activeSize，表示当前信号活动像素数，不是面板原生分辨率、首选模式、DPI 逻辑坐标或桌面布局。旋转/缩放不由库推断或交换宽高。索引、类型、目标 ID/适配器匹配均验证后才读取；不存在目标模式为字段 NotPresent，损坏索引/类型/零尺寸为 InvalidData。名称失败与尺寸失败隔离。

同一目标的重复路径拒绝为 InvalidData；镜像显示可有不同目标共享源，仍按不同路径返回。不枚举未激活、断开、HMD 或所有物理显示器。成功空数组仅表示当次活动视图为空；远程/无控制台访问的 ERROR_ACCESS_DENIED 为 Restricted/PermissionDenied，不绕过会话访问控制，ERROR_NOT_SUPPORTED 为 Unsupported/NotSupported。

## 资源与隐私

路径缓冲最大 1024、模式最大 4096，估算大小先校验再分配；最终条目遵守 Options.max_entries（默认 128）。拓扑竞争的 INSUFFICIENT_BUFFER 最多重试 3 次，耗尽为 TemporarilyUnavailable；超限拒绝整个集合，不返回成功前缀。零估算仍查询，传入非空地址且最少一元素的有界缓冲，不能凭估算宣布成功空列表。返回计数超过实际缓冲先拒绝，再访问/截断。

字符串为固定 64 UTF-16 单元，要求 NUL、合法 UTF-16、非空白、无控制字符。SDK 结构暂时包含适配器/目标标识与设备路径，匹配只在 worker 内进行；不记录、缓存、导出或解析序列号、MAC、UUID、monitorDevicePath 或原始 EDID。默认仅保留名称与尺寸。原生 API 内部的分配不能由投影上限硬限制。

沿用静态缓存：成功、空数组和失败均缓存，refresh_dynamic 不重扫；显示模式/连接变化后新建 Hardware。FFI NULL options 缓存、非 NULL 有效 options 每次独立采集。检查取消/截止时间围绕原生调用；不能强制终止同步驱动。错误取 API 返回值，绝不使用残留 GetLastError。

路径查询和名称查询为顺序调用，拓扑变化时不保证跨调用的原子快照；匹配用的原生 ID 不是稳定设备标识，也不进入公共模型。

## 兼容与验收

核心模型、签名、C ABI 1/Schema 1 形状不变；补充像素字段说明。仅为已锁定 windows-sys 0.61.2 增加 Windows target 的 Win32_Devices_Display feature，不新增包/版本或更改许可证。CLI 使用既有 --json 输出，不增加命令枚举变体；专用文本命令不在本切片。统一组合逻辑可能保留默认 Unsupported/Custom；它仍表示无支持来源，不能当作 SDK 成功读取。

纯采集接口验证重试、限额、返回计数、模式索引/类型/匹配、空集合、Unicode、字段隔离、取消与静态缓存。Windows 本机和 CI 分开记录；CI 会话受限时必须如实记录 Restricted，不能当作尺寸读取成功。独立 C SDK 探针输出计数/尺寸/状态，不保存名称或标识。Linux/macOS 显示器仍 Unsupported；实体多屏、旋转/缩放、热插拔、远程桌面和原生长期泄漏验证独立列为待办。

## 官方依据

- [QueryDisplayConfig](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-querydisplayconfig) 与 [缓冲估算](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getdisplayconfigbuffersizes)。
- [目标路径与虚拟模式索引](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-displayconfig_path_target_info)。
- [信号 activeSize](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-displayconfig_video_signal_info)。
- [设备名称标志](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-displayconfig_target_device_name_flags) 与 [名称查询](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-displayconfiggetdeviceinfo)。
