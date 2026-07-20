# Distributed Key-Value Store

A C++ key-value store project focused on client-server networking, persistence, benchmarking, and distributed systems concepts.

## Current Project Status

The project has completed **Level 4**. The local storage engine, TCP networking, persistent client connections, append-only persistence, startup recovery, single-client benchmarking, multithreaded client handling, and concurrent benchmarking are implemented. The next planned level is **Level 5: log compaction and stronger durability**.

The server now accepts multiple simultaneous client connections. Each accepted connection is assigned to a detached client thread, allowing the main server thread to immediately return to accepting more clients. Each client thread keeps its connection open for multiple commands until the client disconnects or sends `EXIT`.

All client threads share one key-value store and one persistence log. A mutex protects GET, PUT, and DELETE operations so concurrent clients cannot corrupt the shared state or produce persistence-log ordering problems. Concurrent response validation and restart recovery checks confirm that multiclient operations remain consistent.

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
- Python single-client and concurrent benchmarking
- Average, P50, P95, and P99 latency measurements

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

### Single-Client Sequential Benchmark

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

#### Sample Benchmark Results

Measured on localhost using one persistent client connection and 10,000 sequential requests per operation:

| Operation | Total Time | Throughput | Average Latency |
|---|---:|---:|---:|
| PUT | 0.3653 s | 27,378 requests/second | 0.0365 ms |
| GET | 0.1489 s | 67,179 requests/second | 0.0149 ms |
| DELETE | 0.3497 s | 28,600 requests/second | 0.0350 ms |

GET is faster because it only performs an in-memory lookup. PUT and DELETE also append entries to the persistence log.

These results represent a single-client, sequential, persistent-connection benchmark rather than maximum concurrent throughput.

### Concurrent Benchmark

The concurrent benchmark creates one Python thread and one persistent TCP connection per simulated client. A barrier waits for all clients to connect, and an event releases them at approximately the same time. Each client sends one request at a time and waits for its response while the other clients operate concurrently.

Each client uses its own key range so throughput measurements do not depend on clients overwriting the same keys. Every server response is checked for correctness. The benchmark reports aggregate throughput along with average, P50, P95, and P99 request latency.

Run the concurrent benchmark from the project root:

```bash
python3 scripts/concurrent_benchmark.py
```

#### Sample Concurrent Results

Measured on localhost using 10,000 sequential requests per persistent client connection:

| Clients | Operation | Total Requests | Throughput | Average Latency | P95 Latency |
|---:|---|---:|---:|---:|---:|
| 1 | PUT | 10,000 | 24,064 req/s | 0.0409 ms | 0.0640 ms |
| 1 | GET | 10,000 | 51,738 req/s | 0.0186 ms | 0.0255 ms |
| 1 | DELETE | 10,000 | 24,806 req/s | 0.0397 ms | 0.0502 ms |
| 2 | PUT | 20,000 | 41,781 req/s | 0.0472 ms | 0.0660 ms |
| 2 | GET | 20,000 | 85,601 req/s | 0.0227 ms | 0.0323 ms |
| 2 | DELETE | 20,000 | 43,491 req/s | 0.0454 ms | 0.0579 ms |
| 4 | PUT | 40,000 | 44,562 req/s | 0.0888 ms | 0.2258 ms |
| 4 | GET | 40,000 | 67,772 req/s | 0.0581 ms | 0.1065 ms |
| 4 | DELETE | 40,000 | 43,513 req/s | 0.0910 ms | 0.2144 ms |
| 8 | PUT | 80,000 | 43,936 req/s | 0.1799 ms | 0.5787 ms |
| 8 | GET | 80,000 | 38,645 req/s | 0.2055 ms | 0.4011 ms |
| 8 | DELETE | 80,000 | 42,676 req/s | 0.1855 ms | 0.5554 ms |

PUT and DELETE throughput improves as the server moves from one client to two and four clients, then levels off because all shared store and log operations use one mutex. At eight clients, increased lock contention raises latency. This is expected for the first correctness-focused concurrency design.

As a recovery check, four clients concurrently wrote 100 keys each. After the server restarted and replayed the persistence log, concurrent GET requests returned all 400 expected values successfully.

### Persistence-Log Impact

The benchmark results include persistence overhead. Every PUT and DELETE opens and appends to the persistence log before returning a response, while GET performs only an in-memory lookup. This is why write operations are slower than reads.

The log does not currently compact, so overwritten and deleted keys leave obsolete entries behind and the file grows after every write benchmark. The growing log most directly increases disk usage and startup recovery time because the server must replay every historical entry. Depending on the filesystem, storage device, and cache state, a large log can also affect sustained write measurements. Benchmark comparisons should therefore record the log size or begin from a consistent log state.

Level 5 log compaction will rewrite the log to contain only the current key-value state. This should greatly reduce log size and recovery time and make long-running benchmark conditions more consistent. Compaction will not eliminate the normal cost of appending each new PUT or DELETE.

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
│   ├── benchmark.py
│   └── concurrent_benchmark.py
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

### Level 4 — Concurrent Clients (Completed)

- One client-handling thread per connection (implemented)
- Multiple simultaneous persistent clients (implemented)
- Mutex protection for the shared store and persistence log (implemented)
- Per-client socket cleanup (implemented)
- Concurrent response validation and recovery testing (implemented)
- Multi-client throughput and latency benchmarking (implemented)

### Level 5 — Compaction and Durability (Next)

- Log compaction to remove obsolete entries
- Reduced log size and startup recovery time
- Safe temporary-file replacement
- Stronger log-write error handling
- Explicit flush and durability behavior

### Level 6 — Basic Distribution

- Multiple key-value server nodes
- Hash-based key sharding
- Simple replication as a possible extension
