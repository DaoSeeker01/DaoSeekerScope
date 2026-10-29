# 分发许可材料预检

预检回答“打包工具能否找到所需文件”，不替代许可或完整版权归属评审。macOS 预编译包目前仍未开放；缺少材料不会通过复制通用 MIT 文本、猜测版权人或忽略依赖来解决。

## 运行

在干净提交上运行；默认使用本机 Rust host，也可以只查询其他目标的依赖：

```sh
python scripts/notice_audit.py --offline
python scripts/notice_audit.py --offline --target aarch64-apple-darwin --output target/macos-notices.json
```

离线模式要求 Cargo 缓存已有相关包；缺少缓存时失败，不冒充已完成扫描。命令不会编译或运行目标二进制，也不会上传或发布软件。跨目标查询不表示已验证该平台。

报告默认写入 `target/notice-audit-evidence.json`。`overall=completed` 和退出码 0 只表示扫描完成；必须另外读取 CLI/FFI SDK 各自的 `packager_notice_gate`：

- `blocked`：至少一个包缺少 SPDX、根许可文件、有效内容或安全文件名。`packages[].errors` 一次列出全部缺口。
- `satisfied`：满足当前打包器的文件检查，不保证许可全文、版权声明或分发条件完整。`legal_review` 仍为 `not_performed`。

报告只含版本、SPDX、文件名、大小及哈希，不记录本机 Cargo 缓存路径。扫描范围与现有打包器共用依赖闭包和文件发现规则：保守包含 build 依赖，排除 dev 依赖。只检查第三方 crate 根目录材料，不包含 Rust 工具链或系统 SDK 的许可；完整打包还需要其他检查。只读取包根目录原有材料，不从其他来源补写许可文件；未使用 `--offline` 时，Cargo 本身仍可能下载依赖。预检不会改写已缓存的文件。失败或中断作废旧报告；提交、工作区和锁文件须在前后保持一致。

## macOS 当前材料

2026-10-30 复查：上游 [issue 826](https://github.com/madsmtm/objc2/issues/826)已记录添加仓库级许可全文，但关于较旧发布版完整版权材料的后续讨论仍未给出完整答案；[issue 23](https://github.com/madsmtm/objc2/issues/23)的重新许可提案仍为另一事项。不能把 issue 关闭、SPDX 声明或许可摘要链接等同于本项目已经收齐所需文件，也不据此断言现有许可证无效。

原有六个 objc2 系列依赖的版本与源码调查见[历史记录](evidence/macos-license-research-2026-10-26.json)。冻结提交 `5124d16` 的实际扫描结果已归档，历史记录不覆盖。没有联系上游、改许可证、升级依赖或打开 macOS 二进制分发入口。

## 本轮验收

[CI 40973873976](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40973873976)八项任务成功；[证据索引](evidence/notice-audit-ci-40973873976.json)保留三份原生 runner 扫描与两份 Windows 本机查询报告，以及来源、文件哈希和限制。

| 查询环境 | CLI 第三方包数 / 阻塞数 | SDK 第三方包数 / 阻塞数 | 含义 |
|---|---:|---:|---|
| Windows 本机与 Windows CI | 28 / 0 | 28 / 0 | 满足现有 crate 根文件门槛，未执行法律评审 |
| Linux CI | 13 / 0 | 13 / 0 | 满足相同文件门槛 |
| macOS CI 与 Windows 跨目标查询 | 20 / 6 | 20 / 6 | 扫描完成；分发材料仍被阻止 |

六个缺口为 `objc2 0.6.5`、`objc2-encode 4.1.0` 及 `objc2-foundation`、`objc2-core-foundation`、`objc2-io-kit`、`objc2-metal` 的 `0.3.2`。报告列出了全部缺口，未复制替代文本、推断版权人或开放 macOS 打包。

本机 Python 282 项中 277 通过、5 跳过，新增许可预检回归 8 项；Ruff、mypy（69 文件）、项目与 actionlint 检查通过。首轮新 fixture 有一处类型标注遗漏，已在提交前修正。CI 的独立八包 Rust 测试分别为 Windows 269、Linux 261、macOS 266；Python 分别为 277/5、282/0、281/1（通过/跳过）。三平台 crate 归档、Windows/Linux 候选包、Schema、冻结契约、短 fuzz、Miri/ASan 与供应链检查通过。没有在本机重跑 Rust 命令或执行 macOS 二进制。

CI 成功表示本轮代码与扫描过程完成验收，不能作为 macOS 分发许可批准。实体设备、最低 OS 范围、长期验证和正式发布仍待完成。
