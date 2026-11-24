#ifndef AFS_PLATFORM_H
#define AFS_PLATFORM_H

#include "afs.h"

/*
 * Platform layer behind the public request model.  Only this layer differs
 * between Windows and the target system; the public header, the request
 * layer, the worker pool and the call sites stay fixed.
 *
 * Backend contract:
 *   - return the non-negative result on success;
 *   - return -1 with errno set on failure;
 *   - allocate out_path with malloc (the shared layer frees it);
 *   - never retain caller storage beyond the call.
 */

int afs__open(afs_req *req);
int afs__close(afs_req *req);
int afs__read(afs_req *req);
int afs__write(afs_req *req);
int afs__stat(afs_req *req);
int afs__readlink(afs_req *req);
int afs__temp(afs_req *req);

#endif /* AFS_PLATFORM_H */