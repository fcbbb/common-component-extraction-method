/*
 * POSIX implementation of the asynchronous file-system request backend.
 *
 * Implements the platform layer declared in afs_platform.h on top of the
 * native descriptor, vector-I/O and metadata calls.
 */
#include "afs_platform.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* The kernel accepts at most IOV_MAX entries in one vector call.  The value
 * is queried at run time because it can differ between systems. */
static int iov_limit(void)
{
    long value = sysconf(_SC_IOV_MAX);
    if (value <= 0 || value > INT_MAX) {
        value = 1024;
    }
    return (int)value;
}

int afs__open(afs_req *req)
{
    int flags;

    if (!req->path || req->path[0] == '\0') {
        errno = EINVAL;
        return -1;
    }
    /* The Windows reference maps a request with neither access bit, and one
     * with both, to read/write access. */
    switch (req->flags & (AFS_OPEN_READ | AFS_OPEN_WRITE)) {
    case AFS_OPEN_READ:
        flags = O_RDONLY;
        break;
    case AFS_OPEN_WRITE:
        flags = O_WRONLY;
        break;
    default:
        flags = O_RDWR;
        break;
    }
    if (req->flags & AFS_OPEN_CREATE) {
        flags |= O_CREAT;
    }
    if (req->flags & AFS_OPEN_EXCL) {
        flags |= O_EXCL;
    }
    if (req->flags & AFS_OPEN_TRUNC) {
        flags |= O_TRUNC;
    }
    /* Every descriptor the library creates is close-on-exec so a concurrent
     * child never inherits it. */
    flags |= O_CLOEXEC;
    return open(req->path, flags, 0666);
}

int afs__close(afs_req *req)
{
    int rc;

    if (req->fd < 0) {
        errno = EINVAL;
        return -1;
    }
    rc = close(req->fd);
    if (rc < 0 && errno == EINTR) {
        /* On POSIX the descriptor is already released when close reports an
         * interruption; this is not a failure. */
        return 0;
    }
    return rc;
}

/*
 * Write the whole vector list.  Vector calls may transfer fewer bytes than
 * requested and may be interrupted; both are handled by advancing a cursor
 * across the list and retrying.  Each vector call carries at most IOV_MAX
 * entries, so a list of any length is transferred completely.
 */
static long long write_all(int fd, const struct iovec *iov, unsigned niov,
                           long long offset, int *saved_errno)
{
    int limit = iov_limit();
    struct iovec *batch;
    unsigned cur = 0;
    size_t skip = 0;
    long long total = 0;

    batch = (struct iovec *)malloc(sizeof(*batch) * (size_t)limit);
    if (!batch) {
        *saved_errno = ENOMEM;
        return -1;
    }
    while (cur < niov) {
        int count = 0;
        unsigned index = cur;
        size_t prefix = skip;
        ssize_t written;

        while (index < niov && count < limit) {
            size_t length = iov[index].iov_len;

            if (prefix > 0) {
                if (prefix >= length) {
                    prefix -= length;
                    index++;
                    continue;
                }
                batch[count].iov_base = (char *)iov[index].iov_base + prefix;
                batch[count].iov_len = length - prefix;
                prefix = 0;
            } else {
                batch[count] = iov[index];
            }
            if (batch[count].iov_len > 0) {
                count++;
            }
            index++;
        }
        if (count == 0) {
            break;
        }
        if (offset >= 0) {
            written = pwritev(fd, batch, count, (off_t)(offset + total));
        } else {
            written = writev(fd, batch, count);
        }
        if (written < 0) {
            if (errno == EINTR) {
                continue;
            }
            *saved_errno = errno;
            free(batch);
            return total > 0 ? total : -1;
        }
        if (written == 0) {
            *saved_errno = EIO;
            free(batch);
            return total > 0 ? total : -1;
        }
        total += written;
        {
            size_t remaining = (size_t)written;
            while (remaining > 0 && cur < niov) {
                size_t length = iov[cur].iov_len - skip;
                if (remaining >= length) {
                    remaining -= length;
                    cur++;
                    skip = 0;
                } else {
                    skip += remaining;
                    remaining = 0;
                }
            }
        }
    }
    free(batch);
    return total;
}

int afs__write(afs_req *req)
{
    int saved = 0;
    long long total;

    if (req->fd < 0) {
        errno = EINVAL;
        return -1;
    }
    if (req->niov > 0 && !req->iov) {
        errno = EINVAL;
        return -1;
    }
    total = write_all(req->fd, req->iov, req->niov, req->offset, &saved);
    if (total < 0) {
        errno = saved ? saved : EIO;
        return -1;
    }
    return (int)total;
}

int afs__read(afs_req *req)
{
    int limit = iov_limit();
    unsigned count;
    ssize_t got;

    if (req->fd < 0) {
        errno = EINVAL;
        return -1;
    }
    if (req->niov > 0 && !req->iov) {
        errno = EINVAL;
        return -1;
    }
    /* A read is one operation: only the first IOV_MAX buffers participate. */
    count = req->niov > (unsigned)limit ? (unsigned)limit : req->niov;
    if (req->offset >= 0) {
        got = preadv(req->fd, req->iov, (int)count, (off_t)req->offset);
    } else {
        got = readv(req->fd, req->iov, (int)count);
    }
    if (got < 0) {
        return -1;
    }
    return (int)got;
}

int afs__stat(afs_req *req)
{
    struct stat st;

    if (!req->path || !req->out_stat) {
        errno = EINVAL;
        return -1;
    }
    if (lstat(req->path, &st) < 0) {
        return -1;
    }
    *req->out_stat = st;
    return 0;
}

int afs__readlink(afs_req *req)
{
    ssize_t got;

    if (!req->path || !req->out_buf || req->out_cap == 0) {
        errno = EINVAL;
        return -1;
    }
    got = readlink(req->path, req->out_buf, req->out_cap);
    if (got < 0) {
        return -1;
    }
    return (int)got;
}

int afs__temp(afs_req *req)
{
    size_t length;
    char *template;
    int fd;

    if (!req->path) {
        errno = EINVAL;
        return -1;
    }
    length = strlen(req->path);
    if (length < 6 || strcmp(req->path + length - 6, "XXXXXX") != 0) {
        errno = EINVAL;
        return -1;
    }
    template = strdup(req->path);
    if (!template) {
        errno = ENOMEM;
        return -1;
    }
    fd = mkstemp(template);
    if (fd < 0) {
        int saved = errno;
        free(template);
        errno = saved;
        return -1;
    }
    (void)fcntl(fd, F_SETFD, FD_CLOEXEC);
    req->out_path = template;
    return fd;
}