cmake_minimum_required(VERSION 3.10)
project(saf_stft C)
set(HARNESS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/harness" CACHE PATH "Evaluator-only harness directory")

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Default build: no IPP, no VSIPL. It only succeeds once the source has been
# migrated (or the evaluator supplies the reference implementation).
option(USE_IPP  "Build against Intel IPP (golden generation)" OFF)
option(USE_GOLD "Build the reference VSIPL migration (evaluator only)" OFF)
option(BUILD_HIDDEN_TESTS "Build the evaluator-only hidden test" OFF)

set(IPP_ROOT   "" CACHE PATH "Intel IPP prefix (contains include/ and lib/)")
set(VSIPL_ROOT "" CACHE PATH "VSIPL prefix (contains include/ and lib/)")

if(USE_GOLD)
    set(SAF_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/gold/saf_utility_fft_vsipl.c)
else()
    file(GLOB SAF_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/*.c)
endif()

add_library(safft STATIC ${SAF_SOURCES})
target_include_directories(safft PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

if(USE_IPP)
    target_compile_definitions(safft PUBLIC SAF_USE_INTEL_IPP)
    target_include_directories(safft PUBLIC ${IPP_ROOT}/include)
    target_link_libraries(safft PUBLIC
        ${IPP_ROOT}/lib/shared/libipps.so
        ${IPP_ROOT}/lib/shared/libippcore.so)
endif()

# A migrated submission is src/*.c built against VSIPL; USE_GOLD only selects
# the reference file as the source.
if(VSIPL_ROOT)
    target_include_directories(safft PUBLIC ${VSIPL_ROOT}/include)
    target_link_libraries(safft PUBLIC ${VSIPL_ROOT}/lib/libvsip.a m)
endif()

if(BUILD_HIDDEN_TESTS)
    add_executable(hidden_test ${HARNESS_DIR}/hidden_test.c)
    target_link_libraries(hidden_test safft m)
endif()

enable_testing()
add_executable(public_test test/public_test.c)
target_link_libraries(public_test safft m)
add_test(NAME public_test COMMAND public_test)

if(USE_IPP OR USE_GOLD)
    add_executable(golden_gen ${HARNESS_DIR}/golden_gen.c)
    target_link_libraries(golden_gen safft m)
endif()