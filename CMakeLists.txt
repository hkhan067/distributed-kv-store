cmake_minimum_required(VERSION 3.16)

project(distributed_kv_store)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

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
)