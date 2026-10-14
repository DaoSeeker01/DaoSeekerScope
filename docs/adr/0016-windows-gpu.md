# ADR 0016：Windows GPU 最小采集

状态：开发版实现契约；维护者最终评审仍待完成。

## 决定

使用已锁定的 windows 0.62.2 SDK 绑定，经 CreateDXGIFactory1、EnumAdapters1、GetDesc1 采集两个既有字段：适配器产品描述和独占显存字节数。公共 Rust 模型、ABI 1 和 JSON Schema 1 的形状不变，仅补充字段文档。依赖限制在 Windows target，关闭默认 features，启用 std/Foundation/Dxgi/Dxgi_Common。项目许可证仍为 MIT；该依赖保留 MIT OR Apache-2.0。

来源为 Dxgi，能力为 Partial。独占显存不包含 CPU 共享内存，不是使用量、可用量或预算；驱动报告的零是真实值。名称是产品描述，不保证唯一。只依据 SOFTWARE 标志过滤软件适配器，不能依据名称或零 PCI ID 判断软件。虚拟、远程适配器不保证对应物理显卡；顺序不提供稳定身份。

SDK 返回的描述符暂时包含 PCI ID 和 LUID；不记录、不导出、不缓存这些字段，仅保留上述投影。COM 接口由 SDK 所有权包装释放，工厂和适配器全部在单次 worker 调用内创建及销毁，不存入 Backend、不跨线程传递。不得在 DllMain 中调用采集。

## 状态、边界与缓存

只有 EnumAdapters1 的 NOT_FOUND 表示枚举完成。完整空集合为 Available，表示当前没有可见的非软件条目。工厂、枚举或描述符调用失败不返回成功前缀；对应集合返回 Restricted/Unsupported/Unavailable，其他硬件类别仍可采集。权限拒绝、暂不可用、原生超时、无效数据和未知失败使用既有原因码，不输出原始错误字符串。

名称必须在固定 128 个 UTF-16 单元内终止、编码有效、非空且无控制字符；名称错误仅影响该字段，显存仍可用。最多扫描 4096 个适配器（包含软件），输出上限使用 Options.max_entries（默认 128，上限 1024），额外探测一项确认是否超限。超限返回 Unavailable/InvalidData，不返回截断成功集合。

检查取消和截止时间围绕每次原生调用。同步驱动调用不能被强制中断；统一入口的等待超时和 16 个 worker 配额仍适用，不能宣称终止了底层驱动线程。该路径为静态采集，refresh_dynamic 不重复枚举；驱动、设备成员或首次失败变化后需新建 Hardware。组合策略保持不变：Unsupported 增强不替换默认 Unsupported/Custom 占位，其他已观察状态保留 Dxgi 来源。

## 依据与验证边界

依据微软 [CreateDXGIFactory1](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/nf-dxgi-createdxgifactory1)、[EnumAdapters1](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/nf-dxgi-idxgifactory1-enumadapters1)、[GetDesc1](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/nf-dxgi-idxgiadapter1-getdesc1) 和 [DXGI_ADAPTER_DESC1](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/ns-dxgi-dxgi_adapter_desc1)。独立 SDK 探针已在本机非提升令牌下成功，后续生产入口验收另列，不把探针算作库验收。

纯逻辑测试覆盖标志过滤、非法 UTF-16、真实零值、错误分类、中途失败、扫描与输出上限、取消。原生 CI 允许无 GPU 或受限状态并记录；只有实际 Available 字段才算设备读取证据。Linux/macOS GPU、驱动动态显存预算、热插拔刷新均不属于此切片。
