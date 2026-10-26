# Linux FFI SDK 候选包验证

Linux SDK 将共享库、C 头文件、C/Python 示例、Schema 和许可材料打包，便于其他语言接入。设计见 [ADR 0034](adr/0034-linux-ffi-sdk.md)。这不是正式发布。

## 使用入口

在干净 GNU/Linux x86_64 工作区，准备固定 Rust 工具链、GNU 兼容 C 编译器/链接器、readelf、Python 与开发依赖 jsonschema 4.25.1：

```sh
set -eu
sdk=$(python3 scripts/cli_bundle.py --product ffi_sdk --offline)
python3 scripts/ffi_bundle_smoke.py "$sdk"
```

依赖或工具链许可尚未缓存时去掉 `--offline`。产物保存在 target/cli-bundles 的新 candidate 目录，演练只写 target 下临时目录；未提交修改可用 `--allow-dirty` 调试，不能作为干净提交验收。默认报告为 target/ffi-bundle-evidence.json。

归档内 README 给出独立消费命令。C 使用包内 .so 和头文件；Python 示例仅需标准库并显式接收 .so 绝对路径。验证器额外使用 readelf 和 jsonschema，不要求 SDK 使用者安装 Rust 或项目源码。

## 验证边界

Linux SDK 使用格式 4，其他三个包格式不变；ABI 1、硬件 Schema 1、Rust API、依赖/features/锁和 MIT 不变。每个 Linux 演练预计 15 个顶层调用（含 6 次 ELF 检查），300 次 Python collect/free，并检查同候选安装、损坏更新拒绝和回滚。预期次数不是已执行结果。

Windows 主机只能验证共享格式/负向守卫和既有 Windows SDK 回归，不能执行 Linux SDK。本轮原生 Linux CI 尚未运行；新增两项 POSIX 权限用例需在 Linux/macOS 执行，不以模拟模式作为权限证据。

最低 glibc/发行版/内核版本、系统传递依赖闭包、签名、旧正式版升级和正式分发尚未验收；不宣称 musl、ARM、macOS SDK 或静态链接支持。用户延期的实体 Linux/macOS 设备验证保持待办。
