# Windows GPU 验收

源码：`19f20a53a1293fd4de0b8ed585c2615bf1499fe4`。Windows GPU 采集、CLI、C ABI 和 Python 原生入口已在本机通过。三平台 CI [38657166792](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38657166792) 的 8 个任务全部通过；[汇总与哈希索引](evidence/windows-gpu-ci-38657166792.json)绑定源码、三平台报告、本机 SDK 探针、归档报告及完整日志摘要。

## 本机真实读取

干净工作区，Windows x64，Rust 1.96/MSVC。CLI 与 C ABI 均返回 Available/Dxgi、2 个非软件适配器条目、2 个可用产品描述，独占显存字节数分别为 `4126146560` 和 `134217728`。独立 Windows SDK 探针在非提升令牌下枚举 3 个适配器，按 SOFTWARE 标志排除 1 个；数量与容量投影和库的两次调用一致。

这是当前操作系统可见适配器对象及驱动报告容量，不证明物理显卡数量，也不是显存使用率、共享显存或预算。脱敏报告保留字段状态、来源、时间、原因及数量/容量，不保存产品描述文本或设备标识；SDK 描述符在调用时暂含 PCI/LUID，仅提取必要字段。

- [CLI/C/Python 原生报告](evidence/windows-gpu-local-windows-38657166792.json)：5 项检查、15 个子进程均通过，源码和 dirty 状态可核对。
- [独立 SDK 探针报告](evidence/windows-gpu-local-sdk-probe-38657166792.json)：源码与可执行文件哈希、非提升状态、过滤数量及容量。
- [本机打包报告](evidence/windows-gpu-local-packages-38657166792.json)：8 个实际归档、解包独立测试 144 项（含 doctest）、CLI 安装和锁一致性通过。未发布依赖通过本地 patch 提供，不算真实 registry 安装。

探针源码为 [dxgi_probe.cpp](research/dxgi_probe.cpp)。在项目根目录的 MSVC x64 Native Tools 终端复现：

```bat
cl /nologo /W4 /WX /std:c++17 /EHsc /Fetarget\dxgi-probe.exe /Fotarget\dxgi-probe.obj docs\research\dxgi_probe.cpp dxgi.lib advapi32.lib
target\dxgi-probe.exe
```

仓库探针源码使用 LF；报告源码哈希按 Git blob/LF 计算，与编译时 CRLF 副本的规范化字节一致。哈希不证明签名或驱动可信性。

## 实际执行

Windows x64/Linux x64/macOS arm64 的原生 CI、8 crate 归档和独立安装均通过，解包测试数（含 doctest）为 144/134/134，Python 各 60 项。Windows runner 的 CLI/C ABI 均为 Available/Dxgi、1 个非软件适配器、1 个可用名称，驱动报告独占显存为 0；保留真实零，不推断共享显存或物理显卡。Linux/macOS GPU 文本仍为 Unsupported/Custom，其他基础采集与 C/Python 入口通过。

`scripts/check.ps1 -Cross` 通过 fmt、clippy -D warnings、144 项 Rust 测试（含 doctest）、无默认 feature 检查、rustdoc -D warnings、CLI/FFI 构建和 Linux x64/macOS arm64 交叉 check。Windows crate 的两目标 all-targets clippy 也通过，纯逻辑测试可以跨平台编译。

新增 9 项 GPU Rust 测试：仅标志过滤、真实零与 u64 上界、非法/未终止 UTF-16 字段隔离、空枚举与错误分类、中途失败、输出和扫描上限、取消/超时传播、成功和失败静态缓存及实例重建。SDK COM 包装负责释放；这些测试不宣称测量了原生 COM 泄漏。

Ruff format/check、mypy（24 个 Python 文件）、60 项 Python 测试、Schema 生成/黄金样例/未知字段/版本回归和项目链接检查通过。5 项新增 Python GPU 守卫测试使用合成数据，不是真机读取。两个锁文件只增加 Windows crate 到既有 windows 0.62.2 的依赖边；47 个 workspace 包的名称、版本及 checksum 不变。项目 MIT，SDK 绑定仍 MIT OR Apache-2.0。

`cargo fmt --manifest-path fuzz/Cargo.toml --check`、`cargo test --locked --manifest-path fuzz/Cargo.toml --lib` 的 2 项 harness 测试通过。没有新增 GPU 专用 fuzz 目标。完整采集 benchmark 已运行，见[性能基线](benchmarks.md)。

原生 CI 另通过依赖/许可证审计、Linux 容器场景、Miri 8 项和 FFI AddressSanitizer 10 项；现有 11 个 fuzz 目标各完成至少 60 秒。完整空 `/proc` 容器仍被运行时拒绝，属于 not_run，不是库降级成功。Miri/ASan 验证既有 FFI 内存边界，不执行 Windows DXGI 原生 COM 路径。

初次沙盒运行因 rustdoc 临时目录可执行文件权限和 uv 缓存权限失败；随后用正常工具链权限重跑全部相应门禁通过，没有弱化门禁。这些环境失败不计作 backend 错误。

## 兼容性与限制

Rust 模型形状/签名、C ABI 1、JSON Schema 1 不变，仅新增 Schema description。Windows 默认 GPU 从 Unsupported 变为 Partial，消费者必须继续检查集合和字段状态。public API 不暴露 SDK 类型。只有 Windows target 新增显式 SDK 依赖及最小 features；其他目标仍不编译它。

驱动调用为同步，不保证强制中断；等待超时与 worker 配额仍适用。静态缓存不热插拔重扫，包括失败结果，需新建 Hardware。未执行 GPU 原生泄漏 campaign、热插拔、多驱动故障或峰值 heap profiling。Linux/macOS GPU 仍 Unsupported；实体 Linux/macOS 验证按维护者安排延期。剩余工作见[进度清单](progress.md)。

C ABI 的既有缓存契约同样适用：NULL options 复用默认采集器及 GPU 静态缓存；传入有效非 NULL options 每次创建独立采集器，可重新枚举。CLI 每次启动新建实例。没有新增 FFI 重置或热插拔接口。
