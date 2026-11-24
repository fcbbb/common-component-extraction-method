/*
 * Hidden contract probe for the threading backend.
 *
 * Compiled against the public header and the built archive; it makes no use
 * of backend internals.  Orchestration uses native pthread primitives so a
 * broken public primitive cannot wedge the probe's own bookkeeping.
 */
#define _GNU_SOURCE
#include "thr.h"

#include <dirent.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>

static int g_failures;

#define CHECK(cond, ...)                                                     \
    do {                                                                     \
        if (!(cond)) {                                                       \
            fprintf(stderr, "deep: " __VA_ARGS__);                           \
            fprintf(stderr, " (line %d)\n", __LINE__);                       \
            g_failures++;                                                    \
        }                                                                    \
    } while (0)

static double now(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static int task_count(void)
{
    DIR *dir = opendir("/proc/self/task");
    struct dirent *entry;
    int count = 0;

    if (!dir) {
        return -1;
    }
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") != 0 && strcmp(entry->d_name, "..") != 0) {
            count++;
        }
    }
    closedir(dir);
    return count;
}

static int wait_until(volatile int *value, int wanted, double seconds)
{
    double limit = now() + seconds;
    while (now() < limit) {
        if (*value >= wanted) {
            return 1;
        }
        usleep(1000);
    }
    return *value >= wanted;
}

/* ------------------------------------------------------------------ */
/* Threads, identity and join                                          */
/* ------------------------------------------------------------------ */

enum { THREAD_COUNT = 64 };

struct thread_arg {
    int index;
    int seen;
    thr_thread_t self;
};

static struct thread_arg g_args[THREAD_COUNT];
static thr_thread_t g_main_self;

static void *thread_entry(void *arg)
{
    struct thread_arg *mine = arg;

    mine->self = thr_thread_self();
    mine->seen = mine->index;
    return arg;
}

static void test_threads(void)
{
    thr_thread_t ids[THREAD_COUNT];
    int baseline = task_count();
    int i;
    int rc;

    g_main_self = thr_thread_self();
    for (i = 0; i < THREAD_COUNT; i++) {
        g_args[i].index = i;
        g_args[i].seen = -1;
        g_args[i].self = 0;
        ids[i] = 0;
        rc = thr_thread_create(&ids[i], thread_entry, &g_args[i], 0);
        CHECK(rc == THR_OK, "create thread %d returned %d", i, rc);
    }
    for (i = 0; i < THREAD_COUNT; i++) {
        rc = thr_thread_join(&ids[i]);
        CHECK(rc == THR_OK, "join thread %d returned %d", i, rc);
        CHECK(ids[i] == 0, "join left identity %lu for thread %d",
              (unsigned long)ids[i], i);
    }
    for (i = 0; i < THREAD_COUNT; i++) {
        CHECK(g_args[i].seen == i, "thread %d saw argument %d", i,
              g_args[i].seen);
        CHECK(!thr_thread_equal(g_args[i].self, g_main_self),
              "thread %d reports the caller's identity", i);
    }
    CHECK(!thr_thread_equal(g_args[0].self, g_args[1].self),
          "two threads report the same identity");
    CHECK(thr_thread_equal(g_args[0].self, g_args[0].self),
          "a thread identity does not equal itself");
    CHECK(thr_thread_equal(g_main_self, thr_thread_self()),
          "the caller's identity is not stable");
    if (baseline > 0) {
        CHECK(task_count() == baseline,
              "task count after join is %d, baseline %d", task_count(),
              baseline);
    }
    CHECK(thr_thread_join(&ids[0]) == THR_INVAL,
          "joining an already joined identity was accepted");
    {
        thr_thread_t bad = 0;
        CHECK(thr_thread_join(&bad) == THR_INVAL,
              "joining a cleared identity was accepted");
    }
}

/* ------------------------------------------------------------------ */
/* Thread-local storage                                                */
/* ------------------------------------------------------------------ */

static thr_tls_key_t g_tls_key;
static volatile int g_tls_dtor_count;
static void *g_tls_dtor_value;
static volatile int g_tls_worker_bad;
static int g_tls_marker_a;
static int g_tls_marker_b;

static void tls_destructor(void *value)
{
    g_tls_dtor_value = value;
    __sync_fetch_and_add(&g_tls_dtor_count, 1);
}

static void *tls_worker(void *arg)
{
    if (thr_tls_get(g_tls_key) != NULL) {
        __sync_fetch_and_add(&g_tls_worker_bad, 1);
    }
    if (thr_tls_set(g_tls_key, arg) != THR_OK) {
        __sync_fetch_and_add(&g_tls_worker_bad, 2);
    }
    if (thr_tls_get(g_tls_key) != arg) {
        __sync_fetch_and_add(&g_tls_worker_bad, 4);
    }
    return NULL;
}

static void test_tls(void)
{
    thr_thread_t thread;

    CHECK(thr_tls_create(&g_tls_key, tls_destructor) == THR_OK,
          "tls key creation");
    CHECK(thr_tls_get(g_tls_key) == NULL, "a fresh key is not null");
    CHECK(thr_tls_set(g_tls_key, &g_tls_marker_a) == THR_OK, "tls set");
    CHECK(thr_tls_get(g_tls_key) == &g_tls_marker_a,
          "tls returned the wrong value");
    CHECK(thr_tls_set(g_tls_key, NULL) == THR_OK, "tls clear");
    CHECK(thr_tls_get(g_tls_key) == NULL, "clearing tls left a value");

    CHECK(thr_thread_create(&thread, tls_worker, &g_tls_marker_b, 0) == THR_OK,
          "tls worker creation");
    CHECK(thr_thread_join(&thread) == THR_OK, "tls worker join");
    CHECK(g_tls_worker_bad == 0, "tls state leaked into a new thread (%d)",
          g_tls_worker_bad);
    CHECK(g_tls_dtor_count == 1,
          "tls destructor ran %d times, expected once", g_tls_dtor_count);
    CHECK(g_tls_dtor_value == &g_tls_marker_b,
          "tls destructor saw the wrong value");
    CHECK(thr_tls_get(g_tls_key) == NULL,
          "the destructor of another thread changed the caller's value");
    CHECK(thr_tls_delete(g_tls_key) == THR_OK, "tls delete");
}

/* ------------------------------------------------------------------ */
/* Mutexes                                                             */
/* ------------------------------------------------------------------ */

static thr_mutex_t g_mutex;
static volatile int g_holder_locked;

static void *mutex_holder(void *arg)
{
    (void)arg;
    if (thr_mutex_lock(&g_mutex) == THR_OK) {
        __sync_lock_test_and_set(&g_holder_locked, 1);
        usleep(100000);
        thr_mutex_unlock(&g_mutex);
    }
    return NULL;
}

static void test_mutex(void)
{
    thr_thread_t holder;
    double start;
    double elapsed;
    int rc;

    CHECK(thr_mutex_init(&g_mutex) == THR_OK, "mutex init");
    CHECK(thr_mutex_lock(&g_mutex) == THR_OK, "mutex lock");
    CHECK(thr_mutex_unlock(&g_mutex) == THR_OK, "mutex unlock");
    CHECK(thr_mutex_trylock(&g_mutex) == THR_OK, "unlocked trylock");
    CHECK(thr_mutex_unlock(&g_mutex) == THR_OK, "trylock unlock");

    CHECK(thr_thread_create(&holder, mutex_holder, NULL, 0) == THR_OK,
          "mutex holder creation");
    if (!wait_until(&g_holder_locked, 1, 2.0)) {
        CHECK(0, "mutex holder never reported ownership");
    } else {
        start = now();
        rc = thr_mutex_trylock(&g_mutex);
        elapsed = now() - start;
        CHECK(rc == THR_BUSY, "trylock of a held mutex returned %d", rc);
        CHECK(elapsed < 0.2, "trylock blocked for %.3f s", elapsed);
    }
    CHECK(thr_thread_join(&holder) == THR_OK, "mutex holder join");
    CHECK(thr_mutex_destroy(&g_mutex) == THR_OK, "mutex destroy");

    CHECK(thr_mutex_init_recursive(&g_mutex) == THR_OK, "recursive mutex init");
    CHECK(thr_mutex_lock(&g_mutex) == THR_OK, "recursive first lock");
    CHECK(thr_mutex_lock(&g_mutex) == THR_OK, "recursive second lock");
    CHECK(thr_mutex_trylock(&g_mutex) == THR_OK, "recursive trylock");
    CHECK(thr_mutex_unlock(&g_mutex) == THR_OK, "recursive unlock 1");
    CHECK(thr_mutex_unlock(&g_mutex) == THR_OK, "recursive unlock 2");
    CHECK(thr_mutex_unlock(&g_mutex) == THR_OK, "recursive unlock 3");
    CHECK(thr_mutex_destroy(&g_mutex) == THR_OK, "recursive mutex destroy");
}

/* ------------------------------------------------------------------ */
/* Read/write locks                                                    */
/* ------------------------------------------------------------------ */

static thr_rwlock_t g_rwlock;
static volatile int g_reader_done;
static volatile int g_reader_rc;

static void *rw_reader(void *arg)
{
    (void)arg;
    __sync_lock_test_and_set(&g_reader_rc, thr_rwlock_tryrdlock(&g_rwlock));
    if (g_reader_rc == THR_OK) {
        thr_rwlock_unlock(&g_rwlock);
    }
    __sync_lock_test_and_set(&g_reader_done, 1);
    return NULL;
}

static volatile int g_writer_busy;
static volatile int g_writer_done;

static void *rw_writer(void *arg)
{
    (void)arg;
    if (thr_rwlock_trywrlock(&g_rwlock) == THR_BUSY &&
        thr_rwlock_tryrdlock(&g_rwlock) == THR_BUSY) {
        __sync_lock_test_and_set(&g_writer_busy, 1);
    }
    __sync_lock_test_and_set(&g_writer_done, 1);
    return NULL;
}

static void test_rwlock(void)
{
    thr_thread_t reader;
    thr_thread_t writer;

    CHECK(thr_rwlock_init(&g_rwlock) == THR_OK, "rwlock init");

    CHECK(thr_rwlock_rdlock(&g_rwlock) == THR_OK, "rwlock read lock");
    CHECK(thr_thread_create(&reader, rw_reader, NULL, 0) == THR_OK,
          "concurrent reader creation");
    CHECK(thr_thread_join(&reader) == THR_OK, "concurrent reader join");
    CHECK(wait_until(&g_reader_done, 1, 1.0), "concurrent reader never ran");
    CHECK(g_reader_rc == THR_OK,
          "a second reader was refused with %d while a reader held the lock",
          g_reader_rc);
    CHECK(thr_rwlock_unlock(&g_rwlock) == THR_OK, "rwlock read unlock");

    CHECK(thr_rwlock_wrlock(&g_rwlock) == THR_OK, "rwlock write lock");
    CHECK(thr_thread_create(&writer, rw_writer, NULL, 0) == THR_OK,
          "excluded writer creation");
    CHECK(thr_thread_join(&writer) == THR_OK, "excluded writer join");
    CHECK(wait_until(&g_writer_done, 1, 1.0), "excluded writer never ran");
    CHECK(g_writer_busy == 1,
          "a writer holding the lock did not exclude try-read/try-write");
    CHECK(thr_rwlock_unlock(&g_rwlock) == THR_OK, "rwlock write unlock");

    CHECK(thr_rwlock_tryrdlock(&g_rwlock) == THR_OK,
          "try-read on an idle lock");
    CHECK(thr_rwlock_unlock(&g_rwlock) == THR_OK, "idle try-read unlock");
    CHECK(thr_rwlock_trywrlock(&g_rwlock) == THR_OK,
          "try-write on an idle lock");
    CHECK(thr_rwlock_unlock(&g_rwlock) == THR_OK, "idle try-write unlock");
    CHECK(thr_rwlock_destroy(&g_rwlock) == THR_OK, "rwlock destroy");
}

/* ------------------------------------------------------------------ */
/* Semaphores                                                          */
/* ------------------------------------------------------------------ */

static thr_sem_t g_sem;
static volatile int g_sem_waiters;
static volatile int g_sem_released;

static void *sem_waiter(void *arg)
{
    (void)arg;
    __sync_fetch_and_add(&g_sem_waiters, 1);
    if (thr_sem_wait(&g_sem) == THR_OK) {
        __sync_fetch_and_add(&g_sem_released, 1);
    }
    return NULL;
}

static void test_sem(void)
{
    thr_thread_t waiters[3];
    double start;
    double elapsed;
    int i;
    int rc;

    CHECK(thr_sem_init(&g_sem, 0) == THR_OK, "sem init");
    start = now();
    rc = thr_sem_trywait(&g_sem);
    elapsed = now() - start;
    CHECK(rc == THR_AGAIN, "try-wait on an empty semaphore returned %d", rc);
    CHECK(elapsed < 0.2, "try-wait blocked for %.3f s", elapsed);
    CHECK(thr_sem_post(&g_sem) == THR_OK, "sem post");
    CHECK(thr_sem_wait(&g_sem) == THR_OK, "sem wait after post");
    CHECK(thr_sem_post(&g_sem) == THR_OK, "sem second post");
    CHECK(thr_sem_trywait(&g_sem) == THR_OK, "try-wait after post");

    for (i = 0; i < 3; i++) {
        CHECK(thr_thread_create(&waiters[i], sem_waiter, NULL, 0) == THR_OK,
              "sem waiter %d creation", i);
    }
    CHECK(wait_until(&g_sem_waiters, 3, 2.0),
          "waiters did not all block on the semaphore");
    usleep(50000);
    for (i = 0; i < 3; i++) {
        CHECK(thr_sem_post(&g_sem) == THR_OK, "sem release post %d", i);
    }
    for (i = 0; i < 3; i++) {
        CHECK(thr_thread_join(&waiters[i]) == THR_OK, "sem waiter %d join", i);
    }
    CHECK(g_sem_released == 3, "%d of 3 waiters were released",
          g_sem_released);
    CHECK(thr_sem_destroy(&g_sem) == THR_OK, "sem destroy");
}

/* ------------------------------------------------------------------ */
/* Condition variables                                                 */
/* ------------------------------------------------------------------ */

static thr_cond_t g_cond;
static thr_mutex_t g_cond_mutex;
static volatile int g_cond_waiting;
static volatile int g_cond_woke;
static volatile int g_cond_ready;

static void *cond_waiter(void *arg)
{
    (void)arg;
    if (thr_mutex_lock(&g_cond_mutex) != THR_OK) {
        return NULL;
    }
    __sync_fetch_and_add(&g_cond_waiting, 1);
    while (!g_cond_ready) {
        if (thr_cond_wait(&g_cond, &g_cond_mutex) != THR_OK) {
            break;
        }
    }
    __sync_fetch_and_add(&g_cond_woke, 1);
    thr_mutex_unlock(&g_cond_mutex);
    return NULL;
}

static void test_cond(void)
{
    thr_thread_t waiters[2];
    double start;
    double elapsed;
    int i;
    int rc;

    CHECK(thr_cond_init(&g_cond) == THR_OK, "cond init");
    CHECK(thr_mutex_init_recursive(&g_cond_mutex) == THR_OK,
          "cond mutex init");

    CHECK(thr_mutex_lock(&g_cond_mutex) == THR_OK, "cond mutex lock");
    start = now();
    rc = thr_cond_timedwait(&g_cond, &g_cond_mutex, 100);
    elapsed = now() - start;
    CHECK(rc == THR_TIMEDOUT, "timed wait returned %d, expected %d", rc,
          THR_TIMEDOUT);
    CHECK(elapsed >= 0.095, "timed wait returned after %.3f s", elapsed);
    CHECK(elapsed < 2.0, "timed wait overshot to %.3f s", elapsed);
    CHECK(thr_mutex_trylock(&g_cond_mutex) == THR_OK,
          "timed wait did not keep the mutex locked");
    CHECK(thr_mutex_unlock(&g_cond_mutex) == THR_OK, "cond relock 1");
    CHECK(thr_mutex_unlock(&g_cond_mutex) == THR_OK, "cond relock 2");

    for (i = 0; i < 2; i++) {
        CHECK(thr_thread_create(&waiters[i], cond_waiter, NULL, 0) == THR_OK,
              "cond waiter %d creation", i);
    }
    CHECK(wait_until(&g_cond_waiting, 2, 2.0), "cond waiters never blocked");
    usleep(50000);
    CHECK(thr_mutex_lock(&g_cond_mutex) == THR_OK, "cond signal lock");
    g_cond_ready = 1;
    CHECK(thr_cond_signal(&g_cond) == THR_OK, "cond signal");
    thr_mutex_unlock(&g_cond_mutex);
    CHECK(wait_until(&g_cond_woke, 1, 1.0), "signal woke no waiter");
    usleep(100000);
    CHECK(g_cond_woke == 1, "a single signal woke %d waiters", g_cond_woke);
    CHECK(thr_mutex_lock(&g_cond_mutex) == THR_OK, "cond broadcast lock");
    CHECK(thr_cond_broadcast(&g_cond) == THR_OK, "cond broadcast");
    thr_mutex_unlock(&g_cond_mutex);
    for (i = 0; i < 2; i++) {
        CHECK(thr_thread_join(&waiters[i]) == THR_OK, "cond waiter %d join", i);
    }
    CHECK(g_cond_woke == 2, "broadcast left %d wakeups", g_cond_woke);
    CHECK(thr_cond_destroy(&g_cond) == THR_OK, "cond destroy");
    CHECK(thr_mutex_destroy(&g_cond_mutex) == THR_OK, "cond mutex destroy");
}

/* ------------------------------------------------------------------ */
/* One-time initialisation                                             */
/* ------------------------------------------------------------------ */

static thr_once_t g_once = THR_ONCE_INIT;
static volatile int g_once_runs;
static volatile int g_once_bad;

static void once_callback(void)
{
    __sync_fetch_and_add(&g_once_runs, 1);
}

static void *once_worker(void *arg)
{
    (void)arg;
    if (thr_once(&g_once, once_callback) != THR_OK) {
        __sync_fetch_and_add(&g_once_bad, 1);
    }
    return NULL;
}

static void test_once(void)
{
    thr_thread_t threads[16];
    int i;

    for (i = 0; i < 16; i++) {
        CHECK(thr_thread_create(&threads[i], once_worker, NULL, 0) == THR_OK,
              "once worker %d creation", i);
    }
    for (i = 0; i < 16; i++) {
        CHECK(thr_thread_join(&threads[i]) == THR_OK, "once worker %d join",
              i);
    }
    CHECK(g_once_bad == 0, "%d once calls failed", g_once_bad);
    CHECK(g_once_runs == 1, "the guard callback ran %d times", g_once_runs);
}

/* ------------------------------------------------------------------ */
/* Stack sizing                                                        */
/* ------------------------------------------------------------------ */

struct stack_measure {
    size_t measured;
};

static void *stack_worker(void *arg)
{
    struct stack_measure *measure = arg;
    pthread_attr_t attr;
    void *base;
    size_t size = 0;

    measure->measured = 0;
    if (pthread_getattr_np(pthread_self(), &attr) == 0) {
        if (pthread_attr_getstack(&attr, &base, &size) == 0) {
            measure->measured = size;
        }
        pthread_attr_destroy(&attr);
    }
    return NULL;
}

static void test_stack(void)
{
    struct rlimit old_limit;
    struct rlimit small_limit;
    struct stack_measure measure;
    thr_thread_t thread;
    int rc;

    if (getrlimit(RLIMIT_STACK, &old_limit) == 0) {
        small_limit.rlim_cur = 1024 * 1024;
        small_limit.rlim_max = old_limit.rlim_max < small_limit.rlim_cur
                                   ? old_limit.rlim_max
                                   : small_limit.rlim_cur;
        setrlimit(RLIMIT_STACK, &small_limit);
    }

    CHECK(thr_thread_create(&thread, stack_worker, &measure,
                            8u * 1024u * 1024u) == THR_OK,
          "8 MiB stack thread creation");
    CHECK(thr_thread_join(&thread) == THR_OK, "8 MiB stack thread join");
    CHECK(measure.measured >= 4u * 1024u * 1024u,
          "an 8 MiB request produced a %zu-byte stack", measure.measured);

    CHECK(thr_thread_create(&thread, stack_worker, &measure, 0) == THR_OK,
          "default stack thread creation");
    CHECK(thr_thread_join(&thread) == THR_OK, "default stack thread join");

    CHECK(thr_thread_create(&thread, stack_worker, &measure,
                            64u * 1024u) == THR_OK,
          "64 KiB stack thread creation");
    CHECK(thr_thread_join(&thread) == THR_OK, "64 KiB stack thread join");
    CHECK(measure.measured >= 64u * 1024u,
          "a 64 KiB request produced a %zu-byte stack", measure.measured);

    rc = thr_thread_create(&thread, stack_worker, &measure, 100001u);
    CHECK(rc == THR_OK, "unaligned stack request returned %d", rc);
    if (rc == THR_OK) {
        CHECK(thr_thread_join(&thread) == THR_OK, "unaligned stack join");
        CHECK(measure.measured >= 100001u,
              "a 100001-byte request produced a %zu-byte stack",
              measure.measured);
    }

    if (old_limit.rlim_cur != 0) {
        setrlimit(RLIMIT_STACK, &old_limit);
    }
}

/* ------------------------------------------------------------------ */
/* Affinity                                                            */
/* ------------------------------------------------------------------ */

static void test_affinity(void)
{
    unsigned long current[THR_CPU_WORDS];
    unsigned long single[THR_CPU_WORDS];
    unsigned int cpu;
    unsigned int found = THR_CPU_WORDS * 64u;
    int rc;

    memset(current, 0, sizeof(current));
    rc = thr_affinity_get(current, THR_CPU_WORDS);
    CHECK(rc == THR_OK, "affinity get returned %d", rc);
    if (rc != THR_OK) {
        return;
    }
    for (cpu = 0; cpu < THR_CPU_WORDS * 64u; cpu++) {
        if ((current[cpu / 64u] >> (cpu % 64u)) & 1UL) {
            found = cpu;
            break;
        }
    }
    CHECK(found < THR_CPU_WORDS * 64u, "the current affinity mask is empty");
    if (found >= THR_CPU_WORDS * 64u) {
        return;
    }

    memset(single, 0, sizeof(single));
    single[found / 64u] |= 1UL << (found % 64u);
    CHECK(thr_affinity_set(single, THR_CPU_WORDS) == THR_OK,
          "affinity set to CPU %u", found);
    memset(current, 0xff, sizeof(current));
    CHECK(thr_affinity_get(current, THR_CPU_WORDS) == THR_OK,
          "affinity re-read");
    CHECK(current[found / 64u] == (1UL << (found % 64u)),
          "affinity did not become exactly CPU %u", found);
    {
        unsigned int other;
        int extra = 0;
        for (other = 0; other < THR_CPU_WORDS; other++) {
            if (other != found / 64u && current[other] != 0) {
                extra = 1;
            }
        }
        CHECK(!extra, "affinity kept CPUs outside the requested set");
    }
    rc = thr_affinity_current();
    CHECK(rc >= 0, "current CPU query returned %d", rc);
    if (rc >= 0) {
        CHECK((unsigned int)rc == found,
              "current CPU %d is outside the one-CPU mask (%u)", rc, found);
    }

    memset(single, 0, sizeof(single));
    CHECK(thr_affinity_set(single, THR_CPU_WORDS) == THR_INVAL,
          "an empty affinity mask was accepted");
    CHECK(thr_affinity_set(current, 0) == THR_INVAL,
          "a zero-word affinity mask was accepted");
    CHECK(thr_affinity_get(current, 1) == THR_INVAL,
          "a too-small affinity buffer was accepted");
}

/* ------------------------------------------------------------------ */
/* Error contract                                                      */
/* ------------------------------------------------------------------ */

static void test_errors(void)
{
    thr_sem_t sem;
    thr_cond_t cond;
    thr_thread_t thread;

    CHECK(thr_mutex_init(NULL) == THR_INVAL, "null mutex init was accepted");
    CHECK(thr_mutex_lock(NULL) == THR_INVAL, "null mutex lock was accepted");
    CHECK(thr_mutex_trylock(NULL) == THR_INVAL,
          "null mutex trylock was accepted");
    CHECK(thr_cond_init(NULL) == THR_INVAL, "null cond init was accepted");
    CHECK(thr_cond_timedwait(NULL, NULL, 1) == THR_INVAL,
          "null cond wait was accepted");
    CHECK(thr_sem_post(NULL) == THR_INVAL, "null sem post was accepted");
    CHECK(thr_sem_init(&sem, 0x80000000u) == THR_INVAL,
          "an out-of-range semaphore count was accepted");
    CHECK(thr_sem_init(&sem, 0) == THR_OK, "sem init in the error probe");
    CHECK(thr_sem_destroy(&sem) == THR_OK, "sem destroy in the error probe");
    CHECK(thr_thread_create(NULL, thread_entry, NULL, 0) == THR_INVAL,
          "null thread output was accepted");
    CHECK(thr_thread_create(&thread, NULL, NULL, 0) == THR_INVAL,
          "null thread entry was accepted");
    CHECK(thr_thread_create(&thread, thread_entry, &g_args[0], 0) == THR_OK,
          "valid thread creation in the error probe");
    CHECK(thr_thread_join(&thread) == THR_OK, "valid thread join");
}

int main(void)
{
    signal(SIGPIPE, SIG_IGN);
    alarm(120);

    test_threads();
    test_tls();
    test_mutex();
    test_rwlock();
    test_sem();
    test_cond();
    test_once();
    test_stack();
    test_affinity();
    test_errors();

    if (g_failures != 0) {
        printf("THR_DEEP=FAIL count=%d\n", g_failures);
        return 1;
    }
    printf("THR_DEEP=PASS\n");
    return 0;
}