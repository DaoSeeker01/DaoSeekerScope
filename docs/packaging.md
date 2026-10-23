# 打包与安装验证

## 验证入口

需要 Python 3.12+（使用 tar 归档安全过滤 API）。在干净的仓库目录运行：

```sh
python scripts/check_packages.py
```

依赖已缓存时可加 `--offline`；验证未提交的修改时可加 `--allow-dirty`，报告会记录工作区状态。结果写入 `target/package-evidence.json`。CI 在三个原生桌面平台运行，并保存报告 14 天。

脚本在全新临时输出目录执行完整 `cargo package --locked --workspace --all-features`，创建并验证 8 个实际 `.crate` 文件，再检查每个包的 MIT 声明和许可证全文，以及 FFI 包的 C 头文件。归档保存在 `target/package/`。随后解包到独立临时目录，运行全部 feature 的 Rust 测试及 doctest，安装 CLI 到该目录，检查 `--version` 和 JSON 输出。源仓库和独立目录的第三方依赖锁文件均不得变化。所有构建文件和临时安装位置位于 `target/`，不修改系统 PATH 或全局 CLI 安装。

独立测试目录通过本地 Cargo patch 连接解包后的同项目依赖。这验证实际包内文件和消费者构建，不验证真实 registry 下载、依赖发布顺序或 crates.io 发布权限。

## 许可证与头文件

根目录 `LICENSE-MIT` 和 `bindings/daoseeker_scope.h` 是维护来源。8 个 crate 各包含一份许可证，FFI crate 另包含 `include/daoseeker_scope.h`；项目检查要求副本与维护来源逐字节一致。修改来源后应同步副本。

原先 `cargo package --list` 显示所有 crate 都缺少许可证全文，FFI 包也缺少头文件。当前打包门禁检查实际归档，防止这些遗漏再次出现。第三方依赖保留原许可证；发行二进制仍需另行准备相应版权与许可声明。

## 验证边界

2026-10-22 macOS uptime 实现 `bfd28d5` 在干净 Windows 工作区完成八包实际归档、原生 Cargo 验证、提取后独立 workspace 240 项测试与 CLI 安装；[报告](evidence/macos-uptime-packages-windows-bfd28d5.json)保留包哈希和未发布的本地 patch 边界。2026-10-23 源码 8500cc8 的三平台 CI 39878588965 进一步通过每平台八包验证与独立安装：Windows 240、Linux 233、macOS ARM64 238 项测试含 doctest；见[完整索引](evidence/macos-uptime-ci-39878588965.json)。未发布 registry 或 release。

2026-10-22 Windows uptime 实现 `7b79a17` 在干净工作区完成八个实际归档、原生 Cargo 验证、提取后独立 workspace 232 项测试与 CLI 安装；[报告](evidence/windows-uptime-packages-7b79a17.json)记录每包 SHA-256、锁不变及未验证 registry 的边界。随后源码 8fce189 的三平台 CI 39755735940 也通过各八包/独立安装验收；Windows 232、Linux 225、macOS ARM64 229 项独立测试含 doctest，见[本轮 CI 索引](evidence/windows-uptime-ci-39755735940.json)。未执行 registry 发布安装或 release 制品分发。

本机 Cargo 1.96.0 在原输出目录执行 `cargo package --workspace --locked --offline` 时，在验证第二个包时失败，报 `no hash listed for daoseeker-scope-core v0.1.0` 并标记为 Cargo 内部错误。移除 `--locked` 后也出现相同错误，源锁文件没有变化。使用全新 `--target-dir`、保留 `--locked --offline --all-features` 后，8 个包的完整 Cargo 验证全部通过；再次使用该目录也通过。因此确切根因尚未确定，不能将目录复用本身或平台 backend 判为故障原因。初次失败与后续成功分别保留证据。

脚本每次使用新输出目录，保留原生 Cargo 验证与锁文件约束；额外的独立测试仍记录使用本地 patch 的边界。正式发布前还需真实 registry 安装、制品校验和回滚演练；不要把本地临时 registry 验证当作 crates.io 下载验证。当前没有上传 crate 或发布 release。
