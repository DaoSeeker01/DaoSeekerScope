# ADR 0017：Linux DRM 设备视图、GPU 名称和 Xe 专用显存

状态：开发版实现契约，最终公共契约评审仍待维护者完成。

## 范围与来源

LinuxBackend 提供静态 `gpus`，能力为 Partial/Drm。枚举 `/sys/class/drm` 的 `cardN` 与 `renderDN`，按规范化后的 `device` 路径去重，忽略连接器和其他属性。视图可能包含显示控制器、软件和虚拟设备，仅覆盖 DRM 可见设备。完整空视图返回 Available 空集合，路径缺失或权限受限分别返回对应状态。

依据内核 [DRM 用户接口](https://docs.kernel.org/gpu/drm-uapi.html)。驱动提供的属性不同，不能用驱动名、card 编号或 PCI ID 冒充产品型号：

- amdgpu：只读 `device/product_name`，来源 Sysfs。内核 [AMDGPU 文档](https://docs.kernel.org/gpu/amdgpu/driver-misc.html)明确它只在部分服务器卡上提供；缺失为 Unavailable/NotPresent。
- nvidia：按内部 PCI 位置定位 `/proc/driver/nvidia/gpus/<位置>/information`，来源 Procfs。只读取第一行并要求 `Model:` 前缀，至换行即停止，不读后面的 UUID/固件等字段。依据 NVIDIA [proc 接口文档](https://download.nvidia.com/XFree86/Linux-x86_64/580.95.05/README/procinterface.html)及[官方模块实现](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/main/kernel-open/nvidia/nv-procfs.c)。格式变化返回缺失，不扫描后续行或猜测。
- 其他驱动或无绑定驱动：name 为 Unsupported/Drm；无法读取路由信息时保留对应错误。驱动名不作为产品名称。

## Intel Xe 专用显存

Linux x86_64 和 arm64 的 Xe 路径仅打开与该 GPU 对应的唯一 `/dev/dri/renderDN`。它核对字符设备的主次设备号，打开后再次核对设备号和 sysfs 设备路径，再用 `DRM_IOCTL_VERSION` 确认驱动为 Xe。节点以只读、非阻塞方式打开，拒绝末端符号链接。普通用户仍需拥有节点访问权限。

Xe 的 `DRM_XE_DEVICE_QUERY_MEM_REGIONS` 把设备本地显存和共享系统内存分为不同类别。先查响应长度，再读取最多 32 个区域、2824 字节。容量取 VRAM 区域的 `total_size` 之和，即驱动报告的可用容量。ABI 响应同时包含使用量和 CPU 可见容量，采集器只解析容量所需字段。有效响应只有系统内存时返回 NotApplicable/NotPresent。驱动报告的 VRAM 零容量可以作为真实值。依据 [Linux v6.12 Xe UAPI](https://docs.kernel.org/6.12/gpu/driver-uapi.html#intel-xe)、[内核查询实现](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/xe/xe_query.c)。

节点缺失返回 Unavailable/NotPresent，权限不足返回 Restricted/PermissionDenied，节点与枚举身份不匹配返回 TemporarilyUnavailable，歧义路由、未知内存类别、重复区域和长度错误返回 InvalidData。错误仅影响该 GPU 的显存。其余驱动和未接入此查询的架构返回 Unsupported/Drm。

## 边界与状态

每次采集最多扫描 4096 个目录条目，忽略项和重试都计入总数。一次扫描最多保留 Options.max_entries 个去重设备（默认 128，最大 1024）。名称最多 4096 字节，严格 UTF-8，拒绝空值、控制字符和明确未知占位文本。只接受普通属性文件，拒绝 FIFO、目录及末端符号链接。NVIDIA 使用无预读的一字节读取直到首个换行，空首行为暂不可用，过长或格式错误为 InvalidData。

已枚举的设备路径在解析期间缺失时，丢弃第一次结果，在原采集期限内从头扫描一次。第二次仍缺失时返回 Unavailable/NotPresent。权限错误和无效数据立即返回相应状态。只有完整扫描才返回设备列表。设备已确认后的路由或名称读取失败仅影响该字段，其他条目及 CPU/内存可继续返回。规范化路径、PCI 位置只用于本次内部关联，不输出、不日志、不缓存为设备标识，不读取 serial_number、unique_id、product_number 或 PCI vendor/device 属性。名称是驱动报告的产品描述，不是稳定身份。

上下文检查围绕文件操作及每次循环。同步内核调用不能被强制中止；统一入口的等待超时与 worker 配额仍适用，普通文件检查不构成抵御任意恶意挂载或竞态替换的文件系统沙箱。动态刷新不重扫 GPU；成功和失败静态结果均缓存，需新建 Hardware 才重读。FFI NULL options 复用缓存，有效非 NULL options 每次独立采集。

## 兼容与验证

Rust 签名、C ABI 1、Schema 1 保持兼容。Linux Xe 查询复用 workspace 已锁定的 `libc`，只在支持架构上编译。两处 ioctl 调用集中在 Xe 模块，其他 Linux 采集代码继续禁止使用 unsafe。名称解析继续复用现有 `dmi_text` fuzz 目标。

验证覆盖合成 sysfs/procfs、真实内核文件类型和权限、Xe 响应解析、长度握手、静态缓存、三平台 CI 及 CLI/C/Python。驱动报告的设备名称和 Intel Xe 专用显存容量还需对应的实体设备验证。
