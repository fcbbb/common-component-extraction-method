/*
 * Hidden probe for the process-spawn backend.
 *
 * Compiled by harness/spl_probe.sh against the produced static library.  It
 * checks the child-side descriptor plan, environment and search-path rules,
 * detached sessions, signal dispositions, exit-status decoding, failed-spawn
 * cleanup and descriptor hygiene.
 */
#include "spl.h"

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static int failures;
static char g_dir[512];
static char g_helper[512];

#define CHECK(cond, ...)                                                     \
    do {                                                                     \
        if (!(cond)) {                                                       \
            fprintf(stderr, "deep: ");                                       \
            fprintf(stderr, __VA_ARGS__);                                    \
            fprintf(stderr, " (line %d)\n", __LINE__);                       \
            failures++;                                                      \
        }                                                                    \
    } while (0)

struct exit_record {
    int calls;
    int status;
    int signal;
};

static void record_exit(struct spl_process *process, int status, int signal)
{
    struct exit_record *record = (struct exit_record *)process->data;
    record->calls++;
    record->status = status;
    record->signal = signal;
}

static void init_options(struct spl_options *options, const char *file,
                         char *const *args, struct exit_record *record)
{
    memset(options, 0, sizeof(*options));
    options->file = file;
    options->args = args;
    options->env = NULL;
    options->cwd = NULL;
    options->stdio[0].kind = SPL_STDIO_IGNORE;
    options->stdio[1].kind = SPL_STDIO_IGNORE;
    options->stdio[2].kind = SPL_STDIO_IGNORE;
    options->detached = 0;
    options->on_exit = record ? record_exit : NULL;
    options->data = record;
}

static int run_until(spl_loop *loop, struct spl_process *process, int ms)
{
    int waited = 0;

    while (waited < ms) {
        spl_loop_run(loop);
        if (!process->active) {
            return 1;
        }
        usleep(10000);
        waited += 10;
    }
    return 0;
}

static ssize_t read_all(int fd, char *buffer, size_t capacity)
{
    size_t done = 0;

    while (done + 1 < capacity) {
        ssize_t got = read(fd, buffer + done, capacity - 1 - done);
        if (got < 0) {
            if (errno == EINTR) {
                continue;
            }
            break;
        }
        if (got == 0) {
            break;
        }
        done += (size_t)got;
    }
    buffer[done] = '\0';
    return (ssize_t)done;
}

static void read_path(const char *path, char *buffer, size_t capacity)
{
    int fd = open(path, O_RDONLY);
    buffer[0] = '\0';
    if (fd < 0) {
        return;
    }
    read_all(fd, buffer, capacity);
    close(fd);
}

static double seconds_since(const struct timespec *start)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (double)(now.tv_sec - start->tv_sec) +
           (double)(now.tv_nsec - start->tv_nsec) / 1e9;
}

/* Swapping two stdio slots whose sources are themselves low descriptors must
 * not let one slot's placement destroy the other's source. */
static void test_stdio_swap(void)
{
    char out_a[600];
    char out_b[600];
    char text_a[64];
    char text_b[64];
    int saved0 = dup(0);
    int saved1 = dup(1);
    int file_a;
    int file_b;
    struct spl_options options;
    struct spl_process process;
    struct exit_record record;
    spl_loop *loop;
    char *const args[] = {(char *)"splprobe", (char *)"split", NULL};

    snprintf(out_a, sizeof(out_a), "%s/swap-out.txt", g_dir);
    snprintf(out_b, sizeof(out_b), "%s/swap-err.txt", g_dir);

    close(0);
    close(1);
    file_a = open(out_a, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    file_b = open(out_b, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    CHECK(file_a == 0 && file_b == 1, "low-descriptor fixture (%d,%d)",
          file_a, file_b);

    memset(&record, 0, sizeof(record));
    init_options(&options, g_helper, args, &record);
    options.stdio[0].kind = SPL_STDIO_IGNORE;
    options.stdio[1].kind = SPL_STDIO_INHERIT;
    options.stdio[1].fd = file_a;
    options.stdio[2].kind = SPL_STDIO_INHERIT;
    options.stdio[2].fd = file_b;

    loop = spl_loop_new();
    CHECK(spl_spawn(loop, &options, &process) == 0, "swapped-stdio spawn");
    CHECK(run_until(loop, &process, 2000), "swapped-stdio exit");
    CHECK(spl_process_close(&process) == 0, "swapped-stdio close");

    /* Close the fixture descriptors while they still own fds 0/1, then put
     * the caller's originals back; closing them after the restore would
     * close the restored descriptors again. */
    close(file_a);
    close(file_b);
    dup2(saved0, 0);
    dup2(saved1, 1);
    close(saved0);
    close(saved1);
    read_path(out_a, text_a, sizeof(text_a));
    read_path(out_b, text_b, sizeof(text_b));
    CHECK(strcmp(text_a, "OUT\n") == 0, "stdout slot got '%s'", text_a);
    CHECK(strcmp(text_b, "ERR\n") == 0, "stderr slot got '%s'", text_b);
    spl_loop_free(loop);
}

/* An ignored stdin slot must be the null device even when the parent's own
 * descriptor 0 was closed before the spawn. */
static void test_ignored_stdin(void)
{
    char out[600];
    char text[128];
    int saved0 = dup(0);
    int file;
    struct spl_options options;
    struct spl_process process;
    struct exit_record record;
    spl_loop *loop;
    char *const args[] = {(char *)"splprobe", (char *)"stdin", NULL};

    snprintf(out, sizeof(out), "%s/ignored-in.txt", g_dir);
    close(0);
    file = open(out, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    CHECK(file == 0, "ignored-stdin fixture fd %d", file);

    memset(&record, 0, sizeof(record));
    init_options(&options, g_helper, args, &record);
    options.stdio[0].kind = SPL_STDIO_IGNORE;
    options.stdio[1].kind = SPL_STDIO_INHERIT;
    options.stdio[1].fd = file;
    options.stdio[2].kind = SPL_STDIO_IGNORE;

    loop = spl_loop_new();
    CHECK(spl_spawn(loop, &options, &process) == 0, "ignored-stdin spawn");
    CHECK(run_until(loop, &process, 2000), "ignored-stdin exit");
    CHECK(spl_process_close(&process) == 0, "ignored-stdin close");

    close(file);
    dup2(saved0, 0);
    close(saved0);

    read_path(out, text, sizeof(text));
    CHECK(strstr(text, "READ=0 ERRNO=0") != NULL,
          "ignored stdin was not the null device: '%s'", text);
    spl_loop_free(loop);
}

static void test_environment(void)
{
    char bindir[600];
    char linkpath[700];
    char out[600];
    char text[256];
    char *const args[] = {(char *)"splprobe", (char *)"env", (char *)"SPL_VALUE",
                          NULL};
    char *path_env[3] = {NULL, (char *)"SPL_VALUE=child", NULL};
    char path_entry[700];
    char *const empty_env[1] = {NULL};
    struct spl_options options;
    struct spl_process process;
    struct exit_record record;
    spl_loop *loop;
    int file;

    snprintf(bindir, sizeof(bindir), "%s/bin", g_dir);
    snprintf(linkpath, sizeof(linkpath), "%s/splprobe", bindir);
    snprintf(out, sizeof(out), "%s/env-out.txt", g_dir);
    mkdir(bindir, 0777);
    unlink(linkpath);
    CHECK(symlink(g_helper, linkpath) == 0, "search-path fixture");
    snprintf(path_entry, sizeof(path_entry), "PATH=%s", bindir);
    path_env[0] = path_entry;

    memset(&record, 0, sizeof(record));
    init_options(&options, "splprobe", args, &record);
    options.env = path_env;
    options.stdio[1].kind = SPL_STDIO_INHERIT;
    file = open(out, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    options.stdio[1].fd = file;

    loop = spl_loop_new();
    CHECK(spl_spawn(loop, &options, &process) == 0,
          "search path from the child environment");
    CHECK(run_until(loop, &process, 2000), "path env exit");
    CHECK(spl_process_close(&process) == 0, "path env close");
    close(file);
    read_path(out, text, sizeof(text));
    CHECK(strstr(text, "child") != NULL, "child environment value '%s'", text);

    /* An explicitly empty environment is not the same as inheriting one. */
    setenv("SPL_CANARY", "parent", 1);
    {
        char *const canary_args[] = {(char *)"splprobe", (char *)"env",
                                     (char *)"SPL_CANARY", NULL};
        file = open(out, O_WRONLY | O_CREAT | O_TRUNC, 0666);
        init_options(&options, g_helper, canary_args, &record);
        options.env = empty_env;
        options.stdio[1].kind = SPL_STDIO_INHERIT;
        options.stdio[1].fd = file;
        memset(&record, 0, sizeof(record));
        CHECK(spl_spawn(loop, &options, &process) == 0, "empty-environment spawn");
        CHECK(run_until(loop, &process, 2000), "empty-environment exit");
        CHECK(spl_process_close(&process) == 0, "empty-environment close");
        close(file);
        read_path(out, text, sizeof(text));
        CHECK(strstr(text, "UNSET") != NULL,
              "empty environment leaked the parent: '%s'", text);
    }
    spl_loop_free(loop);
}

static void test_cwd(void)
{
    char sub[600];
    char out[600];
    char text[1024];
    struct spl_options options;
    struct spl_process process;
    struct exit_record record;
    spl_loop *loop;
    int file;
    char *const args[] = {(char *)"splprobe", (char *)"cwd", NULL};

    snprintf(sub, sizeof(sub), "%s/subdir", g_dir);
    snprintf(out, sizeof(out), "%s/cwd-out.txt", g_dir);
    mkdir(sub, 0777);
    file = open(out, O_WRONLY | O_CREAT | O_TRUNC, 0666);

    memset(&record, 0, sizeof(record));
    init_options(&options, g_helper, args, &record);
    options.cwd = sub;
    options.stdio[1].kind = SPL_STDIO_INHERIT;
    options.stdio[1].fd = file;

    loop = spl_loop_new();
    CHECK(spl_spawn(loop, &options, &process) == 0, "cwd spawn");
    CHECK(run_until(loop, &process, 2000), "cwd exit");
    CHECK(spl_process_close(&process) == 0, "cwd close");
    close(file);
    read_path(out, text, sizeof(text));
    {
        size_t length = strlen(text);
        while (length > 0 && (text[length - 1] == '\n')) {
            text[--length] = '\0';
        }
        CHECK(strcmp(text, sub) == 0, "cwd was '%s', expected '%s'", text, sub);
    }
    spl_loop_free(loop);
}

static void test_detached(void)
{
    char out[600];
    char text[128];
    struct spl_options options;
    struct spl_process process;
    struct exit_record record;
    spl_loop *loop;
    int file;
    int pid;
    int sid;
    char *const pid_args[] = {(char *)"splprobe", (char *)"pid", NULL};
    char *const sleep_args[] = {(char *)"splprobe", (char *)"sleep", (char *)"10",
                                NULL};
    struct timespec start;

    snprintf(out, sizeof(out), "%s/detached.txt", g_dir);
    loop = spl_loop_new();

    file = open(out, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    memset(&record, 0, sizeof(record));
    init_options(&options, g_helper, pid_args, &record);
    options.detached = 1;
    options.stdio[1].kind = SPL_STDIO_INHERIT;
    options.stdio[1].fd = file;
    CHECK(spl_spawn(loop, &options, &process) == 0, "detached spawn");
    close(file);
    CHECK(run_until(loop, &process, 2000), "detached exit");
    pid = spl_process_pid(&process);
    CHECK(record.calls == 1, "detached callback count");
    CHECK(spl_process_close(&process) == 0, "detached close");
    read_path(out, text, sizeof(text));
    CHECK(sscanf(text, "%d %d", &pid, &sid) == 2, "detached output '%s'", text);
    CHECK(pid == spl_process_pid(&process), "reported pid");
    CHECK(sid == pid, "detached child session %d is not its pid %d", sid, pid);

    /* The loop pass must not block on a child that is still running. */
    memset(&record, 0, sizeof(record));
    init_options(&options, g_helper, sleep_args, &record);
    options.detached = 1;
    CHECK(spl_spawn(loop, &options, &process) == 0, "detached sleep spawn");
    clock_gettime(CLOCK_MONOTONIC, &start);
    spl_loop_run(loop);
    CHECK(seconds_since(&start) < 0.5,
          "loop pass blocked for %.3fs on a detached child",
          seconds_since(&start));
    CHECK(spl_kill(&process, SIGKILL) == 0, "detached kill");
    CHECK(run_until(loop, &process, 2000), "detached kill reap");
    CHECK(spl_process_close(&process) == 0, "detached sleep close");
    spl_loop_free(loop);
}

static void test_exit_status(void)
{
    char *const status_args[] = {(char *)"splprobe", (char *)"status",
                                 (char *)"7", NULL};
    char *const signal_args[] = {(char *)"splprobe", (char *)"raise", NULL};
    struct spl_options options;
    struct spl_process process;
    struct exit_record record;
    spl_loop *loop = spl_loop_new();

    memset(&record, 0, sizeof(record));
    init_options(&options, g_helper, status_args, &record);
    CHECK(spl_spawn(loop, &options, &process) == 0, "exit-status spawn");
    CHECK(run_until(loop, &process, 2000), "exit-status reap");
    CHECK(record.calls == 1, "exit-status callback count");
    CHECK(record.status == 7 && record.signal == 0,
          "exit status reported %d signal %d", record.status, record.signal);
    CHECK(spl_process_close(&process) == 0, "exit-status close");

    memset(&record, 0, sizeof(record));
    init_options(&options, g_helper, signal_args, &record);
    CHECK(spl_spawn(loop, &options, &process) == 0, "signal-death spawn");
    CHECK(run_until(loop, &process, 2000), "signal-death reap");
    CHECK(record.calls == 1, "signal-death callback count");
    CHECK(record.status == 0 && record.signal == SIGTERM,
          "signal death reported status %d signal %d", record.status,
          record.signal);
    CHECK(spl_process_close(&process) == 0, "signal-death close");
    spl_loop_free(loop);
}

static void test_failed_spawn(void)
{
    char noexec[600];
    struct spl_options options;
    struct spl_process process;
    spl_loop *loop = spl_loop_new();
    char *const args[] = {(char *)"missing-program", NULL};
    int status;
    pid_t left;
    int fd;

    init_options(&options, "/nonexistent/spl-probably-missing", args, NULL);
    {
        int rc = spl_spawn(loop, &options, &process);
        CHECK(rc == -ENOENT, "missing program error: %d (errno %d)", rc, errno);
    }
    CHECK(spl_process_pid(&process) == -1, "failed spawn pid %d",
          spl_process_pid(&process));
    CHECK(spl_process_close(&process) == 0, "failed spawn close");

    snprintf(noexec, sizeof(noexec), "%s/noexec", g_dir);
    fd = open(noexec, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd >= 0) {
        (void)!write(fd, "not a program\n", 14);
        close(fd);
        chmod(noexec, 0644);
    }
    init_options(&options, noexec, args, NULL);
    {
        int rc = spl_spawn(loop, &options, &process);
        CHECK(rc == -EACCES, "non-executable program error: %d (errno %d)", rc,
              errno);
    }
    CHECK(spl_process_close(&process) == 0, "non-executable close");

    /* An inherited slot must name a live descriptor.  The source rejected a
     * closed or invalid descriptor as an argument error before creating
     * anything, rather than letting the platform report it from the child. */
    {
        int rc;

        init_options(&options, g_helper, args, NULL);
        options.stdio[0].kind = SPL_STDIO_INHERIT;
        options.stdio[0].fd = -1;
        rc = spl_spawn(loop, &options, &process);
        CHECK(rc == -EINVAL,
              "invalid inherited descriptor error: %d (errno %d)", rc,
              errno);
        CHECK(spl_process_close(&process) == 0, "invalid descriptor close");
    }

    errno = 0;
    left = waitpid(-1, &status, WNOHANG);
    CHECK(left == -1 && errno == ECHILD,
          "a failed spawn left an unreaped child (pid %ld)", (long)left);
    spl_loop_free(loop);
}

static void test_kill(void)
{
    struct spl_options options;
    struct spl_process process;
    struct exit_record record;
    spl_loop *loop = spl_loop_new();
    struct sigaction ignore;
    struct sigaction previous;
    char *const sleep_args[] = {(char *)"splprobe", (char *)"sleep", (char *)"30",
                                NULL};

    /* The child must not inherit the parent's ignored termination signal. */
    memset(&ignore, 0, sizeof(ignore));
    ignore.sa_handler = SIG_IGN;
    sigemptyset(&ignore.sa_mask);
    sigaction(SIGTERM, &ignore, &previous);

    memset(&record, 0, sizeof(record));
    init_options(&options, g_helper, sleep_args, &record);
    CHECK(spl_spawn(loop, &options, &process) == 0, "kill spawn");
    sigaction(SIGTERM, &previous, NULL);

    CHECK(spl_kill(&process, 999) == -EINVAL, "invalid signal accepted");
    CHECK(spl_kill(&process, 0) == 0, "liveness probe on a running child");
    CHECK(spl_kill(&process, SIGTERM) == 0, "termination signal");
    if (!run_until(loop, &process, 3000)) {
        CHECK(0, "child ignored a termination signal reset in the child");
        CHECK(spl_kill(&process, SIGKILL) == 0, "kill escalation");
        (void)run_until(loop, &process, 2000);
    } else {
        CHECK(record.calls == 1, "killed child callback count");
        CHECK(record.status == 0 && record.signal == SIGTERM,
              "killed child reported status %d signal %d", record.status,
              record.signal);
    }
    CHECK(spl_kill(&process, 0) == -ESRCH, "liveness probe after the reap");
    CHECK(spl_process_close(&process) == 0, "kill close");
    spl_loop_free(loop);
}

static void test_fd_hygiene(void)
{
    struct spl_options options;
    struct spl_process process;
    struct exit_record record;
    spl_loop *loop = spl_loop_new();
    char buffer[1024];
    char *line;
    int parent_fd;
    int extras = 0;
    char *const args[] = {(char *)"splprobe", (char *)"fds", NULL};

    memset(&record, 0, sizeof(record));
    init_options(&options, g_helper, args, &record);
    options.stdio[1].kind = SPL_STDIO_CREATE;
    CHECK(spl_spawn(loop, &options, &process) == 0, "descriptor-hygiene spawn");
    parent_fd = options.stdio[1].fd;
    CHECK(parent_fd >= 0, "created stdio descriptor");
    read_all(parent_fd, buffer, sizeof(buffer));
    CHECK(run_until(loop, &process, 2000), "descriptor-hygiene exit");
    close(parent_fd);
    CHECK(spl_process_close(&process) == 0, "descriptor-hygiene close");

    line = strtok(buffer, "\n");
    while (line) {
        if (strncmp(line, "FD ", 3) == 0) {
            int number = atoi(line + 3);
            if (number > 2) {
                extras++;
            }
        }
        line = strtok(NULL, "\n");
    }
    /* The listing tool itself holds one descriptor on /proc/self/fd; nothing
     * else may have crossed the exec. */
    CHECK(extras == 1, "child inherited %d unexpected descriptor(s)", extras);
    spl_loop_free(loop);
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: deep_spawn <scratch-dir> <helper-path>\n");
        return 2;
    }
    snprintf(g_dir, sizeof(g_dir), "%s", argv[1]);
    snprintf(g_helper, sizeof(g_helper), "%s", argv[2]);
    mkdir(g_dir, 0777);

    test_stdio_swap();
    test_ignored_stdin();
    test_environment();
    test_cwd();
    test_detached();
    test_exit_status();
    test_failed_spawn();
    test_kill();
    test_fd_hygiene();

    if (failures) {
        fprintf(stderr, "SPL_DEEP=FAIL count=%d\n", failures);
        return 1;
    }
    printf("SPL_DEEP=PASS\n");
    return 0;
}