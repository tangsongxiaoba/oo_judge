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
import json
import traceback # For logging errors from threads
from typing import List, Dict, Any, Tuple, Optional # For type hinting

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
MAX_OUTPUT_LOG_LINES = 100 # Limit stderr lines in log
IGNORE_NON_TIMESTAMP_LINES = True

# Helper function for conditional debug printing
def debug_print(*args, **kwargs):
    if ENABLE_DETAILED_DEBUG:
        # Add thread identifier for clarity in parallel runs
        thread_name = threading.current_thread().name
        print(f"DEBUG [{time.time():.4f}] [{thread_name}]:", *args, **kwargs, file=sys.stderr, flush=True)

class CustomTester:
    # --- Static variables ---
    _jar_files: List[str] = []
    _finder_executed: bool = False
    _jar_dir: str = ""
    _checker_script_path: str = ""
    _input_file_path: str = "" # Store path to the user-provided input file
    _interrupted: bool = False # Global interrupt flag
    _log_file_path: Optional[str] = None
    IGNORE = IGNORE_NON_TIMESTAMP_LINES

    # --- Locks for shared resources ---
    # History lock removed as history is no longer aggregated incrementally
    _log_lock = threading.Lock()
    _console_lock = threading.Lock()

    # --- Helper: Clear Screen ---
    @staticmethod
    def _clear_screen():
        """Clears the terminal screen."""
        if ENABLE_DETAILED_DEBUG: return
        # Only clear if called from the main thread to avoid messing up parallel output
        if threading.current_thread() is threading.main_thread():
             os.system('cls' if os.name == 'nt' else 'clear')

    # --- (Keep _find_jar_files, _kill_process_tree, _output_reader as they are) ---
    @staticmethod
    def _find_jar_files() -> bool:
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
                # Use console lock for safe printing from potentially different setup stages
                with CustomTester._console_lock:
                    print(f"INFO: Found {len(CustomTester._jar_files)} JAR files in '{CustomTester._jar_dir}'")
            except FileNotFoundError:
                with CustomTester._console_lock:
                    print(f"ERROR: JAR directory not found: '{CustomTester._jar_dir}'", file=sys.stderr)
                return False
            except Exception as e:
                with CustomTester._console_lock:
                    print(f"ERROR: Failed to list JAR files in '{CustomTester._jar_dir}': {e}", file=sys.stderr)
                return False
        return len(CustomTester._jar_files) > 0

    @staticmethod
    def _kill_process_tree(pid: int):
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
                except psutil.AccessDenied: debug_print(f"Access denied terminating child PID {child.pid}")
            debug_print(f"Terminating parent PID {pid}")
            parent.terminate()
            # Use a slightly longer timeout and wait for all processes
            processes_to_wait = children + [parent]
            gone, alive = psutil.wait_procs(processes_to_wait, timeout=1.5) # Increased timeout
            debug_print(f"After terminate: Gone={[(p.pid if hasattr(p,'pid') else '?') for p in gone]}, Alive={[(p.pid if hasattr(p,'pid') else '?') for p in alive]}")
            for p in alive:
                try:
                    if psutil.pid_exists(p.pid): # Check existence before killing
                        debug_print(f"Killing remaining process PID {p.pid}")
                        p.kill()
                    else:
                        debug_print(f"Process PID {p.pid} gone before kill attempt.")
                except psutil.NoSuchProcess: pass
                except psutil.AccessDenied: debug_print(f"Access denied killing process PID {p.pid}")
        except psutil.NoSuchProcess:
            debug_print(f"Process PID {pid} already gone before kill attempt.")
        except psutil.AccessDenied:
            debug_print(f"Access denied trying to terminate process PID {pid}.")
        except Exception as e:
            # Use console lock for safety if printing errors from diverse threads
            with CustomTester._console_lock:
                print(f"ERROR: Exception during process termination for PID {pid}: {e}", file=sys.stderr)

    @staticmethod
    def _output_reader(pipe, output_queue: queue.Queue, stream_name: str, pid: int, error_flag: threading.Event):
        debug_print(f"Output reader ({stream_name}) started for PID {pid}")
        try:
            # Using readline() should be fine with bufsize=1 in Popen
            for line_num, line in enumerate(iter(pipe.readline, '')):
                if error_flag.is_set() or CustomTester._interrupted:
                     debug_print(f"Output reader ({stream_name}) stopping early for PID {pid} (error or interrupt)")
                     break
                output_queue.put(line)
            debug_print(f"Output reader ({stream_name}) finished iter loop for PID {pid}")
        except ValueError:
             # Ignore ValueError if pipe is closed, common scenario when process exits/killed
            if not error_flag.is_set() and not CustomTester._interrupted and pipe and not pipe.closed:
                 debug_print(f"Output reader ({stream_name}) caught ValueError for PID {pid} (pipe not closed)")
        except Exception as e:
            # Avoid printing error if it was due to intentional interrupt/error
            if not error_flag.is_set() and not CustomTester._interrupted:
                # Use console lock for safety
                with CustomTester._console_lock:
                    print(f"ERROR: Output reader ({stream_name}) thread crashed for PID {pid}: {e}", file=sys.stderr)
                debug_print(f"Output reader ({stream_name}) thread exception for PID {pid}", exc_info=True)
                error_flag.set() # Signal error if unexpected exception
        finally:
            try:
                # Check if pipe exists and is not already closed
                if pipe and not pipe.closed:
                    debug_print(f"Output reader ({stream_name}) closing pipe for PID {pid}")
                    pipe.close()
                else:
                    debug_print(f"Output reader ({stream_name}) pipe already closed or None for PID {pid}")

            except Exception as e_close:
                 # Log closing error only if debugging
                 debug_print(f"Output reader ({stream_name}) error closing pipe for PID {pid}: {e_close}")
            debug_print(f"Output reader ({stream_name}) thread exiting for PID {pid}")

    @staticmethod
    def _run_single_jar(jar_path: str, input_content_str: str, original_input_file_path: str, current_wall_limit: float) -> Dict[str, Any]:
        """Executes a single JAR, monitors it, saves stdout, and runs the checker."""
        jar_basename = os.path.basename(jar_path)
        # Ensure TMP_DIR exists before trying to create files in it
        os.makedirs(TMP_DIR, exist_ok=True)

        debug_print(f"Starting run for JAR: {jar_basename} with Wall Limit: {current_wall_limit:.2f}s")
        start_wall_time = time.monotonic()
        process: Optional[subprocess.Popen] = None
        pid: int = -1
        ps_proc: Optional[psutil.Process] = None
        result: Dict[str, Any] = {
            "jar_file": jar_basename, "cpu_time": 0.0, "wall_time": 0.0,
            "status": "PENDING", "error_details": "",
            "stdout_log_path": None, # Path to saved stdout file
            "stderr": [], # Keep stderr in memory for log
            "t_final": None, "wt": None, "w": None, "final_score": 0.0,
            "input_data_path": original_input_file_path # Store the ORIGINAL input path
        }
        stdout_reader_thread: Optional[threading.Thread] = None
        stderr_reader_thread: Optional[threading.Thread] = None
        stdout_queue: queue.Queue[str] = queue.Queue()
        stderr_queue: queue.Queue[str] = queue.Queue()
        error_flag = threading.Event() # Local error flag for this JAR run

        try:
            # --- (Process Launch and Monitoring - largely unchanged) ---
            debug_print(f"Launching JAR: {jar_basename}")
            debug_print(f"Feeding {len(input_content_str)} bytes of input at once.")
            # Ensure java executable can be found
            java_executable = "java" # Assume java is in PATH
            process = subprocess.Popen(
                [java_executable, '-jar', jar_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', bufsize=1 # Line buffered
            )
            pid = process.pid
            debug_print(f"JAR {jar_basename} launched with PID {pid}")
            result["status"] = "RUNNING"
            try:
                # Wait a tiny moment before attaching psutil, process might need time to initialize
                # time.sleep(0.01) # Removed, usually not needed and adds delay
                ps_proc = psutil.Process(pid)
                # Set low priority if possible (especially on Linux/macOS)
                try:
                    if hasattr(ps_proc, 'nice'): # POSIX
                        ps_proc.nice(10) # Lower priority
                        debug_print(f"Set nice value for PID {pid}")
                    elif hasattr(ps_proc, 'ionice') and hasattr(psutil, 'IOPRIO_CLASS_IDLE'): # Linux IO Priority
                         ps_proc.ionice(psutil.IOPRIO_CLASS_IDLE)
                         debug_print(f"Set ionice for PID {pid}")
                    elif hasattr(ps_proc, 'priority') and hasattr(psutil, 'IDLE_PRIORITY_CLASS'): # Windows
                         ps_proc.priority(psutil.IDLE_PRIORITY_CLASS)
                         debug_print(f"Set priority class for PID {pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as e_priority:
                    debug_print(f"Could not set priority for PID {pid}: {e_priority}")

                debug_print(f"Attached psutil to PID {pid}")
            except psutil.NoSuchProcess as e_attach:
                with CustomTester._console_lock:
                    print(f"ERROR: Process {pid} ({jar_basename}) disappeared immediately after launch.", file=sys.stderr)
                debug_print(f"psutil attach failed for PID {pid}", exc_info=True)
                result["status"] = "CRASHED"
                result["error_details"] = f"Process disappeared immediately: {e_attach}"
                error_flag.set() # Signal error

            # Start I/O threads *before* writing stdin, in case the JAR prints errors immediately
            if not error_flag.is_set():
                debug_print(f"Starting I/O threads for PID {pid}")
                stdout_reader_thread = threading.Thread(target=CustomTester._output_reader, args=(process.stdout, stdout_queue, "stdout", pid, error_flag), daemon=True, name=f"stdout_{pid}")
                stderr_reader_thread = threading.Thread(target=CustomTester._output_reader, args=(process.stderr, stderr_queue, "stderr", pid, error_flag), daemon=True, name=f"stderr_{pid}")
                stdout_reader_thread.start()
                stderr_reader_thread.start()

            # Write stdin only if process seems okay so far
            if not error_flag.is_set():
                try:
                    debug_print(f"Writing {len(input_content_str)} bytes of input to PID {pid} stdin...")
                    # Write and close in separate steps
                    process.stdin.write(input_content_str)
                    process.stdin.flush() # Ensure data is sent
                    debug_print(f"Closing PID {pid} stdin...")
                    process.stdin.close() # Crucial: Signal EOF to the JAR program
                    debug_print(f"Successfully wrote and closed stdin for PID {pid}")
                except (BrokenPipeError, OSError) as e_stdin:
                    # This likely means the process terminated unexpectedly after launch but before/during input write.
                    if not error_flag.is_set(): # Avoid duplicate messages if already crashed
                        with CustomTester._console_lock:
                            print(f"ERROR: Failed to write input to {jar_basename} (PID {pid}) - Broken pipe or OS error: {e_stdin}", file=sys.stderr)
                        debug_print(f"BrokenPipeError/OSError writing/closing stdin for PID {pid}", exc_info=True)
                        # Update status only if not already set to a terminal state
                        if result["status"] in ["PENDING", "RUNNING"]:
                            result["status"] = "CRASHED"
                            result["error_details"] = f"Failed to write input (process likely crashed): {e_stdin}"
                        error_flag.set() # Signal error for monitoring loop / cleanup
                except Exception as e_stdin_other:
                     # Catch other potential errors during stdin handling
                    if not error_flag.is_set():
                        with CustomTester._console_lock:
                            print(f"ERROR: Unexpected error writing input to {jar_basename} (PID {pid}): {e_stdin_other}", file=sys.stderr)
                        debug_print(f"Unexpected exception writing/closing stdin for PID {pid}", exc_info=True)
                        if result["status"] in ["PENDING", "RUNNING"]:
                             result["status"] = "CRASHED"
                             result["error_details"] = f"Unexpected error writing input: {e_stdin_other}"
                        error_flag.set()


            # --- Monitoring Loop ---
            debug_print(f"Starting monitoring loop for PID {pid}")
            monitor_loops = 0
            process_exited_normally = False
            while not error_flag.is_set(): # Loop exits if error_flag is set
                monitor_loops += 1

                # Check global interrupt first
                if CustomTester._interrupted:
                    debug_print(f"Monitor loop {monitor_loops}: Global interrupt flag is set. Breaking.")
                    if result["status"] in ["PENDING", "RUNNING"]:
                        result["status"] = "INTERRUPTED"
                        result["error_details"] = "Run interrupted by user (Ctrl+C)."
                    error_flag.set() # Signal threads to stop and trigger cleanup
                    break # Exit while loop

                # Check process status using psutil
                try:
                    if not ps_proc or not ps_proc.is_running():
                        debug_print(f"Monitor loop {monitor_loops}: ps_proc.is_running() is False for PID {pid}. Breaking.")
                        # Don't set error_flag here, let it finish normally if no other errors occurred
                        process_exited_normally = True
                        break # Exit while loop
                except psutil.NoSuchProcess:
                    debug_print(f"Monitor loop {monitor_loops}: psutil.NoSuchProcess caught checking is_running() for PID {pid}. Breaking.")
                    process_exited_normally = True
                    break # Exit while loop
                except Exception as e_ps_check: # Catch other potential psutil errors
                     with CustomTester._console_lock:
                         print(f"ERROR: Monitor loop: Unexpected error checking process status for PID {pid}: {e_ps_check}", file=sys.stderr)
                     debug_print(f"Monitor loop {monitor_loops}: psutil error checking status for PID {pid}", exc_info=True)
                     if result["status"] in ["PENDING", "RUNNING"]:
                         result["status"] = "CRASHED"
                         result["error_details"] = f"Tester error checking process status: {e_ps_check}"
                     error_flag.set() # Signal error
                     break # Exit while loop

                # --- Check Limits ---
                current_wall_time = time.monotonic() - start_wall_time
                current_cpu_time = result["cpu_time"] # Use last known value

                try:
                    # Get CPU times ONLY if process is still running
                    # Check is_running again to be sure, avoids race condition with process exiting
                    if ps_proc.is_running():
                        cpu_times = ps_proc.cpu_times()
                        # Include children's CPU time if possible and relevant (though Java usually runs in one process)
                        # child_cpu_times = sum(c.cpu_times().user + c.cpu_times().system for c in ps_proc.children(recursive=True) if c.is_running())
                        # current_cpu_time = cpu_times.user + cpu_times.system + child_cpu_times
                        current_cpu_time = cpu_times.user + cpu_times.system
                except psutil.NoSuchProcess:
                    debug_print(f"Monitor loop {monitor_loops}: NoSuchProcess getting CPU times for PID {pid}. Process likely exited between checks.")
                    # Don't break here, let the next loop iteration catch the exit status
                    pass # Continue using the last known CPU time
                except Exception as e_cpu:
                    with CustomTester._console_lock:
                        print(f"ERROR: Monitor loop: Unexpected error getting CPU times for PID {pid}: {e_cpu}", file=sys.stderr)
                    debug_print(f"Monitor loop {monitor_loops}: psutil error getting CPU times for PID {pid}", exc_info=True)
                    if result["status"] in ["PENDING", "RUNNING"]:
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Tester error getting CPU time: {e_cpu}"
                    error_flag.set() # Signal error
                    break # Exit while loop

                result["cpu_time"] = current_cpu_time
                result["wall_time"] = current_wall_time

                # Check CPU Time Limit
                if current_cpu_time > CPU_TIME_LIMIT:
                    debug_print(f"Monitor loop {monitor_loops}: CTLE for PID {pid} ({current_cpu_time:.2f}s > {CPU_TIME_LIMIT:.2f}s)")
                    result["status"] = "CTLE"
                    result["error_details"] = f"CPU time {current_cpu_time:.2f}s exceeded limit {CPU_TIME_LIMIT:.2f}s."
                    error_flag.set() # Signal error flag
                    break # Exit while loop

                # Check Wall Time Limit
                if current_wall_time > current_wall_limit:
                    debug_print(f"Monitor loop {monitor_loops}: TLE for PID {pid} ({current_wall_time:.2f}s > {current_wall_limit:.2f}s)")
                    result["status"] = "TLE"
                    result["error_details"] = f"Wall time {current_wall_time:.2f}s exceeded limit {current_wall_limit:.2f}s."
                    error_flag.set() # Signal error flag
                    break # Exit while loop

                # Sleep for a short interval
                time.sleep(0.05) # 50ms sleep interval

            # --- End of Monitoring Loop ---
            debug_print(f"Exited monitoring loop for PID {pid} after {monitor_loops} iterations. Status: {result['status']}, ExitedNormally: {process_exited_normally}")

            # --- Termination and Cleanup ---
            # If an error occurred (TLE, CTLE, Crash detected inside loop, Interrupt) or if process needs killing
            if error_flag.is_set() and pid != -1:
                 debug_print(f"Error flag set or limit exceeded, ensuring process tree killed for PID {pid}")
                 CustomTester._kill_process_tree(pid) # Kill the process tree forcefully

            # Wait for I/O threads to finish reading any remaining output
            debug_print(f"Waiting for I/O threads to finish for PID {pid}")
            thread_join_timeout = 2.0 # Max time to wait for reader threads
            threads_to_join = [t for t in [stdout_reader_thread, stderr_reader_thread] if t and t.is_alive()]
            start_join_time = time.monotonic()
            current_join_time = 0
            while threads_to_join and current_join_time < thread_join_timeout:
                # Join with a short timeout to avoid blocking too long if a thread hangs
                threads_to_join[0].join(timeout=0.1)
                if not threads_to_join[0].is_alive():
                    threads_to_join.pop(0) # Remove finished thread
                current_join_time = time.monotonic() - start_join_time

            # Log warning if any thread didn't finish
            for t in threads_to_join:
                 if t.is_alive():
                      with CustomTester._console_lock:
                          print(f"WARNING: Thread {t.name} for PID {pid} did not exit cleanly within timeout.", file=sys.stderr)
            debug_print(f"Finished waiting for I/O threads for PID {pid}")

            # --- Final State Check ---
            final_status_determined = result["status"] not in ["RUNNING", "PENDING"]

            # Update final wall time
            result["wall_time"] = time.monotonic() - start_wall_time

            # Try to get final CPU time if process existed briefly after loop exit
            try:
                if psutil.pid_exists(pid):
                     final_ps_proc = psutil.Process(pid)
                     final_cpu_times = final_ps_proc.cpu_times()
                     # final_child_cpu = sum(c.cpu_times().user + c.cpu_times().system for c in final_ps_proc.children(recursive=True) if c.is_running()) # Less reliable here
                     result["cpu_time"] = final_cpu_times.user + final_cpu_times.system #+ final_child_cpu
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass # Process already gone or inaccessible, keep last known CPU time

            # Check process exit code if it exited normally and status wasn't already determined
            exit_code: Optional[int] = None
            if process_exited_normally and not final_status_determined:
                debug_print(f"Process {pid} exited normally (flag is True). Getting final state and exit code.")
                try:
                    # Use process.poll() first, it's non-blocking
                    exit_code = process.poll()
                    if exit_code is None:
                        # If poll() is None, it might still be finishing, wait briefly
                        debug_print(f"Process {pid} poll() returned None, waiting briefly...")
                        exit_code = process.wait(timeout=0.5) # Short wait

                    debug_print(f"Process {pid} final exit code: {exit_code}")
                    if exit_code is not None and exit_code != 0:
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Exited with non-zero code {exit_code}."
                        final_status_determined = True
                    elif result["status"] == "RUNNING": # If it was running and exited with 0
                        result["status"] = "COMPLETED" # Intermediate status before checker
                        debug_print(f"Process {pid} completed normally, setting status to COMPLETED")
                    elif result["status"] == "PENDING": # Should not happen if loop ran, but handle defensively
                        result["status"] = "COMPLETED"

                except subprocess.TimeoutExpired:
                    with CustomTester._console_lock:
                        print(f"WARNING: Timeout waiting for final exit code for PID {pid}, which should have exited. Forcing kill.", file=sys.stderr)
                    CustomTester._kill_process_tree(pid) # Kill forcefully
                    if not final_status_determined:
                        result["status"] = "CRASHED"
                        result["error_details"] = "Process did not report exit code after finishing."
                        final_status_determined = True
                except Exception as e_final: # Catch other errors during wait/poll
                    with CustomTester._console_lock:
                        print(f"WARNING: Error getting final state for PID {pid}: {e_final}", file=sys.stderr)
                    debug_print(f"Exception getting final state for PID {pid}", exc_info=True)
                    if not final_status_determined:
                        result["status"] = "CRASHED"
                        result["error_details"] = f"Error getting final process state: {e_final}"
                        final_status_determined = True

            # If after all checks, status is still ambiguous, mark as completed if exited normally, else crashed.
            if result["status"] in ["PENDING", "RUNNING"]:
                if process_exited_normally and exit_code == 0:
                    result["status"] = "COMPLETED"
                    debug_print(f"Final status fallback for PID {pid}: Setting to COMPLETED based on exit code 0.")
                else:
                    result["status"] = "CRASHED" # Or potentially INTERRUPTED if flag was set late
                    if CustomTester._interrupted: result["status"] = "INTERRUPTED"
                    result["error_details"] = result.get("error_details", "") + " (Final status determination fallback)"
                    debug_print(f"Final status fallback for PID {pid}: Setting to {result['status']}.")


        except (psutil.NoSuchProcess) as e_outer:
            # Catch if psutil.Process(pid) failed initially or process disappeared very early
            debug_print(f"Outer exception handler: NoSuchProcess for PID {pid} ({jar_basename}). Handled.")
            if result["status"] in ["PENDING", "RUNNING"]: # Avoid overwriting specific errors
                result["status"] = "CRASHED"
                result["error_details"] = f"Process disappeared unexpectedly: {e_outer}"
            error_flag.set() # Ensure cleanup happens
        except FileNotFoundError as e_fnf:
            # Java executable or JAR file itself not found
            with CustomTester._console_lock:
                print(f"ERROR: Java executable or JAR file '{jar_path}' not found: {e_fnf}.", file=sys.stderr)
            debug_print(f"Outer exception handler: FileNotFoundError for JAR {jar_basename}.")
            result["status"] = "CRASHED"
            result["error_details"] = f"File not found (Java or JAR): {e_fnf}"
            error_flag.set()
        except Exception as e:
            # Catch-all for unexpected errors during setup/monitoring
            with CustomTester._console_lock:
                print(f"FATAL: Error during execution setup/monitoring of {jar_basename} (PID {pid}): {e}", file=sys.stderr)
            debug_print(f"Outer exception handler: Unexpected exception for PID {pid}", exc_info=True)
            if result["status"] in ["PENDING", "RUNNING"]:
                result["status"] = "CRASHED"
                result["error_details"] = f"Tester execution error: {e}"
            error_flag.set() # Ensure cleanup
            # Attempt final kill even in outer exception handler
            if pid != -1 and process and process.poll() is None:
                debug_print(f"Outer exception: Ensuring PID {pid} is killed.")
                CustomTester._kill_process_tree(pid)

        finally:
            # --- Final Cleanup: Drain queues, save stdout, ensure process is gone ---
            debug_print(f"Entering finally block for PID {pid}. Status: {result['status']}")

            # Drain any remaining output from queues
            debug_print(f"Draining output queues for PID {pid}")
            stdout_lines: List[str] = []
            stderr_lines: List[str] = []
            try:
                while True: stdout_lines.append(stdout_queue.get(block=False))
            except queue.Empty: pass
            try:
                while True: stderr_lines.append(stderr_queue.get(block=False))
            except queue.Empty: pass

            # Prepend any captured stderr to the existing list
            result["stderr"] = stderr_lines + result.get("stderr", [])
            debug_print(f"Drained queues for PID {pid}. stdout lines: {len(stdout_lines)}, stderr lines: {len(stderr_lines)}")

            stdout_content = "".join(stdout_lines)

            # Ensure the process is actually terminated
            if pid != -1:
                try:
                    if psutil.pid_exists(pid):
                        debug_print(f"Final cleanup check: PID {pid} still exists. Killing.")
                        CustomTester._kill_process_tree(pid)
                    else:
                        debug_print(f"Final cleanup check: Process {pid} already gone.")
                except Exception as e_kill_final:
                    # Log error during final kill attempt
                    debug_print(f"ERROR: Exception during final kill check for PID {pid}: {e_kill_final}")

            # Save stdout to a file (always save if not CORRECT, or if content exists)
            save_stdout = stdout_content or result["status"] not in ["CORRECT"]
            # Also save if status is unknown/pending (shouldn't happen here, but defensively)
            if result["status"] in ["PENDING", "RUNNING", "COMPLETED", "UNKNOWN"]: save_stdout = True

            if save_stdout:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                rand_id = random.randint(1000, 9999)
                safe_jar_basename = re.sub(r'[^\w.-]+', '_', jar_basename) # More robust replacement
                input_file_basename = os.path.splitext(os.path.basename(original_input_file_path))[0]
                safe_input_basename = re.sub(r'[^\w.-]+', '_', input_file_basename)
                # Add iteration number if available (we'll need to pass it down or get it from context)
                # For now, just use PID which is unique per JAR execution instance
                stdout_filename = f"stdout_{safe_jar_basename}_input_{safe_input_basename}_p{pid}_{timestamp}_{rand_id}.log"
                stdout_filepath = os.path.abspath(os.path.join(TMP_DIR, stdout_filename))
                try:
                    # Ensure TMP_DIR exists again just before writing
                    os.makedirs(TMP_DIR, exist_ok=True)
                    with open(stdout_filepath, 'w', encoding='utf-8', errors='replace') as f_out:
                        f_out.write(stdout_content)
                    result["stdout_log_path"] = stdout_filepath
                    debug_print(f"JAR stdout saved to {stdout_filepath}")
                except Exception as e_write_stdout:
                    with CustomTester._console_lock:
                        print(f"WARNING: Failed to write stdout log for {jar_basename} to {stdout_filepath}: {e_write_stdout}", file=sys.stderr)
                    result["stdout_log_path"] = None # Indicate failure to save
            else:
                 debug_print(f"No stdout content generated or not required for {jar_basename}, not saving file.")
                 result["stdout_log_path"] = None

            # Final check join for I/O threads (should be finished, but doesn't hurt)
            debug_print(f"Final check join for threads of PID {pid}")
            if stdout_reader_thread and stdout_reader_thread.is_alive(): stdout_reader_thread.join(timeout=0.1)
            if stderr_reader_thread and stderr_reader_thread.is_alive(): stderr_reader_thread.join(timeout=0.1)
            debug_print(f"Exiting finally block for PID {pid}")
            # --- End Final Cleanup ---

        # --- Run Checker ---
        # Run checker only if the process completed successfully (status 'COMPLETED') and wasn't interrupted globally
        run_checker = (result["status"] == "COMPLETED" and not CustomTester._interrupted)

        if run_checker:
            debug_print(f"Running checker for {jar_basename} (PID {pid}) because status is COMPLETED and not globally interrupted.")
            temp_output_file: Optional[str] = None
            checker_status: str = "CHECKER_PENDING"
            checker_details: str = ""
            checker_stdout: str = ""
            checker_stderr: str = ""

            # --- Filter stdout content before passing to checker if IGNORE is True ---
            content_for_checker = stdout_content # Default to original content
            if CustomTester.IGNORE:
                debug_print(f"Filtering non-timestamp lines from stdout for {jar_basename} before checking (IGNORE=True)")
                original_line_count = len(stdout_content.splitlines())
                # Regex to match lines starting with "[ timestamp ]"
                # Allows optional whitespace and float timestamps
                timestamp_pattern = re.compile(r"^\s*\[\s*\d+(?:\.\d*)?\s*\].*") # Match the whole line pattern
                filtered_lines = [line for line in stdout_content.splitlines() if timestamp_pattern.match(line)]
                # Join lines back with newline characters
                content_for_checker = "\n".join(filtered_lines)
                # Add a trailing newline if there were any filtered lines (common practice)
                if filtered_lines:
                    content_for_checker += "\n"
                filtered_line_count = len(filtered_lines)
                debug_print(f"Filtered {original_line_count} lines down to {filtered_line_count} lines for checker.")
                if original_line_count > 0 and filtered_line_count == 0:
                    debug_print(f"WARNING: Filtering removed all lines from {jar_basename} output.")
            else:
                debug_print(f"Passing original stdout to checker for {jar_basename} (IGNORE=False)")
            # --- End Filtering Step ---

            try:
                # Create temp file in TMP_DIR
                os.makedirs(TMP_DIR, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt", prefix=f"chk_{pid}_", encoding='utf-8', dir=TMP_DIR, errors='replace') as tf:
                    tf.write(content_for_checker)
                    temp_output_file = tf.name
                debug_print(f"Checker using temp output file: {temp_output_file} (Content was {'filtered' if CustomTester.IGNORE else 'original'})")

                # Use original_input_file_path for checker's first arg
                debug_print(f"Checker using input(orig) '{original_input_file_path}' and output(jar) '{temp_output_file}' with Tmax={current_wall_limit:.2f}s")

                # Use a reasonable timeout for the checker itself
                checker_timeout = 60.0 # Increased checker timeout
                checker_cmd = [
                    sys.executable, # Use the same python interpreter
                    CustomTester._checker_script_path,
                    original_input_file_path,
                    temp_output_file,
                    "--tmax", str(current_wall_limit)
                ]
                debug_print(f"Checker command: {' '.join(checker_cmd)}")

                checker_proc = subprocess.run(
                    checker_cmd,
                    capture_output=True, # Capture stdout/stderr
                    text=True, # Decode as text
                    timeout=checker_timeout,
                    check=False, # Don't raise exception on non-zero exit code
                    encoding='utf-8', errors='replace' # Specify encoding
                )
                debug_print(f"Checker for {jar_basename} finished with code {checker_proc.returncode}")
                checker_stdout = checker_proc.stdout.strip()
                checker_stderr = checker_proc.stderr.strip()

                if checker_stderr:
                    result["stderr"].extend(["--- Checker stderr ---"] + checker_stderr.splitlines())

                # --- (Checker result parsing - logic mostly unchanged, added detail) ---
                if checker_proc.returncode != 0:
                    checker_status = "CHECKER_ERROR"
                    checker_details = f"Checker exited with code {checker_proc.returncode}."
                    # Append checker output to details for easier debugging
                    if checker_stdout: checker_details += f" stdout: '{checker_stdout[:200]}...'"
                    if checker_stderr: checker_details += f" stderr: '{checker_stderr[:200]}...'"
                    debug_print(f"Checker error for {jar_basename}: Exit code {checker_proc.returncode}. Details: {checker_details}")
                else:
                    # Try parsing JSON output from checker stdout
                    try:
                        # Handle empty stdout case
                        if not checker_stdout:
                             raise json.JSONDecodeError("Checker produced empty standard output", "", 0)

                        checker_output_json = json.loads(checker_stdout)
                        checker_result_val = checker_output_json.get("result") # Get the top-level result ("Success" or "Fail")

                        if checker_result_val == "Success":
                            checker_status = "CORRECT"
                            debug_print(f"Checker result for {jar_basename}: CORRECT (via JSON)")
                            try:
                                perf_data = checker_output_json.get("performance", {})
                                t_final_val = float(perf_data['T_final'])
                                wt_val = float(perf_data['WT_weighted_time'])
                                w_val = float(perf_data['W_energy'])

                                result["t_final"] = t_final_val
                                result["wt"] = wt_val
                                result["w"] = w_val
                                debug_print(f"Extracted Metrics via JSON for {jar_basename}: T_final={result['t_final']:.4f}, WT={result['wt']:.4f}, W={result['w']:.4f}")

                            except (KeyError, TypeError, ValueError) as e_parse:
                                with CustomTester._console_lock:
                                    print(f"ERROR: Checker verdict CORRECT for {jar_basename}, but failed parsing metrics from JSON: {e_parse}", file=sys.stderr)
                                debug_print(f"JSON metric parsing failed for {jar_basename}. JSON: {checker_output_json}", exc_info=True)
                                checker_status = "CHECKER_ERROR"
                                checker_details = f"Correct verdict but JSON metric parsing failed: {e_parse}. JSON: {str(checker_output_json)[:200]}..."
                                result["t_final"] = result["wt"] = result["w"] = None # Nullify metrics

                        elif checker_result_val == "Fail":
                            checker_status = "INCORRECT"
                            errors_list = checker_output_json.get("errors", [])
                            # Join multiple errors for more detail if available
                            checker_details = "; ".join(errors_list) if errors_list else "Verdict: INCORRECT (No details in JSON errors list)"
                            debug_print(f"Checker result for {jar_basename}: INCORRECT (via JSON). Details: {checker_details}")

                        else: # Unexpected 'result' value
                            checker_status = "CHECKER_ERROR"
                            checker_details = f"Checker JSON 'result' field invalid: '{checker_result_val}'. JSON: {str(checker_output_json)[:200]}..."
                            debug_print(f"Checker error for {jar_basename}: Invalid JSON 'result' field: {checker_result_val}")

                    except json.JSONDecodeError as e_json:
                        with CustomTester._console_lock:
                             print(f"ERROR: Failed to parse checker JSON output for {jar_basename}: {e_json}", file=sys.stderr)
                        checker_status = "CHECKER_ERROR"
                        checker_details = f"Checker output was not valid JSON: {e_json}. Output: '{checker_stdout[:200]}...'"
                        debug_print(f"Checker error for {jar_basename}: JSONDecodeError. Raw stdout:\n{checker_stdout}")

            except subprocess.TimeoutExpired:
                with CustomTester._console_lock:
                    print(f"ERROR: Checker timed out after {checker_timeout:.1f}s for {jar_basename}.", file=sys.stderr)
                checker_status = "CHECKER_ERROR"
                checker_details = f"Checker process timed out after {checker_timeout:.1f}s."
                # Try to kill the checker process if it timed out (might not exist)
                # This is harder as we don't have the checker's PID directly from run()
            except Exception as e_check:
                with CustomTester._console_lock:
                    print(f"ERROR: Exception running or processing checker for {jar_basename}: {e_check}", file=sys.stderr)
                debug_print(f"Checker exception for {jar_basename}", exc_info=True)
                checker_status = "CHECKER_ERROR"
                checker_details = f"Exception during checker execution/processing: {e_check}"
            finally:
                # Clean up the temporary output file
                if temp_output_file and os.path.exists(temp_output_file):
                    try:
                        os.remove(temp_output_file)
                        debug_print(f"Removed temp checker output file: {temp_output_file}")
                    except Exception as e_rm:
                        with CustomTester._console_lock:
                            print(f"WARNING: Failed to remove temp checker output file {temp_output_file}: {e_rm}", file=sys.stderr)

            # Update the main result status based on the checker outcome
            result["status"] = checker_status
            # If checker didn't result in CORRECT, store details and nullify performance metrics
            if checker_status != "CORRECT":
                result["error_details"] = checker_details
                result["t_final"] = result["wt"] = result["w"] = None

        # Handle cases where checker was skipped
        elif CustomTester._interrupted and result["status"] == "COMPLETED":
             result["status"] = "INTERRUPTED" # Mark as interrupted if it finished but checker was skipped due to interrupt
             result["error_details"] = "Run completed but interrupted before checker execution."
             debug_print(f"Marking {jar_basename} as INTERRUPTED (checker skipped due to global interrupt).")
        elif result["status"] != "COMPLETED":
             # If the status is already TLE, CRASHED, etc., keep that status.
             debug_print(f"Skipping checker for {jar_basename} due to JAR status: {result['status']}")
        else:
             # Should not happen if logic is correct
             debug_print(f"Skipping checker for {jar_basename} (unknown reason). Status: {result['status']}, Interrupt: {CustomTester._interrupted}")
             if result["status"] == "COMPLETED": # Fallback if somehow missed
                 result["status"] = "UNKNOWN_SKIP"
                 result["error_details"] = "Checker skipped for unknown reason despite COMPLETED status."

        # Final check: If status is not CORRECT, ensure score is 0 and metrics are None
        if result["status"] != "CORRECT":
            result["final_score"] = 0.0
            result["t_final"] = result["wt"] = result["w"] = None

        debug_print(f"Finished run for JAR: {jar_basename}. Final Status: {result['status']}, Score: {result['final_score']:.3f}")
        return result

    @staticmethod
    def _read_input_data(input_filepath: str) -> Tuple[Optional[str], float]:
        """Reads the specified input file, parses requests, returns requests and max timestamp."""
        raw_content_str: Optional[str] = None
        max_timestamp: float = 0.0
        try:
            debug_print(f"Reading input data from: {input_filepath}")
            with open(input_filepath, 'r', encoding='utf-8', errors='replace') as f:
                raw_lines = f.readlines()
            raw_content_str = "".join(raw_lines)

            # --- Request Parsing Logic (adapted from _generate_data) ---
            # Regex to find lines like "[ timestamp ] command"
            # Allows for optional decimal part in timestamp and whitespace flexibility
            pattern = re.compile(r"^\s*\[\s*(\d+(?:\.\d*)?)\s*\]\s*(.*)")
            parse_errors = 0
            parsed_request_count = 0
            for line_num, line in enumerate(raw_lines):
                line_stripped = line.strip()
                if not line_stripped or line_stripped.startswith('#'): # Skip empty lines and comments
                    continue

                match = pattern.match(line_stripped)
                if match:
                    try:
                        timestamp_req = float(match.group(1))
                        req_part = match.group(2).strip()
                        # We consider any valid timestamp line, even if command is empty,
                        # as it might signify an end time or marker.
                        # Only count lines with actual commands towards 'parsed_request_count' for feedback?
                        # Let's count any valid parse for max_timestamp determination.
                        max_timestamp = max(max_timestamp, timestamp_req)
                        if req_part: # Count only if there's a command part? Let's count all valid lines for now.
                             parsed_request_count += 1
                        # else: debug_print(f"Input file line {line_num+1}: Empty request part (accepted): {line_stripped}")

                    except ValueError:
                        parse_errors += 1
                        with CustomTester._console_lock:
                             print(f"WARNING: Input file line {line_num+1}: Invalid number format for timestamp (ignored): {line.strip()}", file=sys.stderr)
                else:
                    # Only report as error if it wasn't an empty line or comment
                    parse_errors += 1
                    with CustomTester._console_lock:
                         print(f"WARNING: Input file line {line_num+1}: Invalid line format (ignored): {line.strip()}", file=sys.stderr)

            # Check results of parsing
            if parse_errors > 0 and not raw_content_str: # File only contained invalid lines
                 with CustomTester._console_lock:
                     print(f"ERROR: Input file '{input_filepath}' contained lines, but NO valid requests were parsed.", file=sys.stderr)
                 return None, 0.0 # Indicate failure

            elif parse_errors > 0: # Some lines were invalid
                 with CustomTester._console_lock:
                     print(f"WARNING: {parse_errors} lines in input file '{input_filepath}' had parsing errors.", file=sys.stderr)

            if max_timestamp == 0 and parsed_request_count == 0 and parse_errors == 0 and raw_content_str:
                 # File might contain only comments or lines without timestamps
                 debug_print(f"INFO: Input file '{input_filepath}' read, but no lines matched the [time] command format.")
                 # Keep max_timestamp as 0, proceed with default wall time later
            elif max_timestamp == 0 and parsed_request_count == 0 and not raw_content_str:
                 # File was empty
                 debug_print(f"INFO: Input file '{input_filepath}' is empty.")
                 # Keep max_timestamp as 0

            debug_print(f"Successfully read {len(raw_lines)} lines ({len(raw_content_str or '')} bytes) from '{input_filepath}'. Found max timestamp: {max_timestamp:.3f}s from {parsed_request_count} requests.")
            return raw_content_str, max_timestamp
            # --- End Request Parsing Logic ---

        except FileNotFoundError:
            with CustomTester._console_lock:
                print(f"ERROR: Input file not found at '{input_filepath}'", file=sys.stderr)
            return None, 0.0 # Indicate failure
        except Exception as e:
            with CustomTester._console_lock:
                print(f"ERROR: Unexpected error reading or parsing input file '{input_filepath}': {e}", file=sys.stderr)
            debug_print("Exception in _read_input_data", exc_info=True)
            return None, 0.0 # Indicate failure


    @staticmethod
    def _calculate_scores(current_results: List[Dict[str, Any]]):
        """Calculates normalized performance scores based on results from a SINGLE iteration."""
        # Filter results that are eligible for scoring (CORRECT status with valid metrics)
        correct_results = [
            r for r in current_results
            if r.get("status") == "CORRECT"
            and r.get("t_final") is not None and isinstance(r["t_final"], (int, float))
            and r.get("wt") is not None and isinstance(r["wt"], (int, float))
            and r.get("w") is not None and isinstance(r["w"], (int, float))
        ]
        debug_print(f"Calculating scores based on {len(correct_results)} CORRECT runs with valid metrics.")

        # Initialize final_score to 0.0 for all results in this iteration
        for r in current_results:
            r["final_score"] = 0.0

        if not correct_results:
            debug_print("No CORRECT results with valid metrics found for score calculation in this iteration.")
            return # No scores to calculate

        # Extract metrics into NumPy arrays for efficient calculation
        try:
            t_finals = np.array([r["t_final"] for r in correct_results], dtype=np.float64)
            wts = np.array([r["wt"] for r in correct_results], dtype=np.float64)
            ws = np.array([r["w"] for r in correct_results], dtype=np.float64)
        except Exception as e_np_create:
            with CustomTester._console_lock:
                 print(f"ERROR: Failed to create NumPy arrays from metrics: {e_np_create}. Skipping scoring.", file=sys.stderr)
            debug_print(f"NumPy array creation failed. Correct results: {correct_results}", exc_info=True)
            return


        metrics = {'t_final': t_finals, 'wt': wts, 'w': ws}
        normalized_scores: Dict[str, Dict[str, float]] = {} # Metric -> {JarName -> NormScore}

        # --- Calculate Normalized Scores for each metric ---
        for name, values in metrics.items():
            # Skip if no valid values for this metric (shouldn't happen if correct_results is not empty)
            if len(values) == 0:
                debug_print(f"Skipping metric {name} due to empty values array.")
                continue

            try:
                # Calculate statistics, handle potential NaN/Inf safely if needed (though should be filtered)
                values = values[np.isfinite(values)] # Ensure only finite values are considered
                if len(values) == 0:
                    debug_print(f"Skipping metric {name} after filtering non-finite values.")
                    continue

                x_min = np.min(values)
                x_max = np.max(values)
                x_avg = np.mean(values)
            except Exception as e_np_stats:
                 with CustomTester._console_lock:
                     print(f"ERROR: NumPy error calculating stats for metric '{name}': {e_np_stats}. Skipping scoring for this metric.", file=sys.stderr)
                 debug_print(f"NumPy stats error for {name}. Values: {values}", exc_info=True)
                 continue # Skip this metric

            debug_print(f"Metric {name}: min={x_min:.4f}, max={x_max:.4f}, avg={x_avg:.4f}")

            # Determine base_min and base_max using the P-value formula
            # Handle the case where min and max are very close (or identical)
            if abs(x_max - x_min) < 1e-9:
                 base_min = x_min
                 base_max = x_max
                 debug_print(f"Metric {name}: All values effectively the same.")
            else:
                base_min = PERF_P_VALUE * x_avg + (1 - PERF_P_VALUE) * x_min
                base_max = PERF_P_VALUE * x_avg + (1 - PERF_P_VALUE) * x_max
                # Ensure base_min is not greater than base_max (can happen with unusual distributions)
                if base_min > base_max:
                    debug_print(f"Metric {name}: Adjusted base_min ({base_min:.4f}) > base_max ({base_max:.4f}), clamping base_min = base_max.")
                    base_min = base_max # Clamp base_min to base_max if inversion occurs

            debug_print(f"Metric {name}: base_min={base_min:.4f}, base_max={base_max:.4f}")

            # Calculate normalized score (0 to 1, lower is better -> 0, higher is better -> 1)
            # where 0 represents performance at or better than base_min,
            # and 1 represents performance at or worse than base_max.
            normalized: Dict[str, float] = {} # JarName -> NormalizedScore
            denominator = base_max - base_min
            is_denominator_zero = abs(denominator) < 1e-9

            for r in correct_results:
                x = r.get(name) # Get the original metric value for this JAR
                if x is None or not np.isfinite(x): # Should not happen due to initial filtering, but check
                     normalized[r["jar_file"]] = 0.0 # Assign default/worst score? Or skip? Let's assign 0.
                     debug_print(f"  NormScore {name} for {r['jar_file']}: Skipping due to invalid value {x}")
                     continue

                r_x: float = 0.0 # Default normalized score (best performance)
                if is_denominator_zero:
                    # If denominator is zero, all values are effectively the same.
                    # Assign 0 (best) score to all? Or 0.5? Let's use 0.
                    r_x = 0.0
                else:
                    # Clamp x to the [base_min, base_max] range for normalization
                    if x <= base_min:
                        r_x = 0.0
                    elif x >= base_max:
                        r_x = 1.0
                    else:
                        # Linear interpolation between base_min and base_max
                        r_x = (x - base_min) / denominator

                # Ensure score is within [0, 1] due to potential floating point issues
                r_x = max(0.0, min(1.0, r_x))
                normalized[r["jar_file"]] = r_x
                debug_print(f"  NormScore {name} for {r['jar_file']} (val={x:.4f}): {r_x:.4f}")

            # Store the normalized scores for this metric, using uppercase key convention
            normalized_scores[name.upper()] = normalized # e.g., normalized_scores['T_FINAL'] = {...}

        # --- Calculate Final Weighted Score ---
        # Iterate through the CORRECT results again to calculate the final score based on normalized metrics
        for r in correct_results:
            jar_name = r["jar_file"]
            try:
                # Get the normalized scores (r_x values calculated above) for this JAR for each metric
                # Default to 0.0 if a metric was skipped or JAR wasn't scored for it
                r_t = normalized_scores.get('T_FINAL', {}).get(jar_name, 0.0)
                r_wt = normalized_scores.get('WT', {}).get(jar_name, 0.0)
                r_w = normalized_scores.get('W', {}).get(jar_name, 0.0)

                # Invert the normalized scores (r_prime = 1 - r_x) because lower metric values are better
                # So, a higher r_prime means better relative performance
                r_prime_t = 1.0 - r_t
                r_prime_wt = 1.0 - r_wt
                r_prime_w = 1.0 - r_w

                # Apply weights: 30% T_final, 30% WT, 40% W
                # Scale the result by 15 (as per original formula)
                final_score = 15 * (0.3 * r_prime_t + 0.3 * r_prime_wt + 0.4 * r_prime_w)

                # Ensure final score is non-negative
                r["final_score"] = max(0.0, final_score)

                debug_print(f"Score for {jar_name}: "
                            f"T_final={r['t_final']:.3f}(Norm:{r_t:.3f}, Inv:{r_prime_t:.3f}), "
                            f"WT={r['wt']:.3f}(Norm:{r_wt:.3f}, Inv:{r_prime_wt:.3f}), "
                            f"W={r['w']:.3f}(Norm:{r_w:.3f}, Inv:{r_prime_w:.3f}) "
                            f"-> Final={r['final_score']:.3f}")

            except KeyError as e_key: # Should not happen if normalized_scores keys are uppercase
                with CustomTester._console_lock:
                    print(f"WARNING: Internal error: Missing normalized score component for {jar_name}: {e_key}. Setting final score to 0.", file=sys.stderr)
                r["final_score"] = 0.0
            except Exception as e_score:
                 with CustomTester._console_lock:
                     print(f"ERROR: Unexpected error calculating final score for {jar_name}: {e_score}. Setting score to 0.", file=sys.stderr)
                 debug_print(f"Score calculation exception for {jar_name}", exc_info=True)
                 r["final_score"] = 0.0


    @staticmethod
    def _display_and_log_results(results: List[Dict[str, Any]], iteration_num: int, total_iterations: int, input_file_path_used: str, wall_limit_used: float):
        """Display results for a specific iteration and log errors AND summary table for that iteration. Uses Log Lock and Console Lock."""
        log_lines: List[str] = []
        has_errors_for_log = False

        # Sort results for display within this iteration
        # Sort primarily by final score (desc), then by status (CORRECT first), then wall time (asc) for CORRECT, then JAR name
        def sort_key(r):
            status = r.get("status", "UNKNOWN")
            score = r.get("final_score", 0.0)
            wall_time = r.get("wall_time", float('inf'))
            is_correct = (status == "CORRECT")
            # Prioritize CORRECT, then higher score, then lower wall time (for CORRECT), then name
            return (is_correct, score, -wall_time if is_correct else float('inf'), r.get("jar_file", ""))

        results.sort(key=sort_key, reverse=True) # reverse=True because higher score and is_correct=True should come first

        # --- Prepare Headers ---
        iteration_str = f"Iteration {iteration_num}/{total_iterations}" if total_iterations > 1 else "Single Run"
        run_header = f"\n--- Results [{iteration_str}] (Input: {os.path.basename(input_file_path_used)} | Wall Limit: {wall_limit_used:.1f}s) ---"
        header_line = f"{'JAR':<25} | {'Status':<12} | {'Score':<7} | {'T_final':<10} | {'WT':<10} | {'W':<10} | {'CPU(s)':<8} | {'Wall(s)':<8} | Details"
        separator = "-" * len(header_line)

        # --- Log Summary Table Header ---
        log_lines.append(f"\n{separator}")
        log_lines.append(f"--- Log Summary [{iteration_str}] ---")
        log_lines.append(f"Input Data File: {input_file_path_used}")
        log_lines.append(f"Wall Time Limit: {wall_limit_used:.1f}s")
        log_lines.append(header_line)
        log_lines.append(separator)

        # --- Prepare Console and Log Lines ---
        result_lines_for_console: List[str] = []
        error_log_details: List[str] = [] # Store detailed error logs separately
        error_log_header_needed = True

        for r in results:
            jar_name = r.get("jar_file", "UnknownJAR")
            status = r.get("status", "UNKNOWN")
            score = r.get("final_score", 0.0)
            # Display score only if CORRECT, otherwise "---"
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
            # Truncate details for console display
            details = r.get("error_details", "")
            details_short = (details[:97] + '...') if details and len(details) > 100 else details

            # Format line for console
            console_line = f"{jar_name:<25} | {status:<12} | {score_str:<7} | {tfin_str:<10} | {wt_str:<10} | {w_str:<10} | {cpu_str:<8} | {wall_str:<8} | {details_short}"
            result_lines_for_console.append(console_line)

            # Format line for log summary table (full details)
            log_line = f"{jar_name:<25} | {status:<12} | {score_str:<7} | {tfin_str:<10} | {wt_str:<10} | {w_str:<10} | {cpu_str:<8} | {wall_str:<8} | {details}"
            log_lines.append(log_line)

            # --- Collect Error Details for Logging ---
            # Log details for any status that isn't CORRECT, PENDING, RUNNING, COMPLETED, or INTERRUPTED (if handled gracefully)
            log_worthy_statuses = ["CRASHED", "TLE", "CTLE", "INCORRECT", "CHECKER_ERROR", "UNKNOWN_SKIP", "UNKNOWN"]
            # Optionally add INTERRUPTED if you want logs for those too
            # log_worthy_statuses.append("INTERRUPTED")
            if status in log_worthy_statuses:
                has_errors_for_log = True
                if error_log_header_needed:
                    error_log_details.append(f"\n--- Error Details [{iteration_str}] (Input: {os.path.basename(input_file_path_used)}) ---")
                    error_log_header_needed = False

                error_log_details.append(f"\n--- Details for: {jar_name} (Status: {status}) ---")
                error_log_details.append(f"  Input File Used: {input_file_path_used}") # Reference the input file
                error_log_details.append(f"  Wall Limit Used: {wall_limit_used:.1f}s")
                error_log_details.append(f"  Error Summary: {r.get('error_details', '<No Details>')}")

                # Log path to the *original* input data file (stored in result)
                error_log_details.append("  --- Input Data File ---")
                error_log_details.append(f"    Path: {r.get('input_data_path', '<Not Available>')}")
                # Optional: Log first few lines of input? Might be too verbose.

                # Log path to stdout file (if saved)
                stdout_log = r.get("stdout_log_path")
                error_log_details.append("  --- Stdout Log File ---")
                error_log_details.append(f"    Path: {stdout_log if stdout_log else '<Not Saved or Error>'}")

                # Log stderr content directly (limited lines)
                error_log_details.append("  --- Stderr ---")
                stderr = r.get("stderr", [])
                if stderr:
                    stderr_lines_to_log = [f"    {line.strip()}" for line in stderr]
                    if len(stderr_lines_to_log) > MAX_OUTPUT_LOG_LINES:
                        error_log_details.extend(stderr_lines_to_log[:MAX_OUTPUT_LOG_LINES])
                        error_log_details.append(f"    ... (stderr truncated after {MAX_OUTPUT_LOG_LINES} lines)")
                    else:
                        error_log_details.extend(stderr_lines_to_log)
                    if not stderr_lines_to_log: # Handle case where stderr list exists but contains only empty strings
                         error_log_details.append("    <Stderr content was empty or whitespace>")
                    else:
                         error_log_details.append("    <End of Stderr>")
                else:
                     error_log_details.append("    <No stderr captured>")
                # --- End Stderr ---
                error_log_details.append("-" * 20) # Separator between error details for different JARs
            # --- End Error Logging Section ---

        log_lines.append(separator) # Footer for the summary table in the log

        # --- Print to Console (Locked) ---
        with CustomTester._console_lock:
            print(run_header)
            print(header_line)
            print(separator)
            for line in result_lines_for_console:
                print(line)
            print(separator)
            if total_iterations == 1:
                 print(f"--- End of Test Run ---")
            else:
                 print(f"--- End of Iteration {iteration_num}/{total_iterations} ---")

        # --- Write to Log File (Locked) ---
        if CustomTester._log_file_path:
            # Combine summary table and detailed errors for logging
            full_log_output = log_lines + (error_log_details if has_errors_for_log else [])
            try:
                with CustomTester._log_lock:
                    with open(CustomTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                        f.write("\n".join(full_log_output) + "\n") # Add extra newline for spacing
                debug_print(f"Results and errors for iteration {iteration_num} written to log.")
            except Exception as e:
                # Log writing error needs console lock for safety
                with CustomTester._console_lock:
                    print(f"ERROR: Failed to write iteration {iteration_num} results to log file {CustomTester._log_file_path}: {e}", file=sys.stderr)

    # --- Removed _update_history ---
    # --- Removed _print_summary --- (Replaced by _print_overall_summary called from main)

    @staticmethod
    def _signal_handler(sig, frame):
        """Sets the global interrupt flag."""
        if not CustomTester._interrupted:
            # Use console lock for safe printing from signal handler
            with CustomTester._console_lock:
                 # Use stderr for interrupt message
                print("\nCtrl+C detected. Requesting graceful interruption...", file=sys.stderr, flush=True)
                print("Waiting for running JARs and iterations to complete or timeout...", file=sys.stderr, flush=True)
                print("Press Ctrl+C again to force exit (may corrupt logs/state).", file=sys.stderr, flush=True)
            CustomTester._interrupted = True
        else:
             # Second Ctrl+C: Force exit immediately
             with CustomTester._console_lock:
                  print("\nSecond Ctrl+C detected. Forcing exit NOW.", file=sys.stderr, flush=True)
             # Kill main process group if possible (more forceful)
             try:
                os.killpg(os.getpid(), signal.SIGKILL) # Try killing process group
             except AttributeError: # Windows doesn't have killpg
                pass # Standard exit will likely kill subprocesses
             except Exception as e:
                 print(f"Error during force exit: {e}", file=sys.stderr)
             finally:
                sys.exit(1) # Exit immediately


    @staticmethod
    def _run_single_iteration(
        iteration_num: int,
        total_iterations: int,
        jar_files_to_run: List[str],
        input_content: str,
        input_file_path: str,
        wall_limit: float
        ) -> List[Dict[str, Any]]:
        """
        Runs a single iteration of the test: executes all JARs against the input,
        calculates scores for this iteration, and displays/logs results.
        Returns the list of result dictionaries for this iteration.
        """
        iteration_start_time = time.monotonic()
        iteration_results: List[Dict[str, Any]] = []
        num_jars = len(jar_files_to_run)

        with CustomTester._console_lock:
            print(f"\n>>> Starting Iteration {iteration_num}/{total_iterations} ({num_jars} JARs) <<<")

        # --- Run JARs Concurrently for this iteration ---
        # Use a reasonable number of workers for JAR execution within this iteration
        # Adjust based on available resources, maybe slightly fewer if multiple iterations run in parallel
        inner_max_workers = min(num_jars, (os.cpu_count() or 4) * 2) # Slightly reduced default
        debug_print(f"[Iter {iteration_num}] Running {num_jars} JARs with max {inner_max_workers} inner workers...")

        # Check interrupt flag *before* starting the inner executor
        if CustomTester._interrupted:
            with CustomTester._console_lock:
                print(f"[Iter {iteration_num}] Interrupted before starting JAR executions.")
            return [] # Return empty results if interrupted before start

        # Use a specific ThreadPoolExecutor for the JARs within this iteration
        with concurrent.futures.ThreadPoolExecutor(max_workers=inner_max_workers, thread_name_prefix=f'JarExec_Iter{iteration_num}') as executor:
            future_to_jar: Dict[concurrent.futures.Future, str] = {}
            try:
                # Submit tasks only if not interrupted
                if not CustomTester._interrupted:
                    for jar_file in jar_files_to_run:
                        if CustomTester._interrupted: break # Check again before submitting each task
                        future = executor.submit(
                            CustomTester._run_single_jar,
                            jar_file,
                            input_content,
                            input_file_path,
                            wall_limit
                        )
                        future_to_jar[future] = jar_file
                    debug_print(f"[Iter {iteration_num}] Submitted {len(future_to_jar)} JAR tasks.")
                else:
                     debug_print(f"[Iter {iteration_num}] Interrupted during task submission.")

            except Exception as e_submit:
                 with CustomTester._console_lock:
                     print(f"\nERROR [Iter {iteration_num}]: Failed to submit JAR tasks: {e_submit}", file=sys.stderr)
                 debug_print(f"[Iter {iteration_num}] Exception during future submission", exc_info=True)
                 # Attempt to cancel any submitted futures if possible? Difficult.
                 return [] # Return empty results on submission error

            # Process completed JAR futures for this iteration
            completed_count = 0
            total_submitted = len(future_to_jar)

            # Use as_completed to process results as they finish
            for future in concurrent.futures.as_completed(future_to_jar):
                 # Check interrupt flag frequently while waiting for results
                 if CustomTester._interrupted:
                     debug_print(f"[Iter {iteration_num}] Interrupt detected while processing JAR results.")
                     # Don't break immediately, try to collect results from already finished futures
                     # Futures running _run_single_jar should detect the flag internally and terminate/mark as INTERRUPTED

                 jar_file = future_to_jar[future]
                 jar_basename = os.path.basename(jar_file)
                 try:
                     result = future.result() # Get result from the future
                     iteration_results.append(result)
                     completed_count += 1
                     # Simple progress indication (use console lock)
                     # Only print progress periodically to avoid spamming
                     if completed_count % 5 == 0 or completed_count == total_submitted:
                          with CustomTester._console_lock:
                              status_brief = result.get('status','?')[:4] # Brief status like CORR, TL E, CRAS
                              print(f"[Iter {iteration_num}] JAR {completed_count}/{total_submitted} done ({jar_basename}: {status_brief})", flush=True)

                 except concurrent.futures.CancelledError:
                      # Should not happen unless we explicitly cancel, but handle defensively
                      with CustomTester._console_lock:
                          print(f"\nWARNING [Iter {iteration_num}]: Run for {jar_basename} was cancelled (unexpected).", file=sys.stderr)
                      # Add a placeholder result indicating cancellation
                      iteration_results.append({
                           "jar_file": jar_basename, "status": "CANCELLED", "final_score": 0.0,
                           "error_details": "JAR execution future was cancelled.", "cpu_time": 0, "wall_time": 0,
                           "input_data_path": input_file_path})

                 except Exception as exc:
                    # Catch exceptions raised *within* the _run_single_jar execution (should be rare if inner try/except is robust)
                    with CustomTester._console_lock:
                        print(f'\nERROR [Iter {iteration_num}]: JAR {jar_basename} execution thread failed unexpectedly: {exc}', file=sys.stderr)
                    debug_print(f"[Iter {iteration_num}] Exception from future for {jar_basename}", exc_info=True)
                    # Add a placeholder result indicating the crash
                    iteration_results.append({
                        "jar_file": jar_basename, "status": "CRASHED", "final_score": 0.0,
                        "error_details": f"Tester thread exception: {exc}", "cpu_time": 0, "wall_time": 0,
                        "stderr": [f"Tester thread exception: {exc}", traceback.format_exc()],
                        "input_data_path": input_file_path
                    })
                    completed_count += 1
                    # Print progress update for the crashed one
                    with CustomTester._console_lock:
                         print(f"[Iter {iteration_num}] JAR {completed_count}/{total_submitted} done ({jar_basename}: CRASHED*)", flush=True)

            # End of inner ThreadPoolExecutor for JARs
            debug_print(f"[Iter {iteration_num}] Inner JAR executor finished.")

        # Check interrupt flag again after executor finishes
        if CustomTester._interrupted:
            with CustomTester._console_lock:
                print(f"\n[Iter {iteration_num}] Finished processing JARs, but run was interrupted.")
        else:
             with CustomTester._console_lock:
                 print(f"\n[Iter {iteration_num}] All {num_jars} JAR executions completed.")


        # --- Process Results for this Iteration ---
        if iteration_results:
            # Calculate scores based *only* on the results of this iteration
            with CustomTester._console_lock:
                 print(f"\n[Iter {iteration_num}] Calculating scores...")
            CustomTester._calculate_scores(iteration_results) # Modifies results in-place

            # Display and log the results for *this* iteration
            with CustomTester._console_lock:
                print(f"[Iter {iteration_num}] Displaying and logging iteration results...")
            # Display/log function needs iteration info
            CustomTester._display_and_log_results(
                iteration_results,
                iteration_num,
                total_iterations,
                input_file_path,
                wall_limit
            )
        else:
            with CustomTester._console_lock:
                 print(f"\n[Iter {iteration_num}] No JAR results were collected (possibly due to interruption or errors).")

        iteration_end_time = time.monotonic()
        with CustomTester._console_lock:
             print(f">>> Iteration {iteration_num} finished in {iteration_end_time - iteration_start_time:.2f} seconds. <<<")

        return iteration_results # Return the results for this iteration

    @staticmethod
    def _print_overall_summary(all_iteration_results: List[List[Dict[str, Any]]], input_file_path: str):
        """
        Generates and prints the final summary aggregating results across all iterations.
        Also writes the summary to the log file.
        """
        summary_lines: List[str] = []
        num_iterations = len(all_iteration_results)
        if num_iterations == 0:
             summary_lines.append("\n--- No iterations completed. ---")
             print("\n".join(summary_lines)) # Print to console
             # Log summary even if no iterations ran fully
             if CustomTester._log_file_path:
                try:
                    with CustomTester._log_lock:
                        with open(CustomTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                            f.write("\n\n" + "="*20 + " FINAL SUMMARY (No Iterations Completed) " + "="*20 + "\n")
                            f.write("\n".join(summary_lines) + "\n")
                except Exception: pass # Ignore logging errors here
             return

        # --- Aggregation Logic ---
        # Structure to hold aggregated data per JAR: { jar_name: { 'scores': [s1, s2,...], 'correct_runs': count, 'total_runs': num_iterations } }
        aggregated_data: Dict[str, Dict[str, Any]] = defaultdict(lambda: {'scores': [], 'correct_runs': 0, 'total_runs': num_iterations, 'statuses': []})

        # Find all unique JAR names across all iterations (in case some failed only in certain iterations)
        all_jar_names = set()
        for iter_results in all_iteration_results:
            for r in iter_results:
                 if r.get("jar_file"):
                      all_jar_names.add(r["jar_file"])

        # Populate aggregated_data
        for jar_name in all_jar_names:
             for iter_results in all_iteration_results:
                 # Find the result for this jar_name in this iteration's results
                 jar_result_this_iter = next((r for r in iter_results if r.get("jar_file") == jar_name), None)

                 if jar_result_this_iter:
                     status = jar_result_this_iter.get("status", "UNKNOWN")
                     aggregated_data[jar_name]['statuses'].append(status)
                     if status == "CORRECT":
                         aggregated_data[jar_name]['correct_runs'] += 1
                         # Ensure score is float, default to 0.0 if None or invalid
                         score = jar_result_this_iter.get("final_score", 0.0)
                         aggregated_data[jar_name]['scores'].append(float(score) if score is not None else 0.0)
                     else:
                         # Append 0 score for non-correct runs for average calculation
                         aggregated_data[jar_name]['scores'].append(0.0)
                 else:
                      # JAR missing in this iteration (e.g., iteration interrupted before it ran)
                      aggregated_data[jar_name]['scores'].append(0.0) # Treat as 0 score
                      aggregated_data[jar_name]['statuses'].append("MISSING")


        # --- Prepare Summary Data for Display ---
        summary_display_data: List[Dict[str, Any]] = []
        for jar_name, data in aggregated_data.items():
            scores = data['scores']
            correct_runs = data['correct_runs']
            total_runs = data['total_runs'] # Should equal num_iterations
            avg_score = np.mean(scores) if scores else 0.0
            std_dev = np.std(scores) if scores else 0.0
            success_rate = (correct_runs / total_runs * 100) if total_runs > 0 else 0.0
            # Create a simple status summary (e.g., count of each status)
            status_counts = defaultdict(int)
            for s in data['statuses']: status_counts[s] += 1
            status_summary = ", ".join([f"{s}:{c}" for s,c in sorted(status_counts.items())])


            summary_display_data.append({
                "jar": jar_name,
                "avg_score": avg_score,
                "std_dev": std_dev,
                "correct": correct_runs,
                "total": total_runs,
                "success_%": success_rate,
                "status_summary": status_summary
            })

        # Sort summary data: by success rate (desc), then avg score (desc), then jar name (asc)
        summary_display_data.sort(key=lambda x: (-x["success_%"], -x["avg_score"], x["jar"]))

        # --- Format Summary Lines ---
        if CustomTester._interrupted:
            summary_lines.append("\n--- Testing Interrupted - Overall Summary (Based on Completed Iterations/Runs) ---")
        else:
            summary_lines.append("\n--- Testing Finished - Overall Summary ---")

        summary_lines.append(f"Input File: {os.path.basename(input_file_path)}")
        summary_lines.append(f"Total Iterations Run: {num_iterations}")
        summary_lines.append("-" * 80) # Adjust separator length

        # Define header based on calculated data
        header = f"{'JAR':<25} | {'Avg Score':<10} | {'Std Dev':<8} | {'Correct':<8} | {'Success':<8} | Status Counts"
        summary_lines.append(header)
        summary_lines.append("-" * len(header)) # Match header length

        for item in summary_display_data:
             # Format line carefully
             line = (f"{item['jar']:<25} | "
                     f"{item['avg_score']:<10.3f} | "
                     f"{item['std_dev']:<8.3f} | "
                     f"{str(item['correct']) + '/' + str(item['total']):<8} | " # e.g., "8/10"
                     f"{item['success_%']:<7.1f}% | "
                     f"{item['status_summary']}")
             summary_lines.append(line)

        summary_lines.append("-" * len(header))

        # --- Print Summary to Console (Locked) ---
        summary_string = "\n".join(summary_lines)
        with CustomTester._console_lock:
            print(summary_string)

        # --- Write Summary to Log File (Locked) ---
        if CustomTester._log_file_path:
            try:
                 with CustomTester._log_lock:
                    with open(CustomTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                        f.write("\n\n" + "="*20 + " FINAL OVERALL SUMMARY " + "="*20 + "\n")
                        f.write(summary_string + "\n")
                        f.write("="* (40 + len(" FINAL OVERALL SUMMARY ")) + "\n")
                    debug_print("Final overall summary also written to log file.")
            except Exception as e_log_summary:
                # Use console lock for safety
                with CustomTester._console_lock:
                    print(f"ERROR: Failed to write final overall summary to log file {CustomTester._log_file_path}: {e_log_summary}", file=sys.stderr)

    # --- Main test method - Refactored to handle iterations and parallelism ---
    @staticmethod
    def test(hw_n: str, jar_dir_path: str, input_file: str, iterations: int, parallel_runs: int, wall_time_override: Optional[float], search_string: Optional[str]):
        """Main testing entry point handling setup, iterations, and overall summary."""
        main_start_time = time.monotonic()
        all_results_across_iterations: List[List[Dict[str, Any]]] = [] # List to store results from each iteration

        try:
            # --- Initial Setup (Done Once) ---
            with CustomTester._console_lock:
                 print("--- Elevator Custom Tester Initialization ---")
            hw_n_path = str(hw_n).replace(".", os.sep) # Allows using "." like "hw6.1"
            CustomTester._jar_dir = jar_dir_path
            # Construct checker path relative to the script or CWD if hw_n is just a name
            # Assuming hw_n is a directory path relative to where script is run
            if os.path.isdir(hw_n_path):
                 CustomTester._checker_script_path = os.path.abspath(os.path.join(hw_n_path, "checker.py"))
            else:
                 # Try finding checker relative to script's directory if hw_n isn't a dir
                 script_dir = os.path.dirname(__file__)
                 potential_path = os.path.abspath(os.path.join(script_dir, hw_n_path, "checker.py"))
                 if os.path.exists(potential_path):
                     CustomTester._checker_script_path = potential_path
                 else:
                      with CustomTester._console_lock:
                          print(f"ERROR: Cannot find checker script. '{hw_n_path}' is not a directory and checker not found relative to script.", file=sys.stderr)
                      return # Abort

            selected_input_file_path = input_file # Start with the default/fallback

            if search_string:
                with CustomTester._console_lock:
                    print(f"INFO: --search provided ('{search_string}'). Searching in '{TMP_DIR}/'...")
                found_files = []
                try:
                    if os.path.isdir(TMP_DIR):
                        for filename in os.listdir(TMP_DIR):
                            if search_string in filename:
                                found_files.append(filename)
                    else:
                         with CustomTester._console_lock:
                              print(f"WARNING: Temporary directory '{TMP_DIR}' not found for search. Falling back to --input-file.", file=sys.stderr)

                    if len(found_files) == 1:
                        found_path = os.path.join(TMP_DIR, found_files[0])
                        selected_input_file_path = found_path
                        with CustomTester._console_lock:
                            print(f"INFO: Search successful. Using input file found: {selected_input_file_path}")
                    elif len(found_files) == 0:
                         with CustomTester._console_lock:
                            print(f"WARNING: Search failed. No files containing '{search_string}' found in '{TMP_DIR}'. Falling back to --input-file: {input_file}", file=sys.stderr)
                    else: # More than 1 found
                        with CustomTester._console_lock:
                            print(f"WARNING: Search failed. Multiple files found containing '{search_string}' in '{TMP_DIR}':", file=sys.stderr)
                            for f in found_files:
                                print(f"  - {f}", file=sys.stderr)
                            print(f"Falling back to --input-file: {input_file}", file=sys.stderr)

                except Exception as e_search:
                     with CustomTester._console_lock:
                          print(f"ERROR: Exception during file search in '{TMP_DIR}': {e_search}. Falling back to --input-file: {input_file}", file=sys.stderr)

            # Set the final input file path for the tester
            CustomTester._input_file_path = os.path.abspath(selected_input_file_path)
            
            CustomTester._interrupted = False
            # Clear any potential leftover state (though instance should be fresh)
            CustomTester._jar_files = []
            CustomTester._finder_executed = False

            # Create Log and Temp Dirs
            os.makedirs(LOG_DIR, exist_ok=True)
            os.makedirs(TMP_DIR, exist_ok=True)

            # Setup Logging (Filename includes input name)
            local_time = time.localtime()
            formatted_time = time.strftime("%Y%m%d_%H%M%S", local_time)
            input_basename = os.path.splitext(os.path.basename(CustomTester._input_file_path))[0]
            safe_input_basename = re.sub(r'[^\w.-]+', '_', input_basename)
            iter_str = f"x{iterations}" if iterations > 1 else "single"
            CustomTester._log_file_path = os.path.abspath(os.path.join(LOG_DIR, f"{formatted_time}_custom_{safe_input_basename}_{iter_str}.log"))

            with CustomTester._console_lock:
                print(f"INFO: Logging summary and errors to: {CustomTester._log_file_path}")
                print(f"INFO: Storing temporary output files in: {os.path.abspath(TMP_DIR)}")
                print(f"INFO: Using custom input file: {CustomTester._input_file_path}")
                print(f"INFO: Requested iterations: {iterations}")
                if iterations > 1:
                     print(f"INFO: Requested parallel iterations: {parallel_runs}")


            # Check for checker script existence
            if not os.path.exists(CustomTester._checker_script_path):
                 with CustomTester._console_lock:
                     print(f"ERROR: Checker script not found: {CustomTester._checker_script_path}", file=sys.stderr)
                 return # Abort

            # Find JAR files
            if not CustomTester._find_jar_files():
                 with CustomTester._console_lock:
                     print("ERROR: No JAR files found or accessible. Aborting.", file=sys.stderr)
                 return # Abort
            if not CustomTester._jar_files: # Double check if list is empty
                 with CustomTester._console_lock:
                     print("ERROR: JAR file list is empty after search. Aborting.", file=sys.stderr)
                 return # Abort

            # Setup Signal Handler for Ctrl+C
            signal.signal(signal.SIGINT, CustomTester._signal_handler)

            # --- Read Input Data (Once) ---
            with CustomTester._console_lock:
                 print("\nReading and parsing input file...")
            raw_input_content, max_timestamp = CustomTester._read_input_data(CustomTester._input_file_path)

            if raw_input_content is None:
                with CustomTester._console_lock:
                     print(f"ERROR: Failed to read or parse input file '{CustomTester._input_file_path}'. Aborting.", file=sys.stderr)
                # Log the failure
                if CustomTester._log_file_path:
                     try:
                         with CustomTester._log_lock:
                             with open(CustomTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                                 f.write(f"\n--- TEST ABORTED: FAILED TO READ/PARSE INPUT ---\nInput File: {CustomTester._input_file_path}\n")
                     except Exception as e_log: print(f"ERROR: Failed to log input read failure: {e_log}", file=sys.stderr)
                return # Abort

            # --- Calculate Wall Time Limit (Once) ---
            wall_time_limit_used: float
            if wall_time_override is not None and wall_time_override > 0:
                # Use user override, but ensure it meets the minimum
                wall_time_limit_used = max(MIN_WALL_TIME_LIMIT, wall_time_override)
                with CustomTester._console_lock:
                    print(f"INFO: Using user-provided wall time limit: {wall_time_limit_used:.1f}s (Min enforced: {MIN_WALL_TIME_LIMIT:.1f}s)")
            else:
                # Calculate based on max timestamp from input
                calculated_limit = max_timestamp * DEFAULT_WALL_TIME_BUFFER_FACTOR + DEFAULT_WALL_TIME_ADDITIONAL_SECONDS
                wall_time_limit_used = max(MIN_WALL_TIME_LIMIT, calculated_limit)
                with CustomTester._console_lock:
                    print(f"INFO: Calculated wall time limit based on max timestamp ({max_timestamp:.2f}s): {wall_time_limit_used:.1f}s (Buffer: x{DEFAULT_WALL_TIME_BUFFER_FACTOR}+{DEFAULT_WALL_TIME_ADDITIONAL_SECONDS:.1f}s, Min: {MIN_WALL_TIME_LIMIT:.1f}s)")
            debug_print(f"Final Wall Time Limit set to: {wall_time_limit_used:.2f}s for all iterations.")

            # --- Ready to Start Iterations ---
            with CustomTester._console_lock:
                print(f"\nSetup complete. Found {len(CustomTester._jar_files)} JARs.")
                print(f"Input: '{os.path.basename(CustomTester._input_file_path)}'. Wall Limit: {wall_time_limit_used:.1f}s.")
                print(f"Will run {iterations} iteration(s).")
                if iterations > 1:
                     # Determine actual parallelism
                     actual_parallel_runs = max(1, min(parallel_runs, iterations))
                     print(f"Will run up to {actual_parallel_runs} iteration(s) concurrently.")
                print(f"\nPress Ctrl+C during execution to attempt graceful interruption.")
                print("="*40)
            # Optional: Pause before starting iterations
            # input("Press Enter to begin testing iterations...")
            # CustomTester._clear_screen()
            # print("="*40 + "\n")

            # --- Execute Iterations ---
            if iterations <= 0:
                 with CustomTester._console_lock:
                      print("INFO: Number of iterations is zero or negative. Nothing to run.")
            elif iterations == 1:
                 # Run a single iteration directly
                 with CustomTester._console_lock:
                     print("Starting single test iteration...")
                 # Check interrupt before starting the single run
                 if not CustomTester._interrupted:
                      iter_results = CustomTester._run_single_iteration(
                          iteration_num=1,
                          total_iterations=1,
                          jar_files_to_run=CustomTester._jar_files,
                          input_content=raw_input_content,
                          input_file_path=CustomTester._input_file_path,
                          wall_limit=wall_time_limit_used
                      )
                      all_results_across_iterations.append(iter_results)
                 else:
                      with CustomTester._console_lock:
                          print("Interrupted before starting the single iteration.")

            else: # iterations > 1
                 actual_parallel_runs = max(1, min(parallel_runs, iterations))
                 with CustomTester._console_lock:
                      print(f"Starting {iterations} testing iterations (up to {actual_parallel_runs} in parallel)...")

                 # Use an outer ThreadPoolExecutor for managing parallel iterations
                 with concurrent.futures.ThreadPoolExecutor(max_workers=actual_parallel_runs, thread_name_prefix='IterExec') as outer_executor:
                     iteration_futures: Dict[concurrent.futures.Future, int] = {} # Future -> iteration_num
                     submitted_count = 0
                     try:
                         for i in range(1, iterations + 1):
                             # Check interrupt flag before submitting each iteration
                             if CustomTester._interrupted:
                                 with CustomTester._console_lock:
                                      print(f"Interrupted before submitting iteration {i}.")
                                 break # Stop submitting new iterations

                             future = outer_executor.submit(
                                 CustomTester._run_single_iteration,
                                 iteration_num=i,
                                 total_iterations=iterations,
                                 jar_files_to_run=CustomTester._jar_files, # Pass the list of JARs
                                 input_content=raw_input_content,
                                 input_file_path=CustomTester._input_file_path,
                                 wall_limit=wall_time_limit_used
                             )
                             iteration_futures[future] = i
                             submitted_count += 1

                         with CustomTester._console_lock:
                              print(f"Submitted {submitted_count} iterations to the executor.")

                     except Exception as e_outer_submit:
                          with CustomTester._console_lock:
                              print(f"\nFATAL ERROR: Failed to submit iterations to executor: {e_outer_submit}", file=sys.stderr)
                          debug_print("Exception during iteration future submission", exc_info=True)
                          # Attempt to cancel already submitted futures? Might be complex.
                          CustomTester._interrupted = True # Signal interruption

                     # Collect results from completed iteration futures
                     completed_iterations = 0
                     # Process futures as they complete
                     for future in concurrent.futures.as_completed(iteration_futures):
                          iteration_num = iteration_futures[future]
                          try:
                              # Get the list of results returned by _run_single_iteration
                              iter_result_list = future.result()
                              all_results_across_iterations.append(iter_result_list)
                              completed_iterations += 1
                              with CustomTester._console_lock:
                                   print(f"<<< Iteration {iteration_num}/{iterations} has completed. ({completed_iterations}/{submitted_count} finished) >>>")
                          except concurrent.futures.CancelledError:
                               with CustomTester._console_lock:
                                   print(f"WARNING: Iteration {iteration_num} was cancelled.", file=sys.stderr)
                               # Append an empty list or marker? Append empty list for now.
                               all_results_across_iterations.append([])
                          except Exception as exc:
                               with CustomTester._console_lock:
                                   print(f'\nERROR: Iteration {iteration_num} execution failed unexpectedly: {exc}', file=sys.stderr)
                               debug_print(f"Exception from iteration future {iteration_num}", exc_info=True)
                               # Append an empty list as results are likely unusable
                               all_results_across_iterations.append([])
                               completed_iterations += 1 # Count as finished, albeit failed

                          # Check interrupt flag while waiting for iterations
                          if CustomTester._interrupted:
                              debug_print("Interrupt detected while collecting iteration results.")
                              # Don't break, allow collection of already finished iterations

                     # End of outer ThreadPoolExecutor for iterations
                     debug_print("Outer iteration executor finished.")
                     if completed_iterations < submitted_count and not CustomTester._interrupted:
                         with CustomTester._console_lock:
                              print(f"WARNING: Only {completed_iterations} out of {submitted_count} submitted iterations finished normally.", file=sys.stderr)


            # --- Iterations Complete ---
            if CustomTester._interrupted:
                 with CustomTester._console_lock:
                     print("\nRun interrupted. Final summary will be based on completed runs.")
            else:
                 with CustomTester._console_lock:
                     print(f"\nAll {len(all_results_across_iterations)} requested/submitted iterations have finished processing.")

            # --- Final Overall Summary ---
            # This happens regardless of interruption, summarizing whatever completed.
            with CustomTester._console_lock:
                print("\nGenerating final overall summary...")
            CustomTester._print_overall_summary(all_results_across_iterations, CustomTester._input_file_path)


        except Exception as e_main:
            # Catch fatal errors in the main setup/orchestration part
            with CustomTester._console_lock: # Lock for safe printing
                print(f"\nFATAL ERROR in main testing thread: {e_main}", file=sys.stderr)
            debug_print("Fatal error in main test execution", exc_info=True)
            # Try to log the fatal error
            if CustomTester._log_file_path:
                 try:
                     with CustomTester._log_lock: # Lock for safe writing
                         with open(CustomTester._log_file_path, "a", encoding="utf-8", errors='replace') as f:
                             f.write(f"\n\n!!! FATAL MAIN TESTER ERROR !!!\n{time.strftime('%Y-%m-%d %H:%M:%S')}\nError: {e_main}\n")
                             traceback.print_exc(file=f)
                 except Exception as e_log_main_fatal:
                      # Use console lock if logging the log error
                      with CustomTester._console_lock:
                           print(f"ERROR: Also failed to log fatal main error: {e_log_main_fatal}", file=sys.stderr)

        finally:
            # --- Final Cleanup ---
            # Optional: Clean up temporary directory contents?
            # Be careful if multiple instances run concurrently
            # print(f"\nTemporary files are in: {os.path.abspath(TMP_DIR)}")

            main_end_time = time.monotonic()
            # Use console lock for final message
            with CustomTester._console_lock:
                print(f"\nTotal execution time: {main_end_time - main_start_time:.2f} seconds.")
                print("--- Testing Complete ---")


# --- Main Execution Block ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Elevator Custom Input Tester with Iterations and Parallelism",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter # Show defaults in help
        )
    parser.add_argument("hw_n",
                        help="Homework identifier (e.g., 'hw6' or 'hw6.1'), "
                             "used to find the checker.py script (expects './<hw_n>/checker.py').")
    parser.add_argument("jar_path",
                        help="Path to the directory containing student JAR files.")
    parser.add_argument("--input-file", default=DEFAULT_INPUT_FILE,
                        help="Path to the custom input file.")
    parser.add_argument("--search", type=str, default=None,
                        help="Search string. If provided, look for a *unique* file in the 'tmp/' directory "
                             "containing this string in its name and use it as input. Falls back to --input-file on failure.")
    parser.add_argument("--iterations", "-n", type=int, default=1,
                        help="Number of times to run the test with the same input.")
    parser.add_argument("--parallel", "-p", type=int, default=1,
                        help="Number of iterations to run in parallel (only applies if iterations > 1).")
    parser.add_argument("--wall-time-limit", "-t", type=float, default=None,
                        help="Override calculated wall time limit (seconds). Minimum still applies.")
    parser.add_argument("--debug", action='store_true',
                        help="Enable detailed debug output to stderr.")

    args = parser.parse_args()

    if args.debug:
        ENABLE_DETAILED_DEBUG = True
        debug_print("Detailed debugging enabled.")

    # Validate paths early
    hw_dir_for_checker = args.hw_n # We use this to find the checker, check its validity inside test()
    jar_dir = args.jar_path
    input_f = args.input_file

    # Basic validation before starting
    if not os.path.isdir(jar_dir):
        print(f"ERROR: JAR directory '{jar_dir}' not found or is not a directory.", file=sys.stderr)
        sys.exit(1)
    # Input file existence is checked within _read_input_data
    # Checker existence is checked within test()

    if args.iterations <= 0:
         print(f"INFO: Iterations set to {args.iterations}. No tests will be run.", file=sys.stderr)
         sys.exit(0)

    if args.iterations > 1 and args.parallel <= 0:
         print(f"WARNING: Parallel runs set to {args.parallel}, defaulting to 1.", file=sys.stderr)
         args.parallel = 1

    # Call the main test method with parsed arguments
    CustomTester.test(
        hw_n=hw_dir_for_checker,
        jar_dir_path=jar_dir,
        input_file=input_f,
        iterations=args.iterations,
        parallel_runs=args.parallel,
        wall_time_override=args.wall_time_limit,
        search_string=args.search
        )

# --- END OF FILE custom.py ---