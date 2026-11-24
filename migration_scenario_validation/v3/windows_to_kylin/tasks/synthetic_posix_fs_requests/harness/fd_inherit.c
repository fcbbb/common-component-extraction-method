/*
 * Prints OPENFD=<descriptor> for a descriptor opened through the library and
 * writes the child's descriptor listing to argv[2].  Used by the hidden probe
 * to check that descriptors created by the library are close-on-exec.
 */
#include "afs.h"

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

#define OCCUPIED 24

int main(int argc, char **argv)
{
    afs_req *req;
    int padded[OCCUPIED];
    int fd;
    int i;
    char command[600];

    if (argc < 3) {
        fprintf(stderr, "usage: fd_inherit <file> <listing-output>\n");
        return 2;
    }

    /*
     * Occupy the low descriptor numbers with close-on-exec placeholders so the
     * library's descriptor lands above them.  After exec the placeholders are
     * gone and the listing tool's own directory descriptor takes a low number,
     * so the library's descriptor number cannot collide with it.
     */
    for (i = 0; i < OCCUPIED; i++) {
        padded[i] = open("/dev/null", O_RDONLY | O_CLOEXEC);
        if (padded[i] < 0) {
            fprintf(stderr, "fd_inherit: cannot pad descriptors\n");
            return 1;
        }
    }

    req = afs_req_new(AFS_OP_OPEN);
    req->path = argv[1];
    req->flags = AFS_OPEN_READ;
    fd = afs_submit(req);
    afs_req_free(req);
    if (fd < 0) {
        fprintf(stderr, "fd_inherit: open failed\n");
        return 1;
    }

    printf("OPENFD=%d\n", fd);
    fflush(stdout);

    snprintf(command, sizeof(command), "ls /proc/self/fd > '%s'", argv[2]);
    if (system(command) != 0) {
        fprintf(stderr, "fd_inherit: listing command failed\n");
        return 1;
    }
    close(fd);
    for (i = 0; i < OCCUPIED; i++) {
        close(padded[i]);
    }
    return 0;
}