cmake_minimum_required(VERSION 3.10)
project(demod_frontend C)
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
    set(DEM_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/gold/demod_frontend_vsipl.c)
else()
    file(GLOB DEM_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/*.c)
endif()

add_library(demfront STATIC ${DEM_SOURCES})
target_include_directories(demfront PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

if(USE_IPP)
    target_include_directories(demfront PUBLIC ${IPP_ROOT}/include)
    target_compile_definitions(demfront PUBLIC HAVE_IPP)
    target_link_libraries(demfront PUBLIC
        ${IPP_ROOT}/lib/shared/libipps.so
        ${IPP_ROOT}/lib/shared/libippcore.so)
endif()

# A migrated submission is src/*.c built against VSIPL; USE_GOLD only selects
# the reference file as the source.
if(VSIPL_ROOT)
    target_include_directories(demfront PUBLIC ${VSIPL_ROOT}/include)
    target_link_libraries(demfront PUBLIC ${VSIPL_ROOT}/lib/libvsip.a m)
endif()

if(BUILD_HIDDEN_TESTS)
    add_executable(hidden_test ${HARNESS_DIR}/hidden_test.c)
    target_link_libraries(hidden_test demfront m)
endif()

enable_testing()
add_executable(public_test test/public_test.c)
target_link_libraries(public_test demfront m)
add_test(NAME public_test COMMAND public_test)

if(USE_IPP OR USE_GOLD)
    add_executable(golden_gen ${HARNESS_DIR}/golden_gen.c)
    target_link_libraries(golden_gen demfront m)
endif()