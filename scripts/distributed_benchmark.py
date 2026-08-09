import argparse
import os
import platform
import random
import socket
import statistics
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sharded_client import ShardedClient, shard_index


Node = tuple[str, int]
Request = tuple[str, str]

DEFAULT_CLIENT_COUNTS = [2, 4, 8, 16]
DEFAULT_REQUESTS_PER_CLIENT = 500
DEFAULT_MIXED_REQUESTS_PER_CLIENT = 1000
DEFAULT_TRIALS = 3
DEFAULT_HISTORY_KEYS = 30000
DEFAULT_HISTORY_VERSIONS = 10
SHARD_BALANCE_KEYS = 30000


@dataclass
class Metrics:
    total_requests: int
    total_time_seconds: float
    throughput: float
    average_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float


@dataclass
class MixedWorkload:
    name: str
    get_percent: int
    put_percent: int
    delete_percent: int


@dataclass
class CompactionMetrics:
    records_before: int
    records_after: int
    bytes_before: int
    bytes_after: int
    compaction_time_seconds: float
    recovery_before_ms: float
    recovery_after_ms: float


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def percentile(values: list[float], percentage: float) -> float:
    sorted_values = sorted(values)
    index = int((len(sorted_values) - 1) * percentage)
    return sorted_values[index]


def median_metrics(samples: list[Metrics]) -> Metrics:
    expect(bool(samples), "Cannot calculate a median without samples.")

    return Metrics(
        total_requests=samples[0].total_requests,
        total_time_seconds=statistics.median(
            sample.total_time_seconds for sample in samples
        ),
        throughput=statistics.median(sample.throughput for sample in samples),
        average_latency_ms=statistics.median(
            sample.average_latency_ms for sample in samples
        ),
        p50_latency_ms=statistics.median(
            sample.p50_latency_ms for sample in samples
        ),
        p95_latency_ms=statistics.median(
            sample.p95_latency_ms for sample in samples
        ),
        p99_latency_ms=statistics.median(
            sample.p99_latency_ms for sample in samples
        ),
    )


def find_free_ports(count: int) -> list[int]:
    ports: list[int] = []

    while len(ports) < count:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        if port not in ports:
            ports.append(port)

    return ports


def wait_for_node(node: Node, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 10

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Server at {node[0]}:{node[1]} exited before listening."
            )

        try:
            with socket.create_connection(node, timeout=0.1):
                return
        except OSError:
            time.sleep(0.001)

    raise RuntimeError(f"Timed out waiting for server at {node[0]}:{node[1]}.")


class BenchmarkCluster:
    def __init__(self, server_binary: Path, directory: Path) -> None:
        ports = find_free_ports(3)

        self.server_binary = server_binary
        self.nodes: list[Node] = [
            ("127.0.0.1", port)
            for port in ports
        ]
        self.log_paths = [
            directory / f"node{index}.log"
            for index in range(3)
        ]
        self.processes: list[Optional[subprocess.Popen[bytes]]] = [None, None, None]

    def start(self, node_count: int = 3) -> float:
        expect(1 <= node_count <= 3, "Node count must be from one to three.")
        expect(
            all(process is None for process in self.processes),
            "Cluster is already running.",
        )

        start_time = time.perf_counter()

        for index in range(node_count):
            process = subprocess.Popen(
                [
                    str(self.server_binary),
                    str(self.nodes[index][1]),
                    str(self.log_paths[index]),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
            self.processes[index] = process

        for index in range(node_count):
            process = self.processes[index]
            expect(process is not None, "Server process was not created.")
            wait_for_node(self.nodes[index], process)

        return time.perf_counter() - start_time

    def stop(self) -> None:
        for index, process in enumerate(self.processes):
            if process is None:
                continue

            if process.poll() is None:
                process.terminate()

                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)

            self.processes[index] = None

    def clear_logs(self) -> None:
        for log_path in self.log_paths:
            log_path.unlink(missing_ok=True)
            Path(str(log_path) + ".tmp").unlink(missing_ok=True)

    def reset(self, node_count: int = 3) -> None:
        self.stop()
        self.clear_logs()
        self.start(node_count)


def run_worker(
    client_id: int,
    nodes: list[Node],
    requests: list[Request],
    setup_requests: list[Request],
    ready_barrier: threading.Barrier,
    start_event: threading.Event,
    results: list[Optional[list[float]]],
    finish_times: list[Optional[float]],
    errors: list[Optional[Exception]],
) -> None:
    client: Optional[ShardedClient] = None

    try:
        client = ShardedClient(nodes)

        for node_index in range(len(nodes)):
            response = client.request_node(
                node_index,
                "GET __benchmark_connection_warmup__",
            )
            expect(response == "NOT_FOUND", "Connection warmup returned bad data.")

        for command, expected_response in setup_requests:
            _, response = client.request(command)
            expect(
                response == expected_response,
                f"Setup command failed: {command} returned {response}",
            )

        ready_barrier.wait()
        start_event.wait()

        latencies_ms: list[float] = []

        for command, expected_response in requests:
            request_start = time.perf_counter()
            _, response = client.request(command)
            request_end = time.perf_counter()

            expect(
                response == expected_response,
                f"{command} returned {response}; expected {expected_response}",
            )

            latencies_ms.append((request_end - request_start) * 1000)

        results[client_id] = latencies_ms
        finish_times[client_id] = time.perf_counter()
    except Exception as error:
        errors[client_id] = error
        ready_barrier.abort()
    finally:
        if client is not None:
            client.close()


def run_workload(
    nodes: list[Node],
    requests_by_client: list[list[Request]],
    setup_by_client: Optional[list[list[Request]]] = None,
) -> Metrics:
    client_count = len(requests_by_client)
    expect(client_count > 1, "Final benchmarks require multiple clients.")

    if setup_by_client is None:
        setup_by_client = [[] for _ in range(client_count)]

    ready_barrier = threading.Barrier(client_count + 1)
    start_event = threading.Event()
    results: list[Optional[list[float]]] = [None] * client_count
    finish_times: list[Optional[float]] = [None] * client_count
    errors: list[Optional[Exception]] = [None] * client_count
    threads: list[threading.Thread] = []

    for client_id in range(client_count):
        client_thread = threading.Thread(
            target=run_worker,
            args=(
                client_id,
                nodes,
                requests_by_client[client_id],
                setup_by_client[client_id],
                ready_barrier,
                start_event,
                results,
                finish_times,
                errors,
            ),
        )
        client_thread.start()
        threads.append(client_thread)

    try:
        ready_barrier.wait()
    except threading.BrokenBarrierError as error:
        start_event.set()

        for client_thread in threads:
            client_thread.join()

        failed_error = next((item for item in errors if item is not None), error)
        raise RuntimeError(f"Benchmark setup failed: {failed_error}") from failed_error

    start_time = time.perf_counter()
    start_event.set()

    for client_thread in threads:
        client_thread.join()

    failed_error = next((item for item in errors if item is not None), None)

    if failed_error is not None:
        raise RuntimeError(f"Benchmark worker failed: {failed_error}") from failed_error

    expect(
        all(finish_time is not None for finish_time in finish_times),
        "A benchmark worker returned no finish time.",
    )
    total_time = max(
        finish_time
        for finish_time in finish_times
        if finish_time is not None
    ) - start_time

    all_latencies_ms: list[float] = []

    for client_latencies in results:
        expect(client_latencies is not None, "A benchmark worker returned no results.")
        all_latencies_ms.extend(client_latencies)

    total_requests = len(all_latencies_ms)

    return Metrics(
        total_requests=total_requests,
        total_time_seconds=total_time,
        throughput=total_requests / total_time,
        average_latency_ms=sum(all_latencies_ms) / total_requests,
        p50_latency_ms=percentile(all_latencies_ms, 0.50),
        p95_latency_ms=percentile(all_latencies_ms, 0.95),
        p99_latency_ms=percentile(all_latencies_ms, 0.99),
    )


def create_operation_requests(
    operation: str,
    prefix: str,
    client_count: int,
    requests_per_client: int,
) -> list[list[Request]]:
    requests_by_client: list[list[Request]] = []

    for client_id in range(client_count):
        client_requests: list[Request] = []

        for request_index in range(requests_per_client):
            key = f"{prefix}_{client_id}_{request_index}"
            value = f"value{request_index}"

            if operation == "PUT":
                client_requests.append((f"PUT {key} {value}", "OK"))
            elif operation == "GET":
                client_requests.append((f"GET {key}", f"VALUE {value}"))
            elif operation == "DELETE":
                client_requests.append((f"DELETE {key}", "OK"))
            else:
                raise ValueError(f"Unsupported operation: {operation}")

        requests_by_client.append(client_requests)

    return requests_by_client


def create_mixed_requests(
    workload: MixedWorkload,
    prefix: str,
    client_count: int,
    requests_per_client: int,
    random_seed: int,
) -> tuple[list[list[Request]], list[list[Request]]]:
    get_count = requests_per_client * workload.get_percent // 100
    put_count = requests_per_client * workload.put_percent // 100
    delete_count = requests_per_client - get_count - put_count

    requests_by_client: list[list[Request]] = []
    setup_by_client: list[list[Request]] = []

    for client_id in range(client_count):
        read_key_count = min(100, max(1, get_count))
        client_setup: list[Request] = []
        client_requests: list[Request] = []

        for read_index in range(read_key_count):
            key = f"{prefix}_read_{client_id}_{read_index}"
            value = f"read{read_index}"
            client_setup.append((f"PUT {key} {value}", "OK"))

        for delete_index in range(delete_count):
            key = f"{prefix}_delete_{client_id}_{delete_index}"
            client_setup.append((f"PUT {key} delete_value", "OK"))

        for get_index in range(get_count):
            read_index = get_index % read_key_count
            key = f"{prefix}_read_{client_id}_{read_index}"
            client_requests.append((f"GET {key}", f"VALUE read{read_index}"))

        for put_index in range(put_count):
            key = f"{prefix}_put_{client_id}_{put_index}"
            client_requests.append((f"PUT {key} put_value", "OK"))

        for delete_index in range(delete_count):
            key = f"{prefix}_delete_{client_id}_{delete_index}"
            client_requests.append((f"DELETE {key}", "OK"))

        randomizer = random.Random(random_seed + client_id)
        randomizer.shuffle(client_requests)

        requests_by_client.append(client_requests)
        setup_by_client.append(client_setup)

    return requests_by_client, setup_by_client


def benchmark_concurrency_scaling(
    cluster: BenchmarkCluster,
    client_counts: list[int],
    requests_per_client: int,
    trials: int,
) -> list[tuple[int, str, Metrics]]:
    rows: list[tuple[int, str, Metrics]] = []

    for client_count in client_counts:
        samples: dict[str, list[Metrics]] = {
            "PUT": [],
            "GET": [],
            "DELETE": [],
        }

        for trial in range(trials):
            print(
                f"Concurrency: {client_count} clients, trial {trial + 1}/{trials}",
                flush=True,
            )
            cluster.reset(3)
            prefix = f"scale_{client_count}_{trial}"

            for operation in ["PUT", "GET", "DELETE"]:
                requests = create_operation_requests(
                    operation,
                    prefix,
                    client_count,
                    requests_per_client,
                )
                metrics = run_workload(cluster.nodes, requests)
                samples[operation].append(metrics)

        for operation in ["PUT", "GET", "DELETE"]:
            rows.append((client_count, operation, median_metrics(samples[operation])))

    return rows


def benchmark_mixed_workloads(
    cluster: BenchmarkCluster,
    mixed_requests_per_client: int,
    trials: int,
) -> list[tuple[MixedWorkload, Metrics]]:
    workloads = [
        MixedWorkload("Read-heavy", 80, 10, 10),
        MixedWorkload("Balanced", 50, 25, 25),
    ]
    rows: list[tuple[MixedWorkload, Metrics]] = []
    client_count = 8

    for workload_index, workload in enumerate(workloads):
        samples: list[Metrics] = []

        for trial in range(trials):
            print(
                f"Mixed {workload.name}: trial {trial + 1}/{trials}",
                flush=True,
            )
            cluster.reset(3)
            requests, setup = create_mixed_requests(
                workload,
                f"mixed_{workload_index}_{trial}",
                client_count,
                mixed_requests_per_client,
                random_seed=1000 + trial,
            )
            samples.append(run_workload(cluster.nodes, requests, setup))

        rows.append((workload, median_metrics(samples)))

    return rows


def benchmark_node_scaling(
    cluster: BenchmarkCluster,
    mixed_requests_per_client: int,
    trials: int,
) -> list[tuple[int, Metrics]]:
    workload = MixedWorkload("Read-heavy", 80, 10, 10)
    rows: list[tuple[int, Metrics]] = []
    client_count = 8

    for node_count in [1, 2, 3]:
        samples: list[Metrics] = []

        for trial in range(trials):
            print(
                f"Node scaling: {node_count} node(s), trial {trial + 1}/{trials}",
                flush=True,
            )
            cluster.reset(node_count)
            requests, setup = create_mixed_requests(
                workload,
                f"nodes_{trial}",
                client_count,
                mixed_requests_per_client,
                random_seed=2000 + trial,
            )
            samples.append(
                run_workload(cluster.nodes[:node_count], requests, setup)
            )

        rows.append((node_count, median_metrics(samples)))

    return rows


def measure_shard_balance(key_count: int = SHARD_BALANCE_KEYS) -> list[int]:
    counts = [0, 0, 0]

    for key_index in range(key_count):
        key = f"balance_key_{key_index}"
        counts[shard_index(key, 3)] += 1

    return counts


def generate_history_logs(
    log_paths: list[Path],
    key_count: int,
    version_count: int,
) -> None:
    writers = [
        log_path.open("w", encoding="utf-8")
        for log_path in log_paths
    ]

    try:
        for version in range(version_count):
            for key_index in range(key_count):
                key = f"history_key_{key_index}"
                node_index = shard_index(key, len(log_paths))
                writers[node_index].write(f"PUT {key} version{version}\n")

        for key_index in range(0, key_count, 2):
            key = f"history_key_{key_index}"
            node_index = shard_index(key, len(log_paths))
            writers[node_index].write(f"DELETE {key}\n")
    finally:
        for writer in writers:
            writer.close()


def count_log_records(log_paths: list[Path]) -> int:
    record_count = 0

    for log_path in log_paths:
        with log_path.open("r", encoding="utf-8") as log_file:
            record_count += sum(1 for _ in log_file)

    return record_count


def total_log_bytes(log_paths: list[Path]) -> int:
    return sum(log_path.stat().st_size for log_path in log_paths)


def validate_history(nodes: list[Node], latest_version: int) -> None:
    client = ShardedClient(nodes)

    try:
        _, deleted_response = client.request("GET history_key_0")
        _, live_response = client.request("GET history_key_1")

        expect(deleted_response == "NOT_FOUND", "Deleted history key recovered.")
        expect(
            live_response == f"VALUE version{latest_version}",
            "Live history key recovered with the wrong value.",
        )
    finally:
        client.close()


def benchmark_compaction_and_recovery(
    cluster: BenchmarkCluster,
    history_keys: int,
    history_versions: int,
    trials: int,
) -> CompactionMetrics:
    print("Generating controlled append-only history...", flush=True)
    cluster.stop()
    cluster.clear_logs()
    generate_history_logs(cluster.log_paths, history_keys, history_versions)

    records_before = count_log_records(cluster.log_paths)
    bytes_before = total_log_bytes(cluster.log_paths)
    recovery_before_samples: list[float] = []

    for trial in range(trials):
        print(f"Recovery before compaction: trial {trial + 1}/{trials}", flush=True)
        recovery_before_samples.append(cluster.start(3) * 1000)
        validate_history(cluster.nodes, history_versions - 1)
        cluster.stop()

    cluster.start(3)
    admin_client = ShardedClient(cluster.nodes)

    try:
        for node_index in range(3):
            response = admin_client.request_node(node_index, "GET history_key_0")
            expect(response == "NOT_FOUND", "Compaction warmup returned bad data.")

        compaction_start = time.perf_counter()
        compact_results = admin_client.compact_all()
        compaction_time = time.perf_counter() - compaction_start

        expect(
            all(response == "OK" for _, response in compact_results),
            "Compaction failed on at least one node.",
        )
        validate_history(cluster.nodes, history_versions - 1)
    finally:
        admin_client.close()
        cluster.stop()

    records_after = count_log_records(cluster.log_paths)
    bytes_after = total_log_bytes(cluster.log_paths)
    recovery_after_samples: list[float] = []

    for trial in range(trials):
        print(f"Recovery after compaction: trial {trial + 1}/{trials}", flush=True)
        recovery_after_samples.append(cluster.start(3) * 1000)
        validate_history(cluster.nodes, history_versions - 1)
        cluster.stop()

    return CompactionMetrics(
        records_before=records_before,
        records_after=records_after,
        bytes_before=bytes_before,
        bytes_after=bytes_after,
        compaction_time_seconds=compaction_time,
        recovery_before_ms=statistics.median(recovery_before_samples),
        recovery_after_ms=statistics.median(recovery_after_samples),
    )


def format_bytes(byte_count: int) -> str:
    return f"{byte_count / (1024 * 1024):.2f} MiB"


def print_metrics_row(prefix_columns: list[str], metrics: Metrics) -> None:
    columns = prefix_columns + [
        f"{metrics.total_requests:,}",
        f"{metrics.throughput:,.0f}",
        f"{metrics.average_latency_ms:.3f}",
        f"{metrics.p50_latency_ms:.3f}",
        f"{metrics.p95_latency_ms:.3f}",
        f"{metrics.p99_latency_ms:.3f}",
    ]
    print("| " + " | ".join(columns) + " |")


def print_report(
    server_binary: Path,
    trials: int,
    requests_per_client: int,
    mixed_requests_per_client: int,
    history_keys: int,
    history_versions: int,
    concurrency_rows: list[tuple[int, str, Metrics]],
    mixed_rows: list[tuple[MixedWorkload, Metrics]],
    node_rows: list[tuple[int, Metrics]],
    shard_counts: list[int],
    compaction: CompactionMetrics,
) -> None:
    print()
    print("# Final Distributed Benchmark Results")
    print()
    print(f"- Server binary: `{server_binary}`")
    print(f"- Trials per timed row: {trials} (reported values are medians)")
    print(f"- Platform: {platform.platform()}")
    print(f"- Logical CPUs: {os.cpu_count()}")
    print(f"- Python: {platform.python_version()}")
    print("- Transport: localhost TCP with persistent per-node connections")
    print("- Durability: per-write flush and fsync enabled")
    print("- State: separate temporary log per node and fresh logs between trials")
    print(f"- Concurrent scaling: {requests_per_client} requests/client/operation")
    print(f"- Mixed workloads: {mixed_requests_per_client} requests/client")
    print(
        f"- Compaction history: {history_keys:,} keys, "
        f"{history_versions} PUT versions/key, then half deleted"
    )

    print()
    print("## Three-Node Concurrent Scaling")
    print()
    print("| Clients | Operation | Requests | Requests/sec | Avg ms | P50 ms | P95 ms | P99 ms |")
    print("|---:|---|---:|---:|---:|---:|---:|---:|")

    for client_count, operation, metrics in concurrency_rows:
        print_metrics_row([str(client_count), operation], metrics)

    print()
    print("## Three-Node Mixed Workloads (8 Clients)")
    print()
    print("| Workload | Mix | Requests | Requests/sec | Avg ms | P50 ms | P95 ms | P99 ms |")
    print("|---|---|---:|---:|---:|---:|---:|---:|")

    for workload, metrics in mixed_rows:
        workload_mix = (
            f"{workload.get_percent}% GET / "
            f"{workload.put_percent}% PUT / "
            f"{workload.delete_percent}% DELETE"
        )
        print_metrics_row([workload.name, workload_mix], metrics)

    print()
    print("## Node Scaling (8 Clients, 80/10/10 Read-Heavy Mix)")
    print()
    print("| Nodes | Requests | Requests/sec | Avg ms | P50 ms | P95 ms | P99 ms |")
    print("|---:|---:|---:|---:|---:|---:|---:|")

    for node_count, metrics in node_rows:
        print_metrics_row([str(node_count)], metrics)

    ideal_count = sum(shard_counts) / len(shard_counts)
    max_deviation = max(abs(count - ideal_count) for count in shard_counts)
    max_deviation_percent = max_deviation / ideal_count * 100

    print()
    print("## FNV-1a Shard Balance")
    print()
    print("| Node | Keys | Share |")
    print("|---:|---:|---:|")

    for node_index, count in enumerate(shard_counts):
        share = count / sum(shard_counts) * 100
        print(f"| {node_index} | {count:,} | {share:.2f}% |")

    print()
    print(f"Maximum deviation from ideal: {max_deviation_percent:.2f}%")

    record_reduction = (
        1 - compaction.records_after / compaction.records_before
    ) * 100
    byte_reduction = (1 - compaction.bytes_after / compaction.bytes_before) * 100
    recovery_change = (
        1 - compaction.recovery_after_ms / compaction.recovery_before_ms
    ) * 100

    if recovery_change >= 0:
        recovery_description = f"{recovery_change:.1f}% faster"
    else:
        recovery_description = f"{abs(recovery_change):.1f}% slower"

    print()
    print("## Compaction and Recovery")
    print()
    print("| Metric | Before | After | Change |")
    print("|---|---:|---:|---:|")
    print(
        f"| Log records | {compaction.records_before:,} | "
        f"{compaction.records_after:,} | {record_reduction:.2f}% smaller |"
    )
    print(
        f"| Log size | {format_bytes(compaction.bytes_before)} | "
        f"{format_bytes(compaction.bytes_after)} | {byte_reduction:.2f}% smaller |"
    )
    print(
        f"| Median cluster-ready recovery | {compaction.recovery_before_ms:.1f} ms | "
        f"{compaction.recovery_after_ms:.1f} ms | {recovery_description} |"
    )
    print()
    print(
        f"End-to-end COMPACT time across all three nodes: "
        f"{compaction.compaction_time_seconds:.3f} seconds"
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark the final three-node distributed key-value store."
    )
    parser.add_argument(
        "--server",
        type=Path,
        default=Path("build-release/kv_server"),
        help="Path to the Release kv_server binary.",
    )
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument(
        "--requests-per-client",
        type=int,
        default=DEFAULT_REQUESTS_PER_CLIENT,
    )
    parser.add_argument(
        "--mixed-requests-per-client",
        type=int,
        default=DEFAULT_MIXED_REQUESTS_PER_CLIENT,
    )
    parser.add_argument("--history-keys", type=int, default=DEFAULT_HISTORY_KEYS)
    parser.add_argument(
        "--history-versions",
        type=int,
        default=DEFAULT_HISTORY_VERSIONS,
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    server_binary = arguments.server.resolve()

    expect(server_binary.is_file(), f"Server binary not found: {server_binary}")
    expect(arguments.trials > 0, "Trials must be positive.")
    expect(arguments.requests_per_client > 0, "Request count must be positive.")
    expect(
        arguments.mixed_requests_per_client >= 100,
        "Mixed request count must be at least 100.",
    )
    expect(
        arguments.mixed_requests_per_client % 20 == 0,
        "Mixed request count must be divisible by 20 for exact workload ratios.",
    )
    expect(arguments.history_keys >= 2, "History key count must be at least two.")
    expect(
        arguments.history_keys % 2 == 0,
        "History key count must be even so exactly half can be deleted.",
    )
    expect(arguments.history_versions > 0, "History versions must be positive.")

    with tempfile.TemporaryDirectory(prefix="distributed_kv_benchmark_") as directory:
        cluster = BenchmarkCluster(server_binary, Path(directory))

        try:
            concurrency_rows = benchmark_concurrency_scaling(
                cluster,
                DEFAULT_CLIENT_COUNTS,
                arguments.requests_per_client,
                arguments.trials,
            )
            mixed_rows = benchmark_mixed_workloads(
                cluster,
                arguments.mixed_requests_per_client,
                arguments.trials,
            )
            node_rows = benchmark_node_scaling(
                cluster,
                arguments.mixed_requests_per_client,
                arguments.trials,
            )
            shard_counts = measure_shard_balance()
            compaction = benchmark_compaction_and_recovery(
                cluster,
                arguments.history_keys,
                arguments.history_versions,
                arguments.trials,
            )
        finally:
            cluster.stop()

    print_report(
        server_binary,
        arguments.trials,
        arguments.requests_per_client,
        arguments.mixed_requests_per_client,
        arguments.history_keys,
        arguments.history_versions,
        concurrency_rows,
        mixed_rows,
        node_rows,
        shard_counts,
        compaction,
    )


if __name__ == "__main__":
    main()
