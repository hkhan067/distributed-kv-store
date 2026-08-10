# Distributed Key-Value Store

An educational C++17 key-value store with a multithreaded POSIX TCP server, append-only operation logs, per-node log compaction, and deterministic client-side sharding.

## Project Status

Levels 1 through 6 are complete. The project progresses from a local `std::unordered_map` engine to a concurrent TCP server with persistent client connections and finally to a client-sharded, multi-process system. Here, a node means one independently running `kv_server` process; the examples colocate three nodes on one host.

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

Each node owns its own in-memory map, mutex, and log. The servers do not communicate or maintain cluster metadata. The Python client owns key placement, so this is client-side partitioning rather than replication or server-coordinated distribution. Every sharding-aware client must use the same hash function and ordered node list.

## Features

- PUT, GET, DELETE, COMPACT, and EXIT commands over persistent TCP connections
- In-memory storage using `std::unordered_map`
- Newline-delimited framing with fragmented-request buffering and complete-response send loops
- One detached client thread per connection and one mutex per node for shared store/log state
- Append-only PUT/DELETE logs with startup replay and log-before-memory mutation ordering
- Stream flush, close, and POSIX `fsync()` before acknowledging successful writes
- Per-node compaction through a same-directory temporary file and atomic rename
- Configurable server ports and persistence-log paths
- Deterministic 64-bit FNV-1a client-side sharding with lazy persistent connections to contacted nodes
- Per-shard errors without incorrect fallback routing
- Reproducible distributed benchmarks, C++ unit tests, and a real three-node integration test

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

PUT, GET, and DELETE contain a key, so the sharded client sends each command to exactly one node. COMPACT has no key, so the client contacts every configured node sequentially and reports each result independently; this fan-out is not an atomic cluster transaction. EXIT closes the client's open connections but does not stop the servers.

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
5. Sends the normalized command and waits for one newline-terminated response.

Hash collisions are harmless: they only place multiple keys on the same node. If a node is unavailable, the client reports that shard as unavailable and does not silently send the key to a different node. Requests for healthy shards can continue.

The ordered node list is part of the database configuration. Adding or removing nodes changes the modulo result for many keys; reordering the list changes which server address an existing index names. Any of these changes can make stored keys unreachable until data is migrated manually.

## Concurrency and TCP Handling

The main server thread continuously accepts connections. Each accepted socket is passed to a detached client thread, allowing the listener to accept the next client immediately. That thread processes multiple commands until EXIT, disconnect, oversized input, or a socket error closes the connection.

TCP is a byte stream, so one `read()` is not guaranteed to equal one command. Each client thread buffers incomplete input, extracts all complete newline-delimited commands, and preserves the remainder for the next read. A send loop writes the full response. Requests are limited to 8,192 bytes; oversized input receives an error and closes the connection. The Python client reads through the response newline and rejects EOF before a complete response.

Every node has one exclusive `std::mutex`. GET holds it for the lookup; PUT, DELETE, and COMPACT hold it through their store/log critical sections. Parsing and socket I/O stay outside the lock, but protected operations—including concurrent GETs—serialize on that node. Different nodes use different mutexes and operate independently.

## Persistence and Write Ordering

Each node records write operations in its own append-only log:

```txt
PUT name Haroon
DELETE name
```

The node replays the log at startup to rebuild its in-memory state. GET is not logged because it does not modify data. Records missing required tokens are ignored, but the text format has no checksum or length field to identify every torn or corrupted record that still looks syntactically valid.

The server uses log-before-memory ordering for every PUT and for DELETE when the key exists:

```txt
lock shared state
append the record, flush, and close the stream
fsync the log file
change the in-memory store
unlock shared state
return OK
```

If append, flush, close, or `fsync()` reports failure, the server returns `ERROR persistence failure` without changing the current in-memory map. A late failure is still an ambiguous disk outcome: bytes written before the error are not rolled back and could be replayed after restart.

Completing POSIX `fsync()` before `OK` is stronger than buffered logging alone, but it is not an absolute power-loss guarantee. In particular, the implementation does not `fsync()` the parent directory after first creating a log file.

### Log Compaction

An append-only log retains overwritten values and deletion history. COMPACT reduces that history to the current live state:

1. Hold `dataMutex` and copy the current key-value map.
2. Write one PUT record per live key to `<log-path>.tmp`.
3. Flush, close, and `fsync()` the temporary file.
4. Rename the same-directory temporary file over the original log, atomically changing the active path for running processes.
5. `fsync()` the resulting log before returning OK.

The original log is never truncated first. Failures before a successful rename leave the original path untouched. After rename, however, a final sync failure returns an error even though replacement has already occurred. The parent directory is not `fsync()`ed after rename, so the project does not claim that the replacement is fully crash- or power-loss-durable. Holding the mutex through the entire operation prevents a concurrent acknowledged write from being omitted by the snapshot.

## Testing

`ctest` runs three test suites:

- `level5_tests` checks compaction, recovery equivalence, repeated PUTs, deleted keys, post-compaction writes, empty logs, records missing required fields, and pre-replacement failures that preserve the original log.
- `level6_integration` launches three server processes on temporary ports with separate temporary logs. It verifies deterministic hashing, per-process shard placement, fragmented and batched TCP commands, request routing, client fan-out compaction, unavailable-shard errors, healthy-shard continuity, and recovery after node and full-cluster restarts.
- `distributed_benchmark_smoke` runs every report category with reduced network and persistence workloads to catch orchestration, validation, and reporting regressions; its output is not treated as a performance result.

Tests never modify `data/kv.log`.

## Final Distributed Benchmarks

The final benchmark suite measures the completed Level 6 system rather than an earlier project stage. It launches isolated server processes itself, uses temporary logs, validates every response, and removes all generated data when it finishes.

### Reproduce the Results

Build the optimized server and run the self-contained benchmark from the project root:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
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
- For request workloads, connection setup, fixture creation, log resets, and cleanup are excluded from timing; recovery timing intentionally includes process launch and readiness connections.
- Workers synchronized before timing and every server response checked for correctness.
- Separate key ranges per worker to avoid accidental cross-client overwrites.
- Each request-workload trial starts with fresh logs; PUT, GET, and DELETE within a scaling trial intentionally share one dataset and log history.
- Throughput, latency, and recovery values use three-trial medians. The reported COMPACT duration is one observation.
- PUT and DELETE include stream flush, close, and per-request file `fsync()`.

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

GET peaked at **75,144 requests/second**. PUT and DELETE, including per-request file `fsync()`, peaked around **40,000 requests/second** with four clients. Throughput then plateaued while tail latency rose; the benchmark did not profile a single cause.

### Mixed Workloads

Eight concurrent clients each execute 1,000 shuffled operations against three nodes. Fixtures are created before timing; GETs cycle through a hot set of up to 100 keys per worker, while DELETE keys are used once. The node-process comparison below uses the same read-heavy generator.

| Workload | Operation Mix | Requests | Requests/sec | Avg Latency | P50 | P95 | P99 |
|---|---|---:|---:|---:|---:|---:|---:|
| Read-heavy | 80% GET / 10% PUT / 10% DELETE | 8,000 | 40,569 | 0.195 ms | 0.180 ms | 0.365 ms | 0.467 ms |
| Balanced | 50% GET / 25% PUT / 25% DELETE | 8,000 | 36,527 | 0.217 ms | 0.198 ms | 0.404 ms | 0.540 ms |

The read-heavy result is consistent with only 20% of its operations requiring append, flush, close, and `fsync()`, compared with 50% for the balanced mix.

### Node-Process Scaling

This comparison keeps the workload fixed at eight clients and 8,000 read-heavy operations while changing only the number of active shard processes.

| Nodes | Requests | Requests/sec | Avg Latency | P50 | P95 | P99 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 8,000 | 39,396 | 0.201 ms | 0.186 ms | 0.374 ms | 0.495 ms |
| 2 | 8,000 | 40,428 | 0.196 ms | 0.181 ms | 0.363 ms | 0.482 ms |
| 3 | 8,000 | 39,198 | 0.201 ms | 0.182 ms | 0.385 ms | 0.508 ms |

Throughput remains around 39–40K requests/second while every process, log, and benchmark worker shares one laptop. This same-host comparison shows no material capacity gain and is not evidence of multi-machine horizontal scaling.

### FNV-1a Shard Balance

The benchmark routes 30,000 deterministic keys through the production FNV-1a routing function without sending network requests.

| Node | Assigned Keys | Share |
|---:|---:|---:|
| 0 | 9,972 | 33.24% |
| 1 | 10,018 | 33.39% |
| 2 | 10,010 | 33.37% |

The maximum deviation from the ideal 10,000 keys per node is only **0.28%**.

### Compaction and Recovery

To create a controlled persistence history efficiently, the benchmark generates 315,000 records directly in the server's plain-text log format rather than sending 315,000 network writes: 30,000 keys receive ten PUT versions each, then half of the keys are deleted. It verifies live and deleted sample keys before and after compaction.

| Metric | Before Compaction | After Compaction | Observed Change |
|---|---:|---:|---:|
| Log records | 315,000 | 15,000 | 95.24% reduction |
| Combined log size | 9.12 MiB | 0.44 MiB | 95.19% reduction |
| Median cluster-ready recovery | 22.7 ms | 6.0 ms | 73.7% lower |

One observed sequential COMPACT fan-out from the client across all three localhost nodes took **0.003 seconds**. Recovery is measured from process launch until every node accepts TCP connections, using the median of three restarts before and three restarts after compaction with a 1 ms readiness-polling interval.

### Interpreting the Numbers

- All nodes and benchmark workers run on one machine over loopback, so these are not multi-host or production-network claims.
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
    ├── DistributedIntegrationTest.py
    └── PersistenceCompactionTests.cpp
```

## Design Boundaries

This project demonstrates core systems concepts without pretending to be a production database:

- Sharding uses hash modulo node count, not consistent hashing; membership and node order are configured manually in every client.
- There is no service discovery, server-side shard map, or automatic data migration when membership changes.
- Each key is assigned to one server node; there is no replication or automatic failover.
- A failed shard process makes its keys unavailable without rerouting them, while healthy shard processes remain usable.
- There are no cross-node transactions or coordinated cluster operations. COMPACT is best-effort per node and can partially succeed.
- Each server creates one detached thread per client rather than using a bounded thread pool.
- COMPACT holds that node's exclusive mutex and blocks its data operations until replacement finishes.
- Log records have no checksum or length framing, and a missing or unreadable log is treated as empty during startup.
- Keys and values cannot contain whitespace or newlines; there is no authentication, TLS, versioning, or consensus protocol.

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
- Concurrent persistent-client validation

### Level 5 — Compaction and Durability (Completed)

- Temporary-file compaction with atomic rename
- Log-before-memory mutation ordering with flush/`fsync()` error handling
- Compaction, recovery, malformed-record, and pre-replacement failure tests

### Level 6 — Basic Distribution (Completed)

- Configurable independent server nodes and log paths
- Deterministic FNV-1a client-side sharding
- Persistent per-node connections
- Client fan-out for independent per-node COMPACT operations
- Unavailable-shard isolation without incorrect fallback routing
- Three-node routing, failure, and recovery integration testing

### Possible Next Steps

- Replication and automatic failover
- Consistent hashing and data rebalancing
- Bounded thread pool and reader-writer locking
- Batched or configurable durability modes
- Checksummed or length-prefixed log records
- Multi-host deployment benchmarking
