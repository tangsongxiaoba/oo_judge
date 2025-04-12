import ast
import os
import pathlib
import sys
import subprocess
import time
import signal
import threading
import queue
import tempfile
import psutil
import re
import time
from collections import defaultdict
import numpy as np
import concurrent.futures
import random # Added for preset selection
import traceback # For logging errors from threads
import yaml

# --- Default Configuration, will be replaced by config.yml ---
CPU_TIME_LIMIT = 10.0  # seconds
MIN_WALL_TIME_LIMIT = 120.0 # seconds - Renamed: Minimum wall time limit
PERF_P_VALUE = 0.10
ENABLE_DETAILED_DEBUG = False # Set to True for verbose debugging
LOG_DIR = "logs" # Define log directory constant
TMP_DIR = "tmp"  # Define temporary file directory constant
DEFAULT_GEN_MAX_TIME = 50.0 # Default generator -t value if not specified in preset
DEFAULT_PARALLEL_ROUNDS = 16 # Default number of rounds to run in parallel
CLEANUP_SUCCESSFUL_ROUNDS = True

# Helper function for conditional debug printing
def debug_print(*args, **kwargs):
    if ENABLE_DETAILED_DEBUG:
        # Add thread identifier for clarity in parallel runs
        thread_name = threading.current_thread().name
        print(f"DEBUG [{time.time():.4f}] [{thread_name}]:", *args, **kwargs, file=sys.stderr, flush=True)

class JarTester:
    # --- Static variables ---
    _jar_files = []
    _finder_executed = False
    _jar_dir = ""
    _gen_script_path = ""
    _checker_script_path = ""
    _interrupted = False # Global interrupt flag
    _round_counter = 0 # Global counter for assigning round numbers
    _log_file_path = None
    _all_results_history = defaultdict(lambda: {'correct_runs': 0, 'total_runs': 0, 'scores': []})
    _gen_arg_presets = []
    _raw_preset_commands = []
    _loaded_preset_commands = []

    # --- Locks for shared resources ---
    _history_lock = threading.Lock()
    _log_lock = threading.Lock()
    _round_counter_lock = threading.Lock() # Lock for incrementing round counter
    _console_lock = threading.Lock()
    # <<< NEW: Lock and Dict for tracking running PIDs >>>
    _pid_lock = threading.Lock()
    _running_pids = {} # pid -> round_num mapping

    @staticmethod
    def _register_pid(pid, round_num):
        if pid is None or pid <= 0: return
        with JarTester._pid_lock:
            JarTester._running_pids[pid] = round_num
            debug_print(f"Registered PID {pid} for Round {round_num}. Active PIDs: {list(JarTester._running_pids.keys())}")

    @staticmethod
    def _unregister_pid(pid):
        if pid is None or pid <= 0: return
        with JarTester._pid_lock:
            removed_round = JarTester._running_pids.pop(pid, None)
            if removed_round is not None:
                 debug_print(f"Unregistered PID {pid} (was Round {removed_round}). Active PIDs: {list(JarTester._running_pids.keys())}")
            # else: # Optional: debug if trying to unregister unknown pid
            #     debug_print(f"Attempted to unregister unknown or already removed PID {pid}")

    @staticmethod
    def _robust_remove_file(file_path_str, max_retries=3, delay_seconds=0.2, log_prefix=""):
        """ Robustly tries to remove a file using pathlib. """
        if not file_path_str or not isinstance(file_path_str, str):
            debug_print(f"{log_prefix} Robust remove skipped: Invalid file path provided ('{file_path_str}').")
            return True

        file_path = pathlib.Path(file_path_str)

        # Log path existence *before* starting attempts
        path_exists_before = file_path.exists()
        # pathlib doesn't have a direct os.W_OK check, rely on exists for now
        debug_print(f"{log_prefix} Robust remove check: Path='{file_path.name}', Exists={path_exists_before}")

        if not path_exists_before:
             debug_print(f"{log_prefix} Robust remove: File '{file_path.name}' does not exist before attempt 1.")
             return True # Already gone

        for attempt in range(max_retries):
            try:
                # Re-check existence just before remove
                if not file_path.exists():
                    debug_print(f"{log_prefix} Robust remove: File '{file_path.name}' disappeared before attempt {attempt + 1}.")
                    return True

                # Use unlink, missing_ok=True prevents error if already gone (double check)
                file_path.unlink(missing_ok=True)

                # Verify deletion
                time.sleep(0.05) # Short pause
                if not file_path.exists():
                    debug_print(f"{log_prefix} Robust remove: Successfully deleted '{file_path.name}' on attempt {attempt + 1} (verified).")
                    return True
                else:
                    debug_print(f"{log_prefix} Robust remove: WARNING - unlink completed on attempt {attempt + 1} for '{file_path.name}' but file still exists!")
                    # Continue to retry

            except OSError as e: # unlink raises OSError for permissions etc.
                # Check if error is because the file is in use (Windows specific check)
                if os.name == 'nt' and isinstance(e, PermissionError) and hasattr(e, 'winerror') and e.winerror == 32: # ERROR_SHARING_VIOLATION
                    debug_print(f"{log_prefix} Robust remove: Attempt {attempt + 1}/{max_retries} failed for '{file_path.name}' due to sharing violation (likely process holding lock): {e}")
                else:
                    debug_print(f"{log_prefix} Robust remove: Attempt {attempt + 1}/{max_retries} failed for '{file_path.name}': {e}")

                if attempt >= max_retries - 1:
                    print(f"WARNING {log_prefix}: Failed to delete file '{file_path.name}' after {max_retries} attempts. Last Error: {e}", file=sys.stderr)
                    return False # Final attempt failed

            except Exception as e:
                print(f"ERROR {log_prefix}: Unexpected error during robust delete of '{file_path.name}' on attempt {attempt + 1}: {e}", file=sys.stderr)
                debug_print(f"{log_prefix} Unexpected error during robust delete", exc_info=True)
                return False # Unexpected error, stop trying

            # Wait before retrying
            if attempt < max_retries - 1:
                 time.sleep(delay_seconds)

        debug_print(f"{log_prefix} Robust remove: Loop finished for '{file_path.name}' without confirmed deletion.")
        # Check existence one last time
        return not file_path.exists()


    @staticmethod
    def _get_next_round_number():
        with JarTester._round_counter_lock:
            JarTester._round_counter += 1
            return JarTester._round_counter

    @staticmethod
    def _clear_screen():
        """Clears the terminal screen."""
        if ENABLE_DETAILED_DEBUG: return
        if threading.current_thread() is threading.main_thread():
             os.system('cls' if os.name == 'nt' else 'clear')

    @staticmethod
    def _find_jar_files():
        """Search for JAR files in the specified directory"""
        if not JarTester._finder_executed:
            try:
                JarTester._jar_dir = os.path.abspath(JarTester._jar_dir)
                JarTester._jar_files = [
                    os.path.join(JarTester._jar_dir, f)
                    for f in os.listdir(JarTester._jar_dir)
                    if f.endswith('.jar')
                ]
                JarTester._finder_executed = True
                print(f"INFO: Found {len(JarTester._jar_files)} JAR files in '{JarTester._jar_dir}'")
            except FileNotFoundError:
                print(f"ERROR: JAR directory not found: '{JarTester._jar_dir}'", file=sys.stderr)
                return False
            except Exception as e:
                print(f"ERROR: Failed to list JAR files in '{JarTester._jar_dir}': {e}", file=sys.stderr)
                return False
        return len(JarTester._jar_files) > 0

    @staticmethod
    def _kill_process_tree(pid, reason="Unknown"):
        """Recursively terminate a process and its children."""
        log_prefix = f"Kill PID {pid} (Reason: {reason})"
        try:
            parent = psutil.Process(pid)
            # Use a snapshot of children to avoid race conditions if new ones spawn
            children = parent.children(recursive=True)
            debug_print(f"{log_prefix}: Target has children: {[c.pid for c in children]}")

            # Terminate children first
            for child in children:
                try:
                    debug_print(f"{log_prefix}: Terminating child PID {child.pid}")
                    child.terminate()
                except psutil.NoSuchProcess:
                    debug_print(f"{log_prefix}: Child PID {child.pid} already gone.")
                except psutil.AccessDenied:
                     debug_print(f"{log_prefix}: Access denied terminating child PID {child.pid}.")
                except Exception as e_child_term:
                     debug_print(f"{log_prefix}: Error terminating child PID {child.pid}: {e_child_term}")


            # Terminate the parent process
            try:
                debug_print(f"{log_prefix}: Terminating parent PID {pid}")
                parent.terminate()
            except psutil.NoSuchProcess:
                 debug_print(f"{log_prefix}: Parent PID {pid} already gone before terminate.")
                 # If parent is gone, children should be too (or reparented), skip wait
                 return
            except psutil.AccessDenied:
                 debug_print(f"{log_prefix}: Access denied terminating parent PID {pid}.")
            except Exception as e_parent_term:
                 debug_print(f"{log_prefix}: Error terminating parent PID {pid}: {e_parent_term}")


            # Wait for termination with a timeout
            # Combine parent and the snapshot of children for waiting
            procs_to_wait = children + [parent]
            # Filter out any process objects that might be invalid now (e.g., access denied earlier)
            valid_procs_to_wait = []
            for p in procs_to_wait:
                try:
                    if p.is_running():
                       valid_procs_to_wait.append(p)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass # Ignore processes that are gone or inaccessible

            if not valid_procs_to_wait:
                debug_print(f"{log_prefix}: No running processes left to wait for after terminate calls.")
                return

            debug_print(f"{log_prefix}: Waiting for {len(valid_procs_to_wait)} processes to terminate...")
            gone, alive = psutil.wait_procs(valid_procs_to_wait, timeout=1.5) # Increased timeout slightly
            debug_print(f"{log_prefix}: After wait_procs: Gone={[(p.pid if hasattr(p,'pid') else '?') for p in gone]}, Alive={[(p.pid if hasattr(p,'pid') else '?') for p in alive]}")

            # Force kill any remaining processes
            for p in alive:
                try:
                    # Check if it's still alive before killing
                    if p.is_running():
                        debug_print(f"{log_prefix}: Force killing remaining process PID {p.pid}")
                        p.kill()
                    # else: # Already gone between wait_procs and now
                    #     debug_print(f"{log_prefix}: Process PID {p.pid} disappeared before final kill.")
                except psutil.NoSuchProcess:
                    debug_print(f"{log_prefix}: Process PID {p.pid} disappeared before final kill.")
                except psutil.AccessDenied:
                    debug_print(f"{log_prefix}: Access denied killing remaining process PID {p.pid}.")
                except Exception as e_kill:
                     debug_print(f"{log_prefix}: Error force killing PID {p.pid}: {e_kill}")


        except psutil.NoSuchProcess:
            debug_print(f"{log_prefix}: Target process PID {pid} not found or already gone.")
        except psutil.AccessDenied:
            print(f"ERROR: Access Denied trying to manage process PID {pid}. Cannot guarantee termination.", file=sys.stderr)
            debug_print(f"{log_prefix}: Access Denied.")
        except Exception as e:
            print(f"ERROR: Exception during process termination for PID {pid}: {e}", file=sys.stderr)
            debug_print(f"{log_prefix}: Unexpected exception during kill", exc_info=True)


    @staticmethod
    def _output_reader(pipe, output_queue, stream_name, pid, error_flag):
        # ... (no changes needed here) ...
        debug_print(f"Output reader ({stream_name}) started for PID {pid}")
        try:
            for line_num, line in enumerate(iter(pipe.readline, '')):
                if error_flag.is_set() or JarTester._interrupted:
                     debug_print(f"Output reader ({stream_name}) stopping early for PID {pid} (error or interrupt)")
                     break
                output_queue.put(line)
            debug_print(f"Output reader ({stream_name}) finished iter loop for PID {pid}")
        except ValueError:
            # Only report if the pipe seems to be open and not an error/interrupt case
            if not error_flag.is_set() and not JarTester._interrupted and pipe and not pipe.closed:
                 debug_print(f"Output reader ({stream_name}) caught ValueError for PID {pid} (pipe not closed)")
            # Ignore ValueError if pipe is closed or error/interrupt occurred, common scenario
        except Exception as e:
            # Only log error if it wasn't due to interrupt/error flag
            if not error_flag.is_set() and not JarTester._interrupted:
                print(f"ERROR: Output reader ({stream_name}) thread crashed for PID {pid}: {e}", file=sys.stderr)
                debug_print(f"Output reader ({stream_name}) thread exception for PID {pid}", exc_info=True)
                error_flag.set() # Signal error if unexpected exception
        finally:
            try:
                if pipe and not pipe.closed:
                    debug_print(f"Output reader ({stream_name}) closing pipe for PID {pid}")
                    pipe.close()
                # else: # Optional: log if pipe was already closed
                #      debug_print(f"Output reader ({stream_name}) pipe already closed for PID {pid}")
            except Exception: pass # Ignore errors during close
            debug_print(f"Output reader ({stream_name}) thread exiting for PID {pid}")


    @staticmethod
    def _run_single_jar(jar_path, input_data_path, current_wall_limit, round_num):
        """Executes a single JAR, monitors it, saves stdout, and runs the checker."""
        jar_basename = os.path.basename(jar_path)
        debug_print(f"Starting run for JAR: {jar_basename} with Wall Limit: {current_wall_limit:.2f}s")
        start_wall_time = time.monotonic()
        process = None
        pid = -1 # Initialize pid
        ps_proc = None
        result = {
            "jar_file": jar_basename, "cpu_time": 0.0, "wall_time": 0.0,
            "status": "PENDING", "error_details": "",
            "stdout_log_path": None, # Will be determined later
            "stderr": [],
            "t_final": None, "wt": None, "w": None, "final_score": 0.0,
            "input_data_path": input_data_path,
            "round_num": round_num, # Pass round_num in result
            "checker_temp_output_path": None # <<< 新增：用于传递检查器临时文件路径
        }
        stdout_reader_thread = None
        stderr_reader_thread = None
        stdout_queue = queue.Queue()
        stderr_queue = queue.Queue()
        error_flag = threading.Event()
        stdout_content = "" # Store stdout content here
        stderr_lines = []   # Store stderr lines here
        temp_output_file = None # <<< 新增：在外部作用域定义，以便 finally 访问

        # <<< Determine potential stdout path early for registration/cleanup >>>
        safe_jar_basename = re.sub(r'[^\w.-]', '_', jar_basename)
        stdout_filename = f"output_{safe_jar_basename}_{round_num}.txt"
        stdout_filepath = os.path.abspath(os.path.join(TMP_DIR, stdout_filename))
        result["stdout_log_path"] = stdout_filepath # Store potential path

        try:
            debug_print(f"Launching JAR: {jar_basename}")
            # ... [启动进程和PID注册逻辑 - 无变化] ...
            process = subprocess.Popen(
                ['java', '-jar', jar_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', bufsize=1
            )
            pid = process.pid
            if pid: JarTester._register_pid(pid, round_num)
            result["status"] = "RUNNING"

            try:
                if pid: ps_proc = psutil.Process(pid)
            except psutil.NoSuchProcess:
                # ... [进程立即消失的处理 - 无变化] ...
                print(f"ERROR: Process {pid} ({jar_basename}) disappeared immediately.", file=sys.stderr)
                result["status"] = "CRASHED"
                result["error_details"] = "Process disappeared immediately"
                error_flag.set()
                return result # finally will unregister

            # ... [启动输出读取线程 - 无变化] ...
            if process.stdout and process.stderr:
                stdout_reader_thread = threading.Thread(target=JarTester._output_reader, args=(process.stdout, stdout_queue, "stdout", pid, error_flag), daemon=True)
                stderr_reader_thread = threading.Thread(target=JarTester._output_reader, args=(process.stderr, stderr_queue, "stderr", pid, error_flag), daemon=True)
                stdout_reader_thread.start()
                stderr_reader_thread.start()

            # ... [写入输入数据 - 无变化] ...
            input_content = None
            try:
                debug_print(f"Reading all input data from {input_data_path} for PID {pid}")
                with open(input_data_path, 'r', encoding='utf-8') as f_in:
                    input_content = f_in.read()
                if input_content is not None and process.stdin:
                    process.stdin.write(input_content)
                    process.stdin.flush()
                if process.stdin: process.stdin.close()
                debug_print(f"Successfully wrote input and closed stdin for PID {pid}")
            except FileNotFoundError:
                 # ... [输入文件未找到处理] ...
                 print(f"ERROR: Input file {input_data_path} not found for PID {pid}", file=sys.stderr)
                 result["status"] = "CRASHED"
                 result["error_details"] = f"Input file not found: {input_data_path}"
                 error_flag.set()
            except (BrokenPipeError, OSError, AttributeError) as e_input:
                 # ... [输入写入错误处理] ...
                 print(f"WARNING: Error writing input or closing stdin for PID {pid} (process likely died): {e_input}", file=sys.stderr)
                 debug_print(f"BrokenPipeError/OSError/AttributeError during stdin write/close for PID {pid}")
                 error_flag.set()
                 try:
                     if process.stdin and not process.stdin.closed: process.stdin.close()
                 except Exception: pass
            except Exception as e_input:
                 # ... [其他输入错误处理] ...
                 print(f"ERROR: Unexpected error reading/writing input for PID {pid}: {e_input}", file=sys.stderr)
                 result["status"] = "CRASHED"
                 result["error_details"] = f"Input read/write error: {e_input}"
                 error_flag.set()
                 try:
                     if process.stdin and not process.stdin.closed: process.stdin.close()
                 except Exception: pass

            # --- Monitoring Loop ---
            # ... [监控循环逻辑 - 无变化] ...
            debug_print(f"Starting monitoring loop for PID {pid}")
            monitor_loops = 0
            process_exited_normally = False
            while True:
                monitor_loops += 1
                # 1. Check Global Interrupt FIRST
                if JarTester._interrupted:
                    debug_print(f"Monitor loop {monitor_loops}: Global interrupt detected for PID {pid}. Breaking.")
                    if result["status"] not in ["TLE", "CTLE", "CRASHED", "CHECKER_ERROR", "INTERRUPTED"]:
                        result["status"] = "INTERRUPTED"
                        result["error_details"] = "Run interrupted by user (Ctrl+C)."
                    error_flag.set() # Signal to kill process
                    break

                # 2. Check if process died on its own
                # ... [检查进程是否仍在运行 - 无变化] ...
                process_still_running = False
                try:
                    if psutil.pid_exists(pid):
                        if ps_proc is None: ps_proc = psutil.Process(pid)
                        if ps_proc.is_running():
                            process_still_running = True
                        else:
                            debug_print(f"Monitor loop {monitor_loops}: ps_proc.is_running() False for PID {pid}. Breaking.")
                            if not error_flag.is_set(): process_exited_normally = True
                    else:
                         debug_print(f"Monitor loop {monitor_loops}: psutil.pid_exists False for PID {pid}. Breaking.")
                         if not error_flag.is_set(): process_exited_normally = True
                    if not process_still_running: break
                except psutil.NoSuchProcess:
                    debug_print(f"Monitor loop {monitor_loops}: NoSuchProcess check for PID {pid}. Breaking.")
                    if not error_flag.is_set(): process_exited_normally = True
                    break
                except Exception as e_check_run:
                    print(f"ERROR: Monitor loop: Error checking if PID {pid} is running: {e_check_run}", file=sys.stderr)
                    if result["status"] not in ["CRASHED", "TLE", "CTLE", "INTERRUPTED", "CHECKER_ERROR"]:
                         result["status"] = "CRASHED"
                         result["error_details"] = f"Tester error checking process status: {e_check_run}"
                    error_flag.set()
                    break

                # 3. Check local error flag
                if error_flag.is_set():
                    # ... [处理本地错误标志 - 无变化] ...
                    debug_print(f"Monitor loop {monitor_loops}: Local error flag set for PID {pid}. Breaking.")
                    if result["status"] not in ["TLE", "CTLE", "CRASHED", "CHECKER_ERROR", "INTERRUPTED"]:
                        result["status"] = "CRASHED" # Or a more specific error status?
                        result["error_details"] = "Run failed due to internal error flag (e.g., I/O)."
                    break

                # 4. Time Limit Checks (CPU and Wall)
                # ... [检查时间限制 - 无变化] ...
                current_wall_time = time.monotonic() - start_wall_time
                current_cpu_time = result["cpu_time"]
                try:
                    if ps_proc:
                        cpu_times = ps_proc.cpu_times()
                        current_cpu_time = cpu_times.user + cpu_times.system
                except psutil.NoSuchProcess:
                    debug_print(f"Monitor loop {monitor_loops}: NoSuchProcess getting CPU times for PID {pid}. Breaking.")
                    if not error_flag.is_set(): process_exited_normally = True
                    break
                except Exception as e_cpu:
                    print(f"ERROR: Monitor loop: Error getting CPU times for PID {pid}: {e_cpu}", file=sys.stderr)
                    if result["status"] not in ["CRASHED", "TLE", "CTLE", "INTERRUPTED", "CHECKER_ERROR"]:
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Tester error getting CPU time: {e_cpu}"
                    error_flag.set()
                    break

                result["cpu_time"] = current_cpu_time
                result["wall_time"] = current_wall_time

                if current_cpu_time > CPU_TIME_LIMIT:
                    debug_print(f"Monitor loop {monitor_loops}: CTLE for PID {pid}")
                    result["status"] = "CTLE"
                    result["error_details"] = f"CPU time {current_cpu_time:.2f}s exceeded limit {CPU_TIME_LIMIT:.2f}s."
                    error_flag.set()
                    break

                if current_wall_time > current_wall_limit:
                    debug_print(f"Monitor loop {monitor_loops}: TLE for PID {pid}")
                    result["status"] = "TLE"
                    result["error_details"] = f"Wall time {current_wall_time:.2f}s exceeded limit {current_wall_limit:.2f}s."
                    error_flag.set()
                    break

                time.sleep(0.05)
            # --- End Monitoring Loop ---

            debug_print(f"Exited monitoring loop PID {pid}. Status: {result['status']}, ExitedNormally: {process_exited_normally}")

            # --- Termination & Cleanup ---
            # ... [终止进程（如果需要）和等待 I/O 线程 - 无变化] ...
            if error_flag.is_set() and pid != -1:
                 debug_print(f"Error flag set, ensuring PID {pid} is killed (if still running).")
                 kill_reason = result.get("status", "Error Flag")
                 JarTester._kill_process_tree(pid, reason=f"JarTester({kill_reason})")

            debug_print(f"Waiting for I/O threads to finish for PID {pid}")
            thread_join_timeout = 2.0
            threads_to_join = [t for t in [stdout_reader_thread, stderr_reader_thread] if t and t.is_alive()]
            start_join_time = time.monotonic()
            while threads_to_join and time.monotonic() - start_join_time < thread_join_timeout:
                for t in threads_to_join[:]: t.join(timeout=0.1);
                if not t.is_alive(): threads_to_join.remove(t)
            for t in threads_to_join:
                 if t.is_alive(): print(f"WARNING: Thread {t.name} for PID {pid} did not exit cleanly.", file=sys.stderr)
            debug_print(f"Finished waiting for I/O threads for PID {pid}")

            # ... [更新最终时间和检查退出代码 - 无变化] ...
            result["wall_time"] = time.monotonic() - start_wall_time
            try:
                 if psutil.pid_exists(pid):
                      final_cpu_times = psutil.Process(pid).cpu_times()
                      result["cpu_time"] = final_cpu_times.user + final_cpu_times.system
            except (psutil.NoSuchProcess, psutil.AccessDenied): pass

            final_status_determined = result["status"] not in ["RUNNING", "PENDING"]
            if process_exited_normally and not final_status_determined:
                # ... [获取退出代码逻辑] ...
                debug_print(f"Process {pid} exited normally. Getting exit code.")
                exit_code = None
                try:
                    exit_code = process.poll()
                    if exit_code is None and psutil.pid_exists(pid):
                         debug_print(f"Process {pid} poll() is None, using wait(0.5).")
                         exit_code = process.wait(timeout=0.5)
                    debug_print(f"Process {pid} final exit code: {exit_code}")
                    if exit_code is not None and exit_code != 0:
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Exited with non-zero code {exit_code}."
                        final_status_determined = True
                    elif exit_code == 0 and result["status"] == "PENDING":
                         result["status"] = "RUNNING"
                except subprocess.TimeoutExpired:
                    # ... [处理获取退出代码超时] ...
                    print(f"WARNING: Timeout waiting for exit code for PID {pid} that exited normally.", file=sys.stderr)
                    JarTester._kill_process_tree(pid, reason="ExitCodeWaitTimeout")
                    if not final_status_determined:
                        result["status"] = "CRASHED"
                        result["error_details"] = "Process did not report exit code."
                        final_status_determined = True
                except Exception as e_final:
                    # ... [处理获取退出代码的其他错误] ...
                    print(f"WARNING: Error getting final state/exit code for PID {pid}: {e_final}", file=sys.stderr)
                    if not final_status_determined:
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Error getting final process state: {e_final}"
                        final_status_determined = True

        except Exception as e:
            # ... [外部异常处理 - 无变化] ...
            print(f"FATAL: Error during execution setup/monitoring of {jar_basename} (PID {pid}): {e}", file=sys.stderr)
            debug_print(f"Outer exception handler: Unexpected exception for PID {pid}", exc_info=True)
            if result["status"] not in ["CRASHED", "TLE", "CTLE", "INTERRUPTED", "CHECKER_ERROR"]:
                result["status"] = "CRASHED"
                result["error_details"] = f"Tester execution error: {e}"
            error_flag.set()
            if pid != -1:
                 debug_print(f"Outer exception: Ensuring PID {pid} is killed.")
                 JarTester._kill_process_tree(pid, reason="OuterException")

        finally:
            # --- Final Cleanup in Finally Block ---
            # 1. Ensure Process is Gone
            if pid != -1:
                try:
                    if psutil.pid_exists(pid):
                        debug_print(f"Final cleanup: Ensuring PID {pid} is terminated (if not already).")
                        final_kill_reason = result.get("status", "Final Cleanup")
                        JarTester._kill_process_tree(pid, reason=f"JarTesterFinally({final_kill_reason})")
                except Exception as e_kill_final:
                    print(f"ERROR: Exception during final kill check for PID {pid}: {e_kill_final}", file=sys.stderr)

            # 2. <<< Unregister PID >>>
            if pid != -1: JarTester._unregister_pid(pid)

            # 3. Drain Output Queues
            # ... [排空队列逻辑 - 无变化] ...
            debug_print(f"Draining output queues for PID {pid}")
            stdout_lines_list = []
            stderr_lines_list = []
            try:
                while True: stdout_lines_list.append(stdout_queue.get(block=False, timeout=0.01))
            except queue.Empty: pass
            try:
                while True: stderr_lines_list.append(stderr_queue.get(block=False, timeout=0.01))
            except queue.Empty: pass
            stdout_content = "".join(stdout_lines_list)
            stderr_lines = stderr_lines_list
            result["stderr"] = stderr_lines
            debug_print(f"Drained queues for PID {pid}. stdout lines: {len(stdout_lines_list)}, stderr lines: {len(stderr_lines)}")

            # 4. Save Stdout Content to File (if needed)
            # ... [保存 stdout 到文件逻辑 - 无变化，只是保存，不删除] ...
            save_stdout = stdout_content or result["status"] not in ["PENDING", "RUNNING", "CORRECT"]
            if save_stdout and result["stdout_log_path"]:
                try:
                    os.makedirs(TMP_DIR, exist_ok=True)
                    with open(result["stdout_log_path"], 'w', encoding='utf-8', errors='replace') as f_out:
                        f_out.write(stdout_content) # Write the joined content
                    debug_print(f"JAR stdout content saved to {result['stdout_log_path']}")
                except Exception as e_write_stdout:
                    print(f"WARNING: Failed to write stdout log content for {jar_basename} to {result['stdout_log_path']}: {e_write_stdout}", file=sys.stderr)
            elif result["stdout_log_path"]:
                 debug_print(f"No stdout content saved for {jar_basename} (status OK or empty). Path was {result['stdout_log_path']}")


            # 5. Final check join for I/O threads (daemon should handle this)
            # ... [线程 join 检查 - 无变化] ...
            debug_print(f"Final check join for threads of PID {pid}")
            if stdout_reader_thread and stdout_reader_thread.is_alive(): stdout_reader_thread.join(timeout=0.1)
            if stderr_reader_thread and stderr_reader_thread.is_alive(): stderr_reader_thread.join(timeout=0.1)
            debug_print(f"Exiting finally block for PID {pid}")
            # --- End Final Cleanup in Finally Block ---


        # --- Run Checker ---
        run_checker = (result["status"] == "RUNNING")
        if run_checker:
            debug_print(f"Running checker for {jar_basename} (PID {pid}).")
            # <<< 注意：temp_output_file 在 try 外定义了 >>>
            checker_status = "CHECKER_PENDING"
            checker_details = ""
            try:
                # Use NamedTemporaryFile for checker's input
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt", encoding='utf-8', dir=TMP_DIR, errors='replace') as tf:
                    tf.write(stdout_content)
                    temp_output_file = tf.name
                    result["checker_temp_output_path"] = temp_output_file # <<< 存储路径以供返回

                debug_print(f"Checker using input(gen) '{input_data_path}' and output(jar) '{temp_output_file}' with Tmax={current_wall_limit:.2f}s")
                checker_timeout = 45.0
                checker_proc = subprocess.run(
                    [sys.executable, JarTester._checker_script_path, input_data_path, temp_output_file, "--tmax", str(current_wall_limit)],
                    capture_output=True, text=True, timeout=checker_timeout, check=False, encoding='utf-8', errors='replace'
                )
                debug_print(f"Checker for {jar_basename} finished with code {checker_proc.returncode}")

                # ... [处理检查器结果 - 无变化] ...
                if checker_proc.stderr:
                    result["stderr"].extend(["--- Checker stderr ---"] + checker_proc.stderr.strip().splitlines())

                if checker_proc.returncode != 0:
                    # ... [检查器错误处理] ...
                    checker_status = "CHECKER_ERROR"
                    checker_details = f"Checker exited with code {checker_proc.returncode}."
                    details_stdout = checker_proc.stdout.strip()
                    details_stderr = checker_proc.stderr.strip()
                    if details_stdout: checker_details += f" stdout: {details_stdout[:200]}"
                    if details_stderr: checker_details += f" stderr: {details_stderr[:200]}"
                    debug_print(f"Checker error for {jar_basename}: Exit code {checker_proc.returncode}")
                else:
                    # Parse checker output
                    try:
                        # ... [解析检查器输出逻辑 - 无变化] ...
                        checker_output = checker_proc.stdout
                        if isinstance(checker_output, bytes): checker_output = checker_output.decode('utf-8', errors='replace')
                        if not checker_output.strip(): raise ValueError("Checker produced empty stdout output.")

                        checker_data = ast.literal_eval(checker_output)

                        if checker_data.get("result") == "Success":
                            checker_status = "CORRECT"
                            # ... [提取性能指标] ...
                            performance_metrics = checker_data.get("performance")
                            if performance_metrics:
                                t_final_val = performance_metrics.get("T_final")
                                wt_val = performance_metrics.get("WT_weighted_time")
                                w_val = performance_metrics.get("W_energy")
                                if all(isinstance(v, (int, float)) for v in [t_final_val, wt_val, w_val]):
                                    result["t_final"] = float(t_final_val)
                                    result["wt"] = float(wt_val)
                                    result["w"] = float(w_val)
                                else:
                                    # ... [指标验证失败处理] ...
                                    checker_status = "CHECKER_ERROR"; checker_details = "Correct verdict but failed to extract/validate metrics."
                                    result["t_final"] = result["wt"] = result["w"] = None
                            else:
                                # ... [缺少 performance 处理] ...
                                checker_status = "CHECKER_ERROR"; checker_details = "Correct verdict but 'performance' section missing."
                                result["t_final"] = result["wt"] = result["w"] = None
                        elif checker_data.get("result") == "Fail":
                            # ... [处理 Fail 结果] ...
                            checker_status = "INCORRECT"
                            errors_list = checker_data.get("errors", ["Checker reported 'Fail'"])
                            checker_details = "; ".join(errors_list)[:500]
                            result["t_final"] = result["wt"] = result["w"] = None
                        else:
                            # ... [处理未知 result 值] ...
                            checker_status = "CHECKER_ERROR"
                            res_val = checker_data.get("result", "None")
                            checker_details = f"Checker returned unexpected result value: '{res_val}'"
                            result["t_final"] = result["wt"] = result["w"] = None
                    except (ValueError, SyntaxError, TypeError) as e_parse:
                        # ... [检查器输出解析错误处理] ...
                        print(f"ERROR: Failed to parse checker output for {jar_basename}: {e_parse}", file=sys.stderr)
                        debug_print(f"Checker output parsing error for {jar_basename}. Output:\n{checker_proc.stdout[:1000]}\n")
                        checker_status = "CHECKER_ERROR"
                        checker_details = f"Failed to parse checker output: {e_parse}"
                        result["t_final"] = result["wt"] = result["w"] = None
            except subprocess.TimeoutExpired:
                # ... [检查器超时处理] ...
                print(f"ERROR: Checker timed out for {jar_basename}.", file=sys.stderr)
                checker_status = "CHECKER_ERROR"
                checker_details = f"Checker process timed out after {checker_timeout}s."
            except Exception as e_check:
                # ... [其他检查器异常处理] ...
                print(f"ERROR: Exception running checker for {jar_basename}: {e_check}", file=sys.stderr)
                debug_print(f"Checker exception for {jar_basename}", exc_info=True)
                checker_status = "CHECKER_ERROR"
                checker_details = f"Exception during checker execution: {e_check}"
            finally:
                # <<< 移除: 不再在这里删除检查器临时文件 >>>
                # if temp_output_file and os.path.exists(temp_output_file):
                #     JarTester._robust_remove_file(temp_output_file, log_prefix="Checker Tmp Cleanup:")
                pass # Deletion moved to main thread

            # Update result based on checker outcome
            result["status"] = checker_status
            if checker_status != "CORRECT":
                result["error_details"] = checker_details
                result["t_final"] = result["wt"] = result["w"] = None

        else: # Checker not run
             debug_print(f"Skipping checker for {jar_basename} due to final JAR status: {result['status']}")


        # Ensure score is 0 if final status is not CORRECT
        if result["status"] != "CORRECT":
            result["final_score"] = 0.0
            result["t_final"] = result["wt"] = result["w"] = None


        debug_print(f"Finished run for JAR: {jar_basename}. Final Status: {result['status']}")
        return result

    @staticmethod
    def _generate_data(gen_args_list, round_num, seed_value):
        # ... (no changes needed here) ...
        input_filename = f"input_{seed_value}_{round_num}.txt"
        input_filepath = os.path.abspath(os.path.join(TMP_DIR, input_filename))
        os.makedirs(os.path.dirname(input_filepath), exist_ok=True) # Ensure TMP_DIR exists

        requests_data = None
        gen_stdout = None
        gen_success = False

        try:
            command = [sys.executable, JarTester._gen_script_path] + gen_args_list
            debug_print(f"Running generator: {' '.join(command)}")

            gen_timeout = 20.0 # Maybe increase if generators can be slow?
            gen_proc = subprocess.run(
                command, capture_output=True, text=True, timeout=gen_timeout, check=True, encoding='utf-8', errors='replace'
            )
            gen_stdout = gen_proc.stdout
            gen_success = True # Mark success if run completes without error

            try:
                with open(input_filepath, 'w', encoding='utf-8', errors='replace') as f: f.write(gen_stdout)
                debug_print(f"Generator output written to tmp file: {input_filepath}")
            except Exception as e_write:
                print(f"ERROR: Failed to write generator output to {input_filepath}: {e_write}", file=sys.stderr)
                # Consider generation failed if we can't save the input
                return None, input_filepath # Return path for potential cleanup

            # --- Request Parsing ---
            raw_requests = gen_stdout.strip().splitlines()
            requests_data = []
            pattern = re.compile(r"^\s*\[\s*(\d+\.?\d*)\s*\]\s*(.*)")
            parse_errors = 0
            for line_num, line in enumerate(raw_requests):
                match = pattern.match(line)
                if match:
                    try:
                        timestamp_req = float(match.group(1))
                        req_part = match.group(2).strip()
                        if req_part: requests_data.append((timestamp_req, req_part))
                    except ValueError:
                        parse_errors += 1
                elif line.strip(): # Ignore empty lines but count non-matching lines as errors
                    parse_errors += 1

            # Handle n=0 case specifically
            is_n_zero = any(arg == '-n' and gen_args_list[i+1] == '0' for i, arg in enumerate(gen_args_list[:-1]))
            if not raw_requests and not requests_data and is_n_zero:
                 debug_print("Generator produced no output (expected for n=0). Returning empty list.")
                 return [], input_filepath

            if parse_errors > 0:
                 print(f"WARNING: Generator round {round_num}: {parse_errors} lines had parsing errors in {input_filepath}.", file=sys.stderr)
                 if not requests_data and raw_requests: # Had output but couldn't parse any
                      print(f"ERROR: Generator round {round_num}: NO valid requests parsed from non-empty output.", file=sys.stderr)
                      return None, input_filepath # Treat as failure if no requests parsed

            requests_data.sort(key=lambda x: x[0])
            debug_print(f"Successfully parsed {len(requests_data)} requests.")
            return requests_data, input_filepath

        except subprocess.TimeoutExpired:
            print(f"ERROR: Generator script timed out after {gen_timeout}s (Round {round_num}).", file=sys.stderr)
            # Try save output if available, return None for requests
            if gen_stdout is not None and input_filepath:
                 try:
                     with open(input_filepath, 'w', encoding='utf-8', errors='replace') as f: f.write(gen_stdout)
                 except Exception: pass
            return None, input_filepath # Return path even on failure
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Generator script failed with code {e.returncode} (Round {round_num}).", file=sys.stderr)
            # ... (log command, stdout, stderr - same) ...
            stdout_log = (e.stdout or '<empty>')[:1000]
            stderr_log = (e.stderr or '<empty>')[:1000]
            print(f"--- Generator Command ---\n{' '.join(e.cmd)}", file=sys.stderr)
            print(f"--- Generator Stdout (truncated) ---\n{stdout_log}\n--- Generator Stderr (truncated) ---\n{stderr_log}", file=sys.stderr)
            if e.stdout is not None and input_filepath:
                 try:
                     with open(input_filepath, 'w', encoding='utf-8', errors='replace') as f: f.write(e.stdout)
                     print(f"INFO: Saved generator's failed stdout to {input_filepath}", file=sys.stderr)
                 except Exception: pass
            return None, input_filepath
        except Exception as e:
            print(f"ERROR: Unexpected error during data generation (Round {round_num}): {e}", file=sys.stderr)
            debug_print("Exception in _generate_data", exc_info=True)
            if gen_stdout is not None and input_filepath:
                 try:
                     with open(input_filepath, 'w', encoding='utf-8', errors='replace') as f: f.write(gen_stdout)
                 except Exception: pass
            return None, input_filepath


    @staticmethod
    def _calculate_scores(current_results):
        # ... (no changes needed here) ...
        correct_results = [
            r for r in current_results
            if r and r.get("status") == "CORRECT" # Add check for None result
            and r.get("t_final") is not None and r.get("wt") is not None and r.get("w") is not None
        ]
        debug_print(f"Calculating scores based on {len(correct_results)} CORRECT runs with metrics.")

        # Initialize all scores to 0 first
        for r in current_results:
             if r: r["final_score"] = 0.0 # Check if r is not None

        if not correct_results:
            debug_print("No CORRECT results with metrics found for score calculation.")
            return # All scores remain 0

        # Use try-except for numpy operations
        try:
            t_finals = np.array([r["t_final"] for r in correct_results])
            wts = np.array([r["wt"] for r in correct_results])
            ws = np.array([r["w"] for r in correct_results])
        except Exception as e_np_create:
             print(f"ERROR: Failed to create numpy arrays for scoring: {e_np_create}", file=sys.stderr)
             return # Cannot proceed with scoring

        metrics = {'t_final': t_finals, 'wt': wts, 'w': ws}
        normalized_scores = {}

        for name, values in metrics.items():
            if len(values) == 0: continue
            try:
                x_min = np.min(values) if len(values) > 0 else 0.0
                x_max = np.max(values) if len(values) > 0 else 0.0
                x_avg = np.mean(values) if len(values) > 0 else 0.0
            except Exception as e_np_stats:
                 print(f"ERROR: NumPy error calculating stats for {name}: {e_np_stats}. Skipping scoring for this metric.", file=sys.stderr)
                 continue

            debug_print(f"Metric {name}: min={x_min:.3f}, max={x_max:.3f}, avg={x_avg:.3f}")
            # Handle division by zero or near-zero range
            denominator = x_max - x_min
            is_denominator_zero = abs(denominator) < 1e-9

            if not is_denominator_zero:
                # Apply P-value adjustment only if range is significant
                base_min = PERF_P_VALUE * x_avg + (1 - PERF_P_VALUE) * x_min
                base_max = PERF_P_VALUE * x_avg + (1 - PERF_P_VALUE) * x_max
                # Ensure base_min <= base_max after adjustment
                if base_min > base_max:
                    base_min, base_max = base_max, base_min # Swap if order reversed
            else:
                 # If range is zero, use the single value as base min/max
                 base_min = x_min
                 base_max = x_max
                 debug_print(f"Metric {name}: All values effectively the same.")


            debug_print(f"Metric {name}: base_min={base_min:.3f}, base_max={base_max:.3f}")

            # Recalculate denominator for normalization after p-value adjustment
            norm_denominator = base_max - base_min
            is_norm_denominator_zero = abs(norm_denominator) < 1e-9

            normalized = {}
            for r in correct_results:
                x = r.get(name) # Use .get() for safety
                if x is None: continue # Skip if metric missing

                r_x = 0.0 # Default normalized score (lower is better)
                if is_norm_denominator_zero:
                    # If range is zero, score is 0 (best possible relative score)
                    r_x = 0.0
                else:
                    # Clamp and normalize
                    if x <= base_min + 1e-9: r_x = 0.0
                    elif x >= base_max - 1e-9: r_x = 1.0
                    else: r_x = (x - base_min) / norm_denominator

                normalized[r["jar_file"]] = r_x
                debug_print(f"  NormScore {name} for {r['jar_file']} (val={x:.3f}): {r_x:.4f}")

            normalized_scores[name.upper()] = normalized

        # Calculate final scores
        for r in correct_results:
            jar_name = r.get("jar_file")
            if not jar_name: continue
            try:
                r_t = normalized_scores.get('T_FINAL', {}).get(jar_name, 0.0)
                r_wt = normalized_scores.get('WT', {}).get(jar_name, 0.0)
                r_w = normalized_scores.get('W', {}).get(jar_name, 0.0)

                r_prime_t = 1.0 - r_t
                r_prime_wt = 1.0 - r_wt
                r_prime_w = 1.0 - r_w

                s = 15 * (0.3 * r_prime_t + 0.3 * r_prime_wt + 0.4 * r_prime_w)
                r["final_score"] = max(0.0, s)
                debug_print(f"Score for {jar_name}: T={r_t:.3f}, WT={r_wt:.3f}, W={r_w:.3f} -> Final={r['final_score']:.3f}")
            except Exception as e_score:
                 print(f"ERROR: Unexpected error calculating final score for {jar_name}: {e_score}. Setting score to 0.", file=sys.stderr)
                 r["final_score"] = 0.0


    @staticmethod
    def _display_and_log_results(round_num, results, round_preset_cmd, input_data_path, round_wall_limit):
        # ... (no changes needed here) ...
        log_lines = []
        has_errors_for_log = False

        # Filter out None results potentially caused by forced shutdown?
        valid_results = [r for r in results if r is not None]
        if not valid_results:
            log_lines.append(f"\n--- Test Round {round_num}: No valid results to display (Possibly interrupted) ---")
            # Log writing logic remains the same
            if JarTester._log_file_path:
                try:
                    with JarTester._log_lock:
                        with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                            f.write("\n".join(log_lines) + "\n\n")
                except Exception as e:
                    with JarTester._console_lock:
                        print(f"ERROR: Failed to write results to log file {JarTester._log_file_path} for round {round_num}: {e}", file=sys.stderr)
            return # Nothing to display or log further


        valid_results.sort(key=lambda x: (-x.get("final_score", 0.0), x.get("wall_time", float('inf')) if x.get("status") == "CORRECT" else float('inf')))

        round_header = f"\n--- Test Round {round_num} Results (Preset: {round_preset_cmd} | Wall Limit: {round_wall_limit:.1f}s) ---"
        header = f"{'JAR':<25} | {'Status':<12} | {'Score':<7} | {'T_final':<10} | {'WT':<10} | {'W':<10} | {'CPU(s)':<8} | {'Wall(s)':<8} | Details"
        separator = "-" * len(header)

        log_lines.append(round_header.replace(" Results ", " Summary "))
        # Check if input_data_path exists before logging
        input_log_path = input_data_path if input_data_path and os.path.exists(input_data_path) else '<Not Available or Cleaned>'
        log_lines.append(f"Input Data File: {input_log_path}")
        log_lines.append(header)
        log_lines.append(separator)

        error_log_header_needed = True
        result_lines_for_console = []

        for r in valid_results:
            jar_name = r.get("jar_file", "UnknownJAR")
            status = r.get("status", "UNKNOWN")
            score = r.get("final_score", 0.0)
            score_str = f"{score:.3f}" if status == "CORRECT" else "---"
            tfin_str = f"{r.get('t_final'):.3f}" if r.get('t_final') is not None else "---"
            wt_str = f"{r.get('wt'):.3f}" if r.get('wt') is not None else "---"
            w_str = f"{r.get('w'):.3f}" if r.get('w') is not None else "---"
            cpu_str = f"{r.get('cpu_time', 0.0):.2f}"
            wall_str = f"{r.get('wall_time', 0.0):.2f}"
            details = r.get("error_details", "")[:100] # Truncate details for console

            console_line = f"{jar_name:<25} | {status:<12} | {score_str:<7} | {tfin_str:<10} | {wt_str:<10} | {w_str:<10} | {cpu_str:<8} | {wall_str:<8} | {details}"
            result_lines_for_console.append(console_line)

            log_line = f"{jar_name:<25} | {status:<12} | {score_str:<7} | {tfin_str:<10} | {wt_str:<10} | {w_str:<10} | {cpu_str:<8} | {wall_str:<8} | {r.get('error_details', '')}"
            log_lines.append(log_line)

            # --- Error Logging Section ---
            # Log INTERRUPTED status as well if desired, or keep as is
            if status not in ["CORRECT", "PENDING", "RUNNING"]: # Includes CRASHED, TLE, CTLE, INTERRUPTED, CHECKER_ERROR etc.
                has_errors_for_log = True
                if error_log_header_needed:
                    log_lines.append(f"\n--- Test Round {round_num} Error/Interrupt Details ---")
                    log_lines.append(f"Input Data File for this Round: {input_log_path}") # Use checked path
                    error_log_header_needed = False

                log_lines.append(f"\n--- Details for: {jar_name} (Status: {status}) ---")
                log_lines.append(f"  Preset Used: {round_preset_cmd}")
                log_lines.append(f"  Wall Limit Used: {round_wall_limit:.1f}s")
                log_lines.append(f"  Details: {r.get('error_details', '')}") # Log full details

                # Log path to input data file again
                log_lines.append("  --- Input Data File ---")
                log_lines.append(f"    Path: {input_log_path}") # Use checked path
                log_lines.append("  --- End Input Data File ---")

                # Log path to stdout file (check existence)
                stdout_log = r.get("stdout_log_path")
                stdout_log_path = stdout_log if stdout_log and os.path.exists(stdout_log) else '<Not Saved or Cleaned>'
                log_lines.append("  --- Stdout Log File ---")
                log_lines.append(f"    Path: {stdout_log_path}")
                log_lines.append("  --- End Stdout Log File ---")

                # Log stderr content
                log_lines.append("  --- Stderr ---")
                stderr = r.get("stderr", [])
                if stderr:
                    MAX_OUTPUT_LOG_LINES = 100
                    for i, err_line in enumerate(stderr):
                         if i < MAX_OUTPUT_LOG_LINES: log_lines.append(f"    {err_line.strip()}")
                         elif i == MAX_OUTPUT_LOG_LINES: log_lines.append(f"    ... (stderr truncated)"); break
                    if len(stderr) <= MAX_OUTPUT_LOG_LINES: log_lines.append("    <End of Stderr>")
                else:
                     log_lines.append("    <No stderr captured>")
                log_lines.append("  --- End Stderr ---")
                log_lines.append("-" * 20)
            # --- End Error Logging Section ---

        log_lines.append(separator)

        # --- Print block to console atomically ---
        with JarTester._console_lock:
            print(round_header)
            print(header)
            print(separator)
            for line in result_lines_for_console:
                print(line)
            print(separator)
            print(f"--- End of Round {round_num} ---")

        # --- Log writing with lock ---
        if JarTester._log_file_path:
            try:
                with JarTester._log_lock:
                    with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                        f.write("\n".join(log_lines) + "\n\n")
                debug_print(f"Results and errors for round {round_num} written to log.")
            except Exception as e:
                with JarTester._console_lock:
                    print(f"ERROR: Failed to write results to log file {JarTester._log_file_path} for round {round_num}: {e}", file=sys.stderr)


    @staticmethod
    def _update_history(results):
        """Update the historical results after a round. Uses History Lock."""
        with JarTester._history_lock:
            valid_results = [r for r in results if r is not None] # Filter None
            for r in valid_results:
                # Skip interrupted runs from history calculation
                if r.get("status") == "INTERRUPTED":
                    debug_print(f"Skipping history update for {r.get('jar_file')} (INTERRUPTED)")
                    continue
                jar_name = r.get("jar_file", "UnknownJAR")
                if jar_name == "UnknownJAR": continue

                history = JarTester._all_results_history[jar_name]
                history['total_runs'] += 1
                score_to_add = 0.0
                if r.get("status") == "CORRECT":
                    history['correct_runs'] += 1
                    score_to_add = float(r.get("final_score", 0.0) or 0.0)

                history['scores'].append(score_to_add)
                # debug_print(f"History update for {jar_name}: Total={history['total_runs']}, Correct={history['correct_runs']}, Added Score={score_to_add:.3f}")


    @staticmethod
    def _print_summary():
        # ... (no changes needed here) ...
        summary_lines = []

        if JarTester._interrupted:
            summary_lines.append("\n--- Testing Interrupted ---")
        else:
            summary_lines.append("\n--- Testing Finished ---")

        with JarTester._round_counter_lock:
            total_rounds_assigned = JarTester._round_counter
        summary_lines.append(f"Total test rounds initiated: {total_rounds_assigned}")

        # Get history snapshot under lock
        with JarTester._history_lock:
            # Create a deep copy if history contains mutable objects (like lists), though here it's mostly numbers
            history_snapshot = {k: v.copy() for k, v in JarTester._all_results_history.items()}

        if not history_snapshot:
            summary_lines.append("No completed, non-interrupted test results recorded in history.")
            return "\n".join(summary_lines)

        summary_lines.append("\n--- Average Performance Summary (Based on Completed, Non-Interrupted Rounds) ---")
        summary_data = []
        history_items = list(history_snapshot.items())

        for jar_name, data in history_items:
            total_runs = data.get('total_runs', 0)
            correct_runs = data.get('correct_runs', 0)
            scores = data.get('scores', [])
            valid_scores = [s for s in scores if isinstance(s, (int, float)) and np.isfinite(s)]
            avg_score = np.mean(valid_scores) if valid_scores else 0.0
            correct_rate = (correct_runs / total_runs * 100) if total_runs > 0 else 0.0
            avg_score = avg_score if np.isfinite(avg_score) else 0.0
            summary_data.append({
                "jar": jar_name, "avg_score": avg_score, "correct_rate": correct_rate,
                "correct": correct_runs, "total": total_runs
            })

        summary_data.sort(key=lambda x: (-x["avg_score"], -x["correct_rate"], x["jar"]))

        header = f"{'JAR':<25} | {'Avg Score':<10} | {'Correct %':<10} | {'Passed/Total':<15}"
        summary_lines.append(header)
        summary_lines.append("-" * len(header))

        for item in summary_data:
             # Only display if total runs > 0 (meaning at least one non-interrupted run finished)
             if item['total'] > 0:
                 passed_total_str = f"{item['correct']}/{item['total']}"
                 line = f"{item['jar']:<25} | {item['avg_score']:<10.3f} | {item['correct_rate']:<10.1f}% | {passed_total_str:<15}"
                 summary_lines.append(line)

        summary_lines.append("-" * len(header))
        return "\n".join(summary_lines)


    @staticmethod
    def _signal_handler(sig, frame):
        """Handles Ctrl+C: sets flag, kills running processes."""
        if not JarTester._interrupted:
            print("\nCtrl+C detected. Stopping new rounds and killing running JARs...", file=sys.stderr)
            JarTester._interrupted = True

            # <<< KILL RUNNING PROCESSES >>>
            pids_to_kill = []
            with JarTester._pid_lock:
                pids_to_kill = list(JarTester._running_pids.keys()) # Get snapshot
                debug_print(f"Signal Handler: PIDs targeted for killing: {pids_to_kill}")

            if not pids_to_kill:
                 debug_print("Signal Handler: No PIDs registered to kill.")
                 print("Signal Handler: No active JARs found to kill.", file=sys.stderr)
                 return # Nothing to kill

            killed_count = 0
            # Use a temporary thread pool just for killing, so handler returns quickly
            kill_workers = min(len(pids_to_kill), (os.cpu_count() or 1) * 2)
            if kill_workers > 0:
                debug_print(f"Signal Handler: Using {kill_workers} workers to kill {len(pids_to_kill)} processes.")
                # We create a short-lived pool here; alternatively, manage a global killer pool
                with concurrent.futures.ThreadPoolExecutor(max_workers=kill_workers, thread_name_prefix='Killer') as killer_pool:
                    futures = [killer_pool.submit(JarTester._kill_process_tree, pid, reason="Ctrl+C") for pid in pids_to_kill]
                    try:
                        # Wait briefly for kills to initiate/complete
                        done, not_done = concurrent.futures.wait(futures, timeout=3.0)
                        killed_count = len(done)
                        if not_done:
                            print(f"WARNING: Signal Handler: Killing {len(not_done)} processes timed out after 3s.", file=sys.stderr)
                            # Optionally, attempt to cancel remaining futures? `shutdown` might handle this.
                    except Exception as e_kill_wait:
                        print(f"ERROR: Signal Handler: Exception while waiting for kill tasks: {e_kill_wait}", file=sys.stderr)
                debug_print(f"Signal Handler: Kill attempt finished for {killed_count}/{len(pids_to_kill)} processes.")
            else: # Handle case len=0 or cpu_count=0? Should not happen if pids_to_kill > 0.
                debug_print(f"Signal Handler: Killing {len(pids_to_kill)} process(es) sequentially.")
                for pid in pids_to_kill:
                     try:
                         JarTester._kill_process_tree(pid, reason="Ctrl+C")
                         killed_count += 1
                     except Exception as e_seq_kill:
                          print(f"ERROR: Signal Handler: Exception killing PID {pid} sequentially: {e_seq_kill}", file=sys.stderr)
                debug_print(f"Signal Handler: Sequential kill attempt finished for {killed_count}/{len(pids_to_kill)} processes.")

            print("Signal Handler: Kill process initiated. Waiting for rounds to clean up...", file=sys.stderr)


    @staticmethod
    def _initialize_presets():
        # ... (no changes needed here) ...
        JarTester._gen_arg_presets = []
        JarTester._raw_preset_commands = []
        required_time_arg_present = True

        if not JarTester._loaded_preset_commands:
            print("ERROR: No generator presets were loaded. Cannot initialize.", file=sys.stderr)
            return False

        for cmd_index, cmd_str in enumerate(JarTester._loaded_preset_commands):
            parts = cmd_str.split()
            if not parts or parts[0] != "gen.py":
                # print(f"WARNING: Skipping invalid preset format (must start with 'gen.py'): {cmd_str}", file=sys.stderr)
                continue # Silently skip non-gen presets

            args_dict = {}
            has_time_arg = False
            i = 1
            while i < len(parts):
                arg = parts[i]
                # Basic check: Must start with '-'
                if not arg.startswith('-'):
                    # Allow non-argument parts ONLY if the previous part was not an arg expecting a value
                    # Example flags that don't take values: --hce
                    flags_without_values = {'--hce', '--some-other-flag'} # Add known flags here
                    is_value_expected = i > 1 and parts[i-1].startswith('-') and parts[i-1] not in flags_without_values
                    if is_value_expected:
                         print(f"WARNING: Argument '{parts[i-1]}' in preset '{cmd_str}' seems to be missing a value before '{arg}'. Skipping '{arg}'.", file=sys.stderr)
                    # else: # Treat unexpected non-arg as error or warning
                    #     print(f"WARNING: Skipping invalid non-argument part in preset '{cmd_str}': {arg}", file=sys.stderr)
                    i += 1
                    continue

                if arg in ['-t', '--max-time']: has_time_arg = True

                # Check if next part is a value (doesn't start with '-')
                if i + 1 < len(parts) and not parts[i+1].startswith('-'):
                    value = parts[i+1]
                    try: value = int(value)
                    except ValueError:
                        try: value = float(value)
                        except ValueError: pass # Keep as string
                    args_dict[arg] = value
                    i += 2
                else: # Handle flags (like --hce)
                    args_dict[arg] = True
                    i += 1

            if not has_time_arg:
                # print(f"WARNING: Preset '{cmd_str}' lacks '-t'/'--max-time'. Using default ({DEFAULT_GEN_MAX_TIME}s) for wall limit calc.", file=sys.stderr)
                required_time_arg_present = False # Mark that at least one is missing

            preset_label = " ".join(parts[1:])
            JarTester._gen_arg_presets.append(args_dict)
            JarTester._raw_preset_commands.append(preset_label)

        num_presets = len(JarTester._gen_arg_presets)
        print(f"INFO: Initialized/Parsed {num_presets} valid generator presets from the loaded list.")
        if num_presets == 0:
            print("ERROR: No valid generator presets were parsed. Cannot continue.", file=sys.stderr)
            return False
        if not required_time_arg_present:
             print(f"INFO: Some presets lack time args ('-t'/'--max-time'). Default ({DEFAULT_GEN_MAX_TIME}s) used for wall limit.")
        return True


    @staticmethod
    def _preset_dict_to_arg_list(preset_dict):
        # ... (no changes needed here) ...
        args_list = []
        for key, value in preset_dict.items():
            args_list.append(key)
            if value is not True: # Check for boolean flags (value is True)
                args_list.append(str(value)) # Ensure value is string for subprocess
        return args_list


    @staticmethod
    def _check_interrupt_with_wait(log_prefix, timeout=0.5, interval=0.02):
        """
        Checks the global interrupt flag repeatedly for a short duration.
        Returns True if interrupted during the check, False otherwise.
        """
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            if JarTester._interrupted:
                debug_print(f"{log_prefix} Interrupt detected during wait check.")
                return True # Interrupted
            time.sleep(interval)
        return False # Not interrupted within timeout

    @staticmethod
    def _run_one_round(round_num):
        """Executes all steps for a single test round, returning results and file paths."""
        thread_name = threading.current_thread().name
        if not JarTester._interrupted:
            with JarTester._console_lock:
                print(f"INFO [{thread_name}]: Starting Test Round {round_num}")
        debug_print(f"Round {round_num}: Starting execution.")

        # --- Initialize variables for this round ---
        round_results = None # Final package to return
        results_this_round = [] # List of dicts from _run_single_jar
        selected_preset_cmd = "<Not Selected>"
        input_data_path = None
        error_log_filepath = None
        round_wall_time_limit = MIN_WALL_TIME_LIMIT
        current_seed = -1
        full_preset_cmd = "<Not Set>"
        # <<< 新增：收集文件路径 >>>
        files_generated_this_round = {
            "input": None,
            "outputs": [],
            "checker_temps": [],
            "error_log": None
        }

        try:
            # ... [获取 log_prefix_base - 无变化] ...
            try: current_thread_name = threading.current_thread().name
            except Exception: current_thread_name = f"UnknownThread_R{round_num}"
            log_prefix_base = f"[{current_thread_name}] Round {round_num}"

            # 1. Initial Interrupt Check
            if JarTester._interrupted:
                debug_print(f"{log_prefix_base}: Skipping at start due to global interrupt.")
                return None

            # 2. Select Preset & Setup
            # ... [选择预设和设置参数 - 无变化] ...
            if not JarTester._gen_arg_presets:
                 with JarTester._console_lock: print(f"ERROR [{thread_name}]: No generator presets available for round {round_num}.", file=sys.stderr)
                 return None
            preset_index = random.randrange(len(JarTester._gen_arg_presets))
            selected_preset_dict = JarTester._gen_arg_presets[preset_index]
            selected_preset_cmd = JarTester._raw_preset_commands[preset_index]
            gen_args_list = JarTester._preset_dict_to_arg_list(selected_preset_dict)
            current_seed = int(time.time() * 1000) + round_num + random.randint(0, 10000)
            gen_args_list.extend(["--seed", str(current_seed)])
            full_preset_cmd = f"{selected_preset_cmd} --seed {current_seed}"
            debug_print(f"{log_prefix_base}: Using Generator Preset: {full_preset_cmd}")
            gen_max_time_str = selected_preset_dict.get('-t') or selected_preset_dict.get('--max-time')
            round_gen_max_time = DEFAULT_GEN_MAX_TIME
            if gen_max_time_str:
                try: round_gen_max_time = float(gen_max_time_str)
                except ValueError: debug_print(f"{log_prefix_base}: Warning - Could not parse gen time '{gen_max_time_str}'. Using default {DEFAULT_GEN_MAX_TIME}s.")
            round_wall_time_limit = max(MIN_WALL_TIME_LIMIT, round_gen_max_time * 2.0 + 15.0)
            debug_print(f"{log_prefix_base}: Setting WALL_TIME_LIMIT: {round_wall_time_limit:.2f}s")

            # 3. Generate Data
            if JarTester._interrupted: return None
            debug_print(f"{log_prefix_base}: Generating data...")
            requests_data, input_data_path = JarTester._generate_data(gen_args_list, round_num, current_seed)
            files_generated_this_round["input"] = input_data_path # <<< 存储输入文件路径

            if requests_data is None:
                with JarTester._console_lock: print(f"ERROR [{thread_name}] Round {round_num}: Failed to generate data. Skipping.", file=sys.stderr)
                # Log failure
                if JarTester._log_file_path:
                     try:
                         with JarTester._log_lock:
                             with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                                 f.write(f"\n--- Round {round_num}: Generation FAILED ---\nPreset: {full_preset_cmd}\nFile: {input_data_path or '<Not Set>'}\n")
                     except Exception as e_log_gen_fail:
                         with JarTester._console_lock: print(f"ERROR [{thread_name}] Round {round_num}: Also failed to log generation failure: {e_log_gen_fail}", file=sys.stderr)
                # <<< 返回包含已知文件路径的结果，以便主线程清理 >>>
                return {
                    "round_num": round_num,
                    "results": [], # No results
                    "preset_cmd": full_preset_cmd,
                    "input_path": input_data_path, # Pass original path attempt
                    "wall_limit": round_wall_time_limit,
                    "status": "GENERATION_FAILED", # Add a status
                    "files_generated": files_generated_this_round # Return paths collected so far
                }

            debug_print(f"{log_prefix_base}: Generated {len(requests_data)} requests to '{os.path.basename(input_data_path) if input_data_path else 'N/A'}'")

            # 4. Run JARs Concurrently
            if JarTester._interrupted: return None
            if not JarTester._jar_files:
                 with JarTester._console_lock: print(f"ERROR [{thread_name}] Round {round_num}: No JAR files found.", file=sys.stderr)
                 # <<< 返回包含已知文件路径的结果 >>>
                 return {
                    "round_num": round_num, "results": [], "preset_cmd": full_preset_cmd,
                    "input_path": input_data_path, "wall_limit": round_wall_time_limit,
                    "status": "NO_JARS",
                    "files_generated": files_generated_this_round
                 }

            max_workers_per_round = min(len(JarTester._jar_files), (os.cpu_count() or 4) * 2 + 1)
            debug_print(f"{log_prefix_base}: Running {len(JarTester._jar_files)} JARs (max {max_workers_per_round} workers)...")

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers_per_round, thread_name_prefix=f'JarExec_R{round_num}') as executor:
                if JarTester._interrupted: return None
                future_to_jar = {
                    executor.submit(JarTester._run_single_jar, jar_file, input_data_path, round_wall_time_limit, round_num): jar_file
                    for jar_file in JarTester._jar_files
                }
                debug_print(f"{log_prefix_base}: Submitted {len(future_to_jar)} JAR tasks.")

                for future in concurrent.futures.as_completed(future_to_jar):
                    jar_file = future_to_jar[future]
                    jar_basename = os.path.basename(jar_file)
                    try:
                        result = future.result() # result from _run_single_jar
                        if result:
                            results_this_round.append(result)
                            # <<< 收集文件路径 >>>
                            if result.get("stdout_log_path"):
                                files_generated_this_round["outputs"].append(result["stdout_log_path"])
                            if result.get("checker_temp_output_path"):
                                files_generated_this_round["checker_temps"].append(result["checker_temp_output_path"])
                        else:
                             # ... [处理 future 返回 None 的情况] ...
                             with JarTester._console_lock: print(f"WARNING [{thread_name}] Round {round_num}: Future for {jar_basename} returned None unexpectedly.", file=sys.stderr)
                             # Add placeholder result if needed, but no files to track
                    except concurrent.futures.CancelledError:
                         # ... [处理取消的 future] ...
                         with JarTester._console_lock: print(f"WARNING [{thread_name}] Round {round_num}: JAR run {jar_basename} cancelled.", file=sys.stderr)
                         # Add placeholder result if needed
                    except Exception as exc:
                        # ... [处理 future 异常] ...
                        with JarTester._console_lock: print(f'\nERROR [{thread_name}] Round {round_num}: JAR {jar_basename} thread raised exception: {exc}', file=sys.stderr)
                        debug_print(f"{log_prefix_base}: Exception from future for {jar_basename}", exc_info=True)
                        # Add placeholder result if needed

                    if JarTester._interrupted:
                        debug_print(f"{log_prefix_base}: Interrupt detected while processing JAR results. Breaking as_completed loop.")
                        # Note: Even if we break, results_this_round and files_generated_this_round
                        # will contain info collected so far, which is correct.
                        break

            debug_print(f"{log_prefix_base}: Finished processing JAR futures. Results collected: {len(results_this_round)}")

            # --- Post-processing and Result Preparation ---
            # Don't skip post-processing on interrupt, we need to package results/files
            # 5. Calculate Scores (safe even if interrupted)
            debug_print(f"{log_prefix_base}: Calculating scores...")
            JarTester._calculate_scores(results_this_round)

            # 6. Create Error Log (if needed, safe even if interrupted)
            failed_jars_in_round = [r for r in results_this_round if r and r.get("status") not in ["CORRECT", "PENDING", "RUNNING", "INTERRUPTED", "CANCELLED"]]
            if failed_jars_in_round:
                error_log_filename = f"errors_{round_num}_{current_seed}.log"
                error_log_filepath = os.path.abspath(os.path.join(LOG_DIR, error_log_filename))
                files_generated_this_round["error_log"] = error_log_filepath # <<< 存储错误日志路径
                debug_print(f"{log_prefix_base}: Failures detected. Logging errors to: {error_log_filepath}")
                try:
                    # ... [写入错误日志文件逻辑 - 无变化] ...
                    os.makedirs(LOG_DIR, exist_ok=True)
                    with open(error_log_filepath, "w", encoding="utf-8", errors='replace') as f_err:
                        f_err.write(f"--- Error Log for Test Round {round_num} ---\n")
                        # ... (写入头部信息) ...
                        f_err.write(f"Seed: {current_seed}\n")
                        f_err.write(f"Preset Command Used: {full_preset_cmd}\n")
                        input_log_path = '<Not Available>'
                        if input_data_path: input_log_path = input_data_path if os.path.exists(input_data_path) else f'{input_data_path} <Not Found>'
                        f_err.write(f"Input Data File Path: {input_log_path}\n")
                        f_err.write(f"Wall Time Limit Applied: {round_wall_time_limit:.1f}s\n")
                        f_err.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f_err.write("-" * 40 + "\n\n")
                        for r in failed_jars_in_round:
                             # ... (写入每个失败JAR的详细信息) ...
                             jar_name = r.get("jar_file", "UnknownJAR"); status = r.get("status", "UNKNOWN")
                             f_err.write(f"--- Failing JAR: {jar_name} ---\n")
                             f_err.write(f"Status: {status}\n"); f_err.write(f"Error Details: {r.get('error_details', '')}\n")
                             stdout_log = r.get("stdout_log_path"); stdout_log_path = '<Not Saved>'
                             if stdout_log: stdout_log_path = stdout_log if os.path.exists(stdout_log) else f'{stdout_log} <Not Found or Cleaned>'
                             f_err.write(f"Stdout Log File Path: {stdout_log_path}\n"); f_err.write("--- Stderr Content ---\n")
                             stderr = r.get("stderr", []); MAX_ERR_LOG_LINES = 200; stderr_lines_written = 0
                             if stderr:
                                 for i, err_line in enumerate(stderr):
                                     if isinstance(err_line, str):
                                         if stderr_lines_written < MAX_ERR_LOG_LINES: f_err.write(f"  {err_line.strip()}\n"); stderr_lines_written += 1
                                         elif stderr_lines_written == MAX_ERR_LOG_LINES: f_err.write(f"  ... (stderr truncated)\n"); stderr_lines_written += 1; break
                                 if stderr_lines_written <= MAX_ERR_LOG_LINES: f_err.write("  <End of Stderr>\n")
                             else: f_err.write("  <No stderr captured>\n")
                             f_err.write("--- End Stderr ---\n\n")
                    # Don't print success message if interrupted
                    if not JarTester._interrupted:
                         with JarTester._console_lock: print(f"INFO [{thread_name}] Round {round_num}: Errors occurred. Details saved to {error_log_filepath}")
                except Exception as e_err_log:
                    with JarTester._console_lock: print(f"ERROR [{thread_name}] Round {round_num}: Failed to write error log {error_log_filepath}: {e_err_log}", file=sys.stderr)
                    files_generated_this_round["error_log"] = None # Failed to create/write

            # 7. Prepare final results package
            # Determine final status (consider interrupt)
            round_status = "COMPLETED"
            if JarTester._interrupted:
                round_status = "INTERRUPTED"
            elif not results_this_round and files_generated_this_round.get("input"): # Generation ok, but no jar results (e.g., submit failed?)
                round_status = "JAR_EXEC_FAILED"

            # Use the most recently known input path for reporting
            final_input_path_report = files_generated_this_round.get("input")

            round_results = {
                "round_num": round_num,
                "results": results_this_round,
                "preset_cmd": full_preset_cmd,
                "input_path": final_input_path_report, # Report path even if cleaned
                "wall_limit": round_wall_time_limit,
                "status": round_status, # Add overall round status
                "files_generated": files_generated_this_round # <<< 返回收集到的文件路径
            }
            if not JarTester._interrupted:
                 with JarTester._console_lock: print(f"INFO [{thread_name}]: Finished Test Round {round_num} ({selected_preset_cmd})")
            else:
                 debug_print(f"{log_prefix_base}: Round finished processing after interrupt.")

            return round_results

        except Exception as e_round:
            # ... [处理轮次中的致命错误 - 无变化，但确保返回文件路径] ...
            with JarTester._console_lock: print(f"\nFATAL ERROR in worker thread for Round {round_num}: {e_round}", file=sys.stderr)
            debug_print(f"Fatal error in _run_one_round {round_num}", exc_info=True)
            # Log error
            if JarTester._log_file_path:
                 try:
                     with JarTester._log_lock:
                         with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                             f.write(f"\n\n!!! FATAL WORKER ERROR (Round {round_num}) !!!\nThread: {thread_name}\n")
                             f.write(f"Preset: {full_preset_cmd}\nInput Path: {input_data_path or '<N/A>'}\n")
                             f.write(f"Error: {e_round}\n{traceback.format_exc()}\n")
                 except Exception as e_log_fatal_worker:
                     with JarTester._console_lock: print(f"ERROR [{thread_name}] Round {round_num}: Also failed to log fatal worker error: {e_log_fatal_worker}", file=sys.stderr)
            # <<< 返回包含已知文件路径的错误结果 >>>
            return {
                 "round_num": round_num, "results": results_this_round, "preset_cmd": full_preset_cmd,
                 "input_path": input_data_path, "wall_limit": round_wall_time_limit,
                 "status": "FATAL_WORKER_ERROR",
                 "error_details": f"Fatal worker error: {e_round}",
                 "files_generated": files_generated_this_round # Return paths collected so far
            }

        finally:
            # --- Final Cleanup Logic ---
            # <<< 移除所有文件删除逻辑 >>>
            # <<< 保留非文件清理相关的调试日志 >>>
            log_prefix_base = f"[{threading.current_thread().name}] Round {round_num}" # Recalculate if needed
            debug_print(f"{log_prefix_base}: Exiting finally block. File cleanup delegated to main thread.")
            # No more _robust_remove_file calls here.

    # ==========================================================================
    # test() Method - Main Entry Point
    # ==========================================================================
    @staticmethod
    def _cleanup_round_files(round_num, files_dict, results_list, is_interrupted):
        """Cleans up temporary files for a completed round based on status and config."""
        log_prefix = f"[MainCleanup] Round {round_num}:"
        debug_print(f"{log_prefix} Starting cleanup. Interrupted={is_interrupted}, Config_Cleanup={CLEANUP_SUCCESSFUL_ROUNDS}")

        input_path = files_dict.get("input")
        output_paths = files_dict.get("outputs", [])
        checker_temp_paths = files_dict.get("checker_temps", [])
        error_log_path = files_dict.get("error_log")

        files_to_remove = []
        files_to_keep_reason = []

        # 1. Determine files to remove/keep
        if is_interrupted:
            debug_print(f"{log_prefix} Interrupt detected, cleaning all files.")
            if input_path: files_to_remove.append(("Input (Interrupted)", input_path))
            if error_log_path: files_to_remove.append(("Error Log (Interrupted)", error_log_path))
            for p in output_paths: files_to_remove.append(("Output (Interrupted)", p))
            for p in checker_temp_paths: files_to_remove.append(("Checker Temp (Interrupted)", p))
        else:
            # Always remove checker temps in normal operation
            for p in checker_temp_paths: files_to_remove.append(("Checker Temp", p))

            if CLEANUP_SUCCESSFUL_ROUNDS:
                all_passed = False
                if results_list: # Check if we have results to evaluate
                    all_passed = all(r and r.get("status") == "CORRECT" for r in results_list)
                else: # No results (e.g., generation failed but reported files) - treat as failure for cleanup
                     debug_print(f"{log_prefix} No JAR results found, treating as failed round for cleanup.")

                if all_passed:
                    debug_print(f"{log_prefix} All JARs passed, cleaning input and outputs.")
                    if input_path: files_to_remove.append(("Input (All Correct)", input_path))
                    # Error log shouldn't exist if all passed, but check anyway
                    if error_log_path: files_to_remove.append(("Error Log (All Correct?)", error_log_path))
                    for p in output_paths: files_to_remove.append(("Output (All Correct)", p))
                else:
                    debug_print(f"{log_prefix} Not all JARs passed (or no results), selective cleanup.")
                    if input_path: files_to_keep_reason.append(f"Input: {os.path.basename(input_path)}")
                    if error_log_path: files_to_keep_reason.append(f"Error Log: {os.path.basename(error_log_path)}")

                    # Keep failed outputs, remove correct outputs
                    # Create a mapping from output path back to result status for easier lookup
                    path_to_status = {r.get("stdout_log_path"): r.get("status", "UNKNOWN")
                                      for r in results_list if r and r.get("stdout_log_path")}

                    for p in output_paths:
                        status = path_to_status.get(p, "UNKNOWN") # Find status for this path
                        jar_name = os.path.basename(p).split('_')[1] if len(os.path.basename(p).split('_')) > 1 else '?' # Approximate JAR name

                        if status == "CORRECT":
                             files_to_remove.append((f"Output (Correct - {jar_name})", p))
                        else:
                             files_to_keep_reason.append(f"Output ({status} - {jar_name}): {os.path.basename(p)}")
            else:
                # Cleanup disabled, only remove checker temps (already added)
                debug_print(f"{log_prefix} Cleanup disabled by config. Keeping Input, Outputs, ErrorLog.")
                if input_path: files_to_keep_reason.append(f"Input (Cleanup Disabled): {os.path.basename(input_path)}")
                if error_log_path: files_to_keep_reason.append(f"Error Log (Cleanup Disabled): {os.path.basename(error_log_path)}")
                for p in output_paths:
                     jar_name = os.path.basename(p).split('_')[1] if len(os.path.basename(p).split('_')) > 1 else '?'
                     files_to_keep_reason.append(f"Output ({jar_name}) (Cleanup Disabled): {os.path.basename(p)}")


        # 2. Execute cleanup
        cleaned_count = 0
        failed_count = 0
        if files_to_remove:
            debug_print(f"{log_prefix} Attempting to remove {len(files_to_remove)} file(s)...")
            for reason, file_path in files_to_remove:
                 if file_path and isinstance(file_path, str): # Basic validation
                     # Check existence before attempting removal for cleaner logs
                     if pathlib.Path(file_path).exists():
                          debug_print(f"{log_prefix} Removing [{reason}]: {os.path.basename(file_path)}")
                          if JarTester._robust_remove_file(file_path, log_prefix=f"{log_prefix}"):
                              cleaned_count += 1
                          else:
                              failed_count += 1
                     else:
                         debug_print(f"{log_prefix} Skipping non-existent file [{reason}]: {os.path.basename(file_path)}")
                 else:
                     debug_print(f"{log_prefix} Skipping invalid file path entry: {file_path}")
        else:
            debug_print(f"{log_prefix} No files marked for removal.")

        # 3. Log kept files
        if files_to_keep_reason:
            debug_print(f"{log_prefix} Keeping {len(files_to_keep_reason)} file(s):")
            for reason in files_to_keep_reason:
                debug_print(f"  - {reason}")
        else:
            debug_print(f"{log_prefix} No files specifically marked to keep.")

        if failed_count > 0:
             with JarTester._console_lock:
                 print(f"WARNING {log_prefix}: Failed to remove {failed_count} file(s). Check logs for details.", file=sys.stderr)


    @staticmethod
    def test():
        """Main testing entry point, runs multiple rounds in parallel."""
        # ... [配置加载和初始化 - 无变化] ...
        global ENABLE_DETAILED_DEBUG, LOG_DIR, TMP_DIR, CLEANUP_SUCCESSFUL_ROUNDS, DEFAULT_PARALLEL_ROUNDS, MIN_WALL_TIME_LIMIT, CPU_TIME_LIMIT, PERF_P_VALUE

        start_time_main = time.monotonic()
        config = None
        test_config = {}

        with JarTester._pid_lock:
            JarTester._running_pids.clear()
            debug_print("Cleared running PID tracker at start.")

        try:
            config_path = 'config.yml'
            print(f"INFO: Loading configuration from {config_path}...")
            # ... [加载 YAML 配置] ...
            if not os.path.exists(config_path): print(f"ERROR: Configuration file '{config_path}' not found.", file=sys.stderr); return
            try:
                with open(config_path, 'r', encoding='utf-8') as f: config = yaml.safe_load(f)
                if not config: print(f"ERROR: Configuration file '{config_path}' is empty or invalid.", file=sys.stderr); return

                hw_n = config.get('hw'); jar_base_dir = config.get('jar_base_dir')
                if hw_n is None or not isinstance(hw_n, int): print(f"ERROR: 'hw' value missing or invalid in {config_path}.", file=sys.stderr); return
                if not jar_base_dir or not isinstance(jar_base_dir, str): print(f"ERROR: 'jar_base_dir' value missing or invalid in {config_path}.", file=sys.stderr); return

                LOG_DIR = config.get('logs_dir', LOG_DIR); TMP_DIR = config.get('tmp_dir', TMP_DIR)
                test_config = config.get('test', {})

                ENABLE_DETAILED_DEBUG = bool(test_config.get('debug', ENABLE_DETAILED_DEBUG))
                CLEANUP_SUCCESSFUL_ROUNDS = bool(test_config.get('cleanup', CLEANUP_SUCCESSFUL_ROUNDS))
                parallel_rounds_config = test_config.get('parallel', DEFAULT_PARALLEL_ROUNDS)
                hce_filter_enabled = test_config.get('hce', False)
                MIN_WALL_TIME_LIMIT = float(test_config.get('min_wall_time', MIN_WALL_TIME_LIMIT))
                CPU_TIME_LIMIT = float(test_config.get('cpu_time_limit', CPU_TIME_LIMIT))
                PERF_P_VALUE = float(test_config.get('perf_p_value', PERF_P_VALUE))

                if not isinstance(parallel_rounds_config, int) or parallel_rounds_config < 1:
                    print(f"WARNING: 'test.parallel' value invalid ({parallel_rounds_config}). Using default: {DEFAULT_PARALLEL_ROUNDS}.", file=sys.stderr)
                    parallel_rounds_config = DEFAULT_PARALLEL_ROUNDS

            except yaml.YAMLError as e_yaml: print(f"ERROR: Failed to parse config file '{config_path}': {e_yaml}", file=sys.stderr); return
            except Exception as e_conf: print(f"ERROR: Unexpected error processing config file '{config_path}': {e_conf}", file=sys.stderr); return

            if ENABLE_DETAILED_DEBUG: debug_print("Detailed debugging enabled via config.")
            if CLEANUP_SUCCESSFUL_ROUNDS: debug_print("Cleanup mode for successful runs enabled via config.")

            m = hw_n // 4 + 1; hw_n_str = os.path.join(f"unit_{m}", f"hw_{hw_n}")
            JarTester._jar_dir = jar_base_dir
            JarTester._gen_script_path = os.path.abspath(os.path.join(hw_n_str, "gen.py"))
            JarTester._checker_script_path = os.path.abspath(os.path.join(hw_n_str, "checker.py"))

            # ... [加载生成器预设 - 无变化] ...
            JarTester._loaded_preset_commands = []
            gen_dir = os.path.dirname(JarTester._gen_script_path)
            presets_yaml_path = os.path.abspath(os.path.join(gen_dir, "gen_presets.yml"))
            try:
                print(f"INFO: Loading generator presets from {presets_yaml_path}...")
                if not os.path.exists(presets_yaml_path): print(f"ERROR: Generator presets file '{presets_yaml_path}' not found.", file=sys.stderr); return
                with open(presets_yaml_path, 'r', encoding='utf-8') as f_presets: loaded_presets = yaml.safe_load(f_presets)
                if not isinstance(loaded_presets, list) or not all(isinstance(item, str) for item in loaded_presets): print(f"ERROR: Content of '{presets_yaml_path}' is not a valid list of strings.", file=sys.stderr); return
                JarTester._loaded_preset_commands = loaded_presets
                print(f"INFO: Successfully loaded {len(JarTester._loaded_preset_commands)} generator presets.")
            except yaml.YAMLError as e_yaml: print(f"ERROR: Failed to parse presets file '{presets_yaml_path}': {e_yaml}", file=sys.stderr); return
            except Exception as e_load: print(f"ERROR: Unexpected error loading presets file '{presets_yaml_path}': {e_load}", file=sys.stderr); return


            # ... [重置状态变量，创建目录和日志文件 - 无变化] ...
            JarTester._interrupted = False; JarTester._round_counter = 0; JarTester._all_results_history.clear()
            os.makedirs(LOG_DIR, exist_ok=True); os.makedirs(TMP_DIR, exist_ok=True)
            local_time = time.localtime(); formatted_time = time.strftime("%Y-%m-%d-%H-%M-%S", local_time)
            JarTester._log_file_path = os.path.abspath(os.path.join(LOG_DIR, f"{formatted_time}_elevator_run.log"))
            print(f"INFO: Homework target: {hw_n_str}"); print(f"INFO: JAR directory: {JarTester._jar_dir}")
            print(f"INFO: Logging to {JarTester._log_file_path}"); print(f"INFO: Temp directory: {os.path.abspath(TMP_DIR)}")
            print(f"INFO: Running up to {parallel_rounds_config} rounds concurrently.")
            print(f"INFO: CPU Limit: {CPU_TIME_LIMIT}s, Min Wall Limit: {MIN_WALL_TIME_LIMIT}s, Cleanup: {CLEANUP_SUCCESSFUL_ROUNDS}")

            # ... [应用 HCE 过滤器 - 无变化] ...
            if hce_filter_enabled:
                print("INFO: HCE filter enabled. Filtering presets...")
                original_count = len(JarTester._loaded_preset_commands)
                JarTester._loaded_preset_commands = [cmd for cmd in JarTester._loaded_preset_commands if "--hce" in cmd]
                filtered_count = len(JarTester._loaded_preset_commands)
                print(f"INFO: Filtered presets: {original_count} -> {filtered_count}")
                if filtered_count == 0: print("ERROR: HCE filtering resulted in zero presets. Cannot continue.", file=sys.stderr); return


            # ... [最终检查和设置信号处理器 - 无变化] ...
            if not os.path.exists(JarTester._gen_script_path): print(f"ERROR: Generator script not found: {JarTester._gen_script_path}", file=sys.stderr); return
            if not os.path.exists(JarTester._checker_script_path): print(f"ERROR: Checker script not found: {JarTester._checker_script_path}", file=sys.stderr); return
            if not JarTester._find_jar_files(): print("ERROR: No JAR files found or accessible. Aborting.", file=sys.stderr); return
            if not JarTester._initialize_presets(): print("ERROR: Failed to initialize presets. Aborting.", file=sys.stderr); return

            signal.signal(signal.SIGINT, JarTester._signal_handler)
            print(f"\nPress Ctrl+C to stop testing and kill running JARs.")
            print("\n" + "="*40)
            if not ENABLE_DETAILED_DEBUG:
                try: input("Setup complete. Press Enter to begin testing...")
                except EOFError: print("Non-interactive mode detected. Starting tests immediately.")
            print("="*40 + "\n")


            # --- Main Parallel Round Execution Loop ---
            active_futures = set()
            processed_round_count = 0
            # <<< 新增：跟踪每个 future 对应的轮次编号和返回的文件信息 >>>
            future_to_round_info = {}

            with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_rounds_config, thread_name_prefix='RoundRunner') as round_executor:
                while not JarTester._interrupted:
                    # Submit new rounds
                    while len(active_futures) < parallel_rounds_config and not JarTester._interrupted:
                        round_num = JarTester._get_next_round_number()
                        debug_print(f"MainLoop: Submitting round {round_num}")
                        future = round_executor.submit(JarTester._run_one_round, round_num)
                        active_futures.add(future)
                        future_to_round_info[future] = {"round_num": round_num, "files": None, "results": None} # 预留位置

                    if JarTester._interrupted:
                         debug_print("MainLoop: Interrupt detected, stopping submission.")
                         break

                    # Wait for completed rounds
                    debug_print(f"MainLoop: Waiting for completed rounds (Active: {len(active_futures)})...")
                    try:
                        done, active_futures = concurrent.futures.wait(
                             active_futures,
                             return_when=concurrent.futures.FIRST_COMPLETED
                        )
                    except KeyboardInterrupt: # Should be handled by signal handler
                         debug_print("MainLoop: KeyboardInterrupt caught in wait (should have been handled).")
                         if not JarTester._interrupted: JarTester._signal_handler(signal.SIGINT, None)
                         break

                    debug_print(f"MainLoop: {len(done)} round(s) completed.")

                    # Process completed rounds
                    for future in done:
                        processed_round_count += 1
                        round_info = future_to_round_info.pop(future, {"round_num": "<unknown>", "files": {}, "results": []}) # Get info and remove
                        r_num = round_info["round_num"]

                        try:
                            round_result_package = future.result() # Get package (might be None or partial)

                            if round_result_package:
                                # Store file info and results for cleanup/logging
                                round_info["files"] = round_result_package.get("files_generated", {})
                                round_info["results"] = round_result_package.get("results", [])
                                r_num = round_result_package.get("round_num", r_num) # Update round num if available

                                # Process results *before* cleanup if not interrupted
                                if not JarTester._interrupted:
                                    debug_print(f"MainLoop: Processing results for round {r_num}...")
                                    JarTester._display_and_log_results(
                                        r_num,
                                        round_info["results"],
                                        round_result_package["preset_cmd"],
                                        round_result_package["input_path"], # Use path from package for logging
                                        round_result_package["wall_limit"]
                                    )
                                    JarTester._update_history(round_info["results"])
                                else:
                                     debug_print(f"MainLoop: Round {r_num} completed after interrupt. Skipping result display/history.")
                            else:
                                # Future returned None (likely worker fatal error before return)
                                debug_print(f"MainLoop: Round {r_num} future returned None. Cleanup will use stored info if any.")
                                # We don't have file info from the package, rely on what might be in round_info (likely empty)

                            # <<< Perform cleanup using collected/stored info >>>
                            JarTester._cleanup_round_files(r_num, round_info["files"] or {}, round_info["results"] or [], JarTester._interrupted)

                        except Exception as exc:
                            print(f'\nERROR: Main loop caught exception processing future for round {r_num}: {exc}', file=sys.stderr)
                            debug_print(f"Exception processing round future {r_num}", exc_info=True)
                            # <<< Attempt cleanup even on error >>>
                            JarTester._cleanup_round_files(r_num, round_info["files"] or {}, round_info["results"] or [], True) # Assume interrupt on error

                    # Optional brief sleep
                    # time.sleep(0.01)

                # --- End of main loop ---
                print("\nMainLoop: Exited main execution loop.")
                if JarTester._interrupted:
                    print("MainLoop: Interrupt received. Waiting for remaining round threads to finish...")
                    # Wait for remaining futures to complete (they should exit quickly)
                    if active_futures:
                        debug_print(f"MainLoop: Waiting for {len(active_futures)} active round threads to finish.")
                        # Use a timeout to avoid hanging indefinitely if a thread is stuck
                        done_after_interrupt, not_done_after_interrupt = concurrent.futures.wait(active_futures, timeout=10.0)
                        debug_print(f"MainLoop: After wait: {len(done_after_interrupt)} finished, {len(not_done_after_interrupt)} timed out.")

                        # Process futures that completed *after* the interrupt
                        for future in done_after_interrupt:
                            round_info = future_to_round_info.pop(future, {"round_num": "<unknown_late>", "files": {}, "results": []})
                            r_num = round_info["round_num"]
                            debug_print(f"MainLoop: Processing late-finishing round {r_num} after interrupt.")
                            try:
                                round_result_package = future.result() # Try to get results/files
                                if round_result_package:
                                    round_info["files"] = round_result_package.get("files_generated", {})
                                    round_info["results"] = round_result_package.get("results", [])
                            except Exception as exc:
                                print(f"WARNING: Main loop: Error getting result from late future {r_num}: {exc}", file=sys.stderr)
                            # <<< Force cleanup for late-finishing rounds >>>
                            JarTester._cleanup_round_files(r_num, round_info["files"] or {}, round_info["results"] or [], True)

                        # Handle timed out futures (might be stuck)
                        if not_done_after_interrupt:
                             print(f"WARNING: {len(not_done_after_interrupt)} round threads did not finish within timeout after interrupt.", file=sys.stderr)
                             # We don't know their files reliably, cannot clean them easily here.
                             # The PID killer in signal handler is the main safety net.
                             for future in not_done_after_interrupt:
                                 round_info = future_to_round_info.pop(future, None)
                                 if round_info: print(f"  - Timed out round: {round_info.get('round_num', '?')}", file=sys.stderr)

                    else:
                        debug_print("MainLoop: No active round threads remaining after interrupt.")
                else:
                    print("MainLoop: Finished normally.")

        except Exception as e:
            # ... [主线程致命错误处理 - 无变化] ...
            print(f"\nFATAL ERROR in main testing thread: {e}", file=sys.stderr)
            debug_print("Fatal error in main test execution", exc_info=True)
            if JarTester._log_file_path:
                 try:
                     with JarTester._log_lock:
                         with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                             f.write(f"\n\n!!! FATAL MAIN TESTER ERROR !!!\n{time.strftime('%Y-%m-%d %H:%M:%S')}\nError: {e}\n")
                             traceback.print_exc(file=f)
                 except Exception as e_log_fatal: print(f"ERROR: Also failed to log fatal main error: {e_log_fatal}", file=sys.stderr)
            print("Attempting final PID cleanup due to main error...", file=sys.stderr)
            lingering_pids = [];
            with JarTester._pid_lock: lingering_pids = list(JarTester._running_pids.keys())
            for pid in lingering_pids:
                print(f"Killing lingering PID {pid}..."); JarTester._kill_process_tree(pid, reason="MainThreadError")

        finally:
            # --- Final Summary ---
            # ... [打印和记录最终摘要 - 无变化] ...
            print("\nCalculating final summary...")
            summary = JarTester._print_summary()
            print(summary)
            if JarTester._log_file_path:
                try:
                     with JarTester._log_lock:
                        with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                            f.write("\n\n" + "="*20 + " FINAL SUMMARY " + "="*20 + "\n"); f.write(summary + "\n")
                            f.write("="* (40 + len(" FINAL SUMMARY ")) + "\n")
                        debug_print("Final summary also written to log file.")
                except Exception as e_log_summary: print(f"ERROR: Failed to write final summary to log file {JarTester._log_file_path}: {e_log_summary}", file=sys.stderr)

            # ... [可选的 TMP 清理提示 - 无变化] ...
            # try:
            #     if os.path.exists(TMP_DIR): print(f"\nTemporary files are in: {os.path.abspath(TMP_DIR)}")
            # except Exception as e_clean: print(f"WARNING: Error during final temp dir check: {e_clean}", file=sys.stderr)

            end_time_main = time.monotonic()
            print(f"\nTotal execution time: {end_time_main - start_time_main:.2f} seconds.")
            # --- Ensure PIDs are cleared at the very end ---
            # ... [最终 PID 清理检查 - 无变化] ...
            with JarTester._pid_lock:
                if JarTester._running_pids:
                     debug_print(f"Final state check: PIDs {list(JarTester._running_pids.keys())} were still registered. Clearing now.")
                     JarTester._running_pids.clear()
                else: debug_print("Final state check: PID tracker is empty.")

# ==========================================================================
# Script Execution Block
# ==========================================================================