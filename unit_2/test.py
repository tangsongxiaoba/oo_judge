# --- START OF FILE test.py ---

# tester.py
import ast
import os
import sys
import subprocess
import time
import signal
import threading
import queue
import tempfile
import psutil
import re
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

    @staticmethod
    def _get_next_round_number():
        with JarTester._round_counter_lock:
            JarTester._round_counter += 1
            return JarTester._round_counter

    # --- Helper: Clear Screen ---
    @staticmethod
    def _clear_screen():
        """Clears the terminal screen."""
        if ENABLE_DETAILED_DEBUG: return
        # Only clear if it's likely the main thread, avoid clearing from workers
        if threading.current_thread() is threading.main_thread():
             os.system('cls' if os.name == 'nt' else 'clear')

    # --- (Keep _find_jar_files, _kill_process_tree as they are) ---
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
                # Use print directly as this is initialization info
                print(f"INFO: Found {len(JarTester._jar_files)} JAR files in '{JarTester._jar_dir}'")
            except FileNotFoundError:
                print(f"ERROR: JAR directory not found: '{JarTester._jar_dir}'", file=sys.stderr)
                return False
            except Exception as e:
                print(f"ERROR: Failed to list JAR files in '{JarTester._jar_dir}': {e}", file=sys.stderr)
                return False
        return len(JarTester._jar_files) > 0

    @staticmethod
    def _kill_process_tree(pid):
        """Recursively terminate a process and its children."""
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            debug_print(f"PID {pid} has children: {[c.pid for c in children]}")
            for child in children:
                try:
                    debug_print(f"Terminating child PID {child.pid}")
                    child.terminate()
                except psutil.NoSuchProcess: pass
            debug_print(f"Terminating parent PID {pid}")
            parent.terminate()
            gone, alive = psutil.wait_procs(children + [parent], timeout=1.0)
            debug_print(f"After terminate: Gone={[(p.pid if hasattr(p,'pid') else '?') for p in gone]}, Alive={[(p.pid if hasattr(p,'pid') else '?') for p in alive]}")
            for p in alive:
                try:
                    debug_print(f"Killing remaining process PID {p.pid}")
                    p.kill()
                except psutil.NoSuchProcess: pass
        except psutil.NoSuchProcess:
            debug_print(f"Process PID {pid} already gone before kill attempt.")
        except Exception as e:
            # Use print for potential errors during critical cleanup
            print(f"ERROR: Exception during process termination for PID {pid}: {e}", file=sys.stderr)

    @staticmethod
    def _output_reader(pipe, output_queue, stream_name, pid, error_flag):
        debug_print(f"Output reader ({stream_name}) started for PID {pid}")
        try:
            for line_num, line in enumerate(iter(pipe.readline, '')):
                if error_flag.is_set() or JarTester._interrupted:
                     debug_print(f"Output reader ({stream_name}) stopping early for PID {pid} (error or interrupt)")
                     break
                output_queue.put(line)
            debug_print(f"Output reader ({stream_name}) finished iter loop for PID {pid}")
        except ValueError:
            if not error_flag.is_set() and not JarTester._interrupted and pipe and not pipe.closed:
                 debug_print(f"Output reader ({stream_name}) caught ValueError for PID {pid} (pipe not closed)")
            # Ignore ValueError if pipe is closed, common scenario
        except Exception as e:
            # Only log error if it wasn't due to interrupt/error flag
            if not error_flag.is_set() and not JarTester._interrupted:
                print(f"ERROR: Output reader ({stream_name}) thread crashed for PID {pid}: {e}", file=sys.stderr)
                debug_print(f"Output reader ({stream_name}) thread exception for PID {pid}", exc_info=True)
                error_flag.set() # Signal error if unexpected exception
        finally:
            try:
                debug_print(f"Output reader ({stream_name}) closing pipe for PID {pid}")
                pipe.close()
            except Exception: pass
            debug_print(f"Output reader ({stream_name}) thread exiting for PID {pid}")

    # --- (Keep _run_single_jar as it is, it handles one JAR execution) ---
    @staticmethod
    def _run_single_jar(jar_path, input_data_path, current_wall_limit, round_num):
        """Executes a single JAR, monitors it, saves stdout, and runs the checker."""
        jar_basename = os.path.basename(jar_path)
        debug_print(f"Starting run for JAR: {jar_basename} with Wall Limit: {current_wall_limit:.2f}s")
        start_wall_time = time.monotonic()
        process = None
        pid = -1
        ps_proc = None
        result = {
            "jar_file": jar_basename, "cpu_time": 0.0, "wall_time": 0.0,
            "status": "PENDING", "error_details": "",
            "stdout_log_path": None, # Path to saved stdout file
            "stderr": [], # Keep stderr in memory for log
            "t_final": None, "wt": None, "w": None, "final_score": 0.0,
            "input_data_path": input_data_path # Store the input path with the result
        }
        stdout_reader_thread = None
        stderr_reader_thread = None
        stdout_queue = queue.Queue()
        stderr_queue = queue.Queue()
        error_flag = threading.Event() # Local error flag for this JAR run

        try:
            # --- (Process Launch and Monitoring - unchanged) ---
            debug_print(f"Launching JAR: {jar_basename}")
            process = subprocess.Popen(
                ['java', '-jar', jar_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', bufsize=1
            )
            pid = process.pid
            debug_print(f"JAR {jar_basename} launched with PID {pid}")
            result["status"] = "RUNNING"
            try:
                ps_proc = psutil.Process(pid)
                debug_print(f"Attached psutil to PID {pid}")
            except psutil.NoSuchProcess as e_attach:
                print(f"ERROR: Process {pid} ({jar_basename}) disappeared immediately after launch.", file=sys.stderr)
                debug_print(f"psutil attach failed for PID {pid}", exc_info=True)
                result["status"] = "CRASHED"
                result["error_details"] = f"Process disappeared immediately: {e_attach}"
                error_flag.set()
                # No need to raise here, let the finally block handle cleanup
                # But return early from the try block
                return result # Return the failed result


            debug_print(f"Starting output reader threads for PID {pid}")
            stdout_reader_thread = threading.Thread(target=JarTester._output_reader, args=(process.stdout, stdout_queue, "stdout", pid, error_flag), daemon=True)
            stderr_reader_thread = threading.Thread(target=JarTester._output_reader, args=(process.stderr, stderr_queue, "stderr", pid, error_flag), daemon=True)
            stdout_reader_thread.start()
            stderr_reader_thread.start()

            input_content = None
            try:
                debug_print(f"Reading all input data from {input_data_path} for PID {pid}")
                with open(input_data_path, 'r', encoding='utf-8') as f_in:
                    input_content = f_in.read()
                debug_print(f"Read {len(input_content)} characters from input file.")

                if input_content is not None:
                    debug_print(f"Writing {len(input_content)} characters of input at once to PID {pid}")
                    process.stdin.write(input_content)
                    process.stdin.flush()
                    debug_print(f"Closing stdin for PID {pid}")
                    process.stdin.close()
                    debug_print(f"Successfully wrote input and closed stdin for PID {pid}")
                else:
                    debug_print(f"Input file {input_data_path} was empty or read failed. Closing stdin for PID {pid}.")
                    process.stdin.close()

            except FileNotFoundError:
                print(f"ERROR: Input data file not found: {input_data_path} for PID {pid}", file=sys.stderr)
                result["status"] = "CRASHED"
                result["error_details"] = f"Input data file not found: {input_data_path}"
                error_flag.set()
            except (BrokenPipeError, OSError) as e:
                print(f"WARNING: Error writing input or closing stdin for PID {pid} (process likely died): {e}", file=sys.stderr)
                debug_print(f"BrokenPipeError/OSError during stdin write/close for PID {pid}")
                error_flag.set()
            except Exception as e:
                print(f"ERROR: Unexpected error reading/writing input for PID {pid}: {e}", file=sys.stderr)
                debug_print(f"Exception during input processing for PID {pid}", exc_info=True)
                result["status"] = "CRASHED"
                result["error_details"] = f"Failed to read/write input: {e}"
                error_flag.set()
                try:
                    if process.stdin and not process.stdin.closed:
                        process.stdin.close()
                except Exception: pass

            debug_print(f"Starting monitoring loop for PID {pid}")
            monitor_loops = 0
            process_exited_normally = False
            while True:
                monitor_loops += 1
                try:
                    if not ps_proc.is_running():
                        debug_print(f"Monitor loop {monitor_loops}: ps_proc.is_running() is False for PID {pid}. Breaking.")
                        # Check error flag *before* assuming normal exit
                        if not error_flag.is_set() and not JarTester._interrupted:
                            debug_print(f"Monitor loop {monitor_loops}: Process {pid} detected as not running. Setting exitedNormally=True.")
                            process_exited_normally = True
                        break
                except psutil.NoSuchProcess:
                    debug_print(f"Monitor loop {monitor_loops}: psutil.NoSuchProcess caught checking is_running() for PID {pid}. Breaking.")
                    # Check error flag *before* assuming normal exit
                    if not error_flag.is_set() and not JarTester._interrupted:
                        process_exited_normally = True
                    break # Exit loop, let exit code check handle it

                if error_flag.is_set():
                    debug_print(f"Monitor loop {monitor_loops}: Local error flag is set for PID {pid}. Breaking.")
                    break
                # Check global interrupt flag
                if JarTester._interrupted:
                    debug_print(f"Monitor loop {monitor_loops}: Global interrupt flag is set. Breaking.")
                    if result["status"] not in ["TLE", "CTLE", "CRASHED", "CHECKER_ERROR"]: # Preserve existing failure modes
                        result["status"] = "INTERRUPTED"
                        result["error_details"] = "Run interrupted by user (Ctrl+C)."
                    error_flag.set() # Set local flag too to stop I/O threads
                    break

                current_wall_time = time.monotonic() - start_wall_time
                current_cpu_time = result["cpu_time"]
                try:
                    # Optimization: Get CPU times less frequently if needed, but 0.05s interval is ok
                    cpu_times = ps_proc.cpu_times()
                    current_cpu_time = cpu_times.user + cpu_times.system
                except psutil.NoSuchProcess:
                    debug_print(f"Monitor loop {monitor_loops}: NoSuchProcess getting CPU times for PID {pid}. Likely exited cleanly. Breaking monitor loop.")
                    if not error_flag.is_set() and not JarTester._interrupted:
                        process_exited_normally = True
                    break
                except Exception as e_cpu:
                    print(f"ERROR: Monitor loop: Unexpected error getting CPU times for PID {pid}: {e_cpu}", file=sys.stderr)
                    debug_print(f"Monitor loop {monitor_loops}: psutil error getting CPU times for PID {pid}", exc_info=True)
                    if result["status"] not in ["CRASHED", "TLE", "CTLE", "INTERRUPTED", "CHECKER_ERROR"]:
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Tester error getting CPU time: {e_cpu}"
                    error_flag.set() # Set local flag on error
                    break

                result["cpu_time"] = current_cpu_time
                result["wall_time"] = current_wall_time

                if current_cpu_time > CPU_TIME_LIMIT:
                    debug_print(f"Monitor loop {monitor_loops}: CTLE for PID {pid}")
                    result["status"] = "CTLE"
                    result["error_details"] = f"CPU time {current_cpu_time:.2f}s exceeded limit {CPU_TIME_LIMIT:.2f}s."
                    error_flag.set() # Set local flag on limit exceeded
                    break

                # Use the dynamic wall limit passed to the function
                if current_wall_time > current_wall_limit:
                    debug_print(f"Monitor loop {monitor_loops}: TLE for PID {pid}")
                    result["status"] = "TLE"
                    # Update error message to reflect the actual limit used
                    result["error_details"] = f"Wall time {current_wall_time:.2f}s exceeded limit {current_wall_limit:.2f}s."
                    error_flag.set() # Set local flag on limit exceeded
                    break

                time.sleep(0.05) # Monitoring interval

            debug_print(f"Exited monitoring loop for PID {pid} after {monitor_loops} iterations. Status: {result['status']}, ExitedNormally: {process_exited_normally}")

            # --- Termination and Thread Cleanup ---
            if error_flag.is_set() and pid != -1: # If error or interrupt or limit exceeded
                 debug_print(f"Error flag set or limit exceeded, ensuring process tree killed for PID {pid}")
                 try:
                     # Check existence before killing
                     if process and process.poll() is None: JarTester._kill_process_tree(pid)
                     elif psutil.pid_exists(pid): JarTester._kill_process_tree(pid)
                     else: debug_print(f"Process {pid} already gone before kill attempt after loop exit.")
                 except Exception as e_kill_loop:
                     print(f"WARNING: Error during kill attempt after loop exit for PID {pid}: {e_kill_loop}", file=sys.stderr)

            # Wait for I/O threads with a timeout
            debug_print(f"Waiting for I/O threads to finish for PID {pid}")
            thread_join_timeout = 2.0 # Increased timeout slightly
            threads_to_join = [t for t in [stdout_reader_thread, stderr_reader_thread] if t and t.is_alive()]
            start_join_time = time.monotonic()
            while threads_to_join and time.monotonic() - start_join_time < thread_join_timeout:
                for t in threads_to_join[:]: # Iterate copy for removal
                    t.join(timeout=0.1)
                    if not t.is_alive():
                        threads_to_join.remove(t)
            # Log if threads didn't join cleanly
            for t in threads_to_join:
                if t.is_alive():
                    print(f"WARNING: Thread {t.name} for PID {pid} did not exit cleanly within timeout.", file=sys.stderr)
            debug_print(f"Finished waiting for I/O threads for PID {pid}")


            final_status_determined = result["status"] not in ["RUNNING", "PENDING"]

            # Final update of times
            result["wall_time"] = time.monotonic() - start_wall_time
            try:
                if psutil.pid_exists(pid):
                     final_cpu_times = psutil.Process(pid).cpu_times()
                     result["cpu_time"] = final_cpu_times.user + final_cpu_times.system
            except psutil.NoSuchProcess: pass # Process already gone

            # --- Check Exit Code if Process Exited Normally ---
            if process_exited_normally and not final_status_determined:
                debug_print(f"Process {pid} exited normally (flag is True). Getting final state and exit code.")
                exit_code = None
                try:
                    # process.wait should return quickly if it already exited
                    exit_code = process.wait(timeout=0.5)
                    debug_print(f"Process {pid} wait() returned exit code: {exit_code}")
                    if exit_code is not None and exit_code != 0:
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Exited with non-zero code {exit_code}."
                        final_status_determined = True
                    elif result["status"] == "PENDING": # Should likely be RUNNING here
                         result["status"] = "RUNNING" # Correct if it was PENDING

                except subprocess.TimeoutExpired:
                    # This should ideally not happen if process_exited_normally was true
                    print(f"WARNING: Timeout waiting for exit code for PID {pid}, which should have exited. Forcing kill.", file=sys.stderr)
                    try: JarTester._kill_process_tree(pid) # Ensure it's gone
                    except Exception: pass
                    if not final_status_determined:
                        result["status"] = "CRASHED"
                        result["error_details"] = "Process did not report exit code after finishing."
                        final_status_determined = True
                except Exception as e_final:
                    print(f"WARNING: Error getting final state for PID {pid}: {e_final}", file=sys.stderr)
                    debug_print(f"Exception getting final state for PID {pid}", exc_info=True)
                    if not final_status_determined:
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Error getting final process state: {e_final}"
                        final_status_determined = True
            # --- End Exit Code Check ---

        except (psutil.NoSuchProcess) as e_outer:
            # This usually means the process died very early or psutil lost track
            debug_print(f"Outer exception handler: NoSuchProcess for PID {pid} ({jar_basename}). Handled.")
            if result["status"] not in ["CRASHED", "TLE", "CTLE", "INTERRUPTED", "CHECKER_ERROR"]:
                result["status"] = "CRASHED"
                result["error_details"] = f"Process disappeared unexpectedly: {e_outer}"
            error_flag.set() # Ensure flag is set if we land here
        except FileNotFoundError:
            # Error launching the process itself
            print(f"ERROR: Java executable or JAR file '{jar_path}' not found.", file=sys.stderr)
            debug_print(f"Outer exception handler: FileNotFoundError for JAR {jar_basename}.")
            result["status"] = "CRASHED"
            result["error_details"] = f"File not found (Java or JAR)."
            error_flag.set()
        except Exception as e:
            # Catch-all for unexpected errors during setup or monitoring
            print(f"FATAL: Error during execution setup/monitoring of {jar_basename} (PID {pid}): {e}", file=sys.stderr)
            debug_print(f"Outer exception handler: Unexpected exception for PID {pid}", exc_info=True)
            if result["status"] not in ["CRASHED", "TLE", "CTLE", "INTERRUPTED", "CHECKER_ERROR"]:
                result["status"] = "CRASHED"
                result["error_details"] = f"Tester execution error: {e}"
            error_flag.set()
            # Ensure process is killed if exception happened mid-run
            if pid != -1 and process and process.poll() is None:
                debug_print(f"Outer exception: Ensuring PID {pid} is killed.")
                try: JarTester._kill_process_tree(pid)
                except Exception as e_kill_outer: print(f"ERROR: Exception during final kill in outer catch for PID {pid}: {e_kill_outer}", file=sys.stderr)

        finally:
            debug_print(f"Entering finally block for PID {pid}. Status: {result['status']}")
            # Final check to ensure process is gone
            if pid != -1 and process and process.poll() is None:
                try:
                    if psutil.pid_exists(pid):
                        debug_print(f"Final cleanup killing PID {pid}")
                        JarTester._kill_process_tree(pid)
                    else: debug_print(f"Final cleanup: Process {pid} already gone.")
                except Exception as e_kill:
                    print(f"ERROR: Exception during final kill for PID {pid}: {e_kill}", file=sys.stderr)

            # --- Drain queues and Save Stdout ---
            debug_print(f"Draining output queues for PID {pid}")
            stdout_lines = []
            stderr_lines = []
            # Use timeout on get to prevent potential hangs if queue is unexpectedly blocked
            try:
                while True: stdout_lines.append(stdout_queue.get(block=False))
            except queue.Empty: pass
            try:
                while True: stderr_lines.append(stderr_queue.get(block=False))
            except queue.Empty: pass

            result["stderr"] = stderr_lines # Store stderr directly
            debug_print(f"Drained queues for PID {pid}. stdout lines: {len(stdout_lines)}, stderr lines: {len(stderr_lines)}")

            # Save stdout to a unique file in TMP_DIR
            stdout_content = "".join(stdout_lines)
            # Save stdout if content exists OR if the run failed/was interrupted (for debugging)
            save_stdout = stdout_content or result["status"] not in ["PENDING", "RUNNING", "CORRECT"]
            if save_stdout:
                safe_jar_basename = re.sub(r'[^\w.-]', '_', jar_basename)
                stdout_filename = f"output_{safe_jar_basename}_{round_num}.txt"
                stdout_filepath = os.path.abspath(os.path.join(TMP_DIR, stdout_filename))
                try:
                    os.makedirs(TMP_DIR, exist_ok=True) # Ensure dir exists
                    with open(stdout_filepath, 'w', encoding='utf-8', errors='replace') as f_out:
                        f_out.write(stdout_content)
                    result["stdout_log_path"] = stdout_filepath # Store the path
                    debug_print(f"JAR stdout saved to {stdout_filepath}")
                except Exception as e_write_stdout:
                    print(f"WARNING: Failed to write stdout log for {jar_basename} to {stdout_filepath}: {e_write_stdout}", file=sys.stderr)
                    result["stdout_log_path"] = None # Indicate failure
            else:
                 debug_print(f"No stdout content generated for {jar_basename} and status is OK, not saving file.")
                 result["stdout_log_path"] = None

            # Final check on threads - they should be done or daemonized
            debug_print(f"Final check join for threads of PID {pid}")
            if stdout_reader_thread and stdout_reader_thread.is_alive(): stdout_reader_thread.join(timeout=0.1)
            if stderr_reader_thread and stderr_reader_thread.is_alive(): stderr_reader_thread.join(timeout=0.1)
            debug_print(f"Exiting finally block for PID {pid}")
            # --- End Draining and Saving ---


        # Run Checker (only if status allows and not interrupted globally)
        # Uses the saved stdout content for the checker's temporary file
        # Check should happen only if JAR finished without TLE/CTLE/Crash/Interrupt
        # Note: JarTester._interrupted is the GLOBAL interrupt flag
        run_checker = (result["status"] == "RUNNING" and not JarTester._interrupted)

        if run_checker:
            debug_print(f"Running checker for {jar_basename} (PID {pid}) because status is RUNNING and not globally interrupted.")
            # stdout_content is already available from the finally block
            temp_output_file = None
            checker_status = "CHECKER_PENDING"
            checker_details = ""
            try:
                # Use NamedTemporaryFile for checker's input, content comes from stdout_content
                # Ensure it's created in TMP_DIR for organization
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt", encoding='utf-8', dir=TMP_DIR, errors='replace') as tf:
                    tf.write(stdout_content) # Use the captured content
                    temp_output_file = tf.name

                # Use input_data_path (original generator output path) for checker's first arg
                debug_print(f"Checker using input(gen) '{input_data_path}' and output(jar) '{temp_output_file}' with Tmax={current_wall_limit:.2f}s")

                # Increased checker timeout slightly
                checker_timeout = 45.0
                checker_proc = subprocess.run(
                    [sys.executable, JarTester._checker_script_path, input_data_path, temp_output_file, "--tmax", str(current_wall_limit)],
                    capture_output=True, text=True, timeout=checker_timeout, check=False, encoding='utf-8', errors='replace'
                )
                debug_print(f"Checker for {jar_basename} finished with code {checker_proc.returncode}")

                if checker_proc.stderr:
                    result["stderr"].extend(["--- Checker stderr ---"] + checker_proc.stderr.strip().splitlines())

                # --- (Checker result parsing - unchanged logic, improved debug/error) ---
                if checker_proc.returncode != 0:
                    checker_status = "CHECKER_ERROR"
                    checker_details = f"Checker exited with code {checker_proc.returncode}."
                    details_stdout = checker_proc.stdout.strip()
                    details_stderr = checker_proc.stderr.strip()
                    if details_stdout: checker_details += f" stdout: {details_stdout[:200]}"
                    if details_stderr: checker_details += f" stderr: {details_stderr[:200]}"
                    debug_print(f"Checker error for {jar_basename}: Exit code {checker_proc.returncode}")
                
                # Get the raw output, decode if necessary
                checker_output = checker_proc.stdout
                try:
                    # 如果是 bytes，先解码
                    if isinstance(checker_output, bytes):
                        checker_output = checker_output.decode('utf-8')
                    # 使用 ast.literal_eval 解析（兼容单引号）
                    checker_data = ast.literal_eval(checker_output)
                    
                    # 或者用 json.loads（需要确保是标准 JSON）
                    # checker_data = json.loads(checker_output.replace("'", '"'))
                except (ValueError, SyntaxError) as e:
                    print(f"解析失败！原始数据: {checker_output}")
                    raise

                # Check the result field from the parsed JSON
                if checker_data.get("result") == "Success":
                    checker_status = "CORRECT"
                    debug_print(f"Checker result for {jar_basename}: CORRECT")
                    try:
                        # Access performance metrics directly from the parsed dictionary
                        performance_metrics = checker_data.get("performance")
                        if performance_metrics:
                            t_final_val = performance_metrics.get("T_final")
                            wt_val = performance_metrics.get("WT_weighted_time")
                            w_val = performance_metrics.get("W_energy") # Use the key from checker.py

                            # Validate that all metrics were found and are numeric
                            if t_final_val is not None and wt_val is not None and w_val is not None and \
                            isinstance(t_final_val, (int, float)) and \
                            isinstance(wt_val, (int, float)) and \
                            isinstance(w_val, (int, float)):

                                result["t_final"] = float(t_final_val)
                                result["wt"] = float(wt_val)
                                result["w"] = float(w_val)
                                debug_print(f"Extracted Metrics for {jar_basename}: T_final={result['t_final']}, WT={result['wt']}, W={result['w']}")
                            else:
                                # Handle case where 'performance' exists but metrics are missing/invalid
                                missing = []
                                if t_final_val is None: missing.append("T_final")
                                if wt_val is None: missing.append("WT_weighted_time")
                                if w_val is None: missing.append("W_energy")
                                checker_status = "CHECKER_ERROR"
                                checker_details = f"Correct verdict but failed to extract/validate metrics ({', '.join(missing)}) from performance data."
                                debug_print(f"Metric extraction/validation failed for {jar_basename}. Performance data: {performance_metrics}")
                                result["t_final"] = result["wt"] = result["w"] = None # Ensure reset
                        else:
                            # Handle case where result is "Success" but "performance" key is missing
                            checker_status = "CHECKER_ERROR"
                            checker_details = "Correct verdict but 'performance' section missing in checker output."
                            debug_print(f"Performance section missing for {jar_basename}. Checker data: {checker_data}")
                            result["t_final"] = result["wt"] = result["w"] = None # Ensure reset

                    except (TypeError, ValueError, KeyError) as e_metric:
                        # Catch errors during metric access/conversion (though .get should prevent most KeyErrors)
                        print(f"ERROR: Checker verdict CORRECT for {jar_basename}, but failed processing metrics: {e_metric}", file=sys.stderr)
                        checker_status = "CHECKER_ERROR"
                        checker_details = f"Correct verdict but metric processing failed: {e_metric}"
                        result["t_final"] = result["wt"] = result["w"] = None

                elif checker_data.get("result") == "Fail":
                    # Handle INCORRECT cases based on the JSON output
                    checker_status = "INCORRECT"
                    # Extract error details from the 'errors' list
                    errors_list = checker_data.get("errors", ["Checker reported 'Fail' but no specific errors found."])
                    # Join the errors into a single string for details
                    checker_details = "; ".join(errors_list)
                    # Optional: Truncate if the error string is potentially very long
                    # max_detail_len = 250
                    # if len(checker_details) > max_detail_len:
                    #     checker_details = checker_details[:max_detail_len] + "..."
                    debug_print(f"Checker result for {jar_basename}: INCORRECT/Fail. Details: {checker_details}")
                    result["t_final"] = result["wt"] = result["w"] = None # Ensure metrics are None for failed runs

                else:
                    # Handle unexpected 'result' values
                    checker_status = "CHECKER_ERROR"
                    res_val = checker_data.get("result", "None")
                    checker_details = f"Checker returned unexpected result value: '{res_val}'"
                    debug_print(f"Unexpected checker result for {jar_basename}: {checker_details}. Full data: {checker_data}")
                    result["t_final"] = result["wt"] = result["w"] = None

            except subprocess.TimeoutExpired:
                print(f"ERROR: Checker timed out for {jar_basename}.", file=sys.stderr)
                checker_status = "CHECKER_ERROR"
                checker_details = f"Checker process timed out after {checker_timeout}s."
            except Exception as e_check:
                print(f"ERROR: Exception running checker for {jar_basename}: {e_check}", file=sys.stderr)
                debug_print(f"Checker exception for {jar_basename}", exc_info=True)
                checker_status = "CHECKER_ERROR"
                checker_details = f"Exception during checker execution: {e_check}"
            finally:
                if temp_output_file and os.path.exists(temp_output_file):
                    try: os.remove(temp_output_file)
                    except Exception as e_rm: print(f"WARNING: Failed to remove temp checker output file {temp_output_file}: {e_rm}", file=sys.stderr)

            # Update result based on checker outcome
            result["status"] = checker_status
            if checker_status != "CORRECT":
                result["error_details"] = checker_details
                result["t_final"] = result["wt"] = result["w"] = None # Reset metrics on non-correct

        elif JarTester._interrupted and result["status"] == "RUNNING":
             # If globally interrupted *before* checker ran, mark as interrupted
             result["status"] = "INTERRUPTED"
             result["error_details"] = "Run interrupted before checker execution."
             debug_print(f"Marking {jar_basename} as INTERRUPTED (checker skipped due to global interrupt).")
        elif result["status"] != "RUNNING":
            # If JAR failed before checker (TLE, CTLE, CRASHED)
             debug_print(f"Skipping checker for {jar_basename} due to JAR status: {result['status']}")
        else:
             # Should not happen with current logic, but catch any edge case
             debug_print(f"Skipping checker for {jar_basename} (unknown reason). Status: {result['status']}, Interrupt: {JarTester._interrupted}")


        # Ensure score is 0 if final status is not CORRECT
        if result["status"] != "CORRECT":
            result["final_score"] = 0.0
            # Ensure metrics are None if not correct
            result["t_final"] = result["wt"] = result["w"] = None


        debug_print(f"Finished run for JAR: {jar_basename}. Final Status: {result['status']}")
        return result


    # --- (Keep _generate_data as it is) ---
    @staticmethod
    def _generate_data(gen_args_list, round_num, seed_value):
        """Calls gen.py with provided args, returns requests, writes output to unique tmp file."""
        # Generate a unique filename for this round's input data
        input_filename = f"input_{seed_value}_{round_num}.txt"
        input_filepath = os.path.abspath(os.path.join(TMP_DIR, input_filename))
        os.makedirs(os.path.dirname(input_filepath), exist_ok=True) # Ensure TMP_DIR exists

        requests_data = None
        gen_stdout = None
        gen_success = False

        try:
            command = [sys.executable, JarTester._gen_script_path] + gen_args_list
            debug_print(f"Running generator: {' '.join(command)}")

            gen_timeout = 20.0
            gen_proc = subprocess.run(
                command, capture_output=True, text=True, timeout=gen_timeout, check=True, encoding='utf-8', errors='replace'
            )
            gen_stdout = gen_proc.stdout
            gen_success = True # Mark success if run completes without error

            try:
                # Write generator output regardless of parsing success below
                with open(input_filepath, 'w', encoding='utf-8', errors='replace') as f: f.write(gen_stdout)
                debug_print(f"Generator output written to tmp file: {input_filepath}")
            except Exception as e_write:
                print(f"ERROR: Failed to write generator output to {input_filepath}: {e_write}", file=sys.stderr)
                # Don't mark input_filepath as None, it might still be useful for debugging
                # But generation effectively failed if we can't save the input

            # --- (Request Parsing Logic - unchanged) ---
            raw_requests = gen_stdout.strip().splitlines()
            requests_data = []
            # More robust regex allowing variable whitespace
            pattern = re.compile(r"^\s*\[\s*(\d+\.?\d*)\s*\]\s*(.*)")
            parse_errors = 0
            for line_num, line in enumerate(raw_requests):
                match = pattern.match(line)
                if match:
                    try:
                        timestamp_req = float(match.group(1)) # Renamed to avoid confusion
                        req_part = match.group(2).strip() # Strip whitespace from request part
                        if req_part: # Only add if request part is not empty
                           requests_data.append((timestamp_req, req_part))
                        # else: # Optional: log ignored empty request parts
                        #    debug_print(f"Generator produced empty request part (ignored): {line}")
                    except ValueError:
                        parse_errors += 1
                        print(f"WARNING: Generator line {line_num+1}: Invalid number format (ignored): {line}", file=sys.stderr)
                elif line.strip(): # Ignore empty lines but warn about non-matching lines
                    parse_errors += 1
                    print(f"WARNING: Generator line {line_num+1}: Invalid line format (ignored): {line}", file=sys.stderr)

            # Handle n=0 case specifically
            is_n_zero = any(arg == '-n' and gen_args_list[i+1] == '0' for i, arg in enumerate(gen_args_list[:-1]))
            if not raw_requests and not requests_data and is_n_zero:
                 debug_print("Generator produced no output (expected for n=0). Returning empty list.")
                 # Return empty list and the path (file will be empty)
                 return [], input_filepath

            # Check if parsing failed despite generator producing output
            if parse_errors > 0 and not requests_data:
                 print(f"ERROR: Generator produced output, but NO valid request lines were parsed from {input_filepath}.", file=sys.stderr)
                 # Return empty list, but keep the path for debugging
                 return [], input_filepath
            elif parse_errors > 0:
                 print(f"WARNING: {parse_errors} lines in generator output had parsing errors (see {input_filepath}).", file=sys.stderr)


            # Sort requests by timestamp
            requests_data.sort(key=lambda x: x[0])
            debug_print(f"Successfully parsed {len(requests_data)} requests.")
            return requests_data, input_filepath

        except FileNotFoundError:
            print(f"ERROR: Generator script not found at '{JarTester._gen_script_path}'", file=sys.stderr)
            return None, None # Generation failed completely
        except subprocess.TimeoutExpired:
            print(f"ERROR: Generator script timed out after {gen_timeout}s.", file=sys.stderr)
            # Try save output if available, return None for requests
            if gen_stdout is not None and input_filepath:
                 try:
                     with open(input_filepath, 'w', encoding='utf-8', errors='replace') as f: f.write(gen_stdout)
                 except Exception: pass
            return None, input_filepath # Return path even on failure
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Generator script failed with exit code {e.returncode}.", file=sys.stderr)
            print(f"--- Generator Command ---\n{' '.join(command)}", file=sys.stderr)
            # Limit output logging to avoid spamming console
            stdout_log = (e.stdout or '<empty>')[:1000]
            stderr_log = (e.stderr or '<empty>')[:1000]
            print(f"--- Generator Stdout (truncated) ---\n{stdout_log}\n--- Generator Stderr (truncated) ---\n{stderr_log}", file=sys.stderr)
            # Try to save the failed output anyway
            if e.stdout is not None and input_filepath:
                 try:
                     with open(input_filepath, 'w', encoding='utf-8', errors='replace') as f: f.write(e.stdout)
                     print(f"INFO: Saved generator's failed stdout to {input_filepath}", file=sys.stderr)
                 except Exception: pass
            return None, input_filepath # Return path even on failure
        except Exception as e:
            print(f"ERROR: Unexpected error during data generation: {e}", file=sys.stderr)
            debug_print("Exception in _generate_data", exc_info=True)
            # Try save output if available, return None for requests
            if gen_stdout is not None and input_filepath:
                 try:
                     with open(input_filepath, 'w', encoding='utf-8', errors='replace') as f: f.write(gen_stdout)
                 except Exception: pass
            return None, input_filepath # Return path even on failure

    # --- (Keep _calculate_scores as it is) ---
    @staticmethod
    def _calculate_scores(current_results):
        """Calculates normalized performance scores based on current round results."""
        correct_results = [
            r for r in current_results
            if r["status"] == "CORRECT"
            and r["t_final"] is not None and r["wt"] is not None and r["w"] is not None
        ]
        debug_print(f"Calculating scores based on {len(correct_results)} CORRECT runs with metrics.")

        # Initialize all scores to 0 first
        for r in current_results:
            r["final_score"] = 0.0

        if not correct_results:
            debug_print("No CORRECT results with metrics found for score calculation.")
            return # All scores remain 0

        t_finals = np.array([r["t_final"] for r in correct_results])
        wts = np.array([r["wt"] for r in correct_results])
        ws = np.array([r["w"] for r in correct_results])
        metrics = {'t_final': t_finals, 'wt': wts, 'w': ws}
        normalized_scores = {}

        for name, values in metrics.items():
            if len(values) == 0: continue # Should not happen if correct_results is not empty
            # Use more robust min/max/avg calculation
            try:
                x_min = np.min(values)
                x_max = np.max(values)
                x_avg = np.mean(values)
            except Exception as e_np:
                 print(f"ERROR: NumPy error calculating stats for {name}: {e_np}. Skipping scoring for this metric.", file=sys.stderr)
                 continue # Skip this metric if stats fail

            debug_print(f"Metric {name}: min={x_min:.3f}, max={x_max:.3f}, avg={x_avg:.3f}")
            # Handle cases where all values are the same or very close
            if abs(x_max - x_min) < 1e-9:
                 base_min = x_min
                 base_max = x_max
                 debug_print(f"Metric {name}: All values effectively the same.")
            else:
                # Apply P-value adjustment
                base_min = PERF_P_VALUE * x_avg + (1 - PERF_P_VALUE) * x_min
                base_max = PERF_P_VALUE * x_avg + (1 - PERF_P_VALUE) * x_max
                # Ensure base_min <= base_max after adjustment
                if base_min > base_max:
                    debug_print(f"Metric {name}: Adjusted base_min ({base_min:.3f}) > base_max ({base_max:.3f}), clamping.")
                    # Could swap, or set both to avg, or just clamp min to max
                    base_min = base_max # Clamp min to max if order reversed

            debug_print(f"Metric {name}: base_min={base_min:.3f}, base_max={base_max:.3f}")

            normalized = {}
            denominator = base_max - base_min
            is_denominator_zero = abs(denominator) < 1e-9

            for r in correct_results:
                x = r[name]
                r_x = 0.0 # Default normalized score (lower is better)

                if is_denominator_zero:
                    # If range is zero, all get same relative score (0 here, as lower is better)
                    r_x = 0.0
                else:
                    # Clamp values to the base range before normalizing
                    if x <= base_min + 1e-9: # Add tolerance
                        r_x = 0.0
                    elif x >= base_max - 1e-9: # Add tolerance
                        r_x = 1.0
                    else:
                        r_x = (x - base_min) / denominator

                normalized[r["jar_file"]] = r_x
                debug_print(f"  NormScore {name} for {r['jar_file']} (val={x:.3f}): {r_x:.4f}")

            normalized_scores[name.upper()] = normalized

        # Calculate final scores based on normalized components
        for r in correct_results:
            jar_name = r["jar_file"]
            try:
                # Use .get() with default 0.0 to handle potential missing metrics if scoring failed above
                r_t = normalized_scores.get('T_FINAL', {}).get(jar_name, 0.0)
                r_wt = normalized_scores.get('WT', {}).get(jar_name, 0.0)
                r_w = normalized_scores.get('W', {}).get(jar_name, 0.0)

                # Invert scores (0 is best, 1 is worst -> 1 is best, 0 is worst)
                r_prime_t = 1.0 - r_t
                r_prime_wt = 1.0 - r_wt
                r_prime_w = 1.0 - r_w

                # Weighted sum
                # Weights: T_final=0.3, WT=0.3, W=0.4
                s = 15 * (0.3 * r_prime_t + 0.3 * r_prime_wt + 0.4 * r_prime_w)
                r["final_score"] = max(0.0, s) # Ensure score is non-negative
                debug_print(f"Score for {jar_name}: T_final={r['t_final']:.3f}(Norm:{r_t:.3f}, Inv:{r_prime_t:.3f}), WT={r['wt']:.3f}(Norm:{r_wt:.3f}, Inv:{r_prime_wt:.3f}), W={r['w']:.3f}(Norm:{r_w:.3f}, Inv:{r_prime_w:.3f}) -> Final={r['final_score']:.3f}")
            except KeyError as e_key: # Should be less likely with .get()
                print(f"WARNING: Missing normalized score component for {jar_name}: {e_key}. Setting final score to 0.", file=sys.stderr)
                r["final_score"] = 0.0
            except Exception as e_score:
                 print(f"ERROR: Unexpected error calculating final score for {jar_name}: {e_score}. Setting score to 0.", file=sys.stderr)
                 debug_print(f"Score calculation exception for {jar_name}", exc_info=True)
                 r["final_score"] = 0.0
        # Scores for non-CORRECT runs were already set to 0


    # --- Modify _display_results to use Lock and log round number ---
    @staticmethod
    def _display_and_log_results(round_num, results, round_preset_cmd, input_data_path, round_wall_limit):
        """Display results for the current round and log errors AND summary table. Uses Log Lock."""
        log_lines = []
        has_errors_for_log = False

        results.sort(key=lambda x: (-x.get("final_score", 0.0), x.get("wall_time", float('inf')) if x.get("status") == "CORRECT" else float('inf')))

        round_header = f"\n--- Test Round {round_num} Results (Preset: {round_preset_cmd} | Wall Limit: {round_wall_limit:.1f}s) ---"
        header = f"{'JAR':<25} | {'Status':<12} | {'Score':<7} | {'T_final':<10} | {'WT':<10} | {'W':<10} | {'CPU(s)':<8} | {'Wall(s)':<8} | Details"
        separator = "-" * len(header)

        log_lines.append(round_header.replace(" Results ", " Summary "))
        log_lines.append(f"Input Data File: {input_data_path if input_data_path else '<Not Available>'}")
        log_lines.append(header)
        log_lines.append(separator)

        error_log_header_needed = True # Track if error header needs to be logged for this round
        result_lines_for_console = []

        for r in results:
            jar_name = r.get("jar_file", "UnknownJAR")
            status = r.get("status", "UNKNOWN")
            score = r.get("final_score", 0.0)
            score_str = f"{score:.3f}" if status == "CORRECT" else "---"
            tfin = r.get("t_final")
            tfin_str = f"{tfin:.3f}" if tfin is not None else "---"
            wt = r.get("wt")
            wt_str = f"{wt:.3f}" if wt is not None else "---"
            w = r.get("w")
            w_str = f"{w:.3f}" if w is not None else "---"
            cpu = r.get("cpu_time", 0.0)
            cpu_str = f"{cpu:.2f}"
            wall = r.get("wall_time", 0.0)
            wall_str = f"{wall:.2f}"
            details = r.get("error_details", "")[:100] # Truncate details for console

            # Line for console (potentially truncated details)
            console_line = f"{jar_name:<25} | {status:<12} | {score_str:<7} | {tfin_str:<10} | {wt_str:<10} | {w_str:<10} | {cpu_str:<8} | {wall_str:<8} | {details}"
            result_lines_for_console.append(console_line)            
            
            log_line = f"{jar_name:<25} | {status:<12} | {score_str:<7} | {tfin_str:<10} | {wt_str:<10} | {w_str:<10} | {cpu_str:<8} | {wall_str:<8} | {r.get('error_details', '')}"
            log_lines.append(log_line)

            # --- Modify Error Logging Section ---
            if status not in ["CORRECT", "PENDING", "RUNNING", "INTERRUPTED"]:
                has_errors_for_log = True
                if error_log_header_needed:
                    log_lines.append(f"\n--- Test Round {round_num} Error Details ---")
                    # Log input data path once per error section header
                    log_lines.append(f"Input Data File for this Round: {input_data_path if input_data_path else '<Not Available>'}")
                    error_log_header_needed = False # Header logged for this round

                log_lines.append(f"\n--- Error Details for: {jar_name} (Status: {status}) ---")
                log_lines.append(f"  Preset Used: {round_preset_cmd}")
                log_lines.append(f"  Wall Limit Used: {round_wall_limit:.1f}s")
                log_lines.append(f"  Error: {r.get('error_details', '')}") # Log full details

                # Log path to input data file
                log_lines.append("  --- Input Data File ---")
                log_lines.append(f"    Path: {input_data_path if input_data_path else '<Not Available>'}")
                log_lines.append("  --- End Input Data File ---")

                # Log path to stdout file
                stdout_log = r.get("stdout_log_path")
                log_lines.append("  --- Stdout Log File ---")
                log_lines.append(f"    Path: {stdout_log if stdout_log else '<Not Saved or Error>'}")
                log_lines.append("  --- End Stdout Log File ---")

                # Keep logging stderr content directly
                log_lines.append("  --- Stderr ---")
                stderr = r.get("stderr", [])
                if stderr:
                    MAX_OUTPUT_LOG_LINES = 100
                    for i, err_line in enumerate(stderr):
                         if i < MAX_OUTPUT_LOG_LINES: log_lines.append(f"    {err_line.strip()}")
                         elif i == MAX_OUTPUT_LOG_LINES: log_lines.append(f"    ... (stderr truncated after {MAX_OUTPUT_LOG_LINES} lines)"); break
                    if len(stderr) <= MAX_OUTPUT_LOG_LINES: log_lines.append("    <End of Stderr>")
                else:
                     log_lines.append("    <No stderr captured>")
                log_lines.append("  --- End Stderr ---")
                log_lines.append("-" * 20)
            # --- End Modified Error Logging Section ---

        log_lines.append(separator) # Add separator to log lines

        # --- Print block to console atomically using the console lock ---
        with JarTester._console_lock:
            print(round_header)
            print(header)
            print(separator)
            for line in result_lines_for_console:
                print(line)
            print(separator)
            print(f"--- End of Round {round_num} ---") # Console end marker

        # --- Log writing with lock ---
        if JarTester._log_file_path:
            try:
                with JarTester._log_lock: # Acquire lock before writing
                    with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                        f.write("\n".join(log_lines) + "\n\n") # Add extra newline for spacing
                debug_print(f"Results and errors for round {round_num} written to log.")
            except Exception as e:
                with JarTester._console_lock:
                    print(f"ERROR: Failed to write results to log file {JarTester._log_file_path} for round {round_num}: {e}", file=sys.stderr)


    # --- Modify _update_history to use Lock ---
    @staticmethod
    def _update_history(results):
        """Update the historical results after a round. Uses History Lock."""
        # Acquire lock before accessing/modifying shared history
        with JarTester._history_lock:
            # debug_print("Acquired history lock") # Optional: debug lock acquisition
            for r in results:
                if r.get("status") == "INTERRUPTED": continue # Skip interrupted runs
                jar_name = r.get("jar_file", "UnknownJAR")
                if jar_name == "UnknownJAR": continue

                history = JarTester._all_results_history[jar_name] # defaultdict handles creation
                history['total_runs'] += 1
                score_to_add = 0.0
                if r.get("status") == "CORRECT":
                    history['correct_runs'] += 1
                    # Ensure score is a float, default to 0.0 if None or not present
                    score_to_add = float(r.get("final_score", 0.0) or 0.0)

                history['scores'].append(score_to_add)
                # debug_print(f"History update for {jar_name}: Total={history['total_runs']}, Correct={history['correct_runs']}, Added Score={score_to_add:.3f}")
            # debug_print("Released history lock") # Optional: debug lock release


    # --- (Keep _print_summary as it is, it reads history after all rounds) ---
    @staticmethod
    def _print_summary():
        """Generates the final summary string. Reads locked history at the end."""
        summary_lines = [] # Store lines instead of printing directly

        if JarTester._interrupted:
            summary_lines.append("\n--- Testing Interrupted ---")
        else:
            summary_lines.append("\n--- Testing Finished ---")

        # Access counter safely - though it might be slightly off if interrupted mid-increment
        # It's mainly indicative.
        with JarTester._round_counter_lock:
            total_rounds_assigned = JarTester._round_counter
        summary_lines.append(f"Total test rounds initiated: {total_rounds_assigned}")

        # Access history safely using the lock
        with JarTester._history_lock:
            if not JarTester._all_results_history:
                summary_lines.append("No completed test results recorded in history.")
                return "\n".join(summary_lines) # Return the generated lines

            summary_lines.append("\n--- Average Performance Summary (Based on Completed Rounds) ---")
            summary_data = [] # Renamed from 'summary' to avoid conflict
            # Iterate over a copy of items to avoid issues if dict changes (shouldn't with lock)
            history_items = list(JarTester._all_results_history.items())

        # Process data outside the lock
        for jar_name, data in history_items:
            total_runs = data['total_runs']
            correct_runs = data['correct_runs']
            scores = data['scores']
            # Filter scores more carefully
            valid_scores = [s for s in scores if isinstance(s, (int, float)) and np.isfinite(s)] # Check for finite numbers
            avg_score = np.mean(valid_scores) if valid_scores else 0.0
            correct_rate = (correct_runs / total_runs * 100) if total_runs > 0 else 0.0
            # Ensure avg_score is not nan/inf before formatting
            avg_score = avg_score if np.isfinite(avg_score) else 0.0
            summary_data.append({
                "jar": jar_name, "avg_score": avg_score, "correct_rate": correct_rate,
                "correct": correct_runs, "total": total_runs
            })

        summary_data.sort(key=lambda x: (-x["avg_score"], -x["correct_rate"], x["jar"])) # Added JAR name sort tiebreaker

        header = f"{'JAR':<25} | {'Avg Score':<10} | {'Correct %':<10} | {'Passed/Total':<15}"
        summary_lines.append(header)
        summary_lines.append("-" * len(header))

        for item in summary_data:
             passed_total_str = f"{item['correct']}/{item['total']}"
             line = f"{item['jar']:<25} | {item['avg_score']:<10.3f} | {item['correct_rate']:<10.1f}% | {passed_total_str:<15}"
             summary_lines.append(line)

        summary_lines.append("-" * len(header))
        return "\n".join(summary_lines) # Return the complete summary string

    # --- (Keep _signal_handler as it is) ---
    @staticmethod
    def _signal_handler(sig, frame):
        if not JarTester._interrupted:
            print("\nCtrl+C detected. Stopping submission of new rounds. Waiting for running rounds to finish...", file=sys.stderr)
            JarTester._interrupted = True
            # Potential future enhancement: add a second Ctrl+C handler to force kill running rounds.

    # --- (Keep _initialize_presets, _preset_dict_to_arg_list as they are) ---
    @staticmethod
    def _initialize_presets():
        """Parse the raw command strings into argument dictionaries."""
        JarTester._gen_arg_presets = []
        JarTester._raw_preset_commands = []
        required_time_arg_present = True # Flag to check if all presets have time args

        if not JarTester._loaded_preset_commands: # 检查是否成功加载了命令
            print("ERROR: No generator presets were loaded. Cannot initialize.", file=sys.stderr)
            return False

        for cmd_index, cmd_str in enumerate(JarTester._loaded_preset_commands):
            parts = cmd_str.split()
            if not parts or parts[0] != "gen.py":
                print(f"WARNING: Skipping invalid preset format (must start with 'gen.py'): {cmd_str}", file=sys.stderr)
                continue

            args_dict = {}
            has_time_arg = False # Check time arg per preset
            i = 1
            while i < len(parts):
                arg = parts[i]
                if not arg.startswith('-'):
                    # Simple check for misplaced values (often happens with copy-paste)
                    if i > 1 and parts[i-1].startswith('-'):
                        print(f"WARNING: Argument '{parts[i-1]}' in preset '{cmd_str}' seems to be missing a value before '{arg}'. Assuming '{arg}' is a new argument.", file=sys.stderr)
                    else:
                        print(f"WARNING: Skipping invalid non-argument part in preset '{cmd_str}': {arg}", file=sys.stderr)
                    i += 1
                    continue

                # Track if this is a time argument
                if arg in ['-t', '--max-time']:
                    has_time_arg = True

                # Check if next part is potentially a value (doesn't start with '-')
                if i + 1 < len(parts) and not parts[i+1].startswith('-'):
                    value = parts[i+1]
                    # Basic type inference (optional but helpful for max_time)
                    try:
                        value = int(value)
                    except ValueError:
                        try:
                            value = float(value)
                        except ValueError:
                            pass # Keep as string if not int or float
                    args_dict[arg] = value
                    i += 2
                else:
                    # Handle flags (arguments without values)
                    args_dict[arg] = True
                    i += 1

            # Check if time argument was found for this preset
            if not has_time_arg:
                print(f"WARNING: Preset '{cmd_str}' does not contain '-t' or '--max-time'. Wall time limit calculation will use default ({DEFAULT_GEN_MAX_TIME}s).", file=sys.stderr)
                required_time_arg_present = False # Mark that at least one is missing

            # Store the raw command string fragment as label
            preset_label = " ".join(parts[1:])
            JarTester._gen_arg_presets.append(args_dict)
            JarTester._raw_preset_commands.append(preset_label)
            # debug_print(f"Parsed preset {cmd_index}: '{preset_label}' -> {args_dict}")

        num_presets = len(JarTester._gen_arg_presets)
        print(f"INFO: Initialized/Parsed {num_presets} valid generator presets from the loaded list.") # 更新了打印信息
        if num_presets == 0:
            print("ERROR: No valid generator presets were parsed. Cannot continue.", file=sys.stderr)
            return False # Indicate failure
        if not required_time_arg_present:
             print(f"INFO: Some presets lack explicit time arguments ('-t' or '--max-time'). Default generator time ({DEFAULT_GEN_MAX_TIME}s) will be used for wall limit calculation in those cases.")
        return True # Indicate success


    @staticmethod
    def _preset_dict_to_arg_list(preset_dict):
        """Convert a preset dictionary back to a list of strings for subprocess."""
        args_list = []
        for key, value in preset_dict.items():
            args_list.append(key)
            if value is not True: # Check for boolean flags (value is True)
                args_list.append(str(value)) # Ensure value is string for subprocess
        return args_list

    @staticmethod
    def _run_one_round(round_num):
        """Executes all steps for a single test round."""
        if JarTester._interrupted:
            debug_print(f"Round {round_num}: Skipping execution due to global interrupt flag.")
            return None # Indicate round did not run

        thread_name = threading.current_thread().name
        print(f"INFO [{thread_name}]: Starting Test Round {round_num}")
        debug_print(f"Round {round_num}: Starting execution.")

        round_results = None
        selected_preset_cmd = "<Not Selected>"
        input_data_path = None
        round_wall_time_limit = MIN_WALL_TIME_LIMIT
        current_seed = -1 # 初始化 seed
        full_preset_cmd = "<Not Set>" # 初始化 full_preset_cmd

        try:
            # --- Select Preset and Determine Wall Time Limit ---
            if not JarTester._gen_arg_presets:
                print(f"ERROR [{thread_name}]: No generator presets available for round {round_num}.", file=sys.stderr)
                return None # Cannot proceed

            preset_index = random.randrange(len(JarTester._gen_arg_presets))
            selected_preset_dict = JarTester._gen_arg_presets[preset_index]
            selected_preset_cmd = JarTester._raw_preset_commands[preset_index]
            gen_args_list = JarTester._preset_dict_to_arg_list(selected_preset_dict)

            # Add unique seed for this round
            current_seed = int(time.time() * 1000) + round_num # Add round num for extra uniqueness
            seed_arg_str = f"--seed {current_seed}"
            gen_args_list.extend(["--seed", str(current_seed)])
            full_preset_cmd = f"{selected_preset_cmd} {seed_arg_str}" # Include seed in logged command

            debug_print(f"Round {round_num}: Using Generator Preset: {full_preset_cmd}")

            # Extract gen max_time to calculate wall time limit for this round
            gen_max_time_str = selected_preset_dict.get('-t') or selected_preset_dict.get('--max-time')
            round_gen_max_time = DEFAULT_GEN_MAX_TIME # Use default if not specified
            if gen_max_time_str:
                try:
                    round_gen_max_time = float(gen_max_time_str)
                except ValueError:
                    print(f"WARNING [{thread_name}] Round {round_num}: Could not parse max_time '{gen_max_time_str}' from preset. Using default {round_gen_max_time}s for limit calculation.", file=sys.stderr)
            # Calculate the wall time limit for this specific round
            round_wall_time_limit = max(MIN_WALL_TIME_LIMIT, round_gen_max_time * 2.0 + 10.0) # Add a small buffer maybe
            debug_print(f"Round {round_num}: Setting WALL_TIME_LIMIT: {round_wall_time_limit:.2f}s (based on gen max_time {round_gen_max_time:.2f}s)")
            # --------------------------------------------------

            # 1. Generate Data
            debug_print(f"Round {round_num}: Generating data...")
            requests_data, input_data_path = JarTester._generate_data(gen_args_list, round_num, current_seed)

            if requests_data is None:
                print(f"ERROR [{thread_name}] Round {round_num}: Failed to generate data (Preset: {full_preset_cmd}). Skipping round execution.", file=sys.stderr)
                # Log generation failure (using the log lock)
                if JarTester._log_file_path:
                     try:
                         with JarTester._log_lock:
                             with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                                 f.write(f"\n--- Round {round_num}: Generation FAILED ---\n")
                                 f.write(f"Thread: {thread_name}\n")
                                 f.write(f"Preset: {full_preset_cmd}\n")
                                 f.write(f"Wall Limit (intended): {round_wall_time_limit:.1f}s\n")
                                 # Log path even if write failed or requests=None
                                 f.write(f"Attempted Input File: {input_data_path if input_data_path else '<Path Not Generated>'}\n\n")
                     except Exception as e_log:
                          print(f"ERROR [{thread_name}] Round {round_num}: Failed to log generation failure: {e_log}", file=sys.stderr)
                return None # Stop processing this round
            # Log the path to the generated input file
            debug_print(f"Round {round_num}: Generated {len(requests_data)} requests to '{input_data_path}'")

            if JarTester._interrupted:
                debug_print(f"Round {round_num}: Interrupted after data generation. Cleaning up input file.")
                if input_data_path and os.path.exists(input_data_path):
                    try: os.remove(input_data_path)
                    except Exception: pass
                return None # Stop processing

            # 2. Run JARs Concurrently (Inner Parallelism)
            if not JarTester._jar_files:
                 print(f"ERROR [{thread_name}] Round {round_num}: No JAR files found to test.", file=sys.stderr)
                 # Cleanup generated input file if it exists
                 if input_data_path and os.path.exists(input_data_path):
                      try: os.remove(input_data_path)
                      except Exception: pass
                 return None

            results_this_round = []
            max_workers_per_round = min(len(JarTester._jar_files), (os.cpu_count() or 4) * 2 + 1)
            debug_print(f"Round {round_num}: Running {len(JarTester._jar_files)} JARs with max {max_workers_per_round} inner workers...")

            # Inner ThreadPoolExecutor for JARs within this round
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers_per_round, thread_name_prefix=f'JarExec_R{round_num}') as executor:
                # Check for interrupt *before* submitting tasks
                if JarTester._interrupted:
                    debug_print(f"Round {round_num}: Interrupted before submitting JAR tasks.")
                    if input_data_path and os.path.exists(input_data_path) and not CLEANUP_SUCCESSFUL_ROUNDS: # Only delete if not cleaning up passed rounds later
                        try: os.remove(input_data_path)
                        except Exception: pass
                    return None

                future_to_jar = {
                    executor.submit(JarTester._run_single_jar, jar_file, input_data_path, round_wall_time_limit, round_num): jar_file
                    for jar_file in JarTester._jar_files
                }
                debug_print(f"Round {round_num}: Submitted {len(future_to_jar)} JAR tasks.")

                completed_count = 0
                for future in concurrent.futures.as_completed(future_to_jar):
                     if JarTester._interrupted:
                         debug_print(f"Round {round_num}: Interrupted during JAR execution processing.")

                     jar_file = future_to_jar[future]
                     jar_basename = os.path.basename(jar_file)
                     try:
                         result = future.result()
                         result["round_num"] = round_num
                         results_this_round.append(result)
                         completed_count += 1
                     except concurrent.futures.CancelledError:
                          print(f"WARNING [{thread_name}] Round {round_num}: Run for {jar_basename} was cancelled (unexpected).", file=sys.stderr)
                     except Exception as exc:
                        # Log exceptions from the _run_single_jar future
                        print(f'\nERROR [{thread_name}] Round {round_num}: JAR {jar_basename} generated an unexpected exception in its execution thread: {exc}', file=sys.stderr)
                        debug_print(f"Round {round_num}: Exception from future for {jar_basename}", exc_info=True)
                        # Create a result indicating the crash
                        results_this_round.append({
                            "jar_file": jar_basename, "status": "CRASHED", "final_score": 0.0,
                            "error_details": f"Tester thread exception: {exc}", "cpu_time": 0, "wall_time": 0,
                            "t_final": None, "wt": None, "w": None, "stdout_log_path": None,
                            "stderr": [f"Tester thread exception: {exc}", traceback.format_exc()],
                            "input_data_path": input_data_path, "round_num": round_num
                        })
                        completed_count += 1


            debug_print(f"Round {round_num}: All {len(future_to_jar)} JAR executions completed or terminated.")

            # Check interrupt *after* JAR execution block finishes
            if JarTester._interrupted:
                debug_print(f"Round {round_num}: Interrupted after JAR execution completed. Skipping scoring and history update.")
                if input_data_path and os.path.exists(input_data_path) and not CLEANUP_SUCCESSFUL_ROUNDS:
                    try: os.remove(input_data_path)
                    except Exception: pass
                return None # Don't proceed to scoring/logging/history

            failed_jars_in_round = [r for r in results_this_round if r.get("status") not in ["CORRECT", "PENDING", "RUNNING", "INTERRUPTED"]]
            if failed_jars_in_round:
                # Create a unique filename for this round's errors using the seed
                error_log_filename = f"errors_{round_num}_{current_seed}.log"
                error_log_filepath = os.path.abspath(os.path.join(LOG_DIR, error_log_filename))
                debug_print(f"Round {round_num}: Failures detected. Logging errors to separate file: {error_log_filepath}")
                try:
                    # Write error details for this round to the specific file.
                    # No lock needed here, as this file is unique to this round/thread.
                    with open(error_log_filepath, "w", encoding="utf-8", errors='replace') as f_err:
                        f_err.write(f"--- Error Log for Test Round {round_num} ---\n")
                        f_err.write(f"Seed: {current_seed}\n")
                        f_err.write(f"Preset Command Used: {full_preset_cmd}\n") # Log the command with seed
                        f_err.write(f"Input Data File Path: {input_data_path if input_data_path else '<Not Available>'}\n")
                        f_err.write(f"Wall Time Limit Applied: {round_wall_time_limit:.1f}s\n")
                        f_err.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f_err.write("-" * 40 + "\n\n")

                        # Iterate only through the failing JARs for this round
                        for r in failed_jars_in_round:
                            jar_name = r.get("jar_file", "UnknownJAR")
                            status = r.get("status", "UNKNOWN")
                            f_err.write(f"--- Failing JAR: {jar_name} ---\n")
                            f_err.write(f"Status: {status}\n")
                            f_err.write(f"Error Details: {r.get('error_details', '')}\n")

                            # Log path to stdout file for this failing JAR
                            stdout_log = r.get("stdout_log_path")
                            f_err.write(f"Stdout Log File Path: {stdout_log if stdout_log else '<Not Saved or Error>'}\n")

                            # Log stderr content directly for this failing JAR
                            f_err.write("--- Stderr Content ---\n")
                            stderr = r.get("stderr", [])
                            if stderr:
                                MAX_ERR_LOG_LINES = 200 # Use a potentially larger limit for error logs
                                for i, err_line in enumerate(stderr):
                                    if i < MAX_ERR_LOG_LINES: f_err.write(f"  {err_line.strip()}\n")
                                    elif i == MAX_ERR_LOG_LINES: f_err.write(f"  ... (stderr truncated after {MAX_ERR_LOG_LINES} lines)\n"); break
                                if len(stderr) <= MAX_ERR_LOG_LINES: f_err.write("  <End of Stderr>\n")
                            else:
                                f_err.write("  <No stderr captured>\n")
                            f_err.write("--- End Stderr ---\n\n") # Add space before next failing JAR

                    # Optionally inform user on console
                    print(f"INFO [{thread_name}] Round {round_num}: Errors occurred. Details saved to {error_log_filepath}")

                except Exception as e_err_log:
                    # Log failure to write the specific error log to the main console/stderr
                    print(f"ERROR [{thread_name}] Round {round_num}: Failed to write separate error log file {error_log_filepath}: {e_err_log}", file=sys.stderr)

            # 3. Calculate Performance Scores for this round
            debug_print(f"Round {round_num}: Calculating scores...")
            JarTester._calculate_scores(results_this_round) # Modifies results_this_round in-place

            if CLEANUP_SUCCESSFUL_ROUNDS and results_this_round: # Check if flag is set and results exist
                all_passed = True
                failed_jar_outputs_to_keep = [] # Store paths of outputs from failed jars
                successful_jar_outputs_to_delete = [] # Store paths of outputs from successful jars

                for r in results_this_round:
                    status = r.get("status")
                    stdout_path = r.get("stdout_log_path")

                    if status != "CORRECT":
                        all_passed = False # Mark that not all JARs passed
                        if stdout_path and os.path.exists(stdout_path):
                            failed_jar_outputs_to_keep.append(stdout_path)
                        # Note: Even if status is not CORRECT, we still need to check others
                    else: # Status is CORRECT
                        if stdout_path and os.path.exists(stdout_path):
                            # Mark this successful output for potential deletion
                            successful_jar_outputs_to_delete.append(stdout_path)

                if all_passed:
                    # All JARs passed, delete input and ALL output files
                    files_to_remove = []
                    if input_data_path and os.path.exists(input_data_path):
                        files_to_remove.append(input_data_path)
                    # Add all successful outputs (which is all outputs in this case)
                    files_to_remove.extend(successful_jar_outputs_to_delete)

                    if files_to_remove:
                        debug_print(f"Round {round_num}: All JARs passed. Cleaning up {len(files_to_remove)} temporary files...")
                        for file_path in files_to_remove:
                            try:
                                os.remove(file_path)
                                debug_print(f"  Deleted: {file_path}")
                            except OSError as e: # Catch potential OS errors like permission denied
                                print(f"WARNING [{threading.current_thread().name}] Round {round_num}: Failed to delete temp file {file_path}: {e}", file=sys.stderr)
                            except Exception as e: # Catch any other unexpected errors
                                print(f"WARNING [{threading.current_thread().name}] Round {round_num}: Unexpected error deleting temp file {file_path}: {e}", file=sys.stderr)
                else:
                    # At least one JAR failed. Keep the input file. Keep outputs of failed JARs. Delete outputs of successful JARs.
                    if successful_jar_outputs_to_delete: # Only cleanup if there were successful ones
                        debug_print(f"Round {round_num}: Some JARs failed. Keeping input file and {len(failed_jar_outputs_to_keep)} failed outputs. Cleaning up {len(successful_jar_outputs_to_delete)} successful outputs...")
                        for file_path in successful_jar_outputs_to_delete:
                            try:
                                os.remove(file_path)
                                debug_print(f"  Deleted (successful output): {file_path}")
                            except OSError as e:
                                print(f"WARNING [{threading.current_thread().name}] Round {round_num}: Failed to delete temp file {file_path}: {e}", file=sys.stderr)
                            except Exception as e:
                                print(f"WARNING [{threading.current_thread().name}] Round {round_num}: Unexpected error deleting temp file {file_path}: {e}", file=sys.stderr)
                    else:
                        debug_print(f"Round {round_num}: Some JARs failed, but no successful outputs found/exist to cleanup.")

                # Optional: Add a debug message if input is being kept due to failures
                if not all_passed and input_data_path and os.path.exists(input_data_path):
                    debug_print(f"  Keeping input file (due to failures): {input_data_path}")

            # Prepare results package to return
            round_results = {
                "round_num": round_num,
                "results": results_this_round,
                "preset_cmd": full_preset_cmd, # Use command with seed
                "input_path": input_data_path,
                "wall_limit": round_wall_time_limit
            }

            print(f"INFO [{thread_name}]: Finished Test Round {round_num} ({selected_preset_cmd})")
            return round_results # Return the processed results

        except Exception as e_round:
            # Catch unexpected errors within the round execution logic itself
            print(f"\nFATAL ERROR in worker thread for Round {round_num}: {e_round}", file=sys.stderr)
            debug_print(f"Fatal error in _run_one_round {round_num}", exc_info=True)
            # Log the error (using the log lock)
            if JarTester._log_file_path:
                try:
                    with JarTester._log_lock:
                        with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                            f.write(f"\n\n!!! FATAL WORKER ERROR (Round {round_num}) !!!\n")
                            f.write(f"Thread: {thread_name}\n")
                            f.write(f"Preset: {selected_preset_cmd}\n")
                            f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                            f.write(f"Error: {e_round}\n")
                            traceback.print_exc(file=f)
                            f.write("\n")
                except Exception as e_log_fatal:
                    print(f"ERROR [{thread_name}] Round {round_num}: Also failed to log fatal worker error: {e_log_fatal}", file=sys.stderr)
            # Clean up input file if it exists
            if input_data_path and os.path.exists(input_data_path):
                if not CLEANUP_SUCCESSFUL_ROUNDS:
                    try: os.remove(input_data_path)
                    except Exception: pass
                else:
                    debug_print(f"Round {round_num}: Worker exception occurred, preserving input file {input_data_path} despite cleanup mode.")
            return None # Indicate round failed

    # --- Main test method modified for parallel rounds ---
    @staticmethod
    def test(): # Added parallel_rounds
        """Main testing entry point, runs multiple rounds in parallel."""
        global ENABLE_DETAILED_DEBUG, LOG_DIR, TMP_DIR, CLEANUP_SUCCESSFUL_ROUNDS
        start_time_main = time.monotonic()
        config = None
        try:
            # --- Initialization ---
            config_path = 'config.yml'
            print(f"INFO: Loading configuration from {config_path}...")
            if not os.path.exists(config_path):
                print(f"ERROR: Configuration file '{config_path}' not found.", file=sys.stderr)
                return
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            if not config:
                print(f"ERROR: Configuration file '{config_path}' is empty or invalid.", file=sys.stderr)
                return
            hw_n = config.get('hw')
            jar_base_dir = config.get('jar_base_dir')
            logs_dir_config = config.get('logs_dir', 'logs') # Default if missing
            tmp_dir_config = config.get('tmp_dir', 'tmp')     # Default if missing
            test_config = config.get('test', {})
            hce_filter_enabled = test_config.get('hce', False) # Default False if missing
            parallel_rounds_config = test_config.get('parallel', DEFAULT_PARALLEL_ROUNDS) # Use default
            debug_enabled_config = test_config.get('debug', False) # Default False
            cleanup_enabled_config = test_config.get('cleanup', False) # Default False

            if hw_n is None or not isinstance(hw_n, int):
                print(f"ERROR: 'hw' value missing or invalid in {config_path}.", file=sys.stderr)
                return
            if not jar_base_dir or not isinstance(jar_base_dir, str):
                print(f"ERROR: 'jar_base_dir' value missing or invalid in {config_path}.", file=sys.stderr)
                return
            if not isinstance(parallel_rounds_config, int) or parallel_rounds_config < 1:
                print(f"WARNING: 'test.parallel' value invalid in {config_path}. Using default: {DEFAULT_PARALLEL_ROUNDS}.", file=sys.stderr)
                parallel_rounds_config = DEFAULT_PARALLEL_ROUNDS

            ENABLE_DETAILED_DEBUG = bool(debug_enabled_config)
            LOG_DIR = logs_dir_config
            TMP_DIR = tmp_dir_config
            CLEANUP_SUCCESSFUL_ROUNDS = bool(cleanup_enabled_config)

            # Update debug status immediately if changed
            if ENABLE_DETAILED_DEBUG:
                debug_print("Detailed debugging enabled via config.")
            if CLEANUP_SUCCESSFUL_ROUNDS:
                debug_print("Cleanup mode enabled via config.")

            # Calculate hw_n_path based on hw_n
            m = hw_n // 4 + 1
            hw_n_str = os.path.join(f"unit_{m}", f"hw_{hw_n}")

            JarTester._jar_dir = jar_base_dir
            JarTester._gen_script_path = os.path.abspath(os.path.join(hw_n_str, "gen.py"))
            JarTester._checker_script_path = os.path.abspath(os.path.join(hw_n_str, "checker.py"))

            JarTester._loaded_preset_commands = [] # Reset before loading
            gen_dir = os.path.dirname(JarTester._gen_script_path)
            presets_yaml_path = os.path.abspath(os.path.join(gen_dir, "gen_presets.yml"))

            try:
                print(f"INFO: Loading generator presets from {presets_yaml_path}...")
                if not os.path.exists(presets_yaml_path):
                    print(f"ERROR: Generator presets file '{presets_yaml_path}' not found.", file=sys.stderr)
                    return # Abort if presets are missing
                with open(presets_yaml_path, 'r', encoding='utf-8') as f_presets:
                    loaded_presets = yaml.safe_load(f_presets)

                if not isinstance(loaded_presets, list):
                    print(f"ERROR: Content of '{presets_yaml_path}' is not a valid YAML list.", file=sys.stderr)
                    return # Abort if format is wrong
                # Basic validation: ensure all items are strings
                if not all(isinstance(item, str) for item in loaded_presets):
                    print(f"ERROR: Not all items in '{presets_yaml_path}' are strings. Each preset must be a string.", file=sys.stderr)
                    return # Abort if items aren't strings

                JarTester._loaded_preset_commands = loaded_presets
                print(f"INFO: Successfully loaded {len(JarTester._loaded_preset_commands)} generator presets.")

            except yaml.YAMLError as e_yaml:
                print(f"ERROR: Failed to parse generator presets file '{presets_yaml_path}': {e_yaml}", file=sys.stderr)
                return # Abort on parse error
            except Exception as e_load:
                print(f"ERROR: Unexpected error loading generator presets file '{presets_yaml_path}': {e_load}", file=sys.stderr)
                return # Abort on other errors

            JarTester._interrupted = False
            JarTester._round_counter = 0 # Reset counter
            JarTester._all_results_history.clear()

            os.makedirs(LOG_DIR, exist_ok=True)
            os.makedirs(TMP_DIR, exist_ok=True)
            local_time = time.localtime()
            formatted_time = time.strftime("%Y-%m-%d-%H-%M-%S", local_time)
            JarTester._log_file_path = os.path.abspath(os.path.join(LOG_DIR, f"{formatted_time}_elevator_run.log"))

            print(f"INFO: Homework target: {hw_n_str}")
            print(f"INFO: JAR directory: {JarTester._jar_dir}")
            print(f"INFO: Logging round summaries and errors to {JarTester._log_file_path}")
            print(f"INFO: Storing temporary input/output files in {os.path.abspath(TMP_DIR)}")
            print(f"INFO: Running up to {parallel_rounds_config} test rounds concurrently.")

            if hce_filter_enabled:
                print("INFO: HCE filter enabled. Removing non-HCE presets...")
                original_count = len(JarTester._loaded_preset_commands)
                # Filter the global list directly before it's used by _initialize_presets
                JarTester._loaded_preset_commands = [cmd for cmd in JarTester._loaded_preset_commands if "--hce" in cmd]
                filtered_count = len(JarTester._loaded_preset_commands)
                print(f"INFO: Filtered presets: {original_count} -> {filtered_count}")
                if filtered_count == 0:
                    print("ERROR: HCE filtering resulted in zero presets. Cannot continue.", file=sys.stderr)
                    return

            if not os.path.exists(JarTester._gen_script_path): print(f"ERROR: Generator script not found: {JarTester._gen_script_path}", file=sys.stderr); return
            if not os.path.exists(JarTester._checker_script_path): print(f"ERROR: Checker script not found: {JarTester._checker_script_path}", file=sys.stderr); return
            if not JarTester._find_jar_files(): print("ERROR: No JAR files found or accessible. Aborting.", file=sys.stderr); return

            if not JarTester._initialize_presets():
                print("ERROR: Failed to initialize/parse presets after loading. Aborting.", file=sys.stderr)
                return

            signal.signal(signal.SIGINT, JarTester._signal_handler)
            print(f"Press Ctrl+C to stop testing gracefully after running rounds finish.")

            print("\n" + "="*40)
            if not ENABLE_DETAILED_DEBUG: 
                input("Setup complete. Press Enter to begin testing...")
                # JarTester._clear_screen() # Clear after Enter
                print("="*40 + "\n")

            # --- Main Parallel Round Execution Loop ---
            active_futures = set()
            processed_round_count = 0
            max_rounds = None # Run indefinitely until Ctrl+C unless set

            # Outer ThreadPoolExecutor for managing rounds
            with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_rounds_config, thread_name_prefix='RoundRunner') as round_executor:
                while not JarTester._interrupted:
                    # Submit new rounds if below the parallel limit and not interrupted
                    while len(active_futures) < parallel_rounds_config and not JarTester._interrupted:
                        round_num = JarTester._get_next_round_number()
                        debug_print(f"MainLoop: Submitting round {round_num}")
                        future = round_executor.submit(JarTester._run_one_round, round_num)
                        active_futures.add(future)

                    # If interrupted, break submission loop
                    if JarTester._interrupted:
                         debug_print("MainLoop: Interrupt detected, stopping submission.")
                         break

                    # Wait for at least one round to complete
                    debug_print(f"MainLoop: Waiting for completed rounds (Active: {len(active_futures)})...")
                    done, active_futures = concurrent.futures.wait(active_futures, return_when=concurrent.futures.FIRST_COMPLETED)
                    debug_print(f"MainLoop: {len(done)} round(s) completed.")

                    # Process completed rounds
                    for future in done:
                        try:
                            round_result_package = future.result()
                            processed_round_count += 1

                            if round_result_package:
                                # 4. Display/Log Results for the completed round
                                debug_print(f"MainLoop: Processing results for round {round_result_package['round_num']}...")
                                JarTester._display_and_log_results(
                                    round_result_package["round_num"],
                                    round_result_package["results"],
                                    round_result_package["preset_cmd"],
                                    round_result_package["input_path"],
                                    round_result_package["wall_limit"]
                                )

                                # 5. Update Historical Data (if round was successful)
                                if not JarTester._interrupted: # Check again before history update
                                    debug_print(f"MainLoop: Updating history for round {round_result_package['round_num']}...")
                                    JarTester._update_history(round_result_package["results"])
                                else:
                                    debug_print(f"MainLoop: Skipping history update for round {round_result_package['round_num']} due to interrupt.")

                            else:
                                # Round failed to execute (e.g., gen failed, worker error)
                                # Error message should have been printed/logged by the worker
                                debug_print(f"MainLoop: Round failed to return results (error logged previously).")

                        except Exception as exc:
                            # Catch errors from the future.result() call itself
                            print(f'\nERROR: Main loop caught exception processing a round future: {exc}', file=sys.stderr)
                            debug_print("Exception processing round future", exc_info=True)
                            processed_round_count += 1 # Count it as processed (though failed)

                    # Brief sleep to prevent tight looping if rounds finish instantly (unlikely)
                    # time.sleep(0.1)

                # --- End of main loop (interrupted or finished) ---
                print("\nMainLoop: Exited main execution loop.")
                if JarTester._interrupted:
                    print("MainLoop: Interrupt received. Waiting for remaining active rounds to complete...")
                    # Futures in 'active_futures' are still running
                    # Wait for them to finish naturally (they check the _interrupted flag)
                    if active_futures:
                        concurrent.futures.wait(active_futures) # Wait for all remaining
                    print("MainLoop: All active rounds have finished after interrupt.")
                else:
                    print("MainLoop: Finished normally.") # Or based on max_rounds condition if implemented

            # --- End of outer executor block ---

        except Exception as e:
            # Catch errors in the main setup or loop management
            print(f"\nFATAL ERROR in main testing thread: {e}", file=sys.stderr)
            debug_print("Fatal error in main test execution", exc_info=True)
            if JarTester._log_file_path:
                 try:
                     # Use log lock for safety, though main thread shouldn't conflict often
                     with JarTester._log_lock:
                         with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                             f.write(f"\n\n!!! FATAL MAIN TESTER ERROR !!!\n{time.strftime('%Y-%m-%d %H:%M:%S')}\nError: {e}\n")
                             traceback.print_exc(file=f)
                 except Exception as e_log_main_fatal:
                      print(f"ERROR: Also failed to log fatal main error: {e_log_main_fatal}", file=sys.stderr)

        finally:
            # --- Final Summary ---
            print("\nCalculating final summary...")
            summary = JarTester._print_summary() # Reads history (needs lock internally)
            print(summary)
            if JarTester._log_file_path:
                try:
                     # Use log lock for final summary write
                     with JarTester._log_lock:
                        with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                            f.write("\n\n" + "="*20 + " FINAL SUMMARY " + "="*20 + "\n") # Add separator
                            f.write(summary + "\n")
                            f.write("="* (40 + len(" FINAL SUMMARY ")) + "\n")
                        debug_print("Final summary also written to log file.")
                except Exception as e_log_summary:
                    print(f"ERROR: Failed to write final summary to log file {JarTester._log_file_path}: {e_log_summary}", file=sys.stderr)

            # --- Cleanup --- Optional TMP dir cleanup
            # try:
            #     if os.path.exists(TMP_DIR):
            #         print(f"\nTemporary files are in: {os.path.abspath(TMP_DIR)}")
            #         # Consider making cleanup automatic or controlled by an arg
            #         # response = input("Delete temporary directory? (y/N): ")
            #         # if response.lower() == 'y':
            #         #     print(f"INFO: Cleaning up temporary directory: {os.path.abspath(TMP_DIR)}")
            #         #     shutil.rmtree(TMP_DIR)
            # except Exception as e_clean:
            #     print(f"WARNING: Failed to clean up temporary directory {TMP_DIR}: {e_clean}", file=sys.stderr)

            end_time_main = time.monotonic()
            print(f"\nTotal execution time: {end_time_main - start_time_main:.2f} seconds.")
