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

报告只含版本、SPDX、文件名、大小及哈希，不记录本机 Cargo 缓存路径。扫描范围与现有打包器共用依赖闭包和文件发现规则：保守包含 build 依赖，排除 dev 依赖。只读取包根目录原有材料，不联网补文件，不改动缓存。失败或中断作废旧报告；提交、工作区和锁文件须在前后保持一致。

## macOS 当前材料

2026-10-30 复查：上游 [issue 826](https://github.com/madsmtm/objc2/issues/826)已记录添加仓库级许可全文，但关于较旧发布版完整版权材料的后续讨论仍未给出完整答案；[issue 23](https://github.com/madsmtm/objc2/issues/23)的重新许可提案仍为另一事项。不能把 issue 关闭、SPDX 声明或许可摘要链接等同于本项目已经收齐所需文件，也不据此断言现有许可证无效。

原有六个 objc2 系列依赖的版本与源码调查见[历史记录](evidence/macos-license-research-2026-10-26.json)。本轮实际扫描结果另行归档，历史记录不覆盖。没有联系上游、改许可证、升级依赖或打开 macOS 二进制分发入口。
