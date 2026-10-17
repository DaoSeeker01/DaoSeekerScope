# ADR 0020：Linux DRM 连接视图与授权 EDID 名称

状态：开发版有限实现，本轮三平台 CI 与 26 项合成容器场景已验收；实体 Linux/当前模式仍待验证，不承诺完整显示器信息。见[验证记录](../linux-display-validation.md)。

## 采集范围

只读取 `/sys/class/drm/cardN-<connector>/status`，返回 connected 的连接器视图。不是活动扫描输出、物理显示器总数或桌面布局；同一显示器可能有多个连接器/虚拟对象。能力为 Partial/Drm。disconnected 排除，unknown/无法读取任一候选状态时整个集合返回缺失状态，不用成功前缀或空列表掩盖未知连接器。

`modes` 是候选模式列表；`enabled` 仅关联编码器，不足以证明当前模式。当前 width_pixels/height_pixels 均 Unsupported/NotSupported、Source Drm，不从首选模式、EDID 时序、fbdev virtual_size 或 debugfs 推断。后续 DRM ioctl/显示服务器方案须独立评估访问权、DRM master、探测副作用和有界分配，再扩充当前尺寸。

## 隐私与 EDID

EDID 原始块含序列号等标识，默认不打开、不检查 EDID 文件。name 为 Restricted/PrivacyRedacted、Source Sysfs。仅当 PrivacyOptions 同时显式请求敏感信息并声明调用方已授权，才读取 cached sysfs EDID 的首个 128-byte 基础块；操作系统权限仍生效，不写 status、不强制探测、不打开 `/dev/dri`。

独立解析 EDID 1.3/1.4 基础块的 header、checksum 和四个 18-byte 描述符，只返回 0xfc 产品名称。0xff 序列号描述符、数值序列号、厂商/产品 ID 不解析、不导出、不写日志。只读基础块，不验证/解析扩展块或完整 EDID 的长度；不得把这称为完整 EDID 验证。名称最多 13 ASCII bytes，允许末尾 LF 与空格填充，拒绝 NUL/控制字符、空白、冲突的名称及占位名称。缺失名称为 NotPresent，错误格式/校验和为 InvalidData，其他 EDID 版本 Unsupported。缓存 EDID 可被系统/固件覆盖，不保证物理设备身份。

格式事实以 Linux 公开结构与 sysfs 接口为依据，独立实现解析与合成 fixture，不复制 GPL 内核或 edid-decode 实现，无新依赖或许可证变化，项目仍 MIT。

## 边界、缓存与验证

最多扫描 4096 个类入口、1024 个候选连接器，输出另受 Options.max_entries 默认 128/最大 1024 限制，超限拒绝整个集合。状态最多读取 33 bytes（合法负载上限 32）；EDID 最多 128 bytes。属性必须为普通文件且不是符号链接，拒绝 FIFO/设备文件。类目录的正常连接器符号链接可跟随；不构建恶意文件系统 TOCTOU 沙箱。

两次状态检查围绕名称读取，连接状态变化拒绝为 TemporarilyUnavailable；不是跨文件原子快照，也不能排除 ABA。状态损坏/读取失败阻止完整枚举，名称单字段失败不影响已确认的连接条目。静态成功、空集合和失败都缓存；refresh_dynamic 不重扫，变化/权限恢复后新建 Hardware。调用方等待/取消检查有界，不能强制中止同步 sysfs/驱动或限制平台内部所有分配。

公共模型、Schema 1、C ABI 1、锁和依赖不变；复用默认关闭的隐藏 fuzzing feature 和既有 dmi_text 目标。CLI 通过既有 JSON 查看，敏感选项沿用警告与双重显式请求。默认视图只有连接条目计数及缺失状态，不能宣称读到了名称或分辨率。macOS 显示器仍 Unsupported。

验收包含解析/隐私/缓存/限额单测、JSON/FFI、非 root 只读容器权限/FIFO/恢复场景、授权解析与默认从不读取 EDID 的证据，以及真实 Linux runner 读取（无连接器则如实记空）。合成 EDID 和容器挂载不能冒充真实显示器；实体 Linux、热插拔、MST、多显示器、当前模式仍待独立验证。

## 官方来源

- [sysfs status/edid/modes 与连接器命名](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/drm_sysfs.c)。
- [EDID 字段与名称/序列号标签](https://github.com/torvalds/linux/blob/master/include/drm/drm_edid.h)。
- [sysfs EDID 缓存读取](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/drm_edid.c)。
