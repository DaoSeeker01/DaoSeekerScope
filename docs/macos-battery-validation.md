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

源码 `c3e0c23` 的[三平台 CI 41294415147](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/41294415147)八项任务全部通过。[验收索引](evidence/macos-battery-ci-41294415147.json)记录 18 份报告的来源和哈希，并保留准备阶段失败与修复的记录。2026-11-01 执行，11-02 完成文档归档。

| 环境 | 八包 Rust 测试（含文档测试） | Python 通过 / 跳过 |
|---|---:|---:|
| Windows 本机及原生 CI | 280 | 314 / 6 |
| Linux 原生 CI | 273 | 320 / 0 |
| macOS ARM64 原生 CI | 278 | 319 / 1 |

本机 fmt、Clippy、严格文档、无默认功能及 Linux/macOS 交叉检查通过；干净提交的原生契约、Schema、八包独立构建/测试与 CLI 安装通过。Ruff、77 文件的 Windows/Linux/macOS 三种 mypy 目标、actionlint 和项目检查通过。CI 同时完成两平台候选安装/回滚、C/Python 消费者与既有容器回归。

六项纯 Rust 电池测试覆盖容量边界、属性失败、过滤、条目上限、取消/超时以及动态刷新不重读静态缓存。新增原生 Core Foundation 测试使用合成字典，验证实际 CF 类型、字段错误隔离及分类过滤。对照脚本的五项测试包括子进程空输出回归：此前干净工作树的空 `git status` 输出会被误拒绝，已在源码提交前修复。

macOS 公开 C SDK 探针编译和运行通过。SDK 前后均返回零个电源条目，CLI 与 C ABI 的 `batteries` 均为 `Available []`、来源 Iokit；只验收空视图路径。源码与探针/CLI 哈希前后一致，完整 JSON 的 Schema 和默认隐私检查通过。报告见[SDK 对照](evidence/macos-battery-sdk-macos-41294415147.json)与[原生 CLI/C](evidence/macos-battery-native-macos-41294415147.json)。

Miri 8 项、FFI ASan 11 项与 12 个既有短 fuzz 目标通过，每个目标至少 60 秒；它们没有执行 macOS 电源接口，不构成该接口的长期 fuzz 或无泄漏证明。[性能基线](benchmarks.md)记录本轮原生采集时间。

实体 Mac 电池、电源切换、Intel Mac 原生运行、真实权限或沙盒拒绝仍待验证。合成正值不计作真实电池成功；系统调用仅在调用边界检查取消/期限，不能强行中止系统 API。

未增加锁定包或升级依赖，仅启用已用 objc2-io-kit 0.3.2 的 `ps` 模块。CLI/SDK 各 20 包的名称、版本、SPDX 和缺口与上轮逐项一致；六项材料缺口仍阻止 macOS 分发。公开 Rust 签名/features、MIT、C ABI 1 与硬件 Schema 1 不变。没有正式发布。
