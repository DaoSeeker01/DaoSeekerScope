# ADR 0033：Windows FFI SDK 候选包

日期：2026-10-26。状态：实现，本机原生验收后归档；新增 CI 尚未执行。

## 本轮选择

原计划先补 macOS CLI 制品。实际锁定闭包中的 objc2、objc2-encode、objc2-foundation、objc2-core-foundation、objc2-io-kit 和 objc2-metal 缺少独立许可文件。按 `.cargo_vcs_info.json` 的三个精确提交读取的上游根 LICENSE.md 是同一 1339 字节说明文件，不含完整 MIT grant 或显式版权行；它链接标准许可证并说明 Apple SDK 派生事项。不能把这个文件命名为完整 MIT 正文并宣称已补齐。

[调查索引](../evidence/macos-license-research-2026-10-26.json)记录六包版本、SPDX、源码位置、提交和上游文件哈希。[原文](https://github.com/madsmtm/objc2/blob/d7d2fa23ceaa5e6096c923b081040e5d81b3b9df/LICENSE.md)与[上游跟踪事项](https://github.com/madsmtm/objc2/issues/23)是材料依据；事项开放不等于现有 MIT 声明无效，也不是“这些库不能使用”的法律结论。本轮不推断版权所有者、不联系上游、不放宽完整许可材料的打包门禁。macOS 原生库既有 CI 结论不变，分发候选包继续待补材料/评审。

先交付能在维护者机器验证的 Windows x64 MSVC FFI SDK 候选包。继续复用同一个有界 ZIP 校验器和目标依赖许可闭包，不复制另一套采集、FFI 或序列化实现。

## SDK 内容与格式

`python scripts/cli_bundle.py --product ffi_sdk` 在新 target-dir 原生 release 构建 FFI crate，读取这一次构建的 DLL 和导入库。归档包含 `bin/daoseeker_scope_ffi.dll`、`lib/daoseeker_scope_ffi.dll.lib`、`bindings/daoseeker_scope.h`、原始 C/Python 示例、硬件 Schema、说明、项目和上游/Rust 许可文件。C 示例保留原来的相对 include 路径，头文件与维护来源逐字节相同。

独立 `bundle_format=3`、`product=ffi_sdk`，目前只允许 Windows x64 MSVC。CLI 包仍为 Windows v1、Linux v2；各验证入口在执行前拒绝错误产品。硬件快照 Schema 1、C ABI 1、Rust 公共 API、依赖/features/锁、MIT 均不变。包的 v3 不表示 C ABI v3。

沿用外部 SHA256SUMS、逐文件 manifest、源码/dirty/rustc/锁哈希、512 项/单项 64 MiB/总量 128 MiB 等约束。缺 DLL、导入库、头文件、示例或 Schema 直接失败；完整许可收集规则不变。尚无签名或完整许可合规结论；不上传二进制或正式分发。

## 跨语言与回滚验收

演练只写 target 下全新临时目录。先验证整个包再安装两份相同 SDK；激活前复核全部载荷字节和普通文件类型。每个激活阶段使用包内 C 源码、头文件和导入库，以 `/W4 /WX /std:c11` 编译 C 消费者；消费者输出真实 JSON，按包内 Schema 检查最低读取与默认隐私。DLL 与消费者同在 bin，Python 使用绝对 DLL 路径，不修改全局 PATH。

三个阶段各运行一次包内 Python ctypes 示例，每次 100 个真实 collect/free、空释放和 stale copy 拒绝。共 3 次 C 编译、3 次 C 执行、3 次 Python 执行，即 9 个子进程和 300 次 Python collect/free；父进程不加载 DLL，避免安装目录被加载句柄锁住。子进程超时 90 秒、输出限长，报告不保存原始快照。

损坏更新在创建安装目录前被拒绝，保留原选择，再回到第一槽位。只有同候选目录切换的证据，不是旧正式版升级/ABI 回滚、干净 Windows 镜像依赖或跨版本兼容证明。FFI 内存安全仍以原有 Rust/Miri/ASan 和 C/Python 契约测试共同约束，不将 300 次调用当作完整泄漏证明。

回退可移除 SDK 产品分支、SDK 演练脚本与 CI 步骤，保留既有 CLI 包。没有新增运行时 API 或平台声明。
