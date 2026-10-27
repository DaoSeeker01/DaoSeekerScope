# ADR 0036：Linux 候选包的符号版本要求

日期：2026-10-28。状态：实现；本轮验收见[验证记录](../linux-runtime-validation.md)。

## 问题与选择

已有 Linux SDK 检查 ELF 直接依赖和 RUNPATH，但没有记录所需的符号版本。CLI 尚未做同类检查，运行时还会继承开发者的 `LD_*` 和 `GLIBC_TUNABLES`，可能掩盖环境依赖。

复用已要求安装的 [GNU readelf](https://sourceware.org/binutils/docs/binutils/readelf.html)，一次读取 `--wide --dynamic --version-info`。不引入通用 ELF 解析库，也不运行 `ldd` 或在验证父进程中加载候选库。共享工具只接受当前 GNU 工具的 C locale 文本，格式不认识时明确失败。

保留现有 NEEDED/RPATH/RUNPATH 规则。SDK C 消费者必须直接依赖 `libdaoseeker_scope_ffi.so`，RUNPATH 仅为 `$ORIGIN/../lib`；SDK 库和 CLI 不允许 RPATH/RUNPATH。根据 [Linux loader 文档](https://man7.org/linux/man-pages/man8/ld.so.8.html)，这个 RUNPATH 只覆盖直接依赖，不能据此宣称传递依赖已满足。

只解析 version needs，不把 version definitions 或已提供符号当作要求。按依赖库保存完整版本名称，保留 `GLIBC_ABI_*` 等非数值条件，并单独列出没有版本条目的直接依赖；后者不表示该依赖没有兼容性要求。数字版本按整数分段比较，避免把 2.9 错排在 2.34 之后。`highest_glibc_numeric_requirement` 只表示当前产物声明中的数值最大值，不是项目的最低 glibc 或发行版承诺。拒绝直接依赖 `GLIBC_PRIVATE` 的候选。

## 边界与接入

输出读取最多 1 MiB。版本依赖文件最多 64 个、每个文件最多 256 个版本、总计最多 1024 个版本、名称最多 128 个 ASCII 字符。检查文件和辅助条目计数、直接依赖归属、重复与截断。缺少或无法识别版本表不能返回“没有要求”。这是当前动态 GNU 候选的契约，不是静态 ELF、musl 或任意第三方二进制的通用检查器。

CLI 在第一份候选安装后、执行前检查一次 ELF；验收从六次进程启动增加到七次，其中一次为 readelf。三个实际 CLI 阶段仍各运行版本和 JSON 检查。SDK 将原有六次 readelf 调用扩展为同时读取版本信息，顶层调用仍为 15 次。三阶段语义报告必须一致。原有 `elf_needed` 字段保留，报告新增 `elf_image` / `elf_images`。

CLI 的 readelf 和所有运行子进程、SDK 的既有子进程均使用独立环境副本，移除 `LD_*` 与 `GLIBC_TUNABLES`，设置 `LC_ALL=C`；不改父进程、系统 PATH 或 loader 配置。CLI readelf 超时 30 秒，SDK 继续沿用 90 秒边界。它不能隔离受损主机或系统级 loader 配置，也不枚举传递依赖和运行期 `dlopen`。

纯文本负向测试之外，Linux CI 实际用系统 C 编译器创建一个调用 libc 的共享库，再读取其 readelf 输出；不加载该测试库。真实 CLI/SDK 候选仍须通过原有安装、C/Python、Schema、隐私和回滚门禁。Windows/macOS 上的文本测试不算 Linux 原生证据。

公共 Rust API、C ABI 1、硬件 JSON Schema 1、ZIP 格式 1/2/3/4、crate、feature、依赖和 MIT 均不变。回退只需撤销候选版本检查及新增报告字段；已有 SDK 路径检查和格式契约保留。最低 glibc/内核/发行版验证仍是独立发布前任务。
