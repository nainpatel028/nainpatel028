#!/usr/bin/env python3
"""Refresh the Recent GitHub Activity section of README.md from public events.

Reads public activity for GITHUB_USERNAME via the GitHub REST API and
replaces the content between the RECENT-ACTIVITY markers only — nothing
else in the README is touched. Standard-library only (urllib, json,
datetime), so no extra dependencies are needed in the workflow.

Safe to run locally against a copy of the README: point README_PATH at a
temporary file before running against the real one.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

START_MARKER = "<!-- RECENT-ACTIVITY:START -->"
END_MARKER = "<!-- RECENT-ACTIVITY:END -->"

MAX_EVENTS = 10
RELEVANT_EVENT_TYPES = {
    "PushEvent",
    "PullRequestEvent",
    "IssuesEvent",
    "CreateEvent",
    "PublicEvent",
    "WatchEvent",
    "ForkEvent",
}


def fetch_events(username: str, token: str | None) -> list[dict]:
    url = f"https://api.github.com/users/{username}/events/public?per_page=30"
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", f"{username}-profile-readme-bot")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def format_timestamp(iso_ts: str) -> str:
    dt = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def describe_event(event: dict) -> str | None:
    event_type = event.get("type")
    if event_type not in RELEVANT_EVENT_TYPES:
        return None

    repo_name = event.get("repo", {}).get("name", "")
    repo_url = f"https://github.com/{repo_name}"
    when = format_timestamp(event["created_at"])
    payload = event.get("payload", {})

    if event_type == "PushEvent":
        # GitHub's public events API frequently returns "size"/"commits" as
        # null (not merely absent) rather than a real count, so treat a
        # falsy/missing value as "unknown" instead of asserting "0 commits".
        size = payload.get("size") or len(payload.get("commits") or [])
        branch = (payload.get("ref") or "").replace("refs/heads/", "", 1)
        branch_url = f"{repo_url}/tree/{branch}" if branch else repo_url
        count_phrase = f"{size} {'commit' if size == 1 else 'commits'}" if size else "commit(s)"
        return f"Pushed {count_phrase} to [`{branch}`]({branch_url}) in [{repo_name}]({repo_url}) — {when}"

    if event_type == "PullRequestEvent":
        action = payload.get("action", "updated")
        pr = payload.get("pull_request", {})
        number = pr.get("number")
        title = pr.get("title", "")
        pr_url = pr.get("html_url", repo_url)
        return f"{action.capitalize()} pull request [#{number} {title}]({pr_url}) in [{repo_name}]({repo_url}) — {when}"

    if event_type == "IssuesEvent":
        action = payload.get("action", "updated")
        issue = payload.get("issue", {})
        number = issue.get("number")
        title = issue.get("title", "")
        issue_url = issue.get("html_url", repo_url)
        return f"{action.capitalize()} issue [#{number} {title}]({issue_url}) in [{repo_name}]({repo_url}) — {when}"

    if event_type == "CreateEvent":
        ref_type = payload.get("ref_type", "repository")
        ref = payload.get("ref")
        target = f"{ref_type} `{ref}`" if ref else ref_type
        return f"Created {target} in [{repo_name}]({repo_url}) — {when}"

    if event_type == "PublicEvent":
        return f"Made [{repo_name}]({repo_url}) public — {when}"

    if event_type == "WatchEvent":
        return f"Starred [{repo_name}]({repo_url}) — {when}"

    if event_type == "ForkEvent":
        return f"Forked [{repo_name}]({repo_url}) — {when}"

    return None


def build_section(events: list[dict]) -> str:
    lines = []
    for event in events:
        line = describe_event(event)
        if line:
            lines.append(f"- {line}")
        if len(lines) >= MAX_EVENTS:
            break

    if not lines:
        lines = ["_No recent public activity found._"]

    body = "\n".join(lines)
    # Deliberately no "last checked" timestamp here: the section must be
    # byte-identical across runs when the underlying activity hasn't
    # changed, so the workflow's git-diff check can correctly skip
    # committing when there's nothing new to report.
    return f"{START_MARKER}\n{body}\n{END_MARKER}"


def splice_readme(readme_text: str, section: str) -> str:
    pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)
    if not pattern.search(readme_text):
        raise ValueError(
            f"README is missing {START_MARKER} / {END_MARKER} markers; refusing to guess where to insert."
        )
    return pattern.sub(lambda _: section, readme_text, count=1)


def main() -> int:
    username = os.environ.get("GITHUB_USERNAME", "nainpatel028")
    readme_path = os.environ.get("README_PATH", "README.md")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    try:
        events = fetch_events(username, token)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"Failed to fetch public events for {username}: {exc}", file=sys.stderr)
        return 1

    section = build_section(events)

    with open(readme_path, "r", encoding="utf-8") as f:
        original = f.read()

    updated = splice_readme(original, section)

    if updated == original:
        print("No change to recent-activity section.")
        return 0

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(updated)

    print(f"Updated {readme_path} from {len(events)} fetched events.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
