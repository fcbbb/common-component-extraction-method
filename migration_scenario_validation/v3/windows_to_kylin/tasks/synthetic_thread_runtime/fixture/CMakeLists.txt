cmake_minimum_required(VERSION 3.10)
project(thr_runtime C)

set(CMAKE_C_STANDARD 99)

if(WIN32)
  set(THR_SOURCES src/win32/thr_win32.c)
else()
  set(THR_SOURCES src/posix/thr_posix.c)
endif()

find_package(Threads REQUIRED)

add_library(thr STATIC ${THR_SOURCES})
target_include_directories(thr PUBLIC include)
target_link_libraries(thr PUBLIC Threads::Threads)

add_executable(thr_selftest tests/test_thr.c)
target_link_libraries(thr_selftest PRIVATE thr)

enable_testing()
add_test(NAME thr_selftest COMMAND thr_selftest)