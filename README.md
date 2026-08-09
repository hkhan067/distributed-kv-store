# Distributed Key-Value Store

An educational distributed key-value store built in C++17 with POSIX TCP sockets, multithreaded client handling, durable append-only logs, safe log compaction, and deterministic client-side sharding across multiple server nodes.

## Project Status

Levels 1 through 6 are complete. The project progressed from a local `std::unordered_map` storage engine to a concurrent, persistent TCP server and then to a client-sharded multi-node system.

The distributed layer is intentionally small and explainable: each node runs the same C++ server with its own port, in-memory store, mutex, and persistence log. A Python client hashes each key and routes it to one node. Replication, automatic failover, consensus, and automatic rebalancing are future extensions and are not claimed as current features.

## Architecture

```txt
                         Python ShardedClient
                    FNV-1a(key) % number_of_nodes
                                  |
              +-------------------+-------------------+
              |                   |                   |
              v                   v                   v
       Node 0 :8080         Node 1 :8081         Node 2 :8082
       unordered_map        unordered_map        unordered_map
       dataMutex            dataMutex            dataMutex
       node0.log            node1.log            node2.log
```

The servers do not communicate with one another. This is client-side sharding: every client must use the same deterministic hash function and the same ordered node list so a key always reaches the same node.

## Features

- PUT, GET, DELETE, COMPACT, and EXIT commands
- In-memory storage using `std::unordered_map`
- POSIX TCP server with persistent connections
- Newline-delimited request and response framing
- Correct handling of fragmented or batched TCP commands
- One detached client-handling thread per connection
- Mutex protection for each node's shared store and persistence log
- Append-only PUT and DELETE persistence records
- Startup recovery by replaying each node's log
- Write-ahead in-memory updates with persistence error reporting
- `flush()` and POSIX `fsync()` before acknowledging writes
- Safe log compaction through a temporary file and atomic rename
- Configurable server port and persistence-log path
- Deterministic 64-bit FNV-1a client-side key sharding
- Lazy persistent connection reuse for each contacted node
- Per-shard error reporting without rerouting data incorrectly
- Single-client and concurrent Python benchmarks
- C++ unit tests and a real three-node Python integration test

## Quick Start

### Build

Requirements are CMake 3.16 or newer, a C++17 compiler, POSIX sockets, and Python 3.9 or newer.

```bash
cmake -S . -B build
cmake --build build
```

### Run All Tests

```bash
ctest --test-dir build --output-on-failure
```

### Run One Server Node

The no-argument form preserves the original single-node setup:

```bash
cd build
./kv_server
```

It listens on port `8080` and uses `../data/kv.log` relative to the build directory.

A custom node uses:

```bash
./kv_server <port> <log-path>
```

### Run a Three-Node Cluster

Start one process in each terminal from the build directory:

```bash
./kv_server 8080 ../data/node0.log
```

```bash
./kv_server 8081 ../data/node1.log
```

```bash
./kv_server 8082 ../data/node2.log
```

Each node must have a unique log path. Sharing a persistence log between active server processes is not supported.

From the project root, start the sharded client:

```bash
python3 scripts/sharded_client.py
```

The default ordered node list is `127.0.0.1:8080`, `127.0.0.1:8081`, and `127.0.0.1:8082`. Custom nodes can be supplied in order:

```bash
python3 scripts/sharded_client.py \
    127.0.0.1:9000 \
    127.0.0.1:9001 \
    127.0.0.1:9002
```

The client prints the selected node with every response, making key placement visible.

## Commands

```txt
PUT key value
GET key
DELETE key
COMPACT
EXIT
```

Example sharded session:

```txt
sharded> PUT name Haroon
Node 2 (127.0.0.1:8082): OK
sharded> GET name
Node 2 (127.0.0.1:8082): VALUE Haroon
sharded> COMPACT
Node 0 (127.0.0.1:8080): OK
Node 1 (127.0.0.1:8081): OK
Node 2 (127.0.0.1:8082): OK
sharded> EXIT
Node 0 (127.0.0.1:8080): GOODBYE
Node 1 (127.0.0.1:8081): GOODBYE
Node 2 (127.0.0.1:8082): GOODBYE
GOODBYE
```

PUT, GET, and DELETE contain a key, so the sharded client sends each command to exactly one node. COMPACT has no key, so the client broadcasts it to every node. EXIT closes the client's open connections; it does not stop the server processes.

Keys and values are currently whitespace-delimited single tokens.

## How Sharding Works

The client calculates:

```txt
node_index = FNV1a64(UTF8(key)) % number_of_nodes
```

FNV-1a is implemented directly in Python so the result is deterministic across client restarts. Python's built-in `hash()` is intentionally not used because its result is randomized between processes.

For every key command, the client:

1. Reads the key from the command.
2. Calculates the key's node index.
3. Opens that node's TCP connection if it has not been used yet.
4. Reuses the persistent connection for later requests to that node.
5. Sends the unchanged command and waits for one newline-terminated response.

Hash collisions are harmless: they only place multiple keys on the same node. If a node is unavailable, the client reports that shard as unavailable and does not silently send the key to a different node. Requests for healthy shards can continue.

The ordered node list is part of the database configuration. Adding, removing, or reordering nodes changes the modulo result for many keys. This first design does not automatically move existing data.

## Concurrency and TCP Handling

The main server thread continuously accepts connections. Each accepted socket is passed to a detached client thread, allowing the listening thread to immediately accept the next client. The client thread keeps its connection open and processes multiple commands until the client disconnects or sends EXIT.

TCP is a byte stream, so one `read()` is not guaranteed to equal one command. Each client thread keeps a pending string, extracts complete newline-delimited commands, and preserves any incomplete command for the next read. A send loop similarly continues until the full response has been written.

Every node has one `std::mutex` protecting its own store and log:

- GET locks while reading from the store.
- PUT locks while durably appending its record and then updating memory.
- DELETE locks while checking the key, durably appending its record, and then updating memory.
- COMPACT locks while snapshotting the store and safely replacing the log.
- Socket I/O and command parsing remain outside the data lock.

The simple thread-per-client and single-mutex design prioritizes correctness and readability. Different nodes operate independently, while commands on one node serialize briefly around its shared state.

## Persistence and Durability

Each node records write operations in its own append-only log:

```txt
PUT name Haroon
DELETE name
```

The node replays that log at startup to rebuild its in-memory state. GET is not logged because it does not modify data. Incomplete PUT or DELETE records are ignored during recovery.

PUT and DELETE follow write-ahead order:

```txt
lock shared state
append and flush the log record
fsync the log file
change the in-memory store
unlock shared state
return OK
```

If persistence fails, the server returns `ERROR persistence failure` without changing memory. Per-write `fsync()` provides stronger durability than stream buffering alone, but it also makes writes slower.

### Log Compaction

An append-only log retains overwritten values and deletion history. COMPACT reduces that history to the current live state:

1. Hold `dataMutex` and copy the current key-value map.
2. Write one PUT record per live key to `<log-path>.tmp`.
3. Flush, close, and `fsync()` the temporary file.
4. Atomically rename the temporary file over the original log.
5. `fsync()` the resulting log before returning OK.

The original log is never truncated first. If temporary-file creation or writing fails, the old log remains available for recovery. Holding the mutex through replacement pauses that node's data operations briefly, but prevents an acknowledged concurrent write from being replaced by an older snapshot.

## Testing

`ctest` runs two test suites:

- `level5_tests` checks compaction, recovery equivalence, repeated PUTs, deleted keys, post-compaction writes, empty logs, malformed records, and failure paths that preserve the original log.
- `level6_integration` launches three real server processes on temporary ports with separate temporary logs. It verifies deterministic hashing, physical shard isolation, fragmented and batched TCP commands, PUT/GET/DELETE routing, cluster-wide compaction, unavailable-shard errors, healthy-shard continuity, and recovery after node and full-cluster restarts.

Tests never modify `data/kv.log`.

## Benchmarking

### Single-Client Sequential Benchmark

With one server running on localhost port 8080:

```bash
python3 scripts/benchmark.py
```

The script uses one persistent connection and waits for each response before sending the next request.

#### Historical Level 4 Results

These localhost results used 10,000 sequential requests per operation and were recorded before Level 5 added per-write `fsync()`. They are retained as a Level 4 baseline, not presented as current write performance.

| Operation | Total Time | Throughput | Average Latency |
|---|---:|---:|---:|
| PUT | 0.3653 s | 27,378 requests/second | 0.0365 ms |
| GET | 0.1489 s | 67,179 requests/second | 0.0149 ms |
| DELETE | 0.3497 s | 28,600 requests/second | 0.0350 ms |

### Concurrent Benchmark

```bash
python3 scripts/concurrent_benchmark.py
```

The concurrent benchmark creates one Python thread and one persistent connection per simulated client. Clients use separate key ranges, synchronize their start, validate every response, and report aggregate throughput plus average, P50, P95, and P99 latency.

#### Historical Level 4 Concurrent Results

The persistence log was cleared before this suite, and each persistent client sent 10,000 sequential requests per operation. These measurements also predate Level 5 per-write `fsync()`.

| Clients | Operation | Total Requests | Total Time | Throughput | Average Latency | P50 Latency | P95 Latency | P99 Latency |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | PUT | 10,000 | 0.4227 s | 23,658.03 req/s | 0.0416 ms | 0.0391 ms | 0.0626 ms | 0.0965 ms |
| 1 | GET | 10,000 | 0.1974 s | 50,659.21 req/s | 0.0190 ms | 0.0187 ms | 0.0247 ms | 0.0301 ms |
| 1 | DELETE | 10,000 | 0.4011 s | 24,928.54 req/s | 0.0395 ms | 0.0391 ms | 0.0476 ms | 0.0557 ms |
| 2 | PUT | 20,000 | 0.4706 s | 42,498.05 req/s | 0.0464 ms | 0.0442 ms | 0.0595 ms | 0.0890 ms |
| 2 | GET | 20,000 | 0.2214 s | 90,336.24 req/s | 0.0215 ms | 0.0205 ms | 0.0289 ms | 0.0388 ms |
| 2 | DELETE | 20,000 | 0.4703 s | 42,530.57 req/s | 0.0464 ms | 0.0434 ms | 0.0655 ms | 0.1092 ms |
| 4 | PUT | 40,000 | 0.9290 s | 43,057.56 req/s | 0.0914 ms | 0.0563 ms | 0.2295 ms | 0.3641 ms |
| 4 | GET | 40,000 | 0.6052 s | 66,097.77 req/s | 0.0595 ms | 0.0533 ms | 0.1122 ms | 0.1580 ms |
| 4 | DELETE | 40,000 | 1.0401 s | 38,456.22 req/s | 0.1028 ms | 0.0884 ms | 0.2424 ms | 0.3519 ms |
| 8 | PUT | 80,000 | 1.8297 s | 43,724.03 req/s | 0.1814 ms | 0.0508 ms | 0.5738 ms | 0.9568 ms |
| 8 | GET | 80,000 | 2.0779 s | 38,500.91 req/s | 0.2063 ms | 0.1887 ms | 0.4020 ms | 0.5336 ms |
| 8 | DELETE | 80,000 | 1.8163 s | 44,044.44 req/s | 0.1800 ms | 0.1745 ms | 0.4535 ms | 0.7401 ms |

PUT and DELETE scaled from one to multiple clients before leveling off around the single-node mutex and persistence path. Higher client counts increased contention and tail latency. A separate recovery check successfully restored 400 keys written by four concurrent clients.

### Persistence-Log Impact

PUT and DELETE include persistence overhead, while GET performs only an in-memory lookup. Between compactions, obsolete entries grow the log, increasing disk usage and the amount of work required during startup replay. Benchmark comparisons should therefore begin from a consistent log state or record log size.

Compaction reduces log size and recovery work but does not remove the normal append and `fsync()` cost of new writes. Current Level 5 durability behavior should be re-benchmarked before comparing new PUT or DELETE results with the historical Level 4 numbers above.

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
│   ├── concurrent_benchmark.py
│   └── sharded_client.py
├── src/
│   ├── CommandParser.cpp
│   ├── KeyValueStore.cpp
│   ├── PersistenceLog.cpp
│   ├── Server.cpp
│   ├── kv_server.cpp
│   └── main.cpp
└── tests/
    ├── Level5Tests.cpp
    └── Level6IntegrationTest.py
```

## Design Boundaries

This project demonstrates core systems concepts without pretending to be a production database:

- Sharding uses hash modulo node count, not consistent hashing.
- Changing the node count or order requires manual data migration.
- Data has one copy; there is no replication or automatic failover.
- A failed node makes its assigned shard unavailable instead of rerouting keys incorrectly.
- Each server creates one detached thread per client rather than using a bounded thread pool.
- COMPACT blocks data operations on that node until replacement finishes.
- Keys and values cannot currently contain whitespace or newlines.
- There is no authentication, TLS, checksumming, versioning, or distributed consensus.

These are deliberate boundaries that keep the implementation understandable and define clear future work.

## Development Roadmap

### Level 1 — Local Key-Value Engine (Completed)

- `std::unordered_map` storage
- PUT, GET, and DELETE
- Command parser and local CLI

### Level 2 — TCP Networking (Completed)

- POSIX TCP server
- Request-response protocol
- Persistent connections and EXIT

### Level 3 — Persistence and Benchmarking (Completed)

- Append-only log and startup recovery
- Sequential Python benchmark
- Throughput and latency measurement

### Level 4 — Concurrent Clients (Completed)

- Thread-per-client handling
- Multiple simultaneous persistent clients
- Mutex-protected shared state and log
- Concurrent benchmark and recovery validation

### Level 5 — Compaction and Durability (Completed)

- Safe log compaction and atomic replacement
- Write-ahead memory updates
- Explicit flush, `fsync()`, and error propagation
- Compaction, recovery, malformed-record, and failure-path tests

### Level 6 — Basic Distribution (Completed)

- Configurable independent server nodes and log paths
- Deterministic FNV-1a client-side sharding
- Persistent per-node connections
- Cluster-wide COMPACT handling
- Unavailable-shard isolation without incorrect fallback routing
- Three-node distribution, failure, and recovery integration testing

### Possible Next Steps

- Replication and automatic failover
- Consistent hashing and data rebalancing
- Bounded thread pool and reader-writer locking
- Batched or configurable durability modes
- Checksummed or length-prefixed log records
- Metrics and a multi-node benchmark
