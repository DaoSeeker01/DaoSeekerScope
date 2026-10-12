# 0013 存储对象、静态容量与 Linux 最小实现

日期：2026-10-12。状态：实现决策，原生读取及受限容器结果另列。

## 语义与路线

StorageInfo 表示 OS 暴露的整块存储设备，name 为 OS 设备名，capacity_bytes 为该对象的报告容量。不是文件系统总量/可用空间、挂载卷或分区模型。本轮不新增模型字段，不计算物理磁盘总量；虚拟块设备、device-mapper/RAID 层与底层盘可以同时出现，不能将条目简单相加。

Linux 只枚举 `/sys/block` 的一级条目并读 `size`，不递归读分区。内核 [块设备 ABI](https://www.kernel.org/doc/html/latest/admin-guide/abi-stable.html)、[固定提交的 size 实现](https://code.googlesource.com/linux/torvalds/linux/+/425af483523b76bc78e14674a430579d38b2a593/block/genhd.c)与[字节换算接口](https://github.com/torvalds/linux/blob/master/include/linux/blkdev.h)是单位/属性来源；size 的 sector 采用 512 字节计量，不能乘逻辑/物理 sector_size 或文件系统 block_size。使用检查乘法，合法零保留，负值、混合单位、非十进制、超长及溢出均为 InvalidData。能力 **Partial/Sysfs**：包括虚拟对象，不保证容器与设备可见性或物理拓扑完整。

Windows 后续研究 [IOCTL_DISK_GET_LENGTH_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-ioctl_disk_get_length_info)，需先验证非提升权限下的设备枚举、访问权限、句柄释放和有界 IOCTL；本轮不通过驱动器空闲空间 API 冒充设备容量。macOS 后续研究 [IOMedia 属性](https://developer.apple.com/documentation/iokit/iomedia_h_user-space/defines)的 Size/Whole，需验证公开用户态读取、CF/IOKit 所有权及沙盒。两平台保持 Unsupported，没有基于文档宣称已支持。

不启用 sysinfo disk feature：它的文件系统/挂载对象语义与本模型不同，且默认枚举/元数据路径不提供这里要求的资源和隐私边界。sysinfo 继续负责已有通用字段；无新第三方依赖或锁定版本/许可证变化。

## 隐私、缓存与资源

- 默认名称 Restricted/PrivacyRedacted，仅双重显式授权后转换目录名称；core 对自定义 backend 同样强制脱敏，保留字段来源。目录名必然以原始 OS 路径形式用于访问 size，不宣称名称从未进入内存；不读序列号、UUID、wwid、卷标、挂载路径、型号、backing_file 或文件内容。
- 静态首次采集并缓存。refresh_dynamic 不读取 storage；设备添加/移除/扩容及初次字段失败的恢复须新建 Hardware，不以旧值冒充实时。缓存保留原 observed_at。不新增空闲空间或吞吐量动态字段。
- 枚举最多 max_entries（默认 128，最大 1024），多出一条即 Unavailable/InvalidData，不返回成功前缀。每个 size 读取最多 129 字节，128 字节上限；拒绝非普通属性文件，包括符号链接/FIFO，类条目本身允许正常 sysfs 链接。检查元数据不能防止恶意替换的 TOCTOU，也不能硬取消阻塞的驱动读取，继续遵守核心 worker/等待上限。
- 枚举失败按权限/不存在/其他 IO 映射状态；单个 size 失败保留条目并按字段报告，不影响其他设备或 CPU/内存。成功空目录才表示 Available 空集合。对象名称不存在/非法只影响授权名称，不回退序列号或稳定标识。
- 顺序只是一次有界枚举的路径排序，不是稳定身份；没有原子一致性承诺。枚举前后及每个属性读前后检查取消/截止时间。

## 兼容与验证

公共签名、模型形状、Schema 1、C ABI 1 保持不变；默认 storage.name 从自定义 backend 获得值时会被脱敏，这是隐私收紧的行为变更，需在使用指南说明。项目仍 MIT，现有 Linux fuzzing feature 添加纯容量转换 hook，不读取 OS。

要求纯解析 fuzz、字段隔离/限额/取消/自定义隐私和缓存测试；Linux 原生 CLI/C 至少读取一个真实内核报告容量，另有非 root 只读容器内的合成 sysfs 权限拒绝、FIFO、失败恢复与静态缓存验证。合成数据不证明真实磁盘物理容量、硬件热插拔或故障驱动行为，Windows/macOS 交叉编译不等于存储实现。
