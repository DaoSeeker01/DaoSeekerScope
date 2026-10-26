# ADR 0034：Linux FFI SDK 候选包

日期：2026-10-26。状态：实现；干净提交 f262095 的共享工具守卫与 Windows SDK/CLI 回归通过，原生 Linux 构建、C/Python 调用及权限验证待 CI；见[记录](../linux-ffi-sdk-validation.md)。

## 选择

在既有 Windows SDK 的打包工具中加入 GNU/Linux x86_64 SDK，不增加 crate、依赖、feature 或公共 API。构建入口仍是 `python scripts/cli_bundle.py --product ffi_sdk`，按 rustc host 与运行平台双重核验，只允许原生构建，不在 Windows 生成声称可用的 Linux 二进制。

Linux SDK 采用独立 `bundle_format=4`、`product=ffi_sdk`。Windows SDK 保持 3，Windows/Linux CLI 保持 1/2；C ABI 1、硬件 JSON Schema 1 和 MIT 不变。独立版本避免旧的仅 Windows SDK 读取器接受不认识的布局。macOS SDK 和 CLI 分发材料仍是独立待办。

归档包含 `lib/libdaoseeker_scope_ffi.so`、维护来源原样复制的 C 头文件、C/Python 示例、Schema、项目与依赖/Rust 许可文件和使用说明。不提供静态库或 Windows 导入库。继续使用新 target-dir 的 release 构建、目标过滤的 FFI 依赖闭包、SHA256SUMS、逐文件 manifest 及既有大小/数量限制，缺许可材料即失败。

Linux SDK 所有归档文件为普通文件、权限 0644；共享库不依赖文件的执行位。manifest 和 ZIP 元数据都必须匹配权限契约，安装后显式恢复权限并在激活前复查。C 消费者由验证步骤编译产生，其执行位由编译器设置。CLI 的 0755 规则不变。

## 加载与验收

C 示例以包内头文件和 `lib/` 中共享库编译，设置 `DT_RUNPATH=$ORIGIN/../lib`。根据 [GNU ld](https://sourceware.org/binutils/docs/ld/Options.html) 和 [Linux 动态加载器](https://man7.org/linux/man-pages/man8/ld.so.8.html)，这将直接依赖的库搜索路径关联到消费者目录；不能据此推断系统传递依赖或最低 glibc 版本已满足。验证使用 [readelf](https://sourceware.org/binutils/docs/binutils/readelf.html) 的 dynamic 信息，要求消费者仅使用该 RUNPATH、NEEDED 包含无路径的 `libdaoseeker_scope_ffi.so`，拒绝额外 RPATH；库自身不允许嵌入 RPATH/RUNPATH，依赖名称不允许绝对/相对路径。报告仅保存依赖 basename，不保存构建路径。

每个子进程使用独立环境副本，移除 LD_* 和 GLIBC_TUNABLES，readelf 使用 C locale；不修改父进程、全局 PATH、ldconfig 或系统 loader 配置。这是可复现性边界，不是对系统级 preload、受损工具链或不可信主机的隔离承诺。Python 传入包内 .so 的绝对路径。父验证进程不加载共享库。

安装、切换、回滚三个阶段分别编译并运行 C、运行 Python、检查消费者/共享库 ELF，共 15 项顶层调用：3 次编译、3 次 C、3 次 Python、6 次 readelf；不含编译器和链接器子孙进程。Python 合计 300 次 collect/free，C/Python 同时验证 ABI、Schema、默认隐私、最低读取、空释放和 stale copy 拒绝。单进程 90 秒、输出读取上限 1 MiB，失败覆盖旧 pass，报告不保留原始硬件快照。

复用两槽位安装/激活，损坏更新在创建目录前拒绝，最后回到同候选的第一份。此证据不是旧正式版升级或迁移验证，也不是完整内存泄漏证明。拒绝错误产品和宿主必须发生在安装/执行前。Windows SDK 的字段与九次顶层调用契约保留。

回退可撤销 Linux SDK 的格式、载荷与消费者分支和 CI 入口；保留现有三种格式。当前无新二进制发布、签名、registry 或 Release 操作。
