cmake_minimum_required(VERSION 3.20)
project(letsinfer_watchdog VERSION 0.11.0 LANGUAGES C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

option(WATCHDOG_BUILD_TESTS "Build unit tests" ON)

add_library(watchdog_core STATIC
    src/controllers.c
    src/crc32.c
    src/gateway.c
    src/metadata.c
    src/record.c
    src/ring.c
    src/rollup.c
    src/protobuf.c
    src/safety.c
)
target_include_directories(watchdog_core PUBLIC include)
target_compile_definitions(watchdog_core PRIVATE _FILE_OFFSET_BITS=64)
target_compile_options(watchdog_core PRIVATE -Wall -Wextra -Wpedantic -Werror)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_compile_definitions(watchdog_core PRIVATE _GNU_SOURCE)
endif()
if(CMAKE_DL_LIBS)
    target_link_libraries(watchdog_core PUBLIC ${CMAKE_DL_LIBS})
endif()

if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    find_package(OpenSSL 3.0 REQUIRED)
    add_executable(letsinfer_watchdog
        src/main_linux.c
        src/nvml_linux.c
        src/sampler_linux.c
        src/safety_linux.c
        src/server_linux.c
    )
    target_include_directories(letsinfer_watchdog PRIVATE include)
    target_compile_definitions(letsinfer_watchdog PRIVATE _GNU_SOURCE _FILE_OFFSET_BITS=64)
    target_compile_options(letsinfer_watchdog PRIVATE -Wall -Wextra -Wpedantic -Werror)
    target_link_libraries(letsinfer_watchdog PRIVATE watchdog_core OpenSSL::SSL OpenSSL::Crypto dl)
    set_target_properties(letsinfer_watchdog PROPERTIES OUTPUT_NAME letsinfer-watchdog)
    install(TARGETS letsinfer_watchdog RUNTIME DESTINATION bin)
endif()

if(WATCHDOG_BUILD_TESTS)
    enable_testing()
    add_executable(watchdog_tests
        tests/test_controllers.c
        tests/test_gateway.c
        tests/test_main.c
        tests/test_metadata.c
        tests/test_record.c
        tests/test_ring.c
        tests/test_rollup.c
        tests/test_protobuf.c
        tests/test_safety.c
    )
    target_include_directories(watchdog_tests PRIVATE include tests)
    target_compile_options(watchdog_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
    if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
        target_sources(watchdog_tests PRIVATE src/safety_linux.c)
        target_compile_definitions(watchdog_tests PRIVATE _GNU_SOURCE)
    endif()
    target_link_libraries(watchdog_tests PRIVATE watchdog_core)
    add_test(NAME watchdog_tests COMMAND watchdog_tests)
endif()
