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
- Reproducible final-version distributed benchmark suite
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

`ctest` runs three test suites:

- `level5_tests` checks compaction, recovery equivalence, repeated PUTs, deleted keys, post-compaction writes, empty logs, malformed records, and failure paths that preserve the original log.
- `level6_integration` launches three real server processes on temporary ports with separate temporary logs. It verifies deterministic hashing, physical shard isolation, fragmented and batched TCP commands, PUT/GET/DELETE routing, cluster-wide compaction, unavailable-shard errors, healthy-shard continuity, and recovery after node and full-cluster restarts.
- `distributed_benchmark_smoke` runs every final benchmark category with a tiny workload to catch orchestration, validation, and reporting regressions without treating smoke-run numbers as performance results.

Tests never modify `data/kv.log`.

## Final Distributed Benchmarks

The final benchmark suite measures the completed Level 6 system rather than an earlier project stage. It launches isolated server processes itself, uses temporary logs, validates every response, and removes all generated data when it finishes.

### Reproduce the Results

Build the optimized server and run the self-contained benchmark from the project root:

```bash
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release
python3 scripts/distributed_benchmark.py
```

The script covers concurrent operation scaling, mixed workloads, node-process scaling, shard distribution, log compaction, and recovery. Command-line options can reduce the workload for a faster smoke run:

```bash
python3 scripts/distributed_benchmark.py --help
```

### Methodology

Results were collected on August 9, 2026 using an Apple M5 Pro MacBook Pro with 15 CPU cores and 48 GB of memory, running macOS 26.6 and Python 3.9.6.

- C++ server compiled in Release mode with Apple Clang 21.0.0.
- Primary distributed workloads use three real `kv_server` processes with independent temporary logs; the node-scaling test intentionally varies this from one to three.
- Localhost TCP transport with one persistent connection per worker per node.
- Connection setup, fixture creation, log resets, and cleanup excluded from timed intervals.
- Workers synchronized before timing and every server response checked for correctness.
- Separate key ranges per worker to avoid accidental cross-client overwrites.
- Fresh logs before every timed workload trial so old append history cannot bias later rows; recovery trials intentionally restart the same controlled log.
- Three trials per timed row; each reported metric is the median of those trials.
- PUT and DELETE include the final Level 5 `flush()` and per-request `fsync()` durability behavior.

These are end-to-end, closed-loop measurements: each worker sends one request and waits for its response before sending its next request.

### Three-Node Concurrent Scaling

Each worker performs 500 requests per operation. PUT first creates the dataset, GET reads the same keys, and DELETE removes them.

| Clients | Operation | Requests | Requests/sec | Avg Latency | P50 | P95 | P99 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 2 | PUT | 1,000 | 31,191 | 0.064 ms | 0.059 ms | 0.085 ms | 0.130 ms |
| 2 | GET | 1,000 | 75,144 | 0.026 ms | 0.024 ms | 0.039 ms | 0.055 ms |
| 2 | DELETE | 1,000 | 30,011 | 0.066 ms | 0.062 ms | 0.089 ms | 0.118 ms |
| 4 | PUT | 2,000 | 39,691 | 0.100 ms | 0.092 ms | 0.168 ms | 0.228 ms |
| 4 | GET | 2,000 | 54,979 | 0.072 ms | 0.065 ms | 0.133 ms | 0.177 ms |
| 4 | DELETE | 2,000 | 41,577 | 0.095 ms | 0.088 ms | 0.154 ms | 0.205 ms |
| 8 | PUT | 4,000 | 34,421 | 0.230 ms | 0.217 ms | 0.409 ms | 0.531 ms |
| 8 | GET | 4,000 | 39,070 | 0.202 ms | 0.182 ms | 0.410 ms | 0.554 ms |
| 8 | DELETE | 4,000 | 34,627 | 0.228 ms | 0.215 ms | 0.412 ms | 0.533 ms |
| 16 | PUT | 8,000 | 29,994 | 0.526 ms | 0.481 ms | 1.035 ms | 1.365 ms |
| 16 | GET | 8,000 | 38,541 | 0.408 ms | 0.364 ms | 0.878 ms | 1.165 ms |
| 16 | DELETE | 8,000 | 30,885 | 0.509 ms | 0.462 ms | 1.001 ms | 1.326 ms |

GET peaked at **75,144 requests/second**. Durable PUT and DELETE throughput peaked around **40,000 requests/second** with four clients. At eight and sixteen clients, throughput levels off while tail latency rises, which is consistent with shared-host load generation, storage synchronization, thread scheduling, and per-node mutex contention.

### Mixed Workloads

Eight concurrent clients each execute 1,000 shuffled operations against three nodes. GET and DELETE fixtures are created before timing.

| Workload | Operation Mix | Requests | Requests/sec | Avg Latency | P50 | P95 | P99 |
|---|---|---:|---:|---:|---:|---:|---:|
| Read-heavy | 80% GET / 10% PUT / 10% DELETE | 8,000 | 40,569 | 0.195 ms | 0.180 ms | 0.365 ms | 0.467 ms |
| Balanced | 50% GET / 25% PUT / 25% DELETE | 8,000 | 36,527 | 0.217 ms | 0.198 ms | 0.404 ms | 0.540 ms |

The read-heavy mix is faster because only 20% of its operations require an append, flush, and `fsync()`. The balanced mix performs durable writes for half of its requests.

### Node-Process Scaling

This comparison keeps the workload fixed at eight clients and 8,000 read-heavy operations while changing only the number of active shard processes.

| Nodes | Requests | Requests/sec | Avg Latency | P50 | P95 | P99 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 8,000 | 39,396 | 0.201 ms | 0.186 ms | 0.374 ms | 0.495 ms |
| 2 | 8,000 | 40,428 | 0.196 ms | 0.181 ms | 0.363 ms | 0.482 ms |
| 3 | 8,000 | 39,198 | 0.201 ms | 0.182 ms | 0.385 ms | 0.508 ms |

Throughput remains around 39–40K requests/second while all processes, the Python load generator, and all persistence files share one laptop and storage device. The lack of a material gain is consistent with shared-host limits. Sharding distributes ownership and isolates failures, but running more processes on one host does not create additional physical capacity. A multi-machine deployment is required to measure horizontal hardware scaling.

### FNV-1a Shard Balance

The benchmark routes 30,000 deterministic keys through the production FNV-1a routing function without sending network requests.

| Node | Assigned Keys | Share |
|---:|---:|---:|
| 0 | 9,972 | 33.24% |
| 1 | 10,018 | 33.39% |
| 2 | 10,010 | 33.37% |

The maximum deviation from the ideal 10,000 keys per node is only **0.28%**.

### Compaction and Recovery

To create a controlled persistence history efficiently, the benchmark generates 315,000 records directly in the valid native log format rather than sending 315,000 network writes: 30,000 keys receive ten PUT versions each, then half of the keys are deleted. It verifies live and deleted sample keys before and after compaction.

| Metric | Before Compaction | After Compaction | Improvement |
|---|---:|---:|---:|
| Log records | 315,000 | 15,000 | 95.24% reduction |
| Combined log size | 9.12 MiB | 0.44 MiB | 95.19% reduction |
| Median cluster-ready recovery | 22.7 ms | 6.0 ms | 73.7% faster |

One observed end-to-end COMPACT run across all three localhost nodes took **0.003 seconds**. Recovery is measured from process launch until every node accepts TCP connections, using the median of three restarts before and three restarts after compaction with a 1 ms readiness-polling interval.

### Interpreting the Numbers

- All nodes and benchmark workers run on one machine over loopback, so these are not multi-datacenter or production-network claims.
- The Python load generator, operating-system cache, scheduler, and shared storage device can limit measured throughput.
- Recovery measurements include process startup and use warm localhost filesystem caches.
- Results will vary by CPU, filesystem, storage device, operating system, and background load.
- The system shards data but does not replicate it, so these results do not measure replication or consensus overhead.
- The benchmark favors reproducibility and response validation over generating the largest possible headline number.

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
│   ├── distributed_benchmark.py
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
- Initial Python throughput and latency measurement

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
- Multi-host deployment benchmarking
