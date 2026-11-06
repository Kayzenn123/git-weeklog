#!/usr/bin/env python3
"""git-weeklog — turn a repo's git history into a readable digest.

Reads `git log` for a period, groups commits by day, author, or
conventional-commit type, and prints a human table, JSON, or Markdown
digest. Read-only: it never writes to the repository.

Defaults live in a config file (~/.git-weeklog.json, or the path given by
--config / GIT_WEEKLOG_CONFIG). Every config key can be overridden by a
CLI flag; flags win over config, config wins over built-in defaults.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta

VERSION = "1.0.0"
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.git-weeklog.json")
DEFAULTS = {
    "repo": ".",
    "since": "7d",
    "until": None,
    "author": None,
    "group-by": "day",
    "format": "human",
    "max-commits": 200,
}

TYPES = ["feat", "fix", "docs", "chore", "refactor", "test", "style",
         "build", "ci", "perf", "revert"]
USAGE_ERROR = 2
RUNTIME_ERROR = 1


def parse_since(value, today):
    """Parse '7d', '2w', or 'YYYY-MM-DD' into a date. Raises ValueError."""
    if value is None:
        return None
    value = str(value).strip()
    m = re.fullmatch(r"(\d+)([dw])", value)
    if m:
        n = int(m.group(1))
        if m.group(2) == "d":
            return today - timedelta(days=n)
        return today - timedelta(weeks=n)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(
            "invalid --since value %r: use Nd, Nw, or YYYY-MM-DD" % value)


def parse_date(value, name):
    """Parse 'YYYY-MM-DD' into a date. Raises ValueError."""
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(
            "invalid %s value %r: use YYYY-MM-DD" % (name, value))


def commit_type(subject):
    """Conventional-commit type of a subject, or 'other'."""
    m = re.match(r"^([a-z]+)(?:\([^)]*\))?:\s", subject or "")
    if m and m.group(1) in TYPES:
        return m.group(1)
    return "other"


def load_config(path):
    """Load a JSON config file. Returns {} when absent; errors exit 1."""
    if path is None:
        path = os.environ.get("GIT_WEEKLOG_CONFIG") or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print("error: cannot read config %s: %s" % (path, exc),
              file=sys.stderr)
        sys.exit(RUNTIME_ERROR)
    if not isinstance(data, dict):
        print("error: config %s must be a JSON object" % path,
              file=sys.stderr)
        sys.exit(RUNTIME_ERROR)
    known = set(DEFAULTS)
    unknown = sorted(set(data) - known)
    if unknown:
        print("warning: unknown config keys ignored in %s: %s"
              % (path, ", ".join(unknown)), file=sys.stderr)
    return {k: v for k, v in data.items() if k in known}


def resolve_settings(args):
    """Merge built-in defaults, config file, and CLI flags."""
    cfg = load_config(args.config)
    settings = dict(DEFAULTS)
    settings.update(cfg)
    for key in DEFAULTS:
        flag = getattr(args, key.replace("-", "_"), None)
        if flag is not None:
            settings[key] = flag
    return settings


def build_git_args(settings, since_date, until_date):
    """Build the `git log` argv (list form, no shell)."""
    argv = ["git", "-C", settings["repo"], "log",
            "--numstat",
            "--pretty=format:%H%x1f%an%x1f%ad%x1f%s%x1e",
            "--date=short",
            "--max-count=%d" % int(settings["max-commits"])]
    if since_date is not None:
        argv.append("--since=%s" % since_date.isoformat())
    if until_date is not None:
        # --until is exclusive at midnight; include the whole day.
        argv.append("--until=%s" % (until_date + timedelta(days=1)).isoformat())
    if settings["author"]:
        argv.append("--author=%s" % settings["author"])
    return argv


def parse_log(raw):
    """Parse `git log --numstat` output into a list of commit dicts.

    Each commit header is one line: sha, author, date, subject joined by
    \\x1f and terminated by \\x1e. The numstat lines for that commit
    follow on the next lines, until the next header.
    """
    commits = []
    current = None
    for line in raw.split("\n"):
        line = line.rstrip("\x1e")
        if "\x1f" in line:
            header = line.split("\x1f")
            if len(header) != 4:
                continue
            sha, author, date_s, subject = header
            current = {
                "sha": sha, "author": author, "date": date_s,
                "subject": subject, "type": commit_type(subject),
                "insertions": 0, "deletions": 0, "files": {},
            }
            commits.append(current)
            continue
        if current is None:
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        ins, dele, path = parts
        if ins == "-" or dele == "-":
            continue
        try:
            current["insertions"] += int(ins)
            current["deletions"] += int(dele)
        except ValueError:
            continue
        current["files"][path] = current["files"].get(path, 0) + 1
    return commits


def collect_commits(settings, since_date, until_date):
    """Run git log and return parsed commits. Errors exit 1."""
    argv = build_git_args(settings, since_date, until_date)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=60)
    except FileNotFoundError:
        print("error: git is not installed or not on PATH", file=sys.stderr)
        sys.exit(RUNTIME_ERROR)
    except subprocess.TimeoutExpired:
        print("error: git log timed out after 60s", file=sys.stderr)
        sys.exit(RUNTIME_ERROR)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().split("\n")[0]
        if "not a git repository" in err or "does not exist" in err:
            print("error: %s is not a git repository"
                  % settings["repo"], file=sys.stderr)
        else:
            print("error: git log failed: %s" % err, file=sys.stderr)
        sys.exit(RUNTIME_ERROR)
    return parse_log(proc.stdout)


def group_key(commit, mode):
    if mode == "author":
        return commit["author"]
    if mode == "type":
        return commit["type"]
    return commit["date"]


def summarize(commits, mode):
    """Group commits; each group carries totals and top files."""
    groups = OrderedDict()
    for commit in commits:
        key = group_key(commit, mode)
        group = groups.setdefault(key, {
            "key": key, "commits": [], "authors": Counter(),
            "insertions": 0, "deletions": 0, "files": Counter(),
        })
        group["commits"].append(commit)
        group["authors"][commit["author"]] += 1
        group["insertions"] += commit["insertions"]
        group["deletions"] += commit["deletions"]
        for path, count in commit["files"].items():
            group["files"][path] += count
    for group in groups.values():
        group["top_files"] = group["files"].most_common(5)
        group["top_authors"] = group["authors"].most_common(3)
    return list(groups.values())


def totals(commits):
    return {
        "commits": len(commits),
        "authors": sorted({c["author"] for c in commits}),
        "insertions": sum(c["insertions"] for c in commits),
        "deletions": sum(c["deletions"] for c in commits),
    }


def use_color(no_color):
    if no_color or os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


def render_human(groups, total, settings, color):
    def bold(text):
        return "\x1b[1m%s\x1b[0m" % text if color else text

    lines = []
    header = "git-weeklog — %s  (%s .. %s)" % (
        settings["repo"], settings["since"], settings["until"] or "today")
    lines.append(bold(header))
    lines.append("%d commit(s) by %d author(s): +%d/-%d lines" % (
        total["commits"], len(total["authors"]),
        total["insertions"], total["deletions"]))
    if not groups:
        lines.append("No commits in this period.")
        return "\n".join(lines) + "\n"
    for group in groups:
        lines.append("")
        lines.append(bold("%s — %d commit(s), +%d/-%d" % (
            group["key"], len(group["commits"]),
            group["insertions"], group["deletions"])))
        authors = ", ".join("%s (%d)" % (a, n)
                            for a, n in group["top_authors"])
        lines.append("  authors: %s" % authors)
        if group["top_files"]:
            top = ", ".join("%s (%d)" % (p, n)
                            for p, n in group["top_files"])
            lines.append("  hot files: %s" % top)
        for commit in group["commits"]:
            lines.append("  - %s %s (%s, +%d/-%d)" % (
                commit["date"], commit["subject"], commit["author"],
                commit["insertions"], commit["deletions"]))
    return "\n".join(lines) + "\n"


def render_json(groups, total, settings):
    payload = {
        "repo": settings["repo"],
        "since": settings["since"],
        "until": settings["until"],
        "group_by": settings["group-by"],
        "totals": total,
        "groups": [{
            "key": g["key"],
            "commits": len(g["commits"]),
            "insertions": g["insertions"],
            "deletions": g["deletions"],
            "authors": dict(g["authors"]),
            "top_files": [[p, n] for p, n in g["top_files"]],
            "subjects": [c["subject"] for c in g["commits"]],
        } for g in groups],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render_markdown(groups, total, settings):
    lines = ["# Weeklog — %s" % settings["repo"], "",
             "Period: %s .. %s · %d commit(s) by %d author(s) · "
             "+%d/-%d lines" % (
                 settings["since"], settings["until"] or "today",
                 total["commits"], len(total["authors"]),
                 total["insertions"], total["deletions"]), ""]
    if not groups:
        lines.append("_No commits in this period._")
        return "\n".join(lines) + "\n"
    for group in groups:
        lines.append("## %s (%d commit(s), +%d/-%d)" % (
            group["key"], len(group["commits"]),
            group["insertions"], group["deletions"]))
        for commit in group["commits"]:
            lines.append("- %s — %s (%s)" % (
                commit["date"], commit["subject"], commit["author"]))
        lines.append("")
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="git-weeklog",
        description="Summarize a repo's git history into a readable "
                    "digest (grouped by day, author, or commit type).")
    parser.add_argument("--repo", default=None,
                        help="repository path (default: config or .)")
    parser.add_argument("--since", default=None,
                        help="start of period: Nd, Nw, or YYYY-MM-DD "
                             "(default: 7d)")
    parser.add_argument("--until", default=None,
                        help="end of period: YYYY-MM-DD (default: today)")
    parser.add_argument("--author", default=None,
                        help="only commits by this author (substring match)")
    parser.add_argument("--group-by", default=None,
                        choices=["day", "author", "type"],
                        help="how to group commits (default: day)")
    parser.add_argument("--format", default=None,
                        choices=["human", "json", "markdown"],
                        help="output format (default: human)")
    parser.add_argument("--max-commits", default=None, type=int,
                        help="cap on commits read (default: 200)")
    parser.add_argument("--config", default=None,
                        help="config file path (default: ~/.git-weeklog.json)")
    parser.add_argument("--no-color", action="store_true",
                        help="disable ANSI colors")
    parser.add_argument("--version", action="version",
                        version="git-weeklog %s" % VERSION)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = resolve_settings(args)
    today = date.today()
    try:
        since_date = parse_since(settings["since"], today)
        until_date = (parse_date(settings["until"], "--until")
                      if settings["until"] else None)
    except ValueError as exc:
        parser.error(str(exc))
    if since_date and until_date and since_date > until_date:
        parser.error("--since must not be after --until")
    if int(settings["max-commits"]) < 1:
        parser.error("--max-commits must be at least 1")
    settings["since"] = (since_date.isoformat() if since_date
                         else settings["since"])
    settings["until"] = (until_date.isoformat() if until_date else None)

    commits = collect_commits(settings, since_date, until_date)
    groups = summarize(commits, settings["group-by"])
    total = totals(commits)
    fmt = settings["format"]
    if fmt == "json":
        sys.stdout.write(render_json(groups, total, settings))
    elif fmt == "markdown":
        sys.stdout.write(render_markdown(groups, total, settings))
    else:
        sys.stdout.write(render_human(groups, total, settings,
                                      use_color(args.no_color)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
