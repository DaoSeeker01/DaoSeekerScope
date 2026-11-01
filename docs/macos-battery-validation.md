# macOS 内置电池验证

macOS backend 通过公开 IOPowerSources 接口读取内置电池的电量和供电状态。能力为 Partial，来源为 Iokit；每次动态刷新重新读取，沿用现有 BatteryInfo、Schema 1 与 C ABI 1。分类、单位、资源及所有权约定见 [ADR 0049](adr/0049-macos-battery.md)。

电量为 Current Capacity / Max Capacity × 100，不假设最大容量总是 100。容量必须是有效整数，零电量仍是成功读取。一个属性错误不删除同一电池的其他有效属性。UPS 和明确不存在的内置电池被过滤；成功的空视图只说明本次 API 没有可返回的条目。

## 复现

在 macOS 干净提交中，准备 Rust、C 编译器和 `requirements-dev.txt` 中的 Python 依赖后运行：

```sh
cargo test --locked -p daoseeker-scope-macos
cargo build --locked -p daoseeker-scope-cli
cc -Wall -Wextra -Werror -std=c11 docs/research/macos_battery_probe.c -framework IOKit -framework CoreFoundation -o target/macos-battery-probe
python scripts/macos_battery_smoke.py
```

独立 C 探针直接调用系统 SDK。对照工具在 CLI 前后各读取一次 SDK，最多重试三次，只有匿名字段视图稳定且与 Rust 快照一致才通过。报告 `target/macos-battery-evidence.json` 记录源码提交、二进制哈希、SDK 视图、条目数、Schema 与默认隐私检查。失败或中断先清除旧成功状态；不输出电池名称、序列号或适配器标识。

## 当前结果

Windows 本机完整 Rust 检查已完成，包括 280 项测试、fmt、Clippy、严格文档、无默认功能和 Linux/macOS 交叉检查。六项纯 Rust 电池测试覆盖容量边界、属性失败、过滤、条目上限、取消/超时以及动态刷新不重读静态缓存。macOS CF 类型测试已交叉检查，尚未在本机执行。

Python 全套 320 项中 314 通过、6 跳过；Ruff 与 Windows/Linux/macOS 三种 mypy 目标的 77 个文件检查通过。对照工具原先误拒绝干净工作树的空 `git status` 输出，已修复并补上子进程回归。准备阶段的 Rust 构建、Python 类型检查失败保留为失败记录，修复后重新检查。原生 SDK 编译、CF 运行测试和三平台 CI 待执行，不用交叉检查替代这些结果。

实体 Mac 电池、电源切换、真实权限或沙盒拒绝仍待设备验证。若 CI 只有空列表，只验收空视图路径；合成正值不计作真实电池成功。系统调用仅在调用边界检查取消/期限，不能强行中止系统 API。

未增加锁定包或升级依赖，仅启用已用 objc2-io-kit 0.3.2 的 `ps` 模块。公开 Rust 签名/features、MIT、C ABI 1 与硬件 Schema 1 不变；macOS 现有分发许可材料缺口继续保留。没有正式发布。
