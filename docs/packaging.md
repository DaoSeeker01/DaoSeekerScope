# 打包与安装验证

## 验证入口

需要 Python 3.12+（使用 tar 归档安全过滤 API）。在干净的仓库目录运行：

```sh
python scripts/check_packages.py
```

依赖已缓存时可加 `--offline`；验证未提交的修改时可加 `--allow-dirty`，报告会记录工作区状态。结果写入 `target/package-evidence.json`。CI 在三个原生桌面平台运行，并保存报告 14 天。

脚本创建 8 个实际 `.crate` 文件，检查每个包的 MIT 声明和许可证全文，以及 FFI 包的 C 头文件。随后解包到独立临时目录，运行全部 feature 的 Rust 测试及 doctest，安装 CLI 到该目录，检查 `--version` 和 JSON 输出。源仓库和独立目录的第三方依赖锁文件均不得变化。所有构建文件和临时安装位置位于 `target/`，不修改系统 PATH 或全局 CLI 安装。

独立测试目录通过本地 Cargo patch 连接解包后的同项目依赖。这验证实际包内文件和消费者构建，不验证真实 registry 下载、依赖发布顺序或 crates.io 发布权限。

## 许可证与头文件

根目录 `LICENSE-MIT` 和 `bindings/daoseeker_scope.h` 是维护来源。8 个 crate 各包含一份许可证，FFI crate 另包含 `include/daoseeker_scope.h`；项目检查要求副本与维护来源逐字节一致。修改来源后应同步副本。

原先 `cargo package --list` 显示所有 crate 都缺少许可证全文，FFI 包也缺少头文件。当前打包门禁检查实际归档，防止这些遗漏再次出现。第三方依赖保留原许可证；发行二进制仍需另行准备相应版权与许可声明。

## 验证边界

本机 Cargo 1.96.0 的 `cargo package --workspace --locked --offline` 在验证第二个包时失败，报 `no hash listed for daoseeker-scope-core v0.1.0` 并标记为 Cargo 内部错误。移除 `--locked` 后也出现相同错误，源锁文件没有变化。失败记录不算完整原生 package 验证通过。

脚本用 `--no-verify` 生成归档，再执行上述独立测试及安装；它保留 `--locked`，并记录使用本地 patch 的边界。这是额外验证路径，不代替 Cargo 原生 package 验证。正式发布前仍需解决或重新验证该问题，再执行真实 registry 安装、制品校验和回滚演练。当前没有上传 crate 或发布 release。
