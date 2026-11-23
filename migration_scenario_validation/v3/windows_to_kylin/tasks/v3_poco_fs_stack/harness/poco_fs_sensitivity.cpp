//
// Evaluator-only checks for the removed Poco file stack.
//
// The program exercises behavior that a mechanical Win32 translation tends to
// miss: copy must finish every byte after an interrupted or short write and
// must leave a file intact when it is copied onto itself, links must be
// created at the requested path with the POSIX argument order, new files use
// the 0666 request mode, directory iteration hides dot entries, and the path
// and stream layers keep their observable contracts.
//

#include <Poco/DirectoryIterator.h>
#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/FileStream.h>
#include <Poco/Path.h>
#include <Poco/Timestamp.h>

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iostream>
#include <set>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

static int failures = 0;

#define CHECK(cond, what)                                                     \
  do {                                                                        \
    if (!(cond)) {                                                            \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, what);     \
      ++failures;                                                             \
    }                                                                         \
  } while (0)

static bool write_armed = false;
static bool write_eintr_done = false;
static bool write_short_done = false;
static std::string write_target;

static bool fd_matches_target(int fd);

extern "C" ssize_t write(int fd, const void* buf, size_t count) {
  if (write_armed && fd_matches_target(fd)) {
    if (!write_eintr_done) {
      write_eintr_done = true;
      errno = EINTR;
      return -1;
    }
    if (!write_short_done && count > 1) {
      write_short_done = true;
      return static_cast<ssize_t>(syscall(SYS_write, fd, buf, 1));
    }
  }
  return static_cast<ssize_t>(syscall(SYS_write, fd, buf, count));
}

static bool fd_matches_target(int fd) {
  char link[64];
  std::snprintf(link, sizeof(link), "/proc/self/fd/%d", fd);
  char target[4096];
  ssize_t n = readlink(link, target, sizeof(target) - 1);
  if (n <= 0) return false;
  target[n] = '\0';
  return write_target.size() <= static_cast<size_t>(n)
      && std::string(target + n - write_target.size()) == write_target;
}

static std::string join(const std::string& dir, const std::string& name) {
  return dir + "/" + name;
}

static void write_file(const std::string& path, const std::string& data) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  out.write(data.data(), static_cast<std::streamsize>(data.size()));
}

static std::string read_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  std::ostringstream data;
  data << in.rdbuf();
  return data.str();
}

static void test_copy_interrupted(const std::string& root) {
  const std::string src = join(root, "copy-src");
  const std::string dst = join(root, "copy-dst");
  std::string payload;
  payload.reserve(256 * 1024);
  for (int i = 0; i < 256 * 1024; ++i)
    payload.push_back(static_cast<char>('a' + (i % 23)));
  write_file(src, payload);

  write_target = "/copy-dst";
  write_armed = true;
  write_eintr_done = false;
  write_short_done = false;
  try {
    Poco::File(src).copyTo(dst);
  } catch (const Poco::Exception& exc) {
    std::fprintf(stderr, "FAIL copy threw: %s\n", exc.displayText().c_str());
    ++failures;
  }
  write_armed = false;

  CHECK(read_file(dst) == payload, "copy writes every byte after EINTR and a short write");
  CHECK(Poco::File(dst).getSize() == payload.size(), "copy produces the full size");
}

static void test_copy_onto_self(const std::string& root) {
  const std::string path = join(root, "copy-self");
  const std::string payload = "every byte of a file copied onto itself survives";
  write_file(path, payload);

  bool threw = false;
  try {
    Poco::File(path).copyTo(path);
  } catch (const Poco::Exception&) {
    threw = true;
  }
  CHECK(!threw, "copying a file onto itself succeeds");
  CHECK(read_file(path) == payload,
        "copying a file onto itself preserves its content");
  CHECK(Poco::File(path).getSize() == payload.size(),
        "copying a file onto itself preserves its size");
}

static void test_links(const std::string& root) {
  const std::string source = join(root, "link-source");
  const std::string hard = join(root, "link-hard");
  const std::string soft = join(root, "link-soft");
  write_file(source, "link-target");

  Poco::File original(source);
  original.linkTo(hard, Poco::File::LINK_HARD);
  original.linkTo(soft, Poco::File::LINK_SYMBOLIC);

  struct stat hard_st = {};
  CHECK(stat(hard.c_str(), &hard_st) == 0 && S_ISREG(hard_st.st_mode),
        "the hard link names a regular file");
  CHECK(hard_st.st_nlink == 2, "the hard link shares the source inode");

  struct stat soft_st = {};
  CHECK(lstat(soft.c_str(), &soft_st) == 0 && S_ISLNK(soft_st.st_mode),
        "the symbolic link exists at the requested path");
  char target[4096];
  ssize_t n = readlink(soft.c_str(), target, sizeof(target) - 1);
  CHECK(n > 0 && std::string(target, static_cast<size_t>(n)) == source,
        "the symbolic link points at the source path");
}

static void test_create_mode(const std::string& root) {
  const std::string path = join(root, "created-file");
  mode_t previous = umask(0);
  bool created = Poco::File(path).createFile();
  umask(previous);
  CHECK(created, "createFile creates a new file");
  struct stat st = {};
  CHECK(stat(path.c_str(), &st) == 0 && (st.st_mode & 0777) == 0666,
        "createFile requests mode 0666");
}

static void test_directory_iterator(const std::string& root) {
  const std::string dir = join(root, "iter-dir");
  Poco::File(dir).createDirectory();
  write_file(join(dir, "a-file"), "a");
  Poco::File(join(dir, "a-dir")).createDirectory();
  Poco::File(join(dir, "a-file")).linkTo(join(dir, "a-link"),
                                         Poco::File::LINK_SYMBOLIC);

  std::set<std::string> names;
  bool saw_file = false;
  bool saw_dir = false;
  bool saw_link = false;
  for (Poco::DirectoryIterator it(dir); it != Poco::DirectoryIterator(); ++it) {
    names.insert(it.name());
    if (it.name() == "a-file") saw_file = it->isFile();
    if (it.name() == "a-dir") saw_dir = it->isDirectory();
    if (it.name() == "a-link") saw_link = it->isLink();
  }
  CHECK(names.count(".") == 0 && names.count("..") == 0,
        "directory iteration hides dot entries");
  CHECK(names.size() == 3, "directory iteration returns every real entry");
  CHECK(saw_file, "directory iteration identifies a regular file");
  CHECK(saw_dir, "directory iteration identifies a directory");
  CHECK(saw_link, "directory iteration identifies a symbolic link");
}

static void test_timestamp(const std::string& root) {
  const std::string path = join(root, "timestamp");
  write_file(path, "time");
  Poco::File file(path);
  Poco::Timestamp wanted = Poco::Timestamp::fromEpochTime(1700000000);
  file.setLastModified(wanted);
  Poco::Timestamp actual = file.getLastModified();
  CHECK(std::llabs(actual.epochTime() - wanted.epochTime()) <= 1,
        "setLastModified updates the modification time");
}

static void test_path(const std::string& root) {
  (void) root;
  char cwd[4096];
  CHECK(getcwd(cwd, sizeof(cwd)) != nullptr, "getcwd succeeds");
  std::string current = Poco::Path::current();
  while (current.size() > 1 && current.back() == '/') current.pop_back();
  CHECK(current == cwd, "Path::current returns the working directory");
  std::string self = Poco::Path::self();
  CHECK(!self.empty() && self[0] == '/', "Path::self returns an absolute path");
  CHECK(Poco::File(self).exists(), "Path::self names an existing executable");
  CHECK(!Poco::Path::home().empty(), "Path::home is available");
}

static void test_file_stream(const std::string& root) {
  const std::string path = join(root, "stream");
  {
    Poco::FileStream out(path, std::ios::out | std::ios::trunc);
    out.write("abcdef", 6);
  }
  {
    Poco::FileStream in(path, std::ios::in);
    char buffer[4] = {0};
    in.read(buffer, 3);
    CHECK(std::string(buffer, 3) == "abc", "FileStream reads sequential bytes");
    in.seekg(2);
    char third = 0;
    in.get(third);
    CHECK(third == 'c', "FileStream seekg positions the read");
  }
}

static int run_all() {
  char root[] = "/tmp/poco-fs-sensitivity-XXXXXX";
  if (mkdtemp(root) == nullptr) {
    std::perror("mkdtemp");
    return 2;
  }
  test_copy_interrupted(root);
  test_copy_onto_self(root);
  test_links(root);
  test_create_mode(root);
  test_directory_iterator(root);
  test_timestamp(root);
  test_path(root);
  test_file_stream(root);
  return failures == 0 ? 0 : 1;
}

int main() {
  int rc = run_all();
  if (rc == 0) std::printf("poco fs sensitivity: all checks passed\n");
  return rc;
}