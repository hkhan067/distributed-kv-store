import socket
import sys
from typing import BinaryIO, Optional


Node = tuple[str, int]

DEFAULT_NODES: list[Node] = [
    ("127.0.0.1", 8080),
    ("127.0.0.1", 8081),
    ("127.0.0.1", 8082),
]

FNV_OFFSET_BASIS = 14695981039346656037
FNV_PRIME = 1099511628211
UINT64_MASK = 0xFFFFFFFFFFFFFFFF


def stable_hash(key: str) -> int:
    hash_value = FNV_OFFSET_BASIS

    for byte in key.encode("utf-8"):
        hash_value ^= byte
        hash_value = (hash_value * FNV_PRIME) & UINT64_MASK

    return hash_value


def shard_index(key: str, node_count: int) -> int:
    if node_count <= 0:
        raise ValueError("At least one node is required.")

    return stable_hash(key) % node_count


def parse_node(text: str) -> Node:
    host, separator, port_text = text.rpartition(":")

    if not separator or not host or not port_text:
        raise ValueError(f"Invalid node '{text}'. Expected HOST:PORT.")

    try:
        port = int(port_text)
    except ValueError as error:
        raise ValueError(f"Invalid port in node '{text}'.") from error

    if port < 1 or port > 65535:
        raise ValueError(f"Port in node '{text}' must be from 1 to 65535.")

    return host, port


def format_node(node: Node) -> str:
    return f"{node[0]}:{node[1]}"


class ShardedClient:
    def __init__(self, nodes: list[Node]) -> None:
        if not nodes:
            raise ValueError("At least one node is required.")

        if len(set(nodes)) != len(nodes):
            raise ValueError("Each node address must be unique.")

        self.nodes = list(nodes)
        self.sockets: list[Optional[socket.socket]] = [None] * len(nodes)
        self.streams: list[Optional[BinaryIO]] = [None] * len(nodes)

    def _connect(self, index: int) -> BinaryIO:
        existing_stream = self.streams[index]

        if existing_stream is not None:
            return existing_stream

        node = self.nodes[index]
        client_socket: Optional[socket.socket] = None

        try:
            client_socket = socket.create_connection(node, timeout=5)
            stream = client_socket.makefile("rwb")
        except OSError as error:
            if client_socket is not None:
                client_socket.close()

            raise ConnectionError(
                f"Node {index} ({format_node(node)}) is unavailable: {error}"
            ) from error

        self.sockets[index] = client_socket
        self.streams[index] = stream
        return stream

    def _disconnect(self, index: int) -> None:
        stream = self.streams[index]
        client_socket = self.sockets[index]

        self.streams[index] = None
        self.sockets[index] = None

        if stream is not None:
            try:
                stream.close()
            except (OSError, ValueError):
                pass

        if client_socket is not None:
            try:
                client_socket.close()
            except (OSError, ValueError):
                pass

    def request_node(self, index: int, command: str) -> str:
        stream = self._connect(index)

        try:
            request = command.rstrip("\r\n") + "\n"
            stream.write(request.encode("utf-8"))
            stream.flush()

            response = stream.readline()

            if not response.endswith(b"\n"):
                raise ConnectionError("server returned an incomplete response")

            return response.decode("utf-8").rstrip("\r\n")
        except (OSError, UnicodeError) as error:
            self._disconnect(index)
            node = self.nodes[index]
            raise ConnectionError(
                f"Node {index} ({format_node(node)}) is unavailable: {error}"
            ) from error

    def request(self, command: str) -> tuple[int, str]:
        parts = command.split()

        if not parts:
            raise ValueError("Key command cannot be empty.")

        operation = parts[0].upper()
        valid_put = operation == "PUT" and len(parts) == 3
        valid_read_or_delete = operation in {"GET", "DELETE"} and len(parts) == 2

        if not valid_put and not valid_read_or_delete:
            raise ValueError("Expected PUT key value, GET key, or DELETE key.")

        key = parts[1]
        normalized_command = " ".join([operation] + parts[1:])
        index = shard_index(key, len(self.nodes))
        response = self.request_node(index, normalized_command)
        return index, response

    def compact_all(self) -> list[tuple[int, str]]:
        results: list[tuple[int, str]] = []

        for index in range(len(self.nodes)):
            try:
                response = self.request_node(index, "COMPACT")
            except ConnectionError as error:
                response = f"ERROR {error}"

            results.append((index, response))

        return results

    def exit_all(self) -> list[tuple[int, str]]:
        results: list[tuple[int, str]] = []

        for index, stream in enumerate(self.streams):
            if stream is None:
                continue

            try:
                response = self.request_node(index, "EXIT")
            except ConnectionError as error:
                response = f"ERROR {error}"

            results.append((index, response))
            self._disconnect(index)

        return results

    def close(self) -> None:
        for index in range(len(self.nodes)):
            self._disconnect(index)


def print_result(client: ShardedClient, index: int, response: str) -> None:
    node = format_node(client.nodes[index])
    print(f"Node {index} ({node}): {response}")


def print_commands() -> None:
    print("Commands: PUT key value, GET key, DELETE key, COMPACT, EXIT")


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] in {"-h", "--help"}:
        print(f"Usage: {sys.argv[0]} [HOST:PORT ...]")
        print_commands()
        return

    try:
        nodes = [parse_node(text) for text in sys.argv[1:]]
        client = ShardedClient(nodes if nodes else DEFAULT_NODES)
    except ValueError as error:
        print(f"ERROR: {error}")
        raise SystemExit(1) from error

    print("Node connections open lazily and then remain persistent:")

    for index, node in enumerate(client.nodes):
        print(f"  Node {index}: {format_node(node)}")

    print_commands()

    try:
        while True:
            try:
                line = input("sharded> ").strip()
            except EOFError:
                break

            if not line:
                continue

            parts = line.split()
            operation = parts[0].upper()

            try:
                if operation == "PUT" and len(parts) == 3:
                    command = f"PUT {parts[1]} {parts[2]}"
                    index, response = client.request(command)
                    print_result(client, index, response)
                elif operation in {"GET", "DELETE"} and len(parts) == 2:
                    command = f"{operation} {parts[1]}"
                    index, response = client.request(command)
                    print_result(client, index, response)
                elif operation == "COMPACT" and len(parts) == 1:
                    for index, response in client.compact_all():
                        print_result(client, index, response)
                elif operation == "EXIT" and len(parts) == 1:
                    for index, response in client.exit_all():
                        print_result(client, index, response)

                    print("GOODBYE")
                    break
                else:
                    print("ERROR invalid command")
                    print_commands()
            except ConnectionError as error:
                print(f"ERROR: {error}")
    except KeyboardInterrupt:
        print()
    finally:
        client.close()


if __name__ == "__main__":
    main()
