# 首次交付与增量记录

以下按执行时点保留历史。当前仓库与三平台CI已完成，最新交付见文末及[CI验收](ci-validation.md)。历史记录中的双许可证描述仅代表当时状态，当前项目采用 MIT。

## 2026-10-11：改为单一 MIT 许可证

根据维护者选择，workspace 的 8 个 crate 和独立 fuzz 包均声明 MIT；README、依赖清单及其生成脚本同步更新，保留 LICENSE-MIT，移除 LICENSE-APACHE。第三方包的许可证与 cargo-deny 允许列表保持原样，历史验收记录不改写。

实际检查：两份 manifest 的 cargo metadata --locked --offline --no-deps 确认 9 个本项目包均为 MIT；完整 all-features metadata 重新生成 39 个第三方包清单，cargo-deny --offline check licenses、cargo fmt --all --check、git diff --check 及项目结构/本地链接检查通过。默认 Python 未安装 Ruff，因此本轮 Ruff 检查未运行，mypy 也未运行。没有 Rust 源码变更，未重跑 Rust 测试、clippy、doc、fuzz 或 benchmark。依赖/锁、feature、公共 API、C ABI 1 和 Schema 1 均不变。

## 2026-10-11：归档内容与独立消费者

修复 8 个 crate 漏打包 MIT 全文、FFI crate 漏打包 C 头文件；新增副本一致性检查和 `scripts/check_packages.py`。三个桌面 CI 增加实际归档、解包后的独立测试、CLI 临时安装及报告上传，原有门禁保留。复现步骤和原生 Cargo package 的内部错误见[打包指南](packaging.md)。没有 Rust 源码、公共 API、feature、依赖或锁文件变化；许可证仍为 MIT，ABI 1、Schema 1。

本机 Windows 未提交修复的预验收：8 个实际归档检查、解包后的 83 项 Rust 测试（含 doctest）、锁文件不变、CLI 隔离安装及版本/JSON 输出通过。34 项 Python 守卫、18 个 Python 文件的 Ruff/mypy、Rust fmt、actionlint、项目数据/文档链接与 diff 检查通过。初次 Python 检查缺 jsonschema 且沙盒临时目录拒绝写入；在隔离开发环境和正常临时目录权限下重跑成功，未跳过测试。最初 doctest 也因沙盒拒绝临时可执行文件而失败，重跑通过。

预验收报告位于 `target/package-evidence.json`，标记 `git_dirty=true`，不冒充干净提交验收。三平台新增 CI 门禁等待实际执行结果；尚未完成真实 registry 安装、标准 Cargo package 全流程、发行二进制许可声明、checksum/回滚演练或发布，也未重跑性能基线。

2026-10-08。本地E:/Projects/DaoSeekerScope；无既有代码或Git历史可迁移，目标DaoSeeker01/DaoSeekerScope当前账号查询404。已本地git init并设置origin，无commit/push/远端创建/发布。

| 部分 | 修改/公共契约 |
|---|---|
| workspace | Cargo.toml/Cargo.lock、固定Rust/mise1.96.0、MIT与Apache2.0全文 |
| Phase0 | docs/adr/0001..0005、research独立真实读取probe、dependency-tree与SPDX清单 |
| daoseeker-scope-core | 自有14类领域模型、Observed不变量、能力/Source/Reason/Error、Backend、HardwareBuilder、单worker采集/缓存/取消/有界等待、优先级/健康记录、可选serde/schema |
| daoseeker-scope-sysinfo | 精确sysinfo0.39.6，CPU/内存/OS/运行时，单位/零值/CPU采样转换，Partial错误证据 |
| daoseeker-scope-windows | 安装内存、电池普通用户API；unsafe局部说明 |
| daoseeker-scope-linux | 固定DMI文件有界读取、权限/缺失/坏数据/隐私；无root/udev需求 |
| daoseeker-scope-macos | 公开sysctl hw.model/hw.memsize，固定4096字节缓冲 |
| daoseeker-scope | 主门面Hardware及JSON，default serde，可选schema；目标cfg隔离、无sysinfo类型泄漏 |
| daoseeker-scope-ffi | ABI v1/options/header、线程局部错误、panic捕获、注册buffer/token/重复释放、C/Python例子 |
| daoseeker-scope-cli | dscope所有指定命令/help/version/文本/完整Snapshot JSON/稳定退出码/脱敏与高级授权 |
| 验证与交付 | 黄金样例、Schema生成、26测试+doctest、CI三平台/审计/fuzz、独立fuzz harness与锁、benchmark、check/schema/C脚本 |

首次创建，无既有公共API/feature迁移；crate版本0.1.0，ABI=1，Schema=1。可扩展枚举non_exhaustive，未知JSON枚举拒绝；新增枚举值需Schema主版本协商。Observed字段私有，通过构造函数/getters访问；Snapshot结构公有但交换入口再次验证；静态首次采集后缓存失败字段也不自动重读。collect_with/refresh_dynamic_with提供取消token。所有--json命令包含完整版本化快照。

直接依赖：core可选serde/schemars；sysinfo0.39.6 MIT；windows-sys0.61.2 MIT OR Apache2.0；macOS libc0.2.190 MIT OR Apache2.0；serde_json交换格式。root锁定图39个第三方包，cargo-deny0.20.2三平台advisories/licenses/bans/sources通过，上游syn2/3重复警告保留。schemars仅schema feature；不新增Tokio/WMI/udev/Metal/AI服务。fuzz独立依赖libfuzzer-sys0.4.13和其构建依赖，未进入发行运行依赖；jsonschema4.25.1和cargo-deny仅开发工具。本项目双许可证不覆盖第三方版权义务。

实际完整命令、主机结果与早期失败已在validation.md记录；性能含5次native首读与100传感器/1024网络合成数据见benchmarks.md。Windows Rust、CLI、C/Python实际成功；Linux/macOS只交叉类型检查，尚不能称三平台正式发布DoD通过。fuzz只编译，没有campaign。无移动/Web/no_std/MCU已支持声明。

兼容性/限制：0.1尚未经维护者发布评审；阻塞OS调用无法强杀且构造/JSON编码不在查询timeout内；sysinfo错误/内部集合上限不足；静态失败缓存不会自动随权限变化重试；不保证OS多API原子快照；C无效地址/释放后并发访问/OOM/panic=abort不能捕获；未完成sanitizer、分配profiling、release制品与三平台原生CI。

下一切片：先维护者审阅5份ADR/Schema与隐私/资源契约，并在可访问仓库跑Linux/macOS原生CI、FFI、容器降级与fuzz/sanitizer；再单独实现有界Linux电池/hwmon或桌面受控磁盘/网络枚举。GPU/显示器以后按独立可验收切片实现。移动/Web保持P1实验路线。

## 2026-10-09 增量：输入与FFI验证

修改FFI buffer所有权为Arc，修复Miri发现的指针别名失效；集中注册表大小/容量/token校验，新增读取/扩容/并发/重复释放/失败路径回归。CLI解析拆至lib，非法OS参数编码返回退出码2；新增JSON/DMI确定性输入回归、CLI fuzz目标和种子，固定nightly/cargo-fuzz，CI增加Windows C、Miri及Linux Rust FFI ASan。

实际完整门禁通过37项测试+1项doctest，8项Miri检查通过，C/Python100次真实调用、实时Schema、供应链复验通过。Linux/macOS仍仅交叉类型检查；fuzz三个harness编译通过但未campaign，ASan只配置未运行，benchmark未重跑。主硬件API/feature不变，ABI=1、Schema=1，无新增运行时第三方依赖；CLI移除直接serde_json依赖，root第三方包仍39个。详细文件/命令/中途失败/限制见 [输入与FFI验证](input-ffi-validation.md)。下一步仍为三平台原生CI、容器与fuzz/ASan证据，之后才做独立平台增强。未commit/push/创建远端或发布。

## 2026-10-09 增量：原生验收与CI证据

新增scripts/native_smoke.py、tests/test_native_smoke.py，修改三平台CI统一执行并保留报告，增加Python静态/单元门禁；更新README/validation/release，保留Windows实际报告。四项Python守卫、Ruff/mypy、actionlint以及Windows原生CLI/C/Python、Schema均通过。公共Rust API、feature、ABI=1、Snapshot Schema=1不变，无新增运行依赖；开发工具/action为MIT。Rust完整门禁本轮未重跑。Linux/macOS、fuzz/ASan尚未执行，目标仓库仍无法访问，未创建/上传。下一步需要用户明确目标仓库可见性与创建/推送，再运行三平台CI。完整文件、命令和限制见 [原生验收](native-validation.md)。

## 2026-10-09 增量：私有仓库与三平台CI

按用户授权创建私有仓库DaoSeeker01/DaoSeekerScope，提交a0acc06并推送main。首次CI运行37864529108的7个任务全部通过；三平台原生最小闭环、C/Python、Miri、ASan、供应链与3个60秒fuzz取得实际证据。新增docs/ci-validation.md及4份docs/evidence/ci-*.json，更新README、release、validation、native-validation、平台矩阵和fuzz文档；.gitattributes固定文本LF，.gitignore排除开发缓存，清除首次暂存的多余文件尾空行。8个crate、feature、公共API、0.1.0、ABI=1、Schema=1、Cargo.lock及第三方许可证均未变化。

证据归档提交仅修改文档和JSON报告，使用[skip ci]避免重复相同代码门禁；真实被测源码提交始终为a0acc06。没有把该文档提交描述成新一轮Rust验证。下一切片先补Linux容器/DMI缺失/权限降级原生场景和CI运行环境维护，再进行独立平台增强；长期fuzz、内存profiling、cargo package与发行评审仍待完成。没有发布release/crates.io，也没有新增移动/Web/no_std/MCU支持。实际命令、runner和已知限制见[CI验收](ci-validation.md)。

## 2026-10-10 增量：Linux容器证据归档

源码切片新增scripts/linux_container_smoke.py、tests/test_linux_container_smoke.py，修改.github/workflows/ci.yml。CI固定Ubuntu24.04、Node24官方actions，禁用Cargo HTTP multiplexing以修复实际下载失败；不修改TLS验证或生产Rust采集逻辑。新增非root、只读、断网、资源限制的7个实际CLI场景和一个单列的运行时探针，Fixture守卫新增8项。没有新增crate、feature、公共API或运行依赖，0.1.0、ABI1、Schema1、Cargo.lock及运行依赖许可证不变；更新的开发actions仍MIT。

2026-10-09运行37867335002对源码8e0e7d9全部8任务success：三平台各37Rust测试+1doctest、12Python守卫、fmt/clippy/doc/no-default-features、Schema、CLI/C/Python通过；Miri8、Rust FFI ASan10、cargo-deny和3个60秒fuzz通过；7个容器场景passed。完整/proc挂载被Docker OCI拒绝，进程未执行，单列not_run。DMI内容是合成数据，不能代替真机主板识别证据。中途失败和取消没有改写成成功，细节见[完整切片报告](linux-container-validation.md)。

归档修改README、docs/linux-container-validation.md、ci-validation.md、validation.md、delivery.md、release.md、adr/0005-platform-support-matrix.md，并新增5份docs/evidence/*37867335002.json（CI元数据、容器、三平台原生）。核验报告状态、源码SHA、dirty=false、锁哈希及Linux CLI产物一致；本地git diff --check和文档链接/JSON检查通过。原始日志留在忽略目录，文档提交使用[skip ci]，被测源码仍为8e0e7d9。

未执行新的benchmark、长期campaign、峰值分配、cargo package或发布；既有静态失败缓存、阻塞OS不可强杀、FFI调用方指针限制不变。下一独立切片先覆盖CPU采样就绪与动态源中途失效/刷新语义，再扩展Linux电池/hwmon。其他容器/安全策略、移动/Web/no_std/MCU不增加支持声明。

## 2026-10-10 增量：Linux CPU采样新鲜度

修改LinuxBackend（新增私有cpu.rs）与SysinfoBackend，新增dynamic_probe Rust示例、scripts/linux_dynamic_smoke.py及tests/test_linux_dynamic_smoke.py；CI增加示例构建、连续采样回归与报告保留，Python门禁扩展至六文件/16项守卫。新增7项CPU Rust测试与Linux单独sysinfo注入测试；不泄漏原始计数或sysinfo类型，不新增unsafe、运行依赖或crate。feature不变，示例要求既有serde；0.1.0、ABI1、Schema1及依赖许可证不变。Linux CPU source改为procfs，独立sysinfo注册不再提供该字段，迁移指引在ADR0002与README。

先提交448dd81回归探针，运行38005835576实际失败并归档旧Available/50%错误；随后3ec5f6e修复，容器15项连续观测和原7场景通过。本地主机完整Rust门禁44测试+1doctest、Schema及16项Python守卫通过，沙箱doctest写exe拒绝后普通主机权限重试通过；最终CI结果、未执行验证和完整命令见[CPU刷新报告](cpu-refresh-validation.md)。归档只更新文档/证据，使用[skip ci]，不能算新源码验证。

内存/uptime仍保留sysinfo Partial与缓存局限，Windows/macOS CPU路径未改；完全缺失procfs、其他容器/安全策略、长期CPU解析器fuzz、benchmark、峰值分配、打包和发布未执行。下一独立切片先处理Linux内存/uptime结构化失败与新鲜度，再扩展设备枚举。

## 2026-10-10 增量：Linux 内存与 uptime 新鲜度

修改LinuxBackend与SysinfoBackend、新增私有procfs.rs；扩展desktop真实读取测试，新增7项解析/IO测试和2项缓存/恢复测试。新增scripts/linux_memory_smoke.py、tests/test_linux_memory_smoke.py，复用现有动态Docker控制器，更新原容器期待及CI检查/报告上传。未新增crate/feature/unsafe/运行依赖；公共签名/模型、MIT OR Apache-2.0、ABI1/Schema1及Cargo.lock不变。Linux sysinfo单独注册不再提供内存/uptime，需补LinuxBackend或使用门面，静态失败缓存仍适用。

回归源码64e65c0的38008139512仅容器按预期失败，确认旧内存值被打新时间与uptime回退；修复源码6d0a377的38008554490全部8任务成功。26项内存/uptime、原15项CPU和7场景通过；本地53项Rust测试+1doctest、CI Linux54/Windows及macOS53项+各1doctest、20项Python守卫、全部格式/类型/文档/Schema门禁、原生CLI/C/Python、Miri8、ASan10、审计及既有fuzz通过。完整命令、8份归档报告、兼容与未验范围见[验收](memory-refresh-validation.md)。

归档更新README、ADR0002/0005、release、validation、delivery、ci-validation及新验收文档，保存8份JSON；只改文档/证据，使用[skip ci]，被测代码仍6d0a377。未重跑benchmark/长期campaign/峰值profiling/打包/发布，未增加新平台支持。下一独立切片优先补私有procfs解析器的fuzz入口与独立验证，再推进Linux电池受控枚举。

## 2026-10-10 增量：procfs独立fuzz

源码4eb7e971新增Linux默认关闭的内部fuzzing feature、隐藏CPU/meminfo/uptime入口及3项确定性测试；新增3个fuzz harness、共享Observed断言和25个种子；CI扩展为六目标并保存新目标日志/失败输入。ADR0006固定内部入口与有界输入契约；生产采集、标准公共模型、版本0.1.0、ABI1/Schema1、两份锁与MIT OR Apache-2.0不变，没有新增unsafe/第三方依赖。隐藏feature入口不是稳定消费者API。

本机完整Rust门禁56项+1doctest、fuzz workspace fmt/check/clippy、默认关闭feature测试20项及actionlint通过。运行38044730604全部8任务成功：Linux57、Windows/macOS56项Rust测试+各1doctest及20项Python守卫、原生CLI/C/Python、Schema、Miri8、Rust FFI ASan10、审计，7/15/26个容器场景/观测通过。六个独立fuzz目标各60秒正常结束，新CPU/内存/uptime分别执行1,263,006/4,324,530/19,206,072次。早期测试控制字节修正与基础设施EOF/TLS重试有明确记录，没有降低测试门禁。

后续归档README、fuzz README、验收/交付文档及8份JSON，使用[skip ci]；证据绑定源码4eb7e971，完整命令、哈希与未验范围见[报告](procfs-fuzz-validation.md)。完整/proc运行时拒绝仍not_run；未执行长期campaign、benchmark、峰值profiling、打包或发布。下一独立功能为Linux电池受控枚举，移动/Web/no_std/MCU仍属后续路线。

## 2026-10-10 增量：Linux电池受控枚举

新增Linux私有battery.rs、固定power_supply根路径、capacity/present/Mains online只读映射与Partial能力；7项跨平台fixture测试、Unix symlink测试和512输入变异测试。已有默认关闭fuzzing feature增加隐藏属性入口，新harness与10种子；新增电池30观测脚本及6项证据/控制器守卫，CI原生报告额外记录电池状态。公共模型/字段/feature集合/版本0.1.0、ABI1/Schema1及两份锁/许可证不变；Schema只增加字段说明元数据，没有新增unsafe或依赖。

初版fd18b29的CI38047029198仅容器电池步骤失败，13观测已通过后控制器写000合成文件失败；失败报告/元数据保留。本机复现并增加恢复写入回归，修复仅修改控制器/守卫，未改生产Rust或降低门禁。修复源码15ef5c1的CI38047435339全部8任务成功：Linux66、Windows64、macOS65项Rust测试+各1doctest，26项Python守卫、fmt/clippy/doc/no-default-features/build/Schema、原生CLI/C/Python、Miri8、Rust FFI ASan10、审计和七个60秒fuzz通过。新power_supply目标19,744,677次正常结束；30项电池、26项内存/uptime、15项CPU和7个原容器场景通过，完整/proc探针仍not_run。

本机check.ps1 -Cross为64项Rust+1doctest，七harness fmt/check/clippy、Python/Schema/actionlint与C重新编译/实际调用通过。Linux runner只返回Available空集合，不证明实际笔记本电量；Windows runnerNotApplicable、macOSUnsupported保持实际状态。本机Win32电量100%/AC=true是独立fd18b29读值。完整命令、12份证据、兼容性与边界见[验收](battery-validation.md)。归档仅文档/JSON，使用[skip ci]；未重跑benchmark/长期fuzz/分配profiling/打包/发布或验证真实Linux电池，下一独立切片可推进有界hwmon。

## 2026-10-10实施 / 2026-10-11归档：Linux hwmon温度

源码3c04fd3与CLI补齐0fbc84a已推送；最终[CI38065295625](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38065295625)8/8成功。新增Linux私有hwmon模块、ADR0008、6个本机/7个Unix hwmon测试、已有fuzzing隐藏入口/第8个目标/10种子、容器36观测及5个报告守卫；core只增字段文档，Schema只增description。CLI文本逐项显示温度/状态，未复制采集逻辑。运行依赖/锁/feature集合、公共模型形状/签名、MIT OR Apache-2.0、ABI1/Schema1不变。

实际完成scripts/check.ps1 -Cross（fmt/clippy -Dwarnings、test、doc -Dwarnings、no-default-features/build/cross check）、八harness fmt/check/clippy、12份Ruff/mypy --no-incremental、31项Python守卫、Schema/黄金样例/未知字段/版本、actionlint、C重建与本机CLI/C/Python100次collect/free。最终Linux73/Windows70/macOS72项Rust各+1doctest；8项Miri、10项Rust FFI ASan、cargo-deny及8个60秒fuzz通过。新hwmon fuzz实际61秒43,961,544次。

36项为合成hwmon/真实内核权限/FIFO/目录/资源及恢复验证，不是物理温度验证；最终Linux原生Available空集合，Windows/macOS Unsupported。CLI原生文本只覆盖空/Unsupported路径。未知驱动、Tctl/电压/风扇不转换摄氏度；未运行新性能benchmark、长期fuzz或打包/发布。11份源码绑定JSON与哈希已核验，见[完整验收](hwmon-validation.md)。下一步应逐项增加有文档与实机证据的温度路由或设备验收。

## 2026-10-11：NVMe hwmon增量验收

源码9931cf9的[CI38067341915](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38067341915)八任务success。Linux仅增加nvme通道1..9路由，零Kelvin不发布为温度，Composite是设备报告计算值；默认标签/标识采集边界不变。71项本机Rust+1doctest、fmt/clippy/doc/no-default-features/build/cross check、八harness fmt/check/clippy、32项Python守卫/修改脚本Ruff/mypy、Schema/actionlint、C重建与CLI/C/Python实际调用通过。CI Linux74/Windows71/macOS73项Rust各+1doctest、12份Python静态检查/32守卫、Miri8、Rust FFI ASan10、审计和八个60秒fuzz通过；47项hwmon（11项NVMe）、30电池/26内存/15CPU/7容器通过，完整proc替换仍not_run。属性hwmon fuzz 35,010,619次/61秒正常结束。

11份源码绑定JSON、任务ID/日志和12种子哈希见[NVMe验收](nvme-temperature-validation.md)。原生Linux无传感器条目，Windows/macOS Unsupported，未验证真实NVMe温度、校准、新benchmark、长期fuzz或打包/发布。公共稳定模型/签名、0.1.0、ABI1/Schema1、feature集合、锁与MIT OR Apache-2.0不变，仅Schema说明元数据及默认关闭隐藏fuzz hook增加；后续真实设备验收与性能/打包门禁独立推进。
