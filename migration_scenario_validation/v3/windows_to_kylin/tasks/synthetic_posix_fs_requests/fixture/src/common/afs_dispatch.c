/*
 * Shared request layer: dispatch, completion accounting and request cleanup.
 * Nothing in this file is platform specific.
 */
#include "afs.h"
#include "afs_platform.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>

struct afs_priv {
    char *path;
    struct iovec *iov;
};

afs_req *afs_req_new(int op)
{
    afs_req *req = (afs_req *)calloc(1, sizeof(*req));
    if (req) {
        req->op = op;
        req->fd = -1;
        req->offset = -1;
    }
    return req;
}

void afs_req_free(afs_req *req)
{
    struct afs_priv *priv;
    if (!req) {
        return;
    }
    priv = (struct afs_priv *)req->_priv;
    if (priv) {
        free(priv->path);
        free(priv->iov);
        free(priv);
    }
    free(req->out_path);
    free(req);
}

int afs_dispatch(afs_req *req)
{
    int rc = -1;

    errno = 0;
    switch (req->op) {
    case AFS_OP_OPEN:
        rc = afs__open(req);
        break;
    case AFS_OP_CLOSE:
        rc = afs__close(req);
        break;
    case AFS_OP_READ:
        rc = afs__read(req);
        break;
    case AFS_OP_WRITE:
        rc = afs__write(req);
        break;
    case AFS_OP_STAT:
        rc = afs__stat(req);
        break;
    case AFS_OP_READLINK:
        rc = afs__readlink(req);
        break;
    case AFS_OP_TEMP:
        rc = afs__temp(req);
        break;
    default:
        errno = EINVAL;
        rc = -1;
        break;
    }
    if (rc < 0) {
        req->err = errno ? errno : EIO;
        req->result = -req->err;
        return req->result;
    }
    req->err = 0;
    req->result = rc;
    return rc;
}

/* Copy the caller-owned inputs so an asynchronous request is self-contained. */
int afs_prepare_async(afs_req *req)
{
    struct afs_priv *priv;

    if (!req->path && req->niov == 0) {
        return 0;
    }
    priv = (struct afs_priv *)calloc(1, sizeof(*priv));
    if (!priv) {
        return 0;
    }
    req->_priv = priv;
    if (req->path) {
        priv->path = strdup(req->path);
        if (!priv->path) {
            return 0;
        }
        req->path = priv->path;
    }
    if (req->niov && req->iov) {
        priv->iov = (struct iovec *)malloc(sizeof(struct iovec) * req->niov);
        if (!priv->iov) {
            return 0;
        }
        memcpy(priv->iov, req->iov, sizeof(struct iovec) * req->niov);
        req->iov = priv->iov;
    }
    return 1;
}