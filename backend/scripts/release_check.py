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
                 "CONTRIBUTING.md", "SECURITY.md", "deploy/nginx.conf"):
        assert (ROOT / name).is_file(), name
    versions = []
    for name in ("requirements.lock", "requirements-dev.lock"):
        content = (ROOT / "backend" / name).read_text()
        entries = re.sub(r"\\\n\s*", " ", content).splitlines()
        pins = {}
        for entry in entries:
            if not entry or entry.startswith("#"):
                continue
            match = re.match(r"([A-Za-z0-9_.-]+)==([^\s;]+)", entry)
            assert match and "--hash=sha256:" in entry, f"Unpinned or unhashed dependency: {entry}"
            pins[match.group(1).lower()] = match.group(2)
        versions.append(pins)
    assert all(versions[1].get(name) == value for name, value in versions[0].items()), "Runtime/development lock drift"
    for name in ("Dockerfile", "backend/Dockerfile"):
        content = (ROOT / name).read_text()
        assert "@sha256:" in content and "USER 10001:10001" in content and "--require-hashes" in content
    print(f"PASS: version {version}, dependency locks, release documents and image policy")


if __name__ == "__main__":
    main()
