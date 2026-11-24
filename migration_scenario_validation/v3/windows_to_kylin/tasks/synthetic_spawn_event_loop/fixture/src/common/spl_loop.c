/*
 * Shared loop: a registry of live process handles and one non-blocking run
 * pass.  Nothing here is platform specific.
 */
#include "spl.h"
#include "spl_platform.h"

#include <errno.h>
#include <stdlib.h>

struct spl_loop {
    struct spl_process **items;
    size_t count;
    size_t capacity;
};

spl_loop *spl_loop_new(void)
{
    spl_loop *loop = (spl_loop *)calloc(1, sizeof(*loop));
    return loop;
}

void spl_loop_free(spl_loop *loop)
{
    if (!loop) {
        return;
    }
    free(loop->items);
    free(loop);
}

void spl__register(spl_loop *loop, struct spl_process *process)
{
    if (!loop || !process) {
        return;
    }
    if (loop->count == loop->capacity) {
        size_t capacity = loop->capacity ? loop->capacity * 2 : 8;
        struct spl_process **items = (struct spl_process **)realloc(
            loop->items, capacity * sizeof(*items));
        if (!items) {
            return;
        }
        loop->items = items;
        loop->capacity = capacity;
    }
    loop->items[loop->count++] = process;
}

void spl__unregister(spl_loop *loop, struct spl_process *process)
{
    size_t i;

    if (!loop || !process) {
        return;
    }
    for (i = 0; i < loop->count; i++) {
        if (loop->items[i] == process) {
            loop->items[i] = loop->items[loop->count - 1];
            loop->count--;
            return;
        }
    }
}

int spl_loop_run(spl_loop *loop)
{
    size_t i;
    int delivered = 0;

    if (!loop) {
        return 0;
    }
    for (i = 0; i < loop->count;) {
        struct spl_process *process = loop->items[i];

        if (!process->active || process->closing) {
            i++;
            continue;
        }
        if (spl__reap(process)) {
            process->active = 0;
            delivered++;
            if (process->on_exit) {
                process->on_exit(process, process->exit_status,
                                 process->term_signal);
            }
        }
        i++;
    }
    return delivered;
}