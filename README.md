# 寻道者观微 · DaoSeekerScope

用一套接口读取 Windows、Linux 和 macOS 的硬件与系统信息。

可作为 Rust 库嵌入应用，通过 C 接口接入其他语言，也可以用 `dscope` 在终端查看。数据在本机采集，无需联网。

## 能做什么

- 查看 CPU 型号、核数、占用率、内存和操作系统信息。
- 读取部分平台的设备型号、电池和温度信息。
- 输出文本或 JSON，方便展示、记录和接入其他程序。
- 读不到数据时说明原因；序列号等敏感信息默认隐藏。

## 当前支持

项目处于 0.1 开发阶段，尚未发布正式版本。三个桌面平台已通过原生 CI 构建、测试及基础信息读取。

| 信息 | Windows | Linux | macOS |
|---|---|---|---|
| CPU、内存、系统、运行时长 | 支持 | 支持 | 支持 |
| 网络累计接收/发送字节数 | 部分接口 | 支持 | 部分支持 |
| 整块存储设备容量 | 部分支持 | 部分支持 | 未实现 |
| 设备型号、主板、固件 | 未实现 | 部分 DMI 字段 | 设备型号 |
| 电池 | 支持 | 部分支持 | 未实现 |
| 温度 | 未实现 | 部分 hwmon 驱动 | 未实现 |

GPU、文件系统可用空间和显示器信息尚未实现。网络与存储设备名称默认隐藏；Windows 网络不保证所有逻辑隧道接口，Linux 网络统计限当前命名空间，macOS 的计数可能取整和回绕。Linux 电池与温度已通过模拟数据和权限测试，真实设备验证仍待补充。完整范围见[平台能力矩阵](docs/adr/0005-platform-support-matrix.md)。

## 快速上手

需要 Rust 1.96。克隆仓库后，在项目目录运行：

```sh
cargo run --locked -p daoseeker-scope-cli -- cpu
cargo run --locked -p daoseeker-scope-cli -- memory
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

[使用指南](docs/usage.md) · [开发与测试](CONTRIBUTING.md) · [文档目录](docs/README.md) · [问题与修复记录](docs/project-review-2026-10-11.md)

## 许可证

本项目采用 [MIT 许可证](LICENSE-MIT)。
