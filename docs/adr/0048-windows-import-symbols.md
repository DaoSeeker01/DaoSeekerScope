# 0048 Windows 候选包的导入符号

日期：2026-11-01。状态：已实现，原生与 CI 验收见[记录](../windows-imports-validation.md)。

现有 PE 检查只列出 DLL 名称，无法说明实际使用哪些入口。本轮在原有模块清单旁增加 `direct_symbols` 和 `delay_symbols`，按小写 DLL 名称分组，分别保存 `names` 和 `ordinals`。符号名称保留大小写；序号与名称分开，不用字符串伪装未知入口。导入可能是函数或数据，检查不推断其类型。

依据微软 [PE 规范](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)读取 PE32+ 的 64 位 lookup 表、名称/序号标志、保留位和 Hint/Name 记录。优先使用普通 INT；它缺失时，只允许时间戳为零的未绑定 IAT 回退。已绑定且没有 lookup 的图像明确失败。延迟导入仅接受已有的 RVA 形式，并要求 INT，不能把可能已填入地址的延迟 IAT 当成名称。

每张 lookup 表最多 8192 条，普通与延迟表合计最多 16384 条；去重前计数，避免重复描述符绕过预算。名称最多 1024 字节，当前候选子集仅接受非空、无空白的可打印 ASCII；序号保留 0–65535。沿用 64 MiB 图像、96 节区和模块上限；表与字符串不得越过文件支持的范围，虚拟补零区不能补终止符。这是候选工具的明确子集，不能视为完整 Windows 加载器。

新增 Windows 独立对照入口：校验当前干净源码的 CLI/SDK 归档，安装到临时目录，重新编译包内 C 消费者及一个 USER32 延迟导入样例，再与微软 [DUMPBIN /IMPORTS](https://learn.microsoft.com/en-us/cpp/build/reference/imports-dumpbin)逐项比较。四个图像均只读、不执行；既有 CLI/C/Python 运行验收仍独立进行。MSVC/SDK 沿用现有发现逻辑，不固定维护者路径。

对照要求当前提交、候选清洁标记和前后源码一致；核对图像和工具字节未变，子进程有退出码、90 秒等待限制，读取输出不超过 2 MiB。失败或中断会作废旧成功报告。工具输出只保留模块、符号、版本和哈希，不归档完整路径。

模块列表、ZIP 1/2/3/4、Rust API、依赖/features、MIT、C ABI 1 和硬件 Schema 1 不变。仅候选验证报告增加符号字段，损坏或超限的 lookup 表现在会被拒绝。最低 Windows 仍未验收；不解析 API-set 转发、递归依赖、运行期 LoadLibrary/GetProcAddress 或签名，不能由静态清单推断最低 OS。撤回该增强时保留旧证据，恢复模块级检查即可。
