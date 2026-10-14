# CLI 字段状态与来源验证

2026-10-14，本轮修复文本模式的四项问题：可用标量值缺少来源、成功集合数量缺少来源、能力列表丢失已有原因、多电池/传感器条目没有编号。GPU 原先只打印数量，现在可以逐条呈现公共模型已有的名称与专用显存字节数；默认 backend 的 GPU 采集仍为 Unsupported，渲染 fixture 不代表实现原生 GPU。

所有文本值保留来源，缺失值保留状态与原因；能力原因仅在模型提供时显示，不补猜测原因。真实零、false、负温度仍是可用值，单字段失败不会替换其他条目；成功空列表与缺失/受限列表分别表达。设备编号表示当前顺序，不承诺跨采集稳定身份。存储集合标题也增加来源，因此同步更新其原生文本 gate；精确容量、默认脱敏及容量重叠提示保持原语义。

将文本呈现提取为 CLI 内部函数，使用同一公共 Snapshot，不读取硬件，不新增公共 API。命令、参数、退出码、默认隐私和敏感访问警告保持现有契约。JSON 仍输出完整 Schema 1 快照；C ABI 1、MIT、依赖、feature 与锁文件均无变更。文本格式有兼容性变化，脚本应使用 `--json`。

新增三项 Rust fixture 测试覆盖标量来源、缺失原因、多条目失败隔离、零/false/负温度、五个能力等级及原因；新增一项集成测试运行全部九个文本命令及对应 JSON 命令，不跨独立采集比较值或成员。新增三项 Python 负向测试覆盖来源丢失/未知来源、溢出、坏值、错误编号、空/缺失区别、隐私标签泄漏和能力原因格式。原生验收新增 `cli_text` gate，运行 CPU、内存、系统、GPU、网络、电池、传感器和能力命令，保留字段数量、集合状态及输出哈希，不保存原始值/名称/文本；存储继续单独验收。空或 Unsupported 的输出只表示呈现正确，不计作该设备实际读取成功。

本机运行 `scripts/check.ps1 -Cross`，fmt/Clippy、135 项 Rust 测试（含 doctest）、no-default-features、doc 拒绝警告、CLI/FFI 构建和 Linux/macOS 交叉构建通过。Python Ruff format/check、mypy --no-incremental（22 文件）、47 项 unittest、Schema/generated/golden、项目数据与文档链接检查通过。`scripts/build_c_example.ps1` 的 C 生命周期检查及 `native_smoke.py` 的 CLI/C/Python、存储文本和新增 cli_text gate 通过；实际执行 `--help`、`--version`。自包含 fixture 修正后重跑完整 Rust 门禁、独立打包及完整本机原生验收；最终通过报告绑定干净源码提交 `a04d533aece5f56a4518a42d65314ae113959d01`。

同一源码的 [CI 38486638499](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38486638499) 的 8 个任务全部通过。Rust 测试含 doctest 分别为 Windows 135、Linux 125、macOS 125，Python 每平台 47 项；三平台 fmt/Clippy/doc、Schema、C/Python、九命令文本呈现及独立 `.crate` 解包测试/CLI 安装通过，每平台及本机各验证 8 个归档，第三方锁定版本不变，没有 registry 发布。Miri 8 项、AddressSanitizer 10 项、fuzz harness 两项回归及 11 个各至少 60 秒的 fuzz 目标完成；存储解析器 27,849,684 次/61 秒。短时 fuzz 不替代长期运行。21 项非 root 容器存储场景仍使用模拟 sysfs；完整挂载空 `/proc` 的探针仍因容器运行时拒绝挂载为 `not_run / runtime_mount_error`。

新文本 gate 的真实读取范围：三平台均有 CPU/内存/系统和网络字段可用；网络条目数为 Windows 18、Linux 4、macOS 11。默认 GPU 均 Unsupported；电池在 Windows runner 为 NotApplicable，Linux 为 Available 空列表，macOS 为 Unsupported；传感器在 Linux 为 Available 空列表，Windows/macOS 为 Unsupported。这些不同状态均保留，不能据此声称真实多电池/传感器已验证。本机读到 1 个电池，传感器 Unsupported；多设备编号、字段隔离和负温度由模拟测试验证。独立进程采集不承诺成员/值相同。

既有 macOS 整体采集 benchmark 为首次 369 µs、100 次刷新 p50/p95/max 20/22/39 µs；模拟 100 传感器与 1024 网络接口为 222 µs、JSON 373541 bytes。它是共享 runner 的整体采集回归，未测文本格式化/CLI 启动延迟、磁盘 IO 或峰值内存。本轮未改变采集器、超时或缓存语义，未新增实体设备、sandbox、热插拔或长期 fuzz 验证。

首次打包发现新增 Rust 测试以相对路径引用仓库根目录 fixture；正常源码测试通过，独立 `.crate` 解包测试编译失败（[macOS CI 38486186159](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38486186159) 与本机均复现）。修正为测试内自包含 JSON 输入，不复制黄金样例，不依赖归档外文件，也不降低独立测试门禁；旧 CI 被取消，首次失败不计入成功验收。

修正提交的本机完整验收曾有一次 `cli_text: process_failed`，当时 CLI/C/Python JSON 与存储文本均通过；现有诊断没有保存该次具体命令或 stderr，原因未定位，不能断言是超时或负载。随后八个文本命令单独复测均返回 0，独立打包结束后的完整原生复测通过。首次失败报告保留，未通过重试逻辑掩盖：脚本本身遇到失败仍返回非零。

[证据索引](evidence/cli-text-ci-38486638499.json)包含 12 份报告，区分最终成功、首次打包失败与本机原生失败。报告按 LF 归档，分别记录原始与归档 SHA-256；提交前后核对 Git blob、7 个存储 fuzz 种子和 macOS SDK 探针源码哈希。归档提交不是新的硬件验收源码。下一阶段优先补强原生子进程失败的命令/固定错误码诊断，同时保持日志脱敏。
