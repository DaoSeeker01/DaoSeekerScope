# 原生验收与证据保留（2026-10-09，Asia/Shanghai）

2026-10-26 Windows SDK 回归：源码 `ba11807` 的[CI 40249181949](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40249181949)三平台各 5 组/16 进程通过，Windows/Linux CLI 候选各六进程通过；Windows SDK 另九项顶层调用/300 次 Python collect/free 通过，[验证记录](windows-ffi-sdk-validation.md)。C 编译器子孙进程不计入九项；不扩展为其他平台 SDK、旧版升级或实体设备结论。

2026-10-26 更新：源码 `98172d0` 的三平台原生 CLI/C/Python 各 5 组/16 进程通过；Linux v2 与 Windows v1 另各六进程完成候选安装/回滚，[CI 与验证边界](linux-cli-bundle-validation.md)。POSIX 权限测试不代替实体设备、最低发行版或旧版本兼容验证。

2026-10-25 更新：源码 `2d0a8a1` 的三平台原生 CLI/C/Python 各 5 组/16 进程及 Windows 候选包另 6 进程通过，[运行与边界](cli-bundle-validation.md)。Windows x64、Linux x64、macOS ARM64 的报告归档于[CI 索引](evidence/windows-cli-bundle-ci-40183166615.json)；托管 CI 不能替代延期的实体设备验证。以下为历史入口记录。

本节记录上传前的原生smoke入口切片及本地Windows结果。后续同日已获用户授权创建私有仓库并运行CI，三平台、fuzz与ASan全部通过；最新结论见[三平台CI验收](ci-validation.md)。以下未执行项描述的是上传前状态。

## 变更

| 文件 | 内容 |
|---|---|
| scripts/native_smoke.py | 实际执行已构建CLI、C例子和Python100次FFI；Schema/最小读取/默认隐私检查；记录平台、可用rustc、Git状态、产物/锁SHA256与字段元数据 |
| tests/test_native_smoke.py | 4项守卫测试：错误计数、隐私违反、损坏/超长JSON、失败状态和中断清除旧成功；Fixture不是原生证据 |
| .github/workflows/ci.yml | Python静态/单元检查，统一smoke，C前置编译；固定upload-artifact提交ea165f8d65b6e75b540449e92b4886f43607fa02，报告保留14天 |
| README/validation/delivery/release与docs/evidence/windows-native-2026-10-09.json | 最终Windows报告、复现入口和待验清单 |

报告version=1只表示测试报告格式；crate仍0.1.0，ABI=1，Snapshot Schema=1，feature/公共API不变，无新增运行时依赖或Cargo锁变化。

## 判定规则

overall=passed要求CLI、C ABI、Python三项均通过。最小字段为OS名称、CPU型号/逻辑数、OS可用总内存；不能用空值或0表示成功。可选字段保留实际状态，首次CPU使用率仍TemporarilyUnavailable。序列号必须Restricted/PrivacyRedacted/value=null/observed_at=null。报告不写主机名、账号、路径或序列号。

子进程timeout60秒、JSON输出1MiB上限（CLI换行另留1字节），失败仅固定类别，不导出stderr。工具执行受信任的本项目产物；捕获输出后的长度检查不是任意程序的硬内存沙箱。拒绝优化Python模式，避免既有ctypes例子assert被关闭。

执行前覆盖旧报告为incomplete，中断不能留下旧passed。失败写failed，未执行项保持not_run；报告须与退出码及CI job结果一起看。available_rustc只描述当前工具，不独立证明二进制编译来源；未提交时Git revision=null、dirty=true。SHA256绑定文件，不是制品签名；托管/虚拟runner上的原生OS运行不证明裸机型号。

## 本次实测

最终报告UTC 2026-10-09T00:17:32.355506+00:00（北京时间08:17）。Windows/AMD64，Rust1.96.0，Python3.13.13。CLI/C/Python均passed，C和CLI独立采集均通过Schema。

| 字段 | 实际结果 |
|---|---|
| OS | Windows，11 (26300)，kernel26300，Available/sysinfo |
| CPU | i7-9750H、x86_64、12逻辑/6物理，Available/sysinfo |
| OS可用总内存 | 17,009,004,544字节，Available/sysinfo |
| 安装内存 | 17,179,869,184字节，Available/win32 |
| 首次CPU使用率 | Unavailable/TemporarilyUnavailable/sysinfo，未伪造0 |
| 序列号 | Restricted/PrivacyRedacted/null，未请求敏感数据 |

实际命令从仓库根经 `E:\DevTools\Mise\bin\mise.exe exec --` 执行：

| 命令 | 结果 |
|---|---|
| cargo build --locked -p daoseeker-scope-ffi -p daoseeker-scope-cli | Windows原生通过，CARGO_INCREMENTAL=0 |
| pwsh -NoProfile -File scripts/build_c_example.ps1 | MSVC /W4 /WX编译及实际读取/free通过 |
| uv run --no-project --with ruff==0.14.13 ruff format --check scripts/native_smoke.py tests/test_native_smoke.py | 通过 |
| 同上ruff check两个文件 | 通过 |
| uv run --no-project --with mypy==1.19.1 mypy --ignore-missing-imports scripts/native_smoke.py tests/test_native_smoke.py | 通过；jsonschema外部类型缺失允许，项目代码仍检查 |
| python -m unittest discover -s tests -p test_native_smoke.py | 4项通过 |
| .tools/actionlint/actionlint.exe -shellcheck= -pyflakes= .github/workflows/ci.yml | actionlint1.7.12语义通过；未使用外部shellcheck/pyflakes，不等同执行CI |
| uv run --no-project --with jsonschema==4.25.1 python scripts/native_smoke.py | 原生CLI/C/Python、最小读取、隐私与实时Schema通过 |
| 同上 --build-dir target/artifacts-not-present --output target/native-missing-artifacts.json | 实际缺失产物返回1，failed，三项not_run，无假成功 |

本轮Rust代码未改，未重复fmt/clippy/test/doc/Miri/fuzz/benchmark。上一轮37项Rust测试+1doctest、8项Miri及交叉检查见input-ffi-validation.md，不冒充本轮重跑。

actionlint1.7.12、Ruff0.14.13、mypy1.19.1及新增upload-artifact为MIT开发工具/CI action。运行依赖许可证和39个第三方锁定包不变。官方actionlint Windows amd64 zip下载后核验SHA256=6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9，再执行。[actionlint来源](https://github.com/rhysd/actionlint/releases/tag/v1.7.12)、[Ruff许可证](https://github.com/astral-sh/ruff/blob/main/LICENSE)、[upload-artifact](https://github.com/actions/upload-artifact)。

## 复现与下一步

```powershell
# 先Cargo构建并运行C编译脚本。
& 'E:\DevTools\Mise\bin\mise.exe' exec -- uv run --no-project --with jsonschema==4.25.1 python scripts/native_smoke.py
```

Unix先cargo build，再使用CI中cc命令生成target/debug/c-example，最后python scripts/native_smoke.py；Unix步骤尚未执行。其他产物目录传--build-dir，报告位置传--output。

2026-10-09复查：GitHub当前账号DaoSeeker01，但无法解析目标DaoSeeker01/DaoSeekerScope；不据此断言仓库全局不存在。WSL服务Stopped/Disabled、查询错误0x80070422，没有Docker/Podman入口。未更改系统服务、创建远端或上传源码，CI未运行。

三平台原生CI需要可访问目标仓库或可用Linux/macOS环境。代码与报告已可审阅；远端创建/可见性/推送由用户明确选择后执行现有CI。ADR/Schema评审、容器降级、长期campaign、性能profiling与发布仍待完成。
