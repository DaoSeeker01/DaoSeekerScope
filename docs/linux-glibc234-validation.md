# glibc 2.34 候选运行验证

本轮补测产物声明的 `GLIBC_2.34` 要求。现有 Debian 12 / glibc 2.36 成功和 Debian 11 / glibc 2.31 拒绝的历史记录仍保留在[较低版本环境验证](linux-runtime-container-validation.md)。

## 实施与复现

新增固定摘要的 UBI 9 / Python 3.12 场景；选择与边界见 [ADR 0043](adr/0043-linux-glibc234-runtime.md)。在已有本地 Docker 的 Linux x64 主机上，从干净提交运行：

```sh
cli=$(python scripts/cli_bundle.py)
sdk=$(python scripts/cli_bundle.py --product ffi_sdk)
python scripts/linux_runtime_container_smoke.py "$cli" "$sdk"
```

不安装 Docker、不更改 context、PATH 或系统库。测试拉取的镜像不随项目分发。报告为 `target/linux-runtime-container-evidence.json`；当前私有报告格式为 2，硬件 Schema 和 ABI 仍为 1。

三个场景使用同一组已构建的 CLI、共享库和 C 消费者；输入和完整安装文件均检查哈希，容器内不重编译。显式 Python 入口绕过镜像初始化脚本，实际 Docker 配置与运行身份须相符；原有断网、非 root、只读根目录、资源上限和退出清理保留。

## 当前状态

Windows 本机执行配置、解析和负面测试，不运行 Linux 容器。UBI 的发行版、glibc、Python 补丁版本与候选实际运行结果，待冻结提交后的原生 Linux CI 验收记录补充。镜像 registry 元数据不是运行证据。

无 Rust 公共 API、生产行为、crate/features、依赖/锁、MIT、ABI 1 或硬件 Schema 1 变更，没有正式发布。

## 结论边界

这项测试只验证指定二进制在固定用户空间中的加载与采集。容器共享宿主 CPU/内核；它不验证实体 RHEL 设备、最低内核、所有 glibc 2.34 安装或其他发行版，也不把 UBI 9 自身的 CPU 要求当作本库最低指令集。
