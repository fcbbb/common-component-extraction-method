#ifndef SPL_H
#define SPL_H

#include <stddef.h>

/*
 * Minimal process-spawning surface of the runtime.
 *
 * A successful spawn returns 0; a failure returns -(errno).  A process handle
 * is caller-allocated, remains closable after a failed spawn, and delivers its
 * exit callback from the loop's single run pass.
 *
 * stdio slots are expressed from the child's point of view:
 *   SPL_STDIO_IGNORE   the child gets the null device on that slot;
 *   SPL_STDIO_INHERIT  fd is the caller's descriptor; it is remapped onto the
 *                      slot in the child and stays owned by the caller;
 *   SPL_STDIO_CREATE   a connected pair is created; the child end goes to the
 *                      slot and the parent end is stored in fd for the caller.
 */

typedef struct spl_loop spl_loop;

enum spl_stdio_kind {
    SPL_STDIO_IGNORE = 0,
    SPL_STDIO_INHERIT = 1,
    SPL_STDIO_CREATE = 2
};

struct spl_stdio {
    int kind;
    int fd;
};

struct spl_process;

typedef void (*spl_exit_cb)(struct spl_process *proc, int exit_status,
                            int term_signal);

struct spl_options {
    const char *file;
    char *const *args;
    char *const *env;      /* NULL: inherit the parent environment;
                              env[0] == NULL: an explicitly empty environment */
    const char *cwd;
    struct spl_stdio stdio[3];
    int detached;
    spl_exit_cb on_exit;
    void *data;
};

struct spl_process {
    int pid;               /* -1 unless a spawn succeeded */
    int active;
    int closing;
    int exit_status;
    int term_signal;
    spl_loop *loop;
    spl_exit_cb on_exit;
    void *data;
    void *platform;
};

spl_loop *spl_loop_new(void);
void spl_loop_free(spl_loop *loop);

/* 0 on success, -(errno) on failure. */
int spl_spawn(spl_loop *loop, struct spl_options *options,
              struct spl_process *process);

/* 0 on success, -(errno) on failure; signal 0 is a liveness probe. */
int spl_kill(struct spl_process *process, int signo);
int spl_process_close(struct spl_process *process);
int spl_process_pid(const struct spl_process *process);

/* One non-blocking pass over the registered children: reaps the exited ones
 * and runs their callbacks.  Returns the number of callbacks delivered. */
int spl_loop_run(spl_loop *loop);

#endif /* SPL_H */