# 分发许可材料预检

预检回答“打包工具能否找到所需文件”，不替代许可或完整版权归属评审。macOS 预编译包目前仍未开放；缺少材料不会通过复制通用 MIT 文本、猜测版权人或忽略依赖来解决。

## 运行

在干净提交上运行；默认使用本机 Rust host，也可以只查询其他目标的依赖：

```sh
python scripts/notice_audit.py --offline
python scripts/notice_audit.py --offline --target aarch64-apple-darwin --output target/macos-notices.json
python scripts/notice_audit.py --offline --verify-archives --target aarch64-apple-darwin --output target/macos-notice-sources.json
```

离线模式要求 Cargo 缓存已有相关包；缺少缓存时失败，不冒充已完成扫描。命令不会编译或运行目标二进制，也不会上传或发布软件。跨目标查询不表示已验证该平台。

报告默认写入 `target/notice-audit-evidence.json`。`overall=completed` 和退出码 0 只表示扫描完成；必须另外读取 CLI/FFI SDK 各自的 `packager_notice_gate`：

- `blocked`：至少一个包缺少 SPDX、根许可文件、有效内容或安全文件名。`packages[].errors` 一次列出全部缺口。
- `satisfied`：满足当前打包器的文件检查，不保证许可全文、版权声明或分发条件完整。`legal_review` 仍为 `not_performed`。

报告默认包含版本、SPDX、文件名、大小及哈希。扫描范围与打包器共用依赖闭包和根文件发现规则，保守包含 build 依赖，排除 dev 依赖。完整打包另检查 Rust 工具链材料。预检只读现有材料，失败或中断作废旧报告，提交、工作区和锁文件须在前后保持一致。

`--verify-archives` 为缺少或无法读取材料的包增加 `archive_provenance`。工具先将本机缓存的 `.crate` 与 Cargo.lock 校验和比对，再核对归档内包名、版本和 SPDX，并读取发布提交、源码子目录与根许可文件。报告记录原始材料的哈希及精确源码链接，省去手工查找对应发布版本的步骤。

该字段的 `verified` 表示归档来源核验通过，`invalid` 表示校验和或内容不符，`unavailable` 表示缓存、锁定校验和或缓存布局不可用。单包异常单独记录，其他包继续检查。材料是否齐全仍看 `packager_notice_gate` 和 `packages[].errors`。

归档读取上限为 64 MiB，解压上限为 128 MiB，最多 8192 个条目，选中的单份文本最多 1 MiB。工具拒绝链接、重复条目、跨目录路径和异常版本元数据，只在内存中检查归档。报告省略本机缓存路径。未使用 `--offline` 时，Cargo 可能下载依赖。

许可候选文件必须是普通文件。符号链接、Windows reparse 项和 FIFO 等特殊文件会阻止打包，即使同一包另有有效 LICENSE；普通许可目录仍不递归读取。文件被替换或读取失败时不收录内容，预检记录脱敏错误并继续检查其他依赖。具体规则、测试和边界见[许可输入验证](notice-input-validation.md)。

同一个依赖中出现仅大小写不同的许可文件时，预检和打包会在读取内容前返回 `duplicate_notice_name`。预检继续检查其他依赖。

## macOS 当前材料

2026-11-09 核对六个锁定 `.crate` 的 SHA-256、发布提交和归档内容。六个归档均缺少根许可材料，三个发布提交的根 `LICENSE.md` 指向同一份许可说明。上游补入完整许可文本的提交与 `objc2 0.6.5` 的发布提交分属不同分支。已定位早期 `rust-objc` 的 MIT 文本，相关历史材料的适用性和完整性仍待评审。[归档与来源记录](evidence/notice-provenance-93b01a2-2026-11-09.json) [上游许可讨论](https://github.com/madsmtm/objc2/issues/826)

2026-11-02 复核：提交 `d76e8a9` 的原生 macOS CI 扫描与本机跨目标扫描仍为 CLI/SDK 各 20 个依赖包、6 项材料阻塞。新增的 [Mach-O 原生对照](macos-binary-validation.md)已通过，但没有改变文件门槛或开放打包；元数据检查不代替材料补齐。

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
