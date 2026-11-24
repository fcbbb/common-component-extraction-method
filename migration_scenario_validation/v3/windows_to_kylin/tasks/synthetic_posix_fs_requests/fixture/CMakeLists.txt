cmake_minimum_required(VERSION 3.10)
project(afs_requests C)

set(CMAKE_C_STANDARD 99)

set(AFS_SOURCES
  src/common/afs_dispatch.c
  src/common/afs_pool.c
)

if(WIN32)
  list(APPEND AFS_SOURCES src/win32/afs_win32.c)
else()
  list(APPEND AFS_SOURCES src/posix/afs_posix.c)
endif()

find_package(Threads REQUIRED)

add_library(afs STATIC ${AFS_SOURCES})
target_include_directories(afs PUBLIC include src/common)
target_link_libraries(afs PUBLIC Threads::Threads)

add_executable(afs_selftest tests/test_afs.c)
target_link_libraries(afs_selftest PRIVATE afs)

enable_testing()
add_test(NAME afs_selftest COMMAND afs_selftest)