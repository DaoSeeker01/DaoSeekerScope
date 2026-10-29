# 0042 发布前契约基线与原生 ABI 对照

日期：2026-10-29。状态：实施决定；不代表维护者已批准发布。

## 问题

生成的 Schema 与仓库文件相等，只能证明两者同步；如果实现和 Schema 同时改变，原检查不会要求兼容性评审。C 头文件与 Rust 的 `repr(C)` 定义也可能各自编译成功，却在字段偏移上产生差异。此外，安装头文件缺少使用指南已有的共享库加载期限，调用方可能在 worker 仍运行时卸载代码。

## 决定

保存 [v0.1 基线](../contracts/v0.1.json)：八个包的 features、构建类型与版本/许可声明，以及完整 Schema 的规范化 JSON 哈希。忽略对象键顺序和排版，保留注释性关键词；任何差异都需要评审，并不自动认定为破坏性变化。不得仅为使 CI 变绿重新生成基线。

用独立的 C 与 Rust 程序读取结构体大小、对齐和字段偏移，同时与基线比较。C 程序链接本轮构建的共享库，调用四个固定符号的版本、非法参数、空释放和错误文本路径，不启动采集器。Rust 示例检查函数指针签名和 Schema 版本；Rust 单元测试固定九项错误映射。检查运行在三个现有原生 CI 目标，不推断 32 位或其他架构支持。

所有安装头文件、Rust FFI 文档和使用指南明确：任何 `dsc_collect_json` 调用后，包括失败或超时，须保持共享库加载至进程结束。ABI 1 没有 shutdown/排空接口，释放全部 Buffer 不足以支持卸载或热重载。此次只补齐既有契约的说明，不更改布局、符号、行为或版本。

## 验证与限制

`python scripts/check_contract.py` 仅接受干净提交，在专用目录显式构建本机目标，结束后核对提交与工作区状态。报告含输入、共享库哈希、编译器及双方布局；失败或中断先作废旧成功报告。负面测试覆盖布局、版本、错误码、类型、Schema、features、源码漂移和中断。

此检查不是完整 Rust API 提取或自动语义兼容性证明；仍须结合独立消费方、Schema 往返、FFI 生命周期测试与[维护者评审表](../v0.1-contract-review.md)。新增 API/字段和修正说明可能需要更新基线，应在同一提交说明依据、迁移及版本选择。

依据：[Rust 类型布局](https://doc.rust-lang.org/reference/type-layout.html)、[Cargo 兼容性指南](https://doc.rust-lang.org/cargo/reference/semver.html)、[JSON Schema 2020-12 Validation](https://json-schema.org/draft/2020-12/json-schema-validation)。布局相等不证明全部调用行为正确；Rust 的 `non_exhaustive` 不会使旧 JSON 解码器接受未知枚举值。

回退：可以移除开发探针、基线检查和 CI 步骤；保留共享库生命周期说明。生产采集代码与 ABI 不依赖这些工具，无第三方依赖或 feature 变更。
