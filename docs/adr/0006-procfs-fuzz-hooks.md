# 0006 procfs 解析器 fuzz 入口

日期：2026-10-10。范围只包括现有 Linux CPU、内存和 uptime 解析/采样，不扩展硬件枚举。

选择 Linux crate 默认关闭的 `fuzzing = []` feature 和隐藏的 `fuzzing` 模块，供仓库内部测试使用；入口不作消费者API稳定性承诺。默认编译没有这些函数，主门面、核心模型、ABI1/Schema1与现有采集行为不变。`--all-features` 会编译入口，不能据此称它默认开启。没有增加运行依赖、unsafe、crate或平台支持。

候选：复制解析器到fuzz harness会使验证与生产代码漂移；无条件公开原始解析/计数类型会扩大消费者契约；直接在fuzz crate include平台模块会耦合源码路径及模块可见性。选择小型feature入口调用同一私有解析器与CPU采样状态机，返回现有Observed类型。cargo-fuzz默认设置cfg(fuzzing)也是可行路线，但本项目还需Windows稳定编译及确定性测试，feature能让相同入口在这些门禁中受检。依据：[Rust Fuzz Book配置说明](https://rust-fuzz.github.io/book/cargo-fuzz/guide.html)（2026-10-10核验）。

CPU输入为前8192字节内最多16个NUL分隔帧，每帧首字节低两位选择0/50/300/1000ms步长、再两位选择读取/合成PermissionDenied/NotFound/Other，余下字节走生产有界stat reader。0控制字节本身是分隔符，零步长读取可用0x10编码。每次附加固定错误→新基线→50%→0%→100%序列，检查任意输入后的基线清理与恢复。最多21项输出，固定时间戳；Instant仅作单调锚点，不睡眠、不访问真实procfs。

内存和uptime入口直接调用生产解析器及Observed转换，保留4096/256字节上限。harness检查状态/来源/时间/原因不变量、整数/单位/总量关系、重复调用确定性，并用规范化输入验证合法零值、字段隔离、重复键拒绝和小数截断。IO错误标志是合成输入，不算内核权限证据；File::open、时钟等待、真实缓存总量变化仍由独立原生/容器测试验收。

三个独立目标cpu_stat、meminfo、uptime共有25个合成种子；CI各运行60秒，固定seed20261010、单输入timeout2秒、RSS终止门限512MiB、输入最大8192/8192/512字节，job最多15分钟。显式pipefail使tee日志不掩盖fuzzer错误；always上传日志及存在的失败reproducer。失败或未运行不能以有日志代替成功。运行计数和插桩反馈不等同代码覆盖百分比；60秒smoke不替代长期campaign，固定seed也不保证时间限运行逐次一致。

回滚可移除feature、隐藏入口及三个harness，生产默认路径不受影响；失败用保存的输入复现、最小化，再建立独立回归测试。许可证/锁文件不变。命令、实际结果、未验范围与原始证据见[procfs fuzz验收](../procfs-fuzz-validation.md)。
