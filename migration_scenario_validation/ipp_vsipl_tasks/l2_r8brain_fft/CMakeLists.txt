cmake_minimum_required(VERSION 3.10)
project(r8brain_fft CXX)
set(HARNESS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/harness" CACHE PATH "Evaluator-only harness directory")

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Default build: no IPP, no VSIPL. It only succeeds once the source has been
# migrated (or the evaluator supplies the reference implementation).
option(USE_IPP  "Build against Intel IPP (golden generation)" OFF)
option(USE_GOLD "Build the reference VSIPL migration (evaluator only)" OFF)
option(BUILD_HIDDEN_TESTS "Build the evaluator-only hidden test" OFF)

set(IPP_ROOT   "" CACHE PATH "Intel IPP prefix (contains include/ and lib/)")
set(VSIPL_ROOT "" CACHE PATH "VSIPL prefix (contains include/ and lib/)")

if(USE_GOLD)
    set(FFT_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/gold/CDSPRealFFT_vsipl.cpp)
else()
    file(GLOB FFT_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp)
endif()

add_library(r8bfft STATIC ${FFT_SOURCES})
target_include_directories(r8bfft PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

if(USE_IPP)
    target_include_directories(r8bfft PUBLIC ${IPP_ROOT}/include)
    target_compile_definitions(r8bfft PUBLIC HAVE_IPP)
    target_link_libraries(r8bfft PUBLIC
        ${IPP_ROOT}/lib/shared/libipps.so
        ${IPP_ROOT}/lib/shared/libippcore.so)
endif()

# A migrated submission is src/*.cpp built against VSIPL; USE_GOLD only
# selects the reference file as the source.
if(VSIPL_ROOT)
    target_include_directories(r8bfft PUBLIC ${VSIPL_ROOT}/include)
    target_link_libraries(r8bfft PUBLIC ${VSIPL_ROOT}/lib/libvsip.a m)
endif()

if(BUILD_HIDDEN_TESTS)
    add_executable(hidden_test ${HARNESS_DIR}/hidden_test.cpp)
    target_link_libraries(hidden_test r8bfft m)
endif()

enable_testing()
add_executable(public_test test/public_test.cpp)
target_link_libraries(public_test r8bfft m)
add_test(NAME public_test COMMAND public_test)

if(USE_IPP OR USE_GOLD)
    add_executable(golden_gen ${HARNESS_DIR}/golden_gen.cpp)
    target_link_libraries(golden_gen r8bfft m)
endif()