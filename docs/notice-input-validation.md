# 许可文件输入验证

本轮修复许可预检和候选打包共用的读取路径。原实现通过 `Path.is_file()` 筛选根许可文件，该接口会跟随符号链接，可能将包目录外的文件作为许可内容读取。[Python 文档](https://docs.python.org/3.11/library/pathlib.html#pathlib.Path.is_file)说明了这一行为。

## 读取规则

仍只发现包根目录中以 LICENSE、COPYING、COPYRIGHT 或 NOTICE 开头的文件，不递归进入目录。候选项先通过 `lstat` 检查；符号链接、Windows reparse 项和 FIFO 等非普通文件会被拒绝，不能因同包另有正常 LICENSE 而忽略异常。

读取器打开文件后，先用 `fstat` 与 [samestat](https://docs.python.org/3.11/library/os.path.html#os.path.samestat)核对设备和文件身份，再读内容。支持时使用 `O_NOFOLLOW` 和 `O_NONBLOCK`，防止末级链接替换或 FIFO 造成意外读取/等待；Windows 使用二进制模式。读取仍受原有 64 MiB 单文件上限限制，成功或异常路径都关闭描述符。第三方材料和 Rust 工具链材料共用读取器，普通文件内容保持原样。

预检按包记录 `unsafe_notice_file` 或 `notice_read_failed`，不会把异常归为“没有材料”，也不记录原始错误路径。其他包继续扫描；候选打包遇到异常立即失败。非法文件名在读取前拒绝。

打包仍要求可信且读取期间不变的 Cargo 缓存和工具链目录；本轮检查不覆盖所有父路径、硬链接或同一权限主体对普通文件内容的并发修改。

## 本机验证与修复过程

Windows 本机成功创建并测试真实文件链接、悬空链接和目录链接。修复前 11 项定向测试中，8 项通过、2 个测试方法失败（4 个失败子项）、1 项 FIFO 测试跳过，失败记录保留为负向对照。新增 6 项回归覆盖链接、reparse 元数据、FIFO、普通目录、文件身份不符及异常关闭/错误隔离。单元测试的 reparse 与身份替换使用合成元数据或描述符注入；本机另验证了真实 NTFS junction，没有进行并发攻击验证。

本机 Python 全套 303 项：297 通过、6 跳过；许可定向测试 14 项：13 通过、1 项 POSIX FIFO 跳过。Ruff 格式与检查、mypy（73 文件）通过。首轮本机 mypy 发现 Windows 类型存根没有 `os.mkfifo`，已修正；首轮 Linux/macOS CI 41253914887 又发现测试直接访问 Windows 专有 `OSError.winerror`，现改为可选属性查询。失败日志保留，不能把该次 CI 写成通过。

## 原生验收

修复提交 `cb80fa8` 的[三平台 CI 41254112803](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/41254112803)八项任务均通过。[验收索引](evidence/notice-input-ci-41254112803.json)保存 20 份报告的来源与哈希，并保留首轮失败、取消状态和修复前负向对照。

| 环境 | Python | 八包 Rust（含文档测试） | 许可查询：包数 / 缺口 |
|---|---|---:|---|
| Windows 原生 CI | 297 通过、6 跳过 | 274 通过 | CLI/SDK 各 28 / 0 |
| Linux 原生 CI | 303 通过、0 跳过 | 267 通过 | CLI/SDK 各 13 / 0 |
| macOS 原生 CI | 302 通过、1 跳过 | 271 通过 | CLI/SDK 各 20 / 6，仍被阻止 |

Linux/macOS 的真实 FIFO 和符号链接回归已执行。Windows 本机另创建真实 NTFS junction，与正常 LICENSE 并存时，预检与打包均在打开文件前拒绝；报告和复核脚本见验收索引的 junction 项。最终干净提交还通过三目标许可查询、原生 C/Rust 契约，以及 CLI 六进程、SDK 九项顶层调用/三次 C 编译与运行/300 次 Python collect-free 演练。三目标查询只读取 Cargo 元数据与缓存，不是本机运行 Linux/macOS。Windows/Linux CI 的 CLI/SDK 隔离安装、拒绝损坏更新和同候选双槽位回滚也通过；没有旧正式版升级兼容结论。

fmt、严格 Clippy、Rust 单元/文档、无默认功能、严格文档、Schema、原生 ABI 契约、Ruff/mypy、项目检查，以及 Miri 8 项、FFI ASan 11 项、12 个各至少 60 秒的短 fuzz 目标通过。本轮 Windows 本机没有重跑 Rust 全套，表中 Rust 数量来自对应原生 CI 的八包测试。

首轮 CI 的 Linux/macOS 在相同 `winerror` 类型标注处失败；四项其他任务成功，Windows 与 fuzz 两项因后续修复推送自动取消，首轮工作流总体为 cancelled。最终轮全部通过。准备执行时，默认 shell 初始化两次失败，切换到现有 PowerShell 后正常；不是产品测试失败。

macOS 六项 `missing_dependency_notice` 与原有锁定版本一致。查询 completed、CI 成功和缺口仍被阻止可同时成立，不构成法律评审、材料补齐或分发批准。没有依赖、features、Rust API、MIT、ABI/Schema 或私有候选包格式变更，没有正式发布。
