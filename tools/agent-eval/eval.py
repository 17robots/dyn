#!/usr/bin/env python3
"""Measures how well an agent writes Dyn: first-try success and repair rounds.

Each task in tasks/ is a small command-line tool with a written spec
(PREAMBLE.md + TASK.md), a reference solution and a grader in graders.py.

  eval.py --reference
      Builds and grades the reference solutions. Every check must pass; the
      test suite runs this so the tasks and graders stay correct.

  eval.py --agent 'COMMAND' [--task NAME]... [--rounds N] [--output report.json]
      For each task, makes an empty workspace holding TASK.md and BRIEF.md
      (`dyn guide --brief`) and runs COMMAND there through the shell, with the
      prompt on standard input. The agent writes main.dyn and must not run
      commands. The harness runs `dyn check`; while it fails, it sends the
      diagnostics back as the next round, up to --rounds. Then it builds the
      tool and grades it. For example:
        eval.py --agent 'claude -p --allowedTools Read,Write,Edit'

The report counts, per task: whether round 1 checked clean (first try), the
rounds it took to check clean, and grader checks passed. Grading needs a
non-root user: the fixtures include unreadable files."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import graders  # noqa: E402

DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
FIRST_PROMPT = """Read TASK.md and BRIEF.md in this directory, then write the tool as main.dyn here.
Do not run any commands: the harness checks and builds main.dyn for you."""
REPAIR_PROMPT = """`dyn check` reports these problems in main.dyn:

{diagnostics}
Fix main.dyn. Do not run any commands."""


def tasks(selected):
    names = sorted(path.name for path in (HERE / 'tasks').iterdir() if path.is_dir())
    unknown = set(selected) - set(names)
    if unknown:
        raise SystemExit(f'unknown task: {", ".join(sorted(unknown))}')
    return [name for name in names if not selected or name in selected]


def spec(name):
    return (HERE / 'PREAMBLE.md').read_text() + '\n' + (HERE / 'tasks' / name / 'TASK.md').read_text()


def grade(name, project, work):
    binary = work / f'{name}-tool'
    built = subprocess.run([DYN, 'build', str(project), '--quiet', '--output', str(binary)],
                           capture_output=True, text=True, timeout=300)
    if built.returncode:
        return None, built.stderr
    root = work / f'{name}-fixtures'
    graders.fixtures(root)
    results = []
    graders.GRADERS[name](binary, root, results)
    subprocess.run(['chmod', '-R', 'u+rwx', str(root)], check=False)
    return results, ''


def reference(names):
    failed = 0
    with tempfile.TemporaryDirectory(prefix='dyn-agent-eval-') as temporary:
        for name in names:
            results, error = grade(name, HERE / 'tasks' / name / 'reference', Path(temporary))
            if results is None:
                print(f'FAIL {name}: reference does not build\n{error}')
                failed += 1
                continue
            for check, passed, detail in results:
                if not passed:
                    print(f'FAIL {name}: {check}: {detail}')
                    failed += 1
            print(f'{name}: {sum(passed for _, passed, _ in results)}/{len(results)} checks')
    if failed:
        raise SystemExit(1)
    print(f'PASS agent evaluation references: {len(names)} tasks, every check')


def agent(names, command, rounds, output, keep):
    brief = subprocess.run([DYN, 'guide', '--brief'], capture_output=True, text=True, check=True).stdout
    report = []
    with tempfile.TemporaryDirectory(prefix='dyn-agent-eval-') as temporary:
        work = Path(keep).resolve() if keep else Path(temporary)
        work.mkdir(parents=True, exist_ok=True)
        for name in names:
            project = work / name
            if project.exists():
                shutil.rmtree(project)
            project.mkdir()
            (project / 'TASK.md').write_text(spec(name))
            (project / 'BRIEF.md').write_text(brief)
            prompt = FIRST_PROMPT
            entry = {'task': name, 'first_try': False, 'rounds': None, 'checks': 0, 'total': 0}
            for round_number in range(1, rounds + 1):
                subprocess.run(command, shell=True, cwd=project, input=prompt, text=True, timeout=1800,
                               stdout=subprocess.DEVNULL)
                if not (project / 'main.dyn').exists():
                    prompt = 'main.dyn does not exist yet. ' + FIRST_PROMPT
                    continue
                checked = subprocess.run([DYN, 'check', str(project)], capture_output=True, text=True, timeout=300)
                if checked.returncode == 0:
                    entry['rounds'] = round_number
                    entry['first_try'] = round_number == 1
                    break
                prompt = REPAIR_PROMPT.format(diagnostics=checked.stderr)
                (project / f'round-{round_number}.diagnostics').write_text(checked.stderr)
            if entry['rounds'] is not None:
                results, _ = grade(name, project, work)
                if results is not None:
                    entry['checks'] = sum(passed for _, passed, _ in results)
                    entry['total'] = len(results)
                    entry['failed'] = [check for check, passed, _ in results if not passed]
            report.append(entry)
            print(f"{name:9} first try {'yes' if entry['first_try'] else 'no ':3}  rounds {entry['rounds'] or '-'}"
                  f"  checks {entry['checks']}/{entry['total']}", flush=True)
    first = sum(entry['first_try'] for entry in report)
    clean = [entry['rounds'] for entry in report if entry['rounds']]
    checks = sum(entry['checks'] for entry in report)
    total = sum(entry['total'] for entry in report)
    print(f'first try {first}/{len(report)}, checked clean {len(clean)}/{len(report)}, '
          f'mean rounds {sum(clean) / len(clean) if clean else 0:.2f}, grader checks {checks}/{total}')
    if output:
        Path(output).write_text(json.dumps({'dyn': subprocess.run([DYN, 'version'], capture_output=True, text=True).stdout.strip(),
                                            'command': command, 'rounds': rounds, 'tasks': report}, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--reference', action='store_true', help='grade the reference solutions')
    mode.add_argument('--agent', metavar='COMMAND', help='shell command that runs the agent in the workspace')
    parser.add_argument('--task', action='append', default=[], help='run only this task (repeatable)')
    parser.add_argument('--rounds', type=int, default=3, help='repair rounds allowed (default 3)')
    parser.add_argument('--output', help='write the report as JSON')
    parser.add_argument('--keep', metavar='DIR', help='keep each workspace and its diagnostics under DIR')
    arguments = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit('run as a non-root user: the fixtures include unreadable files')
    names = tasks(arguments.task)
    if arguments.reference:
        reference(names)
    else:
        agent(names, arguments.agent, arguments.rounds, arguments.output, arguments.keep)


if __name__ == '__main__':
    main()
