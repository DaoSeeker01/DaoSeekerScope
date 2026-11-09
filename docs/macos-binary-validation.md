# macOS 二进制元数据验证

2026-11-09 在 Intel macOS 15.7.9（build 24G830）验证源码构建的 CLI 和动态库。两者的 x86_64 架构与 Mach-O 元数据均与 Apple 工具一致，并通过同镜像的原生 CLI、C 和 Python 检查。两个文件声明的部署目标为 10.12.0，链接 SDK 为 15.5.0。实际运行证据对应 15.7.9。[Intel 验收报告](evidence/macos-intel-ci-42544368733.json)

检查源码构建的 `dscope` 和 `libdaoseeker_scope_ffi.dylib`，将自有解析结果与 `xcrun otool -l`、`xcrun lipo -archs` 对照。它不打包、不安装、不执行被检查文件，也不解除许可材料门槛。

在 macOS 干净提交中，安装项目 Python 开发依赖并运行：

```sh
cargo build --locked -p daoseeker-scope-cli -p daoseeker-scope-ffi
python scripts/macos_macho_smoke.py
```

报告默认为 `target/macos-macho-evidence.json`。源码和两个文件的哈希在整个对照结束前保持一致；失败或中断先作废旧成功报告。保留系统库名称，其他路径只记录分类，避免输出构建目录。

当前解析范围为小端、单架构 64 位 Mach-O，支持普通 arm64 与 x86_64 的 executable/dylib 元数据；不支持 universal/fat、32 位、其他子架构或非 macOS 平台。文件最多 64 MiB，命令区最多 1 MiB/4096 条，字符串最多 4096 字节。验证命令长度、对齐与边界，解析普通/弱/重导出/向上依赖、库自身 ID、rpath 和新旧系统版本声明；拒绝内嵌 dyld 环境命令。未知命令只检查其边界，不解释内容。

依据 Apple 公开的 [Mach-O loader.h](https://github.com/apple-oss-distributions/cctools/blob/main/include/mach-o/loader.h) 中的格式定义，代码独立实现，不复制系统解析器。

程序头里声明的最低系统版本不等于已经实测支持的最低版本。检查不验证完整 segment/linkedit、全部导入符号、间接或运行时依赖、签名、notarization 或沙盒加载；不是加载器或恶意文件执行沙箱。只有原生 runner 上的对照通过后，才能记录对应构建结果，不能用合成字节测试替代。

本机 Windows 已通过 8 项新增测试，含 512 次固定种子的有界字节变异、工具文本、输入漂移和失败/中断报告验证；Python 全套 328 项中 322 通过、6 跳过。Ruff、79 文件的 Windows/Linux/macOS 三种 mypy 目标与 actionlint 通过。准备阶段两处测试变量类型复用已修复。

源码 `d76e8a9` 的 [CI 41368963038](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/41368963038)中，macOS ARM64 桌面任务及新对照步骤通过；[原始报告](evidence/macos-macho-41368963038.json)绑定该提交和两个产物哈希。CLI 与动态库分别记录 8 个依赖、没有 rpath；架构、依赖和版本声明均与 Apple 工具一致。两者均声明最低 macOS 11.0.0、链接 SDK 26.5.0；这是头部数据，不是 macOS 11 上的运行证明。本轮没有执行这些镜像或批准分发。完整 CI 的其他任务在归档时仍在运行。

Rust 公共 API、依赖、锁文件、MIT、C ABI 1 和硬件 Schema 1 不变。macOS CLI/SDK 打包目标仍未开放，六项许可材料缺口继续保留。
