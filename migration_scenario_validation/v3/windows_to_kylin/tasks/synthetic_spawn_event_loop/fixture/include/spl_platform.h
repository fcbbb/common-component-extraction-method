#ifndef SPL_PLATFORM_H
#define SPL_PLATFORM_H

#include "spl.h"

/*
 * Platform layer behind the process surface.
 *
 * spl__reap is called by the shared loop: return 1 when the child was reaped
 * (exit_status and term_signal filled in), 0 when it is still running, and
 * never block.
 */
int spl__reap(struct spl_process *process);

void spl__register(spl_loop *loop, struct spl_process *process);
void spl__unregister(spl_loop *loop, struct spl_process *process);

#endif /* SPL_PLATFORM_H */