import time
from concurrent.futures import ThreadPoolExecutor
import threading

def dummy_execution_task(task_id, delay=0.5):
    start_time = time.time()
    thread_name = threading.current_thread().name
    print(f"[Task {task_id}] Started on {thread_name} at {start_time:.4f}")
    time.sleep(delay)
    end_time = time.time()
    print(f"[Task {task_id}] Finished on {thread_name} at {end_time:.4f} (Duration: {end_time - start_time:.4f}s)")
    return task_id

def test_threadpool_concurrency():
    # Menggunakan max_workers=5 seperti di webhook_server.py
    executor = ThreadPoolExecutor(max_workers=5)
    
    num_tasks = 15
    task_delay = 0.5 # 500ms simulasi waktu pengerjaan tugas (misal API request / AI filter)
    
    print(f"=== SIMULASI CONCURRENCY THREADPOOL (max_workers=5, tasks={num_tasks}) ===")
    start_test = time.time()
    
    futures = []
    # Submit all tasks immediately (non-blocking)
    for i in range(num_tasks):
        submit_time = time.time()
        future = executor.submit(dummy_execution_task, i, task_delay)
        futures.append((i, submit_time, future))
        
    print(f"Semua {num_tasks} task telah disubmit dalam {time.time() - start_test:.4f}s")
    
    # Tunggu dan hitung latency masing-masing task
    for task_id, submit_time, future in futures:
        result = future.result()
        # Kami mengukur waktu dari submit hingga eksekusi selesai
        total_latency = time.time() - submit_time
        print(f"[Result {task_id}] Latency dari submit ke selesai: {total_latency:.4f}s")
        
    executor.shutdown(wait=True)
    print(f"Total waktu uji: {time.time() - start_test:.4f}s")

if __name__ == "__main__":
    test_threadpool_concurrency()
