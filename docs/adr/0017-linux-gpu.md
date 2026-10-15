# ADR 0017：Linux DRM 设备视图与 GPU 名称

状态：开发版实现契约，最终公共契约评审仍待维护者完成。

## 范围与来源

LinuxBackend 增加静态 gpus，能力 Partial/Drm。枚举 `/sys/class/drm` 的 `cardN` 与 `renderDN`，按规范化后的 `device` 路径去重；忽略连接器和其他属性，不打开 `/dev/dri`，不执行 ioctl、外部命令、PCI 数据库查询或管理员操作。视图可能包含显示控制器、软件和虚拟设备，不是物理显卡数量，也不保证覆盖未绑定 DRM 的 GPU。完整空视图是 Available 空集合，缺路径或权限受限必须单列状态。

依据内核 [DRM 用户接口](https://docs.kernel.org/gpu/drm-uapi.html)。驱动提供的属性不同，不能用驱动名、card 编号或 PCI ID 冒充产品型号：

- amdgpu：只读 `device/product_name`，来源 Sysfs。内核 [AMDGPU 文档](https://docs.kernel.org/gpu/amdgpu/driver-misc.html)明确它只在部分服务器卡上提供；缺失为 Unavailable/NotPresent。
- nvidia：按内部 PCI 位置定位 `/proc/driver/nvidia/gpus/<位置>/information`，来源 Procfs。只读取第一行并要求 `Model:` 前缀，至换行即停止，不读后面的 UUID/固件等字段。依据 NVIDIA [proc 接口文档](https://download.nvidia.com/XFree86/Linux-x86_64/580.95.05/README/procinterface.html)及[官方模块实现](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/main/kernel-open/nvidia/nv-procfs.c)。格式变化返回缺失，不扫描后续行或猜测。
- 其他驱动或无绑定驱动：name 为 Unsupported/Drm；无法读取路由信息时保留对应错误。驱动名不作为产品名称。

独占显存字段本切片仍为 Unsupported/Drm。AMDGPU 的 VRAM 统计不能普遍证明现有字段所承诺的排除共享内存语义，尤其统一内存设备；不映射它、不读取 GTT、不估算容量。今后需要可靠的设备分类或单独的内存语义后再扩展，不改变现有 GpuInfo 字段含义。

## 边界与状态

最多扫描 4096 个目录条目（包括忽略项），最多保留 Options.max_entries 个去重设备（默认 128，最大 1024）。名称最多 4096 字节，严格 UTF-8，拒绝空值、控制字符和明确未知占位文本。只接受普通属性文件，拒绝 FIFO、目录及末端符号链接。NVIDIA 使用无预读的一字节读取直到首个换行，空首行为暂不可用，过长或格式错误为 InvalidData。

枚举/去重身份解析不完整时整个集合返回缺失，不返回成功前缀。设备已确认后的路由/名称读取失败仅影响该字段，其他条目及 CPU/内存可继续返回。规范化路径、PCI 位置只用于本次内部关联，不输出、不日志、不缓存为设备标识，不读取 serial_number、unique_id、product_number 或 PCI vendor/device 属性。名称是驱动报告的产品描述，不是稳定身份。

上下文检查围绕文件操作及每次循环。同步内核调用不能被强制中止；统一入口的等待超时与 worker 配额仍适用，普通文件检查不构成抵御任意恶意挂载或竞态替换的文件系统沙箱。动态刷新不重扫 GPU；成功和失败静态结果均缓存，需新建 Hardware 才重读。FFI NULL options 复用缓存，有效非 NULL options 每次独立采集。

## 兼容与验证

不增加依赖、unsafe、默认 feature 或公共模型字段。Rust 签名、C ABI 1、Schema 1 不变；Linux GPU 从 Unsupported 转为有限的 DRM 视图。复用默认关闭的 fuzzing 隐藏入口，将两个名称解析器加入现有 dmi_text 目标，不增加 fuzz 目标数量。

验证使用跨平台纯解析测试、Unix 合成 sysfs/procfs 与真实内核权限/符号链接/FIFO 测试、静态缓存回归、三平台原生 CI、CLI/C/Python 和归档验收。CI 无设备的空集合不算 GPU 名称真机读取；维护者实体 Linux/AMD/NVIDIA 设备测试继续延期，不能据此宣称完整 Linux GPU 支持。
