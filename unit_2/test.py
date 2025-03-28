# --- START OF FILE test.py ---

# tester.py
import os
import sys
import subprocess
import time
import signal
import threading
import queue
import argparse
import tempfile
import psutil
import re
from collections import defaultdict
import numpy as np
import concurrent.futures

# --- Configuration ---
CPU_TIME_LIMIT = 10.0  # seconds
WALL_TIME_LIMIT = 120.0 # seconds
CHECKER_TMAX = WALL_TIME_LIMIT
DEFAULT_GEN_ARGS = {
    "hce": True,
    "num_requests": 70,
    "max_time": 50,
    "extreme_floor_ratio": 0.5,
    "burst_size": 15,
    "focus_elevator": 2,
    "priority_bias": "extremes"
}
PERF_P_VALUE = 0.10
ENABLE_DETAILED_DEBUG = False # Set to True for verbose debugging
LOG_DIR = "logs" # Define log directory constant

# Helper function for conditional debug printing
def debug_print(*args, **kwargs):
    if ENABLE_DETAILED_DEBUG:
        print(f"DEBUG [{time.time():.4f}]:", *args, **kwargs, file=sys.stderr, flush=True)

class JarTester:
    _jar_files = []
    _finder_executed = False
    _jar_dir = ""
    _gen_script_path = ""
    _checker_script_path = ""
    _interrupted = False
    _test_count = 0
    _log_file_path = None
    _persistent_request_file_path = None # Added: Path for persistent request data
    _all_results_history = defaultdict(lambda: {'correct_runs': 0, 'total_runs': 0, 'scores': []})

    # --- Helper: Clear Screen ---
    @staticmethod
    def _clear_screen():
        """Clears the terminal screen."""
        if ENABLE_DETAILED_DEBUG:
            return
        if os.name == 'nt':  # Windows
            os.system('cls')
        else:  # macOS, Linux, Unix
            os.system('clear')

    @staticmethod
    def _find_jar_files():
        """Search for JAR files in the specified directory"""
        # (No changes needed here)
        if not JarTester._finder_executed:
            try:
                JarTester._jar_dir = os.path.abspath(JarTester._jar_dir) # Use absolute path
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
    def _kill_process_tree(pid):
        """Recursively terminate a process and its children."""
        # (No changes needed here)
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            debug_print(f"PID {pid} has children: {[c.pid for c in children]}")
            for child in children:
                try:
                    debug_print(f"Terminating child PID {child.pid}")
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass # Child already exited
            debug_print(f"Terminating parent PID {pid}")
            parent.terminate()
            # Wait a bit for termination to propagate
            gone, alive = psutil.wait_procs(children + [parent], timeout=1.0)
            debug_print(f"After terminate: Gone={[(p.pid if hasattr(p,'pid') else '?') for p in gone]}, \
                        Alive={[(p.pid if hasattr(p,'pid') else '?') for p in alive]}")
            for p in alive:
                try:
                    debug_print(f"Killing remaining process PID {p.pid}")
                    p.kill()
                except psutil.NoSuchProcess:
                    pass # Process finally exited
        except psutil.NoSuchProcess:
            debug_print(f"Process PID {pid} already gone before kill attempt.")
        except Exception as e:
            print(f"ERROR: Exception during process termination for PID {pid}: {e}", file=sys.stderr)

    @staticmethod
    def _timed_input_feeder(process, requests, start_event, error_flag):
        """Thread function to feed input to the JAR process at specific times."""
        # (No changes needed here)
        pid = process.pid # Get pid early for logging
        debug_print(f"Input feeder started for PID {pid}")
        try:
            debug_print(f"Input feeder waiting for start event for PID {pid}")
            start_event.wait()
            debug_print(f"Input feeder received start event for PID {pid}")
            start_mono_time = time.monotonic()

            request_count = len(requests)
            for i, (req_time, req_data) in enumerate(requests):
                if error_flag.is_set() or JarTester._interrupted:
                    debug_print(f"Input feeder stopping early for PID {pid} (error or interrupt)")
                    break

                current_mono_time = time.monotonic()
                elapsed_time = current_mono_time - start_mono_time
                sleep_duration = req_time - elapsed_time

                if sleep_duration > 0:
                    debug_print(f"Input feeder sleeping for {sleep_duration:.4f}s for PID {pid}")
                    sleep_end_time = time.monotonic() + sleep_duration
                    while time.monotonic() < sleep_end_time:
                        if error_flag.is_set() or JarTester._interrupted:
                            debug_print(f"Input feeder woken early from sleep for PID {pid} (error or interrupt)")
                            return
                        check_interval = min(0.1, sleep_end_time - time.monotonic())
                        if check_interval > 0: time.sleep(check_interval)

                if error_flag.is_set() or JarTester._interrupted:
                    debug_print(f"Input feeder stopping after sleep for PID {pid} (error or interrupt)")
                    break

                try:
                    debug_print(f"Input feeder feeding request {i+1}/{request_count} to PID {pid}: {req_data}")
                    process.stdin.write(req_data + '\n')
                    process.stdin.flush()
                except (BrokenPipeError, OSError) as e:
                    if not error_flag.is_set() and not JarTester._interrupted:
                        print(f"WARNING: Input feeder: Pipe broken or OS error for PID {pid}. Error: {e}", file=sys.stderr)
                        debug_print(f"Input feeder: Pipe broken/OS error detected for PID {pid}")
                    error_flag.set()
                    break
                except Exception as e:
                    print(f"ERROR: Input feeder: Unexpected error writing to PID {pid}: {e}", file=sys.stderr)
                    debug_print(f"Input feeder: Exception during write for PID {pid}", exc_info=True)
                    error_flag.set()
                    break

            debug_print(f"Input feeder finished loop for PID {pid}. Error={error_flag.is_set()}, Interrupt={JarTester._interrupted}")

            if not error_flag.is_set() and not JarTester._interrupted:
                try:
                    debug_print(f"Input feeder closing stdin for PID {pid}")
                    process.stdin.close()
                    debug_print(f"Input feeder successfully closed stdin for PID {pid}")
                except (BrokenPipeError, OSError):
                    debug_print(f"Input feeder: Pipe already closed or OS error during stdin close for PID {pid}")
                except Exception as e:
                    print(f"ERROR: Input feeder: Error closing stdin for PID {pid}: {e}", file=sys.stderr)
                    debug_print(f"Input feeder: Exception during stdin close for PID {pid}", exc_info=True)
            else:
                debug_print(f"Input feeder skipping stdin close due to error/interrupt for PID {pid}")


        except Exception as e:
            print(f"FATAL: Input feeder thread crashed for PID {pid}: {e}", file=sys.stderr)
            debug_print(f"Input feeder thread exception for PID {pid}", exc_info=True)
            error_flag.set()
        finally:
            debug_print(f"Input feeder thread exiting for PID {pid}")

    @staticmethod
    def _output_reader(pipe, output_queue, stream_name, pid, error_flag):
        # (No changes needed here)
        debug_print(f"Output reader ({stream_name}) started for PID {pid}")
        try:
            for line_num, line in enumerate(iter(pipe.readline, '')):
                if error_flag.is_set() or JarTester._interrupted:
                     debug_print(f"Output reader ({stream_name}) stopping early for PID {pid}")
                     break
                # debug_print(f"Output reader ({stream_name}) read line {line_num} for PID {pid}: {line.strip()}")
                output_queue.put(line)
            debug_print(f"Output reader ({stream_name}) finished iter loop for PID {pid}")
        except ValueError:
            if not error_flag.is_set() and not JarTester._interrupted:
                 print(f"WARNING: Output reader ({stream_name}) for PID {pid}: ValueError (Pipe likely closed).", file=sys.stderr)
                 debug_print(f"Output reader ({stream_name}) caught ValueError for PID {pid}")
        except Exception as e:
            print(f"ERROR: Output reader ({stream_name}) thread crashed for PID {pid}: {e}", file=sys.stderr)
            debug_print(f"Output reader ({stream_name}) thread exception for PID {pid}", exc_info=True)
            error_flag.set()
        finally:
            try:
                debug_print(f"Output reader ({stream_name}) closing pipe for PID {pid}")
                pipe.close()
            except Exception: pass
            debug_print(f"Output reader ({stream_name}) thread exiting for PID {pid}")

    @staticmethod
    def _run_single_jar(jar_path, requests_data, gen_output_path):
        jar_basename = os.path.basename(jar_path) # For logging
        debug_print(f"Starting run for JAR: {jar_basename}")
        start_wall_time = time.monotonic()
        process = None
        pid = -1
        ps_proc = None # Initialize ps_proc
        result = { # Initialize fully, including score metrics
            "jar_file": jar_basename, "cpu_time": 0.0, "wall_time": 0.0,
            "status": "PENDING", "error_details": "", "stdout": [], "stderr": [],
            "t_final": None, "wt": None, "w": None, "final_score": 0.0,
        }
        input_feeder_thread = None
        stdout_reader_thread = None
        stderr_reader_thread = None
        stdout_queue = queue.Queue()
        stderr_queue = queue.Queue()
        feeder_start_event = threading.Event()
        error_flag = threading.Event()

        try:
            # 1. Start Process (Same as before)
            debug_print(f"Launching JAR: {jar_basename}")
            process = subprocess.Popen( # Ensure utf-8 for Java communication
                ['java', '-jar', jar_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', bufsize=1 # Line buffered
            )
            pid = process.pid
            debug_print(f"JAR {jar_basename} launched with PID {pid}")
            result["status"] = "RUNNING"
            try:
                ps_proc = psutil.Process(pid)
                debug_print(f"Attached psutil to PID {pid}")
            except psutil.NoSuchProcess as e_attach:
                # ... (handling immediate disappearance remains the same) ...
                print(f"ERROR: Process {pid} ({jar_basename}) disappeared immediately after launch.", file=sys.stderr)
                debug_print(f"psutil attach failed for PID {pid}", exc_info=True)
                result["status"] = "CRASHED"
                result["error_details"] = f"Process disappeared immediately: {e_attach}"
                error_flag.set()
                raise e_attach # Re-raise to jump to the outer finally block

            # 2. Start I/O Threads (Same as before)
            debug_print(f"Starting I/O threads for PID {pid}")
            input_feeder_thread = threading.Thread(target=JarTester._timed_input_feeder, args=(process, requests_data, feeder_start_event, error_flag), daemon=True)
            stdout_reader_thread = threading.Thread(target=JarTester._output_reader, args=(process.stdout, stdout_queue, "stdout", pid, error_flag), daemon=True)
            stderr_reader_thread = threading.Thread(target=JarTester._output_reader, args=(process.stderr, stderr_queue, "stderr", pid, error_flag), daemon=True)
            input_feeder_thread.start()
            stdout_reader_thread.start()
            stderr_reader_thread.start()

            # 3. Monitoring Loop
            debug_print(f"Starting monitoring loop for PID {pid}")
            monitor_loops = 0
            process_exited_normally = False # Flag to track clean exit
            while True: # Rely on internal breaks
                monitor_loops += 1
                if not feeder_start_event.is_set(): feeder_start_event.set() # Signal feeder if not already done

                # --- Check Process Status FIRST ---
                try:
                    if not ps_proc.is_running():
                        debug_print(f"Monitor loop {monitor_loops}: ps_proc.is_running() is False for PID {pid}. Breaking.")
                        # --- MODIFICATION: Set process_exited_normally flag HERE ---
                        if not error_flag.is_set() and not JarTester._interrupted:
                            debug_print(f"Monitor loop {monitor_loops}: Process {pid} detected as not running. Setting exitedNormally=True.")
                            process_exited_normally = True
                        # ---------------------------------------------------------
                        break # Exit monitoring loop
                except psutil.NoSuchProcess:
                    # This handles cases where the process disappears *before* or *between* is_running() checks
                    debug_print(f"Monitor loop {monitor_loops}: psutil.NoSuchProcess caught checking is_running() for PID {pid}. Breaking.")
                    if not error_flag.is_set() and not JarTester._interrupted:
                        print(f"WARNING: Monitor loop: Process {pid} ({jar_basename}) disappeared unexpectedly (is_running check).", file=sys.stderr)
                        result["status"] = "CRASHED" # Mark as crashed here
                        result["error_details"] = "Process disappeared during monitoring (is_running check)."
                    error_flag.set() # Signal threads
                    break # Exit monitoring loop

                # --- Check for External Stop Signals --- (Same as before)
                if error_flag.is_set():
                    debug_print(f"Monitor loop {monitor_loops}: Error flag is set for PID {pid}. Breaking.")
                    break
                if JarTester._interrupted:
                    debug_print(f"Monitor loop {monitor_loops}: Global interrupt flag is set. Breaking.")
                    if result["status"] not in ["TLE", "CTLE", "CRASHED"]: # Don't overwrite a specific error
                        result["status"] = "INTERRUPTED"
                        result["error_details"] = "Run interrupted by user (Ctrl+C)."
                    error_flag.set() # Signal threads
                    break

                # --- Check Resource Limits ---
                current_wall_time = time.monotonic() - start_wall_time
                current_cpu_time = result["cpu_time"] # Use last known good value as default
                try:
                    # Attempt to get current CPU times
                    cpu_times = ps_proc.cpu_times()
                    current_cpu_time = cpu_times.user + cpu_times.system
                # --- MODIFICATION START: Handle NoSuchProcess during cpu_times() ---
                except psutil.NoSuchProcess:
                    # Process disappeared between is_running() and cpu_times() check.
                    # This is likely a clean exit caught by the race condition.
                    # Do NOT mark as CRASHED here. Simply break the loop.
                    # The exit code will be checked later.
                    debug_print(f"Monitor loop {monitor_loops}: NoSuchProcess getting CPU times for PID {pid}. Likely exited cleanly. Breaking monitor loop.")
                    # Set the flag indicating we detected exit here
                    if not error_flag.is_set() and not JarTester._interrupted:
                        process_exited_normally = True
                    break # Exit monitoring loop
                # --- MODIFICATION END ---
                except Exception as e_cpu: # Catch other potential psutil errors
                    print(f"ERROR: Monitor loop: Unexpected error getting CPU times for PID {pid}: {e_cpu}", file=sys.stderr)
                    debug_print(f"Monitor loop {monitor_loops}: psutil error getting CPU times for PID {pid}", exc_info=True)
                    if result["status"] not in ["CRASHED", "TLE", "CTLE", "INTERRUPTED"]: # Avoid overwriting existing error
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Tester error getting CPU time: {e_cpu}"
                    error_flag.set()
                    break

                # Update results only if CPU time was successfully retrieved
                result["cpu_time"] = current_cpu_time
                result["wall_time"] = current_wall_time

                # Check limits (Same as before)
                if current_cpu_time > CPU_TIME_LIMIT:
                    debug_print(f"Monitor loop {monitor_loops}: CTLE for PID {pid}")
                    print(f"INFO: Process {pid} ({jar_basename}) exceeded CPU time limit ({current_cpu_time:.2f}s > {CPU_TIME_LIMIT:.2f}s). Terminating.", file=sys.stderr)
                    result["status"] = "CTLE"
                    result["error_details"] = f"CPU time {current_cpu_time:.2f}s exceeded limit {CPU_TIME_LIMIT:.2f}s."
                    error_flag.set()
                    break

                if current_wall_time > WALL_TIME_LIMIT:
                    debug_print(f"Monitor loop {monitor_loops}: TLE for PID {pid}")
                    print(f"INFO: Process {pid} ({jar_basename}) exceeded wall time limit ({current_wall_time:.2f}s > {WALL_TIME_LIMIT:.2f}s). Terminating.", file=sys.stderr)
                    result["status"] = "TLE"
                    result["error_details"] = f"Wall time {current_wall_time:.2f}s exceeded limit {WALL_TIME_LIMIT:.2f}s."
                    error_flag.set()
                    break

                time.sleep(0.05) # Same loop delay

            # --- End of Monitoring Loop ---
            debug_print(f"Exited monitoring loop for PID {pid} after {monitor_loops} iterations. Status: {result['status']}, ExitedNormally: {process_exited_normally}")

            # Ensure process is terminated if an error occurred or limit exceeded
            if error_flag.is_set() and pid != -1:
                debug_print(f"Error flag set or limit exceeded, ensuring process tree killed for PID {pid}")
                # Check if process still exists before killing
                try:
                    if psutil.pid_exists(pid):
                        JarTester._kill_process_tree(pid)
                    else:
                        debug_print(f"Process {pid} already gone before kill attempt after loop exit.")
                except Exception as e_kill_loop:
                    print(f"WARNING: Error during kill attempt after loop exit for PID {pid}: {e_kill_loop}", file=sys.stderr)


            # --- Wait for I/O Threads (Same as before) ---
            debug_print(f"Waiting for I/O threads to finish for PID {pid}")
            thread_join_timeout = 1.0 # Slightly longer join timeout
            if input_feeder_thread: input_feeder_thread.join(timeout=thread_join_timeout)
            if stdout_reader_thread: stdout_reader_thread.join(timeout=thread_join_timeout)
            if stderr_reader_thread: stderr_reader_thread.join(timeout=thread_join_timeout)
            debug_print(f"Finished waiting for I/O threads for PID {pid}")

            # Determine if a final status (like TLE/CTLE/CRASHED/INTERRUPTED) was already set
            final_status_determined = result["status"] not in ["RUNNING", "PENDING"]

            # Update final times (Same as before)
            result["wall_time"] = time.monotonic() - start_wall_time
            try:
                # Update CPU time one last time if process still exists somehow (unlikely after kill)
                # or use the last value recorded before exit/kill
                if psutil.pid_exists(pid):
                    result["cpu_time"] = sum(psutil.Process(pid).cpu_times())
            except psutil.NoSuchProcess: pass # Use last recorded time if process gone

            # --- Check Exit Code if process exited normally and no error status set yet ---
            # This block now correctly handles the case where the loop broke due to NoSuchProcess on cpu_times()
            if process_exited_normally and not final_status_determined:
                debug_print(f"Process {pid} exited normally (flag is True). Getting final state and exit code.")
                exit_code = None
                try:
                    # Get exit code - should return immediately as process is known to be gone
                    exit_code = process.wait(timeout=0.5)
                    debug_print(f"Process {pid} wait() returned exit code: {exit_code}")
                    if exit_code != 0:
                        # This is a genuine crash (non-zero exit)
                        print(f"WARNING: Process {pid} ({jar_basename}) exited with non-zero code: {exit_code}.", file=sys.stderr)
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Exited with code {exit_code}."
                        final_status_determined = True
                    # If exit code is 0, status remains RUNNING (or PENDING if it never ran) for checker phase
                    # No need to change status here if exit code is 0

                except subprocess.TimeoutExpired:
                    # Should be very unlikely if process_exited_normally is True
                    print(f"WARNING: Timeout waiting for exit code for PID {pid}, which should have exited.", file=sys.stderr)
                    # Force kill just in case, although it should be gone
                    try: JarTester._kill_process_tree(pid)
                    except Exception: pass
                    if not final_status_determined: # Check again before overwriting
                        result["status"] = "CRASHED"
                        result["error_details"] = "Process did not report exit code after finishing."
                        final_status_determined = True
                except Exception as e_final:
                    print(f"WARNING: Error getting final state for PID {pid}: {e_final}", file=sys.stderr)
                    debug_print(f"Exception getting final state for PID {pid}", exc_info=True)
                    if not final_status_determined: # Check again
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Error getting final process state: {e_final}"
                        final_status_determined = True

        except (psutil.NoSuchProcess) as e_outer:
            debug_print(f"Outer exception handler: NoSuchProcess for PID {pid} ({jar_basename}). Handled.")
            if result["status"] not in ["CRASHED", "TLE", "CTLE", "INTERRUPTED"]: # Don't overwrite specific error
                result["status"] = "CRASHED"
                result["error_details"] = f"Process disappeared: {e_outer}"
            error_flag.set() # Ensure threads stop
        except FileNotFoundError:
            print(f"ERROR: Java executable or JAR file '{jar_path}' not found.", file=sys.stderr)
            debug_print(f"Outer exception handler: FileNotFoundError for JAR {jar_basename}.")
            result["status"] = "CRASHED"
            result["error_details"] = f"File not found (Java or JAR)."
            error_flag.set()
        except Exception as e:
            print(f"FATAL: Error during execution of {jar_basename} (PID {pid}): {e}", file=sys.stderr)
            debug_print(f"Outer exception handler: Unexpected exception for PID {pid}", exc_info=True)
            result["status"] = "CRASHED"
            result["error_details"] = f"Tester execution error: {e}"
            error_flag.set()
            if pid != -1 and process and process.poll() is None:
                debug_print(f"Outer exception: Ensuring PID {pid} is killed.")
                JarTester._kill_process_tree(pid)

        finally:
            # --- Cleanup and Output Collection ---
            debug_print(f"Entering finally block for PID {pid}. Status: {result['status']}")
            if pid != -1 and process and process.poll() is None: # Check PID existence too
                try:
                    if psutil.pid_exists(pid):
                        print(f"WARNING: Final cleanup: Process {pid} still alive? Killing.", file=sys.stderr)
                        debug_print(f"Final cleanup killing PID {pid}")
                        JarTester._kill_process_tree(pid)
                    else: debug_print(f"Final cleanup: Process {pid} already gone.")
                except Exception as e_kill:
                    print(f"ERROR: Exception during final kill for PID {pid}: {e_kill}", file=sys.stderr)

            debug_print(f"Draining output queues for PID {pid}")
            stdout_lines = []
            stderr_lines = []
            while not stdout_queue.empty(): stdout_lines.append(stdout_queue.get_nowait())
            while not stderr_queue.empty(): stderr_lines.append(stderr_queue.get_nowait())
            result["stdout"] = stdout_lines
            result["stderr"] = stderr_lines
            debug_print(f"Drained queues for PID {pid}. stdout lines: {len(stdout_lines)}, stderr lines: {len(stderr_lines)}")

            debug_print(f"Final join for threads of PID {pid}")
            if input_feeder_thread and input_feeder_thread.is_alive(): input_feeder_thread.join(timeout=0.1)
            if stdout_reader_thread and stdout_reader_thread.is_alive(): stdout_reader_thread.join(timeout=0.1)
            if stderr_reader_thread and stderr_reader_thread.is_alive(): stderr_reader_thread.join(timeout=0.1)
            debug_print(f"Exiting finally block for PID {pid}")


        # 4. Run Checker (only if status is still RUNNING after monitor loop/final checks)
        #    Also skip if globally interrupted
        if result["status"] == "RUNNING" and not JarTester._interrupted:
            debug_print(f"Running checker for {jar_basename} (PID {pid}) because status is RUNNING")
            output_content = "".join(result["stdout"])
            temp_output_file = None
            try:
                # Use temp file for checker input (JAR output)
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt", encoding='utf-8') as tf:
                    tf.write(output_content)
                    temp_output_file = tf.name
                debug_print(f"Checker using input(gen) '{gen_output_path}' and output(jar) '{temp_output_file}'")

                checker_proc = subprocess.run(
                    [sys.executable, JarTester._checker_script_path, gen_output_path, temp_output_file, "--tmax", str(CHECKER_TMAX)],
                    capture_output=True, text=True, timeout=30, check=False, encoding='utf-8', errors='replace' # check=False to handle non-zero exit
                )
                debug_print(f"Checker for {jar_basename} finished with code {checker_proc.returncode}")
                debug_print(f"Checker stdout:\n{checker_proc.stdout}")
                debug_print(f"Checker stderr:\n{checker_proc.stderr}")

                # Append checker's stderr to JAR's stderr log for context
                if checker_proc.stderr:
                    result["stderr"].extend(["--- Checker stderr ---"] + checker_proc.stderr.strip().splitlines())

                if checker_proc.returncode != 0:
                    result["status"] = "CHECKER_ERROR"
                    result["error_details"] = f"Checker exited with code {checker_proc.returncode}."
                    # Include checker stdout/stderr in details if non-zero exit
                    details_stdout = checker_proc.stdout.strip()
                    details_stderr = checker_proc.stderr.strip()
                    if details_stdout: result["error_details"] += f" stdout: {details_stdout[:200]}" # Limit length
                    if details_stderr: result["error_details"] += f" stderr: {details_stderr[:200]}" # Limit length
                    debug_print(f"Checker error for {jar_basename}: Exit code {checker_proc.returncode}")
                elif "Verdict: CORRECT" in checker_proc.stdout:
                    result["status"] = "CORRECT"
                    debug_print(f"Checker result for {jar_basename}: CORRECT")
                    # --- FIX 1: Extract Metrics ---
                    try:
                        t_final_match = re.search(r"\s*T_final.*?:\s*(\d+\.?\d*)", checker_proc.stdout)
                        wt_match = re.search(r"\s*WT.*?:\s*(\d+\.?\d*)", checker_proc.stdout)
                        w_match = re.search(r"^\s*W\s+\(Power Consumption\):\s*(\d+\.?\d*)", checker_proc.stdout, re.MULTILINE)
                        if t_final_match: result["t_final"] = float(t_final_match.group(1))
                        if wt_match: result["wt"] = float(wt_match.group(1))
                        if w_match: result["w"] = float(w_match.group(1))
                        debug_print(f"Extracted Metrics for {jar_basename}: T_final={result['t_final']}, WT={result['wt']}, W={result['w']}")
                        if result["t_final"] is None or result["wt"] is None or result["w"] is None:
                            print(f"WARNING: Checker verdict CORRECT for {jar_basename}, but couldn't parse all metrics (T_final, WT, W). Score might be 0.", file=sys.stderr)
                            result["error_details"] = "Correct verdict but failed to parse all metrics from checker."
                            # Keep status CORRECT, but score will likely be 0 due to missing metrics in _calculate_scores
                    except ValueError as e_parse:
                        print(f"ERROR: Checker verdict CORRECT for {jar_basename}, but failed parsing metrics: {e_parse}", file=sys.stderr)
                        result["status"] = "CHECKER_ERROR" # Treat parsing failure as error
                        result["error_details"] = f"Correct verdict but metric parsing failed: {e_parse}"
                        result["t_final"] = result["wt"] = result["w"] = None # Ensure reset
                    except Exception as e_re:
                        print(f"ERROR: Regex error during metric parsing for {jar_basename}: {e_re}", file=sys.stderr)
                        result["status"] = "CHECKER_ERROR"
                        result["error_details"] = f"Internal tester error (regex) parsing metrics: {e_re}"
                        result["t_final"] = result["wt"] = result["w"] = None # Ensure reset
                     # ------------------------------
                else:
                    result["status"] = "INCORRECT"
                    # Try to get reason from checker output
                    verdict_line = next((line for line in checker_proc.stdout.splitlines() if line.startswith("Verdict:")), "Verdict: INCORRECT (No details)")
                    result["error_details"] = verdict_line.strip()
                    debug_print(f"Checker result for {jar_basename}: INCORRECT. Details: {result['error_details']}")

            except subprocess.TimeoutExpired:
                print(f"ERROR: Checker timed out for {jar_basename}.", file=sys.stderr)
                result["status"] = "CHECKER_ERROR"
                result["error_details"] = "Checker process timed out."
            except Exception as e_check:
                print(f"ERROR: Exception running checker for {jar_basename}: {e_check}", file=sys.stderr)
                debug_print(f"Checker exception for {jar_basename}", exc_info=True)
                result["status"] = "CHECKER_ERROR"
                result["error_details"] = f"Exception during checker execution: {e_check}"
            finally:
                if temp_output_file and os.path.exists(temp_output_file):
                    try: os.remove(temp_output_file)
                    except Exception as e_rm: print(f"WARNING: Failed to remove temp checker output file {temp_output_file}: {e_rm}", file=sys.stderr)

        elif JarTester._interrupted and result["status"] == "RUNNING":
             result["status"] = "INTERRUPTED" # Mark as interrupted if checker was skipped due to Ctrl+C
             result["error_details"] = "Run interrupted before checker."
             debug_print(f"Marking {jar_basename} as INTERRUPTED (checker skipped).")
        else:
            debug_print(f"Skipping checker for {jar_basename} due to status: {result['status']} or interrupt: {JarTester._interrupted}")

        # Ensure score is 0 if not CORRECT
        if result["status"] != "CORRECT":
            result["final_score"] = 0.0
            result["t_final"] = result["wt"] = result["w"] = None

        debug_print(f"Finished run for JAR: {jar_basename}. Final Status: {result['status']}")
        return result

    @staticmethod
    def _generate_data(gen_args_list):
        """Calls gen.py, returns parsed request data, writes output to persistent log file."""
        # --- FIX 2: Use persistent file path ---
        if not JarTester._persistent_request_file_path:
            print("ERROR: Persistent request file path not set before calling _generate_data.", file=sys.stderr)
            return None, None
        persistent_file = JarTester._persistent_request_file_path
        # Ensure log directory exists (should be created in test())
        os.makedirs(os.path.dirname(persistent_file), exist_ok=True)
        # -----------------------------------------

        requests_data = None
        gen_stdout = None

        try:
            gen_proc = subprocess.run(
                [sys.executable, JarTester._gen_script_path] + gen_args_list,
                capture_output=True, text=True, timeout=15, check=True, encoding='utf-8', errors='replace'
            )
            print("--- Generator Output (stderr) ---", file=sys.stderr)
            print(gen_proc.stderr or "<No stderr>", file=sys.stderr)
            print("--- End Generator Output ---", file=sys.stderr)

            gen_stdout = gen_proc.stdout

            # Write to persistent file (overwrite)
            try:
                with open(persistent_file, 'w', encoding='utf-8') as f:
                    f.write(gen_stdout)
                debug_print(f"Generator output written to persistent file: {persistent_file}")
            except Exception as e_write:
                print(f"ERROR: Failed to write generator output to {persistent_file}: {e_write}", file=sys.stderr)
                # Continue with parsing if stdout was captured, but return None path
                persistent_file = None # Indicate failure to write

            # Parse requests
            raw_requests = gen_stdout.strip().splitlines()
            requests_data = []
            pattern = re.compile(r"\[\s*(\d+\.\d+)\s*\](.*)") # Original pattern
            for line in raw_requests:
                match = pattern.match(line)
                if match:
                    timestamp = float(match.group(1))
                    req_part = match.group(2) # Keep the rest of the line as is
                    requests_data.append((timestamp, req_part))
                else:
                    print(f"WARNING: Generator produced invalid line format (ignored): {line}", file=sys.stderr)

            if not requests_data:
                 print(f"WARNING: Generator produced output, but no valid request lines were parsed.", file=sys.stderr)
                 # Return empty list but valid path if written
                 return [], persistent_file

            requests_data.sort(key=lambda x: x[0]) # Sort by timestamp
            return requests_data, persistent_file # Return data and the persistent path

        except FileNotFoundError:
            print(f"ERROR: Generator script not found at '{JarTester._gen_script_path}'", file=sys.stderr)
            return None, None
        except subprocess.TimeoutExpired:
            print("ERROR: Generator script timed out.", file=sys.stderr)
            return None, None
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Generator script failed with exit code {e.returncode}.", file=sys.stderr)
            print(f"--- Generator Stdout ---\n{e.stdout or '<empty>'}\n--- Generator Stderr ---\n{e.stderr or '<empty>'}", file=sys.stderr)
            # Try to write output even if failed
            if gen_stdout is not None and persistent_file:
                 try:
                     with open(persistent_file, 'w', encoding='utf-8') as f: f.write(gen_stdout)
                 except Exception: pass
            return None, None
        except Exception as e:
            print(f"ERROR: Failed to generate data: {e}", file=sys.stderr)
            debug_print("Exception in _generate_data", exc_info=True)
            return None, None

    @staticmethod
    def _calculate_scores(current_results):
        """Calculates normalized performance scores based on current round results."""
        correct_results = [
            r for r in current_results
            if r["status"] == "CORRECT"
            and r["t_final"] is not None and r["wt"] is not None and r["w"] is not None # Ensure metrics exist
        ]
        debug_print(f"Calculating scores based on {len(correct_results)} CORRECT runs with metrics.")

        if not correct_results:
            print("INFO: No CORRECT runs with valid metrics in this round to calculate performance scores.", file=sys.stderr)
            # Ensure non-correct runs have score 0 (should already be handled in _run_single_jar)
            for r in current_results:
                 if r["status"] != "CORRECT": r["final_score"] = 0.0
            return

        # --- Score calculation logic (no change needed conceptually) ---
        # Extract metrics into numpy arrays
        t_finals = np.array([r["t_final"] for r in correct_results])
        wts = np.array([r["wt"] for r in correct_results])
        ws = np.array([r["w"] for r in correct_results])

        metrics = {'t_final': t_finals, 'wt': wts, 'w': ws}
        normalized_scores = {}

        # Calculate normalized score for each metric
        for name, values in metrics.items():
            if len(values) == 0: continue # Should not happen if correct_results is not empty
            x_min = np.min(values)
            x_max = np.max(values)
            x_avg = np.mean(values) # Renamed x_arg to x_avg for clarity

            # Define base_min and base_max for normalization range
            base_min = PERF_P_VALUE * x_avg + (1 - PERF_P_VALUE) * x_min
            base_max = PERF_P_VALUE * x_avg + (1 - PERF_P_VALUE) * x_max

            normalized = {}
            for r in correct_results:
                # Get the metric value for the current JAR
                metric_key = name # 't_final', 'wt', 'w'
                x = r[metric_key]
                r_x = 0.0 # Default score contribution

                # Handle normalization logic
                if base_max > base_min + 1e-9: # Normal case, distinct min/max range
                    if x <= base_min + 1e-9: r_x = 0.0
                    elif x >= base_max - 1e-9: r_x = 1.0 # Use >= for max boundary
                    else: r_x = (x - base_min) / (base_max - base_min)
                elif abs(base_max - base_min) < 1e-9: # All values are very close
                    # If value is at or below the (collapsed) base, score 0, else 1
                    r_x = 0.0 if x <= base_min + 1e-9 else 1.0
                # else: Should not happen if values has data

                normalized[r["jar_file"]] = r_x
            normalized_scores[name.upper()] = normalized # Store with uppercase key ('T_FINAL', 'WT', 'W')

        # Calculate final weighted score for each correct JAR
        for r in correct_results:
            jar_name = r["jar_file"]
            try:
                # Retrieve normalized scores (using uppercase keys)
                r_t = normalized_scores['T_FINAL'][jar_name]
                r_wt = normalized_scores['WT'][jar_name]
                r_w = normalized_scores['W'][jar_name]

                # Invert scores (lower metric is better, so higher inverted score)
                r_prime_t = 1.0 - r_t
                r_prime_wt = 1.0 - r_wt
                r_prime_w = 1.0 - r_w

                # Calculate weighted final score (scale 0-15)
                s = 15 * (0.3 * r_prime_t + 0.3 * r_prime_wt + 0.4 * r_prime_w)
                r["final_score"] = max(0.0, s) # Ensure score is non-negative
                debug_print(f"Score for {jar_name}: T_final={r['t_final']:.3f}({r_prime_t:.3f}), WT={r['wt']:.3f}({r_prime_wt:.3f}), W={r['w']:.3f}({r_prime_w:.3f}) -> Final={r['final_score']:.3f}")

            except KeyError:
                print(f"WARNING: Could not find normalized scores for {jar_name} to calculate final score. Setting score to 0.", file=sys.stderr)
                r["final_score"] = 0.0
            except Exception as e_score:
                 print(f"ERROR: Unexpected error calculating final score for {jar_name}: {e_score}. Setting score to 0.", file=sys.stderr)
                 r["final_score"] = 0.0

        # Ensure non-correct runs have final_score 0
        for r in current_results:
            if r["status"] != "CORRECT":
                r["final_score"] = 0.0


    @staticmethod
    def _display_results(results, request_file_path):
        """Display results for the current round and log errors AND summary table."""
        console_lines = []
        log_lines = []
        has_errors_for_log = False

        # Sort results for display
        results.sort(key=lambda x: (-x.get("final_score", 0.0), x.get("wall_time", float('inf')) if x.get("status") == "CORRECT" else float('inf')))

        # --- Prepare Console Output ---
        console_lines.append(f"\n--- Test Round {JarTester._test_count} Results ---")
        header = f"{'JAR':<25} | {'Status':<12} | {'Score':<7} | {'T_final':<10} | {'WT':<10} | {'W':<10} | {'CPU(s)':<8} | {'Wall(s)':<8} | Details"
        console_lines.append(header)
        console_lines.append("-" * len(header))

        # --- Prepare Log Output ---
        log_lines.append(f"\n--- Test Round {JarTester._test_count} Summary ---")
        # log_lines.append(f"Request File: {request_file_path or '<Not Available>'}")
        log_lines.append(header)
        log_lines.append("-" * len(header))

        error_log_header = True # Track if error details header is needed

        for r in results:
            jar_name = r.get("jar_file", "UnknownJAR")
            status = r.get("status", "UNKNOWN")
            # Use .get with defaults for robustness
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
            details = r.get("error_details", "")

            # Format line for both console and log summary
            line = f"{jar_name:<25} | {status:<12} | {score_str:<7} | {tfin_str:<10} | {wt_str:<10} | {w_str:<10} | {cpu_str:<8} | {wall_str:<8} | {details}"

            console_lines.append(line)
            log_lines.append(line) # --- FIX 3: Add summary line to log ---

            # --- Log Detailed Errors ---
            if status not in ["CORRECT", "PENDING", "RUNNING", "INTERRUPTED"]:
                has_errors_for_log = True
                if error_log_header:
                    log_lines.append(f"\n--- Test Round {JarTester._test_count} Error Details ---")
                    error_log_header = False

                log_lines.append(f"\n--- Error Details for: {jar_name} (Status: {status}) ---")
                log_lines.append(f"  Error: {details}")

                # Add Input Data to Log
                log_lines.append("  --- Input Data ---")
                if request_file_path and os.path.exists(request_file_path):
                    try:
                        with open(request_file_path, 'r', encoding='utf-8') as rf:
                            # Log first N lines and last M lines? Or limit total lines? Let's limit lines for now.
                            MAX_INPUT_LOG_LINES = 50
                            input_lines = rf.readlines()
                            logged_lines_count = 0
                            for i, req_line in enumerate(input_lines):
                                if logged_lines_count < MAX_INPUT_LOG_LINES:
                                    log_lines.append(f"    {req_line.strip()}")
                                    logged_lines_count += 1
                                elif i == MAX_INPUT_LOG_LINES:
                                    log_lines.append(f"    ... (input truncated after {MAX_INPUT_LOG_LINES} lines)")
                                    break
                            if len(input_lines) <= MAX_INPUT_LOG_LINES:
                                log_lines.append("    <End of Input>")

                    except Exception as read_err:
                        log_lines.append(f"    <Error reading input file {request_file_path}: {read_err}>")
                else:
                     log_lines.append(f"    <Input file '{request_file_path}' not found or not provided>")
                log_lines.append("  --- End Input Data ---")

                # Add Stdout to Log
                log_lines.append("  --- Stdout ---")
                stdout = r.get("stdout", [])
                if stdout:
                    MAX_OUTPUT_LOG_LINES = 100
                    for i, out_line in enumerate(stdout):
                         if i < MAX_OUTPUT_LOG_LINES: log_lines.append(f"    {out_line.strip()}")
                         elif i == MAX_OUTPUT_LOG_LINES: log_lines.append(f"    ... (stdout truncated after {MAX_OUTPUT_LOG_LINES} lines)"); break
                    if len(stdout) <= MAX_OUTPUT_LOG_LINES: log_lines.append("    <End of Stdout>")
                else:
                    log_lines.append("    <No stdout captured>")
                log_lines.append("  --- End Stdout ---")

                # Add Stderr to Log
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
                log_lines.append("-" * 20) # Separator

        console_lines.append("-" * len(header))
        log_lines.append("-" * len(header)) # Footer for summary table in log

        # Print to console
        print("\n".join(console_lines))

        # Write log entries
        if JarTester._log_file_path:
            try:
                with open(JarTester._log_file_path, "a", encoding="utf-8") as f:
                    f.write("\n".join(log_lines) + "\n")
                debug_print(f"Results and errors for round {JarTester._test_count} written to log.")
            except Exception as e:
                print(f"ERROR: Failed to write results to log file {JarTester._log_file_path}: {e}", file=sys.stderr)


    @staticmethod
    def _update_history(results):
        """Update the historical results after a round."""
        # (No changes needed here, relies on final_score being set correctly)
        for r in results:
            if r.get("status") == "INTERRUPTED":
                continue # Skip interrupted runs

            jar_name = r.get("jar_file", "UnknownJAR")
            if jar_name == "UnknownJAR": continue # Skip malformed results

            history = JarTester._all_results_history[jar_name]
            history['total_runs'] += 1
            score_to_add = 0.0 # Default score for non-correct runs

            if r.get("status") == "CORRECT":
                history['correct_runs'] += 1
                # Use .get() for safety, though it should exist if status is CORRECT and calculation worked
                score_to_add = r.get("final_score", 0.0)
                # Handle potential None score if calculation failed unexpectedly
                if score_to_add is None: score_to_add = 0.0

            # Append the score (0.0 for non-correct/interrupted/error, calculated score for CORRECT)
            history['scores'].append(score_to_add)
            debug_print(f"History update for {jar_name}: Total={history['total_runs']}, Correct={history['correct_runs']}, Added Score={score_to_add}")


    @staticmethod
    def _print_summary():
        """Prints the average scores upon interruption or normal completion."""
        # (No changes needed here, relies on _update_history working correctly)
        if JarTester._interrupted:
            print("\n--- Testing Interrupted ---")
        else:
            print("\n--- Testing Finished ---")

        print(f"Total test rounds attempted: {JarTester._test_count}")

        if not JarTester._all_results_history:
            print("No completed test results recorded.")
            return

        print("\n--- Average Performance Summary (Based on Completed Rounds) ---")
        summary = []
        for jar_name, data in JarTester._all_results_history.items():
            total_runs = data['total_runs']
            correct_runs = data['correct_runs']
            scores = data['scores']
            # Ensure scores list contains numbers, replace None/NaN if any crept in
            valid_scores = [s for s in scores if isinstance(s, (int, float)) and not np.isnan(s)]
            avg_score = np.mean(valid_scores) if valid_scores else 0.0
            correct_rate = (correct_runs / total_runs * 100) if total_runs > 0 else 0.0
            # Ensure avg_score is not NaN if valid_scores was empty
            avg_score = avg_score if not np.isnan(avg_score) else 0.0
            summary.append({
                "jar": jar_name,
                "avg_score": avg_score,
                "correct_rate": correct_rate,
                "correct": correct_runs,
                "total": total_runs
            })

        summary.sort(key=lambda x: (-x["avg_score"], -x["correct_rate"]))

        header = f"{'JAR':<25} | {'Avg Score':<10} | {'Correct %':<10} | {'Passed/Total':<15}"
        print(header)
        print("-" * len(header))
        for item in summary:
             passed_total_str = f"{item['correct']}/{item['total']}"
             line = f"{item['jar']:<25} | {item['avg_score']:<10.3f} | {item['correct_rate']:<10.1f}% | {passed_total_str:<15}"
             print(line)
        print("-" * len(header))

    @staticmethod
    def _signal_handler(sig, frame):
        # (No changes needed here)
        if not JarTester._interrupted: # Prevent multiple prints if Ctrl+C hit rapidly
            print("\nCtrl+C detected. Stopping after current round finishes...", file=sys.stderr)
            JarTester._interrupted = True


    @staticmethod
    def test(hw_n, jar_path, gen_args=None):
        """Main testing entry point."""
        try: # Wrap main logic in try/finally for cleanup
            hw_n = str(hw_n).replace(".", os.sep) # Use os.sep for cross-platform paths
            JarTester._jar_dir = jar_path
            JarTester._gen_script_path = os.path.abspath(os.path.join(hw_n, "gen.py"))
            JarTester._checker_script_path = os.path.abspath(os.path.join(hw_n, "checker.py"))
            JarTester._interrupted = False
            JarTester._test_count = 0
            JarTester._all_results_history.clear()

            # --- Log Setup ---
            os.makedirs(LOG_DIR, exist_ok=True)
            local_time = time.localtime()
            formatted_time = time.strftime("%Y-%m-%d-%H-%M-%S", local_time)
            JarTester._log_file_path = os.path.abspath(os.path.join(LOG_DIR, f"{formatted_time}_elevator_run.log"))
            # --- FIX 2: Define persistent request file path ---
            JarTester._persistent_request_file_path = os.path.abspath(os.path.join(LOG_DIR, "latest_requests.txt"))
            print(f"INFO: Logging errors and round summaries to {JarTester._log_file_path}")
            print(f"INFO: Storing latest generated requests to {JarTester._persistent_request_file_path}")
            # -------------------------------------------------

            if not os.path.exists(JarTester._gen_script_path):
                 print(f"ERROR: Generator script not found: {JarTester._gen_script_path}", file=sys.stderr); return
            if not os.path.exists(JarTester._checker_script_path):
                 print(f"ERROR: Checker script not found: {JarTester._checker_script_path}", file=sys.stderr); return
            if not JarTester._find_jar_files():
                print("ERROR: No JAR files found or accessible. Aborting.", file=sys.stderr); return

            signal.signal(signal.SIGINT, JarTester._signal_handler)
            print(f"Press Ctrl+C to stop testing gracefully after the current round.")

            actual_gen_args = DEFAULT_GEN_ARGS.copy()
            if gen_args: actual_gen_args.update(gen_args)
            gen_args_list = []
            for key, value in actual_gen_args.items():
                 arg_name = f"--{key.replace('_', '-')}"
                 if isinstance(value, bool):
                     if value: gen_args_list.append(arg_name)
                 elif value is not None:
                     gen_args_list.extend([arg_name, str(value)])

            current_request_file_path = None # Track path used in the round

            while not JarTester._interrupted:
                JarTester._test_count += 1
                JarTester._clear_screen()
                print(f"\n--- Starting Test Round {JarTester._test_count} ---")
                print(f"Generator Args: {' '.join(gen_args_list)}")

                # 1. Generate Data
                debug_print(f"Round {JarTester._test_count}: Generating data...")
                # _generate_data now returns persistent path
                requests_data, current_request_file_path = JarTester._generate_data(gen_args_list)

                if requests_data is None: # Check only data, path might exist even on failure
                    print("ERROR: Failed to generate data for this round. Skipping.", file=sys.stderr)
                    if JarTester._interrupted: break
                    time.sleep(2) # Pause before retrying or exiting
                    continue # Skip to next round or exit loop if interrupted
                debug_print(f"Round {JarTester._test_count}: Generated {len(requests_data)} requests to '{current_request_file_path}'")

                # Check for interrupt *after* generation
                if JarTester._interrupted: break

                # 2. Run JARs Concurrently
                results = []
                # Use CPU count or a reasonable number if JAR count is very high?
                max_workers = min(len(JarTester._jar_files), os.cpu_count() or 8)
                print(f"INFO: Running {len(JarTester._jar_files)} JARs with max {max_workers} workers...")
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_jar = {
                        # Pass the persistent request file path to _run_single_jar
                        executor.submit(JarTester._run_single_jar, jar_file, requests_data, current_request_file_path): jar_file
                        for jar_file in JarTester._jar_files
                    }
                    debug_print(f"Round {JarTester._test_count}: Submitted {len(future_to_jar)} JARs.")
                    try:
                        # Use as_completed to process results as they finish
                        completed_count = 0
                        for future in concurrent.futures.as_completed(future_to_jar):
                             if JarTester._interrupted:
                                 # Don't cancel futures, let them finish or time out naturally
                                 # The internal checks within _run_single_jar handle interruption
                                 debug_print("Interrupt detected during as_completed, waiting for running jobs...")

                             jar_file = future_to_jar[future]
                             jar_basename = os.path.basename(jar_file)
                             try:
                                 result = future.result()
                                 results.append(result)
                                 completed_count += 1
                                 # Simple progress indicator
                                 print(f"Progress: {completed_count}/{len(future_to_jar)} completed ({jar_basename}: {result.get('status','?')})...", end='\r', flush=True)
                             except concurrent.futures.CancelledError:
                                  # Should not happen often now as we don't cancel
                                  print(f"INFO: Run for {jar_basename} was cancelled (unexpected).", file=sys.stderr)
                             except Exception as exc:
                                print(f'\nERROR: JAR {jar_basename} generated an unexpected exception in tester thread: {exc}', file=sys.stderr)
                                debug_print(f"Exception from future for {jar_basename}", exc_info=True)
                                results.append({ "jar_file": jar_basename, "status": "CRASHED", "final_score": 0.0, "error_details": f"Tester thread exception: {exc}", "cpu_time": 0, "wall_time": 0, "t_final": None, "wt": None, "w": None, "stdout": [], "stderr": []})
                                print(f"Progress: {completed_count}/{len(future_to_jar)} completed ({jar_basename}: CRASHED)...", end='\r', flush=True)
                                completed_count += 1


                    except KeyboardInterrupt: # Catch Ctrl+C during the as_completed loop
                        if not JarTester._interrupted:
                             print("\nCtrl+C detected during JAR execution. Stopping after current round finishes...", file=sys.stderr)
                             JarTester._interrupted = True
                        # Allow loop to finish processing already completed futures

                print(f"\nINFO: All {len(future_to_jar)} JAR executions completed or terminated for round {JarTester._test_count}.")
                debug_print(f"Round {JarTester._test_count}: Concurrent execution finished.")

                # Check for interrupt *before* processing results
                if JarTester._interrupted: break

                # 3. Calculate Performance Scores
                debug_print(f"Round {JarTester._test_count}: Calculating scores...")
                JarTester._calculate_scores(results)

                # 4. Display Results (Pass request file path)
                debug_print(f"Round {JarTester._test_count}: Displaying results...")
                JarTester._display_results(results, current_request_file_path)

                # 5. Update Historical Data (Check interrupt flag *before* updating)
                if not JarTester._interrupted:
                    debug_print(f"Round {JarTester._test_count}: Updating history...")
                    JarTester._update_history(results)
                else:
                    debug_print(f"Round {JarTester._test_count}: Skipping history update due to interrupt.")
                    break

                # 6. Cleanup - No need to remove persistent request file
                current_request_file_path = None # Reset for next loop

                # Optional: Brief pause between rounds
                if not JarTester._interrupted: time.sleep(1)


        except Exception as e:
            print(f"\nFATAL ERROR in main testing loop: {e}", file=sys.stderr)
            debug_print("Fatal error in main loop", exc_info=True)
            # Attempt to log the fatal error
            if JarTester._log_file_path:
                 try:
                     with open(JarTester._log_file_path, "a", encoding="utf-8") as f:
                         f.write(f"\n\n!!! FATAL TESTER ERROR !!!\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n{e}\n")
                         import traceback
                         traceback.print_exc(file=f)
                 except Exception: pass # Best effort logging
        finally:
             # --- FIX 2: Remove deletion of persistent request file ---
             # if temp_req_file_path and os.path.exists(temp_req_file_path):
             #     try: os.remove(temp_req_file_path)
             #     except Exception as e: print(f"WARNING: Failed to remove temporary request file on exit: {e}", file=sys.stderr)

             # Print summary (will be called on normal or interrupted exit)
             JarTester._print_summary()

# --- Main Execution Block ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Elevator Concurrent Tester")
    parser.add_argument("hw_n", help="Homework identifier (e.g., 'hw5'), directory containing gen.py and checker.py")
    parser.add_argument("jar_path", help="Path to the directory containing student JAR files")
    # Keep existing gen args
    parser.add_argument("--gen-num-requests", type=int, help="Pass --num-requests to gen.py")
    parser.add_argument("--gen-max-time", type=float, help="Pass --max-time to gen.py")
    # Add other gen args as needed from your original example if they weren't included above
    parser.add_argument("--gen-hce", action='store_true', help="Pass --hce to gen.py")
    parser.add_argument("--gen-priority-bias", choices=['none', 'extremes', 'middle'], help="Pass --priority-bias to gen.py")
    parser.add_argument("--gen-priority-bias-ratio", type=float, help="Pass --priority-bias-ratio to gen.py")

    # Example: Add argument for detailed debug mode
    parser.add_argument("--debug", action='store_true', help="Enable detailed debug output to stderr.")

    args = parser.parse_args()

    if args.debug:
        ENABLE_DETAILED_DEBUG = True
        debug_print("Detailed debugging enabled.")

    gen_args_override = {}
    if args.gen_num_requests is not None: gen_args_override['num_requests'] = args.gen_num_requests
    if args.gen_max_time is not None: gen_args_override['max_time'] = args.gen_max_time
    if args.gen_hce: gen_args_override['hce'] = True
    if args.gen_priority_bias is not None: gen_args_override['priority_bias'] = args.gen_priority_bias
    if args.gen_priority_bias_ratio is not None: gen_args_override['priority_bias_ratio'] = args.gen_priority_bias_ratio

    hw_dir = args.hw_n
    jar_dir = args.jar_path

    # Directory existence checks
    if not os.path.isdir(hw_dir):
        print(f"ERROR: Homework directory '{hw_dir}' not found.", file=sys.stderr); sys.exit(1)
    if not os.path.isdir(jar_dir):
        print(f"ERROR: JAR directory '{jar_dir}' not found.", file=sys.stderr); sys.exit(1)

    # Start testing
    JarTester.test(hw_dir, jar_dir, gen_args=gen_args_override)