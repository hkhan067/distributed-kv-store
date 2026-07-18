import socket
import threading
import time

HOST = "10.154.222.98"
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

def create_command(operation: str, client_count: int, 
                   client_id: int, index: int) -> str:
    key = f"bench_{client_count}_{client_id}_{index}"
    
    if operation == "PUT":
        return f"PUT {key} value{index}\n"
    elif operation == "GET":
        return f"GET {key}\n"
    else:
        return f"DELETE {key}\n"

def run_client(operation: str, client_count: str, client_id: int, 
               ready_barrier: threading.Barrier, start_event: threading.Event,
               results: list, errors: list) -> None:
    try:
        client_socket = socket.create_connection((HOST, PORT), timeout=5)
        
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
            receive_response(client_socket)
            
            request_end = time.perf_counter()
            
            latency_ms = (request_end - request_start) * 1000
            latencies_ms.append(latency_ms)
        
        client_socket.close()
        results[client_id] = latencies_ms
        
    except Exception as error:
        errors[client_id] = error
        
        try:
            ready_barrier.abort()
        except threading.BrokenBarrierError:
            pass

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
    except threading.BrokenBarrierError:
        start_event.set()
        
        for client_thread in threads:
            client_thread.join()
            
        raise RuntimeError(f"Client connection failed: {errors}")
    
    start_time = time.perf_counter()
    start_event()
    

def main():
    return

if __name__ == "__main__":
    main()
    