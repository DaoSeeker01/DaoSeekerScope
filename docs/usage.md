# 使用指南

DaoSeekerScope 在本机采集 Windows、Linux、macOS 的系统信息。当前为未发布的 0.1 开发版，请从源码使用；支持范围见[能力矩阵](adr/0005-platform-support-matrix.md)。

## Rust

克隆仓库后，在应用的 Cargo.toml 中添加本地依赖，按实际目录调整路径：

```toml
[dependencies]
daoseeker-scope = { path = "../DaoSeekerScope/crates/daoseeker-scope" }
```

```rust
fn main() -> Result<(), daoseeker_scope::ScopeError> {
    let hardware = daoseeker_scope::Hardware::new()?;
    let snapshot = hardware.collect()?;
    let brand = &snapshot.static_info.system.cpu.brand;
    println!("CPU: {:?}; state: {:?}", brand.value(), brand.availability());

    // CPU 占用率需要两次有效采样；首次或过早读取会暂不可用。
    std::thread::sleep(std::time::Duration::from_millis(300));
    let dynamic = hardware.refresh_dynamic()?;
    println!("CPU usage: {:?}", dynamic.cpu_usage_percent.value());
    hardware.shutdown()?;
    Ok(())
}
```

`collect()` 首次采集静态信息，之后使用静态缓存并刷新动态字段。`refresh_dynamic()` 需要先成功调用一次 `collect()`。型号、核数和设备列表属于静态数据；CPU 用量、可用内存、网络计数、电量、温度和运行时长按需刷新。

成功快照中的静态字段及其不可用状态都会缓存。核心在提交结果前检测到整次采集失败、取消或超时时，不建立本次静态缓存，已有缓存保留；取消不会撤销已经提交的结果。权限、设备、显示模式或内存容量变化后，重建 `Hardware` 重新采集。

核心在准备好快照并取得能力状态锁后，再检查一次取消和期限，然后提交缓存与能力；接收响应后也会复核。若 worker 已在有效期限内完成提交，但调用方稍后才取消或收到响应，调用方仍可能得到取消/超时错误，此时不会回滚已经有效提交的缓存。

一次快照包含多个系统调用，不保证所有字段同一时刻读取。动态采集失败不会假装返回上次的有效值。

### 处理操作错误

构造、采集、关闭和 JSON 函数通过 `ScopeError` 返回操作错误。用 `error.code` 判断错误类型；`error.to_string()` 提供可直接显示的脱敏说明，例如 `invalid options or input`。提示文字可能调整，程序不要据此分支或重试。超时和取消的提示会提醒后台工作可能仍在运行，具体限制见下文。

字段不可用仍通过成功快照中的 `Observed<T>` 表达。CLI 沿用相同错误说明和现有退出码；C ABI 保留独立的状态码及线程局部错误文本。

### 判断字段是否可用

`Observed<T>` 包含值、状态、来源、采集时间和原因。程序应先判断 `value()` 或 `availability()`，不要把缺失值自动替换为零。

| 状态 | 含义 |
|---|---|
| `Available` | 成功取得值；零或空集合也可能是真实结果 |
| `Unavailable` | 已有采集路径，但这次没有得到有效值；可能暂不可用、数据损坏或路径缺失 |
| `Restricted` | 受到隐私策略、权限或沙盒限制 |
| `Unsupported` | 当前 backend 没有实现该字段 |
| `NotApplicable` | 已确认不适用，例如 Windows 明确报告无电池 |

能力查询说明实现范围，不保证机器必然有某个设备。成功采集后，能力会结合实际来源和限制更新。空列表只表示本次成功枚举的可见条目为空；无法枚举时返回缺失状态。

### 资源与超时

默认超时 2 秒、每类最多 128 个条目。`Options` 允许 1 毫秒至 60 秒、1 至 1024 个条目，也可用 `CancelToken` 取消等待。

需要取消时，为本次调用创建 `CancelToken`，将其传给 `collect_with` 或 `refresh_dynamic_with`；取消按钮或另一个线程持有它的克隆并调用 `cancel()`。已取消的 token 不能重置，重试时使用新 token。核心检查到取消时会返回 `Cancelled`，即使 backend 同时返回错误，也不应把这次取消误认为设备读取故障。

每个实例有一个采集 worker，全进程最多 16 个；并发调用可能返回 `Busy`。超时和取消限制调用方的等待，不能杀死阻塞中的系统 API；阻塞 worker 继续占用额度。需要结束整个采集进程时，可使用下述 CLI 隔离模式。详见 [ADR 0003](adr/0003-capability-and-error-model.md)。

Rust 调用方可用 `hardware.shutdown()?` 消费采集器，等待采集循环退出和 backend 资源释放；等待预算为该实例的 `Options::timeout`。成功关闭后，已经取得的快照仍可使用。返回 `Timeout` 时，该句柄已消耗，阻塞任务仍可能继续占用配额；backend 析构发生可展开 panic 时返回 `Panic`。直接丢弃实例仍不会等待关闭。

关闭确认不涵盖操作系统线程或线程局部变量的最终收尾，不表示整个动态库可以卸载。C ABI 1 没有新增关闭入口，仍须保持库加载至进程结束。

## 命令行

```sh
cargo install --locked --path crates/daoseeker-scope-cli
dscope cpu
dscope memory
dscope disk
dscope display
dscope --json
dscope --help
```

也支持 `gpu`、`network`、`battery`、`sensors`、`system` 和 `capabilities`。文本显示所选类别；所有 `--json` 命令都输出完整快照。`cpu` 等待至少 300 毫秒取得第二次采样，其他命令保留首次 CPU 暂不可用状态。

退出码：0 为命令成功，结果仍可包含不可用字段；2 为参数错误；3 为采集或输出错误。管道接收端关闭时正常结束。

文本保留来源和原因，例如 `Available bytes: 0 (Procfs)`、`Name: Restricted (Sysfs, PrivacyRedacted)`。条目编号仅代表本次顺序，不是设备的稳定身份。程序集成使用 JSON，不解析文本格式。

### 在独立进程中采集

自动化脚本需要在超时后结束采集任务时，使用 `--isolate`：

```sh
dscope --isolate --json --timeout-ms=10000
dscope cpu --isolate --timeout-ms=1000
```

`--timeout-ms=N` 接受 1–60000 的十进制整数，默认 2000。隔离模式只启动当前 `dscope` 自身，沿用相同的公共 API、字段状态和隐私选项；父进程验证完整 JSON 和子进程成功退出后，才输出 JSON 或所选文本。输出超过 1 MiB、无效 JSON、子进程失败或超时时返回退出码 3，不输出部分结果。

预算从启动子进程前开始计时，包括 CPU 命令的两次采样和至少 300 毫秒间隔。到期后请求终止子进程，再用最多 1 秒确认退出并回收；未确认时，错误会给出进程号，便于检查 OS 进程状态。子进程已启动父管道监测后，管道关闭也会使它退出。

这不是实时期限或通用沙盒：操作系统的进程创建不能在中途取消，JSON 校验在有界输入上同步完成，最终终端写入不受采集预算控制；无法保证立即结束不可中断的内核操作，也不管理任意后代进程。默认仍在当前进程采集，此时超时按每次库调用计算。Rust 库和 C ABI 的阻塞调用、动态库卸载限制不变。

Linux 二进制应在兼容的用户空间中构建，再到目标环境验证。CI 使用固定 Debian 12 镜像链接 CLI/SDK 候选，原生测试保留在 Ubuntu 24.04；直接在更新的 glibc 上链接可能增加加载要求，即使未使用 `--isolate` 也会受影响。

### 容易误解的数据

- **存储**：整设备容量，不是文件系统可用空间。虚拟对象和底层设备可能重叠，不能把条目容量相加当作物理总量。文本同时显示精确字节数和 KiB/MiB/GiB。
- **显示器**：Windows 提供目标信号的活动像素，macOS 提供当前模式像素；都不保证是面板原生分辨率、DPI 逻辑尺寸或物理显示器数量。Linux 当前像素尺寸未实现。
- **GPU**：Windows 独占显存不是实时用量；Linux 仅有有限 DRM 枚举及部分 AMD/NVIDIA 名称，显存未实现；macOS 统一内存设备的独占显存可为不适用，不能用工作集预算代替容量。
- **网络**：累计字节数，不是速率。计数可能重置，接口顺序可能变化；Linux 限当前命名空间，其他平台也不保证覆盖所有逻辑接口。
- **Windows 电池**：返回 GetSystemPowerStatus 的系统级摘要，能力为 Partial，最多一条记录。它不表示电池数量。电量与 AC 状态分别判断，未知值返回 TemporarilyUnavailable，非法数值返回 InvalidData。系统报告没有电池时为 NotApplicable，无法确定是否有电池时为 Unavailable。[微软接口说明](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-system_power_status)
- **macOS 电池**：只返回系统公开的内置电池。电量按当前容量与最大容量的比值计算；`on_ac_power` 表示系统报告外部供电，不表示正在充电，也不区分电源适配器或 USB-C。UPS 不包含在内；空列表不证明机器物理上没有电池。
- **macOS 内存**：可用量是非压缩页等计算得到的估计，不等于系统保证可立即分配的内存。
- **Linux 温度**：另支持 JC42、SPD5118 和 LM75/LM75A/LM75B 的单个 `temp1_input`。它们是驱动提供的传感器读数，不根据总线位置推断 CPU 或主板测点，不保证覆盖每根内存条。驱动可能缓存读数；库不扫描 I²C、不加载模块、不读取 SPD/EEPROM 或告警寄存器。

更多平台细节见[能力矩阵](adr/0005-platform-support-matrix.md)和[验证目录](README.md)，使用入口不重复每轮历史测试次数。

## JSON

Rust 使用 `to_json` / `from_json` 交换 Schema v1。输入和展开后的输出均限 1 MiB。未知对象字段忽略，未知枚举值或错误版本拒绝；还会检查数值、字符串、集合及内存关系。显示像素尺寸为正整数，缺失时使用状态而非零。

CLI 通常在 JSON 后添加换行；编码恰好达到 1 MiB 时省略换行，保证原始输出仍能直接传给 `from_json`。不要依赖换行判断 JSON 是否完整。

[JSON Schema](schema/snapshot-v1.schema.json)用于交换验证，不能代替 Rust 的全部领域检查。ABI、Schema 和 Rust 包版本分别管理，见[发布路线](release.md)。

## C 与 Python

运行 `cargo build --locked -p daoseeker-scope-ffi` 构建共享库。使用 [C 头文件](../bindings/daoseeker_scope.h)、[C 示例](../examples/collect.c)和 [Python 示例](../examples/collect.py)；C 编译命令见[贡献指南](../CONTRIBUTING.md)。Python 示例只需标准库：

```sh
# Windows
python examples/collect.py target/debug/daoseeker_scope_ffi.dll
# Linux
python examples/collect.py target/debug/libdaoseeker_scope_ffi.so
# macOS
python examples/collect.py target/debug/libdaoseeker_scope_ffi.dylib
```

按 `len` 读取 UTF-8 Buffer，它没有 NUL 结尾。用 `dsc_buffer_free` 释放，原结构随后清零；空释放可重复，陈旧复制会被拒绝。最多保留 64 个未释放 Buffer，不得在另一线程读取时释放同一块内存。

NULL options 复用采集器；非 NULL options 每次新建实例，CPU 可能没有采样基线。ABI v1 没有 shutdown，任何采集调用后（包括失败或超时）都应保持共享库加载到进程结束；释放全部 Buffer 不代表后台 worker 已停止。本版不支持运行中的卸载或热重载，详见[所有权契约](adr/0004-c-abi.md)。

候选 SDK 包含共享库、头文件、示例和 Schema，尚未正式分发。构建与安装验证见 [Windows SDK](windows-ffi-sdk-validation.md)和 [Linux SDK](linux-ffi-sdk-validation.md)。

## 隐私与授权

序列号默认不读取，网络接口名和存储设备名称默认隐藏。Rust 的 `PrivacyOptions` 需要同时设置 `include_sensitive` 与 `caller_authorized`；CLI 对应 `--include-sensitive --authorized`，并会向 stderr 输出警告。调用方应先获得授权，声明不会绕过系统权限。

当前不解析、保存或输出 MAC、IP、UUID、磁盘序列号、用户、进程、主机名或个人文件。系统 API 可能把额外元数据写入临时缓冲区，例如 Windows 网络结构中的 MAC/GUID；实现不会导出这些字段，这不等于它们从未进入进程内存。

Linux 显示器默认不读取含标识的 EDID；授权后只导出基础块的产品名称，不导出序列号。分享报告时仍需检查和脱敏。漏洞按[安全政策](../SECURITY.md)私密报告。

## 自定义 backend

通过 `HardwareBuilder::with_backend` 注册 `Backend`。高优先级字段覆盖低优先级有效值，同级按注册顺序处理；缺失增强值保留已有有效值，冲突记录来源。backend 是受信任的应用代码，必须遵守隐私、资源上限和取消检查。

门面自动组合所需 backend。单独使用 sysinfo backend 时，委托给平台实现的 CPU、内存或运行时长字段可能保持不支持；通常优先使用 `daoseeker_scope::Hardware`。
