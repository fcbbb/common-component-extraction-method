/*
 * Evaluator-only checks for the removed nginx threading primitives.
 *
 * The test links against the objects built from the candidate
 * src/os/unix/ngx_thread_mutex.c, ngx_thread_cond.c and ngx_thread_id.c.
 * It checks the contract the thread pool depends on:
 *
 *   - mutex create/destroy/lock/unlock succeed and serialise increments;
 *   - cond create/signal/wait block until signalled and return NGX_OK;
 *   - ngx_thread_tid() is nonzero and differs between threads.
 *
 * The program is entered through a constructor so the test object can be
 * linked with the complete nginx object set without colliding with main().
 */

#define _GNU_SOURCE

#include <ngx_config.h>
#include <ngx_core.h>
#include <ngx_thread.h>

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static ngx_log_t test_log;
static int failures;

#define CHECK(cond, msg)                                                      \
    do {                                                                      \
        if (!(cond)) {                                                        \
            fprintf(stderr, "FAIL: %s\n", msg);                               \
            failures++;                                                       \
        }                                                                     \
    } while (0)

static ngx_thread_mutex_t counter_mutex;
static long counter;
static int counter_ok;
static ngx_tid_t worker_tids[4];

static void *counter_worker(void *arg) {
    int i;
    long idx = (long) arg;

    worker_tids[idx] = ngx_thread_tid();

    if (ngx_thread_mutex_lock(&counter_mutex, &test_log) != NGX_OK) {
        counter_ok = 0;
        return NULL;
    }
    for (i = 0; i < 20000; i++) {
        counter++;
    }
    if (ngx_thread_mutex_unlock(&counter_mutex, &test_log) != NGX_OK) {
        counter_ok = 0;
    }
    return NULL;
}

static ngx_thread_mutex_t cond_mutex;
static ngx_thread_cond_t cond;
static int cond_ready;
static int cond_result;

static void *cond_worker(void *arg) {
    (void) arg;

    if (ngx_thread_mutex_lock(&cond_mutex, &test_log) != NGX_OK) {
        cond_result = -1;
        return NULL;
    }
    while (!cond_ready) {
        if (ngx_thread_cond_wait(&cond, &cond_mutex, &test_log) != NGX_OK) {
            cond_result = -1;
            ngx_thread_mutex_unlock(&cond_mutex, &test_log);
            return NULL;
        }
    }
    ngx_thread_mutex_unlock(&cond_mutex, &test_log);
    cond_result = 1;
    return NULL;
}

static int run_all(void) {
    pthread_t threads[4];
    pthread_t cond_thread;
    ngx_tid_t main_tid;
    int i, distinct;

    CHECK(ngx_thread_mutex_create(&counter_mutex, &test_log) == NGX_OK,
          "ngx_thread_mutex_create failed");

    counter_ok = 1;
    for (i = 0; i < 4; i++) {
        CHECK(pthread_create(&threads[i], NULL, counter_worker,
                             (void *) (long) i) == 0,
              "pthread_create failed");
    }
    for (i = 0; i < 4; i++) {
        pthread_join(threads[i], NULL);
    }
    CHECK(counter_ok, "mutex lock/unlock failed inside a worker");
    CHECK(counter == 80000, "mutex did not serialise shared counter updates");

    CHECK(ngx_thread_mutex_destroy(&counter_mutex, &test_log) == NGX_OK,
          "ngx_thread_mutex_destroy failed");

    CHECK(ngx_thread_mutex_create(&cond_mutex, &test_log) == NGX_OK,
          "cond mutex create failed");
    CHECK(ngx_thread_cond_create(&cond, &test_log) == NGX_OK,
          "ngx_thread_cond_create failed");

    cond_result = 0;
    CHECK(pthread_create(&cond_thread, NULL, cond_worker, NULL) == 0,
          "pthread_create for cond failed");

    usleep(100000);
    CHECK(cond_result == 0, "cond wait returned before the predicate was set");

    CHECK(ngx_thread_mutex_lock(&cond_mutex, &test_log) == NGX_OK,
          "cond mutex lock failed");
    cond_ready = 1;
    CHECK(ngx_thread_cond_signal(&cond, &test_log) == NGX_OK,
          "ngx_thread_cond_signal failed");
    CHECK(ngx_thread_mutex_unlock(&cond_mutex, &test_log) == NGX_OK,
          "cond mutex unlock failed");

    pthread_join(cond_thread, NULL);
    CHECK(cond_result == 1, "cond wait did not resume after signal");

    CHECK(ngx_thread_cond_destroy(&cond, &test_log) == NGX_OK,
          "ngx_thread_cond_destroy failed");
    CHECK(ngx_thread_mutex_destroy(&cond_mutex, &test_log) == NGX_OK,
          "cond mutex destroy failed");

    main_tid = ngx_thread_tid();
    CHECK(main_tid != 0, "ngx_thread_tid returned zero for the main thread");

    distinct = 0;
    for (i = 0; i < 4; i++) {
        int j;
        int unique = 1;
        CHECK(worker_tids[i] != 0, "ngx_thread_tid returned zero in a worker");
        CHECK(worker_tids[i] != main_tid,
              "ngx_thread_tid returned the main thread id in a worker");
        for (j = 0; j < i; j++) {
            if (worker_tids[i] == worker_tids[j]) {
                unique = 0;
            }
        }
        distinct += unique;
    }
    CHECK(distinct == 4, "ngx_thread_tid did not distinguish worker threads");

    if (failures != 0) {
        fprintf(stderr, "ngx_thread sensitivity: %d failure(s)\n", failures);
        return 1;
    }
    printf("ngx_thread sensitivity: all checks passed\n");
    return 0;
}

__attribute__((constructor)) static void sensitivity_entry(void) {
    int rc;

    rc = run_all();
    fflush(NULL);
    _exit(rc);
}