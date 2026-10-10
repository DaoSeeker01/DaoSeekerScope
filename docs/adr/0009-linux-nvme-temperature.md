# 0009: Linux NVMe hwmon 温度路由

状态：实施决策；发布评审待完成。2026-10-11。补充 ADR0008，不扩大存储采集范围。

依据固定为 [Linux v6.8 NVMe hwmon 驱动](https://raw.githubusercontent.com/torvalds/linux/v6.8/drivers/nvme/host/hwmon.c) 的 read/is_visible/init 路径及 [NVMe Base 2.0e](https://nvmexpress.org/wp-content/uploads/NVM-Express-Base-Specification-2.0e-2024.07.29-Ratified.pdf) Figure212/213（文档页201/204）。驱动注册 name=nvme，将 SMART 的 Kelvin 转为毫摄氏度；temp1 是 Composite，temp2..9 是八个独立传感器。库不能再次减273.15。规范允许 Composite 是实现相关的计算值，未必对应任何物理点；独立传感器未实现时报告0 K。驱动初始化只暴露非零独立传感器，但后续读取没有零值过滤。

决策：仅新增 name=nvme 且通道1..=9 的路由，复用已有128字节整数解析、毫度/1000换算、数值接受边界、可选enable/fault与权限映射。更高通道保持Unsupported/NotSupported且不打开input。不强制整数Kelvin量化格点，以hwmon声明的毫摄氏度为交换单位；保留合法0°C与负摄氏度。

精确的-273150毫度不作为NVMe温度发布：独立通道2..9返回Unavailable/NotPresent，表示本次报告没有实现的温度值，不推断整个设备物理缺席；Composite通道1返回Unavailable/InvalidData，因为规范没有赋予其0 K相同的缺席语义。其他驱动保持ADR0008规则，不能全局拒绝绝对零度边界。失败没有值/采集时间，下一次刷新重新读取并可恢复，不保留旧值。

SensorInfo文档改为后端报告的摄氏度，明确可能包含设备计算值，不承诺物理点或校准准确度。Rust模型形状/签名与ABI1/Schema1不变，Schema仅description更新。能力仍Partial/SourceHwmon；字段状态必须逐项检查，集合Available不意味着各温度可用。默认标签仍Restricted/PrivacyRedacted，敏感选项也不读取标签、serial、device、uevent或磁盘标识；不访问/dev、不发ioctl、不写阈值。

复用ADR0008的四级枚举限额、取消/超时与TOCTOU边界。新增单位/全部九通道/零Kelvin区分/负值/字段隔离/拔插/恢复测试，扩展现有非root合成hwmon容器与属性fuzz；三平台原生结果单独记录，合成fixture不能证明真实NVMe温度读取或校准。无新依赖、feature或许可证变化：仅根据公开接口独立实现，不复制GPL内核代码。回滚只移除NVMe路由即可恢复Unsupported，CPU路由不受影响。
