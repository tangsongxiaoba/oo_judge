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
import random # Added for preset selection
import shutil # Needed for potential future cleanup, good practice

# --- Configuration ---
CPU_TIME_LIMIT = 10.0  # seconds
MIN_WALL_TIME_LIMIT = 120.0 # seconds - Renamed: Minimum wall time limit
# CHECKER_TMAX removed, will be derived dynamically
PERF_P_VALUE = 0.10
ENABLE_DETAILED_DEBUG = False # Set to True for verbose debugging
LOG_DIR = "logs" # Define log directory constant
TMP_DIR = "tmp"  # Define temporary file directory constant
DEFAULT_GEN_MAX_TIME = 50.0 # Default generator -t value if not specified in preset

# --- Generator Argument Presets ---
# List of command strings for gen.py
GEN_PRESET_COMMANDS = [
    # === Baseline ===
    # "gen.py -n 25 -t 50.0",
    # === Load & Density ===
    "gen.py -n 70 -t 40.0 --min-interval 0.0 --max-interval 0.5 --hce",
    "gen.py -n 98 -t 70.0 --min-interval 0.1 --max-interval 0.8",
    "gen.py -n 8 -t 100.0 --min-interval 10.0 --max-interval 15.0",
    "gen.py -n 75 -t 150.0 --min-interval 0.5 --max-interval 2.5",
    # "gen.py -n 1 -t 10.0",
    "gen.py -n 2 -t 10.0 --min-interval 0.1 --max-interval 0.5",
    # "gen.py -n 1 -t 10.0 --hce",
    "gen.py -n 2 -t 10.0 --hce --min-interval 0.2 --max-interval 0.8",
    # === Timing & Bursts ===
    "gen.py -n 30 --start-time 1.0 --max-time 10.0 --force-start-requests 30", # Uses --max-time
    "gen.py -n 20 --start-time 1.0 --max-time 30.0 --force-end-requests 20", # Uses --max-time
    "gen.py -n 15 --start-time 5.0 --max-time 5.0",                             # Uses --max-time
    "gen.py -n 45 --start-time 10.0 --max-time 10.1 --burst-size 45 --burst-time 10.0", # Uses --max-time
    "gen.py -n 60 -t 50.0 --burst-size 30",
    "gen.py -n 90 -t 80.0 --start-time 2.0 --force-start-requests 25 --burst-size 30 --burst-time 41.0 --force-end-requests 25",
    "gen.py -n 65 -t 40.0 --hce --force-start-requests 20 --burst-size 25 --burst-time 8.0",
    "gen.py -n 40 -t 49.5 --hce --burst-size 20 --burst-time 48.0",
    "gen.py -n 20 -t 100.0 --min-interval 8.0 --max-interval 12.0 --burst-size 8 --burst-time 50.0",
    "gen.py -n 30 -t 30.0 --min-interval 0.5 --max-interval 0.5",
    # === Priority ===
    "gen.py -n 60 -t 30.0 --priority-bias extremes --priority-bias-ratio 0.9",
    "gen.py -n 55 -t 40.0 --priority-bias middle --priority-bias-ratio 0.9 --priority-middle-range 10",
    "gen.py -n 50 -t 40.0 --priority-bias middle --priority-bias-ratio 0.8 --priority-middle-range 2",
    "gen.py -n 15 -t 120.0 --min-interval 5.0 --max-interval 10.0 --priority-bias extremes --priority-bias-ratio 0.9",
    "gen.py -n 40 -t 30.0 --priority-bias extremes --priority-bias-ratio 1.0",
    # === Elevator Focus ===
    "gen.py -n 40 -t 30.0 --focus-elevator 1 --focus-ratio 1.0 --hce", # Added -t
    "gen.py -n 70 -t 48.0 --hce --focus-elevator 2 --focus-ratio 0.8",
    "gen.py -n 80 -t 60.0 --focus-elevator 4 --focus-ratio 0.9",
    "gen.py -n 40 -t 30.0 --focus-elevator 5 --focus-ratio 0.0",
    # === Floor Patterns ===
    "gen.py -n 50 -t 60.0 --extreme-floor-ratio 0.8",
    # === Complex Combinations ===
    "gen.py -n 65 -t 45.0 --start-time 1.0 --force-start-requests 5 --force-end-requests 5 --burst-size 15 --burst-time 20.0 --focus-elevator 3 --focus-ratio 0.5 --priority-bias extremes --priority-bias-ratio 0.3 --hce",
    "gen.py -n 60 -t 20.0 --hce --min-interval 0.0 --max-interval 0.2 --priority-bias extremes --priority-bias-ratio 0.4",
    "gen.py -n 55 -t 45.0 --hce --extreme-floor-ratio 0.6 --priority-bias middle --priority-bias-ratio 0.7 --priority-middle-range 15",
    "gen.py -n 50 -t 45.0 --hce --extreme-floor-ratio 0.7 --priority-bias extremes --priority-bias-ratio 0.6",
    "gen.py -n 60 -t 70.0 --extreme-floor-ratio 0.7 --priority-bias extremes --priority-bias-ratio 0.7",
]


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
    # _persistent_request_file_path removed
    _all_results_history = defaultdict(lambda: {'correct_runs': 0, 'total_runs': 0, 'scores': []})
    _gen_arg_presets = []
    _raw_preset_commands = []

    # --- Helper: Clear Screen ---
    @staticmethod
    def _clear_screen():
        """Clears the terminal screen."""
        if ENABLE_DETAILED_DEBUG: return
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

    @staticmethod
    def _timed_input_feeder(process, requests, start_event, error_flag):
        """Thread function to feed input to the JAR process at specific times."""
        pid = process.pid
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
                    # debug_print(f"Input feeder feeding request {i+1}/{request_count} to PID {pid}: {req_data}")
                    process.stdin.write(req_data + '\n')
                    process.stdin.flush()
                except (BrokenPipeError, OSError) as e:
                    if not error_flag.is_set() and not JarTester._interrupted:
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
        debug_print(f"Output reader ({stream_name}) started for PID {pid}")
        try:
            for line_num, line in enumerate(iter(pipe.readline, '')):
                if error_flag.is_set() or JarTester._interrupted:
                     debug_print(f"Output reader ({stream_name}) stopping early for PID {pid}")
                     break
                output_queue.put(line)
            debug_print(f"Output reader ({stream_name}) finished iter loop for PID {pid}")
        except ValueError:
            if not error_flag.is_set() and not JarTester._interrupted:
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
    def _run_single_jar(jar_path, requests_data, input_data_path, current_wall_limit): # Changed gen_output_path to input_data_path
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
        }
        input_feeder_thread = None
        stdout_reader_thread = None
        stderr_reader_thread = None
        stdout_queue = queue.Queue()
        stderr_queue = queue.Queue()
        feeder_start_event = threading.Event()
        error_flag = threading.Event()

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
                raise e_attach

            debug_print(f"Starting I/O threads for PID {pid}")
            input_feeder_thread = threading.Thread(target=JarTester._timed_input_feeder, args=(process, requests_data, feeder_start_event, error_flag), daemon=True)
            stdout_reader_thread = threading.Thread(target=JarTester._output_reader, args=(process.stdout, stdout_queue, "stdout", pid, error_flag), daemon=True)
            stderr_reader_thread = threading.Thread(target=JarTester._output_reader, args=(process.stderr, stderr_queue, "stderr", pid, error_flag), daemon=True)
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
                        if not error_flag.is_set() and not JarTester._interrupted:
                            debug_print(f"Monitor loop {monitor_loops}: Process {pid} detected as not running. Setting exitedNormally=True.")
                            process_exited_normally = True
                        break
                except psutil.NoSuchProcess:
                    debug_print(f"Monitor loop {monitor_loops}: psutil.NoSuchProcess caught checking is_running() for PID {pid}. Breaking.")
                    if not error_flag.is_set() and not JarTester._interrupted:
                        process_exited_normally = True
                    # Error flag not necessarily set here, could be normal exit
                    break # Exit loop, let exit code check handle it

                if error_flag.is_set():
                    debug_print(f"Monitor loop {monitor_loops}: Error flag is set for PID {pid}. Breaking.")
                    break
                if JarTester._interrupted:
                    debug_print(f"Monitor loop {monitor_loops}: Global interrupt flag is set. Breaking.")
                    if result["status"] not in ["TLE", "CTLE", "CRASHED"]:
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
                    if not error_flag.is_set() and not JarTester._interrupted:
                        process_exited_normally = True
                    break
                except Exception as e_cpu:
                    print(f"ERROR: Monitor loop: Unexpected error getting CPU times for PID {pid}: {e_cpu}", file=sys.stderr)
                    debug_print(f"Monitor loop {monitor_loops}: psutil error getting CPU times for PID {pid}", exc_info=True)
                    if result["status"] not in ["CRASHED", "TLE", "CTLE", "INTERRUPTED"]:
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

                # Use the dynamic wall limit passed to the function
                if current_wall_time > current_wall_limit:
                    debug_print(f"Monitor loop {monitor_loops}: TLE for PID {pid}")
                    result["status"] = "TLE"
                    # Update error message to reflect the actual limit used
                    result["error_details"] = f"Wall time {current_wall_time:.2f}s exceeded limit {current_wall_limit:.2f}s."
                    error_flag.set()
                    break

                time.sleep(0.05)

            debug_print(f"Exited monitoring loop for PID {pid} after {monitor_loops} iterations. Status: {result['status']}, ExitedNormally: {process_exited_normally}")

            if error_flag.is_set() and pid != -1:
                debug_print(f"Error flag set or limit exceeded, ensuring process tree killed for PID {pid}")
                try:
                    if psutil.pid_exists(pid): JarTester._kill_process_tree(pid)
                    else: debug_print(f"Process {pid} already gone before kill attempt after loop exit.")
                except Exception as e_kill_loop:
                    print(f"WARNING: Error during kill attempt after loop exit for PID {pid}: {e_kill_loop}", file=sys.stderr)

            debug_print(f"Waiting for I/O threads to finish for PID {pid}")
            thread_join_timeout = 1.0
            if input_feeder_thread: input_feeder_thread.join(timeout=thread_join_timeout)
            if stdout_reader_thread: stdout_reader_thread.join(timeout=thread_join_timeout)
            if stderr_reader_thread: stderr_reader_thread.join(timeout=thread_join_timeout)
            debug_print(f"Finished waiting for I/O threads for PID {pid}")

            final_status_determined = result["status"] not in ["RUNNING", "PENDING"]

            result["wall_time"] = time.monotonic() - start_wall_time
            try:
                if psutil.pid_exists(pid): result["cpu_time"] = sum(psutil.Process(pid).cpu_times())
            except psutil.NoSuchProcess: pass

            if process_exited_normally and not final_status_determined:
                debug_print(f"Process {pid} exited normally (flag is True). Getting final state and exit code.")
                exit_code = None
                try:
                    exit_code = process.wait(timeout=0.5)
                    debug_print(f"Process {pid} wait() returned exit code: {exit_code}")
                    if exit_code != 0:
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Exited with code {exit_code}."
                        final_status_determined = True
                    elif result["status"] == "PENDING": # Should likely be RUNNING here
                         result["status"] = "RUNNING" # Correct if it was PENDING

                except subprocess.TimeoutExpired:
                    print(f"WARNING: Timeout waiting for exit code for PID {pid}, which should have exited.", file=sys.stderr)
                    try: JarTester._kill_process_tree(pid)
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
            # --- End Process Launch and Monitoring ---
        except (psutil.NoSuchProcess) as e_outer:
            debug_print(f"Outer exception handler: NoSuchProcess for PID {pid} ({jar_basename}). Handled.")
            if result["status"] not in ["CRASHED", "TLE", "CTLE", "INTERRUPTED"]:
                result["status"] = "CRASHED"
                result["error_details"] = f"Process disappeared: {e_outer}"
            error_flag.set()
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
            while not stdout_queue.empty(): stdout_lines.append(stdout_queue.get_nowait())
            while not stderr_queue.empty(): stderr_lines.append(stderr_queue.get_nowait())
            result["stderr"] = stderr_lines # Store stderr directly
            debug_print(f"Drained queues for PID {pid}. stdout lines: {len(stdout_lines)}, stderr lines: {len(stderr_lines)}")

            # Save stdout to a unique file in TMP_DIR
            stdout_content = "".join(stdout_lines)
            if stdout_content or result["status"] != "PENDING": # Save even if empty if run finished/failed
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                rand_id = random.randint(1000, 9999)
                # Sanitize jar_basename for filename
                safe_jar_basename = re.sub(r'[^\w.-]', '_', jar_basename)
                stdout_filename = f"stdout_{safe_jar_basename}_{timestamp}_{rand_id}.log"
                stdout_filepath = os.path.abspath(os.path.join(TMP_DIR, stdout_filename))
                try:
                    os.makedirs(TMP_DIR, exist_ok=True) # Ensure dir exists
                    with open(stdout_filepath, 'w', encoding='utf-8') as f_out:
                        f_out.write(stdout_content)
                    result["stdout_log_path"] = stdout_filepath # Store the path
                    debug_print(f"JAR stdout saved to {stdout_filepath}")
                except Exception as e_write_stdout:
                    print(f"WARNING: Failed to write stdout log for {jar_basename} to {stdout_filepath}: {e_write_stdout}", file=sys.stderr)
                    result["stdout_log_path"] = None # Indicate failure
            else:
                 debug_print(f"No stdout content generated for {jar_basename}, not saving file.")
                 result["stdout_log_path"] = None

            debug_print(f"Final join for threads of PID {pid}")
            if input_feeder_thread and input_feeder_thread.is_alive(): input_feeder_thread.join(timeout=0.1)
            if stdout_reader_thread and stdout_reader_thread.is_alive(): stdout_reader_thread.join(timeout=0.1)
            if stderr_reader_thread and stderr_reader_thread.is_alive(): stderr_reader_thread.join(timeout=0.1)
            debug_print(f"Exiting finally block for PID {pid}")
            # --- End Draining and Saving ---

        # Run Checker (only if status allows and not interrupted)
        # Uses the saved stdout content for the checker's temporary file
        if result["status"] == "RUNNING" and not JarTester._interrupted:
            debug_print(f"Running checker for {jar_basename} (PID {pid}) because status is RUNNING")
            # stdout_content is already available from the finally block
            temp_output_file = None
            try:
                # Use NamedTemporaryFile for checker's input, content comes from stdout_content
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt", encoding='utf-8') as tf:
                    tf.write(stdout_content) # Use the captured content
                    temp_output_file = tf.name
                # Use input_data_path (original generator output path) for checker's first arg
                debug_print(f"Checker using input(gen) '{input_data_path}' and output(jar) '{temp_output_file}' with Tmax={current_wall_limit:.2f}s")

                # Use the dynamic wall limit for the checker's tmax
                checker_proc = subprocess.run(
                    [sys.executable, JarTester._checker_script_path, input_data_path, temp_output_file, "--tmax", str(current_wall_limit)],
                    capture_output=True, text=True, timeout=30, check=False, encoding='utf-8', errors='replace'
                )
                debug_print(f"Checker for {jar_basename} finished with code {checker_proc.returncode}")

                if checker_proc.stderr:
                    result["stderr"].extend(["--- Checker stderr ---"] + checker_proc.stderr.strip().splitlines())

                # --- (Checker result parsing - unchanged) ---
                if checker_proc.returncode != 0:
                    result["status"] = "CHECKER_ERROR"
                    result["error_details"] = f"Checker exited with code {checker_proc.returncode}."
                    details_stdout = checker_proc.stdout.strip()
                    details_stderr = checker_proc.stderr.strip()
                    if details_stdout: result["error_details"] += f" stdout: {details_stdout[:200]}"
                    if details_stderr: result["error_details"] += f" stderr: {details_stderr[:200]}"
                    debug_print(f"Checker error for {jar_basename}: Exit code {checker_proc.returncode}")
                elif "Verdict: CORRECT" in checker_proc.stdout:
                    result["status"] = "CORRECT"
                    debug_print(f"Checker result for {jar_basename}: CORRECT")
                    try:
                        t_final_match = re.search(r"\s*T_final.*?:\s*(\d+\.?\d*)", checker_proc.stdout)
                        wt_match = re.search(r"\s*WT.*?:\s*(\d+\.?\d*)", checker_proc.stdout)
                        w_match = re.search(r"^\s*W\s+\(Power Consumption\):\s*(\d+\.?\d*)", checker_proc.stdout, re.MULTILINE)
                        if t_final_match: result["t_final"] = float(t_final_match.group(1))
                        if wt_match: result["wt"] = float(wt_match.group(1))
                        if w_match: result["w"] = float(w_match.group(1))
                        debug_print(f"Extracted Metrics for {jar_basename}: T_final={result['t_final']}, WT={result['wt']}, W={result['w']}")
                        if result["t_final"] is None or result["wt"] is None or result["w"] is None:
                            result["error_details"] = "Correct verdict but failed to parse all metrics from checker."
                    except ValueError as e_parse:
                        print(f"ERROR: Checker verdict CORRECT for {jar_basename}, but failed parsing metrics: {e_parse}", file=sys.stderr)
                        result["status"] = "CHECKER_ERROR"
                        result["error_details"] = f"Correct verdict but metric parsing failed: {e_parse}"
                        result["t_final"] = result["wt"] = result["w"] = None
                    except Exception as e_re:
                        print(f"ERROR: Regex error during metric parsing for {jar_basename}: {e_re}", file=sys.stderr)
                        result["status"] = "CHECKER_ERROR"
                        result["error_details"] = f"Internal tester error (regex) parsing metrics: {e_re}"
                        result["t_final"] = result["wt"] = result["w"] = None
                else:
                    result["status"] = "INCORRECT"
                    verdict_line = next((line for line in checker_proc.stdout.splitlines() if line.startswith("Verdict:")), "Verdict: INCORRECT (No details)")
                    result["error_details"] = verdict_line.strip()
                    debug_print(f"Checker result for {jar_basename}: INCORRECT. Details: {result['error_details']}")
                # --- (End Checker result parsing) ---

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
             result["status"] = "INTERRUPTED"
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
        """Calls gen.py with provided args, returns requests, writes output to unique tmp file."""
        # Generate a unique filename for this round's input data
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        rand_id = random.randint(1000, 9999)
        input_filename = f"input_{timestamp}_{rand_id}.txt"
        input_filepath = os.path.abspath(os.path.join(TMP_DIR, input_filename))
        os.makedirs(os.path.dirname(input_filepath), exist_ok=True) # Ensure TMP_DIR exists

        requests_data = None
        gen_stdout = None

        try:
            command = [sys.executable, JarTester._gen_script_path] + gen_args_list
            debug_print(f"Running generator: {' '.join(command)}")

            gen_proc = subprocess.run(
                command, capture_output=True, text=True, timeout=15, check=True, encoding='utf-8', errors='replace'
            )
            gen_stdout = gen_proc.stdout

            try:
                with open(input_filepath, 'w', encoding='utf-8') as f: f.write(gen_stdout)
                debug_print(f"Generator output written to tmp file: {input_filepath}")
            except Exception as e_write:
                print(f"ERROR: Failed to write generator output to {input_filepath}: {e_write}", file=sys.stderr)
                input_filepath = None # Mark as failed

            # --- (Request Parsing Logic - unchanged) ---
            raw_requests = gen_stdout.strip().splitlines()
            requests_data = []
            pattern = re.compile(r"\[\s*(\d+\.\d+)\s*\](.*)")
            for line in raw_requests:
                match = pattern.match(line)
                if match:
                    timestamp_req = float(match.group(1)) # Renamed to avoid confusion
                    req_part = match.group(2)
                    requests_data.append((timestamp_req, req_part))
                elif line.strip(): # Ignore empty lines
                    print(f"WARNING: Generator produced invalid line format (ignored): {line}", file=sys.stderr)

            is_n_zero = any(arg == '-n' and gen_args_list[i+1] == '0' for i, arg in enumerate(gen_args_list[:-1]))
            if not raw_requests and not requests_data and is_n_zero:
                 debug_print("Generator produced no output (expected for n=0). Returning empty list.")
                 return [], input_filepath # Still return path even if empty

            if not requests_data and raw_requests:
                 print(f"WARNING: Generator produced output, but no valid request lines were parsed.", file=sys.stderr)
                 return [], input_filepath # Return path even if parsing failed

            requests_data.sort(key=lambda x: x[0])
            return requests_data, input_filepath
            # --- (End Request Parsing Logic) ---

        except FileNotFoundError:
            print(f"ERROR: Generator script not found at '{JarTester._gen_script_path}'", file=sys.stderr)
            return None, None
        except subprocess.TimeoutExpired:
            print("ERROR: Generator script timed out.", file=sys.stderr)
            return None, None
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Generator script failed with exit code {e.returncode}.", file=sys.stderr)
            print(f"--- Generator Command ---\n{' '.join(command)}", file=sys.stderr)
            print(f"--- Generator Stdout ---\n{e.stdout or '<empty>'}\n--- Generator Stderr ---\n{e.stderr or '<empty>'}", file=sys.stderr)
            # Try to save the failed output anyway
            if gen_stdout is not None and input_filepath:
                 try:
                     with open(input_filepath, 'w', encoding='utf-8') as f: f.write(gen_stdout)
                 except Exception: pass
            return None, input_filepath # Return path even on failure, might contain partial/error output
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
            and r["t_final"] is not None and r["wt"] is not None and r["w"] is not None
        ]
        debug_print(f"Calculating scores based on {len(correct_results)} CORRECT runs with metrics.")

        if not correct_results:
            for r in current_results:
                 if r["status"] != "CORRECT": r["final_score"] = 0.0
            return

        t_finals = np.array([r["t_final"] for r in correct_results])
        wts = np.array([r["wt"] for r in correct_results])
        ws = np.array([r["w"] for r in correct_results])
        metrics = {'t_final': t_finals, 'wt': wts, 'w': ws}
        normalized_scores = {}

        for name, values in metrics.items():
            if len(values) == 0: continue
            x_min = np.min(values)
            x_max = np.max(values)
            x_avg = np.mean(values)
            # Handle cases where all values are the same
            if abs(x_max - x_min) < 1e-9:
                 base_min = x_min
                 base_max = x_max
            else:
                base_min = PERF_P_VALUE * x_avg + (1 - PERF_P_VALUE) * x_min
                base_max = PERF_P_VALUE * x_avg + (1 - PERF_P_VALUE) * x_max
                # Ensure base_min is not slightly larger than base_max due to precision
                if base_min > base_max: base_min = base_max

            normalized = {}
            for r in correct_results:
                x = r[name]
                r_x = 0.0
                denominator = base_max - base_min
                if denominator > 1e-9: # Use tolerance for floating point comparison
                    if x <= base_min + 1e-9: r_x = 0.0
                    elif x >= base_max - 1e-9: r_x = 1.0
                    else: r_x = (x - base_min) / denominator
                elif abs(denominator) < 1e-9: # All values (or base min/max) are essentially the same
                    r_x = 0.0 # Assign 0 if all are same (no performance difference)
                normalized[r["jar_file"]] = r_x
            normalized_scores[name.upper()] = normalized

        for r in correct_results:
            jar_name = r["jar_file"]
            try:
                r_t = normalized_scores.get('T_FINAL', {}).get(jar_name, 0.0) # Default to 0 if key missing
                r_wt = normalized_scores.get('WT', {}).get(jar_name, 0.0)
                r_w = normalized_scores.get('W', {}).get(jar_name, 0.0)
                r_prime_t = 1.0 - r_t
                r_prime_wt = 1.0 - r_wt
                r_prime_w = 1.0 - r_w
                s = 15 * (0.3 * r_prime_t + 0.3 * r_prime_wt + 0.4 * r_prime_w)
                r["final_score"] = max(0.0, s) # Ensure score is non-negative
                debug_print(f"Score for {jar_name}: T_final={r['t_final']:.3f}({r_prime_t:.3f}), WT={r['wt']:.3f}({r_prime_wt:.3f}), W={r['w']:.3f}({r_prime_w:.3f}) -> Final={r['final_score']:.3f}")
            except KeyError as e_key: # Should be less likely with .get()
                print(f"WARNING: Missing normalized score component for {jar_name}: {e_key}. Setting final score to 0.", file=sys.stderr)
                r["final_score"] = 0.0
            except Exception as e_score:
                 print(f"ERROR: Unexpected error calculating final score for {jar_name}: {e_score}. Setting score to 0.", file=sys.stderr)
                 debug_print(f"Score calculation exception for {jar_name}", exc_info=True)
                 r["final_score"] = 0.0

        for r in current_results:
            if r["status"] != "CORRECT":
                r["final_score"] = 0.0

    @staticmethod
    def _display_results(results, round_preset_cmd, input_data_path, round_wall_limit): # Added input_data_path
        """Display results for the current round and log errors AND summary table."""
        console_lines = []
        log_lines = []
        has_errors_for_log = False

        results.sort(key=lambda x: (-x.get("final_score", 0.0), x.get("wall_time", float('inf')) if x.get("status") == "CORRECT" else float('inf')))

        # Include wall limit in the header
        round_header = f"\n--- Test Round {JarTester._test_count} Results (Preset: {round_preset_cmd} | Wall Limit: {round_wall_limit:.1f}s) ---"
        console_lines.append(round_header)
        log_lines.append(round_header.replace(" Results ", " Summary "))
        # Log the input data file path used for this round
        log_lines.append(f"Input Data File: {input_data_path if input_data_path else '<Not Available>'}")


        header = f"{'JAR':<25} | {'Status':<12} | {'Score':<7} | {'T_final':<10} | {'WT':<10} | {'W':<10} | {'CPU(s)':<8} | {'Wall(s)':<8} | Details"
        console_lines.append(header)
        log_lines.append(header)
        console_lines.append("-" * len(header))
        log_lines.append("-" * len(header))

        error_log_header = True

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
            details = r.get("error_details", "")

            line = f"{jar_name:<25} | {status:<12} | {score_str:<7} | {tfin_str:<10} | {wt_str:<10} | {w_str:<10} | {cpu_str:<8} | {wall_str:<8} | {details}"

            console_lines.append(line)
            log_lines.append(line)

            # --- Modify Error Logging Section ---
            if status not in ["CORRECT", "PENDING", "RUNNING", "INTERRUPTED"]:
                has_errors_for_log = True
                if error_log_header:
                    log_lines.append(f"\n--- Test Round {JarTester._test_count} Error Details ---")
                    # Log input data path once per error section header
                    log_lines.append(f"Input Data File for this Round: {input_data_path if input_data_path else '<Not Available>'}")
                    error_log_header = False

                log_lines.append(f"\n--- Error Details for: {jar_name} (Status: {status}) ---")
                log_lines.append(f"  Preset Used: {round_preset_cmd}")
                log_lines.append(f"  Wall Limit Used: {round_wall_limit:.1f}s")
                log_lines.append(f"  Error: {details}")

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

        console_lines.append("-" * len(header))
        log_lines.append("-" * len(header))

        print("\n".join(console_lines))

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
        for r in results:
            if r.get("status") == "INTERRUPTED": continue
            jar_name = r.get("jar_file", "UnknownJAR")
            if jar_name == "UnknownJAR": continue
            history = JarTester._all_results_history[jar_name]
            history['total_runs'] += 1
            score_to_add = 0.0
            if r.get("status") == "CORRECT":
                history['correct_runs'] += 1
                score_to_add = r.get("final_score", 0.0)
                if score_to_add is None: score_to_add = 0.0
            history['scores'].append(score_to_add)
            # debug_print(f"History update for {jar_name}: Total={history['total_runs']}, Correct={history['correct_runs']}, Added Score={score_to_add}")

      
# --- START OF Method JarTester._print_summary ---
    @staticmethod
    def _print_summary():
        """Generates the final summary string."""
        summary_lines = [] # Store lines instead of printing directly

        if JarTester._interrupted:
            summary_lines.append("\n--- Testing Interrupted ---")
        else:
            summary_lines.append("\n--- Testing Finished ---")

        summary_lines.append(f"Total test rounds attempted: {JarTester._test_count}")

        if not JarTester._all_results_history:
            summary_lines.append("No completed test results recorded.")
            return "\n".join(summary_lines) # Return the generated lines

        summary_lines.append("\n--- Average Performance Summary (Based on Completed Rounds) ---")
        summary_data = [] # Renamed from 'summary' to avoid conflict
        for jar_name, data in JarTester._all_results_history.items():
            total_runs = data['total_runs']
            correct_runs = data['correct_runs']
            scores = data['scores']
            valid_scores = [s for s in scores if isinstance(s, (int, float)) and not np.isnan(s)]
            avg_score = np.mean(valid_scores) if valid_scores else 0.0
            correct_rate = (correct_runs / total_runs * 100) if total_runs > 0 else 0.0
            avg_score = avg_score if not np.isnan(avg_score) else 0.0
            summary_data.append({
                "jar": jar_name, "avg_score": avg_score, "correct_rate": correct_rate,
                "correct": correct_runs, "total": total_runs
            })
        summary_data.sort(key=lambda x: (-x["avg_score"], -x["correct_rate"]))

        header = f"{'JAR':<25} | {'Avg Score':<10} | {'Correct %':<10} | {'Passed/Total':<15}"
        summary_lines.append(header)
        summary_lines.append("-" * len(header))

        for item in summary_data:
             passed_total_str = f"{item['correct']}/{item['total']}"
             line = f"{item['jar']:<25} | {item['avg_score']:<10.3f} | {item['correct_rate']:<10.1f}% | {passed_total_str:<15}"
             summary_lines.append(line)

        summary_lines.append("-" * len(header))
        return "\n".join(summary_lines) # Return the complete summary string
# --- END OF Method JarTester._print_summary ---

    @staticmethod
    def _signal_handler(sig, frame):
        if not JarTester._interrupted:
            print("\nCtrl+C detected. Stopping after current round finishes...", file=sys.stderr)
            JarTester._interrupted = True

    @staticmethod
    def _initialize_presets():
        """Parse the raw command strings into argument dictionaries."""
        JarTester._gen_arg_presets = []
        JarTester._raw_preset_commands = []
        required_time_arg_present = True # Flag to check if all presets have time args
        for cmd_index, cmd_str in enumerate(GEN_PRESET_COMMANDS):
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
                    print(f"WARNING: Skipping invalid part in preset '{cmd_str}': {arg}", file=sys.stderr)
                    i += 1
                    continue

                # Track if this is a time argument
                if arg in ['-t', '--max-time']:
                    has_time_arg = True

                if i + 1 < len(parts) and not parts[i+1].startswith('-'):
                    value = parts[i+1]
                    args_dict[arg] = value
                    i += 2
                else:
                    args_dict[arg] = True # Handle flags like --hce
                    i += 1

            # Check if time argument was found for this preset
            if not has_time_arg:
                print(f"WARNING: Preset '{cmd_str}' does not contain '-t' or '--max-time'. Wall time limit calculation might use default ({DEFAULT_GEN_MAX_TIME}s).", file=sys.stderr)
                # Keep required_time_arg_present = True if you want to allow this, or set to False to issue a final warning
                # required_time_arg_present = False # Uncomment to get the final info message

            preset_label = " ".join(parts[1:])
            JarTester._gen_arg_presets.append(args_dict)
            JarTester._raw_preset_commands.append(preset_label)
            # debug_print(f"Parsed preset {cmd_index}: '{preset_label}' -> {args_dict}")

        print(f"INFO: Initialized {len(JarTester._gen_arg_presets)} generator presets.")
        if not required_time_arg_present:
             print(f"INFO: Some presets lack explicit time arguments ('-t' or '--max-time'). Default generator time ({DEFAULT_GEN_MAX_TIME}s) will be used for wall limit calculation in those cases.")


    @staticmethod
    def _preset_dict_to_arg_list(preset_dict):
        """Convert a preset dictionary back to a list of strings for subprocess."""
        args_list = []
        for key, value in preset_dict.items():
            args_list.append(key)
            if value is not True: # Check for boolean flags
                args_list.append(str(value))
        return args_list

    @staticmethod
    def test(hw_n, jar_path, gen_args_override=None):
        """Main testing entry point."""
        try:
            hw_n = str(hw_n).replace(".", os.sep)
            JarTester._jar_dir = jar_path
            JarTester._gen_script_path = os.path.abspath(os.path.join(hw_n, "gen.py"))
            JarTester._checker_script_path = os.path.abspath(os.path.join(hw_n, "checker.py"))
            JarTester._interrupted = False
            JarTester._test_count = 0
            JarTester._all_results_history.clear()

            # Create LOG_DIR and TMP_DIR
            os.makedirs(LOG_DIR, exist_ok=True)
            os.makedirs(TMP_DIR, exist_ok=True)
            local_time = time.localtime()
            formatted_time = time.strftime("%Y-%m-%d-%H-%M-%S", local_time)
            JarTester._log_file_path = os.path.abspath(os.path.join(LOG_DIR, f"{formatted_time}_elevator_run.log"))
            # JarTester._persistent_request_file_path removed
            print(f"INFO: Logging round summaries and errors to {JarTester._log_file_path}")
            print(f"INFO: Storing temporary input/output files in {os.path.abspath(TMP_DIR)}/")


            if not os.path.exists(JarTester._gen_script_path): print(f"ERROR: Generator script not found: {JarTester._gen_script_path}", file=sys.stderr); return
            if not os.path.exists(JarTester._checker_script_path): print(f"ERROR: Checker script not found: {JarTester._checker_script_path}", file=sys.stderr); return
            if not JarTester._find_jar_files(): print("ERROR: No JAR files found or accessible. Aborting.", file=sys.stderr); return

            JarTester._initialize_presets()
            if not JarTester._gen_arg_presets: print("ERROR: No valid generator presets found. Aborting.", file=sys.stderr); return

            signal.signal(signal.SIGINT, JarTester._signal_handler)
            print(f"Press Ctrl+C to stop testing gracefully after the current round.")

            print("\n" + "="*40)
            input("Setup complete. Press Enter to begin testing...")
            print("="*40 + "\n")

            while not JarTester._interrupted:
                JarTester._test_count += 1
                JarTester._clear_screen()
                print(f"\n--- Starting Test Round {JarTester._test_count} ---")

                # --- Select Preset and Determine Wall Time Limit ---
                preset_index = random.randrange(len(JarTester._gen_arg_presets))
                selected_preset_dict = JarTester._gen_arg_presets[preset_index]
                selected_preset_cmd = JarTester._raw_preset_commands[preset_index]
                gen_args_list = JarTester._preset_dict_to_arg_list(selected_preset_dict)
                print(f"Using Generator Preset: {selected_preset_cmd}")
                debug_print(f"Round {JarTester._test_count}: Selected preset index {preset_index}, args: {gen_args_list}")

                # Extract gen max_time to calculate wall time limit for this round
                gen_max_time_str = selected_preset_dict.get('-t') or selected_preset_dict.get('--max-time')
                round_gen_max_time = DEFAULT_GEN_MAX_TIME # Use default if not specified
                if gen_max_time_str:
                    try:
                        round_gen_max_time = float(gen_max_time_str)
                    except ValueError:
                        print(f"WARNING: Could not parse max_time '{gen_max_time_str}' from preset. Using default {round_gen_max_time}s for limit calculation.", file=sys.stderr)
                # Calculate the wall time limit for this specific round
                round_wall_time_limit = max(MIN_WALL_TIME_LIMIT, round_gen_max_time * 2.0)
                print(f"Setting Round WALL_TIME_LIMIT: {round_wall_time_limit:.2f}s (based on gen max_time {round_gen_max_time:.2f}s)")
                debug_print(f"Round {JarTester._test_count}: Calculated wall limit {round_wall_time_limit:.2f}s")
                # --------------------------------------------------

                # 1. Generate Data
                debug_print(f"Round {JarTester._test_count}: Generating data...")
                # _generate_data now returns the path to the unique input file
                requests_data, input_data_path = JarTester._generate_data(gen_args_list)

                if requests_data is None:
                    print(f"ERROR: Failed to generate data for this round (Preset: {selected_preset_cmd}). Skipping.", file=sys.stderr)
                    if JarTester._log_file_path:
                         try:
                             with open(JarTester._log_file_path, "a", encoding="utf-8") as f:
                                 # Log failure and the intended input path (even if write failed)
                                 f.write(f"\n--- Round {JarTester._test_count}: Generation FAILED ---\n")
                                 f.write(f"Preset: {selected_preset_cmd}\n")
                                 f.write(f"Wall Limit: {round_wall_time_limit:.1f}s\n")
                                 f.write(f"Intended Input File: {input_data_path if input_data_path else '<Path Not Generated>'}\n")
                         except Exception: pass
                    if JarTester._interrupted: break
                    time.sleep(2)
                    continue
                # Log the path to the generated input file
                debug_print(f"Round {JarTester._test_count}: Generated {len(requests_data)} requests to '{input_data_path}' using preset '{selected_preset_cmd}'")


                if JarTester._interrupted: break

                # 2. Run JARs Concurrently
                results = []
                # Adjusted worker count - consider tuning based on typical JAR behavior (CPU vs IO)
                max_workers = min(len(JarTester._jar_files), (os.cpu_count() or 4) * 2 + 1)
                print(f"INFO: Running {len(JarTester._jar_files)} JARs with max {max_workers} workers...")
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_jar = {
                        # Pass the unique input_data_path to _run_single_jar
                        executor.submit(JarTester._run_single_jar, jar_file, requests_data, input_data_path, round_wall_time_limit): jar_file
                        for jar_file in JarTester._jar_files
                    }
                    debug_print(f"Round {JarTester._test_count}: Submitted {len(future_to_jar)} JARs.")
                    try:
                        completed_count = 0
                        for future in concurrent.futures.as_completed(future_to_jar):
                             if JarTester._interrupted:
                                 debug_print("Interrupt detected during as_completed, waiting for running jobs...")

                             jar_file = future_to_jar[future]
                             jar_basename = os.path.basename(jar_file)
                             try:
                                 result = future.result()
                                 # Ensure stdout_log_path exists in result, even if None
                                 if "stdout_log_path" not in result: result["stdout_log_path"] = None
                                 results.append(result)
                                 completed_count += 1
                                 print(f"Progress: {completed_count}/{len(future_to_jar)} completed ({jar_basename}: {result.get('status','?')})...", end='\r', flush=True)
                             except concurrent.futures.CancelledError:
                                  print(f"INFO: Run for {jar_basename} was cancelled (unexpected).", file=sys.stderr)
                             except Exception as exc:
                                print(f'\nERROR: JAR {jar_basename} generated an unexpected exception in tester thread: {exc}', file=sys.stderr)
                                debug_print(f"Exception from future for {jar_basename}", exc_info=True)
                                results.append({ "jar_file": jar_basename, "status": "CRASHED", "final_score": 0.0, "error_details": f"Tester thread exception: {exc}", "cpu_time": 0, "wall_time": 0, "t_final": None, "wt": None, "w": None, "stdout_log_path": None, "stderr": [f"Tester thread exception: {exc}"]})
                                print(f"Progress: {completed_count}/{len(future_to_jar)} completed ({jar_basename}: CRASHED)...", end='\r', flush=True)
                                completed_count += 1

                    except KeyboardInterrupt:
                        if not JarTester._interrupted:
                             print("\nCtrl+C detected during JAR execution. Stopping after current round finishes...", file=sys.stderr)
                             JarTester._interrupted = True

                print(f"\nINFO: All {len(future_to_jar)} JAR executions completed or terminated for round {JarTester._test_count}.")
                debug_print(f"Round {JarTester._test_count}: Concurrent execution finished.")

                if JarTester._interrupted: break

                # 3. Calculate Performance Scores
                debug_print(f"Round {JarTester._test_count}: Calculating scores...")
                JarTester._calculate_scores(results)

                # 4. Display Results (Pass round-specific wall limit and input_data_path)
                debug_print(f"Round {JarTester._test_count}: Displaying results...")
                JarTester._display_results(results, selected_preset_cmd, input_data_path, round_wall_time_limit)

                # 5. Update Historical Data
                if not JarTester._interrupted:
                    debug_print(f"Round {JarTester._test_count}: Updating history...")
                    JarTester._update_history(results)
                else:
                    debug_print(f"Round {JarTester._test_count}: Skipping history update due to interrupt.")
                    break

                if not JarTester._interrupted: time.sleep(1)

        except Exception as e:
            print(f"\nFATAL ERROR in main testing loop: {e}", file=sys.stderr)
            debug_print("Fatal error in main loop", exc_info=True)
            if JarTester._log_file_path:
                 try:
                     with open(JarTester._log_file_path, "a", encoding="utf-8") as f:
                         f.write(f"\n\n!!! FATAL TESTER ERROR !!!\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n{e}\n")
                         import traceback
                         traceback.print_exc(file=f)
                 except Exception: pass
        finally:
            summary = JarTester._print_summary()
            print(summary)
            if JarTester._log_file_path:
                try:
                    with open(JarTester._log_file_path, "a", encoding="utf-8") as f:
                        f.write("\n\n" + "="*20 + " FINAL SUMMARY " + "="*20 + "\n") # Add a clear separator
                        f.write(summary + "\n")
                        f.write("="* (40 + len(" FINAL SUMMARY ")) + "\n")
                    debug_print("Final summary also written to log file.")
                except Exception as e_log_summary:
                    print(f"ERROR: Failed to write final summary to log file {JarTester._log_file_path}: {e_log_summary}", file=sys.stderr)

            try:
                if os.path.exists(TMP_DIR) and input("Input 'Confirm' to Delete TMP_DIR: ") == "Confirm":
                    print(f"INFO: Cleaning up temporary directory: {os.path.abspath(TMP_DIR)}")
                    shutil.rmtree(TMP_DIR)
            except Exception as e_clean:
                print(f"WARNING: Failed to clean up temporary directory {TMP_DIR}: {e_clean}", file=sys.stderr)


# --- Main Execution Block ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Elevator Concurrent Tester")
    parser.add_argument("hw_n", help="Homework identifier (e.g., 'hw5'), directory containing gen.py and checker.py")
    parser.add_argument("jar_path", help="Path to the directory containing student JAR files")
    parser.add_argument("--gen-num-requests", type=int, help="[IGNORED] Pass --num-requests to gen.py")
    parser.add_argument("--gen-max-time", type=float, help="[IGNORED] Pass --max-time to gen.py")
    # ... other ignored gen args ...
    parser.add_argument("--debug", action='store_true', help="Enable detailed debug output to stderr.")

    args = parser.parse_args()

    if args.debug:
        ENABLE_DETAILED_DEBUG = True
        debug_print("Detailed debugging enabled.")

    hw_dir = args.hw_n
    jar_dir = args.jar_path

    if not os.path.isdir(hw_dir): print(f"ERROR: Homework directory '{hw_dir}' not found.", file=sys.stderr); sys.exit(1)
    if not os.path.isdir(jar_dir): print(f"ERROR: JAR directory '{jar_dir}' not found.", file=sys.stderr); sys.exit(1)

    # Pass None for gen_args_override as presets are used
    JarTester.test(hw_dir, jar_dir, gen_args_override=None)

# --- END OF FILE test.py ---