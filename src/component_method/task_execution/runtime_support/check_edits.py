"""Check edited repository files without running them (stdlib only)."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


def check_edits(repository: Path) -> list[str]:
    errors = []
    whitespace = subprocess.run(
        ["git", "diff", "--check", "HEAD"], cwd=repository, capture_output=True, text=True,
    )
    if whitespace.returncode:
        errors.append((whitespace.stdout + whitespace.stderr).strip() or "git diff --check failed")
    files = set()
    for arguments in (
        ["git", "diff", "--name-only", "-z", "HEAD", "--diff-filter=ACMR"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ):
        result = subprocess.run(arguments, cwd=repository, capture_output=True)
        if result.returncode:
            errors.append(result.stderr.decode("utf-8", errors="replace"))
        else:
            files.update(result.stdout.decode("utf-8", errors="strict").split("\0"))
    for name in sorted(files):
        path = Path(name)
        if not name or path.suffix != ".py" or path.parts[0] == ".components":
            continue
        try:
            compile((repository / path).read_bytes(), name, "exec")
        except (OSError, SyntaxError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path("/testbed"))
    parser.add_argument("--submit", action="store_true", help="Print the completion marker after checks pass")
    args = parser.parse_args()
    try:
        errors = check_edits(args.repository)
    except (OSError, ValueError) as exc:
        errors = [str(exc)]
    if errors:
        print("Submission check failed:\n" + "\n".join(errors) + "\nCorrect the edited files and check again.")
        return 1
    print("COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" if args.submit else "Edited files pass whitespace and Python syntax checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
