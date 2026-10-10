"""Generate a license inventory without recording local absolute dependency paths."""

import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
packages = sorted(
    (p for p in data["packages"] if p["source"] is not None),
    key=lambda p: (p["name"], p["version"]),
)
output = [
    "# 锁定依赖许可证清单",
    "",
    "由 cargo metadata --locked --all-features 生成，含三个目标的传递依赖；构建/开发工具 cargo-deny、jsonschema、libFuzzer 不属于运行时依赖。",
    "项目自身采用 MIT；上游保留各自许可证，分发时仍需保留版权与许可证。清单不是法律结论。",
    "",
    "| crate | version | SPDX license |",
    "|---|---|---|",
]
for package in packages:
    output.append(
        f"| {package['name']} | {package['version']} | {package['license'] or 'UNKNOWN'} |"
    )
pathlib.Path("docs/dependencies.md").write_text(
    "\n".join(output) + "\n", encoding="utf-8"
)
print(f"license inventory: {len(packages)} third-party packages")
