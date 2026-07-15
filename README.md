# Distributed Key-Value Store

A C++ key-value store project focused on client-server networking, persistence, benchmarking, and distributed systems concepts.

## Current Project Status

The project has completed **Level 3** and is currently at **Level 4**. The local storage engine, TCP networking, persistent client connections, append-only persistence, startup recovery, and single-client benchmarking are implemented.

The server now accepts multiple simultaneous client connections. Each accepted connection is assigned to a detached client thread, allowing the main server thread to immediately return to accepting more clients. Each client thread keeps its connection open for multiple commands until the client disconnects or sends `EXIT`.

All client threads share one key-value store and one persistence log. A mutex protects GET, PUT, and DELETE operations so concurrent clients cannot corrupt the shared state or produce persistence-log ordering problems. Concurrent correctness testing and multi-client benchmarking are the remaining Level 4 tasks.

## Current Features

- PUT, GET, and DELETE operations
- In-memory storage using `std::unordered_map`
- Command parsing
- TCP client-server communication
- Persistent TCP client connections
- Append-only persistence logging
- Recovery from the persistence log on server startup
- Graceful client disconnection with `EXIT`
- Thread-per-client handling for simultaneous connections
- Mutex protection for the shared store and persistence log
- Per-client socket ownership and cleanup
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
EXIT
GOODBYE
```

`EXIT` closes only the current client connection. It does not stop the server.

## Concurrent Client Handling

The main server thread continuously accepts connections. For each accepted connection, it creates a detached worker thread that runs the persistent `handleClient()` loop for that client. This prevents one connected or idle client from blocking the server from accepting other clients.

Each client thread owns its client socket and closes that socket when the client disconnects, sends `EXIT`, or encounters a read failure. The listening thread remains responsible only for accepting new connections.

The in-memory store and persistence log are shared by every client thread. A single `std::mutex` coordinates access to these resources:

- GET holds the mutex while reading from the store.
- PUT holds the mutex while updating the store and appending the matching log entry.
- DELETE holds the mutex while updating the store and appending the matching log entry.
- Socket reads, command parsing, and response sends happen outside the locked section.

The store mutation and its matching persistence-log append use the same lock so their ordering remains consistent during recovery. CMake uses the portable `Threads::Threads` target to provide the platform-specific thread support required by `kv_server`.

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

Concurrent client throughput is not measured yet and will be added as the next part of Level 4. The existing results remain the single-client baseline for comparing future multi-client performance.

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

### Level 1 — Local Key-Value Engine (Completed)

- In-memory storage using `std::unordered_map`
- PUT, GET, and DELETE operations
- Command parser
- Local command-line interface

### Level 2 — TCP Networking (Completed)

- POSIX TCP server
- Client-server request and response handling
- Persistent client connections
- Client-controlled disconnection with `EXIT`

### Level 3 — Persistence and Benchmarking (Completed)

- Append-only persistence log
- PUT and DELETE logging
- Recovery on startup by replaying the log
- Python benchmark using one persistent client connection
- Sequential throughput and average latency measurements

### Level 4 — Concurrent Clients (Current)

- One client-handling thread per connection (implemented)
- Multiple simultaneous persistent clients (implemented)
- Mutex protection for the shared store and persistence log (implemented)
- Per-client socket cleanup (implemented)
- Concurrent correctness tests (next)
- Multi-client benchmarking (next)

### Level 5 — Compaction and Durability

- Log compaction to remove obsolete entries
- Safe temporary-file replacement
- Stronger log-write error handling
- Explicit flush and durability behavior

### Level 6 — Basic Distribution

- Multiple key-value server nodes
- Hash-based key sharding
- Simple replication as a possible extension
