# 文档目录

## 使用与开发

- [使用指南](usage.md)：Rust、CLI、JSON、C/Python、刷新与隐私。
- [剩余工作](progress.md)：首版工作包、延期设备验证与后续扩展。
- [开发指南](../CONTRIBUTING.md)：构建、检查、跨语言、fuzz 和性能命令。
- [平台能力矩阵](adr/0005-platform-support-matrix.md)：逐字段来源和支持范围。
- [项目检查与修复](project-review-2026-10-11.md)：2026-10-11 全项目审查结果。
- [发布与迁移](release.md)、[依赖许可证](dependencies.md)、[性能基线](benchmarks.md)。
- [打包与安装验证](packaging.md)：归档内容、MIT/C 头文件、独立构建与验证边界。

## 设计决策

[公共模型](adr/0001-public-model.md) · [sysinfo 适配](adr/0002-sysinfo-backend.md) · [能力、错误与资源](adr/0003-capability-and-error-model.md) · [C ABI](adr/0004-c-abi.md) · [procfs fuzz](adr/0006-procfs-fuzz-hooks.md) · [Linux 电池](adr/0007-linux-power-supply.md) · [hwmon](adr/0008-linux-hwmon.md) · [NVMe 温度](adr/0009-linux-nvme-temperature.md)

[Linux 网络决策](adr/0010-linux-network-counters.md) · [网络验证](network-validation.md)

[Windows 网络决策](adr/0011-windows-network-counters.md) · [Windows 网络验证](windows-network-validation.md)

[macOS 网络决策](adr/0012-macos-network-counters.md) · [macOS 网络验证](macos-network-validation.md)

[存储容量决策](adr/0013-storage-capacity.md) · [Linux 存储验证](storage-validation.md)

[Windows 存储决策](adr/0014-windows-storage-capacity.md) · [Windows 存储验证](windows-storage-validation.md)

[macOS 存储决策](adr/0015-macos-storage-capacity.md) · [macOS 存储验证](macos-storage-validation.md)

[Windows GPU 决策](adr/0016-windows-gpu.md) · [Windows GPU 验收](windows-gpu-validation.md)

[存储 CLI 文本输出验证](storage-text-validation.md)

[CLI 字段状态与来源验证](cli-text-validation.md)

[原生验收失败诊断](native-diagnostics-validation.md)

[JSON Schema v1](schema/snapshot-v1.schema.json) · [黄金样例](../tests/fixtures/snapshot-v1.json)

## 验证记录

这些记录对应各自日期和 source commit，保留当时的结果与限制。判断当前版本请先看[项目检查报告](project-review-2026-10-11.md)和 [GitHub CI](https://github.com/DaoSeeker01/DaoSeekerScope/actions/workflows/ci.yml)。

- [首次本地验证](validation.md)、[首次三平台 CI](ci-validation.md)、[交付历史](delivery.md)。
- [输入与 FFI](input-ffi-validation.md)、[原生验收入口](native-validation.md)、[Linux 容器](linux-container-validation.md)。
- [CPU 刷新](cpu-refresh-validation.md)、[内存与运行时长](memory-refresh-validation.md)、[procfs fuzz](procfs-fuzz-validation.md)。
- [电池](battery-validation.md)、[hwmon](hwmon-validation.md)、[NVMe 温度](nvme-temperature-validation.md)。

脱敏 JSON 证据保存在 `docs/evidence/`。模拟输入、内核权限测试和真实设备读取是不同证据；完整替换 `/proc` 的探针曾被 OCI 运行时拒绝，属于 `not_run`。
