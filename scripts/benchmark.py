import socket
import time

HOST = "192.168.4.22"
PORT = 8080
NUM_REQUESTS = 10000


def send_command(command: str) -> str:
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    try:
        client_socket.connect((HOST, PORT))
        client_socket.sendall(command.encode("utf-8"))
        
        response = client_socket.recv(1024);
        return response.decode("utf-8").strip()
    finally:
        client_socket.close()
    
    
def run_benchmark(name: str, commands: list[str]) -> None:
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.connect((HOST, PORT))
    start_time = time.perf_counter()
    
    for command in commands:
        client_socket.sendall(command.encode("utf-8"))
        response = client_socket.recv(1024)

        if not response:
            raise ConnectionError("Server closed the connection.")
    end_time = time.perf_counter()
    
    client_socket.close()
    
    total_time = (end_time - start_time) 
    throughput = len(commands) / total_time
    average_latency_ms = (total_time / len(commands)) * 1000
    
    print()
    print(name)
    print("-" * len(name))
    print(f"Total requests: {len(commands)}")
    print(f"Total time: {total_time:.4f} seconds")
    print(f"Throughput: {throughput:.2f} requests/second")
    print(f"Average latency: {average_latency_ms:.4f} ms")
    
    
def main() -> None:
    put_commands    : list[str] = []
    get_commands    : list[str] = []
    delete_commands : list[str] = []
    
    for index in range(NUM_REQUESTS):
        put_commands.append(f"PUT key{index} value{index}\n")
        get_commands.append(f"GET key{index}\n")
        delete_commands.append(f"DELETE key{index}\n")
        
    run_benchmark("PUT", put_commands)
    run_benchmark("GET", get_commands)
    run_benchmark("DELETE", delete_commands)
    
    
if __name__ == "__main__":
    main()
