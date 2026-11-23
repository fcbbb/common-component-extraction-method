cmake_minimum_required(VERSION 3.16)
project(s3_channelizer C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

option(USE_IPP  "Build the original IPP implementation" OFF)
option(USE_GOLD "Build the reference VSIPL implementation" OFF)
option(BUILD_HIDDEN_TESTS "Build the evaluator-only hidden test" OFF)

set(IPP_ROOT   "" CACHE PATH "Intel IPP prefix")
set(VSIPL_ROOT "" CACHE PATH "VSIPL prefix")
set(HARNESS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/harness" CACHE PATH "Evaluator-only harness")

if(USE_GOLD)
  set(CORE_SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/gold/state_vsipl.c
    ${CMAKE_CURRENT_SOURCE_DIR}/gold/mixer_vsipl.c
    ${CMAKE_CURRENT_SOURCE_DIR}/gold/fir_vsipl.c
    ${CMAKE_CURRENT_SOURCE_DIR}/gold/stats_vsipl.c)
else()
  set(CORE_SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/src/state_ipp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/src/mixer_ipp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/src/fir_ipp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/src/stats_ipp.c)
endif()

add_library(channelizer STATIC ${CORE_SOURCES})
target_include_directories(channelizer PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/src)

if(USE_IPP)
  target_compile_definitions(channelizer PUBLIC CHANNELIZER_USE_IPP=1)
  target_include_directories(channelizer PUBLIC ${IPP_ROOT}/include)
  target_link_libraries(channelizer PUBLIC
    ${IPP_ROOT}/lib/shared/libipps.so
    ${IPP_ROOT}/lib/shared/libippcore.so)
endif()

if(USE_GOLD OR VSIPL_ROOT)
  if(NOT VSIPL_ROOT)
    message(FATAL_ERROR "VSIPL_ROOT is required for the VSIPL build")
  endif()
  target_include_directories(channelizer PUBLIC ${VSIPL_ROOT}/include)
  target_link_libraries(channelizer PUBLIC ${VSIPL_ROOT}/lib/libvsip.a m)
endif()

enable_testing()
add_executable(public_test test/public_test.c)
target_link_libraries(public_test channelizer m)
add_test(NAME public_test COMMAND public_test)

if(BUILD_HIDDEN_TESTS)
  add_executable(hidden_test ${HARNESS_DIR}/hidden_test.c)
  target_link_libraries(hidden_test channelizer m)
endif()