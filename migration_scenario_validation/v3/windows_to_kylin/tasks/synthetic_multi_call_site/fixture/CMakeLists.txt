cmake_minimum_required(VERSION 3.10)
project(mc_multi_call_site C)

set(MC_SOURCES
  src/common/mc_util.c
)

if(WIN32)
  list(APPEND MC_SOURCES src/win32/mc_platform_win32.c)
else()
  list(APPEND MC_SOURCES src/posix/mc_platform_posix.c)
endif()

add_library(mc_platform STATIC ${MC_SOURCES})
target_include_directories(mc_platform PUBLIC include src/common)

foreach(app mcdump mccount mccopy mctail)
  add_executable(${app} apps/${app}.c)
  target_link_libraries(${app} PRIVATE mc_platform)
endforeach()

add_executable(test_platform tests/test_platform.c)
target_link_libraries(test_platform PRIVATE mc_platform)

enable_testing()
add_test(NAME platform COMMAND test_platform)