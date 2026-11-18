cmake_minimum_required(VERSION 3.10)
project(iir_eq C)
set(HARNESS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/harness" CACHE PATH "Evaluator-only harness directory")

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

option(USE_IPP  "Build against Intel IPP (golden generation)" OFF)
option(USE_GOLD "Build the reference migration (evaluator only)" OFF)

set(IPP_ROOT   "" CACHE PATH "Intel IPP prefix (contains include/ and lib/)")
set(VSIPL_ROOT "" CACHE PATH "VSIPL prefix (contains include/ and lib/)")

if(USE_GOLD)
    set(IIR_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/gold/iir_eq_c.c)
else()
    file(GLOB IIR_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/*.c)
endif()

add_library(iireq STATIC ${IIR_SOURCES})
target_include_directories(iireq PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

if(USE_IPP)
    target_include_directories(iireq PUBLIC ${IPP_ROOT}/include)
    target_link_libraries(iireq PUBLIC
        ${IPP_ROOT}/lib/shared/libipps.so
        ${IPP_ROOT}/lib/shared/libippcore.so)
endif()

# This task is a negative control: VSIPL has no IIR, so a correct migration
# does not link VSIPL at all.  VSIPL_ROOT is still accepted so the same
# evaluator driver works across tasks.
if(VSIPL_ROOT)
    target_include_directories(iireq PUBLIC ${VSIPL_ROOT}/include)
    target_link_libraries(iireq PUBLIC ${VSIPL_ROOT}/lib/libvsip.a m)
endif()

if(BUILD_HIDDEN_TESTS)
    add_executable(hidden_test ${HARNESS_DIR}/hidden_test.c)
    target_link_libraries(hidden_test iireq m)
endif()

enable_testing()
add_executable(public_test test/public_test.c)
target_link_libraries(public_test iireq m)
add_test(NAME public_test COMMAND public_test)

if(USE_IPP OR USE_GOLD)
    add_executable(golden_gen ${HARNESS_DIR}/golden_gen.c)
    target_link_libraries(golden_gen iireq m)
endif()