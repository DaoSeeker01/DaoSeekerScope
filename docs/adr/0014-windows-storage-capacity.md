# 0014 Windows 整盘容量

日期：2026-10-13。状态：已完成非提升权限探针，实现及验收结果另列。

## 路线

沿用 [ADR 0013](0013-storage-capacity.md) 的 StorageInfo：OS 暴露的整块设备容量，不是卷或文件系统可用空间，不相加推断物理总容量。Windows 通过 SetupAPI 枚举 present GUID_DEVINTERFACE_DISK 接口，使用 CreateFileW（desired access = 0、share read/write、OPEN_EXISTING）取得元数据句柄，再调用 IOCTL_DISK_GET_DRIVE_GEOMETRY_EX，直接读取 DiskSize；不通过虚拟几何参数相乘。真实零保留，负数与截断响应 InvalidData。

依据：[接口详情与不解析符号路径约束](https://learn.microsoft.com/en-us/windows/win32/api/setupapi/nf-setupapi-setupdigetdeviceinterfacedetailw)、[DeviceIoControl 元数据调用例](https://learn.microsoft.com/en-us/windows/win32/devio/calling-deviceiocontrol)、[扩展几何容量](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-ioctl_disk_get_drive_geometry_ex)。本机同一探针在受限执行环境中打开句柄返回 access denied；沙盒外、Windows token 未提升时枚举一项并实读 1000204886016 bytes。文档及探针不保证其他设备驱动、沙盒或普通用户均可访问。

能力 Partial/Setupapi，集合来源 Setupapi、容量来源 Win32。成功枚举无设备才返回 Available 空集合；枚举失败按集合报告，单项详情/打开/IOCTL 失败仅影响该设备字段。平台增强优先级仍为 100，高于通用后端。不新增公共字段、API、Source 变体、第三方包或锁定版本。

## 资源、所有权与隐私

- 枚举 max_entries + 1 次（默认 128、最大 1024），超限拒绝整个集合，不以成功前缀冒充完整枚举。先完成有界接口枚举，再逐个查询；不遍历猜测 PhysicalDrive 编号。
- 每项详情缓冲区固定 8192 bytes，一次查询，不按 RequiredSize 扩容；验证 SDK cbSize、对齐、路径偏移、返回大小和有界 UTF-16 NUL 结尾。符号路径仅原样用于打开设备，不解析为名称、序列号或 GUID，不写入日志或快照。临时 OS 缓冲区确实含标识，不声称从未进入内存。
- 默认 name 为 Restricted/PrivacyRedacted，不执行设备编号查询。仅 PrivacyOptions 双重显式授权时查询 IOCTL_STORAGE_GET_DEVICE_NUMBER，成功且为整盘设备后形成 PhysicalDriveN 名称；不返回接口路径、卷标或序列号。不请求磁盘读写权限、不读取内容、不查询 SMART。
- 设备信息集合与每个打开的句柄均独占拥有，通过 RAII 在成功、失败和取消返回时释放。同步 IOCTL 使用活跃且固定大小的输出内存；不引入取消异步 IO 后提前释放缓冲区的风险。
- 每次枚举、详情、打开和 IOCTL 前后检查截止时间/取消。core 限制调用方等待及并发 worker；同步驱动调用不能硬终止，失控驱动最多占用有界 worker，不能声称强制取消或已测坏驱动。
- 只在首次静态 collect 查询并缓存，包括失败字段；动态刷新不读 storage。设备变更或访问恢复需新建 Hardware，沿用原采集时间。枚举顺序不是持久身份，读取不是跨设备原子快照。

## 验收边界

要求 SDK 布局、路径/容量截断、负数/零、枚举限额、权限与不支持、单字段隔离、显式名称授权、取消、RAII 与静态缓存测试；本机非提升权限 CLI/C 和原生 Windows CI 至少读到一个正容量。Linux 存储及其资源/隐私回归不得退化。模拟资源释放测试不能替代原生长期泄漏或驱动超时测试，Miri/ASan Linux 不验证 Windows SDK unsafe 调用。

新增 windows-sys Windows 专用 features（SetupAPI、FileSystem、IO、Ioctl、Security）；其他平台不启用。MIT、Schema 1、C ABI 1 保持不变。macOS 存储仍 Unsupported，GPU/移动/Web/MCU 不扩大范围。
