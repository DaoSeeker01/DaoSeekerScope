# ADR 0032：Linux CLI 候选包与显式文件权限

日期：2026-10-26。状态：已实现，干净提交 cdd8760 的 Windows 本机门禁、格式/负向测试和 Windows v1 回归已通过，见[记录](../linux-cli-bundle-validation.md)；Linux 原生构建、链接、六进程与 POSIX 权限测试已通过 Ubuntu 24.04 的 CI 40245533279。实体 Linux 设备验证仍延期。

## 范围

在 [Windows 候选包](0031-windows-cli-candidate.md) 的共享工具中增加 `x86_64-unknown-linux-gnu`，不建立重复的打包器。不增加 crate、第三方依赖或 features，不改变 Cargo.lock、Rust API、MIT、C ABI 1 或硬件快照 Schema 1。macOS、musl、其他架构、FFI 动态库包和正式分发仍独立验收。

构建从 rustc 的唯一 host 行选择平台，并同时核对实际 OS 和 OS 报告的 x64 架构。Windows/Linux 只允许匹配的原生 host；不提供用 Windows 工具链生成“已验收 Linux 包”的捷径。继续使用全新 target-dir、release、锁定依赖、目标过滤的 CLI 依赖/许可闭包及 Rust 工具链许可文件。缺少许可仍失败。

## 归档格式

继续采用 ZIP，复用已验证的限额、路径、重复名、特殊文件、SHA-256 与 manifest 检查。Windows 保持 bundle_format 1，文件内容契约和 `bin/dscope.exe` 不变；Linux 使用 **bundle_format 2** 和 `bin/dscope`，明确逐文件 `mode`：CLI 为 `0755`，其他普通载荷和 manifest 为 `0644`。

Linux v2 同时要求 ZIP Unix 标记、普通文件类型位以及完全匹配的权限位；manifest 的 mode 必须为整数，不接受 bool。拒绝 setuid/setgid、额外可写权限、丢失执行位、DOS 标记冒充 Unix、没有普通文件类型、缺失 mode、Linux 降级为 v1。单独更换外部校验和也不能绕过这些格式约束。硬件快照 Schema 1 与此候选包格式版本相互独立。

不依赖 ZIP 解包工具自动保留权限。验证全部字节与元数据后，只向全新隔离目录写文件，并显式 chmod；激活前重新核对普通文件类型、内容和最终权限。原选择通过同目录原子替换保持。Unix umask 不作为执行权限来源；测试覆盖常见的限制性 umask 077，不承诺支持任意特殊挂载或 ACL 策略。

## 执行与兼容边界

六进程演练沿用初次安装、第二槽位切换和回滚各一次版本/JSON 检查，包括 Schema、最低读取和默认隐私；损坏 ZIP 在安装目录创建前被拒绝。执行前再次核对目标与实际主机，不运行合成字节。两槽位仍为同一候选，旧正式版升级和 ABI 回滚没有证据。

GNU target 名称不等于所有 Linux 发行版都可运行。只记录实际原生 runner 上的构建与执行，不从构建主机 glibc 版本推导二进制的最小 glibc、内核或发行版基线，也不声称静态链接、musl 或跨发行版兼容。发布前需另测最低运行环境、动态链接器/系统库前提、签名和许可覆盖。

本机 WSL 当前不可运行且 Docker CLI 不可用，不调整机器服务或安装发行版。Windows 可验证格式、模拟篡改和旧 Windows 真实包读取；两项真实 POSIX mode/umask 测试在 Windows 明确跳过，由 Linux/macOS 的 POSIX 文件系统测试和 Linux 原生候选步骤分别提供证据，不能互相冒充。新增 CI 尚未执行时不写为已支持 Linux 二进制分发。

回滚可移除 Linux target、v2 模式处理及 Linux CI 步骤，保留 Windows v1；通用库 API 不受影响。SHA-256 仍只检验完整性，不认证发布者。没有上传候选二进制、registry 或 GitHub Release 发布。
