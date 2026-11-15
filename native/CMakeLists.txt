cmake_minimum_required(VERSION 3.21)
project(PyQtDesignerSnap7 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
find_package(Threads REQUIRED)
set(SNAP7_SOURCES
    src/sys/snap_msgsock.cpp src/sys/snap_sysutils.cpp src/sys/snap_tcpsrvr.cpp src/sys/snap_threads.cpp
    src/core/s7_client.cpp src/core/s7_isotcp.cpp src/core/s7_partner.cpp src/core/s7_peer.cpp
    src/core/s7_server.cpp src/core/s7_text.cpp src/core/s7_micro_client.cpp src/lib/snap7_libmain.cpp)
list(TRANSFORM SNAP7_SOURCES PREPEND "${SNAP7_SOURCE_ROOT}/")
add_library(snap7 SHARED ${SNAP7_SOURCES})
target_include_directories(snap7 PRIVATE "${SNAP7_SOURCE_ROOT}/src/sys" "${SNAP7_SOURCE_ROOT}/src/core" "${SNAP7_SOURCE_ROOT}/src/lib")
target_link_libraries(snap7 PRIVATE Threads::Threads)
set_target_properties(snap7 PROPERTIES LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib" INSTALL_NAME_DIR "@rpath" BUILD_WITH_INSTALL_NAME_DIR TRUE)
if(WIN32)
    target_compile_definitions(snap7 PRIVATE _CRT_SECURE_NO_WARNINGS _WINSOCK_DEPRECATED_NO_WARNINGS WIN32_LEAN_AND_MEAN)
    target_link_libraries(snap7 PRIVATE ws2_32 winmm)
elseif(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_link_libraries(snap7 PRIVATE rt)
endif()
