/*
 * Public self-test: the basic spawn and exit-callback contract.
 */
#include "spl.h"

#include <stdio.h>
#include <unistd.h>

static int failures;
static int callbacks;

#define CHECK(cond, msg)                                                     \
    do {                                                                     \
        if (!(cond)) {                                                       \
            fprintf(stderr, "selftest: %s (line %d)\n", (msg), __LINE__);     \
            failures++;                                                      \
        }                                                                    \
    } while (0)

static void on_exit(struct spl_process *process, int status, int signal)
{
    (void)process;
    (void)signal;
    callbacks++;
    CHECK(status == 3, "exit status");
}

int main(void)
{
    spl_loop *loop = spl_loop_new();
    struct spl_process process;
    struct spl_options options;
    char *const args[] = {(char *)"/bin/sh", (char *)"-c", (char *)"exit 3",
                          NULL};
    int waited = 0;

    CHECK(loop != NULL, "loop allocation");
    if (!loop) {
        return 1;
    }
    options.file = "/bin/sh";
    options.args = args;
    options.env = NULL;
    options.cwd = NULL;
    options.stdio[0].kind = SPL_STDIO_IGNORE;
    options.stdio[1].kind = SPL_STDIO_IGNORE;
    options.stdio[2].kind = SPL_STDIO_IGNORE;
    options.detached = 0;
    options.on_exit = on_exit;
    options.data = NULL;

    CHECK(spl_spawn(loop, &options, &process) == 0, "spawn");
    CHECK(spl_process_pid(&process) > 0, "pid");
    while (waited < 200) {
        spl_loop_run(loop);
        if (!process.active) {
            break;
        }
        usleep(10000);
        waited++;
    }
    CHECK(callbacks == 1, "exit callback");
    CHECK(spl_process_close(&process) == 0, "close");

    spl_loop_free(loop);
    if (failures) {
        fprintf(stderr, "SPL_SELFTEST=FAIL count=%d\n", failures);
        return 1;
    }
    printf("SPL_SELFTEST=PASS\n");
    return 0;
}