# 输入与 FFI 验证切片（2026-10-09，Asia/Shanghai）

本节记录上传前Windows可复现的输入与内存契约验证，未新增硬件字段。当时Linux/macOS仅有交叉类型检查；后续同日三平台原生CI、Unix参数回归、三个fuzz smoke及ASan均已通过，见[CI验收](ci-validation.md)。以下待验清单保留当时状态。

## 变更与兼容性

| 文件/范围 | 结果 |
|---|---|
| crates/daoseeker-scope-ffi/src/lib.rs | 注册表改Arc<[u8]>、集中大小/容量/token检查；增加真实读取、128次释放循环、8线程独立buffer、64条目扩容、篡改、错误输入、token耗尽回归 |
| crates/daoseeker-scope-cli/src/lib.rs、src/main.rs | 解析与采集分离；新增CLI辅助Command/Invocation/parse_args及参数上限常量；args_os非法编码返回退出码2和固定脱敏错误 |
| crates/daoseeker-scope/tests/input_regression.rs | 512个固定种子JSON变异、512层嵌套拒绝；成功解码必须往返相等 |
| crates/daoseeker-scope-linux/tests/input_regression.rs | 512个0..8192字节DMI样本，验证值/状态/来源/时间不变量 |
| crates/daoseeker-scope-cli/tests/invalid_encoding.rs | Windows未配对UTF-16 surrogate实测通过；Unix非法UTF-8分支尚未原生运行 |
| fuzz/Cargo.toml、Cargo.lock、fuzz_targets/cli_args.rs、corpus/ | CLI目标及有效/无效种子，三个harness编译通过 |
| scripts/check_miri.ps1、.github/workflows/ci.yml | 固定nightly日期和cargo-fuzz版本，Miri独立目录，新增Windows C、Miri与Linux Rust FFI ASan作业 |
| docs/adr/0004-c-abi.md、README、delivery、validation、依赖树 | 同步所有权修复、证据与限制 |

主Rust硬件模型/Backend API、feature、C头文件布局和符号未改变；crate0.1.0、ABI=1、Schema=1。CLI辅助lib用于测试/fuzz；命令和退出码不变，非法编码从可能panic改为usage error。

## Miri发现的真实缺陷

原实现先以 `bytes.as_ptr()` 导出Box指针，后将Box移入HashMap。默认Stacked Borrows检测在读取切片时失败：`trying to retag ... SharedReadOnly ... tag does not exist`，指出插入时的Unique retag使旧指针失效。普通测试和仅释放测试通过不能排除此问题。

改用Arc共享所有权和Arc::as_ptr，不禁用别名/泄漏检测。8项纯内存契约通过。Miri针对Linux目标交叉解释，不执行Win32/sysfs或CPU/内存采集，不能计入Linux原生证据。注册表另有恢复baseline断言；全局可达分配不会被Miri作为泄漏报告，不能称为完整驻留内存/泄漏证明。并发测试覆盖独立buffer，同一buffer并发释放或释放后读取仍违反C契约。

工具：stable1.96.0；固定nightly-2026-10-08为1.101.0-nightly (1d81eb4ad 2026-10-07)。nightly对stable兼容的AtomicUsize::fetch_update给出弃用警告，stable clippy零警告；未因此提高MSRV或改变worker计数逻辑。

## 实际命令和结果

在仓库根由 `E:\DevTools\Mise\bin\mise.exe exec --` 调用，最终门禁为普通主机权限、CARGO_INCREMENTAL=0。

| 命令 | 实际结果 |
|---|---|
| pwsh -NoProfile -File scripts/check.ps1 -Cross | 完整通过：fmt、clippy --locked --workspace --all-targets --all-features -- -D warnings、37项test +1项doctest、core/门面no-default-features、doc -D warnings、Windows FFI/CLI链接、Linux x86_64/macOS arm64 cargo check |
| pwsh -NoProfile -File scripts/check_miri.ps1 | 8 passed，2项实际硬件测试filtered，解释测试11.15s；默认检测，target/miri-contracts-fixed |
| cargo check --manifest-path fuzz/Cargo.toml；cargo check --offline --locked --manifest-path fuzz/Cargo.toml；cargo fmt --manifest-path fuzz/Cargo.toml --check | 三个harness通过，独立锁更新后复验；没有campaign/coverage证据 |
| pwsh -NoProfile -File scripts/build_c_example.ps1 | MSVC /W4 /WX，真实DLL读取/free/清零/空释放/陈旧副本拒绝通过 |
| python examples/collect.py target/debug/daoseeker_scope_ffi.dll | 100次真实collect/free、默认隐私、Schema及错误副本拒绝通过 |
| dscope --json；uv run --no-project --with jsonschema==4.25.1 python scripts/check_schema.py target/real-snapshot.json | 实时脱敏快照、黄金/生成漂移、Schema自身、不变量、未知字段和版本通过 |
| uv run --no-project --with pyyaml==6.0.3 python -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml',encoding='utf-8')); assert len(d['jobs'])==5; print('workflow syntax: 5 jobs')" | YAML语法/5个job检查通过，不是GitHub运行证据 |
| .tools/bin/cargo-deny.exe check | advisories/bans/licenses/sources通过，保留syn2/3重复警告 |

确定性输入回归随test执行，无覆盖反馈，不替代fuzz。本轮未重跑benchmark；旧硬件采集基线不含新的FFI Arc分配开销。

中途失败：沙箱doctest临时exe拒绝写入、uv缓存无写权限，最终普通主机整套复验成功；自动审批服务曾因额度用尽未启动fuzz编译，恢复后原操作成功，不是安全判断；中断的Miri缓存曾报找不到serde，独立目录重编译后进入测试并发现上述缺陷。失败运行均不计通过。

## 依赖、限制和下一步

无新增运行时第三方依赖；CLI移除直接serde_json边，JSON仍由门面负责。root锁定第三方包仍39个，许可证范围不变。fuzz只增加本项目CLI crate；cargo-fuzz0.13.2为MIT OR Apache-2.0开发工具。nightly/Miri未改变默认stable；jsonschema4.25.1、PyYAML6.0.3仅用于临时验证环境。

未执行：Linux/macOS原生链接/读取/C-Python、Unix非法参数回归、Linux容器/权限降级、三个libFuzzer campaign、CI ASan、长跑/峰值分配profiling和release打包。ASan job覆盖Rust FFI测试，不代表C本体已插桩。WSL服务仍禁用，没有修改系统服务。目标仓库2026-10-08账号查询不可访问；未创建远端、push或运行CI。

下一阶段先在可访问仓库运行三平台CI与fuzz/ASan并收集原生证据，再开展独立Linux电池/hwmon切片。ADR/Schema维护者评审与三平台原生DoD尚未完成。

方法依据：[Miri交叉解释及检测限制](https://github.com/rust-lang/miri#cross-interpretation)、[Rust sanitizer目标与build-std](https://doc.rust-lang.org/unstable-book/compiler-flags/sanitizer.html)。文档说明路线，实际结果以上述命令为准。
