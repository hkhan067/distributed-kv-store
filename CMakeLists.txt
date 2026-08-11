cmake_minimum_required(VERSION 3.16)

project(distributed_kv_store)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(Threads REQUIRED)
find_package(Python3 3.9 COMPONENTS Interpreter REQUIRED)

include_directories(include)

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
    tests/PersistenceCompactionTests.cpp
    src/KeyValueStore.cpp
    src/CommandParser.cpp
    src/PersistenceLog.cpp
)

add_test(NAME level5_tests COMMAND level5_tests)

add_test(
    NAME level6_integration
    COMMAND
        ${Python3_EXECUTABLE}
        ${CMAKE_SOURCE_DIR}/tests/DistributedIntegrationTest.py
        $<TARGET_FILE:kv_server>
)

set_tests_properties(level6_integration PROPERTIES TIMEOUT 30)

add_test(
    NAME distributed_benchmark_smoke
    COMMAND
        ${Python3_EXECUTABLE}
        ${CMAKE_SOURCE_DIR}/scripts/distributed_benchmark.py
        --server $<TARGET_FILE:kv_server>
        --trials 1
        --requests-per-client 5
        --mixed-requests-per-client 100
        --history-keys 20
        --history-versions 2
)

set_tests_properties(distributed_benchmark_smoke PROPERTIES TIMEOUT 30)
