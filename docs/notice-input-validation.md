# 许可文件输入验证

本轮修复许可预检和候选打包共用的读取路径。原实现通过 `Path.is_file()` 筛选根许可文件，该接口会跟随符号链接，可能将包目录外的文件作为许可内容读取。[Python 文档](https://docs.python.org/3.11/library/pathlib.html#pathlib.Path.is_file)说明了这一行为。此前的 macOS 六项材料缺口与分发门槛保持不变。

## 读取规则

仍只发现包根目录中以 LICENSE、COPYING、COPYRIGHT 或 NOTICE 开头的文件，不递归进入目录。候选项先通过 `lstat` 检查；符号链接、Windows reparse 项和 FIFO 等非普通文件会被拒绝，不能因同包另有正常 LICENSE 而忽略异常。

读取器打开文件后，先用 `fstat` 与 [samestat](https://docs.python.org/3.11/library/os.path.html#os.path.samestat)核对设备和文件身份，再读内容。支持时使用 `O_NOFOLLOW` 和 `O_NONBLOCK`，防止末级链接替换或 FIFO 造成意外读取/等待；Windows 使用二进制模式。读取仍受原有 64 MiB 单文件上限限制，成功或异常路径都关闭描述符。第三方材料和 Rust 工具链材料共用读取器，普通文件内容保持原样。

预检按包记录 `unsafe_notice_file` 或 `notice_read_failed`，不会把异常归为“没有材料”，也不记录原始错误路径。其他包继续扫描；候选打包遇到异常立即失败。非法文件名在读取前拒绝。

这不是文件系统沙箱。打包仍要求可信且读取期间不变的 Cargo 缓存和工具链目录，不检查所有父路径或硬链接，也不防御同一权限主体对普通文件内容的并发修改。本轮没有引入依赖、改变 Rust API、features、MIT、C ABI 1 或硬件 Schema 1，也没有开放 macOS 预编译分发。

## 实际验证与待办

Windows 本机成功创建并测试真实文件链接、悬空链接和目录链接。修复前 11 项定向测试中，8 项通过、2 个测试方法失败（4 个失败子项）、1 项 FIFO 测试跳过；失败记录保留为负向对照。修复后新增 6 项回归，覆盖上述链接、reparse 元数据、FIFO、普通目录、文件身份不符及异常关闭/错误隔离；reparse 与身份替换使用合成元数据/描述符注入，不是实际并发攻击验证。

本机 Python 全套 303 项：297 通过、6 跳过；许可定向测试 14 项：13 通过、1 项 POSIX FIFO 跳过。Ruff 格式与检查、mypy（73 文件）通过。首轮 mypy 发现 Windows 类型存根没有 `os.mkfifo`，现按既有 POSIX 可选 API 调用方式修正。

原生 Linux/macOS 的 FIFO 与链接测试、干净源码的许可预检、Windows CLI/SDK 候选安装及三平台 CI 尚待执行；未运行前不作通过结论。没有本轮 Rust 代码改动，Windows 本机未重跑 Rust 全套；原有硬件能力结果保留各自来源。完成验收后追加源码、报告与 CI 记录。
