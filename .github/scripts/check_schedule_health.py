from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def _env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _api_request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    request = Request(url, data=body, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "CTF-bot schedule monitor")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    with urlopen(request, timeout=30) as response:
        content = response.read()
        if not content:
            return None
        return json.loads(content.decode("utf-8"))


def _parse_github_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _find_alert_issue(repo: str, title: str, token: str | None) -> dict[str, Any] | None:
    issues = _api_request(
        "GET",
        f"https://api.github.com/repos/{repo}/issues?state=open&per_page=100",
        token=token,
    )
    for issue in issues or []:
        if issue.get("pull_request"):
            continue
        if issue.get("title") == title:
            return issue
    return None


def _upsert_alert_issue(repo: str, title: str, body: str, token: str | None) -> None:
    if not token:
        print("No GITHUB_TOKEN available. Skipping issue creation.", file=sys.stderr)
        return

    issue = _find_alert_issue(repo, title, token)
    if issue is None:
        _api_request(
            "POST",
            f"https://api.github.com/repos/{repo}/issues",
            token=token,
            payload={"title": title, "body": body},
        )
        return

    _api_request(
        "PATCH",
        f"https://api.github.com/repos/{repo}/issues/{issue['number']}",
        token=token,
        payload={"body": body, "state": "open"},
    )


def _close_alert_issue(repo: str, title: str, token: str | None, body: str) -> None:
    if not token:
        return

    issue = _find_alert_issue(repo, title, token)
    if issue is None:
        return

    _api_request(
        "PATCH",
        f"https://api.github.com/repos/{repo}/issues/{issue['number']}",
        token=token,
        payload={"body": body, "state": "closed"},
    )


def main() -> int:
    repo = _env("GITHUB_REPOSITORY", "yunttai/CTF-bot")
    workflow_path = _env("TARGET_WORKFLOW_PATH", ".github/workflows/update-ctf-db.yml")
    max_lag_minutes = int(_env("MAX_SCHEDULE_LAG_MINUTES", "80"))
    alert_issue_title = _env("ALERT_ISSUE_TITLE", "Scheduled CTF DB refresh appears stale")
    token = os.getenv("GITHUB_TOKEN", "").strip() or None

    workflow_ref = quote(workflow_path, safe="")
    runs_url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_ref}/runs"
        "?event=schedule&per_page=1"
    )
    payload = _api_request("GET", runs_url, token=token)
    runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []

    if not runs:
        message = (
            f"No scheduled runs were found for `{workflow_path}` in `{repo}`.\n\n"
            "This usually means the workflow has not been triggered yet or the schedule stopped firing."
        )
        _upsert_alert_issue(repo, alert_issue_title, message, token)
        print(message, file=sys.stderr)
        return 1

    latest_run = runs[0]
    created_at = _parse_github_timestamp(latest_run["created_at"])
    age_minutes = (datetime.now(timezone.utc) - created_at).total_seconds() / 60
    html_url = latest_run.get("html_url", "")
    status = latest_run.get("status")
    conclusion = latest_run.get("conclusion")

    is_stale = age_minutes > max_lag_minutes
    is_failed = not (status == "completed" and conclusion == "success")

    if is_stale or is_failed:
        message = (
            f"The latest scheduled run for `{workflow_path}` looks unhealthy.\n\n"
            f"- Run URL: {html_url or '(missing)'}\n"
            f"- Created at: {latest_run['created_at']}\n"
            f"- Age (minutes): {age_minutes:.1f}\n"
            f"- Status: {status}\n"
            f"- Conclusion: {conclusion}\n"
            f"- Allowed lag (minutes): {max_lag_minutes}\n"
        )
        _upsert_alert_issue(repo, alert_issue_title, message, token)
        print(message, file=sys.stderr)
        return 1

    recovery_message = (
        f"The latest scheduled run is healthy again.\n\n"
        f"- Run URL: {html_url or '(missing)'}\n"
        f"- Created at: {latest_run['created_at']}\n"
        f"- Age (minutes): {age_minutes:.1f}\n"
        f"- Status: {status}\n"
        f"- Conclusion: {conclusion}\n"
    )
    _close_alert_issue(repo, alert_issue_title, token, recovery_message)
    print(recovery_message)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"GitHub API request failed with {exc.code}: {body}", file=sys.stderr)
        raise
