#ifndef AFS_H
#define AFS_H

#include <stddef.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/uio.h>

/*
 * Public request model of the asynchronous file-system layer.
 *
 * A request is a plain struct the caller fills in and submits.  A submission
 * without a callback runs the operation inline and returns its result.  A
 * submission with a callback is queued on the worker pool, returns 0, and the
 * callback runs on a worker thread once the operation finished.
 *
 * Every operation reports its outcome twice:
 *   result   non-negative byte count / descriptor / 0 on success,
 *            -(errno) on failure;
 *   err      the positive errno of a failure, 0 on success.
 *
 * Ownership:
 *   - the submission call borrows path and the iovec array; the asynchronous
 *     path copies them into the request before it returns, so the caller may
 *     reuse or mutate its own storage immediately;
 *   - out_stat is caller storage borrowed until the callback runs;
 *   - out_path is allocated by the backend and released by afs_req_free();
 *   - out_buf/out_cap are caller storage for readlink results.
 */

typedef struct afs_req afs_req;
typedef void (*afs_cb)(afs_req *req);

enum afs_op {
    AFS_OP_OPEN = 1,
    AFS_OP_CLOSE,
    AFS_OP_READ,
    AFS_OP_WRITE,
    AFS_OP_STAT,
    AFS_OP_READLINK,
    AFS_OP_TEMP
};

/* access and disposition bits for AFS_OP_OPEN */
#define AFS_OPEN_READ   0x01
#define AFS_OPEN_WRITE  0x02
#define AFS_OPEN_CREATE 0x04
#define AFS_OPEN_EXCL   0x08
#define AFS_OPEN_TRUNC  0x10

struct afs_req {
    int op;
    int flags;
    int fd;
    const struct iovec *iov;
    unsigned niov;
    long long offset;      /* negative: use the descriptor position */
    const char *path;
    char *out_path;        /* backend-owned, released by afs_req_free() */
    struct stat *out_stat; /* caller storage, borrowed until the callback */
    char *out_buf;         /* caller storage for readlink */
    size_t out_cap;
    int result;
    int err;
    afs_cb cb;
    void *data;
    void *_priv;           /* shared request layer */
};

afs_req *afs_req_new(int op);
void afs_req_free(afs_req *req);

/*
 * Submit a request.  Without a callback the operation runs inline and the
 * function returns its result; with a callback the request is queued, the
 * function returns 0, and the request must stay alive until the callback.
 */
int afs_submit(afs_req *req);

void afs_pool_start(unsigned workers);
void afs_pool_drain(void);
void afs_pool_stop(void);
int afs_on_worker_thread(void);

#endif /* AFS_H */