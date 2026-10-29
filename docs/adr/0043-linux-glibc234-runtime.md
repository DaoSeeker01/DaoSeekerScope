# 0043 在 glibc 2.34 用户空间运行既有候选

日期：2026-10-29。状态：实施决定；运行结果见[验收记录](../linux-glibc234-validation.md)。

## 目的与选择

既有候选声明最高强制数值要求 `GLIBC_2.34`，但先前只实测了 glibc 2.36 成功和 2.31 拒绝。增加一份固定摘要的 Red Hat UBI 9 / Python 3.12 镜像，在相同内核与 CPU 上运行相同的 CLI、共享库和 C 消费者，不在容器内重编译。

UBI 9 提供 glibc 2.34 系列。选择自带 Python 3.12 的镜像，使标准库探针可以直接运行，无需在测试容器内联网安装包。镜像仅用于验证，不随候选分发，也不是对部署环境的推荐。项目 MIT 与第三方锁不变；测试镜像遵循其自身许可。原始 manifest/config 摘要、架构及配置来源见[镜像记录](../evidence/linux-runtime-ubi9-image-2026-10-29.json)。这些元数据不作为运行成功证据。

依据：[RHEL 9.2 发行说明](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/9.2_release_notes/new-features)、[官方 Python 镜像构建文件](https://github.com/sclorg/s2i-python-container/blob/master/3.12/Dockerfile.rhel9)、[UBI 说明](https://access.redhat.com/articles/4238681)。UBI 9 的 [x86-64-v2 要求](https://access.redhat.com/solutions/7057314)是该测试环境的限制，不能据此宣称本库的最低 CPU 指令集。

## 实施边界

沿用 [ADR 0037](0037-linux-candidate-older-userlands.md) 的校验、完整复制、哈希、资源与清理规则。三个场景共用同一组二进制。Debian 12/11 的精确 Python 与发行版本检查保留；UBI 的 manifest 与 config 摘要固定内容，运行时核对 RHEL 9、glibc 2.34 和 Python 3.12，并记录完整发行版与 Python 补丁版本，不把预期值写成实测值。

所有场景显式指定 Python 入口与 `/work` 工作目录，核验 Docker 的实际配置。这样不依赖镜像自带的应用初始化脚本，也不允许它尝试修改只读根目录。UBI 使用 `/usr/bin/python3.12`；原有 Python 镜像使用 `python`。`os-release` 只按有界字面字段读取 ID/VERSION_ID，不执行 shell；重复、缺失和损坏字段拒绝。

UBI 镜像压缩层合计约 380 MiB，其拉取等待上限为 300 秒；其他镜像保留 180 秒。容器内仍断网，UID/GID 65534、只读根目录、64 MiB 工作区及 256 MiB 内存上限均不变。容器结果私有格式从 1 增至 2，保留 Debian 旧字段并新增实际 distribution；不改变硬件 Schema 1 或 C ABI 1。

## 验证与回退

正面场景必须通过 CLI 版本/JSON、C 采集、Python 100 次 collect/free、Schema 与默认隐私检查；负面场景仍须识别实际缺失 GLIBC 诊断，不能把任意失败当成功。镜像入口、实际身份、解析损坏、旧场景及清理均有回归。

即使 2.34 成功，也只证明当前构建产物在这份固定用户空间和宿主上可运行。未建立最低内核、所有 glibc 2.34 系统、所有发行版或实体设备保证。生产代码不依赖此验证工具；回退可移除 UBI profile 和新增身份字段，保留旧场景、显式入口与资源限制。
