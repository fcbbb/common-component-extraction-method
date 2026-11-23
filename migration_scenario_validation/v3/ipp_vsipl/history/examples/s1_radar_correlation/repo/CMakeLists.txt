cmake_minimum_required(VERSION 3.16)
project(s1_radar_correlation C)

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
    ${CMAKE_CURRENT_SOURCE_DIR}/gold/plan_vsipl.c
    ${CMAKE_CURRENT_SOURCE_DIR}/gold/matched_filter_vsipl.c
    ${CMAKE_CURRENT_SOURCE_DIR}/gold/correlate_vsipl.c
    ${CMAKE_CURRENT_SOURCE_DIR}/gold/profile_vsipl.c)
else()
  set(CORE_SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/src/plan_ipp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/src/matched_filter_ipp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/src/correlate_ipp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/src/profile_ipp.c)
endif()

add_library(radar_correlation STATIC ${CORE_SOURCES})
target_include_directories(radar_correlation PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/src)

if(USE_IPP)
  target_compile_definitions(radar_correlation PUBLIC RADAR_USE_IPP=1)
  target_include_directories(radar_correlation PUBLIC ${IPP_ROOT}/include)
  target_link_libraries(radar_correlation PUBLIC
    ${IPP_ROOT}/lib/shared/libipps.so
    ${IPP_ROOT}/lib/shared/libippcore.so)
endif()

if(USE_GOLD OR VSIPL_ROOT)
  if(NOT VSIPL_ROOT)
    message(FATAL_ERROR "VSIPL_ROOT is required for the VSIPL build")
  endif()
  target_include_directories(radar_correlation PUBLIC ${VSIPL_ROOT}/include)
  target_link_libraries(radar_correlation PUBLIC ${VSIPL_ROOT}/lib/libvsip.a m)
endif()

enable_testing()
add_executable(public_test test/public_test.c)
target_link_libraries(public_test radar_correlation m)
add_test(NAME public_test COMMAND public_test)

if(BUILD_HIDDEN_TESTS)
  add_executable(hidden_test ${HARNESS_DIR}/hidden_test.c)
  target_link_libraries(hidden_test radar_correlation m)
endif()