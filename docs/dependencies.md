# 锁定依赖许可证清单

2026-10-19 Windows 内存直接查询使用已有 windows-sys 0.61.2 和现有 SystemInformation feature；不增加依赖、feature、锁文件或许可证变更。独立 C SDK 探针是开发工具，项目仍 MIT。

2026-10-15 Windows GPU 使用已锁定的 windows 0.62.2，增加为 Windows crate 的显式 target 依赖，关闭默认 features，仅启用 std/Win32_Foundation/Win32_Graphics_Dxgi/Win32_Graphics_Dxgi_Common。两个 Cargo.lock 仅增加依赖边，包和版本不变。SDK 绑定许可证 MIT OR Apache-2.0，项目仍 MIT；sysinfo 的默认 feature 路线不变。

2026-10-13 macOS 存储切片把已有 objc2-core-foundation 0.3.2、objc2-io-kit 0.3.2 增加为 macOS crate 的显式 target 依赖；关闭默认 features，限定 std/CFBase/CFDictionary/CFNumber/CFString 及 IOKit libc。Cargo.lock 仅增加该 crate 的依赖边，不新增包或版本；两者原有 Zlib OR Apache-2.0 OR MIT 许可证不变。Apple 公开 API/SDK 是接口依据，没有复制 APSL 实现；项目仍 MIT。sysinfo disk feature 仍关闭，公共模型不泄漏 CF/IOKit 类型。

2026-10-12 Linux 存储容量切片仅使用标准库与现有 core；无新依赖、锁定版本或许可证变化，sysinfo disk feature 仍关闭。复用既有 Linux fuzzing feature，没有新增默认 feature。

由 cargo metadata --locked --all-features 生成，含三个目标的传递依赖；构建/开发工具 cargo-deny、jsonschema、libFuzzer 不属于运行时依赖。
项目自身采用 MIT；上游保留各自许可证，分发时仍需保留版权与许可证。清单不是法律结论。

2026-10-11 Windows 网络切片仅为 Windows target 的 windows-sys 0.61.2 增加 `Win32_NetworkManagement_IpHelper` / `Win32_NetworkManagement_Ndis` feature；未增加 crate 或修改锁定版本、许可证。sysinfo network feature 仍关闭。

macOS 网络切片沿用 libc 0.2.190，不新增依赖或许可证；macOS crate 增加默认关闭的 `fuzzing` 测试 feature，fuzz harness 显式启用。公开消费 API 不变。

| crate | version | SPDX license |
|---|---|---|
| bitflags | 2.13.2 | MIT OR Apache-2.0 |
| dyn-clone | 1.0.20 | MIT OR Apache-2.0 |
| itoa | 1.0.18 | MIT OR Apache-2.0 |
| libc | 0.2.190 | MIT OR Apache-2.0 |
| memchr | 2.8.3 | Unlicense OR MIT |
| ntapi | 0.4.3 | Apache-2.0 OR MIT |
| objc2-core-foundation | 0.3.2 | Zlib OR Apache-2.0 OR MIT |
| objc2-io-kit | 0.3.2 | Zlib OR Apache-2.0 OR MIT |
| proc-macro2 | 1.0.107 | MIT OR Apache-2.0 |
| quote | 1.0.47 | MIT OR Apache-2.0 |
| ref-cast | 1.0.27 | MIT OR Apache-2.0 |
| ref-cast-impl | 1.0.27 | MIT OR Apache-2.0 |
| schemars | 1.2.2 | MIT |
| schemars_derive | 1.2.2 | MIT |
| serde | 1.0.229 | MIT OR Apache-2.0 |
| serde_core | 1.0.229 | MIT OR Apache-2.0 |
| serde_derive | 1.0.229 | MIT OR Apache-2.0 |
| serde_derive_internals | 0.30.0 | MIT OR Apache-2.0 |
| serde_json | 1.0.151 | MIT OR Apache-2.0 |
| syn | 2.0.119 | MIT OR Apache-2.0 |
| syn | 3.0.6 | MIT OR Apache-2.0 |
| sysinfo | 0.39.6 | MIT |
| unicode-ident | 1.0.26 | (MIT OR Apache-2.0) AND Unicode-3.0 |
| winapi | 0.3.9 | MIT/Apache-2.0 |
| winapi-i686-pc-windows-gnu | 0.4.0 | MIT/Apache-2.0 |
| winapi-x86_64-pc-windows-gnu | 0.4.0 | MIT/Apache-2.0 |
| windows | 0.62.2 | MIT OR Apache-2.0 |
| windows-collections | 0.3.2 | MIT OR Apache-2.0 |
| windows-core | 0.62.2 | MIT OR Apache-2.0 |
| windows-future | 0.3.2 | MIT OR Apache-2.0 |
| windows-implement | 0.60.2 | MIT OR Apache-2.0 |
| windows-interface | 0.59.3 | MIT OR Apache-2.0 |
| windows-link | 0.2.1 | MIT OR Apache-2.0 |
| windows-numerics | 0.3.1 | MIT OR Apache-2.0 |
| windows-result | 0.4.1 | MIT OR Apache-2.0 |
| windows-strings | 0.5.1 | MIT OR Apache-2.0 |
| windows-sys | 0.61.2 | MIT OR Apache-2.0 |
| windows-threading | 0.2.1 | MIT OR Apache-2.0 |
| zmij | 1.0.23 | MIT |

2026-10-16 macOS Metal GPU：新增以下 target 专用依赖（默认 features 关闭，按 SDK 模块启用）。原有包版本不变；Windows/Linux 不编译这些新增包。第三方多选许可证均可采用 MIT，无须扩大 cargo-deny 允许列表；项目仍为 MIT。

| crate | version | SPDX license |
|---|---|---|
| objc2 | 0.6.5 | MIT |
| objc2-encode | 4.1.0 | MIT |
| objc2-foundation | 0.3.2 | MIT |
| objc2-metal | 0.3.2 | Zlib OR Apache-2.0 OR MIT |

2026-10-16 Windows 显示器切片为已锁定 windows-sys 0.61.2 增加 `Win32_Devices_Display` feature，仅 Windows target 启用。两个 Cargo.lock 包版本、checksum 和依赖边不变，无新增 crate/许可证；项目 MIT、sysinfo features、公共 crate 默认 features 均不变。

2026-10-17 Linux DRM 连接/授权 EDID 名称切片只使用标准库和现有 core，无新增依赖、许可证、锁定版本或默认 features。复用隐藏 fuzzing feature 扩展 dmi_text；格式事实参考内核公开接口，独立实现并使用自行生成的合成 EDID，不复制 GPL 内核或 edid-decode 实现。项目仍 MIT。

2026-10-18 macOS 显示器切片仅增加 macOS 内部 CoreGraphics 系统 framework 链接及五个私有 C 声明，使用现有 std/core，无新 Rust 包、feature、锁定版本或许可证变化。独立 C SDK 探针校验宽度与 CGError 常量，不复制 Apple 实现。项目仍 MIT。
