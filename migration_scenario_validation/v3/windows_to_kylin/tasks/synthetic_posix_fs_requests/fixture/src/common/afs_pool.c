/*
 * Shared worker pool.  Requests that carry a callback are executed here, off
 * the thread that submitted them.
 */
#include "afs.h"

#include <errno.h>
#include <pthread.h>
#include <stdlib.h>

#define AFS_MAX_WORKERS 16

struct afs_node {
    afs_req *req;
    struct afs_node *next;
};

extern int afs_dispatch(afs_req *req);
extern int afs_prepare_async(afs_req *req);

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_work = PTHREAD_COND_INITIALIZER;
static pthread_cond_t g_idle = PTHREAD_COND_INITIALIZER;
static struct afs_node *g_head;
static struct afs_node *g_tail;
static pthread_t g_threads[AFS_MAX_WORKERS];
static unsigned g_workers;
static unsigned g_running;
static unsigned g_active;
static int g_stop;
static int g_started;
static __thread int g_is_worker;

static void *worker_main(void *arg)
{
    (void)arg;
    g_is_worker = 1;
    for (;;) {
        struct afs_node *node;
        afs_req *req;

        pthread_mutex_lock(&g_lock);
        while (!g_head && !g_stop) {
            pthread_cond_wait(&g_work, &g_lock);
        }
        if (!g_head && g_stop) {
            pthread_mutex_unlock(&g_lock);
            break;
        }
        node = g_head;
        g_head = node->next;
        if (!g_head) {
            g_tail = NULL;
        }
        g_active++;
        pthread_mutex_unlock(&g_lock);

        req = node->req;
        free(node);
        afs_dispatch(req);
        if (req->cb) {
            req->cb(req);
        }

        pthread_mutex_lock(&g_lock);
        g_active--;
        if (!g_head && g_active == 0) {
            pthread_cond_broadcast(&g_idle);
        }
        pthread_mutex_unlock(&g_lock);
    }
    return NULL;
}

void afs_pool_start(unsigned workers)
{
    unsigned i;

    if (workers == 0) {
        workers = 2;
    }
    if (workers > AFS_MAX_WORKERS) {
        workers = AFS_MAX_WORKERS;
    }
    pthread_mutex_lock(&g_lock);
    if (g_started) {
        pthread_mutex_unlock(&g_lock);
        return;
    }
    g_started = 1;
    g_stop = 0;
    for (i = 0; i < workers; i++) {
        if (pthread_create(&g_threads[i], NULL, worker_main, NULL) == 0) {
            g_workers++;
        }
    }
    pthread_mutex_unlock(&g_lock);
}

static void ensure_started(void)
{
    pthread_mutex_lock(&g_lock);
    if (!g_started) {
        pthread_mutex_unlock(&g_lock);
        afs_pool_start(2);
        return;
    }
    pthread_mutex_unlock(&g_lock);
}

static void enqueue(afs_req *req)
{
    struct afs_node *node = (struct afs_node *)calloc(1, sizeof(*node));
    if (!node) {
        req->err = ENOMEM;
        req->result = -ENOMEM;
        if (req->cb) {
            req->cb(req);
        }
        return;
    }
    node->req = req;
    pthread_mutex_lock(&g_lock);
    if (g_tail) {
        g_tail->next = node;
    } else {
        g_head = node;
    }
    g_tail = node;
    pthread_cond_signal(&g_work);
    pthread_mutex_unlock(&g_lock);
}

int afs_submit(afs_req *req)
{
    if (!req) {
        return -EINVAL;
    }
    if (!req->cb) {
        return afs_dispatch(req);
    }
    ensure_started();
    if (!afs_prepare_async(req)) {
        req->err = ENOMEM;
        req->result = -ENOMEM;
        req->cb(req);
        return 0;
    }
    enqueue(req);
    return 0;
}

void afs_pool_drain(void)
{
    pthread_mutex_lock(&g_lock);
    while (g_head || g_active) {
        pthread_cond_wait(&g_idle, &g_lock);
    }
    pthread_mutex_unlock(&g_lock);
}

void afs_pool_stop(void)
{
    unsigned i;
    unsigned n;

    pthread_mutex_lock(&g_lock);
    if (!g_started) {
        pthread_mutex_unlock(&g_lock);
        return;
    }
    g_stop = 1;
    n = g_workers;
    g_started = 0;
    g_workers = 0;
    pthread_cond_broadcast(&g_work);
    pthread_mutex_unlock(&g_lock);
    for (i = 0; i < n; i++) {
        pthread_join(g_threads[i], NULL);
    }
}

int afs_on_worker_thread(void)
{
    return g_is_worker;
}