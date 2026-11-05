#!/usr/bin/env python3
"""Summarize a pull request for triage: metadata, files, risk flags and CI state.

Usage:
    python docs/maintainers/handle-pr/scripts/pr_info.py          # list open PRs
    python docs/maintainers/handle-pr/scripts/pr_info.py 3        # triage PR #3

Uses only the public GitHub API (no token, no gh). Set GITHUB_TOKEN to raise the rate limit.
If the default network path fails (for example a broken HTTP proxy), it retries without a proxy.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

REPO = "timmy1688/five-api"
API = f"https://api.github.com/repos/{REPO}"
TIMEOUT = 20

# Paths that run on maintainer machines or CI, or change what ships. Read these first.
RISKY = [
    (r"^\.github/", "workflow / CI"),
    (r"(^|/)Dockerfile", "image build"),
    (r"requirements.*\.txt$", "Python dependencies"),
    (r"(^|/)package(-lock)?\.json$", "frontend dependencies"),
    (r"^backend/scripts/", "scripts that run locally"),
    (r"conftest\.py$", "test bootstrap"),
    (r"^service\.sh$|docker-compose\.yml$", "deployment"),
    (r"^backend/migrations/", "database migration"),
    (r"^backend/app/models/", "ORM models (needs a migration)"),
    (r"settlement|billing|quota|selling_quote", "billing path"),
    (r"proxy\.py$|stream_outcomes\.py$", "streaming path"),
    (r"auth|secret|crypto|redaction", "security path"),
]


def fetch(url: str):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "five-api-handle-pr"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    request = urllib.request.Request(url, headers=headers)
    openers = [urllib.request.build_opener(), urllib.request.build_opener(urllib.request.ProxyHandler({}))]
    last_error = None
    for opener in openers:
        try:
            with opener.open(request, timeout=TIMEOUT) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"GitHub API {exc.code} for {url}: {exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
    raise SystemExit(f"Cannot reach GitHub API: {last_error}")


def list_open():
    pulls = fetch(f"{API}/pulls?state=open&per_page=30")
    if not pulls:
        print("No open pull requests.")
        return
    for pull in pulls:
        draft = " [draft]" if pull["draft"] else ""
        print(f"#{pull['number']}{draft} {pull['title']} | {pull['user']['login']} | {pull['head']['sha'][:7]}")


def section(body: str, name: str) -> str:
    match = re.search(rf"##\s*{name}\s*\n(.*?)(?=\n##\s|\Z)", body or "", re.S | re.I)
    return match.group(1).strip() if match else ""


def triage(number: int):
    pull = fetch(f"{API}/pulls/{number}")
    main = fetch(f"{API}/commits/{pull['base']['ref']}")
    files = fetch(f"{API}/pulls/{number}/files?per_page=100")
    runs = fetch(f"{API}/actions/runs?head_sha={pull['head']['sha']}").get("workflow_runs", [])

    print(f"#{number} {pull['title']}")
    print(f"author: {pull['user']['login']} | state: {pull['state']}{' (merged)' if pull['merged'] else ''}"
          f"{' | DRAFT' if pull['draft'] else ''}")
    print(f"size: {pull['changed_files']} files, +{pull['additions']} -{pull['deletions']}, {pull['commits']} commit(s)")
    print(f"mergeable: {pull['mergeable']} ({pull['mergeable_state']})")
    if pull["state"] == "open":
        up_to_date = pull["base"]["sha"] == main["sha"]
        print(f"based on latest {pull['base']['ref']}: "
              f"{'yes' if up_to_date else 'NO, base ' + pull['base']['sha'][:7] + ' vs ' + main['sha'][:7] + ' (Update branch needed)'}")
    else:
        print(f"merge commit: {(pull.get('merge_commit_sha') or '')[:7] or 'none'}")
    if runs:
        print("CI: " + ", ".join(f"{run['name']} {run['status']}/{run['conclusion']}" for run in runs))
    else:
        print("CI: no runs for this commit (a first-time fork PR may need a maintainer to approve the workflow)")

    print("\nfiles:")
    flagged = {}
    for item in files:
        name = item["filename"]
        print(f"  {item['status'][:3]} {name} +{item['additions']} -{item['deletions']}")
        for pattern, reason in RISKY:
            if re.search(pattern, name):
                flagged.setdefault(reason, []).append(name)
    if len(files) >= 100:
        print("  (100 files shown, there may be more)")
    if flagged:
        print("\nread these first / risk areas touched:")
        for reason, names in flagged.items():
            print(f"  - {reason}: {', '.join(names)}")

    body = pull["body"] or ""
    print("\nPR template sections:")
    for name in ("What changes", "Validation", "Upgrade"):
        text = section(body, name)
        print(f"  {name}: {'filled' if len(text) > 20 else 'EMPTY or very short'}")
    not_run = [line.strip() for line in section(body, "Validation").splitlines()
               if re.search(r"未运行|没有运行|未测试|not run|did not run|skipped", line, re.I)]
    for line in not_run:
        print(f"  author says not done: {line}")
    print(f"\nfetch the code:  git fetch origin pull/{number}/head:pr-{number}")


def main():
    if len(sys.argv) == 1:
        list_open()
    elif sys.argv[1].isdigit():
        triage(int(sys.argv[1]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
