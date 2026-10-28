# ADR 0037：在较低版本 Linux 用户空间验证候选包

日期：2026-10-28。状态：实现，等待本轮原生 CI；结果见[验证记录](../linux-runtime-container-validation.md)。

## 要解决的问题

上一轮候选声明最高强制数值要求 `GLIBC_2.34`，只在构建 runner 上运行过。版本表不能替代旧环境实际加载与采集，也不建立最低发行版或内核承诺。

## 选择

继续使用现有 Linux 原生构建的 CLI ZIP 与 FFI SDK ZIP。校验 SHA256SUMS、manifest、目标、产品和干净源码身份后，解包到临时目录。C 消费者在构建宿主使用包内头文件及共享库编译一次；三个二进制记录哈希，后续容器只复制并运行它们，不重建 Rust 库、CLI 或 C 消费者。

采用两份 [Docker Official Python 镜像](https://hub.docker.com/_/python)的 `linux/amd64` manifest 摘要：

- Bookworm：Python 3.13.13，预期 Debian 12 / glibc 2.36，验证 CLI 版本和 JSON、C 采集及 Python 100 次 collect/free。
- Bullseye：Python 3.13.5，预期 Debian 11 / glibc 2.31，专门验证不兼容时的加载拒绝，不作为部署镜像推荐。

完整 manifest/config/layer 摘要与解析来源见[镜像记录](../evidence/linux-runtime-images-2026-10-28.json)。摘要固定输入内容，不能替代运行证据；本机只查询 registry，未启动镜像。镜像 ID、OS、架构、Python、glibc 和发行版须在验收中复核，不能根据标签推断。

## 容器边界

要求既有本地 Unix Docker daemon，不启动服务、不改变 context。使用 [Docker 运行约束](https://docs.docker.com/engine/containers/run/)：UID/GID 65534、根文件系统只读、无网络、丢弃全部 capabilities、禁止新增权限；内存上限 256 MiB，内存与 swap 总额也为 256 MiB，另有 32 PIDs、1 CPU 配额和每进程 64 个文件描述符的限制。输入挂载只读，唯一可写目录是 64 MiB 的 `/work` tmpfs，用于在容器内复制安装候选并执行。启动前检查 daemon 配置，实际用户身份在容器内复核。

容器内的独立 Python runner 只使用标准库。安装后逐文件检查 payload 哈希、大小与权限，再检查三个二进制与宿主哈希一致。C 消费者用 `$ORIGIN/../lib` 加载包内 SDK。没有 LD_* 或 GLIBC_TUNABLES 覆盖；不安装包、不使用编译器、不挂载宿主系统库。

正面环境必须退出成功；宿主用项目 Schema 和最低读取/默认隐私契约检查 CLI/C 快照，并验证包内 Python 示例完成 100 次 collect/free、空释放和 stale copy 拒绝。公开报告只保留判断、计数和哈希，不存原始快照或 loader 完整路径。

负面环境须分别看到 CLI、C 和 ctypes 的缺失 GLIBC 版本诊断；缺失版本必须高于实际环境，且来自对应二进制声明的强制要求。信号退出、文件缺失、权限错误或任意非零退出均不能冒充预期拒绝。该环境没有执行采集，其“通过”只表示预期的不兼容拒绝被正确识别。

每个候选子进程最多 60 秒、容器附着最多 300 秒、镜像拉取最多 180 秒。只清理本次唯一命名的容器，超时也必须尝试移除；移除失败不接受为成功。失败或中断作废旧成功报告。CI 复用已有 Linux 候选构建并保留单独报告，不增加新平台或二进制发布。

## 验证与兼容性

Windows 本机只验证配置、报告和异常路径；真正的用户空间结果由 Linux 原生 CI 提供。容器共享宿主内核，不能作为实体 Debian 设备、最低内核、所有发行版或完整硬件覆盖证据。更低版本中间区间仍须逐项验证，不能把首个通过值当作精确最低值。

公共 Rust API、C ABI 1、硬件 JSON Schema 1、ZIP 格式、crate、feature、锁文件、依赖和 MIT 不变。回退可移除这个独立验收入口、CI 步骤和报告，保留既有构建、安装回滚及 ELF/PE 门禁。
