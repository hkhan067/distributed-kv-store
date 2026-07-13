# Distributed Key-Value Store

A C++ key-value store project focused on client-server networking, persistence, benchmarking, and distributed systems concepts.

## Current Features

- PUT, GET, and DELETE operations
- In-memory storage using `std::unordered_map`
- Command parsing
- TCP client-server communication
- Persistent TCP client connections
- Append-only persistence logging
- Recovery from the persistence log on server startup
- Python benchmarking for throughput and average latency

## Supported Commands

```txt
PUT key value
GET key
DELETE key
EXIT
```

Example:

```txt
PUT name Haroon
OK
GET name
VALUE Haroon
DELETE name
OK
GET name
NOT_FOUND
```

## Persistence Log

The server records write operations in an append-only log.

Example log entries:

```txt
PUT name Haroon
DELETE name
```

When the server starts, it replays the persistence log to rebuild the in-memory key-value store. PUT and DELETE operations are written to the log, while GET operations are not logged because they do not modify stored data.

## Benchmarking

The benchmark script uses one persistent TCP client connection and sends requests sequentially. Each request waits for a response before the next request is sent.

This measures single-client, sequential, end-to-end performance over one persistent localhost TCP connection.

Run the server in one terminal:

```bash
cd build
./kv_server
```

Run the benchmark from the project root in another terminal:

```bash
python3 scripts/benchmark.py
```

### Sample Benchmark Results

Measured on localhost using one persistent client connection and 10,000 sequential requests per operation:

| Operation | Total Time | Throughput | Average Latency |
|---|---:|---:|---:|
| PUT | 0.3653 s | 27,378 requests/second | 0.0365 ms |
| GET | 0.1489 s | 67,179 requests/second | 0.0149 ms |
| DELETE | 0.3497 s | 28,600 requests/second | 0.0350 ms |

GET is faster because it only performs an in-memory lookup. PUT and DELETE also append entries to the persistence log.

These results represent a single-client, sequential, persistent-connection benchmark rather than maximum concurrent throughput.

## Project Structure

```txt
distributed-kv-store/
├── CMakeLists.txt
├── README.md
├── data/
│   └── .gitkeep
├── include/
│   ├── CommandParser.h
│   ├── KeyValueStore.h
│   ├── PersistenceLog.h
│   └── Server.h
├── scripts/
│   └── benchmark.py
└── src/
    ├── CommandParser.cpp
    ├── KeyValueStore.cpp
    ├── PersistenceLog.cpp
    ├── Server.cpp
    ├── kv_server.cpp
    └── main.cpp
```

## Build

```bash
mkdir build
cd build
cmake ..
cmake --build .
```

## Run

Run the local command-line version:

```bash
./kv_cli
```

Run the TCP server:

```bash
./kv_server
```

## Development Roadmap

1. Local in-memory key-value store
2. Command parser
3. TCP server
4. Persistent client connections
5. Append-only persistence log
6. Recovery on server startup
7. Benchmarking
8. Multithreaded client handling
9. Log compaction
10. Basic hash-based sharding across multiple nodes