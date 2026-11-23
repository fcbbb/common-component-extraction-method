/*
 * Evaluator-only checks for the removed nginx file-layer backend.
 *
 * The test links against the object built from the candidate
 * src/os/unix/ngx_files.c.  It targets backend decisions that a mechanical
 * translation of the Win32 file layer tends to miss:
 *
 *   - positioned reads and writes must not move the descriptor position;
 *   - a chain write must honour its offset and write every buffer;
 *   - a non-persistent temporary file is unlinked after opening;
 *   - open_dir clears valid_info, read_dir publishes the dirent type, and a
 *     regular file is rejected by open_dir;
 *   - set_file_time sets the modification time.
 *
 * The program is entered through a constructor so the test object can be
 * linked with the complete nginx object set without colliding with main().
 */

#define _GNU_SOURCE

#include <ngx_config.h>
#include <ngx_core.h>
#include <ngx_files.h>

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static int failures;

/*
 * Interpose the 64-bit positioned write so a signal-interrupted write can be
 * exercised deterministically.  A correct backend retries EINTR; one that
 * treats it as a hard error returns NGX_ERROR and fails the check below.
 */
static int pwrite_eintr_armed;
static off_t pwrite_eintr_offset;
static size_t pwrite_eintr_size;

static int pwrite_partial_armed;
static off_t pwrite_partial_offset;
static size_t pwrite_partial_size;

ssize_t pwrite64(int fd, const void* buf, size_t count, off64_t offset) {
  if (pwrite_eintr_armed && (off_t) offset == pwrite_eintr_offset
      && count == pwrite_eintr_size) {
    pwrite_eintr_armed = 0;
    errno = EINTR;
    return -1;
  }

  if (pwrite_partial_armed && (off_t) offset == pwrite_partial_offset
      && count == pwrite_partial_size) {
    pwrite_partial_armed = 0;
    return (ssize_t) syscall(SYS_pwrite64, fd, buf, 1, (off_t) offset);
  }

  return (ssize_t) syscall(SYS_pwrite64, fd, buf, count, (off_t) offset);
}

#define CHECK(cond, what)                                                     \
  do {                                                                        \
    if (!(cond)) {                                                            \
      fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, what);          \
      failures++;                                                             \
    }                                                                         \
  } while (0)

/*
 * A candidate can spin inside a write loop that never reaches its termination
 * condition.  The watchdog turns that into a bounded failure instead of a
 * judge timeout.
 */
static void timeout_handler(int sig) {
  static const char msg[] = "ngx_files sensitivity: timed out\n";

  (void) sig;
  (void) write(STDERR_FILENO, msg, sizeof(msg) - 1);
  _exit(3);
}

static void join(char* dst, size_t size, const char* dir, const char* name) {
  snprintf(dst, size, "%s/%s", dir, name);
}

static int write_file(const char* path, const char* data) {
  int fd;
  size_t len;
  ssize_t n;

  fd = open(path, O_CREAT | O_TRUNC | O_WRONLY, 0600);
  if (fd < 0)
    return -1;
  len = strlen(data);
  n = write(fd, data, len);
  if (close(fd) != 0)
    return -1;
  return n == (ssize_t) len ? 0 : -1;
}

static void init_file(ngx_file_t* file, ngx_log_t* log, int fd,
                      const char* path) {
  ngx_memzero(file, sizeof(*file));
  file->fd = fd;
  file->log = log;
  file->name.data = (u_char*) path;
  file->name.len = strlen(path);
}

static void test_read_file(const char* root) {
  char path[4096];
  u_char buf[8];
  ngx_file_t file;
  ngx_log_t log;
  int fd;
  ssize_t n;

  join(path, sizeof(path), root, "read-file");
  CHECK(write_file(path, "abcdefghijklmnopqrstuvwxyz") == 0,
        "read fixture is written");

  fd = open(path, O_RDWR);
  CHECK(fd >= 0, "read fixture opens");
  if (fd < 0)
    return;

  ngx_memzero(&log, sizeof(log));
  init_file(&file, &log, fd, path);

  ngx_memzero(buf, sizeof(buf));
  n = ngx_read_file(&file, buf, 5, 5);
  CHECK(n == 5, "read at an offset returns five bytes");
  CHECK(memcmp(buf, "fghij", 5) == 0, "read at an offset reads from it");
  CHECK(lseek(fd, 0, SEEK_CUR) == 0,
        "read at an offset leaves the descriptor position alone");
  CHECK(file.offset == 5, "read advances the logical file offset");
  CHECK(file.sys_offset == 0,
        "read at an offset does not advance the system offset");

  close(fd);
}

static void test_write_file(const char* root) {
  char path[4096];
  char check[4];
  ngx_file_t file;
  ngx_log_t log;
  int fd;
  ssize_t n;

  join(path, sizeof(path), root, "write-file");
  CHECK(write_file(path, "0123456789abcdefghij") == 0,
        "write fixture is written");

  fd = open(path, O_RDWR);
  CHECK(fd >= 0, "write fixture opens");
  if (fd < 0)
    return;

  ngx_memzero(&log, sizeof(log));
  init_file(&file, &log, fd, path);

  n = ngx_write_file(&file, (u_char*) "XYZ", 3, 10);
  CHECK(n == 3, "write at an offset writes three bytes");
  CHECK(lseek(fd, 0, SEEK_CUR) == 0,
        "write at an offset leaves the descriptor position alone");
  CHECK(file.offset == 3, "write advances the logical file offset");
  CHECK(file.sys_offset == 0,
        "write at an offset does not advance the system offset");

  ngx_memzero(check, sizeof(check));
  CHECK(pread(fd, check, 3, 10) == 3,
        "the positioned write can be read back");
  CHECK(memcmp(check, "XYZ", 3) == 0,
        "the positioned write lands at the requested offset");

  close(fd);
}

static void test_write_eintr(const char* root) {
  char path[4096];
  char check[4];
  ngx_file_t file;
  ngx_log_t log;
  int fd;
  ssize_t n;

  join(path, sizeof(path), root, "write-eintr");
  CHECK(write_file(path, "0123456789abcdefghij") == 0,
        "interrupted-write fixture is written");

  fd = open(path, O_RDWR);
  CHECK(fd >= 0, "interrupted-write fixture opens");
  if (fd < 0)
    return;

  ngx_memzero(&log, sizeof(log));
  init_file(&file, &log, fd, path);

  pwrite_eintr_armed = 0;
  pwrite_partial_armed = 0;
  pwrite_eintr_armed = 1;
  pwrite_eintr_offset = 10;
  pwrite_eintr_size = 3;

  n = ngx_write_file(&file, (u_char*) "XYZ", 3, 10);

  /* A backend that does not use the interposed symbol is still checked for
   * ordinary behavior by the positioned-write test above. */
  if (pwrite_eintr_armed == 0) {
    CHECK(n == 3, "write retries after an interrupted write");

    ngx_memzero(check, sizeof(check));
    CHECK(pread(fd, check, 3, 10) == 3,
          "the retried write can be read back");
    CHECK(memcmp(check, "XYZ", 3) == 0,
          "the retried write lands at the requested offset");
  }

  close(fd);
}

static void test_write_partial(const char* root) {
  char path[4096];
  char check[4];
  ngx_file_t file;
  ngx_log_t log;
  int fd;
  ssize_t n;

  join(path, sizeof(path), root, "write-partial");
  CHECK(write_file(path, "0123456789abcdefghij") == 0,
        "short-write fixture is written");

  fd = open(path, O_RDWR);
  CHECK(fd >= 0, "short-write fixture opens");
  if (fd < 0)
    return;

  ngx_memzero(&log, sizeof(log));
  init_file(&file, &log, fd, path);

  pwrite_eintr_armed = 0;
  pwrite_partial_armed = 0;
  pwrite_partial_armed = 1;
  pwrite_partial_offset = 10;
  pwrite_partial_size = 3;

  n = ngx_write_file(&file, (u_char*) "XYZ", 3, 10);

  if (pwrite_partial_armed == 0) {
    CHECK(n == 3, "write completes a short write");

    ngx_memzero(check, sizeof(check));
    CHECK(pread(fd, check, 3, 10) == 3,
          "the completed write can be read back");
    CHECK(memcmp(check, "XYZ", 3) == 0,
          "the completed write lands at the requested offset");
  }

  close(fd);
}

static void test_write_chain(const char* root) {
  char path[4096];
  char check[7];
  ngx_file_t file;
  ngx_log_t log;
  ngx_buf_t first_buf;
  ngx_buf_t second_buf;
  ngx_chain_t first;
  ngx_chain_t second;
  int fd;
  ssize_t n;

  join(path, sizeof(path), root, "write-chain");
  CHECK(write_file(path, "012345678901234567890123456789") == 0,
        "chain fixture is written");

  fd = open(path, O_RDWR);
  CHECK(fd >= 0, "chain fixture opens");
  if (fd < 0)
    return;

  ngx_memzero(&log, sizeof(log));
  init_file(&file, &log, fd, path);

  ngx_memzero(&first_buf, sizeof(first_buf));
  first_buf.pos = (u_char*) "ABC";
  first_buf.last = first_buf.pos + 3;
  ngx_memzero(&second_buf, sizeof(second_buf));
  second_buf.pos = (u_char*) "XYZ";
  second_buf.last = second_buf.pos + 3;

  first.buf = &first_buf;
  first.next = &second;
  second.buf = &second_buf;
  second.next = NULL;

  n = ngx_write_chain_to_file(&file, &first, 20, NULL);
  CHECK(n == 6, "chain write reports all six bytes");
  CHECK(lseek(fd, 0, SEEK_CUR) == 0,
        "chain write leaves the descriptor position alone");
  CHECK(file.offset == 6, "chain write advances the logical file offset");

  ngx_memzero(check, sizeof(check));
  CHECK(pread(fd, check, 6, 20) == 6, "the chain write can be read back");
  CHECK(memcmp(check, "ABCXYZ", 6) == 0,
        "the chain write lands at the requested offset");

  close(fd);
}

static void test_tempfile(const char* root) {
  char transient[4096];
  char persistent[4096];
  struct stat st;
  int fd;

  join(transient, sizeof(transient), root, "temp-transient");
  join(persistent, sizeof(persistent), root, "temp-persistent");

  fd = ngx_open_tempfile((u_char*) transient, 0, 0);
  CHECK(fd != NGX_INVALID_FILE, "a transient temporary file opens");
  if (fd != NGX_INVALID_FILE) {
    CHECK(fstat(fd, &st) == 0 && (st.st_mode & 0777) == 0600,
          "a transient temporary file uses mode 0600");
    CHECK(stat(transient, &st) == -1 && errno == ENOENT,
          "a transient temporary file is unlinked after opening");
    close(fd);
  }

  fd = ngx_open_tempfile((u_char*) persistent, 1, 0640);
  CHECK(fd != NGX_INVALID_FILE, "a persistent temporary file opens");
  if (fd != NGX_INVALID_FILE) {
    CHECK(stat(persistent, &st) == 0 && (st.st_mode & 0777) == 0640,
          "a persistent temporary file stays on disk with its mode");
    close(fd);
    unlink(persistent);
  }
}

static void test_directory(const char* root) {
  char dir[4096];
  char file[4096];
  char sub[4096];
  char link[4096];
  char child[4096];
  ngx_str_t name;
  ngx_dir_t handle;
  ngx_dir_t info;
  int saw_file;
  int saw_dir;
  int saw_link;

  join(dir, sizeof(dir), root, "dir");
  join(file, sizeof(file), dir, "entry-file");
  join(sub, sizeof(sub), dir, "entry-dir");
  join(link, sizeof(link), dir, "entry-link");

  CHECK(mkdir(dir, 0755) == 0, "the directory is created");
  CHECK(write_file(file, "x") == 0, "the directory file is created");
  CHECK(mkdir(sub, 0755) == 0, "the directory subdirectory is created");
  CHECK(symlink("entry-file", link) == 0, "the directory symlink is created");

  name.data = (u_char*) dir;
  name.len = strlen(dir);
  ngx_memzero(&handle, sizeof(handle));
  handle.valid_info = 1;
  CHECK(ngx_open_dir(&name, &handle) == NGX_OK, "open_dir succeeds");
  CHECK(handle.valid_info == 0, "open_dir clears valid_info");

  saw_file = 0;
  saw_dir = 0;
  saw_link = 0;

  while (ngx_read_dir(&handle) == NGX_OK) {
    const char* entry;

    entry = (const char*) handle.de->d_name;
    if (strcmp(entry, ".") == 0 || strcmp(entry, "..") == 0)
      continue;

    CHECK(handle.type == handle.de->d_type,
          "read_dir publishes the dirent type");

    join(child, sizeof(child), dir, entry);
    ngx_memzero(&info, sizeof(info));

    if (strcmp(entry, "entry-file") == 0) {
      saw_file = 1;
      CHECK(ngx_de_info((u_char*) child, &info) == 0,
            "de_info reads a regular file");
      CHECK(info.type == 0, "de_info clears the dirent type");
      CHECK(ngx_de_is_file(&info), "de_is_file identifies a regular file");
    }

    if (strcmp(entry, "entry-dir") == 0) {
      saw_dir = 1;
      CHECK(ngx_de_info((u_char*) child, &info) == 0,
            "de_info reads a directory");
      CHECK(ngx_de_is_dir(&info), "de_is_dir identifies a directory");
    }

    if (strcmp(entry, "entry-link") == 0) {
      saw_link = 1;
      info.type = 0;
      CHECK(ngx_de_link_info((u_char*) child, &info) == 0,
            "de_link_info reads a symbolic link");
      CHECK(ngx_de_is_link(&info), "de_is_link identifies a symbolic link");
    }
  }

  CHECK(handle.de == NULL, "read_dir reports the end of the directory");
  CHECK(saw_file && saw_dir && saw_link,
        "read_dir returns the file, directory and link entries");
  CHECK(ngx_close_dir(&handle) == 0, "close_dir succeeds");

  name.data = (u_char*) file;
  name.len = strlen(file);
  ngx_memzero(&info, sizeof(info));
  CHECK(ngx_open_dir(&name, &info) == NGX_ERROR,
        "open_dir rejects a regular file");
}

static void test_set_file_time(const char* root) {
  char path[4096];
  struct stat st;
  time_t mtime;
  int fd;

  join(path, sizeof(path), root, "set-time");
  CHECK(write_file(path, "time") == 0, "time fixture is written");

  fd = open(path, O_RDWR);
  CHECK(fd >= 0, "time fixture opens");
  if (fd < 0)
    return;

  mtime = (time_t) 1700000000;
  CHECK(ngx_set_file_time((u_char*) path, fd, mtime) == NGX_OK,
        "set_file_time succeeds");
  CHECK(stat(path, &st) == 0 && st.st_mtime == mtime,
        "set_file_time sets the modification time");

  close(fd);
}

static int run_all(void) {
  char root[] = "/tmp/ngx-files-sensitivity-XXXXXX";
  static ngx_time_t cached_time;

  signal(SIGALRM, timeout_handler);
  alarm(30);

  cached_time.sec = time(NULL);
  ngx_cached_time = &cached_time;

  if (mkdtemp(root) == NULL) {
    perror("mkdtemp");
    return 2;
  }

  test_read_file(root);
  test_write_file(root);
  test_write_eintr(root);
  test_write_partial(root);
  test_write_chain(root);
  test_tempfile(root);
  test_directory(root);
  test_set_file_time(root);

  if (failures != 0) {
    fprintf(stderr, "ngx_files sensitivity: %d failure(s)\n", failures);
    return 1;
  }

  printf("ngx_files sensitivity: all checks passed\n");
  return 0;
}

__attribute__((constructor)) static void sensitivity_entry(void) {
  int rc;

  rc = run_all();
  fflush(NULL);
  _exit(rc);
}