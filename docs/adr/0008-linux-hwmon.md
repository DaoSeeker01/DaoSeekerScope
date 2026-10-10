# 0008: Linux hwmon 温度最小闭环

状态：实施决策；发布评审待完成。2026-10-10。

现有 SensorInfo 仅有 label 与 temperature_celsius，不能把电压、RPM 或相对温控值放入摄氏度字段。Linux 提供 hwmon 类入口，但仅文件名不能证明物理单位。

依据：[hwmon ABI](https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-class-hwmon)、[接口说明](https://docs.kernel.org/hwmon/sysfs-interface.html)、[coretemp](https://docs.kernel.org/hwmon/coretemp.html)、[k10temp](https://docs.kernel.org/hwmon/k10temp.html)。接口说明明确存在 temp 文件以毫伏表达的热敏电阻通道；k10temp temp1 是相对 Tctl，temp2 是支持设备上的 Tdie。

决策：动态刷新重新枚举 /sys/class/hwmon/hwmon[0-9]+ 中的 temp[1-9][0-9]*_input。仅 name=coretemp 或 name=k10temp 且通道=2 转换有符号整数毫摄氏度。其他 name/通道不读取 input，返回 Unsupported/NotSupported。名称读取失败映射至各通道温度，不伪装成未知驱动；同一坏字段不抹去其他温度。coretemp 负值拒绝；Tdie 接受负值。通用数值保护范围 [-273150,1000000] 毫度（库的接受边界，不是硬件量程），不截断、不钳制。缺失 enable/fault 为可选属性；存在时必须严格 0/1，enable=0 或 fault=1 返回 TemporarilyUnavailable。

label 默认 Restricted/PrivacyRedacted，不读取 name 之外的设备标签、路径、serial、uevent 或 device。name 仅供固定单位路由，不输出其原始值，敏感选项也不扩大此切片采集面。保留 collection=Available 的已枚举条目，包括其温度失败；目录枚举失败则 collection 不可用，不能描述不完整集合为完整。空可读集合才 Available/空数组。来源 Hwmon；能力 sensors=Partial。排序仅保证一次刷新顺序，索引不是设备标识。

资源边界：类入口最多256个，每芯片目录最多1024个条目，所有芯片合计最多4096个目录条目；输出遵循 Options.max_entries；单属性最多128字节（多读1字节检测超限），任何枚举超限丢弃不完整前缀返回 InvalidData。类设备允许符号链接，属性要求自身为普通文件，拒绝未变化的FIFO/设备/目录/属性链接；不能消除恶意TOCTOU。操作前后检查已有取消/超时上下文，不承诺能硬取消阻塞驱动读取。动态刷新不读取公共静态字段。

不引入 libsensors：首版明确限制温度路由，不处理用户配置、热敏电阻电压换算、主板校正、风扇或阈值。未来扩展按驱动资料与实际证据逐个加入；不得将 Unsupported 通道改成猜测摄氏度。无需新依赖、feature、公共类型或 ABI/Schema 主版本变化；仅模型文档与 Schema description 元数据更新。

验收：跨平台 fixture 测试、Linux 非root容器真实权限/FIFO/目录失败与连续恢复、单位/限额/隐私/静态缓存验证、属性 fuzz、三桌面 CI 原生探针。合成 fixture 不是物理温度计验证；真实 runner 观测需单独归档。回滚可移除 sensors 能力与本模块，保持既有 Unsupported 行为。
