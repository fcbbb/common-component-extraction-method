/*
 * Child program used by the public self-test and the hidden probe.
 */
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    const char *mode;

    if (argc < 2) {
        fprintf(stderr, "usage: splprobe <mode> [args]\n");
        return 2;
    }
    mode = argv[1];

    if (strcmp(mode, "split") == 0) {
        (void)!write(1, "OUT\n", 4);
        (void)!write(2, "ERR\n", 4);
        return 0;
    }
    if (strcmp(mode, "env") == 0) {
        const char *value = argc > 2 ? getenv(argv[2]) : NULL;
        printf("%s\n", value ? value : "UNSET");
        return 0;
    }
    if (strcmp(mode, "cwd") == 0) {
        char buffer[PATH_MAX];
        if (!getcwd(buffer, sizeof(buffer))) {
            return 3;
        }
        printf("%s\n", buffer);
        return 0;
    }
    if (strcmp(mode, "status") == 0) {
        return argc > 2 ? atoi(argv[2]) : 0;
    }
    if (strcmp(mode, "raise") == 0) {
        signal(SIGTERM, SIG_DFL);
        raise(SIGTERM);
        return 99;
    }
    if (strcmp(mode, "fds") == 0) {
        DIR *dir = opendir("/proc/self/fd");
        struct dirent *entry;
        if (!dir) {
            return 3;
        }
        while ((entry = readdir(dir)) != NULL) {
            if (strcmp(entry->d_name, ".") == 0 ||
                strcmp(entry->d_name, "..") == 0) {
                continue;
            }
            printf("FD %s\n", entry->d_name);
        }
        closedir(dir);
        return 0;
    }
    if (strcmp(mode, "pid") == 0) {
        printf("%d %d\n", (int)getpid(), (int)getsid(0));
        return 0;
    }
    if (strcmp(mode, "stdin") == 0) {
        char byte;
        ssize_t got;
        errno = 0;
        got = read(0, &byte, 1);
        printf("READ=%ld ERRNO=%d\n", (long)got, errno);
        return 0;
    }
    if (strcmp(mode, "argv") == 0) {
        int i;
        for (i = 2; i < argc; i++) {
            printf("%s|", argv[i]);
        }
        printf("\n");
        return 0;
    }
    if (strcmp(mode, "sleep") == 0) {
        unsigned seconds = argc > 2 ? (unsigned)atoi(argv[2]) : 1;
        sleep(seconds);
        return 0;
    }
    fprintf(stderr, "unknown mode: %s\n", mode);
    return 2;
}