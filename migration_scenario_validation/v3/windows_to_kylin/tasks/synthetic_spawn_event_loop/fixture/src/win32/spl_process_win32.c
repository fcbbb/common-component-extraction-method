/*
 * Windows reference implementation of the process-spawn backend.
 *
 * Only compiled when CMake sees WIN32.  Kept in the snapshot as the reference
 * for the target-platform implementation.
 */
#include "spl.h"
#include "spl_platform.h"

#include <windows.h>
#include <stdlib.h>
#include <string.h>

struct win_platform {
    HANDLE process;
};

static void join_arguments(char *const *args, char *line, size_t capacity)
{
    size_t used = 0;
    size_t i;

    line[0] = '\0';
    for (i = 0; args[i] && used + 1 < capacity; i++) {
        int needed = snprintf(line + used, capacity - used, "%s%s",
                              i ? " " : "", args[i]);
        if (needed < 0) {
            break;
        }
        used += (size_t)needed;
    }
}

int spl_spawn(spl_loop *loop, struct spl_options *options,
              struct spl_process *process)
{
    STARTUPINFOA startup;
    PROCESS_INFORMATION info;
    struct win_platform *platform;
    SECURITY_ATTRIBUTES security;
    char command[4096];
    int i;

    if (!loop || !options || !process || !options->file ||
        !options->args || !options->args[0]) {
        return -EINVAL;
    }
    process->pid = -1;
    process->active = 0;
    process->closing = 0;
    process->exit_status = 0;
    process->term_signal = 0;
    process->loop = loop;
    process->on_exit = options->on_exit;
    process->data = options->data;

    memset(&startup, 0, sizeof(startup));
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    security.nLength = sizeof(security);
    security.lpSecurityDescriptor = NULL;
    security.bInheritHandle = TRUE;

    for (i = 0; i < 3; i++) {
        if (options->stdio[i].kind == SPL_STDIO_IGNORE) {
            HANDLE null_handle = CreateFileA("NUL", GENERIC_READ | GENERIC_WRITE,
                                             FILE_SHARE_READ | FILE_SHARE_WRITE,
                                             &security, OPEN_EXISTING,
                                             FILE_ATTRIBUTE_NORMAL, NULL);
            if (null_handle == INVALID_HANDLE_VALUE) {
                return -EINVAL;
            }
            if (i == 0) {
                startup.hStdInput = null_handle;
            } else if (i == 1) {
                startup.hStdOutput = null_handle;
            } else {
                startup.hStdError = null_handle;
            }
        } else if (options->stdio[i].kind == SPL_STDIO_INHERIT) {
            HANDLE handle = (HANDLE)(intptr_t)options->stdio[i].fd;
            if (i == 0) {
                startup.hStdInput = handle;
            } else if (i == 1) {
                startup.hStdOutput = handle;
            } else {
                startup.hStdError = handle;
            }
        } else if (options->stdio[i].kind == SPL_STDIO_CREATE) {
            HANDLE read_end = INVALID_HANDLE_VALUE;
            HANDLE write_end = INVALID_HANDLE_VALUE;
            if (!CreatePipe(&read_end, &write_end, &security, 0)) {
                return -EINVAL;
            }
            SetHandleInformation(
                i == 0 ? write_end : read_end, HANDLE_FLAG_INHERIT, 0);
            options->stdio[i].fd = (int)(intptr_t)(i == 0 ? write_end : read_end);
            if (i == 0) {
                startup.hStdInput = read_end;
            } else if (i == 1) {
                startup.hStdOutput = write_end;
            } else {
                startup.hStdError = write_end;
            }
        }
    }

    join_arguments(options->args, command, sizeof(command));
    if (!CreateProcessA(options->file, command, NULL, NULL, TRUE,
                        options->detached ? DETACHED_PROCESS : 0,
                        (LPVOID)options->env, options->cwd, &startup, &info)) {
        return -(int)GetLastError();
    }
    CloseHandle(info.hThread);
    platform = (struct win_platform *)calloc(1, sizeof(*platform));
    if (!platform) {
        TerminateProcess(info.hProcess, 1);
        CloseHandle(info.hProcess);
        return -ENOMEM;
    }
    platform->process = info.hProcess;
    process->platform = platform;
    process->pid = (int)info.dwProcessId;
    process->active = 1;
    spl__register(loop, process);
    return 0;
}

int spl__reap(struct spl_process *process)
{
    struct win_platform *platform;
    DWORD code = 0;

    if (!process || !process->active || !process->platform) {
        return 0;
    }
    platform = (struct win_platform *)process->platform;
    if (WaitForSingleObject(platform->process, 0) != WAIT_OBJECT_0) {
        return 0;
    }
    GetExitCodeProcess(platform->process, &code);
    process->exit_status = (int)code;
    process->term_signal = 0;
    return 1;
}

int spl_kill(struct spl_process *process, int signo)
{
    struct win_platform *platform;

    if (!process || signo < 0 || signo >= NSIG) {
        return -EINVAL;
    }
    if (!process->active || !process->platform) {
        return -ESRCH;
    }
    platform = (struct win_platform *)process->platform;
    if (signo == 0) {
        return 0;
    }
    return TerminateProcess(platform->process, (UINT)signo) ? 0 : -EINVAL;
}

int spl_process_close(struct spl_process *process)
{
    struct win_platform *platform;

    if (!process) {
        return -EINVAL;
    }
    if (process->active && process->loop) {
        spl__unregister(process->loop, process);
    }
    platform = (struct win_platform *)process->platform;
    if (platform) {
        CloseHandle(platform->process);
        free(platform);
        process->platform = NULL;
    }
    process->active = 0;
    process->closing = 1;
    return 0;
}

int spl_process_pid(const struct spl_process *process)
{
    return process ? process->pid : -1;
}