/*
 * Hidden probe for the asynchronous file-system request backend.
 *
 * Compiled by harness/afs_probe.sh against the produced static library.  It
 * checks the parts of the request contract that call sites depend on: vector
 * limits, interrupted and short transfers, descriptor hygiene at open,
 * asynchronous execution on the worker pool, and the error convention.
 */
#include "afs.h"

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/uio.h>
#include <unistd.h>

static int failures;

#define CHECK(cond, ...)                                                     \
    do {                                                                     \
        if (!(cond)) {                                                       \
            fprintf(stderr, "deep: ");                                       \
            fprintf(stderr, __VA_ARGS__);                                    \
            fprintf(stderr, " (line %d)\n", __LINE__);                       \
            failures++;                                                      \
        }                                                                    \
    } while (0)

static char g_dir[512];

static void path_of(char *out, size_t cap, const char *name)
{
    snprintf(out, cap, "%s/%s", g_dir, name);
}

static int write_file(const char *path, const char *data, size_t length)
{
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    size_t done = 0;

    if (fd < 0) {
        return -1;
    }
    while (done < length) {
        ssize_t n = write(fd, data + done, length - done);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            close(fd);
            return -1;
        }
        done += (size_t)n;
    }
    return close(fd);
}

static ssize_t read_file(const char *path, char *buffer, size_t capacity)
{
    int fd = open(path, O_RDONLY);
    size_t done = 0;

    if (fd < 0) {
        return -1;
    }
    while (done < capacity) {
        ssize_t n = read(fd, buffer + done, capacity - done);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            close(fd);
            return -1;
        }
        if (n == 0) {
            break;
        }
        done += (size_t)n;
    }
    close(fd);
    return (ssize_t)done;
}

static int open_afs(const char *path, int flags)
{
    afs_req *req = afs_req_new(AFS_OP_OPEN);
    int result;

    req->path = path;
    req->flags = flags;
    afs_submit(req);
    result = req->result;
    afs_req_free(req);
    return result;
}

static int close_afs(int fd)
{
    afs_req *req = afs_req_new(AFS_OP_CLOSE);
    int result;

    req->fd = fd;
    afs_submit(req);
    result = req->result;
    afs_req_free(req);
    return result;
}

static void test_iovec_limits(char *scratch)
{
    const unsigned big = 1500;
    const size_t chunk = 4;
    char part[5] = "abcd";
    char *path = NULL;
    struct iovec *iov;
    unsigned i;
    int fd;
    int result;
    char *content;
    long limit;

    path = malloc(strlen(scratch) + 32);
    snprintf(path, strlen(scratch) + 32, "%s/vector.bin", scratch);

    iov = calloc(big, sizeof(*iov));
    for (i = 0; i < big; i++) {
        iov[i].iov_base = part;
        iov[i].iov_len = chunk;
    }

    fd = open_afs(path, AFS_OPEN_WRITE | AFS_OPEN_CREATE | AFS_OPEN_TRUNC);
    CHECK(fd >= 0, "vector open failed: %s", strerror(errno));
    {
        afs_req *req = afs_req_new(AFS_OP_WRITE);
        req->fd = fd;
        req->iov = iov;
        req->niov = big;
        req->offset = 0;
        result = afs_submit(req);
        CHECK(result == (int)(big * chunk),
              "vector write transferred %d of %u bytes", result, big * (unsigned)chunk);
        afs_req_free(req);
    }
    close_afs(fd);

    {
        struct stat info;
        CHECK(stat(path, &info) == 0 && info.st_size == (off_t)(big * chunk),
              "vector write size is %lld", (long long)info.st_size);
    }
    content = malloc(big * chunk);
    CHECK(read_file(path, content, big * chunk) == (ssize_t)(big * chunk),
          "vector file read-back failed");
    for (i = 0; i + 4 <= big * chunk; i += 4) {
        if (memcmp(content + i, part, 4) != 0) {
            CHECK(0, "vector write content differs at %u", i);
            break;
        }
    }
    free(content);
    free(path);
    free(iov);

    /* A read vector longer than the platform's limit transfers only the
     * buffers up to that limit. */
    limit = sysconf(_SC_IOV_MAX);
    if (limit <= 0) {
        limit = 1024;
    }
    {
        size_t total = 1200;
        char *readpath = malloc(strlen(scratch) + 32);
        char *filedata = malloc(total);
        char **slots = malloc(total * sizeof(*slots));
        struct iovec *riov = calloc(total, sizeof(*riov));
        afs_req *req;
        ssize_t expect;

        snprintf(readpath, strlen(scratch) + 32, "%s/readvec.bin", scratch);
        memset(filedata, 'x', total);
        CHECK(write_file(readpath, filedata, total) == 0, "read-vector fixture");
        for (i = 0; i < total; i++) {
            slots[i] = calloc(1, 1);
            riov[i].iov_base = slots[i];
            riov[i].iov_len = 1;
        }
        fd = open_afs(readpath, AFS_OPEN_READ);
        req = afs_req_new(AFS_OP_READ);
        req->fd = fd;
        req->iov = riov;
        req->niov = (unsigned)total;
        req->offset = 0;
        result = afs_submit(req);
        expect = (ssize_t)(total < (size_t)limit ? total : (size_t)limit);
        CHECK(result == (int)expect,
              "long read vector transferred %d bytes, expected %d", result, (int)expect);
        for (i = 0; i < (unsigned)result; i++) {
            if (*slots[i] != 'x') {
                CHECK(0, "long read vector slot %u not filled", i);
                break;
            }
        }
        if ((unsigned)result < total) {
            CHECK(*slots[result] == 0, "read beyond the vector limit wrote into a buffer");
        }
        afs_req_free(req);
        close_afs(fd);
        for (i = 0; i < total; i++) {
            free(slots[i]);
        }
        free(riov);
        free(slots);
        free(filedata);
        free(readpath);
    }
}

static void test_offsets(char *scratch)
{
    char path[600];
    char fixture[16] = "abcdefghij";
    char buffer[16];
    struct iovec iov;
    afs_req *req;
    int fd;

    path_of(path, sizeof(path), "offsets.txt");
    CHECK(write_file(path, fixture, 10) == 0, "offset fixture");

    fd = open_afs(path, AFS_OPEN_READ);
    CHECK(fd >= 0, "offset open");
    memset(buffer, 0, sizeof(buffer));
    iov.iov_base = buffer;
    iov.iov_len = 3;
    req = afs_req_new(AFS_OP_READ);
    req->fd = fd;
    req->iov = &iov;
    req->niov = 1;
    req->offset = 5;
    CHECK(afs_submit(req) == 3 && memcmp(buffer, "fgh", 3) == 0,
          "positioned read returned the wrong bytes");
    CHECK(lseek(fd, 0, SEEK_CUR) == 0, "positioned read moved the descriptor");
    memset(buffer, 0, sizeof(buffer));
    req->offset = -1;
    CHECK(afs_submit(req) == 3 && memcmp(buffer, "abc", 3) == 0,
          "sequential read returned the wrong bytes");
    CHECK(lseek(fd, 0, SEEK_CUR) == 3, "sequential read did not advance the descriptor");
    afs_req_free(req);
    close_afs(fd);

    fd = open_afs(path, AFS_OPEN_WRITE);
    req = afs_req_new(AFS_OP_WRITE);
    req->fd = fd;
    iov.iov_base = (void *)"XY";
    iov.iov_len = 2;
    req->iov = &iov;
    req->niov = 1;
    req->offset = 2;
    CHECK(afs_submit(req) == 2, "positioned write");
    CHECK(lseek(fd, 0, SEEK_CUR) == 0, "positioned write moved the descriptor");
    afs_req_free(req);
    close_afs(fd);

    CHECK(read_file(path, buffer, sizeof(buffer)) == 10, "offset read-back");
    CHECK(memcmp(buffer, "abXYefghij", 10) == 0, "positioned write changed the wrong bytes");
}

static void test_errors(char *scratch)
{
    char missing[600];
    char path[600];
    char linkpath[600];
    char templ[700];
    char rw_path[600];
    struct iovec iov;
    char buffer[64];
    struct stat info;
    afs_req *req;
    int fd;

    path_of(missing, sizeof(missing), "does-not-exist");
    req = afs_req_new(AFS_OP_OPEN);
    req->path = missing;
    req->flags = AFS_OPEN_READ;
    CHECK(afs_submit(req) == -ENOENT && req->err == ENOENT, "missing open error");
    afs_req_free(req);

    /* Neither access bit means read/write access, exactly as the Windows
     * reference's flag mapping does, so a missing path reaches the platform
     * open and fails with ENOENT rather than an argument error. */
    req = afs_req_new(AFS_OP_OPEN);
    req->path = missing;
    req->flags = 0;
    CHECK(afs_submit(req) == -ENOENT && req->err == ENOENT,
          "open without access bits did not reach the platform");
    afs_req_free(req);

    path_of(rw_path, sizeof(rw_path), "open-read-write");
    req = afs_req_new(AFS_OP_OPEN);
    req->path = rw_path;
    req->flags = AFS_OPEN_CREATE | AFS_OPEN_WRITE | AFS_OPEN_TRUNC;
    CHECK(afs_submit(req) >= 0, "cannot create the read/write fixture");
    fd = req->result;
    afs_req_free(req);

    req = afs_req_new(AFS_OP_OPEN);
    req->path = rw_path;
    req->flags = 0;
    CHECK(afs_submit(req) >= 0 && req->result >= 0,
          "open without access bits is not read/write");
    if (req->result >= 0) {
        int rw_fd = req->result;
        char byte = 'x';
        struct iovec write_iov;
        afs_req_free(req);

        write_iov.iov_base = &byte;
        write_iov.iov_len = 1;
        req = afs_req_new(AFS_OP_WRITE);
        req->fd = rw_fd;
        req->iov = &write_iov;
        req->niov = 1;
        CHECK(afs_submit(req) == 1,
              "a write on a default-access descriptor failed");
        afs_req_free(req);

        req = afs_req_new(AFS_OP_CLOSE);
        req->fd = rw_fd;
        CHECK(afs_submit(req) >= 0, "cannot close the read/write fixture");
        afs_req_free(req);
    } else {
        afs_req_free(req);
    }

    req = afs_req_new(AFS_OP_STAT);
    req->path = missing;
    req->out_stat = &info;
    CHECK(afs_submit(req) == -ENOENT, "missing stat error");
    afs_req_free(req);

    fd = open(g_dir, O_RDONLY | O_DIRECTORY);
    CHECK(fd >= 0, "cannot open scratch directory");
    req = afs_req_new(AFS_OP_READ);
    req->fd = fd;
    iov.iov_base = buffer;
    iov.iov_len = 8;
    req->iov = &iov;
    req->niov = 1;
    CHECK(afs_submit(req) == -EISDIR && req->err == EISDIR, "read on a directory");
    afs_req_free(req);
    close(fd);

    path_of(path, sizeof(path), "regular.txt");
    CHECK(write_file(path, "data", 4) == 0, "regular fixture");
    req = afs_req_new(AFS_OP_READLINK);
    req->path = path;
    req->out_buf = buffer;
    req->out_cap = sizeof(buffer);
    CHECK(afs_submit(req) == -EINVAL, "readlink on a regular file");
    afs_req_free(req);

    path_of(linkpath, sizeof(linkpath), "symlink");
    unlink(linkpath);
    CHECK(symlink("target.txt", linkpath) == 0, "symlink fixture");
    memset(buffer, 0, sizeof(buffer));
    req = afs_req_new(AFS_OP_READLINK);
    req->path = linkpath;
    req->out_buf = buffer;
    req->out_cap = sizeof(buffer);
    CHECK(afs_submit(req) == 10, "readlink of a symlink");
    CHECK(memcmp(buffer, "target.txt", 10) == 0, "readlink returned a rewritten target");
    afs_req_free(req);

    snprintf(templ, sizeof(templ), "%s/bad-template", scratch);
    req = afs_req_new(AFS_OP_TEMP);
    req->path = templ;
    CHECK(afs_submit(req) == -EINVAL, "temporary template without the suffix");
    afs_req_free(req);

    snprintf(templ, sizeof(templ), "%s/tmpXXXXXX", scratch);
    req = afs_req_new(AFS_OP_TEMP);
    req->path = templ;
    fd = afs_submit(req);
    CHECK(fd >= 0, "temporary file creation");
    if (fd >= 0) {
        CHECK(req->out_path != NULL && access(req->out_path, F_OK) == 0,
              "temporary path is not usable");
        close(fd);
        if (req->out_path) {
            unlink(req->out_path);
        }
    }
    afs_req_free(req);
}

struct cb_ctx {
    int called;
    int on_worker;
    pthread_t thread;
    afs_req *req;
};

static void record_cb(afs_req *req)
{
    struct cb_ctx *ctx = (struct cb_ctx *)req->data;
    ctx->called++;
    ctx->on_worker = afs_on_worker_thread();
    ctx->thread = pthread_self();
    ctx->req = req;
}

static void test_async(char *scratch)
{
    char path[600];
    char copy_path[600];
    char *mutable_path;
    struct stat info;
    struct cb_ctx ctx;
    pthread_t main_thread = pthread_self();
    afs_req *req;
    int fd;

    path_of(path, sizeof(path), "async.bin");
    CHECK(write_file(path, "async-data", 10) == 0, "async fixture");
    path_of(copy_path, sizeof(copy_path), "async-copy.bin");
    CHECK(write_file(copy_path, "copied", 6) == 0, "async copy fixture");

    afs_pool_start(2);

    memset(&ctx, 0, sizeof(ctx));
    req = afs_req_new(AFS_OP_STAT);
    req->path = path;
    req->out_stat = &info;
    req->cb = record_cb;
    req->data = &ctx;
    CHECK(afs_submit(req) == 0, "asynchronous submission did not return 0");
    afs_pool_drain();
    CHECK(ctx.called == 1, "asynchronous callback ran %d times", ctx.called);
    CHECK(ctx.on_worker == 1, "asynchronous callback did not run on a worker thread");
    CHECK(!pthread_equal(ctx.thread, main_thread), "asynchronous callback ran on the loop thread");
    CHECK(req->result == 0 && req->err == 0, "asynchronous stat failed");
    CHECK(info.st_size == 10, "asynchronous stat size");
    afs_req_free(req);

    /* The asynchronous path must own a copy of the caller's path. */
    mutable_path = strdup(copy_path);
    CHECK(mutable_path != NULL, "out of memory");
    memset(&ctx, 0, sizeof(ctx));
    req = afs_req_new(AFS_OP_OPEN);
    req->path = mutable_path;
    req->flags = AFS_OPEN_READ;
    req->cb = record_cb;
    req->data = &ctx;
    CHECK(afs_submit(req) == 0, "asynchronous open submission");
    memset(mutable_path, 'Z', strlen(mutable_path));
    afs_pool_drain();
    CHECK(ctx.called == 1, "asynchronous open callback missed");
    fd = req->result;
    CHECK(fd >= 0, "asynchronous open used the mutated caller path");
    if (fd >= 0) {
        close(fd);
    }
    afs_req_free(req);
    free(mutable_path);
}

struct reader_arg {
    int fd;
    size_t want;
    size_t got;
    int failed;
};

static void *reader_main(void *opaque)
{
    struct reader_arg *arg = (struct reader_arg *)opaque;
    char buffer[65536];

    usleep(200000);
    while (arg->got < arg->want) {
        ssize_t n = read(arg->fd, buffer, sizeof(buffer));
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            arg->failed = 1;
            break;
        }
        if (n == 0) {
            break;
        }
        arg->got += (size_t)n;
    }
    return NULL;
}

struct ping_arg {
    pthread_t target;
};

static void ignore_signal(int signo)
{
    (void)signo;
}

static void *pinger_main(void *opaque)
{
    struct ping_arg *arg = (struct ping_arg *)opaque;
    int i;

    for (i = 0; i < 40; i++) {
        usleep(20000);
        pthread_kill(arg->target, SIGUSR1);
    }
    return NULL;
}

static void test_interrupted_write(void)
{
    const size_t total = 2u * 1024u * 1024u;
    const unsigned niov = 16;
    int pipefd[2];
    struct sigaction action;
    pthread_t reader_thread;
    pthread_t ping_thread;
    struct reader_arg reader;
    struct ping_arg ping;
    struct iovec iov[16];
    char *block;
    afs_req *req;
    int result;
    unsigned i;

    CHECK(pipe(pipefd) == 0, "pipe");
    memset(&action, 0, sizeof(action));
    action.sa_handler = ignore_signal;
    sigemptyset(&action.sa_mask);
    action.sa_flags = 0; /* deliberately no SA_RESTART */
    sigaction(SIGUSR1, &action, NULL);

    block = malloc(total / niov);
    memset(block, 'q', total / niov);
    for (i = 0; i < niov; i++) {
        iov[i].iov_base = block;
        iov[i].iov_len = total / niov;
    }

    memset(&reader, 0, sizeof(reader));
    reader.fd = pipefd[0];
    reader.want = total;
    pthread_create(&reader_thread, NULL, reader_main, &reader);

    ping.target = pthread_self();
    pthread_create(&ping_thread, NULL, pinger_main, &ping);

    req = afs_req_new(AFS_OP_WRITE);
    req->fd = pipefd[1];
    req->iov = iov;
    req->niov = niov;
    req->offset = -1;
    result = afs_submit(req);
    afs_req_free(req);

    CHECK(result == (int)total,
          "interrupted write reported %d of %zu bytes", result, total);
    close(pipefd[1]);
    pthread_join(ping_thread, NULL);
    pthread_join(reader_thread, NULL);
    CHECK(reader.failed == 0, "interrupted-write reader failed");
    CHECK(reader.got == total, "interrupted-write reader received %zu bytes", reader.got);
    close(pipefd[0]);
    free(block);
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: deep_probe <scratch-dir>\n");
        return 2;
    }
    snprintf(g_dir, sizeof(g_dir), "%s", argv[1]);
    mkdir(g_dir, 0777);

    test_iovec_limits(g_dir);
    test_offsets(g_dir);
    test_errors(g_dir);
    test_async(g_dir);
    test_interrupted_write();

    afs_pool_stop();

    if (failures) {
        fprintf(stderr, "AFS_DEEP=FAIL count=%d\n", failures);
        return 1;
    }
    printf("AFS_DEEP=PASS\n");
    return 0;
}