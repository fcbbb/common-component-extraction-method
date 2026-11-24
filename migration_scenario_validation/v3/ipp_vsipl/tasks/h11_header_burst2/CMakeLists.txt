cmake_minimum_required(VERSION 3.16)
project(h11_header_burst2 C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

option(USE_IPP  "Build the original IPP implementation" OFF)
option(USE_GOLD "Build the reference VSIPL implementation" OFF)
option(BUILD_HIDDEN_TESTS "Build the evaluator-only hidden test" OFF)

set(IPP_ROOT   "" CACHE PATH "Intel IPP prefix")
set(VSIPL_ROOT "" CACHE PATH "VSIPL prefix")
set(HARNESS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/harness" CACHE PATH "Evaluator-only harness")

if(USE_GOLD)
  file(GLOB CORE_SOURCES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/gold/*.c)
else()
  file(GLOB CORE_SOURCES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/src/*.c)
endif()

add_library(burst_acq STATIC ${CORE_SOURCES})
target_include_directories(burst_acq PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/src)

if(USE_IPP)
  target_include_directories(burst_acq PUBLIC ${IPP_ROOT}/include)
  target_link_libraries(burst_acq PUBLIC
    ${IPP_ROOT}/lib/shared/libipps.so
    ${IPP_ROOT}/lib/libippcore.so)
endif()

if(USE_GOLD OR VSIPL_ROOT)
  if(NOT VSIPL_ROOT)
    message(FATAL_ERROR "VSIPL_ROOT is required for the VSIPL build")
  endif()
  target_include_directories(burst_acq PUBLIC ${VSIPL_ROOT}/include)
  target_link_libraries(burst_acq PUBLIC ${VSIPL_ROOT}/lib/libvsip.a m)
endif()

enable_testing()
add_executable(public_test test/public_test.c)
target_link_libraries(public_test burst_acq m)
add_test(NAME public_test COMMAND public_test)

if(BUILD_HIDDEN_TESTS)
  add_executable(hidden_test ${HARNESS_DIR}/hidden_test.c)
  target_link_libraries(hidden_test burst_acq m)
endif()