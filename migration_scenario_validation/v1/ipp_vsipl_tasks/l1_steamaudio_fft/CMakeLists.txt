cmake_minimum_required(VERSION 3.10)
project(steamaudio_fft CXX)
set(HARNESS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/harness" CACHE PATH "Evaluator-only harness directory")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(USE_IPP  "Build against Intel IPP (golden generation)" OFF)
option(USE_GOLD "Build the reference VSIPL migration (evaluator only)" OFF)
option(BUILD_HIDDEN_TESTS "Build the evaluator-only hidden test" OFF)

set(IPP_ROOT   "" CACHE PATH "Intel IPP prefix (contains include/ and lib/)")
set(VSIPL_ROOT "" CACHE PATH "VSIPL prefix (contains include/ and lib/)")

if(USE_GOLD)
    set(FFT_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/gold/fft_vsipl.cpp)
else()
    set(FFT_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/ipp_fft.cpp)
endif()

add_library(safft STATIC
    ${FFT_SOURCES}
    ${CMAKE_CURRENT_SOURCE_DIR}/support/math_functions.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/support/memory_allocator.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/support/globals.cpp)
target_include_directories(safft PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/support)

if(USE_IPP)
    target_compile_definitions(safft PUBLIC IPL_ENABLE_IPP)
    target_include_directories(safft PUBLIC ${IPP_ROOT}/include)
    target_link_libraries(safft PUBLIC
        ${IPP_ROOT}/lib/shared/libipps.so
        ${IPP_ROOT}/lib/shared/libippcore.so)
endif()

# A migrated submission is src/ipp_fft.cpp replaced by a VSIPL implementation;
# USE_GOLD only selects the reference file as the source.
if(VSIPL_ROOT)
    target_include_directories(safft PUBLIC ${VSIPL_ROOT}/include)
    target_link_libraries(safft PUBLIC ${VSIPL_ROOT}/lib/libvsip.a m)
endif()

if(BUILD_HIDDEN_TESTS)
    add_executable(hidden_test ${HARNESS_DIR}/hidden_test.cpp)
    target_link_libraries(hidden_test safft)
endif()

enable_testing()
add_executable(public_test test/public_test.cpp)
target_link_libraries(public_test safft)
add_test(NAME public_test COMMAND public_test)

if(USE_IPP OR USE_GOLD)
    add_executable(golden_gen ${HARNESS_DIR}/golden_gen.cpp)
    target_link_libraries(golden_gen safft)
endif()