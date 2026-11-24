/* Public self-test: basic use of the threading surface. */
#include "thr.h"

#include <stdio.h>
#include <string.h>

static thr_mutex_t counter_mutex;
static int counter;
static thr_sem_t done;
static thr_once_t once_guard = THR_ONCE_INIT;
static int once_count;
static thr_tls_key_t tls_key;

static void bump_once(void)
{
    once_count++;
}

static void *worker(void *arg)
{
    int i;
    long id = (long)arg;

    for (i = 0; i < 100; i++) {
        thr_mutex_lock(&counter_mutex);
        counter++;
        thr_mutex_unlock(&counter_mutex);
    }
    thr_tls_set(tls_key, (void *)(id + 1));
    thr_once(&once_guard, bump_once);
    thr_sem_post(&done);
    return arg;
}

int main(void)
{
    thr_thread_t threads[4];
    thr_thread_t self = thr_thread_self();
    thr_cond_t cond;
    thr_mutex_t mutex;
    long i;
    int rc;
    int ok = 1;

    if (thr_mutex_init(&counter_mutex) != THR_OK) {
        fprintf(stderr, "mutex init failed\n");
        return 1;
    }
    if (thr_sem_init(&done, 0) != THR_OK) {
        fprintf(stderr, "sem init failed\n");
        return 1;
    }
    if (thr_tls_create(&tls_key, NULL) != THR_OK) {
        fprintf(stderr, "tls create failed\n");
        return 1;
    }

    for (i = 0; i < 4; i++) {
        rc = thr_thread_create(&threads[i], worker, (void *)i, 0);
        if (rc != THR_OK) {
            fprintf(stderr, "thread create %ld: %d\n", i, rc);
            return 1;
        }
        if (thr_thread_equal(threads[i], self)) {
            fprintf(stderr, "thread %ld equals the caller\n", i);
            ok = 0;
        }
    }
    for (i = 0; i < 4; i++) {
        if (thr_sem_wait(&done) != THR_OK) {
            fprintf(stderr, "sem wait failed\n");
            return 1;
        }
    }
    for (i = 0; i < 4; i++) {
        if (thr_thread_join(&threads[i]) != THR_OK) {
            fprintf(stderr, "join %ld failed\n", i);
            ok = 0;
        }
    }

    if (counter != 400) {
        fprintf(stderr, "counter is %d, expected 400\n", counter);
        ok = 0;
    }
    if (once_count != 1) {
        fprintf(stderr, "once ran %d times\n", once_count);
        ok = 0;
    }
    if (thr_tls_get(tls_key) != NULL) {
        fprintf(stderr, "main thread has a TLS value it never set\n");
        ok = 0;
    }

    if (thr_mutex_destroy(&counter_mutex) != THR_OK) {
        fprintf(stderr, "plain mutex destroy failed\n");
        ok = 0;
    }
    if (thr_mutex_init_recursive(&counter_mutex) != THR_OK ||
        thr_mutex_lock(&counter_mutex) != THR_OK ||
        thr_mutex_lock(&counter_mutex) != THR_OK ||
        thr_mutex_unlock(&counter_mutex) != THR_OK ||
        thr_mutex_unlock(&counter_mutex) != THR_OK ||
        thr_mutex_destroy(&counter_mutex) != THR_OK) {
        fprintf(stderr, "recursive mutex sequence failed\n");
        ok = 0;
    }

    if (thr_cond_init(&cond) != THR_OK || thr_mutex_init(&mutex) != THR_OK) {
        fprintf(stderr, "cond/mutex init failed\n");
        return 1;
    }
    thr_mutex_lock(&mutex);
    rc = thr_cond_timedwait(&cond, &mutex, 20);
    thr_mutex_unlock(&mutex);
    if (rc != THR_TIMEDOUT) {
        fprintf(stderr, "timed wait returned %d, expected %d\n", rc,
                THR_TIMEDOUT);
        ok = 0;
    }
    thr_cond_destroy(&cond);
    thr_mutex_destroy(&mutex);
    thr_tls_delete(tls_key);
    thr_sem_destroy(&done);

    if (!ok) {
        return 1;
    }
    printf("THR_SELFTEST=PASS counter=%d\n", counter);
    return 0;
}