# ADR 0030：Windows 注册表设备、主板与固件摘要

状态：已实现并通过本地 Rust/Python 门禁与独立 SDK 对照；本轮 CI 尚未执行。最初调研确认本机六值存在，均为 REG_SZ；具体来源与验收边界见[验证记录](../windows-hardware-summary-validation.md)。不新增公共消费类型。

只读 `HKLM\HARDWARE\DESCRIPTION\System\BIOS` 中固定六个值，不枚举键或其他值：

| 注册表值 | 既有公共字段 |
|---|---|
| SystemManufacturer | system.device.vendor |
| SystemProductName | system.device.model |
| BaseBoardManufacturer | system.motherboard.vendor |
| BaseBoardProduct | system.motherboard.model |
| BIOSVendor | system.firmware.vendor |
| BIOSVersion | system.firmware.version |

使用已有 WindowsBackend 的静态入口；单元构造、门面注册不变，动态刷新不重读六值，成功和缺失均由 Hardware 静态缓存，重新采集需新建 Hardware。固定白名单由内部枚举表示，生产不接收自定义路径。来源 Win32、能力 Partial：这是 Windows 注册表报告的 OEM 摘要，键/字段可缺失、修改或是占位内容，不保证 SMBIOS/物理硬件真实性、固件安全状态或安装更新后的即时版本。键布局仅作有限适配路线，不承诺未来 Windows 或所有 OEM 都保留；缺失明确返回状态，不回退虚构值。

不选 GetSystemFirmwareTable(RSMB)，因为整个原始表会同时包含序列号/UUID；不选默认 WMI/COM，以免引入查询生命周期和阻塞回退。默认和敏感授权模式都只读上述六值，不查询 serial/UUID/SKU/资产编号，不读取整份键、SMBIOS 或文件。OEM 仍可能错误地把标识写入型号等字段；库无法证明任意 OEM 内容不含识别信息，不能声称脱敏保证覆盖 OEM 任意文本。

每值一次 RegGetValueW，固定 4096-byte、至少 WCHAR 对齐且初始化的缓冲；限定 REG_SZ，NOEXPAND、ZEROONFAILURE，不读取失败输出，不对 MORE_DATA 扩容/重试。检查成功返回的类型、偶数长度、末尾单 NUL、无内嵌 NUL、严格 UTF-16、无控制字符、修剪后非空、已知 OEM 占位词和最终 UTF-8 <=4096 bytes。无替换字符修复、截断或默认字符串。每个 API 前后检查取消/截止时间，字段失败隔离；合作式检查不能中断已阻塞的内核调用。

LSTATUS 是错误来源，不读取 GetLastError。缺失值/键（2/3）为 Unavailable/NotPresent；拒绝（5/1314）为 Restricted/PermissionDenied；类型/长度/格式（13/87/234/1630）为 Unavailable/InvalidData；暂时资源/删除（8/14/170/1018/1237）为 Unavailable/TemporarilyUnavailable；API 不支持（50/120）为 Unsupported/NotSupported，其他为 Unavailable/Unknown。不猜测 Sandbox。组合器可能保留默认 Unsupported/Custom，验证分别检查直接 backend 与门面，不改 core 合并规则。

只为 Windows target 的既有 windows-sys 0.61.2 增加 Win32_System_Registry 绑定 feature，无新第三方包/版本/许可证。复用默认关闭的 Windows `fuzzing` 与 dmi_text 目标测试生产 UTF-16 解析器，不加新 fuzz 目标或锁边。公共模型、JSON 形状、ABI 1、Schema 1、MIT 不变；Windows 六字段从 Unsupported 改为有界尝试。回滚可移除该静态读取和六项能力声明。

验证包括状态映射、恶意 UTF-16/长度/占位词、失败输出不消费、每字段隔离、12 个取消检查位置、静态成功/失败缓存与重建、固定白名单以及独立 C SDK/持久公共快照对照。机器实际 token 是否提升单列；管理员读取不冒充普通用户验证。真实 ACL 拒绝、键缺失、不同 OEM/虚拟机和实体其他系统另列，不修改机器真实 BIOS 注册表制造场景。

依据（2026-10-25）：Microsoft [RegGetValueW](https://learn.microsoft.com/en-us/windows/win32/api/winreg/nf-winreg-reggetvaluew)、[注册表结构](https://learn.microsoft.com/en-us/windows/win32/sysinfo/structure-of-the-registry)、[WOW 共享键规则](https://learn.microsoft.com/en-us/windows/win32/winprog64/shared-registry-keys)、[原始固件表范围](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getsystemfirmwaretable)。字段路径来自实际本机观察，不以文档推断可用；SDK 编译/CI 不能替代更多设备证据。
