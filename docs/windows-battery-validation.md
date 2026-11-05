# Windows 电池摘要验证

WindowsBackend 通过 GetSystemPowerStatus 获取系统级电池摘要，声明能力为 Partial。有可用摘要时返回一条记录，数量不代表实际电池数量。每次动态刷新重新调用接口，型号等静态信息继续使用缓存。字段含义依据[微软接口说明](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-system_power_status)。

## 状态与错误

电量 0–100 是有效百分比，AC 状态 0/1 分别表示离线和在线。两字段的 255 表示未知，返回 Unavailable/TemporarilyUnavailable；其他非法数值返回 Unavailable/InvalidData。一个字段无效时保留另一个字段的读数，充电标志不用于推断 AC 状态。

电池标志 255 表示无法确定摘要，整个集合暂不可用。系统明确报告无电池时返回 NotApplicable。API 调用失败仍走现有错误映射，失败输出不参与转换。数据来源为 Win32，默认不采集电池标识。

## 本机验证

提交 `c32b7f6` 对原有电池转换作两处行为修正，AC 的非法数值与未知值分别返回原因，电池能力声明从 Supported 改为 Partial。转换代码集中在私有 battery 模块，供实际 WindowsBackend 调用。

Windows crate 的 79 项测试通过，门面和 CLI 的 48 项测试通过，另有 1 项 CLI 夹具按原设计跳过直接运行。新增三个纯转换测试覆盖全部 256 种电量值、256 种 AC 值，以及无电池和未知标志。原生测试把 SDK 读取放在生产采集前后，在两次原始状态一致时核对结果，最多进行三轮对照。

干净提交的 SDK 对照测试通过，本机报告电量 100%、AC 在线，生产 CLI 的 JSON 同时通过 Schema、最低读取和默认隐私检查。fmt、严格 Clippy、Linux x64 交叉 check 和冻结契约检查通过。详细命令、日志校验值和字段结果见[验收数据](evidence/windows-battery-41950968745.json)。

## 验证边界

提交 `c32b7f6` 的[三平台定向 CI 41950968745](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/41950968745)已完成，三个桌面任务通过，五项未涉及任务按范围跳过。Windows 原生日志确认 SDK 对照测试通过。CI 日志记录了测试结果，具体读数保留在本机验证数据中。

未知值和非法值来自合成输入。当前本机对照没有验证拔插电池、API 故障注入或电量校准，不将 API 报告值作为电池健康度。MIT、C ABI 1、JSON Schema 1 为当前交付契约。
