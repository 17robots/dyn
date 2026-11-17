# Agent evaluation

Seven small command-line tasks that measure how well an agent writes Dyn from
a written spec: how often its first attempt type-checks, how many repair
rounds it needs, and how many grader checks the finished tool passes. Most
checks exercise failure handling: missing, unreadable and invalid files,
read-only directories and a full device.

| Task | What it exercises |
| --- | --- |
| `config` | read and validate a JSON file |
| `concat` | stream many files into one |
| `summary` | list a directory, count lines, write a report |
| `jobs` | a command loop that carries on past failures |
| `move` | an irreversible step that must wait for a complete copy |
| `settings` | a fallback only when the first file is missing |
| `scan` | per-file failures inside a directory pass |

Each task has `TASK.md` (added to `PREAMBLE.md` to make the spec), a
`reference/main.dyn` that passes every check, and a grader in `graders.py`.

```sh
tools/agent-eval/eval.py --reference
tools/agent-eval/eval.py --agent 'claude -p --allowedTools Read,Write,Edit' --output report.json
```

The agent gets an empty workspace with `TASK.md` and `BRIEF.md` (`dyn guide
--brief`) and the prompt on standard input. It writes `main.dyn` without
running commands; the harness runs `dyn check` and sends the diagnostics back
for up to `--rounds` repair rounds, then builds and grades the tool. Record
`dyn version` and the agent's model with any number you quote. Run as a
non-root user on Linux.
