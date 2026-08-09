cmake_minimum_required(VERSION 3.16)

project(distributed_kv_store)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(Threads REQUIRED)
find_package(Python3 3.9 COMPONENTS Interpreter REQUIRED)

include_directories(include)

add_executable(kv_cli
    src/main.cpp
    src/KeyValueStore.cpp
    src/CommandParser.cpp
)

add_executable(kv_server
    src/kv_server.cpp
    src/Server.cpp
    src/KeyValueStore.cpp
    src/CommandParser.cpp
    src/PersistenceLog.cpp
)

target_link_libraries(kv_server PRIVATE Threads::Threads)

enable_testing()

add_executable(level5_tests
    tests/Level5Tests.cpp
    src/KeyValueStore.cpp
    src/CommandParser.cpp
    src/PersistenceLog.cpp
)

add_test(NAME level5_tests COMMAND level5_tests)

add_test(
    NAME level6_integration
    COMMAND
        ${Python3_EXECUTABLE}
        ${CMAKE_SOURCE_DIR}/tests/Level6IntegrationTest.py
        $<TARGET_FILE:kv_server>
)

set_tests_properties(level6_integration PROPERTIES TIMEOUT 30)
