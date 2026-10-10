# Linux NVMe hwmon 温度验证

2026-10-11。[CI38067341915](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/38067341915)八任务全部成功，绑定源码`9931cf9ed789e600c89cb67f123c9bb878e5ddfb`。独立切片，补充[既有hwmon验收](hwmon-validation.md)；真实NVMe设备读取与温度校准仍未验证。

[ADR0009](adr/0009-linux-nvme-temperature.md)先固定通道、单位与零Kelvin策略。Linux私有hwmon模块新增name=nvme的1..9路由：Composite与八个独立通道均为后端报告的摄氏度。内核已将Kelvin转换为毫摄氏度，库只除1000；Composite可为设备计算值，不能承诺物理点或校准准确度。更高通道Unsupported且不打开input。

- -273150毫度：Composite为Unavailable/InvalidData；独立通道为Unavailable/NotPresent，表示本次报告未实现温度值，不推断整个设备不存在。合法0°C与负摄氏度保留。
- 坏数值、权限、可选enable/fault、每次枚举与恢复复用既有hwmon契约；失败不带旧值/时间，单个字段失败不抹去健康通道。
- 标签始终Restricted/PrivacyRedacted；不读serial/device/uevent，不访问/dev、不发ioctl或写阈值。四级限额、调用方等待、不能硬取消阻塞驱动及TOCTOU边界不变。

文件变化：Linux hwmon.rs/fuzzing.rs、core SensorInfo字段文档、Schema description、现有hwmon fuzz harness与两个种子、容器控制器和报告守卫。新增一个Rust全部九通道/单位/零Kelvin/恢复测试和一个Python报告守卫；容器从36增至47观察（11项NVMe）。默认关闭fuzzing增加隐藏hook，不属于稳定公共API。Rust公共模型形状/签名、0.1.0、ABI1/Schema1、feature集合、运行依赖与两份锁文件、MIT OR Apache-2.0不变；仅研究公开接口，没有复制GPL内核代码。行为兼容变化为已知NVMe通道可由Unsupported转为Available或明确失败状态，调用方必须逐项判断Observed。

## 实际命令与结果

本机Windows x64/Rust1.96.0，通过mise，CARGO_INCREMENTAL=0。实际执行scripts/check.ps1 -Cross（fmt、Clippy -Dwarnings、workspace all-features test、core/门面no-default-features、rustdoc -Dwarnings、CLI/FFI build、Linux x64/macOS arm64交叉check）：71项Rust测试+1doctest通过。fuzz manifest fmt/check/clippy八harness通过，Windows编译不等于libFuzzer执行。32项Python报告守卫、两份修改脚本的Ruff format/check及mypy --no-incremental、check_schema.py黄金样例/未知字段/版本、actionlint通过。C重建和native_smoke.py的CLI/C/Python100次collect/free通过，源树干净且绑定相同源码。

控制器结构在Windows通过模拟47步/11项NVMe核对；最初只读位阻止删除自有模拟文件，改为模拟权限/FIFO后核对完成。该检查不算内核验收，也没有修改生产或Linux权限门禁。

三平台CI实际完成上述Rust门禁和原生CLI/C/Python、Schema，12份Python脚本/测试的Ruff/mypy与32项守卫；Linux74/Windows71/macOS73项Rust各+1doctest。8项Miri内存契约、10项Rust FFI ASan、cargo-deny与八个配置60秒fuzz通过。C原生示例不是ASan插桩的C端测试。

| 任务 | 实际结果 |
|---|---|
| ffi-asan / 114257557372 | success |
| supply-chain / 114257557527 | success |
| fuzz-smoke / 114257557532 | success |
| desktop (ubuntu-24.04) / 114257557556 | success |
| miri / 114257557567 | success |
| desktop (macos-latest) / 114257557570 | success |
| desktop (windows-latest) / 114257557571 | success |
| linux-container / 114257557590 | success |

运行UTC开始2026-10-10T16:21:38Z，结束2026-10-10T16:31:20Z。原始日志测试计数和哈希已核验，不把文档矩阵当实验记录。

## 合成容器与原生观测

47个连续hwmon观察全部passed，其中11项NVMe包括Composite/独立通道毫度值、两类零Kelvin、合法零/负摄氏度、输入权限拒绝、单坏字段、恢复、未知通道FIFO、拔插和重新枚举。所有观察Schema有效，内存健康、静态缓存不变、能力与来源/原因/时间匹配，默认标签不泄露。内容是合成fixture；权限拒绝/FIFO/只读挂载由真实Linux内核执行。生产Hardware探针确实启动且进程/Docker退出0。

容器实际UID/GID65534、只读rootfs/挂载、断网、cap-drop ALL/no-new-privileges、内存与交换总量256MiB、PID32、CPU1、nofile64。原电池30/内存26/CPU15/容器7项保持通过。完整/proc替换的额外探针仍runtime_rejected_mount、process_started=false、not_run，不能算backend验收。

原生Linux CLI/C sensors均Available空集合，Windows/macOS及本机Windows Unsupported/NotSupported。因此本轮没有真实NVMe温度值；数值文本CLI分支也未由原生设备命中。原生sensor条目没有公开驱动标识，不能仅凭SourceHwmon把未来的任意温度归因于NVMe。

## 属性 fuzz 与持久证据

扩展现有hwmon_temperature目标，复用生产解析器和Composite/独立通道零Kelvin策略；12个种子，包括已有绝对零度与新增NVMe毫度样本。实际61秒、**35,010,619次**，cov154/ft343、最终RSS306Mb，无崩溃完成。seed20261010、输入512字节、属性128字节、单输入2秒/RSS终止512MiB。原始日志66,708字节、SHA256 `7b2d69aec9a69915328006b842017f4a7bdfdbce96c77929161a0f2c2baf8cc2`；12个种子逐字节与被测Git对象一致。

属性fuzz不测试目录/权限/热插拔或物理设备；cov/ft不是覆盖百分比，RSS包含libFuzzer/ASan，不是库benchmark或硬沙箱。八个目标均核验DONE/Done完成标记；变异corpus未归档，固定seed不保证限时运行次数逐次一致。

11份持久JSON：[CI元数据](evidence/ci-run-38067341915.json)、[原容器](evidence/linux-container-38067341915.json)/[CPU](evidence/linux-dynamic-38067341915.json)/[内存](evidence/linux-memory-38067341915.json)/[电池](evidence/linux-battery-38067341915.json)/[hwmon](evidence/linux-hwmon-38067341915.json)、[Linux](evidence/linux-native-38067341915.json)/[Windows](evidence/windows-native-38067341915.json)/[macOS](evidence/macos-native-38067341915.json)原生、[本机Windows](evidence/windows-native-nvme-2026-10-11.json)、[fuzz/测试汇总](evidence/nvme-fuzz-38067341915.json)。报告成功/源码/git_dirty=false/锁哈希、容器状态和零Kelvin/零摄氏度/FIFO观察均已独立核对。原始日志保存在忽略目录target/ci-evidence/38067341915，GitHub artifact保留14天；哈希绑定不是签名或供应链认证。

## 未执行与下一阶段

真实NVMe设备温度、物理温度计比对、更多内核/驱动版本、长期fuzz、新性能benchmark/分配profiling与发行打包未验证。没有新增GPU/存储/网络或移动/Web/no_std/MCU支持。下一阶段优先真实设备验收与性能/打包门禁，新增温度路由仍须独立资料和测试，不扩大默认标识采集。
