#!/usr/bin/env python3
"""Tests for git-weeklog. Run: python3 -m unittest discover -s test -q"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "git-weeklog.py")

_spec = importlib.util.spec_from_file_location("git_weeklog", SCRIPT)
gw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gw)


def make_repo():
    """Create a temp git repo with dated commits; return its path."""
    tmp = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", "-b", "main", tmp], check=True)
    subprocess.run(["git", "-C", tmp, "config", "user.name", "Ada"],
                   check=True)
    subprocess.run(["git", "-C", tmp, "config", "user.email",
                    "ada@example.com"], check=True)
    commits = [
        ("2026-11-04", "feat: add parser", "a.py", "x = 1\n" * 10),
        ("2026-11-04", "fix: handle empty input", "a.py", "x = 2\n" * 5),
        ("2026-11-05", "docs: explain usage", "README.md", "# hi\n" * 3),
        ("2026-11-06", "chore: bump version", "a.py", "x = 3\n" * 2),
    ]
    for day, msg, fname, content in commits:
        with open(os.path.join(tmp, fname), "a", encoding="utf-8") as fh:
            fh.write(content)
        subprocess.run(["git", "-C", tmp, "add", "."], check=True)
        env = dict(os.environ, GIT_AUTHOR_DATE=day + "T10:00:00",
                   GIT_COMMITTER_DATE=day + "T10:00:00")
        subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", msg],
                       check=True, env=env)
    return tmp


class TestParseSince(unittest.TestCase):
    def test_days(self):
        today = date(2026, 11, 6)
        self.assertEqual(gw.parse_since("7d", today), date(2026, 10, 30))

    def test_weeks(self):
        today = date(2026, 11, 6)
        self.assertEqual(gw.parse_since("2w", today), date(2026, 10, 23))

    def test_iso_date(self):
        today = date(2026, 11, 6)
        self.assertEqual(gw.parse_since("2026-11-01", today),
                         date(2026, 11, 1))

    def test_invalid(self):
        with self.assertRaises(ValueError):
            gw.parse_since("yesterday", date(2026, 11, 6))
        with self.assertRaises(ValueError):
            gw.parse_since("2026-13-40", date(2026, 11, 6))


class TestCommitType(unittest.TestCase):
    def test_known_types(self):
        self.assertEqual(gw.commit_type("feat: add thing"), "feat")
        self.assertEqual(gw.commit_type("fix(core): crash"), "fix")
        self.assertEqual(gw.commit_type("docs: readme"), "docs")

    def test_other(self):
        self.assertEqual(gw.commit_type("Add thing"), "other")
        self.assertEqual(gw.commit_type("wip: stuff"), "other")
        self.assertEqual(gw.commit_type(""), "other")


class TestParseLog(unittest.TestCase):
    SAMPLE = (
        "abc123\x1fAda\x1f2026-11-04\x1ffeat: add parser\x1e\n"
        "10\t2\ta.py\n3\t0\tb.py\n"
        "def456\x1fBo\x1f2026-11-05\x1ffix: typo\x1e\n"
        "-\t-\timg.png\n")

    def test_two_commits(self):
        commits = gw.parse_log(self.SAMPLE)
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0]["subject"], "feat: add parser")
        self.assertEqual(commits[0]["insertions"], 13)
        self.assertEqual(commits[0]["deletions"], 2)
        self.assertEqual(commits[0]["files"], {"a.py": 1, "b.py": 1})
        # binary files count no lines but still parse
        self.assertEqual(commits[1]["insertions"], 0)
        self.assertEqual(commits[1]["type"], "fix")

    def test_empty_log(self):
        self.assertEqual(gw.parse_log(""), [])
        self.assertEqual(gw.parse_log("\n"), [])


class TestSummarize(unittest.TestCase):
    def setUp(self):
        self.commits = [
            {"sha": "a", "author": "Ada", "date": "2026-11-04",
             "subject": "feat: x", "type": "feat", "insertions": 10,
             "deletions": 2, "files": {"a.py": 1}},
            {"sha": "b", "author": "Bo", "date": "2026-11-04",
             "subject": "fix: y", "type": "fix", "insertions": 5,
             "deletions": 5, "files": {"a.py": 1, "b.py": 1}},
            {"sha": "c", "author": "Ada", "date": "2026-11-05",
             "subject": "docs: z", "type": "docs", "insertions": 3,
             "deletions": 0, "files": {"README.md": 1}},
        ]

    def test_group_by_day(self):
        groups = gw.summarize(self.commits, "day")
        self.assertEqual([g["key"] for g in groups],
                         ["2026-11-04", "2026-11-05"])
        self.assertEqual(groups[0]["insertions"], 15)
        self.assertEqual(groups[0]["top_files"][0], ("a.py", 2))

    def test_group_by_type(self):
        groups = gw.summarize(self.commits, "type")
        self.assertEqual([g["key"] for g in groups],
                         ["feat", "fix", "docs"])

    def test_group_by_author(self):
        groups = gw.summarize(self.commits, "author")
        self.assertEqual([g["key"] for g in groups], ["Ada", "Bo"])
        self.assertEqual(groups[0]["commits"].__len__(), 2)

    def test_totals(self):
        total = gw.totals(self.commits)
        self.assertEqual(total["commits"], 3)
        self.assertEqual(total["authors"], ["Ada", "Bo"])
        self.assertEqual(total["insertions"], 18)
        self.assertEqual(total["deletions"], 7)


class TestConfig(unittest.TestCase):
    def test_flag_beats_config_beats_default(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                        delete=False) as fh:
            json.dump({"since": "30d", "group-by": "author",
                       "format": "json", "max-commits": 5}, fh)
            path = fh.name
        try:
            parser = gw.build_parser()
            args = parser.parse_args(["--config", path, "--since", "3d"])
            settings = gw.resolve_settings(args)
            self.assertEqual(settings["since"], "3d")       # flag wins
            self.assertEqual(settings["group-by"], "author")  # config wins
            self.assertEqual(settings["format"], "json")
            self.assertEqual(settings["max-commits"], 5)
            self.assertEqual(settings["repo"], ".")          # default
        finally:
            os.unlink(path)

    def test_missing_config_is_empty(self):
        parser = gw.build_parser()
        args = parser.parse_args(["--config", "/nonexistent/x.json"])
        self.assertEqual(gw.resolve_settings(args)["since"], "7d")

    def test_unknown_keys_warned_not_fatal(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                        delete=False) as fh:
            json.dump({"since": "3d", "bogus": 1}, fh)
            path = fh.name
        try:
            parser = gw.build_parser()
            args = parser.parse_args(["--config", path])
            self.assertEqual(gw.resolve_settings(args)["since"], "3d")
        finally:
            os.unlink(path)


class TestRender(unittest.TestCase):
    def setUp(self):
        self.commits = gw.parse_log(
            "abc\x1fAda\x1f2026-11-04\x1ffeat: add parser\x1e\n"
            "10\t2\ta.py\n")
        self.groups = gw.summarize(self.commits, "day")
        self.total = gw.totals(self.commits)
        self.settings = dict(gw.DEFAULTS, repo="/tmp/demo",
                             since="2026-11-01", until="2026-11-06")

    def test_human_contains_subject(self):
        out = gw.render_human(self.groups, self.total, self.settings, False)
        self.assertIn("feat: add parser", out)
        self.assertIn("2026-11-04", out)
        self.assertNotIn("\x1b[", out)  # no ANSI when color off

    def test_json_structure(self):
        data = json.loads(gw.render_json(self.groups, self.total,
                                         self.settings))
        self.assertEqual(data["totals"]["commits"], 1)
        self.assertEqual(data["groups"][0]["key"], "2026-11-04")
        self.assertEqual(data["groups"][0]["subjects"],
                         ["feat: add parser"])

    def test_markdown_structure(self):
        out = gw.render_markdown(self.groups, self.total, self.settings)
        self.assertIn("# Weeklog", out)
        self.assertIn("## 2026-11-04", out)
        self.assertIn("feat: add parser", out)

    def test_empty_period(self):
        out = gw.render_human([], gw.totals([]), self.settings, False)
        self.assertIn("No commits", out)


class TestEndToEnd(unittest.TestCase):
    def test_real_repo_human_and_json(self):
        repo = make_repo()
        env = dict(os.environ)
        env.pop("GIT_WEEKLOG_CONFIG", None)
        r = subprocess.run(
            [sys.executable, SCRIPT, "--repo", repo, "--since", "2026-11-01",
             "--until", "2026-11-06", "--no-color"],
            capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4 commit(s)", r.stdout)
        self.assertIn("feat: add parser", r.stdout)
        self.assertIn("docs: explain usage", r.stdout)
        r = subprocess.run(
            [sys.executable, SCRIPT, "--repo", repo, "--since", "2026-11-01",
             "--until", "2026-11-06", "--format", "json"],
            capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["totals"]["commits"], 4)
        self.assertEqual(len(data["groups"]), 3)  # 3 distinct days

    def test_group_by_type_end_to_end(self):
        repo = make_repo()
        env = dict(os.environ)
        env.pop("GIT_WEEKLOG_CONFIG", None)
        r = subprocess.run(
            [sys.executable, SCRIPT, "--repo", repo, "--since", "2026-11-01",
             "--until", "2026-11-06", "--group-by", "type", "--no-color"],
            capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        for t in ("feat", "fix", "docs", "chore"):
            self.assertIn(t, r.stdout)

    def test_not_a_repo_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, SCRIPT, "--repo", tmp],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("not a git repository", r.stderr)

    def test_bad_since_exits_2(self):
        repo = make_repo()
        r = subprocess.run([sys.executable, SCRIPT, "--repo", repo,
                            "--since", "bogus"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_help_and_version(self):
        r = subprocess.run([sys.executable, SCRIPT, "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("--group-by", r.stdout)
        r = subprocess.run([sys.executable, SCRIPT, "--version"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("git-weeklog 1.0.0", r.stdout)


if __name__ == "__main__":
    unittest.main()
