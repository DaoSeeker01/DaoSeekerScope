# 寻道者观微 · DaoSeekerScope

用一套接口读取 Windows、Linux 和 macOS 的硬件与系统信息。

可作为 Rust 库嵌入应用，通过 C 接口接入其他语言，也可以用 `dscope` 在终端查看。数据在本机采集，无需联网。

## 能做什么

- 查看 CPU 型号、核数、占用率、内存、存储容量和操作系统信息。
- 读取部分平台的设备型号、电池和温度信息。
- 输出文本或 JSON，方便展示、记录和接入其他程序。
- 读不到数据时说明原因；序列号等敏感信息默认隐藏。

## 当前支持

项目处于 0.1 开发阶段，尚未发布正式版本。三个桌面平台已通过原生 CI 构建、测试及基础信息读取。

| 信息 | Windows | Linux | macOS |
|---|---|---|---|
| CPU、内存、系统、运行时长 | 支持 | 支持 | 支持 |
| 网络累计接收/发送字节数 | 部分接口 | 支持 | 部分支持 |
| 整块存储设备容量 | 部分支持 | 部分支持 | 部分支持 |
| GPU | 型号、独占显存 | 有限枚举/部分名称 | Metal 名称、显存状态 |
| 显示器 | 活动路径、信号像素尺寸 | 连接视图，名称需授权 | 活动视图、模式像素 |
| 设备型号、主板、固件 | 部分 OEM 摘要 | 部分 DMI 字段 | 设备型号 |
| 电池 | 支持 | 部分支持 | 未实现 |
| 温度 | 未实现 | 部分 hwmon 驱动 | 未实现 |

系统权限、容器和驱动会影响结果，请逐字段检查状态。GPU 使用率、Linux 显存和文件系统可用空间尚未实现；显示像素尺寸不一定是面板原生分辨率。详细语义与设备验证边界见[平台能力矩阵](docs/adr/0005-platform-support-matrix.md)。

序列号、网络接口名和存储设备名称默认隐藏。敏感采集需要调用方显式请求并确认已获授权，见[隐私与限制](docs/usage.md)。

## 快速上手

需要 Rust 1.96，以及当前平台的 C/C++ 链接工具。当前从源码使用；尚无 crates.io 正式版本。克隆仓库后，在项目目录运行：

```sh
cargo run --locked -p daoseeker-scope-cli -- cpu
cargo run --locked -p daoseeker-scope-cli -- memory
cargo run --locked -p daoseeker-scope-cli -- disk
cargo run --locked -p daoseeker-scope-cli -- display
cargo run --locked -p daoseeker-scope-cli -- --json
```

安装命令行工具：

```sh
cargo install --locked --path crates/daoseeker-scope-cli
dscope system
dscope --help
```

Rust 调用示例：

```rust
fn main() -> Result<(), daoseeker_scope::ScopeError> {
    let hardware = daoseeker_scope::Hardware::new()?;
    let snapshot = hardware.collect()?;
    println!("CPU: {:?}", snapshot.static_info.system.cpu.brand.value());
    Ok(())
}
```

依赖配置、动态刷新和 JSON 用法见[使用指南](docs/usage.md)。其他语言可从 [C 头文件](bindings/daoseeker_scope.h)、[C 示例](examples/collect.c)和 [Python 示例](examples/collect.py)开始。

## 文档与参与

[使用指南](docs/usage.md) · [开发与测试](CONTRIBUTING.md) · [文档目录](docs/README.md) · [当前审计](docs/project-review-2026-10-27.md)

报告问题或建议，请使用 [Issue 模板](https://github.com/DaoSeeker01/DaoSeekerScope/issues/new/choose)；提交代码前请阅读[贡献指南](CONTRIBUTING.md)和[社区规范](CODE_OF_CONDUCT.md)。漏洞请按[安全政策](SECURITY.md)私密报告。

[更新日志](CHANGELOG.md) · [v0.1 交付清单](docs/v0.1-checklist.md) · [开发进度](docs/progress.md) · [本轮审计](docs/project-review-2026-10-27.md)

## 许可证

本项目采用 [MIT 许可证](LICENSE-MIT)。
