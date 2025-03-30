# --- START OF FILE custom.py ---

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
import random # Keep for unique filenames
import shutil # Keep for potential future cleanup
import traceback # For logging errors from threads

# --- Configuration ---
CPU_TIME_LIMIT = 10.0  # seconds (Keep from test.py)
MIN_WALL_TIME_LIMIT = 60.0 # seconds - Minimum wall time, can be adjusted based on input
DEFAULT_WALL_TIME_BUFFER_FACTOR = 1.5 # Multiplier for max timestamp from input
DEFAULT_WALL_TIME_ADDITIONAL_SECONDS = 15.0 # Extra buffer time
PERF_P_VALUE = 0.10 # Keep from test.py
ENABLE_DETAILED_DEBUG = False # Set to True for verbose debugging
LOG_DIR = "logs" # Define log directory constant
TMP_DIR = "tmp"  # Define temporary file directory constant
DEFAULT_INPUT_FILE = "stdin.txt" # Default input file name

# Helper function for conditional debug printing
def debug_print(*args, **kwargs):
    if ENABLE_DETAILED_DEBUG:
        # Add thread identifier for clarity in parallel runs
        thread_name = threading.current_thread().name
        print(f"DEBUG [{time.time():.4f}] [{thread_name}]:", *args, **kwargs, file=sys.stderr, flush=True)

class CustomTester:
    # --- Static variables ---
    _jar_files = []
    _finder_executed = False
    _jar_dir = ""
    _checker_script_path = ""
    _input_file_path = "" # Store path to the user-provided input file
    _interrupted = False # Global interrupt flag
    _log_file_path = None
    # Use history for the single run's results before summary
    _run_results_history = defaultdict(lambda: {'correct_runs': 0, 'total_runs': 1, 'scores': []}) # Simplified for one run

    # --- Locks for shared resources ---
    _history_lock = threading.Lock()
    _log_lock = threading.Lock()
    _console_lock = threading.Lock()

    # --- Helper: Clear Screen ---
    @staticmethod
    def _clear_screen():
        """Clears the terminal screen."""
        if ENABLE_DETAILED_DEBUG: return
        if threading.current_thread() is threading.main_thread():
             os.system('cls' if os.name == 'nt' else 'clear')

    # --- (Keep _find_jar_files, _kill_process_tree as they are from test.py) ---
    @staticmethod
    def _find_jar_files():
        """Search for JAR files in the specified directory"""
        if not CustomTester._finder_executed:
            try:
                CustomTester._jar_dir = os.path.abspath(CustomTester._jar_dir)
                CustomTester._jar_files = [
                    os.path.join(CustomTester._jar_dir, f)
                    for f in os.listdir(CustomTester._jar_dir)
                    if f.endswith('.jar')
                ]
                CustomTester._finder_executed = True
                print(f"INFO: Found {len(CustomTester._jar_files)} JAR files in '{CustomTester._jar_dir}'")
            except FileNotFoundError:
                print(f"ERROR: JAR directory not found: '{CustomTester._jar_dir}'", file=sys.stderr)
                return False
            except Exception as e:
                print(f"ERROR: Failed to list JAR files in '{CustomTester._jar_dir}': {e}", file=sys.stderr)
                return False
        return len(CustomTester._jar_files) > 0

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
            print(f"ERROR: Exception during process termination for PID {pid}: {e}", file=sys.stderr)


    # --- (Keep _timed_input_feeder, _output_reader as they are from test.py) ---
    @staticmethod
    def _timed_input_feeder(process, requests, start_event, error_flag):
        """Thread function to feed input to the JAR process at specific times."""
        pid = process.pid
        debug_print(f"Input feeder started for PID {pid}")
        try:
            debug_print(f"Input feeder waiting for start event for PID {pid}")
            start_event.wait()
            if error_flag.is_set() or CustomTester._interrupted: return # Check after wait

            debug_print(f"Input feeder received start event for PID {pid}")
            start_mono_time = time.monotonic()
            request_count = len(requests)
            for i, (req_time, req_data) in enumerate(requests):
                if error_flag.is_set() or CustomTester._interrupted:
                    debug_print(f"Input feeder stopping early for PID {pid} (error or interrupt)")
                    break
                current_mono_time = time.monotonic()
                elapsed_time = current_mono_time - start_mono_time
                sleep_duration = req_time - elapsed_time
                if sleep_duration > 0:
                    sleep_end_time = time.monotonic() + sleep_duration
                    while time.monotonic() < sleep_end_time:
                        if error_flag.is_set() or CustomTester._interrupted:
                            debug_print(f"Input feeder woken early from sleep for PID {pid} (error or interrupt)")
                            return
                        check_interval = min(0.05, sleep_end_time - time.monotonic()) # Fine-tune check interval
                        if check_interval > 0: time.sleep(check_interval)
                if error_flag.is_set() or CustomTester._interrupted:
                    debug_print(f"Input feeder stopping after sleep for PID {pid} (error or interrupt)")
                    break
                try:
                    # debug_print(f"Input feeder feeding request {i+1}/{request_count} to PID {pid}: {req_data}")
                    process.stdin.write(req_data + '\n')
                    process.stdin.flush()
                except (BrokenPipeError, OSError) as e:
                    if not error_flag.is_set() and not CustomTester._interrupted:
                        debug_print(f"Input feeder: Pipe broken/OS error detected for PID {pid}")
                    error_flag.set()
                    break
                except Exception as e:
                    print(f"ERROR: Input feeder: Unexpected error writing to PID {pid}: {e}", file=sys.stderr)
                    debug_print(f"Input feeder: Exception during write for PID {pid}", exc_info=True)
                    error_flag.set()
                    break
            debug_print(f"Input feeder finished loop for PID {pid}. Error={error_flag.is_set()}, Interrupt={CustomTester._interrupted}")
            if not error_flag.is_set() and not CustomTester._interrupted:
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
        debug_print(f"Output reader ({stream_name}) started for PID {pid}")
        try:
            for line_num, line in enumerate(iter(pipe.readline, '')):
                if error_flag.is_set() or CustomTester._interrupted:
                     debug_print(f"Output reader ({stream_name}) stopping early for PID {pid} (error or interrupt)")
                     break
                output_queue.put(line)
            debug_print(f"Output reader ({stream_name}) finished iter loop for PID {pid}")
        except ValueError:
            if not error_flag.is_set() and not CustomTester._interrupted and pipe and not pipe.closed:
                 debug_print(f"Output reader ({stream_name}) caught ValueError for PID {pid} (pipe not closed)")
            # Ignore ValueError if pipe is closed, common scenario
        except Exception as e:
            if not error_flag.is_set() and not CustomTester._interrupted:
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
    # --- It now gets the *original* input file path for the checker ---
    @staticmethod
    def _run_single_jar(jar_path, requests_data, original_input_file_path, current_wall_limit):
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
            "input_data_path": original_input_file_path # Store the ORIGINAL input path
        }
        input_feeder_thread = None
        stdout_reader_thread = None
        stderr_reader_thread = None
        stdout_queue = queue.Queue()
        stderr_queue = queue.Queue()
        feeder_start_event = threading.Event()
        error_flag = threading.Event() # Local error flag for this JAR run

        try:
            # --- (Process Launch and Monitoring - unchanged from test.py) ---
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
                return result

            debug_print(f"Starting I/O threads for PID {pid}")
            input_feeder_thread = threading.Thread(target=CustomTester._timed_input_feeder, args=(process, requests_data, feeder_start_event, error_flag), daemon=True)
            stdout_reader_thread = threading.Thread(target=CustomTester._output_reader, args=(process.stdout, stdout_queue, "stdout", pid, error_flag), daemon=True)
            stderr_reader_thread = threading.Thread(target=CustomTester._output_reader, args=(process.stderr, stderr_queue, "stderr", pid, error_flag), daemon=True)
            input_feeder_thread.start()
            stdout_reader_thread.start()
            stderr_reader_thread.start()

            debug_print(f"Starting monitoring loop for PID {pid}")
            monitor_loops = 0
            process_exited_normally = False
            while True:
                monitor_loops += 1
                if not feeder_start_event.is_set(): feeder_start_event.set()

                try:
                    if not ps_proc.is_running():
                        debug_print(f"Monitor loop {monitor_loops}: ps_proc.is_running() is False for PID {pid}. Breaking.")
                        if not error_flag.is_set() and not CustomTester._interrupted:
                            debug_print(f"Monitor loop {monitor_loops}: Process {pid} detected as not running. Setting exitedNormally=True.")
                            process_exited_normally = True
                        break
                except psutil.NoSuchProcess:
                    debug_print(f"Monitor loop {monitor_loops}: psutil.NoSuchProcess caught checking is_running() for PID {pid}. Breaking.")
                    if not error_flag.is_set() and not CustomTester._interrupted:
                        process_exited_normally = True
                    break

                if error_flag.is_set():
                    debug_print(f"Monitor loop {monitor_loops}: Local error flag is set for PID {pid}. Breaking.")
                    break
                if CustomTester._interrupted:
                    debug_print(f"Monitor loop {monitor_loops}: Global interrupt flag is set. Breaking.")
                    if result["status"] not in ["TLE", "CTLE", "CRASHED", "CHECKER_ERROR"]:
                        result["status"] = "INTERRUPTED"
                        result["error_details"] = "Run interrupted by user (Ctrl+C)."
                    error_flag.set()
                    break

                current_wall_time = time.monotonic() - start_wall_time
                current_cpu_time = result["cpu_time"]
                try:
                    cpu_times = ps_proc.cpu_times()
                    current_cpu_time = cpu_times.user + cpu_times.system
                except psutil.NoSuchProcess:
                    debug_print(f"Monitor loop {monitor_loops}: NoSuchProcess getting CPU times for PID {pid}. Likely exited cleanly. Breaking monitor loop.")
                    if not error_flag.is_set() and not CustomTester._interrupted:
                        process_exited_normally = True
                    break
                except Exception as e_cpu:
                    print(f"ERROR: Monitor loop: Unexpected error getting CPU times for PID {pid}: {e_cpu}", file=sys.stderr)
                    debug_print(f"Monitor loop {monitor_loops}: psutil error getting CPU times for PID {pid}", exc_info=True)
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

            debug_print(f"Exited monitoring loop for PID {pid} after {monitor_loops} iterations. Status: {result['status']}, ExitedNormally: {process_exited_normally}")

            # --- (Termination and Thread Cleanup - unchanged from test.py) ---
            if error_flag.is_set() and pid != -1:
                 debug_print(f"Error flag set or limit exceeded, ensuring process tree killed for PID {pid}")
                 try:
                     if process and process.poll() is None: CustomTester._kill_process_tree(pid)
                     elif psutil.pid_exists(pid): CustomTester._kill_process_tree(pid)
                     else: debug_print(f"Process {pid} already gone before kill attempt after loop exit.")
                 except Exception as e_kill_loop:
                     print(f"WARNING: Error during kill attempt after loop exit for PID {pid}: {e_kill_loop}", file=sys.stderr)

            debug_print(f"Waiting for I/O threads to finish for PID {pid}")
            thread_join_timeout = 2.0
            threads_to_join = [t for t in [input_feeder_thread, stdout_reader_thread, stderr_reader_thread] if t and t.is_alive()]
            start_join_time = time.monotonic()
            while threads_to_join and time.monotonic() - start_join_time < thread_join_timeout:
                for t in threads_to_join[:]:
                    t.join(timeout=0.1)
                    if not t.is_alive():
                        threads_to_join.remove(t)
            for t in threads_to_join:
                if t.is_alive():
                    print(f"WARNING: Thread {t.name} for PID {pid} did not exit cleanly within timeout.", file=sys.stderr)
            debug_print(f"Finished waiting for I/O threads for PID {pid}")

            final_status_determined = result["status"] not in ["RUNNING", "PENDING"]

            result["wall_time"] = time.monotonic() - start_wall_time
            try:
                if psutil.pid_exists(pid):
                     final_cpu_times = psutil.Process(pid).cpu_times()
                     result["cpu_time"] = final_cpu_times.user + final_cpu_times.system
            except psutil.NoSuchProcess: pass

            # --- (Check Exit Code - unchanged from test.py) ---
            if process_exited_normally and not final_status_determined:
                debug_print(f"Process {pid} exited normally (flag is True). Getting final state and exit code.")
                exit_code = None
                try:
                    exit_code = process.wait(timeout=0.5)
                    debug_print(f"Process {pid} wait() returned exit code: {exit_code}")
                    if exit_code is not None and exit_code != 0:
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Exited with non-zero code {exit_code}."
                        final_status_determined = True
                    elif result["status"] == "PENDING":
                         result["status"] = "RUNNING"

                except subprocess.TimeoutExpired:
                    print(f"WARNING: Timeout waiting for exit code for PID {pid}, which should have exited. Forcing kill.", file=sys.stderr)
                    try: CustomTester._kill_process_tree(pid)
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

        except (psutil.NoSuchProcess) as e_outer:
            debug_print(f"Outer exception handler: NoSuchProcess for PID {pid} ({jar_basename}). Handled.")
            if result["status"] not in ["CRASHED", "TLE", "CTLE", "INTERRUPTED", "CHECKER_ERROR"]:
                result["status"] = "CRASHED"
                result["error_details"] = f"Process disappeared unexpectedly: {e_outer}"
            error_flag.set()
        except FileNotFoundError:
            print(f"ERROR: Java executable or JAR file '{jar_path}' not found.", file=sys.stderr)
            debug_print(f"Outer exception handler: FileNotFoundError for JAR {jar_basename}.")
            result["status"] = "CRASHED"
            result["error_details"] = f"File not found (Java or JAR)."
            error_flag.set()
        except Exception as e:
            print(f"FATAL: Error during execution setup/monitoring of {jar_basename} (PID {pid}): {e}", file=sys.stderr)
            debug_print(f"Outer exception handler: Unexpected exception for PID {pid}", exc_info=True)
            if result["status"] not in ["CRASHED", "TLE", "CTLE", "INTERRUPTED", "CHECKER_ERROR"]:
                result["status"] = "CRASHED"
                result["error_details"] = f"Tester execution error: {e}"
            error_flag.set()
            if pid != -1 and process and process.poll() is None:
                debug_print(f"Outer exception: Ensuring PID {pid} is killed.")
                try: CustomTester._kill_process_tree(pid)
                except Exception as e_kill_outer: print(f"ERROR: Exception during final kill in outer catch for PID {pid}: {e_kill_outer}", file=sys.stderr)

        finally:
            # --- (Drain queues and Save Stdout - unchanged from test.py) ---
            debug_print(f"Entering finally block for PID {pid}. Status: {result['status']}")
            if pid != -1 and process and process.poll() is None:
                try:
                    if psutil.pid_exists(pid):
                        debug_print(f"Final cleanup killing PID {pid}")
                        CustomTester._kill_process_tree(pid)
                    else: debug_print(f"Final cleanup: Process {pid} already gone.")
                except Exception as e_kill:
                    print(f"ERROR: Exception during final kill for PID {pid}: {e_kill}", file=sys.stderr)

            debug_print(f"Draining output queues for PID {pid}")
            stdout_lines = []
            stderr_lines = []
            try:
                while True: stdout_lines.append(stdout_queue.get(block=False))
            except queue.Empty: pass
            try:
                while True: stderr_lines.append(stderr_queue.get(block=False))
            except queue.Empty: pass

            result["stderr"] = stderr_lines
            debug_print(f"Drained queues for PID {pid}. stdout lines: {len(stdout_lines)}, stderr lines: {len(stderr_lines)}")

            stdout_content = "".join(stdout_lines)
            save_stdout = stdout_content or result["status"] not in ["PENDING", "RUNNING", "CORRECT"]
            if save_stdout:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                rand_id = random.randint(1000, 9999)
                safe_jar_basename = re.sub(r'[^\w.-]', '_', jar_basename)
                # Include PID in filename for better debugging
                # Use original input filename base for context
                input_file_basename = os.path.splitext(os.path.basename(original_input_file_path))[0]
                safe_input_basename = re.sub(r'[^\w.-]', '_', input_file_basename)
                stdout_filename = f"stdout_{safe_jar_basename}_input_{safe_input_basename}_p{pid}_{timestamp}_{rand_id}.log"
                stdout_filepath = os.path.abspath(os.path.join(TMP_DIR, stdout_filename))
                try:
                    os.makedirs(TMP_DIR, exist_ok=True)
                    with open(stdout_filepath, 'w', encoding='utf-8', errors='replace') as f_out:
                        f_out.write(stdout_content)
                    result["stdout_log_path"] = stdout_filepath
                    debug_print(f"JAR stdout saved to {stdout_filepath}")
                except Exception as e_write_stdout:
                    print(f"WARNING: Failed to write stdout log for {jar_basename} to {stdout_filepath}: {e_write_stdout}", file=sys.stderr)
                    result["stdout_log_path"] = None
            else:
                 debug_print(f"No stdout content generated for {jar_basename} and status is OK, not saving file.")
                 result["stdout_log_path"] = None

            debug_print(f"Final check join for threads of PID {pid}")
            if input_feeder_thread and input_feeder_thread.is_alive(): input_feeder_thread.join(timeout=0.1)
            if stdout_reader_thread and stdout_reader_thread.is_alive(): stdout_reader_thread.join(timeout=0.1)
            if stderr_reader_thread and stderr_reader_thread.is_alive(): stderr_reader_thread.join(timeout=0.1)
            debug_print(f"Exiting finally block for PID {pid}")


        # --- Run Checker ---
        # Uses the original input file path and saved stdout content
        run_checker = (result["status"] == "RUNNING" and not CustomTester._interrupted)

        if run_checker:
            debug_print(f"Running checker for {jar_basename} (PID {pid}) because status is RUNNING and not globally interrupted.")
            temp_output_file = None
            checker_status = "CHECKER_PENDING"
            checker_details = ""
            try:
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt", encoding='utf-8', dir=TMP_DIR, errors='replace') as tf:
                    tf.write(stdout_content)
                    temp_output_file = tf.name

                # Use original_input_file_path for checker's first arg
                debug_print(f"Checker using input(orig) '{original_input_file_path}' and output(jar) '{temp_output_file}' with Tmax={current_wall_limit:.2f}s")

                checker_timeout = 45.0
                checker_proc = subprocess.run(
                    [sys.executable, CustomTester._checker_script_path, original_input_file_path, temp_output_file, "--tmax", str(current_wall_limit)],
                    capture_output=True, text=True, timeout=checker_timeout, check=False, encoding='utf-8', errors='replace'
                )
                debug_print(f"Checker for {jar_basename} finished with code {checker_proc.returncode}")

                if checker_proc.stderr:
                    result["stderr"].extend(["--- Checker stderr ---"] + checker_proc.stderr.strip().splitlines())

                # --- (Checker result parsing - unchanged logic from test.py) ---
                if checker_proc.returncode != 0:
                    checker_status = "CHECKER_ERROR"
                    checker_details = f"Checker exited with code {checker_proc.returncode}."
                    details_stdout = checker_proc.stdout.strip()
                    details_stderr = checker_proc.stderr.strip()
                    if details_stdout: checker_details += f" stdout: {details_stdout[:200]}"
                    if details_stderr: checker_details += f" stderr: {details_stderr[:200]}"
                    debug_print(f"Checker error for {jar_basename}: Exit code {checker_proc.returncode}")
                elif "Verdict: CORRECT" in checker_proc.stdout:
                    checker_status = "CORRECT"
                    debug_print(f"Checker result for {jar_basename}: CORRECT")
                    try:
                        t_final_match = re.search(r"\s*T_final.*?:\s*(\d+\.?\d*)", checker_proc.stdout)
                        wt_match = re.search(r"\s*WT.*?:\s*(\d+\.?\d*)", checker_proc.stdout)
                        w_match = re.search(r"^\s*W\s+\(Power Consumption\):\s*(\d+\.?\d*)", checker_proc.stdout, re.MULTILINE)
                        t_final_val = float(t_final_match.group(1)) if t_final_match else None
                        wt_val = float(wt_match.group(1)) if wt_match else None
                        w_val = float(w_match.group(1)) if w_match else None

                        if t_final_val is not None and wt_val is not None and w_val is not None:
                             result["t_final"] = t_final_val
                             result["wt"] = wt_val
                             result["w"] = w_val
                             debug_print(f"Extracted Metrics for {jar_basename}: T_final={result['t_final']}, WT={result['wt']}, W={result['w']}")
                        else:
                             checker_status = "CHECKER_ERROR"
                             checker_details = "Correct verdict but failed to parse all metrics (T_final, WT, W) from checker output."
                             debug_print(f"Metric parsing failed for {jar_basename}. Matches: T={t_final_match}, WT={wt_match}, W={w_match}")
                             result["t_final"] = result["wt"] = result["w"] = None

                    except ValueError as e_parse:
                        print(f"ERROR: Checker verdict CORRECT for {jar_basename}, but failed parsing metrics: {e_parse}", file=sys.stderr)
                        checker_status = "CHECKER_ERROR"
                        checker_details = f"Correct verdict but metric parsing failed: {e_parse}"
                        result["t_final"] = result["wt"] = result["w"] = None
                    except Exception as e_re:
                        print(f"ERROR: Regex error during metric parsing for {jar_basename}: {e_re}", file=sys.stderr)
                        checker_status = "CHECKER_ERROR"
                        checker_details = f"Internal tester error (regex) parsing metrics: {e_re}"
                        result["t_final"] = result["wt"] = result["w"] = None
                else:
                    checker_status = "INCORRECT"
                    verdict_line = next((line for line in checker_proc.stdout.splitlines() if line.strip().startswith("Verdict:")), "Verdict: INCORRECT (No details found)")
                    checker_details = verdict_line.strip()
                    debug_print(f"Checker result for {jar_basename}: INCORRECT. Details: {checker_details}")

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

            result["status"] = checker_status
            if checker_status != "CORRECT":
                result["error_details"] = checker_details
                result["t_final"] = result["wt"] = result["w"] = None

        elif CustomTester._interrupted and result["status"] == "RUNNING":
             result["status"] = "INTERRUPTED"
             result["error_details"] = "Run interrupted before checker execution."
             debug_print(f"Marking {jar_basename} as INTERRUPTED (checker skipped due to global interrupt).")
        elif result["status"] != "RUNNING":
             debug_print(f"Skipping checker for {jar_basename} due to JAR status: {result['status']}")
        else:
             debug_print(f"Skipping checker for {jar_basename} (unknown reason). Status: {result['status']}, Interrupt: {CustomTester._interrupted}")


        if result["status"] != "CORRECT":
            result["final_score"] = 0.0
            result["t_final"] = result["wt"] = result["w"] = None

        debug_print(f"Finished run for JAR: {jar_basename}. Final Status: {result['status']}")
        return result

    # --- NEW: Read and parse input data from file ---
    @staticmethod
    def _read_input_data(input_filepath):
        """Reads the specified input file, parses requests, returns requests and max timestamp."""
        requests_data = []
        max_timestamp = 0.0
        try:
            debug_print(f"Reading input data from: {input_filepath}")
            with open(input_filepath, 'r', encoding='utf-8', errors='replace') as f:
                raw_lines = f.readlines()

            # --- Request Parsing Logic (adapted from _generate_data) ---
            pattern = re.compile(r"^\s*\[\s*(\d+\.?\d*)\s*\]\s*(.*)")
            parse_errors = 0
            for line_num, line in enumerate(raw_lines):
                line_stripped = line.strip()
                if not line_stripped: continue # Skip empty lines silently

                match = pattern.match(line_stripped)
                if match:
                    try:
                        timestamp_req = float(match.group(1))
                        req_part = match.group(2).strip()
                        if req_part:
                           requests_data.append((timestamp_req, req_part))
                           max_timestamp = max(max_timestamp, timestamp_req)
                        # else: debug_print(f"Input file line {line_num+1}: Empty request part (ignored): {line}")
                    except ValueError:
                        parse_errors += 1
                        print(f"WARNING: Input file line {line_num+1}: Invalid number format (ignored): {line.strip()}", file=sys.stderr)
                else:
                    parse_errors += 1
                    print(f"WARNING: Input file line {line_num+1}: Invalid line format (ignored): {line.strip()}", file=sys.stderr)

            if parse_errors > 0 and not requests_data:
                 print(f"ERROR: Input file '{input_filepath}' contained lines, but NO valid requests were parsed.", file=sys.stderr)
                 return None, 0.0 # Indicate failure
            elif parse_errors > 0:
                 print(f"WARNING: {parse_errors} lines in input file '{input_filepath}' had parsing errors.", file=sys.stderr)

            if not requests_data and not parse_errors:
                 print(f"INFO: Input file '{input_filepath}' is empty or contains no valid request lines.")
                 # Allow empty input, max_timestamp remains 0

            # Sort requests by timestamp
            requests_data.sort(key=lambda x: x[0])
            debug_print(f"Successfully parsed {len(requests_data)} requests from '{input_filepath}'. Max timestamp: {max_timestamp:.3f}s")
            return requests_data, max_timestamp
            # --- End Request Parsing Logic ---

        except FileNotFoundError:
            print(f"ERROR: Input file not found at '{input_filepath}'", file=sys.stderr)
            return None, 0.0 # Indicate failure
        except Exception as e:
            print(f"ERROR: Unexpected error reading or parsing input file '{input_filepath}': {e}", file=sys.stderr)
            debug_print("Exception in _read_input_data", exc_info=True)
            return None, 0.0 # Indicate failure


    # --- (Keep _calculate_scores as it is from test.py) ---
    @staticmethod
    def _calculate_scores(current_results):
        """Calculates normalized performance scores based on current run results."""
        correct_results = [
            r for r in current_results
            if r["status"] == "CORRECT"
            and r["t_final"] is not None and r["wt"] is not None and r["w"] is not None
        ]
        debug_print(f"Calculating scores based on {len(correct_results)} CORRECT runs with metrics.")

        for r in current_results:
            r["final_score"] = 0.0

        if not correct_results:
            debug_print("No CORRECT results with metrics found for score calculation.")
            return

        t_finals = np.array([r["t_final"] for r in correct_results])
        wts = np.array([r["wt"] for r in correct_results])
        ws = np.array([r["w"] for r in correct_results])
        metrics = {'t_final': t_finals, 'wt': wts, 'w': ws}
        normalized_scores = {}

        for name, values in metrics.items():
            if len(values) == 0: continue
            try:
                x_min = np.min(values)
                x_max = np.max(values)
                x_avg = np.mean(values)
            except Exception as e_np:
                 print(f"ERROR: NumPy error calculating stats for {name}: {e_np}. Skipping scoring for this metric.", file=sys.stderr)
                 continue

            debug_print(f"Metric {name}: min={x_min:.3f}, max={x_max:.3f}, avg={x_avg:.3f}")
            if abs(x_max - x_min) < 1e-9:
                 base_min = x_min
                 base_max = x_max
                 debug_print(f"Metric {name}: All values effectively the same.")
            else:
                base_min = PERF_P_VALUE * x_avg + (1 - PERF_P_VALUE) * x_min
                base_max = PERF_P_VALUE * x_avg + (1 - PERF_P_VALUE) * x_max
                if base_min > base_max:
                    debug_print(f"Metric {name}: Adjusted base_min ({base_min:.3f}) > base_max ({base_max:.3f}), clamping.")
                    base_min = base_max

            debug_print(f"Metric {name}: base_min={base_min:.3f}, base_max={base_max:.3f}")

            normalized = {}
            denominator = base_max - base_min
            is_denominator_zero = abs(denominator) < 1e-9

            for r in correct_results:
                x = r[name]
                r_x = 0.0
                if is_denominator_zero:
                    r_x = 0.0
                else:
                    if x <= base_min + 1e-9:
                        r_x = 0.0
                    elif x >= base_max - 1e-9:
                        r_x = 1.0
                    else:
                        r_x = (x - base_min) / denominator
                normalized[r["jar_file"]] = r_x
                debug_print(f"  NormScore {name} for {r['jar_file']} (val={x:.3f}): {r_x:.4f}")
            normalized_scores[name.upper()] = normalized

        for r in correct_results:
            jar_name = r["jar_file"]
            try:
                r_t = normalized_scores.get('T_FINAL', {}).get(jar_name, 0.0)
                r_wt = normalized_scores.get('WT', {}).get(jar_name, 0.0)
                r_w = normalized_scores.get('W', {}).get(jar_name, 0.0)
                r_prime_t = 1.0 - r_t
                r_prime_wt = 1.0 - r_wt
                r_prime_w = 1.0 - r_w
                s = 15 * (0.3 * r_prime_t + 0.3 * r_prime_wt + 0.4 * r_prime_w)
                r["final_score"] = max(0.0, s)
                debug_print(f"Score for {jar_name}: T_final={r['t_final']:.3f}(Norm:{r_t:.3f}, Inv:{r_prime_t:.3f}), WT={r['wt']:.3f}(Norm:{r_wt:.3f}, Inv:{r_prime_wt:.3f}), W={r['w']:.3f}(Norm:{r_w:.3f}, Inv:{r_prime_w:.3f}) -> Final={r['final_score']:.3f}")
            except KeyError as e_key:
                print(f"WARNING: Missing normalized score component for {jar_name}: {e_key}. Setting final score to 0.", file=sys.stderr)
                r["final_score"] = 0.0
            except Exception as e_score:
                 print(f"ERROR: Unexpected error calculating final score for {jar_name}: {e_score}. Setting score to 0.", file=sys.stderr)
                 debug_print(f"Score calculation exception for {jar_name}", exc_info=True)
                 r["final_score"] = 0.0


    # --- Modify _display_results for single run context ---
    @staticmethod
    def _display_and_log_results(results, input_file_path_used, wall_limit_used):
        """Display results for the current run and log errors AND summary table. Uses Log Lock."""
        log_lines = []
        has_errors_for_log = False

        results.sort(key=lambda x: (-x.get("final_score", 0.0), x.get("wall_time", float('inf')) if x.get("status") == "CORRECT" else float('inf')))

        run_header = f"\n--- Custom Test Results (Input: {input_file_path_used} | Wall Limit: {wall_limit_used:.1f}s) ---"
        header = f"{'JAR':<25} | {'Status':<12} | {'Score':<7} | {'T_final':<10} | {'WT':<10} | {'W':<10} | {'CPU(s)':<8} | {'Wall(s)':<8} | Details"
        separator = "-" * len(header)

        log_lines.append(run_header.replace(" Results ", " Summary "))
        log_lines.append(f"Input Data File: {input_file_path_used}") # Log the input file used
        log_lines.append(header)
        log_lines.append(separator)

        error_log_header_needed = True
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
            details = r.get("error_details", "")[:100] # Truncate for console

            console_line = f"{jar_name:<25} | {status:<12} | {score_str:<7} | {tfin_str:<10} | {wt_str:<10} | {w_str:<10} | {cpu_str:<8} | {wall_str:<8} | {details}"
            result_lines_for_console.append(console_line)

            log_line = f"{jar_name:<25} | {status:<12} | {score_str:<7} | {tfin_str:<10} | {wt_str:<10} | {w_str:<10} | {cpu_str:<8} | {wall_str:<8} | {r.get('error_details', '')}"
            log_lines.append(log_line)

            # --- Error Logging Section (adapted for single run) ---
            if status not in ["CORRECT", "PENDING", "RUNNING", "INTERRUPTED"]:
                has_errors_for_log = True
                if error_log_header_needed:
                    log_lines.append(f"\n--- Custom Test Error Details (Input: {input_file_path_used}) ---")
                    error_log_header_needed = False

                log_lines.append(f"\n--- Error Details for: {jar_name} (Status: {status}) ---")
                log_lines.append(f"  Input File Used: {input_file_path_used}") # Reference the input file
                log_lines.append(f"  Wall Limit Used: {wall_limit_used:.1f}s")
                log_lines.append(f"  Error: {r.get('error_details', '')}")

                # Log path to the *original* input data file (already stored in result)
                log_lines.append("  --- Input Data File ---")
                log_lines.append(f"    Path: {r.get('input_data_path', '<Not Available>')}")
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
            # --- End Error Logging Section ---

        log_lines.append(separator)

        with CustomTester._console_lock:
            print(run_header)
            print(header)
            print(separator)
            for line in result_lines_for_console:
                print(line)
            print(separator)
            print(f"--- End of Test Run ---")

        if CustomTester._log_file_path:
            try:
                with CustomTester._log_lock:
                    with open(CustomTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                        f.write("\n".join(log_lines) + "\n\n")
                debug_print(f"Results and errors for the run written to log.")
            except Exception as e:
                with CustomTester._console_lock:
                    print(f"ERROR: Failed to write results to log file {CustomTester._log_file_path}: {e}", file=sys.stderr)


    # --- Modify _update_history for single run ---
    @staticmethod
    def _update_history(results):
        """Update the results history for the single run. Uses History Lock."""
        with CustomTester._history_lock:
            CustomTester._run_results_history.clear() # Clear previous data if any (though unlikely)
            for r in results:
                if r.get("status") == "INTERRUPTED": continue
                jar_name = r.get("jar_file", "UnknownJAR")
                if jar_name == "UnknownJAR": continue

                history = CustomTester._run_results_history[jar_name] # defaultdict handles creation
                # 'total_runs' is already 1 by default lambda
                score_to_add = 0.0
                if r.get("status") == "CORRECT":
                    history['correct_runs'] = 1 # It's either 0 or 1 for a single run
                    score_to_add = float(r.get("final_score", 0.0) or 0.0)

                history['scores'] = [score_to_add] # Store the single score
                # debug_print(f"History update for {jar_name}: Correct={history['correct_runs']}, Score={score_to_add:.3f}")


    # --- Modify _print_summary for single run ---
    @staticmethod
    def _print_summary():
        """Generates the final summary string for the single run."""
        summary_lines = []

        if CustomTester._interrupted:
            summary_lines.append("\n--- Testing Interrupted ---")
        else:
            summary_lines.append("\n--- Testing Finished ---")

        summary_lines.append(f"Tested against input file: {CustomTester._input_file_path}")

        with CustomTester._history_lock:
            if not CustomTester._run_results_history:
                summary_lines.append("No test results recorded.")
                return "\n".join(summary_lines)

            summary_lines.append("\n--- Final Performance Summary ---")
            summary_data = []
            history_items = list(CustomTester._run_results_history.items())

        for jar_name, data in history_items:
            correct_runs = data['correct_runs'] # Will be 0 or 1
            scores = data['scores'] # List with 0 or 1 score
            final_score = scores[0] if scores else 0.0
            status_str = "CORRECT" if correct_runs == 1 else "FAILED/OTHER" # Simple status
            summary_data.append({
                "jar": jar_name, "final_score": final_score, "status": status_str,
            })

        summary_data.sort(key=lambda x: (-x["final_score"], x["jar"]))

        # Adjusted header for single run summary
        header = f"{'JAR':<25} | {'Final Score':<12} | {'Status'}"
        summary_lines.append(header)
        summary_lines.append("-" * len(header))

        for item in summary_data:
             line = f"{item['jar']:<25} | {item['final_score']:<12.3f} | {item['status']}"
             summary_lines.append(line)

        summary_lines.append("-" * len(header))
        return "\n".join(summary_lines)

    # --- (Keep _signal_handler as it is from test.py) ---
    @staticmethod
    def _signal_handler(sig, frame):
        if not CustomTester._interrupted:
            print("\nCtrl+C detected. Stopping JAR executions and finalizing...", file=sys.stderr)
            CustomTester._interrupted = True
            # Forcing termination might be complex here, let _run_single_jar handle the flag

    # --- Main test method modified for single, custom input run ---
    @staticmethod
    def test(hw_n, jar_path, input_file, wall_time_override=None):
        """Main testing entry point for a single run with custom input."""
        start_time_main = time.monotonic()
        final_results = [] # Store results from all JARs for this run
        wall_time_limit_used = MIN_WALL_TIME_LIMIT

        try:
            # --- Initialization ---
            hw_n_path = str(hw_n).replace(".", os.sep)
            CustomTester._jar_dir = jar_path
            CustomTester._checker_script_path = os.path.abspath(os.path.join(hw_n_path, "checker.py"))
            CustomTester._input_file_path = os.path.abspath(input_file) # Store absolute path
            CustomTester._interrupted = False
            CustomTester._run_results_history.clear()

            os.makedirs(LOG_DIR, exist_ok=True)
            os.makedirs(TMP_DIR, exist_ok=True)
            local_time = time.localtime()
            formatted_time = time.strftime("%Y-%m-%d-%H-%M-%S", local_time)
            input_basename = os.path.splitext(os.path.basename(CustomTester._input_file_path))[0]
            safe_input_basename = re.sub(r'[^\w.-]', '_', input_basename)
            CustomTester._log_file_path = os.path.abspath(os.path.join(LOG_DIR, f"{formatted_time}_custom_run_{safe_input_basename}.log"))

            print(f"INFO: Logging summary and errors to {CustomTester._log_file_path}")
            print(f"INFO: Storing temporary output files in {os.path.abspath(TMP_DIR)}/")
            print(f"INFO: Using custom input file: {CustomTester._input_file_path}")

            if not os.path.exists(CustomTester._checker_script_path): print(f"ERROR: Checker script not found: {CustomTester._checker_script_path}", file=sys.stderr); return
            if not CustomTester._find_jar_files(): print("ERROR: No JAR files found or accessible. Aborting.", file=sys.stderr); return

            signal.signal(signal.SIGINT, CustomTester._signal_handler)

            # --- Read Input Data ---
            print("\nReading input file...")
            requests_data, max_timestamp = CustomTester._read_input_data(CustomTester._input_file_path)

            if requests_data is None:
                print(f"ERROR: Failed to read or parse input file '{CustomTester._input_file_path}'. Aborting.", file=sys.stderr)
                # Log the failure
                if CustomTester._log_file_path:
                     try:
                         with CustomTester._log_lock:
                             with open(CustomTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                                 f.write(f"\n--- TEST ABORTED: FAILED TO READ/PARSE INPUT ---\n")
                                 f.write(f"Input File: {CustomTester._input_file_path}\n\n")
                     except Exception as e_log: print(f"ERROR: Failed to log input read failure: {e_log}", file=sys.stderr)
                return

            # --- Calculate Wall Time Limit ---
            if wall_time_override is not None:
                wall_time_limit_used = max(MIN_WALL_TIME_LIMIT, wall_time_override)
                print(f"INFO: Using user-provided wall time limit: {wall_time_limit_used:.1f}s")
            else:
                calculated_limit = max_timestamp * DEFAULT_WALL_TIME_BUFFER_FACTOR + DEFAULT_WALL_TIME_ADDITIONAL_SECONDS
                wall_time_limit_used = max(MIN_WALL_TIME_LIMIT, calculated_limit)
                print(f"INFO: Calculated wall time limit based on max timestamp ({max_timestamp:.2f}s): {wall_time_limit_used:.1f}s")
            debug_print(f"Final Wall Time Limit set to: {wall_time_limit_used:.2f}s")

            print(f"\nPress Ctrl+C to attempt graceful interruption.")
            print("="*40)
            input(f"Setup complete. Found {len(CustomTester._jar_files)} JARs. Press Enter to begin testing...")
            # CustomTester._clear_screen()
            print("="*40 + "\n")
            print(f"Starting test run against {len(CustomTester._jar_files)} JARs...")

            # --- Run JARs Concurrently ---
            num_jars = len(CustomTester._jar_files)
            # Use a reasonable number of workers, similar to inner parallelism in test.py
            max_workers = min(num_jars, (os.cpu_count() or 4) * 2 + 1)
            debug_print(f"Running {num_jars} JARs with max {max_workers} workers...")

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='JarExec_Custom') as executor:
                if CustomTester._interrupted: return # Check interrupt before submitting

                future_to_jar = {
                    executor.submit(CustomTester._run_single_jar, jar_file, requests_data, CustomTester._input_file_path, wall_time_limit_used): jar_file
                    for jar_file in CustomTester._jar_files
                }
                debug_print(f"Submitted {len(future_to_jar)} JAR tasks.")

                completed_count = 0
                for future in concurrent.futures.as_completed(future_to_jar):
                     if CustomTester._interrupted:
                         debug_print(f"Interrupted during JAR execution processing.")
                         # Allow running futures to finish checking the flag internally

                     jar_file = future_to_jar[future]
                     jar_basename = os.path.basename(jar_file)
                     try:
                         result = future.result()
                         final_results.append(result)
                         completed_count += 1
                         # Simple progress indication
                         print(f"Progress: JAR {completed_count}/{num_jars} completed ({jar_basename}: {result.get('status','?')})", flush=True)
                     except concurrent.futures.CancelledError:
                          print(f"WARNING: Run for {jar_basename} was cancelled (unexpected).", file=sys.stderr)
                     except Exception as exc:
                        print(f'\nERROR: JAR {jar_basename} generated an unexpected exception in its execution thread: {exc}', file=sys.stderr)
                        debug_print(f"Exception from future for {jar_basename}", exc_info=True)
                        final_results.append({
                            "jar_file": jar_basename, "status": "CRASHED", "final_score": 0.0,
                            "error_details": f"Tester thread exception: {exc}", "cpu_time": 0, "wall_time": 0,
                            "t_final": None, "wt": None, "w": None, "stdout_log_path": None,
                            "stderr": [f"Tester thread exception: {exc}", traceback.format_exc()],
                            "input_data_path": CustomTester._input_file_path
                        })
                        completed_count += 1
                        print(f"Progress: JAR {completed_count}/{num_jars} completed (CRASHED)", flush=True)


            print(f"\nAll {num_jars} JAR executions completed or terminated.")

            if CustomTester._interrupted:
                 print("Run interrupted. Final results may be incomplete.")
                 # Proceed to process whatever results were gathered

            # --- Process Results ---
            if final_results:
                print("\nCalculating scores...")
                CustomTester._calculate_scores(final_results)

                print("Displaying and logging results...")
                CustomTester._display_and_log_results(final_results, CustomTester._input_file_path, wall_time_limit_used)

                print("Updating history for summary...")
                CustomTester._update_history(final_results)
            else:
                print("\nNo JAR results were collected (possibly due to early interruption or errors).")


        except Exception as e:
            print(f"\nFATAL ERROR in main testing thread: {e}", file=sys.stderr)
            debug_print("Fatal error in main test execution", exc_info=True)
            if CustomTester._log_file_path:
                 try:
                     with CustomTester._log_lock:
                         with open(CustomTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                             f.write(f"\n\n!!! FATAL MAIN TESTER ERROR !!!\n{time.strftime('%Y-%m-%d %H:%M:%S')}\nError: {e}\n")
                             traceback.print_exc(file=f)
                 except Exception as e_log_main_fatal:
                      print(f"ERROR: Also failed to log fatal main error: {e_log_main_fatal}", file=sys.stderr)

        finally:
            # --- Final Summary ---
            print("\nGenerating final summary...")
            summary = CustomTester._print_summary() # Reads history
            print(summary)
            if CustomTester._log_file_path:
                try:
                     with CustomTester._log_lock:
                        with open(CustomTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                            f.write("\n\n" + "="*20 + " FINAL SUMMARY " + "="*20 + "\n")
                            f.write(summary + "\n")
                            f.write("="* (40 + len(" FINAL SUMMARY ")) + "\n")
                        debug_print("Final summary also written to log file.")
                except Exception as e_log_summary:
                    print(f"ERROR: Failed to write final summary to log file {CustomTester._log_file_path}: {e_log_summary}", file=sys.stderr)

            # --- Cleanup --- (Optional TMP dir cleanup can be added here if desired)
            # print(f"\nTemporary files are in: {os.path.abspath(TMP_DIR)}")

            end_time_main = time.monotonic()
            print(f"\nTotal execution time: {end_time_main - start_time_main:.2f} seconds.")


# --- Main Execution Block ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Elevator Custom Input Tester")
    parser.add_argument("hw_n", help="Homework identifier (e.g., 'hw5'), directory containing checker.py")
    parser.add_argument("jar_path", help="Path to the directory containing student JAR files")
    parser.add_argument("--input-file", default=DEFAULT_INPUT_FILE,
                        help=f"Path to the custom input file (default: {DEFAULT_INPUT_FILE})")
    parser.add_argument("--wall-time-limit", type=float, default=None,
                        help="Override calculated wall time limit (seconds). Minimum still applies.")
    parser.add_argument("--debug", action='store_true', help="Enable detailed debug output to stderr.")

    args = parser.parse_args()

    if args.debug:
        ENABLE_DETAILED_DEBUG = True
        debug_print("Detailed debugging enabled.")

    hw_dir = args.hw_n
    jar_dir = args.jar_path
    input_f = args.input_file

    if not os.path.isdir(hw_dir): print(f"ERROR: Homework directory '{hw_dir}' not found.", file=sys.stderr); sys.exit(1)
    if not os.path.isdir(jar_dir): print(f"ERROR: JAR directory '{jar_dir}' not found.", file=sys.stderr); sys.exit(1)
    # Input file existence checked within _read_input_data

    CustomTester.test(hw_dir, jar_dir, input_f, wall_time_override=args.wall_time_limit)

# --- END OF FILE custom.py ---