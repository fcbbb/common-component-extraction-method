/*
 * Public self-test: the basic request-model behaviour every call site
 * relies on.  The hidden probe exercises the full contract.
 */
#include "afs.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int failures;

#define CHECK(cond, msg)                                                     \
    do {                                                                     \
        if (!(cond)) {                                                       \
            fprintf(stderr, "selftest: %s (line %d)\n", (msg), __LINE__);     \
            failures++;                                                      \
        }                                                                    \
    } while (0)

int main(int argc, char **argv)
{
    char root[256];
    char path[320];
    afs_req *req;
    char buffer[32];

    if (argc > 1) {
        snprintf(root, sizeof(root), "%s", argv[1]);
    } else {
        snprintf(root, sizeof(root), ".");
    }
    snprintf(path, sizeof(path), "%s/afs_selftest.txt", root);

    {
        struct iovec iov[2];
        const char *parts[2] = {"hello ", "world\n"};
        int fd;

        req = afs_req_new(AFS_OP_OPEN);
        req->path = path;
        req->flags = AFS_OPEN_WRITE | AFS_OPEN_CREATE | AFS_OPEN_TRUNC;
        CHECK(afs_submit(req) >= 0, "open for write");
        CHECK(req->err == 0, "open err");
        fd = req->result;

        iov[0].iov_base = (void *)parts[0];
        iov[0].iov_len = strlen(parts[0]);
        iov[1].iov_base = (void *)parts[1];
        iov[1].iov_len = strlen(parts[1]);

        req->op = AFS_OP_WRITE;
        req->fd = fd;
        req->iov = iov;
        req->niov = 2;
        CHECK(afs_submit(req) == 12, "write count");

        req->op = AFS_OP_CLOSE;
        req->fd = fd;
        CHECK(afs_submit(req) == 0, "close");
        afs_req_free(req);
    }

    {
        req = afs_req_new(AFS_OP_OPEN);
        req->path = path;
        req->flags = AFS_OPEN_READ;
        CHECK(afs_submit(req) >= 0, "open for read");
        memset(buffer, 0, sizeof(buffer));
        {
            struct iovec iov;
            iov.iov_base = buffer;
            iov.iov_len = sizeof(buffer) - 1;
            req->op = AFS_OP_READ;
            req->fd = req->result;
            req->iov = &iov;
            req->niov = 1;
            CHECK(afs_submit(req) == 12, "read count");
        }
        CHECK(strcmp(buffer, "hello world\n") == 0, "read content");
        afs_req_free(req);
    }

    {
        struct stat info;
        req = afs_req_new(AFS_OP_STAT);
        req->path = path;
        req->out_stat = &info;
        CHECK(afs_submit(req) == 0, "stat");
        CHECK(info.st_size == 12, "stat size");
        afs_req_free(req);
    }

    unlink(path);
    if (failures) {
        fprintf(stderr, "AFS_SELFTEST=FAIL count=%d\n", failures);
        return 1;
    }
    printf("AFS_SELFTEST=PASS\n");
    return 0;
}