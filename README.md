# git-weeklog

> Turn a repo's git history into a readable digest. Daily Tools #31.

## Why

`git log` answers "what changed", but not "what did we do this week" in a
form you can paste into a standup note or a report. Existing summarizers
either need an AI key, scan many projects at once, or only list raw commit
lines. git-weeklog is one zero-dependency Python file: it reads `git log
--numstat` for a period, groups commits by day, author, or
conventional-commit type, and prints totals, hot files, and a digest in
human, JSON, or Markdown form. Defaults live in `~/.git-weeklog.json`, so
your usual week view is one command away, and any flag overrides it.

## Install

```bash
git clone https://github.com/Kayzenn123/git-weeklog.git
cd git-weeklog
# no dependencies
```

Requires: Python >= 3.9, git on PATH.

Optional config file `~/.git-weeklog.json` (copy `examples/git-weeklog.json`
there and edit it). Any key can be overridden by a flag; flags win over the
config file, the config file wins over built-in defaults.

## Usage

```bash
python3 git-weeklog.py --help
python3 git-weeklog.py --repo ~/my-project --since 7d
python3 git-weeklog.py --repo . --since 2026-10-01 --until 2026-10-31 --group-by type
python3 git-weeklog.py --repo . --since 30d --author ada --format json
python3 git-weeklog.py --repo . --since 7d --format markdown
```

| Flag | Function | Default |
| --- | --- | --- |
| `--repo PATH` | repository to read (read-only, never modified) | `.` |
| `--since Nd\|Nw\|YYYY-MM-DD` | start of period | `7d` |
| `--until YYYY-MM-DD` | end of period (whole day included) | today |
| `--author NAME` | only commits by this author (substring match) | all |
| `--group-by day\|author\|type` | how commits are grouped | `day` |
| `--format human\|json\|markdown` | output format | `human` |
| `--max-commits N` | cap on commits read | `200` |
| `--config PATH` | config file (or `GIT_WEEKLOG_CONFIG`) | `~/.git-weeklog.json` |
| `--no-color` | disable ANSI colors | colors only on TTY |
| `--version` | print version and exit | — |

Exit codes: `0` success, `1` runtime error (not a git repo, git missing,
unreadable config), `2` bad arguments.

## Example output

Command:

```bash
python3 git-weeklog.py --repo remotion-opus-skill --since 90d --no-color
```

Output (real, copied from an actual run):

```text
git-weeklog — remotion-opus-skill  (2026-08-08 .. today)
11 commit(s) by 1 author(s): +10808/-417 lines

2026-10-06 — 8 commit(s), +2069/-115
  authors: direkturcrypto (8)
  hot files: cli/agent.ts (4), skill/remotion-opus/SKILL.md (3), cli/code.ts (3), prompts/agent.md (3), README.md (2)
  - 2026-10-06 Skill: chat-driven install flow (install from a repo link, ask for keys in chat, write .env) (direkturcrypto, +12/-1)
  - 2026-10-06 Skill: describe flexible length + code mode; document hermes/skills.sh install (direkturcrypto, +8/-5)
  - 2026-10-06 Captions: keep words/URLs unbroken but let lines wrap between them (direkturcrypto, +4/-3)
  - 2026-10-06 DNS fallback for API calls; sanitize resumed agent sessions (direkturcrypto, +46/-0)
  - 2026-10-06 Agent survives the gateway's 10-minute reply cut; balance check before code runs; reference screenshots (direkturcrypto, +89/-12)
  - 2026-10-06 Merge code mode (bespoke agent-built scenes) (direkturcrypto, +0/-0)
  - 2026-10-06 Code mode works end to end: agent loop builds bespoke scenes, budget guard, calibrated pacing (direkturcrypto, +124/-37)
  - 2026-10-06 WIP: code mode — bespoke scenes written by an Opus agent (not yet tested end to end) (direkturcrypto, +1786/-57)

2026-10-05 — 3 commit(s), +8739/-302
  authors: direkturcrypto (3)
  hot files: cli/pipeline.ts (3), prompts/builder.md (3), src/spec/schema.ts (3), src/widgets/agents.tsx (3), .env.example (2)
  - 2026-10-05 Three visual engines + creative-director step so films stop looking like one template (direkturcrypto, +1414/-294)
  - 2026-10-05 Polish widgets from Opus review feedback; save builder attempts (direkturcrypto, +14/-8)
  - 2026-10-05 Initial release: ros CLI + remotion-opus agent skill (direkturcrypto, +7311/-0)
```

The same period as JSON (`--group-by type --format json`) reports 11
commits, +10808/-417 lines, all under group `other` (that repo does not
use conventional-commit prefixes). A Markdown digest driven by a config
file (`--config`, group by author) is also verified in the test suite's
end-to-end runs.

## How it works

1. Settings merge: built-in defaults, then `~/.git-weeklog.json` (or
   `--config` / `GIT_WEEKLOG_CONFIG`), then CLI flags.
2. `since` accepts `7d`, `2w`, or `YYYY-MM-DD`; `until` is inclusive.
3. One `git log --numstat` call (list-form argv, no shell) with a
   machine-readable pretty format; output is parsed line by line into
   commit records with per-file insertions/deletions.
4. Commits are grouped by day, author, or conventional-commit type
   (`feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `style`, `build`,
   `ci`, `perf`, `revert`; anything else is `other`).
5. Each group reports commit count, authors, +/− lines, and the 5 most
   changed files; the chosen renderer prints human, JSON, or Markdown.

Structure: `git-weeklog.py` (single file, stdlib only), `test/` (unittest,
24 tests), `examples/git-weeklog.json` (sample config).

## Limitations

- Only local repositories: no GitHub API, no remote fetching.
- Binary files contribute no line counts (git reports `-` for them).
- Merge commits count like any other commit; their diff stats come from
  `git log --numstat` as usual.
- `--author` is git's own substring match on the author name/email.
- Very large histories are capped by `--max-commits` (default 200);
  raise it for full-history digests.
- Commit subjects are taken verbatim; no AI summarising is done.

## Development

```bash
python3 -m unittest discover -s test -q
```

## License

MIT

---
Ringkasan (Bahasa Indonesia): git-weeklog merangkum riwayat commit sebuah
repo git menjadi digest mingguan/harian yang siap dibaca — dikelompokkan per
hari, author, atau tipe commit, lengkap dengan jumlah baris berubah dan file
paling sering disentuh. Pengaturan default disimpan di `~/.git-weeklog.json`
dan bisa di-override lewat flag; output tersedia sebagai tabel manusia, JSON,
atau Markdown. Tool ini hanya membaca repo (tidak pernah mengubahnya) dan
tidak butuh dependensi apa pun selain Python dan git.
