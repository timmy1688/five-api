"""Offline checks used by CI and tag publishing."""
import argparse
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())["project"]["version"]
    frontend = json.loads((ROOT / "frontend/package.json").read_text())
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    assert frontend["version"] == lock["version"] == lock["packages"][""]["version"] == version
    assert f'version="{version}"' in (ROOT / "backend/app/main.py").read_text()
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert f"## [{version}]" in changelog
    if args.tag:
        assert args.tag == "v" + version, "Tag must match package versions"
    for name in ("README.md", "docs/README.en.md", "docs/OPERATIONS.md", "docs/COMPATIBILITY.md",
                 "CONTRIBUTING.md"):
        assert (ROOT / name).is_file(), name
    requirements = sorted((ROOT / "backend").glob("requirements*"))
    assert [path.name for path in requirements] == ["requirements.txt"], "Keep a single requirements.txt"
    for entry in requirements[0].read_text().splitlines():
        if entry and not entry.startswith("#"):
            assert re.match(r"[A-Za-z0-9_.\[\]-]+==[^\s;]+", entry), f"Unpinned dependency: {entry}"
    content = (ROOT / "Dockerfile").read_text()
    assert content.count("@sha256:") == 2 and "USER 10001:10001" in content and "mirrors.aliyun.com" in content
    print(f"PASS: version {version}, pinned requirements, release documents and image policy")


if __name__ == "__main__":
    main()
