# Linux GPU 视图验收

源码 `b039c18da4521cde087e8e3d76f1c69b40c0c7dd`。实现 DRM 可见设备去重枚举和部分驱动产品名称，独占显存保持 Unsupported。[CI 38660183893](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38660183893) 的 8 个任务全部通过，2026-10-16 完成[9 份报告及哈希索引](evidence/linux-gpu-ci-38660183893.json)归档。范围与依据见 [ADR 0017](adr/0017-linux-gpu.md)。

## 真实环境结果

Linux x64 runner 的 CLI/C ABI 均为 Available/Drm，枚举到 1 个设备；其名称为 Unsupported/Drm，独占显存也为 Unsupported/Drm。它证明该环境的 DRM 设备视图可枚举，不证明实际 AMD/NVIDIA 产品名称读取，更不是物理显卡数量。macOS GPU 保持 Unsupported；Windows 既有 DXGI 路径的本机 CLI/C/Python 回归通过。

AMD 产品名称仅支持 amdgpu 的可选 product_name，NVIDIA 名称仅支持绑定 DRM 的 nvidia 设备首行 Model。其他驱动、未绑定 DRM 的 GPU、统一/共享内存、VRAM/GTT 容量映射均不宣称支持。实体 AMD/NVIDIA/Linux 设备验证按维护者安排延期。

## 权限、隔离与恢复

[容器报告](evidence/linux-gpu-container-38660183893.json)对应干净源码，20 项全部通过。容器配置为 UID/GID 65534、只读根和输入挂载、无网络、CapDrop ALL、no-new-privileges；256 MiB 内存、1 CPU、32 PID 与 64 文件描述符上限。fixture 由宿主生成，库运行在容器中只读，不授予管理员能力。

场景覆盖 card/render 同设备去重、连接器忽略、静态缓存与实例重建、非法 UTF-8、未知占位文本、控制字符、过长名称、属性缺失、真实权限拒绝、FIFO 与属性符号链接拒绝、未知驱动隔离、目录权限与恢复、身份链接损坏、目录缺失与恢复、129 项超限及最终恢复。权限拒绝实际返回字段 Restricted/PermissionDenied；枚举失败不返回成功前缀，内存仍可读。

这 20 项是合成 DRM 视图和真实内核文件类型/权限行为，不是 AMD/NVIDIA 驱动或实体 GPU 验证。NVIDIA 首行截断通过 Unix 文件夹 fixture 测试，未用真实 NVIDIA proc 节点验证。

## 已执行命令

`scripts/check.ps1 -Cross`：fmt、clippy -D warnings、Windows 150 项 Rust 测试（含 doctest）、无默认 features、rustdoc -D warnings、CLI/FFI 构建及 Linux x64/macOS arm64 交叉 check 通过。另对 Linux crate 在两目标执行 all-targets/all-features clippy，修正测试权限值的八进制写法后通过。

新增 12 项 GPU Rust 测试，其中 6 项通用、6 项仅 Unix：有界文本/首行解析、节点与 PCI 位置校验、状态映射、取消、成功与失败静态缓存、去重/连接器、NVIDIA 长尾截断、失败/上限、字段隔离/权限、属性类型和扫描上限。扫描 4097 个忽略项会返回 InvalidData，而不是无界循环。

Ruff format/check、mypy 26 个 Python 文件、65 项 Python 测试、Schema 生成/黄金样例/未知字段/版本与项目链接检查通过。新增 5 项 Python GPU 报告守卫使用合成数据，检查显存不被伪装为零、名称元数据与字段失败，报告不保留产品名称或内部位置。

`cargo fmt --manifest-path fuzz/Cargo.toml --check`、`cargo test --locked --manifest-path fuzz/Cargo.toml --lib` 的 2 项 harness 测试通过；现有 dmi_text 目标新增生产 GPU 名称解析检查及两个合成种子，不新增目标，不 fuzz DRM 枚举/实际权限。CI 的 11 个目标各完成至少 60 秒，Miri 8 项、FFI AddressSanitizer 10 项、依赖/许可证审计及其他容器回归均通过；完整空 `/proc` 仍被 OCI 运行时拒绝，属于 not_run。

最终三平台的 Rust 测试及解包后测试数（含 doctest）为 Windows 150、Linux 146、macOS 146；Python 各 65 项，Ruff/mypy 各检查 26 个文件。三个平台均验证 8 个实际归档和 CLI 隔离安装，仍未执行真实 registry 安装。Miri/ASan 验证既有 FFI 内存边界，不替代 AMD/NVIDIA 原生驱动泄漏测试。

`scripts/build_c_example.ps1` 与 `scripts/native_smoke.py` 通过：[本机 Windows 报告](evidence/linux-gpu-local-windows-38660183893.json)含 5 项检查及 15 个通过的子进程。`scripts/check_packages.py --offline` 验证 [8 个本机归档](evidence/linux-gpu-local-packages-38660183893.json)、解包 150 项测试、CLI 安装、MIT/头文件与锁一致性；依赖未发布时使用本地 patch，不算真实 registry 安装。

## 兼容性与未验范围

Rust 公共模型/签名、JSON Schema 1、C ABI 1、MIT、依赖与两份锁文件不变，无新 unsafe 或默认 feature。只增加现有 opt-in fuzzing 模块的隐藏测试函数。Linux gpus 行为由 Unsupported 转为有限 Drm 视图，消费者仍须检查每项字段状态。

动态刷新不重扫 GPU，包括静态失败；需新建 Hardware。FFI NULL options 复用缓存，非 NULL 有效 options 独立采集。同步内核调用不能强制中止，使用既有等待边界与 worker 配额；普通文件检查不构成恶意文件系统竞态沙箱。

未执行实体 GPU 验证、热插拔/驱动崩溃、GPU 专项内存泄漏/峰值分配或延迟 campaign，也未发布 registry 或 release 制品。后续任务见[剩余工作](progress.md)。
