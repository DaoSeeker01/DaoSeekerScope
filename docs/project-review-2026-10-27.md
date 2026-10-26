# 项目审计与修复 · 2026-10-27

基线提交：`a038930`。目标是保留既有能力和有效证据，修复当前可复现问题，补齐长期维护与 v0.1 交付所需内容。当前不是正式发布验收。

## 审计范围与方法

逐文件清点并读取基线的 838 个跟踪文件，记录路径、大小与 SHA-256；其中 Rust 源码 72 个、18,366 行，Python 55 个、11,356 行，Markdown 85 个。历史 JSON 证据按结构、来源和索引检查，不重写历史结果。人工检查重点为公共模型、采集组合、FFI 所有权、平台采集边界、CLI、打包及 CI；自动读取和静态扫描不等于证明每一行没有缺陷。

继续保留八个 crate、同步 backend、静态缓存、调用方等待边界、字段隐私与版本化 JSON。未发现需要大规模重构的依据，也没有新增运行时依赖、移动平台或 MCU 支持声明。

## 确认的问题与处理

| ID | 严重性 | 问题与证据 | 本轮处理 |
|---|---|---|---|
| A01 | 高 | 打包脚本仅成功时写报告；模拟第一次命令失败后，旧 `overall=passed` 仍存在，已复现 | 开始时作废旧结果，异常写 failed，中断保留 incomplete；增加回归 |
| A02 | 中 | 打包子进程未设置超时；安装后的 CLI 仅检查 Schema 版本数字 | 命令限时 900 秒，增加 CLI 版本、完整 Schema、最低读取和默认隐私检查 |
| A03 | 中 | 核心和 JSON 允许零显示像素，但平台/CLI 将零尺寸视为无效 | 按轴隔离为 InvalidData；JSON 与 Schema 同步拒绝零尺寸，不改布局或主版本 |
| A04 | 中 | 缺少安全政策、社区规范、Issue/PR 模板和面向用户的更新日志 | 补充根目录社区文件、GitHub 表单和 PR 模板 |
| A05 | 中 | 文档中的 fuzz 数量过期；版本和 YAML 配置缺少自动一致性检查 | 移除易失效的重复数量，集中开发依赖，检查内部版本/更新日志和 YAML 重复键 |
| A06 | 中 | CI 未统一限制运行时间，同分支重复运行可能浪费资源 | 增加 job 超时与同分支并发控制；保留只读权限和固定 Action SHA |
| A07 | 低 | CLI 的缺失原因仍显示 `Some(...)`，敏感选项错误提示过于笼统；README 限制说明堆在长段落 | 统一可读输出，明确授权提示，简化入口并保留详细能力文档 |
| A08 | 高 | 本机八包运行期间发生提交变更，报告只记录结束时提交，可能错绑混合源码结果 | 记录初始提交/工作树状态并在结束时复查，变化即失败；该次结果不计验收，需重跑 |

本机验证：fmt、严格 Clippy/doc、264 项 Rust 测试、Linux x64/macOS ARM64 交叉 check 通过；Python 164 项中 160 通过、4 项 POSIX 权限用例跳过，56 文件 Ruff/mypy 通过。Schema、项目文件/链接和 actionlint 通过；C 示例以及 CLI/C/Python 原生 smoke 通过。三平台 CI、干净源码的八包与候选包回归尚待本轮执行，历史结果不替代本轮验收。

私密漏洞报告已通过 API 开启并核验为 enabled=true；未发送漏洞报告或其他对外消息。

首次 CI [40422585226](https://github.com/DaoSeeker01/DaoSeekerScope/actions/runs/40422585226)的 Linux 集成测试发现两条旧文本断言未更新，已修正；失败记录保留，剩余任务取消。随后运行 40422984594 为加入 A08 修复而取消，不计作通过。八包本机结果也因源码变动不计验收，最终记录以冻结源码后的重跑为准。

## 保留的限制

实体 Linux/macOS、多组 CPU、其他 OEM/驱动、最低运行环境和长期资源测量仍有缺口。macOS 分发材料未补齐，不通过更改许可门禁来宣称完成；也不把 AMDGPU 的 VRAM 统计直接当作所有设备的独占显存。

当前 [v0.1 清单](v0.1-checklist.md)列出正式交付门槛；[开发进度](progress.md)保留平台增强任务。未知问题继续通过 Issue 跟踪，不宣称本次找出了项目的所有缺陷。

## 参考依据

- [GitHub Issue 表单语法](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms)。
- [GitHub 私密漏洞报告](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately)；写 SECURITY.md 不会自动开启私密报告功能。
- [GitHub 工作流并发](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)。

依赖说明：新增 [PyYAML 6.0.3](https://pypi.org/project/PyYAML/6.0.3/)（MIT）及 [types-PyYAML 6.0.12.20260906](https://pypi.org/project/types-PyYAML/6.0.12.20260906/)（Apache-2.0），分别用于开发期 YAML 检查和类型检查，不进入 Rust 或 SDK 运行时依赖。既有 jsonschema/Ruff/mypy 版本移到 requirements-dev.txt。移除该检查及对应开发依赖即可回退，替代方式是单独运行 YAML 检查器。项目 MIT、C ABI 1、Schema 1 和 SDK/CLI 候选包格式保持。
