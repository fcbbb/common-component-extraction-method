#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SHARED=""
d="$ROOT"
while [ "$d" != "/" ]; do
  if [ -f "$d/shared/harness/api_removal.py" ]; then
    SHARED="$d/shared/harness/api_removal.py"
    break
  fi
  d="$(dirname "$d")"
done
if [ -z "$SHARED" ]; then
  echo "shared/harness/api_removal.py not found above $ROOT" >&2
  exit 2
fi
exec python3 "$SHARED" \
  --source-dir "$ROOT/work/src/os/unix/ngx_process.c" \
  --source-dir "$ROOT/work/src/os/unix/ngx_process_cycle.c" \
  --source-dir "$ROOT/work/src/os/unix/ngx_channel.c" \
  --source-dir "$ROOT/work/src/os/unix/ngx_daemon.c" \
  --exclude-glob '**/*_WIN32*' --exclude-glob '**/*_win32*' --exclude-glob '**/*w32*' --exclude-glob '**/*W32*' --exclude-glob '**/*_windows.c' --exclude-glob '**/*_windows.h' --exclude-glob '**/win32/**' --exclude-glob '**/Win32/**' --exclude-glob '**/win/**' --exclude-glob '**/Windows/**' --exclude-glob '**/windows/**' --exclude-glob '**/projects/Windows/**' --exclude-glob '**/winbuild/**' \
  --symbol-regex '^(__imp_|CreateProcessA|CreateProcessW|CreatePipe|TerminateProcess|WaitForSingleObject|GetExitCodeProcess|ShellExecuteA|ShellExecuteW|DuplicateHandle|SetHandleInformation|RegOpenKeyEx|RegCreateKeyEx|CreateEventA|CreateEventW)' \
  --source-regex 'windows\.h|__declspec|_MSC_VER|#pragma comment|TCHAR\b|CreateProcess|CreatePipe|TerminateProcess|WaitForSingleObject|GetExitCodeProcess|DuplicateHandle|SetHandleInformation|RegOpenKey|CreateEvent' \
  "$@"