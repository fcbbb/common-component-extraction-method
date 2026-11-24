/*
 * POSIX process-spawn backend for the runtime.
 *
 * Rebuilds the Windows handle-based spawn on fork/exec: descriptor plans are
 * resolved in the child, child-side failures travel back over a close-on-exec
 * error channel, and the shared loop reaps statuses without blocking.
 */
#include "spl.h"
#include "spl_platform.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static void child_fail(int fd, int error)
{
    ssize_t written;

    do {
        written = write(fd, &error, sizeof(error));
    } while (written < 0 && errno == EINTR);
    _exit(127);
}

static const char *child_path(char *const *envp)
{
    for (; *envp; envp++) {
        if (strncmp(*envp, "PATH=", 5) == 0) {
            return *envp + 5;
        }
    }
    /* The platform default search path, used when the environment the child
     * will receive has no PATH entry. */
    return "/usr/local/bin:/usr/bin:/bin";
}

static void child_exec(const char *file, char *const *args, char *const *envp,
                       int error_fd)
{
    char candidate[PATH_MAX];
    const char *path;
    const char *cursor;
    int denied = 0;
    int last = ENOENT;
    int sig;
    sigset_t empty;

    /* A child starts with default dispositions and an empty mask; a signal
     * the parent ignored or blocked must not follow the child through exec. */
    for (sig = 1; sig < NSIG; sig++) {
        if (sig != SIGKILL && sig != SIGSTOP) {
            signal(sig, SIG_DFL);
        }
    }
    sigemptyset(&empty);
    sigprocmask(SIG_SETMASK, &empty, NULL);

    if (strchr(file, '/')) {
        execve(file, args, envp);
        child_fail(error_fd, errno);
    }

    path = child_path(envp);
    cursor = path;
    for (;;) {
        const char *end = strchr(cursor, ':');
        size_t length = end ? (size_t)(end - cursor) : strlen(cursor);
        int needed;

        if (length == 0) {
            needed = snprintf(candidate, sizeof(candidate), "%s", file);
        } else {
            needed = snprintf(candidate, sizeof(candidate), "%.*s/%s",
                              (int)length, cursor, file);
        }
        if (needed < 0 || (size_t)needed >= sizeof(candidate)) {
            last = ENAMETOOLONG;
        } else {
            execve(candidate, args, envp);
            if (errno == EACCES) {
                denied = 1;
            }
            last = errno;
        }
        if (!end) {
            break;
        }
        cursor = end + 1;
    }
    child_fail(error_fd, denied ? EACCES : last);
}

static void child_stdio(int source[3], int error_fd)
{
    int i;

    /* Move every source that would collide with a stdio slot out of the way
     * before any slot is written, so swapped slots cannot clobber each other. */
    for (i = 0; i < 3; i++) {
        if (source[i] >= 0 && source[i] < 3 && source[i] != i) {
            int moved = fcntl(source[i], F_DUPFD_CLOEXEC, 3);
            if (moved < 0) {
                child_fail(error_fd, errno);
            }
            source[i] = moved;
        }
    }

    for (i = 0; i < 3; i++) {
        if (source[i] >= 0) {
            if (source[i] != i && dup2(source[i], i) < 0) {
                child_fail(error_fd, errno);
            }
        } else {
            int null_fd = open("/dev/null", i == 0 ? O_RDONLY : O_WRONLY);
            if (null_fd < 0) {
                child_fail(error_fd, errno);
            }
            if (null_fd != i) {
                if (dup2(null_fd, i) < 0) {
                    child_fail(error_fd, errno);
                }
                close(null_fd);
            }
        }
    }

    for (i = 0; i < 3; i++) {
        int flags = fcntl(i, F_GETFL);
        if (flags >= 0 && (flags & O_NONBLOCK)) {
            fcntl(i, F_SETFL, flags & ~O_NONBLOCK);
        }
        fcntl(i, F_SETFD, 0);
    }
    for (i = 0; i < 3; i++) {
        if (source[i] > 2) {
            close(source[i]);
        }
    }
}

int spl_spawn(spl_loop *loop, struct spl_options *options,
              struct spl_process *process)
{
    int source[3] = {-1, -1, -1};
    int child_end[3] = {-1, -1, -1};
    int error_pipe[2] = {-1, -1};
    int saved = 0;
    int i;
    pid_t pid;

    if (!loop || !options || !process) {
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

    if (!options->file || !options->args || !options->args[0]) {
        return -EINVAL;
    }
    for (i = 0; i < 3; i++) {
        switch (options->stdio[i].kind) {
        case SPL_STDIO_IGNORE:
            source[i] = -1;
            break;
        case SPL_STDIO_INHERIT:
            if (options->stdio[i].fd < 0) {
                return -EINVAL;
            }
            source[i] = options->stdio[i].fd;
            break;
        case SPL_STDIO_CREATE: {
            int pair[2];
            if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, pair) < 0) {
                saved = errno;
                goto fail;
            }
            source[i] = pair[1];
            child_end[i] = pair[1];
            options->stdio[i].fd = pair[0];
            break;
        }
        default:
            return -EINVAL;
        }
    }
    if (pipe2(error_pipe, O_CLOEXEC) < 0) {
        saved = errno;
        goto fail;
    }
    fflush(NULL);
    pid = fork();
    if (pid < 0) {
        saved = errno;
        goto fail;
    }
    if (pid == 0) {
        close(error_pipe[0]);
        /* The failure channel must survive the stdio plan.  With the caller's
         * low descriptors closed, pipe2 can hand us 0-2, which child_stdio
         * would overwrite; move the write end above the stdio range first. */
        if (error_pipe[1] < 3) {
            int moved = fcntl(error_pipe[1], F_DUPFD_CLOEXEC, 3);
            if (moved < 0) {
                _exit(127);
            }
            close(error_pipe[1]);
            error_pipe[1] = moved;
        }
        for (i = 0; i < 3; i++) {
            if (child_end[i] >= 0) {
                close(options->stdio[i].fd); /* parent end */
            }
        }
        if (options->detached && setsid() < 0) {
            child_fail(error_pipe[1], errno);
        }
        if (options->cwd && chdir(options->cwd) < 0) {
            child_fail(error_pipe[1], errno);
        }
        child_stdio(source, error_pipe[1]);
        child_exec(options->file, options->args,
                   options->env ? options->env : environ, error_pipe[1]);
        child_fail(error_pipe[1], errno);
    }

    close(error_pipe[1]);
    error_pipe[1] = -1;
    for (i = 0; i < 3; i++) {
        if (child_end[i] >= 0) {
            close(child_end[i]);
            child_end[i] = -1;
        }
    }
    {
        int child_error = 0;
        ssize_t got;
        do {
            got = read(error_pipe[0], &child_error, sizeof(child_error));
        } while (got < 0 && errno == EINTR);
        close(error_pipe[0]);
        error_pipe[0] = -1;
        if (got > 0) {
            int status;
            while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
            }
            return -child_error;
        }
    }

    process->pid = (int)pid;
    process->active = 1;
    spl__register(loop, process);
    return 0;

fail:
    for (i = 0; i < 3; i++) {
        if (child_end[i] >= 0) {
            close(child_end[i]);
        }
        if (options->stdio[i].kind == SPL_STDIO_CREATE &&
            options->stdio[i].fd >= 0) {
            close(options->stdio[i].fd);
            options->stdio[i].fd = -1;
        }
    }
    if (error_pipe[0] >= 0) {
        close(error_pipe[0]);
    }
    if (error_pipe[1] >= 0) {
        close(error_pipe[1]);
    }
    return -(saved ? saved : EIO);
}

int spl__reap(struct spl_process *process)
{
    int status;
    pid_t got;

    if (!process || process->pid <= 0 || !process->active) {
        return 0;
    }
    got = waitpid(process->pid, &status, WNOHANG);
    if (got == 0) {
        return 0;
    }
    if (got < 0) {
        return errno == ECHILD ? 1 : 0;
    }
    process->exit_status = 0;
    process->term_signal = 0;
    if (WIFEXITED(status)) {
        process->exit_status = WEXITSTATUS(status);
    } else if (WIFSIGNALED(status)) {
        process->term_signal = WTERMSIG(status);
    }
    return 1;
}

int spl_kill(struct spl_process *process, int signo)
{
    if (!process) {
        return -EINVAL;
    }
    if (signo < 0 || signo >= NSIG) {
        return -EINVAL;
    }
    if (process->pid <= 0 || !process->active) {
        return -ESRCH;
    }
    if (kill(process->pid, signo) < 0) {
        return -errno;
    }
    return 0;
}

int spl_process_close(struct spl_process *process)
{
    if (!process) {
        return -EINVAL;
    }
    if (process->active && process->loop) {
        spl__unregister(process->loop, process);
    }
    process->active = 0;
    process->closing = 1;
    return 0;
}

int spl_process_pid(const struct spl_process *process)
{
    return process ? process->pid : -1;
}