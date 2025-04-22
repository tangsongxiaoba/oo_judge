# --- START OF FILE test.py ---

# tester.py
# import ast # No longer needed
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
# import numpy as np # No longer needed
import concurrent.futures
import random # Added for preset selection
import traceback # For logging errors from threads
import yaml
import json # Needed for parsing checker output

# --- Default Configuration, will be replaced by config.yml ---
CPU_TIME_LIMIT = 10.0  # seconds
# FIXED_WALL_TIME_LIMIT = 15.0 # <<< REMOVED - Replaced by MIN_WALL_TIME_LIMIT as the single fixed value
MIN_WALL_TIME_LIMIT = 10.0 # seconds - This will now be the FIXED wall time limit used for all runs
# PERF_P_VALUE = 0.10 # Removed - No longer used for scoring
ENABLE_DETAILED_DEBUG = False # Set to True for verbose debugging
LOG_DIR = "logs" # Define log directory constant
TMP_DIR = "tmp"  # Define temporary file directory constant
DEFAULT_GEN_MAX_TIME = 50.0 # Default generator -t value if not specified in preset (NO LONGER USED FOR WALL LIMIT)
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
    # Modified History: Stores correct/total counts, no scores list needed
    _all_results_history = defaultdict(lambda: {'correct_runs': 0, 'total_runs': 0})
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

    # --- Modified _run_single_jar (Parameter name changed for clarity) ---
    @staticmethod
    def _run_single_jar(jar_path, input_data_path, fixed_wall_limit, round_num): # Renamed current_wall_limit
        """Executes a single JAR, monitors it, saves stdout, and runs the checker."""
        jar_basename = os.path.basename(jar_path)
        # Use the fixed wall limit passed in
        debug_print(f"Starting run for JAR: {jar_basename} with FIXED Wall Limit: {fixed_wall_limit:.2f}s")
        start_wall_time = time.monotonic()
        process = None
        pid = -1
        ps_proc = None
        result = {
            "jar_file": jar_basename, "cpu_time": 0.0, "wall_time": 0.0,
            "status": "PENDING", "error_details": "",
            "stdout_log_path": None, # Path to saved stdout file
            "stderr": [], # Keep stderr in memory for log
            # Removed: "t_final", "wt", "w", "final_score"
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
                return result

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
                # Don't necessarily set error_flag here, process might exit normally after this
                # error_flag.set()
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
                        if not error_flag.is_set() and not JarTester._interrupted:
                            debug_print(f"Monitor loop {monitor_loops}: Process {pid} detected as not running. Setting exitedNormally=True.")
                            process_exited_normally = True
                        break
                except psutil.NoSuchProcess:
                    debug_print(f"Monitor loop {monitor_loops}: psutil.NoSuchProcess caught checking is_running() for PID {pid}. Breaking.")
                    if not error_flag.is_set() and not JarTester._interrupted:
                        # If process disappears without error flag, assume normal exit
                        process_exited_normally = True
                    break # Exit loop, let exit code check handle it

                if error_flag.is_set():
                    debug_print(f"Monitor loop {monitor_loops}: Local error flag is set for PID {pid}. Breaking.")
                    break
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
                    # Ensure process exists before getting CPU times
                    if psutil.pid_exists(pid):
                        # Check if process is still running, might have just exited
                        if ps_proc.is_running():
                             cpu_times = ps_proc.cpu_times()
                             current_cpu_time = cpu_times.user + cpu_times.system
                        else: # Process exists but is not running (zombie?)
                            debug_print(f"Monitor loop {monitor_loops}: Process {pid} exists but is_running() is False. Breaking.")
                            if not error_flag.is_set() and not JarTester._interrupted:
                                process_exited_normally = True
                            break
                    else:
                        # Process disappeared between checks
                        debug_print(f"Monitor loop {monitor_loops}: NoSuchProcess getting CPU times for PID {pid}. Likely exited cleanly. Breaking monitor loop.")
                        if not error_flag.is_set() and not JarTester._interrupted:
                            process_exited_normally = True
                        break
                except psutil.NoSuchProcess: # Catch again just in case
                    debug_print(f"Monitor loop {monitor_loops}: NoSuchProcess (redundant catch) getting CPU times for PID {pid}. Breaking monitor loop.")
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

                # Check against the fixed wall limit passed to the function
                if current_wall_time > fixed_wall_limit:
                    debug_print(f"Monitor loop {monitor_loops}: TLE for PID {pid}")
                    result["status"] = "TLE"
                    result["error_details"] = f"Wall time {current_wall_time:.2f}s exceeded limit {fixed_wall_limit:.2f}s."
                    error_flag.set() # Set local flag on limit exceeded
                    break

                time.sleep(0.05) # Monitoring interval

            debug_print(f"Exited monitoring loop for PID {pid} after {monitor_loops} iterations. Status: {result['status']}, ExitedNormally: {process_exited_normally}")

            # --- Termination and Thread Cleanup ---
            if error_flag.is_set() and pid != -1:
                 debug_print(f"Error flag set or limit exceeded, ensuring process tree killed for PID {pid}")
                 try:
                     if process and process.poll() is None: JarTester._kill_process_tree(pid)
                     elif psutil.pid_exists(pid): JarTester._kill_process_tree(pid)
                     else: debug_print(f"Process {pid} already gone before kill attempt after loop exit.")
                 except Exception as e_kill_loop:
                     print(f"WARNING: Error during kill attempt after loop exit for PID {pid}: {e_kill_loop}", file=sys.stderr)

            debug_print(f"Waiting for I/O threads to finish for PID {pid}")
            thread_join_timeout = 2.0
            threads_to_join = [t for t in [stdout_reader_thread, stderr_reader_thread] if t and t.is_alive()]
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
            except psutil.NoSuchProcess: pass # Process already gone

            # --- Check Exit Code if Process Exited Normally ---
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
                    # If exit code is 0, status remains what it was (likely RUNNING)
                    elif result["status"] == "PENDING": # Should not happen if exitedNormally is true
                         result["status"] = "RUNNING" # Correct it just in case

                except subprocess.TimeoutExpired:
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
            # Ensure final status is set if nothing else set it and process exited
            if process_exited_normally and not final_status_determined:
                result["status"] = "COMPLETED" # Use a generic completed status if exit 0 and no other status set
                debug_print(f"Process {pid} exited normally, setting status to COMPLETED as no error/limit occurred.")
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
                try: JarTester._kill_process_tree(pid)
                except Exception as e_kill_outer: print(f"ERROR: Exception during final kill in outer catch for PID {pid}: {e_kill_outer}", file=sys.stderr)

        finally:
            debug_print(f"Entering finally block for PID {pid}. Status: {result['status']}")
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
            try:
                while True: stdout_lines.append(stdout_queue.get(block=False))
            except queue.Empty: pass
            try:
                while True: stderr_lines.append(stderr_queue.get(block=False))
            except queue.Empty: pass

            result["stderr"] = stderr_lines # Store stderr directly
            debug_print(f"Drained queues for PID {pid}. stdout lines: {len(stdout_lines)}, stderr lines: {len(stderr_lines)}")

            stdout_content = "".join(stdout_lines)
            # Save stdout if content exists OR if the run failed/was interrupted (useful for debugging failures)
            save_stdout = stdout_content or result["status"] not in ["PENDING", "RUNNING", "COMPLETED", "CORRECT"]
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
                 debug_print(f"Not saving empty stdout for {jar_basename} with status {result['status']}.")
                 result["stdout_log_path"] = None

            debug_print(f"Final check join for threads of PID {pid}")
            if stdout_reader_thread and stdout_reader_thread.is_alive(): stdout_reader_thread.join(timeout=0.1)
            if stderr_reader_thread and stderr_reader_thread.is_alive(): stderr_reader_thread.join(timeout=0.1)
            debug_print(f"Exiting finally block for PID {pid}")
            # --- End Draining and Saving ---


        # Run Checker (only if status indicates normal completion and not interrupted globally)
        # Status should be COMPLETED if it finished normally without TLE/CTLE/Crash/Error
        run_checker = (result["status"] == "COMPLETED" and not JarTester._interrupted)

        if run_checker:
            debug_print(f"Running checker for {jar_basename} (PID {pid}) because status is COMPLETED and not globally interrupted.")
            temp_output_file = None
            checker_status = "CHECKER_PENDING"
            checker_details = ""
            try:
                # Create temporary file for JAR's output
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt", encoding='utf-8', dir=TMP_DIR, errors='replace') as tf:
                    tf.write(stdout_content)
                    temp_output_file = tf.name

                # Checker command WITHOUT --tmax
                checker_cmd = [sys.executable, JarTester._checker_script_path, input_data_path, temp_output_file]
                debug_print(f"Checker using input(gen) '{input_data_path}' and output(jar) '{temp_output_file}'")
                debug_print(f"Checker command: {' '.join(checker_cmd)}")

                checker_timeout = 45.0 # Keep checker timeout reasonable
                checker_proc = subprocess.run(
                    checker_cmd, # Use modified command
                    capture_output=True, text=True, timeout=checker_timeout, check=False, encoding='utf-8', errors='replace'
                )
                debug_print(f"Checker for {jar_basename} finished with code {checker_proc.returncode}")

                if checker_proc.stderr:
                    result["stderr"].extend(["--- Checker stderr ---"] + checker_proc.stderr.strip().splitlines())

                # --- New Checker Result Parsing (JSON) ---
                if checker_proc.returncode != 0:
                    checker_status = "CHECKER_ERROR"
                    checker_details = f"Checker process exited with code {checker_proc.returncode}."
                    details_stdout = checker_proc.stdout.strip()
                    details_stderr = checker_proc.stderr.strip()
                    if details_stdout: checker_details += f" stdout: {details_stdout[:200]}"
                    if details_stderr: checker_details += f" stderr: {details_stderr[:200]}"
                    debug_print(f"Checker error for {jar_basename}: Exit code {checker_proc.returncode}")
                else:
                    # Try parsing JSON output
                    try:
                        checker_output = checker_proc.stdout
                        checker_data = json.loads(checker_output)

                        # Check the 'result' field from the parsed JSON
                        checker_result_val = checker_data.get("result")
                        if checker_result_val == "Accepted":
                            checker_status = "CORRECT"
                            checker_details = "Checker accepted the output."
                            debug_print(f"Checker result for {jar_basename}: CORRECT (Accepted)")
                        elif checker_result_val == "Rejected":
                            checker_status = "INCORRECT"
                            # Extract error details from the 'errors' list
                            errors_list = checker_data.get("errors", [{"reason": "Checker reported 'Rejected' but no specific error details found."}])
                            # Format error details nicely
                            formatted_errors = []
                            for err_item in errors_list:
                                cmd_num = err_item.get('command_number', '?')
                                reason = err_item.get('reason', 'Unknown reason')
                                cmd = err_item.get('command', '<N/A>')
                                expected = err_item.get('expected', '<N/A>')
                                actual = err_item.get('actual', '<N/A>')
                                formatted_errors.append(f"Cmd {cmd_num}: {reason} (Cmd: '{cmd}', Exp: '{expected}', Act: '{actual}')")
                            checker_details = "; ".join(formatted_errors)
                            # Truncate if too long for overview, full details in log
                            if len(checker_details) > 300:
                                checker_details = checker_details[:300] + "..."
                            debug_print(f"Checker result for {jar_basename}: INCORRECT (Rejected). Details: {checker_details}")
                        else:
                            # Handle unexpected 'result' values or missing key
                            checker_status = "CHECKER_ERROR"
                            res_val = checker_data.get("result", "None")
                            checker_details = f"Checker returned unexpected/missing result value in JSON: '{res_val}'"
                            debug_print(f"Unexpected checker JSON result for {jar_basename}: {checker_details}. Full data: {checker_data}")

                    except json.JSONDecodeError as e_json:
                        print(f"ERROR: Failed to parse checker JSON output for {jar_basename}: {e_json}", file=sys.stderr)
                        debug_print(f"Checker JSON parse error. Raw output:\n---\n{checker_proc.stdout}\n---")
                        checker_status = "CHECKER_ERROR"
                        checker_details = f"Failed to parse checker JSON output: {e_json}"
                    except Exception as e_parse: # Catch other potential errors during parsing
                        print(f"ERROR: Unexpected error processing checker JSON for {jar_basename}: {e_parse}", file=sys.stderr)
                        checker_status = "CHECKER_ERROR"
                        checker_details = f"Error processing checker JSON: {e_parse}"

            except subprocess.TimeoutExpired:
                print(f"ERROR: Checker timed out for {jar_basename}.", file=sys.stderr)
                checker_status = "CHECKER_ERROR"
                checker_details = f"Checker process timed out after {checker_timeout}s."
            except Exception as e_check:
                print(f"ERROR: Exception running/processing checker for {jar_basename}: {e_check}", file=sys.stderr)
                debug_print(f"Checker exception for {jar_basename}", exc_info=True)
                checker_status = "CHECKER_ERROR"
                checker_details = f"Exception during checker execution/processing: {e_check}"
            finally:
                if temp_output_file and os.path.exists(temp_output_file):
                    try: os.remove(temp_output_file)
                    except Exception as e_rm: print(f"WARNING: Failed to remove temp checker output file {temp_output_file}: {e_rm}", file=sys.stderr)

            # Update result based on checker outcome
            result["status"] = checker_status
            if checker_status != "CORRECT":
                # Prepend original details if any, then add checker details
                # Since original status was COMPLETED, there shouldn't be prior error details
                # original_details = result.get("error_details", "")
                if checker_details:
                    result["error_details"] = f"Checker: {checker_details}"
                # else: keep original details if checker_details is empty (should be none)

        elif JarTester._interrupted and result["status"] == "COMPLETED":
             result["status"] = "INTERRUPTED"
             result["error_details"] = "Run interrupted before checker execution."
             debug_print(f"Marking {jar_basename} as INTERRUPTED (checker skipped due to global interrupt).")
        elif result["status"] != "COMPLETED":
             debug_print(f"Skipping checker for {jar_basename} due to JAR status: {result['status']}")
        else:
             debug_print(f"Skipping checker for {jar_basename} (unknown reason). Status: {result['status']}, Interrupt: {JarTester._interrupted}")

        debug_print(f"Finished run for JAR: {jar_basename}. Final Status: {result['status']}")
        return result

    # --- Modified _generate_data (Removed request parsing) ---
    @staticmethod
    def _generate_data(gen_args_list, round_num, seed_value):
        """
        Calls gen.py with provided args, saves its raw stdout to a unique tmp file.
        Returns (True, path) on success, (False, path_or_None) on failure.
        Does NOT parse or validate the generator's output content.
        """
        # Generate a unique filename for this round's input data
        input_filename = f"input_{seed_value}_{round_num}.txt"
        input_filepath = os.path.abspath(os.path.join(TMP_DIR, input_filename))
        os.makedirs(os.path.dirname(input_filepath), exist_ok=True) # Ensure TMP_DIR exists

        gen_stdout = None
        # Removed requests_data initialization

        try:
            command = [sys.executable, JarTester._gen_script_path] + gen_args_list
            debug_print(f"Running generator: {' '.join(command)}")

            gen_timeout = 20.0
            gen_proc = subprocess.run(
                command, capture_output=True, text=True, timeout=gen_timeout, check=True, encoding='utf-8', errors='replace'
            )
            gen_stdout = gen_proc.stdout
            # gen_success = True # Mark success if run completes without error (done implicitly by reaching write)

            try:
                # Write generator output directly to file
                with open(input_filepath, 'w', encoding='utf-8', errors='replace') as f: f.write(gen_stdout)
                debug_print(f"Generator output written to tmp file: {input_filepath}")
                # Return success and the path
                return True, input_filepath
            except Exception as e_write:
                print(f"ERROR: Failed to write generator output to {input_filepath}: {e_write}", file=sys.stderr)
                # Generation technically succeeded, but saving failed. Return failure but with path.
                return False, input_filepath

            # --- REMOVED Request Parsing Logic ---
            # raw_requests = gen_stdout.strip().splitlines()
            # pattern = re.compile(...)
            # parse_errors = 0
            # for line_num, line in enumerate(raw_requests): ...
            # if not raw_requests and not requests_data and is_n_zero: ...
            # if parse_errors > 0 and not requests_data: ...
            # requests_data.sort(...)
            # debug_print(f"Successfully parsed {len(requests_data)} requests.")
            # return requests_data, input_filepath # Old return

        except FileNotFoundError:
            print(f"ERROR: Generator script not found at '{JarTester._gen_script_path}'", file=sys.stderr)
            return False, None # Generation failed completely
        except subprocess.TimeoutExpired:
            print(f"ERROR: Generator script timed out after {gen_timeout}s.", file=sys.stderr)
            # Try save output if available, return failure and path
            if gen_stdout is not None and input_filepath:
                 try:
                     with open(input_filepath, 'w', encoding='utf-8', errors='replace') as f: f.write(gen_stdout)
                     debug_print(f"Saved timed-out generator stdout to {input_filepath}")
                 except Exception: pass
            return False, input_filepath # Return failure and path (if created)
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
            return False, input_filepath # Return failure and path (if created)
        except Exception as e:
            print(f"ERROR: Unexpected error during data generation: {e}", file=sys.stderr)
            debug_print("Exception in _generate_data", exc_info=True)
            # Try save output if available, return failure and path
            if gen_stdout is not None and input_filepath:
                 try:
                     with open(input_filepath, 'w', encoding='utf-8', errors='replace') as f: f.write(gen_stdout)
                     debug_print(f"Saved generator stdout after unexpected error to {input_filepath}")
                 except Exception: pass
            return False, input_filepath # Return failure and path (if created)

    # --- REMOVED _calculate_scores ---
    # @staticmethod
    # def _calculate_scores(current_results):
    #     ... # This function is no longer needed

    # --- Modify _display_and_log_results (remove score/metrics, display fixed wall limit) ---
    @staticmethod
    def _display_and_log_results(round_num, results, round_preset_cmd, input_data_path, fixed_round_wall_limit): # Renamed param
        """Display results for the current round and log errors AND summary table. Uses Log Lock."""
        log_lines = []
        has_errors_for_log = False

        # Sort: Correct first, then by JAR name alphabetically
        results.sort(key=lambda x: (0 if x.get("status") == "CORRECT" else 1, x.get("jar_file", "")))

        # Display the FIXED wall limit used for this round
        round_header = f"\n--- Test Round {round_num} Results (Preset: {round_preset_cmd} | Wall Limit: {fixed_round_wall_limit:.1f}s) ---"
        # Updated Header: Removed Score, T_final, WT, W
        header = f"{'JAR':<25} | {'Status':<12} | {'CPU(s)':<8} | {'Wall(s)':<8} | Details"
        separator = "-" * len(header)

        log_lines.append(round_header.replace(" Results ", " Summary "))
        log_lines.append(f"Input Data File: {input_data_path if input_data_path else '<Not Available>'}")
        log_lines.append(header)
        log_lines.append(separator)

        error_log_header_needed = True
        result_lines_for_console = []

        for r in results:
            jar_name = r.get("jar_file", "UnknownJAR")
            status = r.get("status", "UNKNOWN")
            # Removed: score, tfin, wt, w variables and formatting
            cpu = r.get("cpu_time", 0.0)
            cpu_str = f"{cpu:.2f}"
            wall = r.get("wall_time", 0.0)
            wall_str = f"{wall:.2f}"
            details = r.get("error_details", "")[:100] # Truncate details for console

            # Updated Line: Removed score/metrics
            console_line = f"{jar_name:<25} | {status:<12} | {cpu_str:<8} | {wall_str:<8} | {details}"
            result_lines_for_console.append(console_line)

            # Updated Log Line: Removed score/metrics
            log_line = f"{jar_name:<25} | {status:<12} | {cpu_str:<8} | {wall_str:<8} | {r.get('error_details', '')}"
            log_lines.append(log_line)

            # --- Error Logging Section (Unchanged logic, details are still relevant) ---
            # Note: Statuses considered non-error are CORRECT, PENDING, RUNNING, COMPLETED, INTERRUPTED
            if status not in ["CORRECT", "PENDING", "RUNNING", "COMPLETED", "INTERRUPTED"]:
                has_errors_for_log = True
                if error_log_header_needed:
                    log_lines.append(f"\n--- Test Round {round_num} Error Details ---")
                    log_lines.append(f"Input Data File for this Round: {input_data_path if input_data_path else '<Not Available>'}")
                    error_log_header_needed = False

                log_lines.append(f"\n--- Error Details for: {jar_name} (Status: {status}) ---")
                log_lines.append(f"  Preset Used: {round_preset_cmd}")
                # Log the fixed wall limit that was applied
                log_lines.append(f"  Wall Limit Applied: {fixed_round_wall_limit:.1f}s")
                log_lines.append(f"  Error: {r.get('error_details', '')}") # Log full details

                log_lines.append("  --- Input Data File ---")
                log_lines.append(f"    Path: {input_data_path if input_data_path else '<Not Available>'}")
                log_lines.append("  --- End Input Data File ---")

                stdout_log = r.get("stdout_log_path")
                log_lines.append("  --- Stdout Log File ---")
                log_lines.append(f"    Path: {stdout_log if stdout_log else '<Not Saved or Error>'}")
                log_lines.append("  --- End Stdout Log File ---")

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

        with JarTester._console_lock:
            print(round_header)
            print(header)
            print(separator)
            for line in result_lines_for_console:
                print(line)
            print(separator)
            print(f"--- End of Round {round_num} ---")

        if JarTester._log_file_path:
            try:
                with JarTester._log_lock:
                    with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                        f.write("\n".join(log_lines) + "\n\n")
                debug_print(f"Results and errors for round {round_num} written to log.")
            except Exception as e:
                with JarTester._console_lock:
                    print(f"ERROR: Failed to write results to log file {JarTester._log_file_path} for round {round_num}: {e}", file=sys.stderr)

    # --- Modify _update_history (remove score list) ---
    @staticmethod
    def _update_history(results):
        """Update the historical results after a round. Uses History Lock."""
        with JarTester._history_lock:
            for r in results:
                if r.get("status") == "INTERRUPTED": continue
                jar_name = r.get("jar_file", "UnknownJAR")
                if jar_name == "UnknownJAR": continue

                history = JarTester._all_results_history[jar_name]
                history['total_runs'] += 1
                # Removed score appending logic
                if r.get("status") == "CORRECT":
                    history['correct_runs'] += 1
                # debug_print(f"History update for {jar_name}: Total={history['total_runs']}, Correct={history['correct_runs']}")


    # --- Modify _print_summary (use pass rate) ---
    @staticmethod
    def _print_summary():
        """Generates the final summary string based on pass rates."""
        summary_lines = []

        if JarTester._interrupted:
            summary_lines.append("\n--- Testing Interrupted ---")
        else:
            summary_lines.append("\n--- Testing Finished ---")

        with JarTester._round_counter_lock:
            total_rounds_assigned = JarTester._round_counter
        summary_lines.append(f"Total test rounds initiated: {total_rounds_assigned}")

        with JarTester._history_lock:
            if not JarTester._all_results_history:
                summary_lines.append("No completed test results recorded in history.")
                return "\n".join(summary_lines)

            summary_lines.append("\n--- Final Summary (Based on Completed Rounds) ---")
            summary_data = []
            history_items = list(JarTester._all_results_history.items())

        for jar_name, data in history_items:
            total_runs = data.get('total_runs', 0)
            correct_runs = data.get('correct_runs', 0)
            # Removed score list processing
            correct_rate = (correct_runs / total_runs * 100) if total_runs > 0 else 0.0
            summary_data.append({
                "jar": jar_name,
                "correct_rate": correct_rate,
                "correct": correct_runs,
                "total": total_runs
            })

        # Sort by Correct Rate (desc), then JAR name
        summary_data.sort(key=lambda x: (-x["correct_rate"], x["jar"]))

        # Updated Header: Removed Avg Score
        header = f"{'JAR':<25} | {'Correct %':<10} | {'Passed/Total':<15}"
        summary_lines.append(header)
        summary_lines.append("-" * len(header))

        for item in summary_data:
             passed_total_str = f"{item['correct']}/{item['total']}"
             # Updated Line: Removed Avg Score
             line = f"{item['jar']:<25} | {item['correct_rate']:<10.1f}% | {passed_total_str:<15}"
             summary_lines.append(line)

        summary_lines.append("-" * len(header))
        return "\n".join(summary_lines)

    # --- (Keep _signal_handler as it is) ---
    @staticmethod
    def _signal_handler(sig, frame):
        if not JarTester._interrupted:
            print("\nCtrl+C detected. Stopping submission of new rounds. Waiting for running rounds to finish...", file=sys.stderr)
            JarTester._interrupted = True

    # --- (Keep _initialize_presets, _preset_dict_to_arg_list as they are) ---
    # Note: _initialize_presets now only parses presets, doesn't use -t for wall time limit calculation later
    @staticmethod
    def _initialize_presets():
        """Parse the raw command strings into argument dictionaries."""
        JarTester._gen_arg_presets = []
        JarTester._raw_preset_commands = []
        # required_time_arg_present = True # Flag no longer needed for wall time limit

        if not JarTester._loaded_preset_commands: # 检查是否成功加载了命令
            print("ERROR: No generator presets were loaded. Cannot initialize.", file=sys.stderr)
            return False

        for cmd_index, cmd_str in enumerate(JarTester._loaded_preset_commands):
            parts = cmd_str.split()
            if not parts or parts[0] != "gen.py":
                print(f"WARNING: Skipping invalid preset format (must start with 'gen.py'): {cmd_str}", file=sys.stderr)
                continue

            args_dict = {}
            # has_time_arg = False # No longer need to track time arg specifically for wall limit
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

                # Track if this is a time argument (still useful for other potential logic, but not wall limit)
                # if arg in ['-t', '--max-time']:
                #     has_time_arg = True

                # Check if next part is potentially a value (doesn't start with '-')
                if i + 1 < len(parts) and not parts[i+1].startswith('-'):
                    value = parts[i+1]
                    # Basic type inference (optional but helpful)
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

            # Check if time argument was found for this preset (Now just informational)
            # if not has_time_arg:
            #     print(f"INFO: Preset '{cmd_str}' does not contain '-t' or '--max-time'. (Wall time limit is fixed anyway).", file=sys.stderr)
                # required_time_arg_present = False # Mark that at least one is missing

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
        # if not required_time_arg_present: # Informational message removed as it's not used for limit
        #      print(f"INFO: Some presets lack explicit time arguments ('-t' or '--max-time'). Fixed wall time limit will be used.")
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

    # --- Modify _run_one_round (use fixed wall limit, check gen success bool) ---
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
        # Use the globally defined fixed wall time limit directly
        round_wall_time_limit = MIN_WALL_TIME_LIMIT
        current_seed = -1 # 初始化 seed
        full_preset_cmd = "<Not Set>" # 初始化 full_preset_cmd

        try:
            # --- Select Preset ---
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

            # --- REMOVED Dynamic Wall Time Limit Calculation ---
            # gen_max_time_str = selected_preset_dict.get('-t') or selected_preset_dict.get('--max-time')
            # round_gen_max_time = DEFAULT_GEN_MAX_TIME # Use default if not specified
            # if gen_max_time_str:
            #     try: round_gen_max_time = float(gen_max_time_str)
            #     except ValueError: print(...)
            # round_wall_time_limit = max(MIN_WALL_TIME_LIMIT, round_gen_max_time * 2.0 + 10.0)
            debug_print(f"Round {round_num}: Using FIXED WALL_TIME_LIMIT: {round_wall_time_limit:.2f}s")
            # --------------------------------------------------

            # 1. Generate Data (No longer parses, returns success bool and path)
            debug_print(f"Round {round_num}: Generating data...")
            # Changed: Expect boolean success flag and path
            gen_success, input_data_path = JarTester._generate_data(gen_args_list, round_num, current_seed)

            # Changed: Check the boolean success flag
            if not gen_success:
                print(f"ERROR [{thread_name}] Round {round_num}: Failed to generate data (Preset: {full_preset_cmd}). Skipping round execution.", file=sys.stderr)
                # Log generation failure (using the log lock)
                if JarTester._log_file_path:
                     try:
                         with JarTester._log_lock:
                             with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                                 f.write(f"\n--- Round {round_num}: Generation FAILED ---\n")
                                 f.write(f"Thread: {thread_name}\n")
                                 f.write(f"Preset: {full_preset_cmd}\n")
                                 # Log the fixed wall limit that would have been used
                                 f.write(f"Wall Limit (intended): {round_wall_time_limit:.1f}s\n")
                                 # Log path even if write failed or requests=None
                                 f.write(f"Attempted Input File: {input_data_path if input_data_path else '<Path Not Generated>'}\n\n")
                     except Exception as e_log:
                          print(f"ERROR [{thread_name}] Round {round_num}: Failed to log generation failure: {e_log}", file=sys.stderr)
                return None # Stop processing this round
            # Changed: Simplified debug message
            debug_print(f"Round {round_num}: Generator output saved to '{input_data_path}'")

            if JarTester._interrupted:
                debug_print(f"Round {round_num}: Interrupted after data generation. Cleaning up input file.")
                if input_data_path and os.path.exists(input_data_path) and not CLEANUP_SUCCESSFUL_ROUNDS: # Keep if failed & not cleanup mode
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
            # Limit workers based on JAR count and CPU cores (maybe slightly more than cores due to I/O wait)
            max_workers_per_round = min(len(JarTester._jar_files), (os.cpu_count() or 4) + 1)
            debug_print(f"Round {round_num}: Running {len(JarTester._jar_files)} JARs with max {max_workers_per_round} inner workers...")

            # Inner ThreadPoolExecutor for JARs within this round
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers_per_round, thread_name_prefix=f'JarExec_R{round_num}') as executor:
                if JarTester._interrupted:
                    debug_print(f"Round {round_num}: Interrupted before submitting JAR tasks.")
                    if input_data_path and os.path.exists(input_data_path) and not CLEANUP_SUCCESSFUL_ROUNDS:
                        try: os.remove(input_data_path)
                        except Exception: pass
                    return None

                future_to_jar = {
                    # Pass the fixed wall time limit here
                    executor.submit(JarTester._run_single_jar, jar_file, input_data_path, round_wall_time_limit, round_num): jar_file
                    for jar_file in JarTester._jar_files
                }
                debug_print(f"Round {round_num}: Submitted {len(future_to_jar)} JAR tasks.")

                completed_count = 0
                for future in concurrent.futures.as_completed(future_to_jar):
                     if JarTester._interrupted:
                         debug_print(f"Round {round_num}: Interrupted during JAR execution processing.")
                         # Don't break, let already running tasks finish if possible, but stop processing results

                     jar_file = future_to_jar[future]
                     jar_basename = os.path.basename(jar_file)
                     try:
                         result = future.result()
                         result["round_num"] = round_num # Add round num to result dict
                         results_this_round.append(result)
                         completed_count += 1
                     except concurrent.futures.CancelledError:
                          # This shouldn't happen normally unless we cancel futures on interrupt (which we don't currently)
                          print(f"WARNING [{thread_name}] Round {round_num}: Run for {jar_basename} was cancelled (unexpected).", file=sys.stderr)
                     except Exception as exc:
                        print(f'\nERROR [{thread_name}] Round {round_num}: JAR {jar_basename} generated an unexpected exception in its execution thread: {exc}', file=sys.stderr)
                        debug_print(f"Round {round_num}: Exception from future for {jar_basename}", exc_info=True)
                        # Create a dummy result indicating the crash
                        results_this_round.append({
                            "jar_file": jar_basename, "status": "CRASHED",
                            "error_details": f"Tester thread exception: {exc}", "cpu_time": 0, "wall_time": 0,
                            "stdout_log_path": None, # Removed metrics
                            "stderr": [f"Tester thread exception: {exc}", traceback.format_exc()],
                            "input_data_path": input_data_path, "round_num": round_num
                        })
                        completed_count += 1
                     # No else needed, successful results are appended in the try block

            debug_print(f"Round {round_num}: All {len(future_to_jar)} JAR executions completed or terminated.")

            if JarTester._interrupted:
                debug_print(f"Round {round_num}: Interrupted after JAR execution completed. Skipping history update and further processing.")
                # Decide whether to keep files on interrupt based on cleanup setting
                if input_data_path and os.path.exists(input_data_path) and not CLEANUP_SUCCESSFUL_ROUNDS:
                    debug_print(f"  Keeping input file (interrupt + no cleanup): {input_data_path}")
                elif input_data_path and os.path.exists(input_data_path):
                    try:
                        os.remove(input_data_path)
                        debug_print(f"  Deleting input file (interrupt + cleanup enabled): {input_data_path}")
                    except Exception: pass
                # Also clean up output files if cleanup enabled
                if CLEANUP_SUCCESSFUL_ROUNDS:
                    for r in results_this_round:
                        stdout_path = r.get("stdout_log_path")
                        if stdout_path and os.path.exists(stdout_path):
                            try:
                                os.remove(stdout_path)
                                debug_print(f"  Deleting output file (interrupt + cleanup): {stdout_path}")
                            except Exception: pass

                return None # Stop processing this round

            # Log errors to separate file (unchanged logic, uses fixed limit in log)
            failed_jars_in_round = [r for r in results_this_round if r.get("status") not in ["CORRECT", "COMPLETED", "PENDING", "RUNNING", "INTERRUPTED"]]
            if failed_jars_in_round:
                error_log_filename = f"errors_{round_num}_{current_seed}.log"
                error_log_filepath = os.path.abspath(os.path.join(LOG_DIR, error_log_filename))
                debug_print(f"Round {round_num}: Failures detected. Logging errors to separate file: {error_log_filepath}")
                try:
                    os.makedirs(LOG_DIR, exist_ok=True) # Ensure log dir exists
                    with open(error_log_filepath, "w", encoding="utf-8", errors='replace') as f_err:
                        f_err.write(f"--- Error Log for Test Round {round_num} ---\n")
                        f_err.write(f"Seed: {current_seed}\n")
                        f_err.write(f"Preset Command Used: {full_preset_cmd}\n")
                        f_err.write(f"Input Data File Path: {input_data_path if input_data_path else '<Not Available>'}\n")
                        # Log the fixed wall limit applied
                        f_err.write(f"Wall Time Limit Applied: {round_wall_time_limit:.1f}s\n")
                        f_err.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f_err.write("-" * 40 + "\n\n")
                        for r in failed_jars_in_round:
                            jar_name = r.get("jar_file", "UnknownJAR")
                            status = r.get("status", "UNKNOWN")
                            f_err.write(f"--- Failing JAR: {jar_name} ---\n")
                            f_err.write(f"Status: {status}\n")
                            f_err.write(f"Error Details: {r.get('error_details', '')}\n")
                            stdout_log = r.get("stdout_log_path")
                            f_err.write(f"Stdout Log File Path: {stdout_log if stdout_log else '<Not Saved or Error>'}\n")
                            f_err.write("--- Stderr Content ---\n")
                            stderr = r.get("stderr", [])
                            if stderr:
                                MAX_ERR_LOG_LINES = 200
                                for i, err_line in enumerate(stderr):
                                    if i < MAX_ERR_LOG_LINES: f_err.write(f"  {err_line.strip()}\n")
                                    elif i == MAX_ERR_LOG_LINES: f_err.write(f"  ... (stderr truncated after {MAX_ERR_LOG_LINES} lines)\n"); break
                                if len(stderr) <= MAX_ERR_LOG_LINES: f_err.write("  <End of Stderr>\n")
                            else:
                                f_err.write("  <No stderr captured>\n")
                            f_err.write("--- End Stderr ---\n\n")
                    print(f"INFO [{thread_name}] Round {round_num}: Errors occurred. Details saved to {error_log_filepath}")
                except Exception as e_err_log:
                    print(f"ERROR [{thread_name}] Round {round_num}: Failed to write separate error log file {error_log_filepath}: {e_err_log}", file=sys.stderr)


            # 3. REMOVED: Calculate Performance Scores
            # debug_print(f"Round {round_num}: Calculating scores...") # Removed
            # JarTester._calculate_scores(results_this_round) # Removed

            # Cleanup successful round files (logic adjusted for pass/fail)
            if CLEANUP_SUCCESSFUL_ROUNDS and results_this_round:
                all_passed = True
                failed_jar_outputs_to_keep = []
                successful_jar_outputs_to_delete = []

                for r in results_this_round:
                    status = r.get("status")
                    stdout_path = r.get("stdout_log_path")

                    if status != "CORRECT":
                        all_passed = False
                        if stdout_path and os.path.exists(stdout_path):
                            failed_jar_outputs_to_keep.append(stdout_path)
                    else: # CORRECT
                        if stdout_path and os.path.exists(stdout_path):
                            successful_jar_outputs_to_delete.append(stdout_path)

                if all_passed:
                    files_to_remove = []
                    if input_data_path and os.path.exists(input_data_path):
                        files_to_remove.append(input_data_path)
                    files_to_remove.extend(successful_jar_outputs_to_delete)

                    if files_to_remove:
                        debug_print(f"Round {round_num}: All JARs passed. Cleaning up {len(files_to_remove)} temporary files...")
                        for file_path in files_to_remove:
                            try:
                                os.remove(file_path)
                                debug_print(f"  Deleted: {file_path}")
                            except OSError as e:
                                print(f"WARNING [{threading.current_thread().name}] Round {round_num}: Failed to delete temp file {file_path}: {e}", file=sys.stderr)
                            except Exception as e:
                                print(f"WARNING [{threading.current_thread().name}] Round {round_num}: Unexpected error deleting temp file {file_path}: {e}", file=sys.stderr)
                else:
                    # If not all passed, keep input data, delete only successful outputs
                    if successful_jar_outputs_to_delete:
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
                    if input_data_path and os.path.exists(input_data_path):
                        debug_print(f"  Keeping input file (due to failures): {input_data_path}")
            elif not CLEANUP_SUCCESSFUL_ROUNDS and input_data_path and os.path.exists(input_data_path):
                 debug_print(f"Round {round_num}: Cleanup disabled. Keeping input file: {input_data_path}")


            # Prepare results package to return
            round_results = {
                "round_num": round_num,
                "results": results_this_round,
                "preset_cmd": full_preset_cmd,
                "input_path": input_data_path,
                "wall_limit": round_wall_time_limit # Pass the fixed limit used
            }

            print(f"INFO [{thread_name}]: Finished Test Round {round_num} ({selected_preset_cmd})")
            return round_results

        except Exception as e_round:
            print(f"\nFATAL ERROR in worker thread for Round {round_num}: {e_round}", file=sys.stderr)
            debug_print(f"Fatal error in _run_one_round {round_num}", exc_info=True)
            if JarTester._log_file_path:
                try:
                    with JarTester._log_lock:
                        with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                            f.write(f"\n\n!!! FATAL WORKER ERROR (Round {round_num}) !!!\n")
                            f.write(f"Thread: {thread_name}\n")
                            f.write(f"Preset: {selected_preset_cmd}\n") # Use selected_preset_cmd as full_preset_cmd might not be set
                            f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                            f.write(f"Error: {e_round}\n")
                            traceback.print_exc(file=f)
                            f.write("\n")
                except Exception as e_log_fatal:
                    print(f"ERROR [{thread_name}] Round {round_num}: Also failed to log fatal worker error: {e_log_fatal}", file=sys.stderr)
            # Ensure input file is handled correctly on fatal error
            if input_data_path and os.path.exists(input_data_path):
                if not CLEANUP_SUCCESSFUL_ROUNDS:
                     debug_print(f"Round {round_num}: Worker exception, cleanup disabled, preserving input file {input_data_path}.")
                else:
                     # Generally keep files on error even if cleanup is on, for debugging
                     debug_print(f"Round {round_num}: Worker exception occurred, preserving input file {input_data_path} despite cleanup mode.")
            return None # Indicate round failed

    # --- Main test method (unchanged except call removal and MIN_WALL_TIME_LIMIT usage) ---
    @staticmethod
    def test():
        """Main testing entry point, runs multiple rounds in parallel."""
        global ENABLE_DETAILED_DEBUG, LOG_DIR, TMP_DIR, CLEANUP_SUCCESSFUL_ROUNDS, MIN_WALL_TIME_LIMIT # Add MIN_WALL_TIME_LIMIT
        start_time_main = time.monotonic()
        config = None
        try:
            # --- Initialization (Loads config, sets paths, etc.) ---
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
            # Get Wall Time Limit from config, fallback to default MIN_WALL_TIME_LIMIT
            wall_time_limit_config = test_config.get('wall_time_limit', MIN_WALL_TIME_LIMIT)

            if hw_n is None or not isinstance(hw_n, int):
                print(f"ERROR: 'hw' value missing or invalid in {config_path}.", file=sys.stderr)
                return
            if not jar_base_dir or not isinstance(jar_base_dir, str):
                print(f"ERROR: 'jar_base_dir' value missing or invalid in {config_path}.", file=sys.stderr)
                return
            if not isinstance(parallel_rounds_config, int) or parallel_rounds_config < 1:
                print(f"WARNING: 'test.parallel' value invalid in {config_path}. Using default: {DEFAULT_PARALLEL_ROUNDS}.", file=sys.stderr)
                parallel_rounds_config = DEFAULT_PARALLEL_ROUNDS
            # Validate configured wall time limit
            try:
                 config_limit_float = float(wall_time_limit_config)
                 if config_limit_float > 0:
                      MIN_WALL_TIME_LIMIT = config_limit_float # Override default with config value
                      print(f"INFO: Using Fixed Wall Time Limit from config: {MIN_WALL_TIME_LIMIT:.1f}s")
                 else:
                      print(f"WARNING: 'test.wall_time_limit' in {config_path} must be positive. Using default: {MIN_WALL_TIME_LIMIT:.1f}s.", file=sys.stderr)
            except (ValueError, TypeError):
                 print(f"WARNING: 'test.wall_time_limit' value '{wall_time_limit_config}' invalid in {config_path}. Using default: {MIN_WALL_TIME_LIMIT:.1f}s.", file=sys.stderr)


            ENABLE_DETAILED_DEBUG = bool(debug_enabled_config)
            LOG_DIR = logs_dir_config
            TMP_DIR = tmp_dir_config
            CLEANUP_SUCCESSFUL_ROUNDS = bool(cleanup_enabled_config)

            # Update debug status immediately if changed
            if ENABLE_DETAILED_DEBUG:
                debug_print("Detailed debugging enabled via config.")
            if CLEANUP_SUCCESSFUL_ROUNDS:
                debug_print("Cleanup mode enabled via config.")
            else:
                debug_print("Cleanup mode disabled via config.")


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
                    return
                with open(presets_yaml_path, 'r', encoding='utf-8') as f_presets:
                    loaded_presets = yaml.safe_load(f_presets)

                if not isinstance(loaded_presets, list):
                    print(f"ERROR: Content of '{presets_yaml_path}' is not a valid YAML list.", file=sys.stderr)
                    return
                if not all(isinstance(item, str) for item in loaded_presets):
                    print(f"ERROR: Not all items in '{presets_yaml_path}' are strings. Each preset must be a string.", file=sys.stderr)
                    return

                JarTester._loaded_preset_commands = loaded_presets
                print(f"INFO: Successfully loaded {len(JarTester._loaded_preset_commands)} generator presets.")

            except yaml.YAMLError as e_yaml:
                print(f"ERROR: Failed to parse generator presets file '{presets_yaml_path}': {e_yaml}", file=sys.stderr)
                return
            except Exception as e_load:
                print(f"ERROR: Unexpected error loading generator presets file '{presets_yaml_path}': {e_load}", file=sys.stderr)
                return

            JarTester._interrupted = False
            JarTester._round_counter = 0
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
            # The wall time limit is now fixed and already printed above if loaded from config
            # print(f"INFO: Using fixed Wall Time Limit: {MIN_WALL_TIME_LIMIT:.1f}s")

            if hce_filter_enabled:
                print("INFO: HCE filter enabled. Removing non-HCE presets...")
                original_count = len(JarTester._loaded_preset_commands)
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
                print("="*40 + "\n")

            # --- Main Parallel Round Execution Loop ---
            active_futures = set()
            processed_round_count = 0
            max_rounds = None # Run indefinitely until Ctrl+C unless max_rounds is set

            with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_rounds_config, thread_name_prefix='RoundRunner') as round_executor:
                while not JarTester._interrupted:
                    # Check if we need to submit more rounds
                    while len(active_futures) < parallel_rounds_config and not JarTester._interrupted:
                        round_num = JarTester._get_next_round_number()
                        debug_print(f"MainLoop: Submitting round {round_num}")
                        future = round_executor.submit(JarTester._run_one_round, round_num)
                        active_futures.add(future)

                    if JarTester._interrupted:
                         debug_print("MainLoop: Interrupt detected, stopping submission.")
                         break # Exit the outer while loop

                    # Wait for at least one round to complete before checking again
                    debug_print(f"MainLoop: Waiting for completed rounds (Active: {len(active_futures)})...")
                    done, active_futures = concurrent.futures.wait(active_futures, return_when=concurrent.futures.FIRST_COMPLETED)
                    debug_print(f"MainLoop: {len(done)} round(s) completed.")

                    for future in done:
                        try:
                            round_result_package = future.result() # Get result from completed future
                            processed_round_count += 1

                            if round_result_package:
                                # Display/Log Results (modified function, takes fixed limit)
                                debug_print(f"MainLoop: Processing results for round {round_result_package['round_num']}...")
                                JarTester._display_and_log_results(
                                    round_result_package["round_num"],
                                    round_result_package["results"],
                                    round_result_package["preset_cmd"],
                                    round_result_package["input_path"],
                                    round_result_package["wall_limit"] # Pass the fixed limit stored in the package
                                )

                                # Update History (modified function)
                                if not JarTester._interrupted: # Only update history if not interrupted during processing
                                    debug_print(f"MainLoop: Updating history for round {round_result_package['round_num']}...")
                                    JarTester._update_history(round_result_package["results"])
                                else:
                                    debug_print(f"MainLoop: Skipping history update for round {round_result_package['round_num']} due to interrupt.")

                            else:
                                # Round function returned None, likely due to an error logged within the thread
                                debug_print(f"MainLoop: Round failed to return results (error logged previously or skipped).")

                        except Exception as exc:
                            # Catch errors during future.result() or subsequent processing
                            print(f'\nERROR: Main loop caught exception processing a round future: {exc}', file=sys.stderr)
                            debug_print("Exception processing round future", exc_info=True)
                            processed_round_count += 1 # Increment even on error
                            # Attempt to log the error if possible
                            if JarTester._log_file_path:
                                try:
                                    with JarTester._log_lock:
                                        with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                                             f.write(f"\n\n!!! ERROR PROCESSING ROUND RESULT (Main Loop) !!!\n")
                                             f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                                             f.write(f"Error: {exc}\n")
                                             traceback.print_exc(file=f)
                                             f.write("\n")
                                except Exception: pass # Avoid error loops

                # --- End of main loop (exited due to interrupt or potential future max_rounds) ---
                print("\nMainLoop: Exited main execution loop.")
                if JarTester._interrupted:
                    print("MainLoop: Interrupt received. Waiting for remaining active rounds to complete...")
                    if active_futures:
                        # Wait for all remaining futures submitted before interrupt
                        (done_after_interrupt, not_done) = concurrent.futures.wait(active_futures, return_when=concurrent.futures.ALL_COMPLETED)
                        debug_print(f"MainLoop: {len(done_after_interrupt)} remaining rounds finished after interrupt.")
                        # Process results of rounds that finished *after* interrupt was detected but before shutdown
                        for future in done_after_interrupt:
                            try:
                                round_result_package = future.result()
                                processed_round_count += 1
                                if round_result_package:
                                    # Display final results, but don't update history
                                    debug_print(f"MainLoop: Processing final results for round {round_result_package['round_num']} (post-interrupt)...")
                                    JarTester._display_and_log_results(
                                        round_result_package["round_num"],
                                        round_result_package["results"],
                                        round_result_package["preset_cmd"],
                                        round_result_package["input_path"],
                                        round_result_package["wall_limit"]
                                    )
                                    debug_print(f"MainLoop: Skipping history update for round {round_result_package['round_num']} (post-interrupt).")
                                else:
                                    debug_print(f"MainLoop: Post-interrupt round failed to return results.")
                            except Exception as exc:
                                print(f'\nERROR: Main loop caught exception processing a post-interrupt round future: {exc}', file=sys.stderr)
                                debug_print("Exception processing post-interrupt round future", exc_info=True)
                                processed_round_count += 1
                    print("MainLoop: All active rounds have finished after interrupt.")
                else:
                    print("MainLoop: Finished normally.") # Should only happen if max_rounds was implemented and reached

            # --- End of outer executor block ---

        except Exception as e:
            print(f"\nFATAL ERROR in main testing thread: {e}", file=sys.stderr)
            debug_print("Fatal error in main test execution", exc_info=True)
            JarTester._interrupted = True # Ensure interrupt flag is set on fatal error
            if JarTester._log_file_path:
                 try:
                     with JarTester._log_lock:
                         with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                             f.write(f"\n\n!!! FATAL MAIN TESTER ERROR !!!\n{time.strftime('%Y-%m-%d %H:%M:%S')}\nError: {e}\n")
                             traceback.print_exc(file=f)
                 except Exception as e_log_main_fatal:
                      print(f"ERROR: Also failed to log fatal main error: {e_log_main_fatal}", file=sys.stderr)

        finally:
            # --- Final Summary (Modified function) ---
            print("\nCalculating final summary...")
            summary = JarTester._print_summary()
            print(summary)
            if JarTester._log_file_path:
                try:
                     with JarTester._log_lock:
                        with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                            f.write("\n\n" + "="*20 + " FINAL SUMMARY " + "="*20 + "\n")
                            f.write(summary + "\n")
                            f.write("="* (40 + len(" FINAL SUMMARY ")) + "\n")
                        debug_print("Final summary also written to log file.")
                except Exception as e_log_summary:
                    print(f"ERROR: Failed to write final summary to log file {JarTester._log_file_path}: {e_log_summary}", file=sys.stderr)

            # --- Cleanup Information ---
            try:
                if os.path.exists(TMP_DIR):
                    print(f"\nTemporary files are in: {os.path.abspath(TMP_DIR)}")
                    if not CLEANUP_SUCCESSFUL_ROUNDS:
                         print("Cleanup was disabled. Manual cleanup of temporary files may be needed.")
                    elif JarTester._interrupted:
                         print("Testing was interrupted. Some temporary files might remain if cleanup was enabled.")
                    else: # Cleanup enabled and finished normally
                         # Check if tmp dir is empty (or only contains non-round files)
                         try:
                            remaining_files = [f for f in os.listdir(TMP_DIR) if f.startswith(('input_', 'output_'))]
                            if not remaining_files:
                                print("Cleanup was enabled and temporary round files appear to have been removed.")
                            else:
                                print(f"Cleanup was enabled, but {len(remaining_files)} round-related files remain (likely from failed rounds).")
                         except Exception:
                             print("Cleanup was enabled. Could not verify status of temporary files.")

            except Exception as e_clean_info:
                print(f"WARNING: Error checking temporary directory status: {e_clean_info}", file=sys.stderr)


            end_time_main = time.monotonic()
            print(f"\nTotal execution time: {end_time_main - start_time_main:.2f} seconds.")

# Example Usage (if running this script directly)
# if __name__ == "__main__":
#     # Ensure config.yml exists and is correctly populated
#     # Example config.yml content:
#     # hw: 6
#     # jar_base_dir: "path/to/your/jars"
#     # logs_dir: "my_logs"
#     # tmp_dir: "my_tmp"
#     # test:
#     #  parallel: 8
#     #  debug: false
#     #  cleanup: true
#     #  hce: false
#     #  wall_time_limit: 20.0 # Optional: Sets the fixed wall time limit
#
#     JarTester.test()