# Linux 网络累计字节数验证

日期：2026-10-11。本轮契约见 [ADR 0010](adr/0010-linux-network-counters.md)。

## 实现范围

Linux `/proc/net/dev` 有界读取，字节字段隔离、默认名称脱敏、错误后清除旧值、接口热插拔及累计计数重置。CLI 文本/JSON、Rust 和 C JSON 使用相同模型。Windows/macOS 网络仍 Unsupported，磁盘未实现；运行时依赖、feature、MIT 许可证、Schema 1 / ABI 1 均不变。

Core 同样脱敏自定义 backend 的接口名；已有消费者要显示名称时须显式设置授权的 PrivacyOptions。名称不是稳定硬件标识，数组索引也不能跨快照识别同一接口。仅统计当前进程网络命名空间，不推断宿主流量、进程流量、物理网卡数量或网速。

## 可复现验证

```sh
cargo test --locked -p daoseeker-scope-linux --all-features network -- --test-threads=1
cargo test --locked -p daoseeker-scope --all-features --test network
cargo test --locked -p daoseeker-scope-cli --test cli network
cargo test --locked --workspace --all-features -- --test-threads=1
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo fmt --all --check
cargo fmt --manifest-path fuzz/Cargo.toml --check
cargo +nightly-2026-10-08 fuzz run network_dev -- -seed=20261011 -max_total_time=60 -max_len=524289 -timeout=2 -rss_limit_mb=512
```

正常数据、合法 0/u64 上界、负数/溢出、字段隔离、非法列头/列数、损坏 UTF-8、重复接口、512 KiB/条数上限、I/O 原因、默认/授权名称、JSON 往返和刷新恢复由 Rust 回归覆盖。生产 parser 与 fuzz hook 共用实现；语料回放属于确定性回归，不能代替 libFuzzer 运行。

## 本机结果

Windows x64 / Rust 1.96.0：`scripts/check.ps1 -Cross` 全部通过，含 fmt、workspace Clippy、单元/集成/doctest、无默认 feature 检查、文档构建和 Linux x64 / macOS arm64 交叉 check。Python Ruff / mypy（`--no-incremental`，18 文件）、35 个测试、Schema/黄金样例和项目文档检查通过。C 示例及 CLI/C/Python 原生 smoke 通过；本机网络字段仍 Unsupported。

九个 fuzz harness 在 Windows 通过固定 nightly check 及 Rust 1.96 Clippy；Windows 不支持 cargo-fuzz campaign。固定 nightly 会对既有 Atomic::fetch_update 发出弃用警告，稳定工具链无此警告。本轮未改其实现。初次沙盒 doctest 因临时目录拒绝写 exe 失败，正常工具环境重跑成功；初次 Python 工具缓存拒绝访问，正常工具环境成功。初次打包门禁因未提交文件拒绝运行，待提交后对干净源码重跑，不添加 --allow-dirty 或削弱门禁。

Linux CI 另检查生产读取的累计字节数和默认名称脱敏，并对合成网络文件执行真实 chmod 权限拒绝/恢复；该权限 fixture 在 CI 要求普通用户，特权本地执行明确记录 not_run。原生 Linux 读取、权限 fixture、libFuzzer、最终打包结果将在本轮 CI 完成后单独归档。旧版本 CI 或 Windows fixture 不算此切片的 Linux 真机证据。

初次源码 `6fed0fb` 的 [CI 38092358804](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38092358804) 在 Linux Clippy 阶段拒绝 `Permissions::from_mode(0)`：Unix 权限字面量应写成八进制 `0o0`。修正字面量并保留权限测试/Clippy 门槛，随后重新运行原生 CI；此前该任务未进入 Linux 测试，不算网络读取成功。

本轮尚未运行新增网络路径的 benchmark、长期 fuzz 或 Linux 网络命名空间切换实验；已有容器证据不证明宿主网络可见。无新依赖/feature；Schema 1 仅更新字段说明，ABI 1 的函数和头文件均未改变。
