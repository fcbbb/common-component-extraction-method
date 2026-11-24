/*
 * POSIX backend for the runtime's threading surface.
 *
 * The public types in thr.h are caller-allocated opaque storage; each one is
 * large enough and aligned enough for the native object, which is initialised
 * in place.  Error codes are translated into the public THR_* set instead of
 * being reported as errno.
 */
#define _GNU_SOURCE
#include "thr.h"

#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <semaphore.h>
#include <string.h>
#include <time.h>

typedef char thr_check_mutex_size
    [(sizeof(pthread_mutex_t) <= sizeof(thr_mutex_t)) ? 1 : -1];
typedef char thr_check_rwlock_size
    [(sizeof(pthread_rwlock_t) <= sizeof(thr_rwlock_t)) ? 1 : -1];
typedef char thr_check_sem_size
    [(sizeof(sem_t) <= sizeof(thr_sem_t)) ? 1 : -1];
typedef char thr_check_cond_size
    [(sizeof(pthread_cond_t) <= sizeof(thr_cond_t)) ? 1 : -1];
typedef char thr_check_once_size
    [(sizeof(pthread_once_t) <= sizeof(thr_once_t)) ? 1 : -1];

#define MUTEX(m) ((pthread_mutex_t *)(void *)(m))
#define RWLOCK(l) ((pthread_rwlock_t *)(void *)(l))
#define SEM(s) ((sem_t *)(void *)(s))
#define COND(c) ((pthread_cond_t *)(void *)(c))
#define ONCE(o) ((pthread_once_t *)(void *)(o))

static int map_error(int rc)
{
    switch (rc) {
    case 0:
        return THR_OK;
    case EBUSY:
        return THR_BUSY;
    case EAGAIN:
        return THR_AGAIN;
    case ETIMEDOUT:
        return THR_TIMEDOUT;
    case ENOMEM:
        return THR_NOMEM;
    case ENOSYS:
    case EOPNOTSUPP:
        return THR_NOSYS;
    default:
        return THR_INVAL;
    }
}

/* ------------------------------------------------------------------ */
/* Threads                                                             */
/* ------------------------------------------------------------------ */

int thr_thread_create(thr_thread_t *thread, void *(*entry)(void *), void *arg,
                      size_t stack_size)
{
    pthread_attr_t attr;
    pthread_t tid;
    int rc;

    if (!thread || !entry) {
        return THR_INVAL;
    }
    if (pthread_attr_init(&attr) != 0) {
        return THR_INVAL;
    }
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_JOINABLE);
    if (stack_size > 0) {
        /* The request is honoured as a floor: tiny values are raised to a
         * workable minimum and the size is rounded up to a page. */
        size_t pages = 4096;
        size_t minimum = 64u * 1024u;
        if (stack_size < minimum) {
            stack_size = minimum;
        }
        if (stack_size > (size_t)-1 - (pages - 1)) {
            pthread_attr_destroy(&attr);
            return THR_INVAL;
        }
        stack_size = (stack_size + pages - 1) & ~(pages - 1);
        if (pthread_attr_setstacksize(&attr, stack_size) != 0) {
            pthread_attr_destroy(&attr);
            return THR_INVAL;
        }
    }
    rc = pthread_create(&tid, &attr, entry, arg);
    pthread_attr_destroy(&attr);
    if (rc != 0) {
        return map_error(rc);
    }
    *thread = (thr_thread_t)tid;
    return THR_OK;
}

int thr_thread_join(thr_thread_t *thread)
{
    int rc;

    if (!thread || *thread == 0) {
        return THR_INVAL;
    }
    rc = pthread_join((pthread_t)*thread, NULL);
    *thread = 0;
    return map_error(rc);
}

thr_thread_t thr_thread_self(void)
{
    return (thr_thread_t)pthread_self();
}

int thr_thread_equal(thr_thread_t a, thr_thread_t b)
{
    return pthread_equal((pthread_t)a, (pthread_t)b) ? 1 : 0;
}

/* ------------------------------------------------------------------ */
/* Mutexes                                                             */
/* ------------------------------------------------------------------ */

static int mutex_init_typed(thr_mutex_t *mutex, int type)
{
    pthread_mutexattr_t attr;
    pthread_mutex_t *native;
    int rc;

    if (!mutex) {
        return THR_INVAL;
    }
    native = MUTEX(mutex);
    if (pthread_mutexattr_init(&attr) != 0) {
        return THR_INVAL;
    }
    pthread_mutexattr_settype(&attr, type);
    rc = pthread_mutex_init(native, &attr);
    pthread_mutexattr_destroy(&attr);
    return map_error(rc);
}

int thr_mutex_init(thr_mutex_t *mutex)
{
    return mutex_init_typed(mutex, PTHREAD_MUTEX_NORMAL);
}

int thr_mutex_init_recursive(thr_mutex_t *mutex)
{
    return mutex_init_typed(mutex, PTHREAD_MUTEX_RECURSIVE);
}

int thr_mutex_lock(thr_mutex_t *mutex)
{
    if (!mutex) {
        return THR_INVAL;
    }
    return map_error(pthread_mutex_lock(MUTEX(mutex)));
}

int thr_mutex_trylock(thr_mutex_t *mutex)
{
    if (!mutex) {
        return THR_INVAL;
    }
    return map_error(pthread_mutex_trylock(MUTEX(mutex)));
}

int thr_mutex_unlock(thr_mutex_t *mutex)
{
    if (!mutex) {
        return THR_INVAL;
    }
    return map_error(pthread_mutex_unlock(MUTEX(mutex)));
}

int thr_mutex_destroy(thr_mutex_t *mutex)
{
    if (!mutex) {
        return THR_INVAL;
    }
    return map_error(pthread_mutex_destroy(MUTEX(mutex)));
}

/* ------------------------------------------------------------------ */
/* Read/write locks                                                    */
/* ------------------------------------------------------------------ */

int thr_rwlock_init(thr_rwlock_t *lock)
{
    if (!lock) {
        return THR_INVAL;
    }
    return map_error(pthread_rwlock_init(RWLOCK(lock), NULL));
}

int thr_rwlock_rdlock(thr_rwlock_t *lock)
{
    if (!lock) {
        return THR_INVAL;
    }
    return map_error(pthread_rwlock_rdlock(RWLOCK(lock)));
}

int thr_rwlock_wrlock(thr_rwlock_t *lock)
{
    if (!lock) {
        return THR_INVAL;
    }
    return map_error(pthread_rwlock_wrlock(RWLOCK(lock)));
}

int thr_rwlock_tryrdlock(thr_rwlock_t *lock)
{
    if (!lock) {
        return THR_INVAL;
    }
    return map_error(pthread_rwlock_tryrdlock(RWLOCK(lock)));
}

int thr_rwlock_trywrlock(thr_rwlock_t *lock)
{
    if (!lock) {
        return THR_INVAL;
    }
    return map_error(pthread_rwlock_trywrlock(RWLOCK(lock)));
}

int thr_rwlock_unlock(thr_rwlock_t *lock)
{
    if (!lock) {
        return THR_INVAL;
    }
    return map_error(pthread_rwlock_unlock(RWLOCK(lock)));
}

int thr_rwlock_destroy(thr_rwlock_t *lock)
{
    if (!lock) {
        return THR_INVAL;
    }
    return map_error(pthread_rwlock_destroy(RWLOCK(lock)));
}

/* ------------------------------------------------------------------ */
/* Semaphores                                                          */
/* ------------------------------------------------------------------ */

int thr_sem_init(thr_sem_t *sem, unsigned int count)
{
    if (!sem || count > 0x7fffffffu) {
        return THR_INVAL;
    }
    return sem_init(SEM(sem), 0, count) == 0 ? THR_OK : THR_INVAL;
}

int thr_sem_post(thr_sem_t *sem)
{
    if (!sem) {
        return THR_INVAL;
    }
    for (;;) {
        if (sem_post(SEM(sem)) == 0) {
            return THR_OK;
        }
        if (errno != EINTR) {
            return THR_INVAL;
        }
    }
}

int thr_sem_wait(thr_sem_t *sem)
{
    if (!sem) {
        return THR_INVAL;
    }
    for (;;) {
        if (sem_wait(SEM(sem)) == 0) {
            return THR_OK;
        }
        if (errno != EINTR) {
            return THR_INVAL;
        }
    }
}

int thr_sem_trywait(thr_sem_t *sem)
{
    if (!sem) {
        return THR_INVAL;
    }
    if (sem_trywait(SEM(sem)) == 0) {
        return THR_OK;
    }
    return errno == EAGAIN ? THR_AGAIN : THR_INVAL;
}

int thr_sem_destroy(thr_sem_t *sem)
{
    if (!sem) {
        return THR_INVAL;
    }
    return sem_destroy(SEM(sem)) == 0 ? THR_OK : THR_INVAL;
}

/* ------------------------------------------------------------------ */
/* Condition variables                                                 */
/* ------------------------------------------------------------------ */

int thr_cond_init(thr_cond_t *cond)
{
    pthread_condattr_t attr;
    pthread_cond_t *native;
    int rc;

    if (!cond) {
        return THR_INVAL;
    }
    native = COND(cond);
    if (pthread_condattr_init(&attr) != 0) {
        return THR_INVAL;
    }
    /* Timed waits are measured against the monotonic clock so a step of the
     * wall clock cannot stretch or collapse the interval. */
    pthread_condattr_setclock(&attr, CLOCK_MONOTONIC);
    rc = pthread_cond_init(native, &attr);
    pthread_condattr_destroy(&attr);
    return map_error(rc);
}

int thr_cond_wait(thr_cond_t *cond, thr_mutex_t *mutex)
{
    if (!cond || !mutex) {
        return THR_INVAL;
    }
    return map_error(pthread_cond_wait(COND(cond), MUTEX(mutex)));
}

int thr_cond_timedwait(thr_cond_t *cond, thr_mutex_t *mutex,
                       unsigned long milliseconds)
{
    struct timespec deadline;
    unsigned long long nanos;

    if (!cond || !mutex) {
        return THR_INVAL;
    }
    clock_gettime(CLOCK_MONOTONIC, &deadline);
    nanos = (unsigned long long)milliseconds * 1000000ull;
    deadline.tv_sec += (time_t)(nanos / 1000000000ull);
    deadline.tv_nsec += (long)(nanos % 1000000000ull);
    if (deadline.tv_nsec >= 1000000000L) {
        deadline.tv_sec += 1;
        deadline.tv_nsec -= 1000000000L;
    }
    return map_error(pthread_cond_timedwait(COND(cond), MUTEX(mutex),
                                            &deadline));
}

int thr_cond_signal(thr_cond_t *cond)
{
    if (!cond) {
        return THR_INVAL;
    }
    return map_error(pthread_cond_signal(COND(cond)));
}

int thr_cond_broadcast(thr_cond_t *cond)
{
    if (!cond) {
        return THR_INVAL;
    }
    return map_error(pthread_cond_broadcast(COND(cond)));
}

int thr_cond_destroy(thr_cond_t *cond)
{
    if (!cond) {
        return THR_INVAL;
    }
    return map_error(pthread_cond_destroy(COND(cond)));
}

/* ------------------------------------------------------------------ */
/* Thread-local storage                                                */
/* ------------------------------------------------------------------ */

int thr_tls_create(thr_tls_key_t *key, void (*destructor)(void *))
{
    pthread_key_t native;
    int rc;

    if (!key) {
        return THR_INVAL;
    }
    rc = pthread_key_create(&native, destructor);
    if (rc != 0) {
        return map_error(rc);
    }
    *key = (thr_tls_key_t)native;
    return THR_OK;
}

void *thr_tls_get(thr_tls_key_t key)
{
    return pthread_getspecific((pthread_key_t)key);
}

int thr_tls_set(thr_tls_key_t key, void *value)
{
    return map_error(pthread_setspecific((pthread_key_t)key, value));
}

int thr_tls_delete(thr_tls_key_t key)
{
    return map_error(pthread_key_delete((pthread_key_t)key));
}

/* ------------------------------------------------------------------ */
/* One-time initialisation                                             */
/* ------------------------------------------------------------------ */

int thr_once(thr_once_t *guard, void (*callback)(void))
{
    if (!guard || !callback) {
        return THR_INVAL;
    }
    return map_error(pthread_once(ONCE(guard), callback));
}

/* ------------------------------------------------------------------ */
/* Affinity                                                            */
/* ------------------------------------------------------------------ */

int thr_affinity_set(const unsigned long *mask, unsigned int words)
{
    cpu_set_t set;
    unsigned int cpu;
    int any = 0;

    if (!mask || words < THR_CPU_WORDS) {
        return THR_INVAL;
    }
    CPU_ZERO(&set);
    for (cpu = 0; cpu < THR_CPU_WORDS * 64u; cpu++) {
        if ((mask[cpu / 64u] >> (cpu % 64u)) & 1UL) {
            if (cpu >= CPU_SETSIZE) {
                return THR_INVAL;
            }
            CPU_SET(cpu, &set);
            any = 1;
        }
    }
    if (!any) {
        return THR_INVAL;
    }
    if (pthread_setaffinity_np(pthread_self(), sizeof(set), &set) != 0) {
        return THR_INVAL;
    }
    return THR_OK;
}

int thr_affinity_get(unsigned long *mask, unsigned int words)
{
    cpu_set_t set;
    unsigned int cpu;

    if (!mask || words < THR_CPU_WORDS) {
        return THR_INVAL;
    }
    CPU_ZERO(&set);
    if (pthread_getaffinity_np(pthread_self(), sizeof(set), &set) != 0) {
        return THR_INVAL;
    }
    memset(mask, 0, (size_t)words * sizeof(*mask));
    for (cpu = 0; cpu < THR_CPU_WORDS * 64u && cpu < CPU_SETSIZE; cpu++) {
        if (CPU_ISSET(cpu, &set)) {
            mask[cpu / 64u] |= 1UL << (cpu % 64u);
        }
    }
    return THR_OK;
}

int thr_affinity_current(void)
{
    int cpu = sched_getcpu();
    return cpu >= 0 ? cpu : THR_NOSYS;
}