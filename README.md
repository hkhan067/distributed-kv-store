# Distributed Key-Value Store

A C++ key-value store project focused on client-server networking, persistence, multithreading, and benchmarking.

## Planned Features

- PUT, GET, and DELETE operations
- In-memory hash table storage
- Command parsing
- TCP client-server communication
- Append-only log persistence
- Recovery on server startup
- Multithreaded client handling
- Benchmarking for throughput and latency

## Build

```bash
mkdir build
cd build
cmake ..
cmake --build .
# Distributed Key-Value Store

A C++ key-value store project focused on building a storage system step by step, starting with a local in-memory store and later adding client-server networking, persistence, multithreading, and benchmarking.

## Current Version

Level 1: Local in-memory key-value store.

The current version supports basic command-line operations using an in-memory hash table.

## Supported Commands

```txt
PUT key value
GET key
DELETE key
EXIT
```

Example:

```txt
> PUT name Haroon
OK
> GET name
VALUE Haroon
> DELETE name
OK
> GET name
NOT_FOUND
```

## Planned Features

- PUT, GET, and DELETE operations
- In-memory hash table storage
- Command parsing
- TCP client-server communication
- Append-only log persistence
- Recovery on server startup
- Multithreaded client handling
- Benchmarking for throughput and latency
- Basic hash-based sharding across multiple nodes

## Project Structure

```txt
distributed-kv-store/
├── CMakeLists.txt
├── README.md
├── include/
│   ├── KeyValueStore.h
│   └── CommandParser.h
└── src/
    ├── main.cpp
    ├── KeyValueStore.cpp
    └── CommandParser.cpp
```

## Build

```bash
mkdir build
cd build
cmake ..
cmake --build .
```

## Run

```bash
./kv_store
```

## Development Roadmap

1. Local in-memory key-value store
2. Command parser
3. TCP server
4. C++ TCP client
5. Append-only persistence log
6. Recovery on server startup
7. Multithreaded client handling
8. Benchmarking
9. Basic distributed sharding
10.