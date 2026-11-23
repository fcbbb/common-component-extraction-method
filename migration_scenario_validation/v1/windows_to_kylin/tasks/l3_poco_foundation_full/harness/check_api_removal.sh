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
  --source-dir "$ROOT/work/Foundation/src/DirectoryIterator_UNIX.cpp" --source-dir "$ROOT/work/Foundation/src/Environment_UNIX.cpp" --source-dir "$ROOT/work/Foundation/src/Event_POSIX.cpp" --source-dir "$ROOT/work/Foundation/src/FileStream_POSIX.cpp" --source-dir "$ROOT/work/Foundation/src/File_UNIX.cpp" --source-dir "$ROOT/work/Foundation/src/Mutex_POSIX.cpp" --source-dir "$ROOT/work/Foundation/src/NamedEvent_UNIX.cpp" --source-dir "$ROOT/work/Foundation/src/NamedMutex_UNIX.cpp" --source-dir "$ROOT/work/Foundation/src/Path_UNIX.cpp" --source-dir "$ROOT/work/Foundation/src/PipeImpl_POSIX.cpp" --source-dir "$ROOT/work/Foundation/src/Process_UNIX.cpp" --source-dir "$ROOT/work/Foundation/src/RWLock_POSIX.cpp" --source-dir "$ROOT/work/Foundation/src/Semaphore_POSIX.cpp" --source-dir "$ROOT/work/Foundation/src/SharedLibrary_UNIX.cpp" --source-dir "$ROOT/work/Foundation/src/SharedMemory_POSIX.cpp" --source-dir "$ROOT/work/Foundation/src/Thread_POSIX.cpp" --source-dir "$ROOT/work/Foundation/src/Timezone_UNIX.cpp" \
  --exclude-glob '**/*_WIN32*' --exclude-glob '**/*_win32*' --exclude-glob '**/*w32*' --exclude-glob '**/*W32*' --exclude-glob '**/*_windows.c' --exclude-glob '**/*_windows.h' --exclude-glob '**/win32/**' --exclude-glob '**/Win32/**' --exclude-glob '**/win/**' --exclude-glob '**/Windows/**' --exclude-glob '**/windows/**' --exclude-glob '**/projects/Windows/**' --exclude-glob '**/winbuild/**' --symbol-regex '^(__imp_|CreateFileA|CreateFileW|ReadFile|WriteFile|WaitForSingleObject|WSAStartup|RegOpenKeyEx|RegCreateKeyEx|CoCreateInstance|LoadLibraryA|LoadLibraryW)' \
  --source-regex 'windows\.h|__declspec|_MSC_VER|#pragma comment|TCHAR\b|\bCreateFile\b|WaitForSingleObject|RegOpenKey|CoCreateInstance' \
  "$@"
