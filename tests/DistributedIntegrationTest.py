import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from sharded_client import ShardedClient, parse_node, shard_index, stable_hash


Node = tuple[str, int]


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def expect_value(response: str, expected_value: str, message: str) -> None:
    expect(response == f"VALUE {expected_value}", message)


def find_free_ports(count: int) -> list[int]:
    ports: list[int] = []

    while len(ports) < count:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        if port not in ports:
            ports.append(port)

    return ports


def wait_for_node(node: Node, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 5

    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout is not None else ""
            raise RuntimeError(f"Server exited before listening:\n{output}")

        try:
            with socket.create_connection(node, timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)

    raise RuntimeError(f"Timed out waiting for server at {node[0]}:{node[1]}")


class TestServer:
    def __init__(self, executable: Path, node: Node, log_path: Path) -> None:
        self.executable = executable
        self.node = node
        self.log_path = log_path
        self.process: Optional[subprocess.Popen[str]] = None

    def start(self) -> None:
        expect(self.process is None, "server is already running")

        self.process = subprocess.Popen(
            [str(self.executable), str(self.node[1]), str(self.log_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        wait_for_node(self.node, self.process)

    def stop(self) -> None:
        if self.process is None:
            return

        if self.process.poll() is None:
            self.process.terminate()

            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)

        if self.process.stdout is not None:
            self.process.stdout.close()

        self.process = None


def direct_request(node: Node, command: str) -> str:
    with socket.create_connection(node, timeout=2) as client_socket:
        with client_socket.makefile("rwb") as stream:
            stream.write((command.rstrip("\r\n") + "\n").encode("utf-8"))
            stream.flush()
            response = stream.readline()

    expect(response.endswith(b"\n"), "direct request received an incomplete response")
    return response.decode("utf-8").rstrip("\r\n")


def find_key_for_node(target_index: int, node_count: int) -> str:
    candidate_number = 0

    while True:
        key = f"shard_{target_index}_key_{candidate_number}"

        if shard_index(key, node_count) == target_index:
            return key

        candidate_number += 1


def test_hash_and_node_parsing() -> None:
    expect(
        stable_hash("apple") == 17819163333647859135,
        "FNV-1a hash changed unexpectedly",
    )
    expect(parse_node("localhost:8080") == ("localhost", 8080), "valid node parse")

    for invalid_node in ["localhost", ":8080", "localhost:0", "localhost:70000"]:
        try:
            parse_node(invalid_node)
            raise RuntimeError(f"invalid node was accepted: {invalid_node}")
        except ValueError:
            pass


def test_tcp_framing(node: Node, key: str, expected_value_text: str) -> None:
    with socket.create_connection(node, timeout=2) as client_socket:
        stream = client_socket.makefile("rb")

        client_socket.sendall(b"GET ")
        time.sleep(0.02)
        client_socket.sendall(
            f"{key}\nGET definitely_missing_key\n".encode("utf-8")
        )

        first_response = stream.readline().decode("utf-8").rstrip("\r\n")
        second_response = stream.readline().decode("utf-8").rstrip("\r\n")
        stream.close()

    expect_value(first_response, expected_value_text, "fragmented command failed")
    expect(second_response == "NOT_FOUND", "batched command failed")


def test_request_size_limit(node: Node) -> None:
    with socket.create_connection(node, timeout=2) as client_socket:
        with client_socket.makefile("rb") as stream:
            client_socket.sendall(b"x" * 8193)
            response = stream.readline().decode("utf-8").rstrip("\r\n")

    expect(response == "ERROR request too long", "oversized request was not rejected")


def test_interactive_client(nodes: list[Node], key: str, expected_value_text: str) -> None:
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "sharded_client.py"),
    ]
    command.extend(f"{host}:{port}" for host, port in nodes)

    result = subprocess.run(
        command,
        input=f"GET {key}\nEXIT\n",
        capture_output=True,
        text=True,
        timeout=5,
    )

    expect(result.returncode == 0, f"interactive client failed:\n{result.stdout}")
    expect(
        f"VALUE {expected_value_text}" in result.stdout,
        "interactive client did not return the expected value",
    )


def run_cluster_test(executable: Path) -> None:
    ports = find_free_ports(3)
    nodes = [("127.0.0.1", port) for port in ports]

    with tempfile.TemporaryDirectory(prefix="distributed_integration_") as directory:
        servers = [
            TestServer(executable, node, Path(directory) / f"node{index}.log")
            for index, node in enumerate(nodes)
        ]
        client: Optional[ShardedClient] = None

        try:
            for server in servers:
                server.start()

            keys = [find_key_for_node(index, len(nodes)) for index in range(len(nodes))]
            values = [f"value{index}" for index in range(len(nodes))]

            for index, key in enumerate(keys):
                expect(shard_index(key, len(nodes)) == index, "key routed incorrectly")

            client = ShardedClient(nodes)

            for expected_index, (key, value) in enumerate(zip(keys, values)):
                actual_index, response = client.request(f"PUT {key} {value}")
                expect(actual_index == expected_index, "PUT used the wrong node")
                expect(response == "OK", "PUT failed")

            for expected_index, (key, value) in enumerate(zip(keys, values)):
                actual_index, response = client.request(f"GET {key}")
                expect(actual_index == expected_index, "GET used the wrong node")
                expect_value(response, value, "sharded GET failed")

            for node_index, node in enumerate(nodes):
                for key_index, (key, value) in enumerate(zip(keys, values)):
                    response = direct_request(node, f"GET {key}")

                    if node_index == key_index:
                        expect_value(response, value, "key missing from selected node")
                    else:
                        expect(response == "NOT_FOUND", "key leaked to another shard")

            test_tcp_framing(nodes[0], keys[0], values[0])
            test_request_size_limit(nodes[0])
            test_interactive_client(nodes, keys[0], values[0])

            deleted_index, delete_response = client.request(f"DELETE {keys[2]}")
            expect(deleted_index == 2, "DELETE used the wrong node")
            expect(delete_response == "OK", "DELETE failed")

            compact_results = client.compact_all()
            expect(
                all(response == "OK" for _, response in compact_results),
                "COMPACT did not succeed on every node",
            )

            servers[1].stop()

            try:
                client.request(f"GET {keys[1]}")
                raise RuntimeError("request to stopped shard unexpectedly succeeded")
            except ConnectionError:
                pass

            _, healthy_response = client.request(f"GET {keys[0]}")
            expect_value(healthy_response, values[0], "healthy shard stopped working")

            servers[1].start()
            _, recovered_response = client.request(f"GET {keys[1]}")
            expect_value(recovered_response, values[1], "restarted shard did not recover")

            client.close()
            client = None

            for server in servers:
                server.stop()

            for server in servers:
                server.start()

            client = ShardedClient(nodes)

            _, first_response = client.request(f"GET {keys[0]}")
            _, second_response = client.request(f"GET {keys[1]}")
            _, deleted_response = client.request(f"GET {keys[2]}")

            expect_value(first_response, values[0], "node 0 recovery failed")
            expect_value(second_response, values[1], "node 1 recovery failed")
            expect(deleted_response == "NOT_FOUND", "deleted key recovered unexpectedly")
        finally:
            if client is not None:
                client.close()

            for server in servers:
                server.stop()


def main() -> None:
    if len(sys.argv) != 2:
        raise RuntimeError("Expected path to kv_server executable.")

    executable = Path(sys.argv[1]).resolve()
    expect(executable.is_file(), f"Server executable not found: {executable}")

    test_hash_and_node_parsing()
    run_cluster_test(executable)

    print("Level 6 integration tests passed.")


if __name__ == "__main__":
    main()
