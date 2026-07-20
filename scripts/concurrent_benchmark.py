import socket
import threading
import time


HOST = "127.0.0.1"
PORT = 8080

REQUESTS_PER_CLIENT = 10000
CLIENT_COUNTS = [1, 2, 4, 8]


def receive_response(client_socket: socket.socket) -> bytes:
    response = bytearray()

    while not response.endswith(b"\n"):
        chunk = client_socket.recv(1024)

        if not chunk:
            raise ConnectionError("Server closed the connection.")

        response.extend(chunk)

    return bytes(response)


def create_command(
    operation: str,
    client_count: int,
    client_id: int,
    index: int
) -> str:
    key = f"bench_{client_count}_{client_id}_{index}"

    if operation == "PUT":
        return f"PUT {key} value{index}\n"
    elif operation == "GET":
        return f"GET {key}\n"
    elif operation == "DELETE":
        return f"DELETE {key}\n"

    raise ValueError(f"Unsupported operation: {operation}")


def expected_response(operation: str, index: int) -> bytes:
    if operation == "GET":
        return f"VALUE value{index}\n".encode("utf-8")

    return b"OK\n"


def run_client(
    operation: str,
    client_count: int,
    client_id: int,
    ready_barrier: threading.Barrier,
    start_event: threading.Event,
    results: list,
    errors: list
) -> None:
    try:
        with socket.create_connection((HOST, PORT), timeout=5) as client_socket:
            ready_barrier.wait()
            start_event.wait()

            latencies_ms: list[float] = []

            for index in range(REQUESTS_PER_CLIENT):
                command = create_command(
                    operation,
                    client_count,
                    client_id,
                    index
                )

                request_start = time.perf_counter()

                client_socket.sendall(command.encode("utf-8"))
                response = receive_response(client_socket)

                request_end = time.perf_counter()

                if response != expected_response(operation, index):
                    raise RuntimeError(
                        f"Unexpected response for {command.strip()}: "
                        f"{response.decode('utf-8').strip()}"
                    )

                latency_ms = (request_end - request_start) * 1000
                latencies_ms.append(latency_ms)

            results[client_id] = latencies_ms

    except Exception as error:
        errors[client_id] = error
        ready_barrier.abort()


def percentile(values: list[float], percentage: float) -> float:
    sorted_values = sorted(values)
    index = int((len(sorted_values) - 1) * percentage)
    return sorted_values[index]


def run_benchmark(operation: str, client_count: int) -> None:
    ready_barrier = threading.Barrier(client_count + 1)
    start_event = threading.Event()

    results: list = [None] * client_count
    errors: list = [None] * client_count
    threads: list[threading.Thread] = []

    for client_id in range(client_count):
        client_thread = threading.Thread(
            target=run_client,
            args=(
                operation,
                client_count,
                client_id,
                ready_barrier,
                start_event,
                results,
                errors
            )
        )

        client_thread.start()
        threads.append(client_thread)

    try:
        ready_barrier.wait()
    except threading.BrokenBarrierError as error:
        start_event.set()

        for client_thread in threads:
            client_thread.join()

        raise RuntimeError(f"Client connection failed: {errors}") from error

    start_time = time.perf_counter()
    start_event.set()

    for client_thread in threads:
        client_thread.join()

    end_time = time.perf_counter()

    failed_clients = [error for error in errors if error is not None]

    if failed_clients:
        raise RuntimeError(f"Benchmark client failed: {failed_clients[0]}")

    all_latencies_ms: list[float] = []

    for client_latencies in results:
        all_latencies_ms.extend(client_latencies)

    total_requests = client_count * REQUESTS_PER_CLIENT
    total_time = end_time - start_time
    throughput = total_requests / total_time
    average_latency_ms = sum(all_latencies_ms) / len(all_latencies_ms)

    print()
    print(f"{operation} with {client_count} clients")
    print("-" * 30)
    print(f"Total requests: {total_requests}")
    print(f"Total time: {total_time:.4f} seconds")
    print(f"Throughput: {throughput:.2f} requests/second")
    print(f"Average latency: {average_latency_ms:.4f} ms")
    print(f"P50 latency: {percentile(all_latencies_ms, 0.50):.4f} ms")
    print(f"P95 latency: {percentile(all_latencies_ms, 0.95):.4f} ms")
    print(f"P99 latency: {percentile(all_latencies_ms, 0.99):.4f} ms")


def main() -> None:
    for client_count in CLIENT_COUNTS:
        print()
        print(f"Testing {client_count} concurrent clients")

        run_benchmark("PUT", client_count)
        run_benchmark("GET", client_count)
        run_benchmark("DELETE", client_count)


if __name__ == "__main__":
    main()
