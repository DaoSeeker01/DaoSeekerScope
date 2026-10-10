# 0001 公共模型（0.1 草案，实施审查完成，尚未经维护者发布评审）

日期：2026-10-08。范围：桌面基础库最小闭环。调研当日目标仓库当前账号查询 404；本地无既有工作区/API/feature/测试/fuzz/LICENSE/Git 历史可迁移。不创建移动、Web 或 MCU 空壳 crate。2026-10-09已获授权创建私有仓库并通过三平台原生CI，见[验收记录](../ci-validation.md)。

选择：主 crate `daoseeker-scope` 为门面；core 只依赖可选 serde/schemars，禁止平台依赖、unsafe。同步 Backend 返回自有 StaticSnapshot / DynamicSnapshot，Hardware 使用一个常驻工作线程，静态首次成功后缓存，collect 合并缓存与一次动态读取。snapshot 的时间指采集结束，不保证 OS 多 API 原子一致；每字段带独立时间。bytes 为字节、seconds 为秒、percent 为 0..100、温度为 Celsius。

Observed 私有字段，通过 available / missing 构造，Available 必有值与时间，其余必无值；反序列化同样校验。Source、ReasonCode、Availability、CapabilityLevel、ErrorCode 使用 non_exhaustive；JSON 小写 snake_case，未知枚举拒绝，未知对象属性忽略，新增字段必须可默认并更新黄金样例/Schema。schema_version=1；新增枚举值需要 Schema 主版本协商，因为旧解码器明确拒绝未知值；破坏变化增主版本。0.1 API 不宣称 1.0 稳定，发布前需要维护者审阅这些 ADR。

CPU 型号/逻辑核数/物理核数/架构、OS 名称/版本/kernel、可用总内存、平台型号/厂商/固件为静态；占用率/可用内存/运行时长/电池/传感器为动态。设备序列号作为受控敏感字段；MAC/UUID/磁盘序列号本切片不采集也不提供空字段。GpuInfo、StorageInfo、NetworkInfo、DisplayInfo 仅定义有可靠未来来源的最小类型，集合默认 Observed Unsupported；不把模型存在描述成实现。SystemInfo 组合 OS/Device/CPU/Memory/Motherboard/Firmware；RuntimeInfo 独立动态；无进程/用户/主机名采集。

替代：直接暴露 sysinfo（破坏可替换性）；Tokio（本切片不需要）；独立刷新全部静态信息（无谓成本）。回滚：替换适配层不改变模型；未来扩展先评审 Schema 与来源。
