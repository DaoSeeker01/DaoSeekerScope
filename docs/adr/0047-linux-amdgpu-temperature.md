# 0047 Linux amdgpu 温度通道

日期：2026-10-31。状态：实施决定；实体设备验证待完成。

已有 hwmon 读取器按驱动限制摄氏度通道，避免把相对温控值或电压误当温度。本轮加入 `name=amdgpu`、通道 1–3；只读取枚举中实际存在的 `tempN_input`，不补齐缺失通道，也不据通道数量判断 GPU 型号或 APU/dGPU 类型。

依据是[内核接口文档](https://docs.kernel.org/gpu/amdgpu/thermal.html)和 [Linux v6.12 驱动实现](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/pm/amdgpu_pm.c)。温度输入单位为毫摄氏度，额外通道依设备而定。既有有符号整数转换、数值保护、enable/fault、条目和单属性上限继续适用；保护范围不是硬件量程。标签、serial、unique_id 等仍不读取，不新增稳定标识或 GPU 归属推断。

驱动的传感器读取函数在重置或部分挂起状态也可能返回 EPERM。仅凭读错误无法区分这些状态与策略拒绝，因此 amdgpu **读取阶段**的 EPERM 返回 Unavailable/Unknown；metadata/open 阶段权限错误以及 EACCES 保持 Restricted/PermissionDenied。读取阶段的 WouldBlock/ResourceBusy 与 ENODATA 返回暂不可用，Unsupported 和 TimedOut 分别保留不支持与超时语义；其他错误不猜测原因。其他驱动原有分类不变。

只读 sysfs 查询可能触发驱动的运行时电源恢复。库不写入电源、时钟、风扇或性能策略，不承诺读取不会唤醒设备，也没有本轮实际硬件的耗时或功耗结论。阻塞读取仍受既有调用方等待与 worker 资源边界约束，不承诺硬终止原生调用。

Rust 字段、枚举、函数签名、依赖、features、MIT 和 ABI 1 不变。`SensorInfo.temperature_celsius` 的说明增加驱动覆盖，生成 Schema 只有一处 `description` 差异；类型、范围、必选项和其他校验约束逐项相同，因此硬件 Schema 仍为 1，不需要数据迁移。[元数据评审](../evidence/amdgpu-schema-review-2026-10-31.json)记录唯一差异路径和前后哈希，再更新冻结基线；这不是绕过兼容性检查或批准发布。

验收包括通道/单位/零值、损坏单通道、未提供通道、隐私、刷新、静态缓存和上限回归；Linux 另验证 errno 分类及非 root 权限/FIFO/恢复。fixture 是合成输入和真实文件系统权限，不是 AMD 设备或真实温度证据。回退可删除 amdgpu 路由与专用读取错误分类，恢复这些通道的 Unsupported；历史报告保留。
