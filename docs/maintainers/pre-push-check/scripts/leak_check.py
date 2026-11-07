#!/usr/bin/env python3
"""Scan what is about to be pushed for secrets and personal data.

Usage (from the repository root):
  python docs/maintainers/pre-push-check/scripts/leak_check.py              # commits in @{upstream}..HEAD
  python docs/maintainers/pre-push-check/scripts/leak_check.py --worktree   # plus uncommitted and untracked files
  python docs/maintainers/pre-push-check/scripts/leak_check.py --range origin/main..HEAD
  python docs/maintainers/pre-push-check/scripts/leak_check.py --history    # every commit on every branch

Exit code 1 when a BLOCK finding exists. Matched values are always masked; local
secret values are compared in memory and never printed.
"""
import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ALLOW_MARKER = "leak-check: allow"
KNOWN_FAKES = {
    "AKIAIOSFODNN7EXAMPLE",
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
}
PLACEHOLDER = re.compile(r"(?i)(example|your[-_]|xxx|placeholder|change[-_]?me|dummy|fake|<[^>]+>|\.\.\.|\*\*\*)")
TEST_PATH = re.compile(r"(^|/)(tests?|fixtures?|scripts/[^/]*_check\.py)(/|$)|(^|/)test_[^/]*\.py$|_test\.py$")

SECRET_RULES = [
    ("private_key", re.compile(r"-----BEGIN [A-Z0-9 ]{0,48}PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("gitee_or_gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9]{8,}-[A-Za-z0-9-]{8,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{30,}")),
    ("openai_style_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("aliyun_access_key", re.compile(r"\bLTAI[A-Za-z0-9]{12,30}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("url_credentials", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@'\"]+:[^/\s@'\"]{6,}@")),
    ("feishu_dingtalk_webhook", re.compile(r"(?:open\.feishu\.cn/open-apis/bot/v2/hook/[0-9a-f-]{20,}|oapi\.dingtalk\.com/robot/send\?access_token=[0-9a-f]{40,})")),
    ("password_assignment", re.compile(
        r"""(?i)\b(?:password|passwd|secret|secret_key|api_key|token)\b["']?\s*[:=]\s*["']([^"'\s$]{10,})["']""")),
]
PERSONAL_RULES = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("cn_mobile", re.compile(r"(?<![\d.])1[3-9]\d{9}(?![\d.])")),
    ("cn_id_card", re.compile(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")),
    ("public_ipv4", re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")),
]
SAFE_EMAIL = re.compile(r"(?i)(^git@|noreply|no-reply|example\.(com|org|net)|\.test$|\.invalid$|dromara\.org$|localhost)")
LOCK_FILE = re.compile(r"(?i)(\.lock|package-lock\.json|pnpm-lock\.yaml)$")
DOTTED_NAME = re.compile(r"^[A-Za-z_]\w*(\.\w+)+$")
SENSITIVE_FILE = re.compile(
    r"(?i)(^|/)(\.env(\.(?!example$)[^/]+)?|secrets?\.json|id_(rsa|ed25519|ecdsa)|[^/]+\.(pem|key|p12|pfx|keystore|jks)"
    r"|[^/]+\.(sqlite3?|db|sql|dump|bak)|credentials(\.json)?|\.npmrc|\.pypirc)$|(^|/)data/")
IMAGE_FILE = re.compile(r"(?i)\.(png|jpe?g|gif|webp|bmp)$")
LOCAL_SECRET_FILES = (".env", "backend/.env", "data/secrets.json")
TRACKED_DEFAULTS = (".env.example", "docker-compose.yml")


@dataclass
class Finding:
    level: str
    kind: str
    where: str
    detail: str


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, errors="replace").stdout


def mask(value: str) -> str:
    value = value.strip()
    return value[:4] + "…" + f"({len(value)} chars)" if len(value) > 6 else "…"


def public_ip(ip: str) -> bool:
    parts = [int(p) for p in ip.split(".")]
    if any(p > 255 for p in parts):
        return False
    a, b = parts[0], parts[1]
    private = (a in (0, 10, 127) or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)
               or (a == 169 and b == 254) or a >= 224 or (a == 100 and 64 <= b <= 127))
    documentation = ip.startswith(("192.0.2.", "198.51.100.", "203.0.113."))
    well_known = ip in {"1.1.1.1", "8.8.8.8", "8.8.4.4", "114.114.114.114", "223.5.5.5"}
    return not (private or documentation or well_known)


def valid_id_card(number: str) -> bool:
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    total = sum(int(d) * w for d, w in zip(number[:17], weights))
    return "10X98765432"[total % 11] == number[17].upper()


def local_secret_values(root: Path) -> dict[str, str]:
    """value -> origin label. Values also present in tracked defaults are public already."""
    public = ""
    for name in TRACKED_DEFAULTS:
        path = root / name
        if path.exists():
            public += path.read_text(errors="replace")
    values: dict[str, str] = {}

    def keep(value, label):
        if isinstance(value, str) and len(value) >= 8 and value not in public and not PLACEHOLDER.search(value):
            values[value] = label

    for name in LOCAL_SECRET_FILES:
        path = root / name
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        if name.endswith(".json"):
            try:
                for key, value in json.loads(text).items():
                    keep(value, f"{name}:{key}")
            except (ValueError, AttributeError):
                pass
            continue
        for line in text.splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                keep(value.strip().strip("'\""), f"{name}:{key.strip()}")
    return values


def added_lines_from_patch(patch: str):
    """Yield (path, commit, line) for every added line in `git log -p` / `git diff` output."""
    path, commit = "", ""
    for raw in patch.splitlines():
        if raw.startswith("commit ") and len(raw.split()) == 2:
            commit = raw.split()[1][:9]
        elif raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else ""
        elif raw.startswith("+") and not raw.startswith("+++") and path:
            yield path, commit, raw[1:]


def scan_line(path: str, commit: str, line: str, local: dict[str, str], findings: list[Finding]):
    if ALLOW_MARKER in line:
        return
    where = f"{path}" + (f" @{commit}" if commit else "")
    in_tests = bool(TEST_PATH.search(path))
    for value, origin in local.items():
        if value in line:
            findings.append(Finding("BLOCK", "local_secret_value", where, f"matches the real value of {origin}"))
    for kind, pattern in SECRET_RULES:
        for match in pattern.finditer(line):
            value = match.group(match.lastindex or 0)
            if value in KNOWN_FAKES or PLACEHOLDER.search(match.group(0)):
                continue
            if kind == "password_assignment" and DOTTED_NAME.match(value):
                continue
            level = "WARN" if in_tests else "BLOCK"
            if kind in {"password_assignment", "jwt", "url_credentials"} and in_tests:
                continue
            findings.append(Finding(level, kind, where, mask(value) + (" (test path: confirm it is fake)" if in_tests else "")))
    if LOCK_FILE.search(path):
        return
    for kind, pattern in PERSONAL_RULES:
        if in_tests and kind in {"email", "public_ipv4"}:
            continue
        for match in pattern.finditer(line):
            value = match.group(0)
            if kind == "email" and SAFE_EMAIL.search(value):
                continue
            if kind == "public_ipv4" and (not public_ip(value) or line[max(0, match.start() - 1):match.start()] in "=v@"):
                continue
            if kind == "cn_id_card" and not valid_id_card(value):
                continue
            findings.append(Finding("WARN", kind, where, mask(value)))


def scan_files(changed: list[tuple[str, str]], findings: list[Finding]) -> list[str]:
    images = []
    for status, path in changed:
        if status.startswith("D"):
            continue
        if SENSITIVE_FILE.search(path) and not path.endswith(".example"):
            findings.append(Finding("BLOCK", "sensitive_file", path, f"status {status}"))
        if IMAGE_FILE.search(path):
            images.append(path)
    return images


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--range", help="commit range, default @{upstream}..HEAD")
    parser.add_argument("--worktree", action="store_true", help="also scan uncommitted and untracked files")
    parser.add_argument("--history", action="store_true", help="scan every commit on every branch")
    args = parser.parse_args()

    root = Path(git("rev-parse", "--show-toplevel").strip())
    local = local_secret_values(root)
    findings: list[Finding] = []
    changed: list[tuple[str, str]] = []

    if args.history:
        rev_args = ["--all"]
        label = "all history"
    else:
        rng = args.range
        if not rng:
            try:
                rng = git("rev-parse", "--abbrev-ref", "@{upstream}").strip() + "..HEAD"
            except subprocess.CalledProcessError:
                rng = "origin/main..HEAD"
        rev_args = [rng]
        label = rng

    patch = git("log", "-p", "--no-color", "--no-ext-diff", "--format=commit %H", *rev_args)
    commits = [line.split()[1] for line in patch.splitlines() if line.startswith("commit ") and len(line.split()) == 2]
    for path, commit, line in added_lines_from_patch(patch):
        scan_line(path, commit, line, local, findings)
    if commits:
        for line in git("log", "--name-status", "--format=", *rev_args).splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                changed.append((parts[0], parts[-1]))
        for line in git("log", "--format=%h%x00%an%x00%ae%x00%ce", *rev_args).splitlines():
            short, name, author_email, committer_email = line.split("\x00")
            for email in {author_email, committer_email}:
                if email and not SAFE_EMAIL.search(email):
                    findings.append(Finding("WARN", "commit_email", f"commit {short} ({name})",
                                            f"{mask(email)} will be public in the commit log"))

    if args.worktree:
        label += " + worktree"
        for path, commit, line in added_lines_from_patch(git("diff", "HEAD", "--no-color", "--no-ext-diff")):
            scan_line(path, "", line, local, findings)
        for line in git("diff", "HEAD", "--name-status").splitlines():
            parts = line.split("\t")
            changed.append((parts[0], parts[-1]))
        for path in git("ls-files", "--others", "--exclude-standard").splitlines():
            changed.append(("A?", path))
            file = root / path
            if file.is_file() and not IMAGE_FILE.search(path) and file.stat().st_size < 2_000_000:
                for line in file.read_text(errors="replace").splitlines():
                    scan_line(path, "", line, local, findings)

    images = sorted(set(scan_files(changed, findings)))
    unique = {(f.level, f.kind, f.where, f.detail): f for f in findings}
    findings = sorted(unique.values(), key=lambda f: (f.level != "BLOCK", f.kind, f.where))

    print(f"Scanned: {label} ({len(commits)} commits, {len(local)} local secret values compared)")
    for finding in findings:
        print(f"[{finding.level}] {finding.kind}: {finding.where} -> {finding.detail}")
    if images:
        print("[REVIEW] images added or changed, open each one and check for real data:")
        for path in images:
            print(f"  {path}")
    blocks = sum(f.level == "BLOCK" for f in findings)
    warns = sum(f.level == "WARN" for f in findings)
    print(f"Result: {blocks} BLOCK, {warns} WARN, {len(images)} images to review")
    return 1 if blocks else 0


if __name__ == "__main__":
    sys.exit(main())
