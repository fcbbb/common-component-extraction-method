cmake_minimum_required(VERSION 3.16)
project(h1_power_spectrum C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

option(USE_IPP  "Build the IPP source implementation" OFF)
option(USE_GOLD "Build the reference VSIPL implementation" OFF)

set(IPP_ROOT   "" CACHE PATH "Intel IPP prefix")
set(VSIPL_ROOT "" CACHE PATH "VSIPL prefix")

if(USE_GOLD)
  set(CORE_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/gold/spectrum_vsipl.c)
else()
  file(GLOB CORE_SOURCES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/src/*.c)
endif()

add_library(power_spectrum STATIC ${CORE_SOURCES})
target_include_directories(power_spectrum PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include)

if(USE_IPP)
  target_include_directories(power_spectrum PUBLIC ${IPP_ROOT}/include)
  target_link_libraries(power_spectrum PUBLIC
    ${IPP_ROOT}/lib/shared/libipps.so
    ${IPP_ROOT}/lib/shared/libippcore.so)
endif()

if(USE_GOLD OR VSIPL_ROOT)
  if(NOT VSIPL_ROOT)
    message(FATAL_ERROR "VSIPL_ROOT is required for the VSIPL build")
  endif()
  target_include_directories(power_spectrum PUBLIC ${VSIPL_ROOT}/include)
  target_link_libraries(power_spectrum PUBLIC ${VSIPL_ROOT}/lib/libvsip.a m)
endif()

enable_testing()
add_executable(public_test test/public_test.c)
target_link_libraries(public_test power_spectrum m)
add_test(NAME public_test COMMAND public_test)