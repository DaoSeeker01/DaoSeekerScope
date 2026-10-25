# ADR 0031：Windows CLI 离线候选包与回滚演练

日期：2026-10-25。状态：实现与 Windows 本机验收通过，见[记录](../cli-bundle-validation.md)；新增 CI 步骤尚待运行。

## 范围与选择

首版 Rust/C/CLI 已形成闭环，但 crate 消费者测试不证明二进制归档可安装。本轮先提供 Windows x64 MSVC 的 CLI 候选 ZIP、外部 SHA256SUMS、内部 manifest 和临时目录演练。它不上传制品，不修改 PATH，不安装 DLL/header，也不发布 registry 或 GitHub Release。Linux/macOS 二进制、签名和正式分发独立验收。

使用 Python 标准库复用现有开发工具；不增加运行时依赖、安装器框架或管理员默认路径。构建在独立的新 target-dir 中使用 `cargo build --locked --release --target x86_64-pc-windows-msvc`，防止读取旧产物或受 CARGO_TARGET_DIR 重定向影响。只接受匹配的原生 rustc host；不从交叉编译推断安装成功。默认要求干净工作区，`--allow-dirty` 仅供调试并记录为 dirty。

## 包内容与许可

`bin/dscope.exe`、简短说明、项目 MIT 全文、上游 crate 清单和许可文件，以及当前 Rust 工具链的版权/许可文件一起归档。Cargo metadata 按目标筛选，遍历 CLI 依赖闭包，保守包含 build 依赖而排除纯 dev 边。上游根目录 LICENSE/COPYING/COPYRIGHT/NOTICE 文件按原字节复制；缺 SPDX 或没有许可文件直接失败。该自动检查不能代替发布前对版权、许可正文覆盖和运行时前提的人工评审。

不把已有依赖表当作许可正文，不编造缺失的版权。检查缓存发现 objc2 系列归档没有独立许可文件；本轮不会据此生成 macOS 制品。Windows 系统组件不随包分发；当前机器安装演练不证明干净 Windows 镜像上的运行时前提已满足。

## 格式与验证

独立的 bundle_format 为 1；模型 Schema 1、C ABI 1、Rust API 和消费 features 均不变。manifest 记录源码提交、dirty、版本、target、rustc、Cargo.lock 哈希，以及每个文件的长度和 SHA-256。ZIP 成员排序并固定时间，仅保证相同输入在同一压缩实现下的稳定归档，不宣称编译可重现。

验证外部哈希后，只读取同一份已校验 ZIP 字节。拒绝绝对路径、父目录跳转、Windows 特殊名、大小写冲突、文件/目录前缀冲突、特殊文件、重复 JSON 键、加密条目、未列入 manifest 的成员和内容不符。最多 512 项，单项 64 MiB（manifest 256 KiB），总解包及 ZIP 各 128 MiB；读取先检查声明大小再限长。归档仅供可信来源使用：SHA-256 不认证发布者，重写归档和校验文件可以一起造假；本轮没有代码签名。

## 安装、失败与回滚

演练只在 target 下新建临时目录。验证全包后写入全新 a/b 槽位；激活前再次比较已安装全部字节，原子替换演练目录内的选择文件。用真实包内 CLI 分别检查版本和默认 JSON 的最低读取/脱敏契约，切换和回滚共六个进程。损坏归档在创建安装目录和改变选择前被拒绝。已有安装目录不覆盖，失败重跑写 failed 报告替代历史 passed；不记录机器字段或原始错误。

两个槽位使用同一个候选版本，证明目录保留、校验和重新选择流程；当前没有上一正式版，因此不能宣称旧版本升级兼容、ABI 回滚、全局原子更新或跨文件系统安装已验证。回退本轮工具可移除两个脚本、测试和 CI 增量，运行时库不受影响。
