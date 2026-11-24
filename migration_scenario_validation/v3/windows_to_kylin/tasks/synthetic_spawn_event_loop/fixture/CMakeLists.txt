cmake_minimum_required(VERSION 3.10)
project(spl_event_loop C)

set(CMAKE_C_STANDARD 99)
add_compile_definitions(_GNU_SOURCE)

set(SPL_SOURCES
  src/common/spl_loop.c
)

if(WIN32)
  list(APPEND SPL_SOURCES src/win32/spl_process_win32.c)
else()
  list(APPEND SPL_SOURCES src/posix/spl_process_posix.c)
endif()

add_library(spl STATIC ${SPL_SOURCES})
target_include_directories(spl PUBLIC include src/common)

add_executable(spl_selftest tests/test_spl.c)
target_link_libraries(spl_selftest PRIVATE spl)

add_executable(splprobe helpers/splprobe.c)

enable_testing()
add_test(NAME spl_selftest COMMAND spl_selftest)