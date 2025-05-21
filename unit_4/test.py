# --- START OF FILE test.py ---

# tester.py
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
import concurrent.futures
import random
import traceback
import yaml
import json

# --- Default Configuration, will be replaced by config.yml ---
CPU_TIME_LIMIT = 10.0  # seconds for the driver process
MIN_WALL_TIME_LIMIT = 15.0 # Minimum floor for any wall time limit
BASE_WALL_TIME_PER_CYCLE = 2.5 # Estimated time per cycle in driver.py
BASE_FIXED_OVERHEAD_TIME = 5.0 # Estimated fixed overhead for driver (startup, SUT init, etc.)
DEFAULT_ESTIMATED_WALL_TIME = 50.0 # Fallback wall time if --max_cycles not in preset

ENABLE_DETAILED_DEBUG = False
LOG_DIR = "logs"
TMP_DIR = "tmp"
DEFAULT_PARALLEL_ROUNDS = 16
CLEANUP_SUCCESSFUL_ROUNDS = True

# Helper function for conditional debug printing
def debug_print(*args, **kwargs):
    if ENABLE_DETAILED_DEBUG:
        thread_name = threading.current_thread().name
        print(f"DEBUG [{time.time():.4f}] [{thread_name}]:", *args, **kwargs, file=sys.stderr, flush=True)

class JarTester:
    _jar_files = []
    _finder_executed = False
    _jar_dir = ""
    _driver_script_path = ""
    _interrupted = False
    _round_counter = 0
    _log_file_path = None
    _all_results_history = defaultdict(lambda: {'correct_runs': 0, 'total_runs': 0})
    _gen_arg_presets = [] # List of preset dictionaries
    _raw_preset_commands = [] # List of raw preset strings (for logging)
    _loaded_preset_commands = []

    _history_lock = threading.Lock()
    _log_lock = threading.Lock()
    _round_counter_lock = threading.Lock()
    _console_lock = threading.Lock()

    @staticmethod
    def _get_next_round_number():
        with JarTester._round_counter_lock:
            JarTester._round_counter += 1
            return JarTester._round_counter

    @staticmethod
    def _clear_screen(): # (Unchanged)
        if ENABLE_DETAILED_DEBUG: return
        if threading.current_thread() is threading.main_thread():
             os.system('cls' if os.name == 'nt' else 'clear')

    @staticmethod
    def _find_jar_files(): # (Unchanged)
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
    def _kill_process_tree(pid): # (Unchanged)
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try: child.terminate()
                except psutil.NoSuchProcess: pass
            parent.terminate()
            gone, alive = psutil.wait_procs(children + [parent], timeout=1.0)
            for p in alive:
                try: p.kill()
                except psutil.NoSuchProcess: pass
        except psutil.NoSuchProcess: pass
        except Exception as e:
            print(f"ERROR: Exception during process termination for PID {pid}: {e}", file=sys.stderr)

    @staticmethod
    def _output_reader(pipe, output_queue, stream_name, pid, error_flag): # (Unchanged)
        debug_print(f"Output reader ({stream_name}) started for PID {pid}")
        try:
            for line_num, line in enumerate(iter(pipe.readline, '')):
                if error_flag.is_set() or JarTester._interrupted: break
                output_queue.put(line)
        except ValueError: pass
        except Exception as e:
            if not error_flag.is_set() and not JarTester._interrupted:
                print(f"ERROR: Output reader ({stream_name}) thread crashed for PID {pid}: {e}", file=sys.stderr)
                error_flag.set()
        finally:
            try: pipe.close()
            except Exception: pass
            debug_print(f"Output reader ({stream_name}) thread exiting for PID {pid}")

    @staticmethod
    def _run_single_driver_instance(jar_under_test_path, driver_args_list, calculated_wall_limit, round_num, seed_value): # param renamed
        jar_basename = os.path.basename(jar_under_test_path)
        # Use the calculated_wall_limit passed to this function
        debug_print(f"Starting DRIVER run for JAR: {jar_basename} (Seed: {seed_value}) with Calculated Wall Limit: {calculated_wall_limit:.2f}s")
        start_wall_time = time.monotonic()
        driver_process = None
        pid = -1
        ps_proc = None
        result = {
            "jar_file": jar_basename, "cpu_time": 0.0, "wall_time": 0.0,
            "status": "PENDING", "error_details": "",
            "driver_stdout": [], "driver_stderr": [],
            "driver_input_log_path": None, "driver_sut_output_log_path": None,
            "seed_used": seed_value
        }
        stdout_reader_thread, stderr_reader_thread = None, None
        stdout_queue, stderr_queue = queue.Queue(), queue.Queue()
        error_flag = threading.Event()

        safe_jar_basename = re.sub(r'[^\w.-]', '_', jar_basename)
        driver_sut_input_log = os.path.abspath(os.path.join(TMP_DIR, f"driver_input_sut_{safe_jar_basename}_{seed_value}_{round_num}.txt"))
        driver_sut_output_log = os.path.abspath(os.path.join(TMP_DIR, f"driver_output_sut_{safe_jar_basename}_{seed_value}_{round_num}.txt"))
        result["driver_input_log_path"] = driver_sut_input_log
        result["driver_sut_output_log_path"] = driver_sut_output_log

        command_for_driver = [
            sys.executable, JarTester._driver_script_path, jar_under_test_path
        ] + driver_args_list + ["-i", driver_sut_input_log, "-o", driver_sut_output_log]
        debug_print(f"Driver command for {jar_basename}: {' '.join(command_for_driver)}")

        try:
            driver_process = subprocess.Popen(
                command_for_driver, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace', bufsize=1
            )
            pid = driver_process.pid
            result["status"] = "RUNNING_DRIVER"
            try: ps_proc = psutil.Process(pid)
            except psutil.NoSuchProcess as e:
                result["status"] = "CRASHED_DRIVER"; result["error_details"] = f"Driver disappeared: {e}"; error_flag.set(); return result

            stdout_reader_thread = threading.Thread(target=JarTester._output_reader, args=(driver_process.stdout, stdout_queue, "driver_stdout", pid, error_flag), daemon=True)
            stderr_reader_thread = threading.Thread(target=JarTester._output_reader, args=(driver_process.stderr, stderr_queue, "driver_stderr", pid, error_flag), daemon=True)
            stdout_reader_thread.start(); stderr_reader_thread.start()

            process_exited_normally = False
            while True:
                try:
                    if not ps_proc.is_running(): process_exited_normally = True; break
                except psutil.NoSuchProcess: process_exited_normally = True; break
                if error_flag.is_set() or JarTester._interrupted: break

                current_wall_time = time.monotonic() - start_wall_time
                current_cpu_time = 0.0
                try:
                    if psutil.pid_exists(pid) and ps_proc.is_running():
                         cpu_times = ps_proc.cpu_times(); current_cpu_time = cpu_times.user + cpu_times.system
                    else: process_exited_normally = True; break
                except psutil.NoSuchProcess: process_exited_normally = True; break
                except Exception as e:
                    result["status"] = "CRASHED_DRIVER"; result["error_details"] = f"CPU time error: {e}"; error_flag.set(); break
                result["cpu_time"] = current_cpu_time; result["wall_time"] = current_wall_time
                if current_cpu_time > CPU_TIME_LIMIT:
                    result["status"] = "CTLE_DRIVER"; result["error_details"] = f"CPU {current_cpu_time:.2f}s > {CPU_TIME_LIMIT:.2f}s"; error_flag.set(); break
                if current_wall_time > calculated_wall_limit: # Use calculated limit
                    result["status"] = "TLE_DRIVER"; result["error_details"] = f"Wall {current_wall_time:.2f}s > {calculated_wall_limit:.2f}s"; error_flag.set(); break
                time.sleep(0.05)

            if error_flag.is_set() and pid != -1:
                 try:
                     if driver_process and driver_process.poll() is None: JarTester._kill_process_tree(pid)
                     elif psutil.pid_exists(pid): JarTester._kill_process_tree(pid)
                 except Exception: pass

            # (Thread join logic unchanged)
            thread_join_timeout = 2.0; threads_to_join = [t for t in [stdout_reader_thread, stderr_reader_thread] if t and t.is_alive()]
            start_join_time = time.monotonic()
            while threads_to_join and time.monotonic() - start_join_time < thread_join_timeout:
                for t in threads_to_join[:]: t.join(timeout=0.1);
                if not t.is_alive(): threads_to_join.remove(t)

            result["wall_time"] = time.monotonic() - start_wall_time
            try:
                if psutil.pid_exists(pid):
                     final_cpu_times = psutil.Process(pid).cpu_times(); result["cpu_time"] = final_cpu_times.user + final_cpu_times.system
            except psutil.NoSuchProcess: pass
            try:
                while True: result["driver_stdout"].append(stdout_queue.get(block=False))
            except queue.Empty: pass
            try:
                while True: result["driver_stderr"].append(stderr_queue.get(block=False))
            except queue.Empty: pass

            final_status_determined = result["status"] not in ["RUNNING_DRIVER", "PENDING"]
            if process_exited_normally and not final_status_determined:
                exit_code = None
                try: exit_code = driver_process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    result["status"] = "CRASHED_DRIVER"; result["error_details"] = "Driver no exit code."; final_status_determined = True
                    try: JarTester._kill_process_tree(pid)
                    except Exception: pass
                if exit_code is not None:
                    driver_stdout_full = "".join(result["driver_stdout"]).strip()
                    if not driver_stdout_full:
                        result["status"] = "CHECKER_ERROR" if exit_code == 0 else "CRASHED_DRIVER"
                        result["error_details"] = f"Driver exit {exit_code}, no JSON output."
                    else:
                        try:
                            driver_json = json.loads(driver_stdout_full)
                            ds = driver_json.get("status")
                            if ds == "success": result["status"] = "CORRECT"; result["error_details"] = "Driver: success."
                            elif ds == "failure": result["status"] = "INCORRECT"; result["error_details"] = f"Driver: {driver_json.get('reason', 'failure, no reason')}"
                            else: result["status"] = "CHECKER_ERROR"; result["error_details"] = f"Driver JSON unknown status: '{ds}'. Output: {driver_stdout_full[:100]}"
                        except json.JSONDecodeError:
                            result["status"] = "CHECKER_ERROR"; result["error_details"] = f"Driver JSON parse error. Exit {exit_code}. Output: {driver_stdout_full[:100]}"
                        except Exception as e:
                            result["status"] = "CHECKER_ERROR"; result["error_details"] = f"Driver JSON process error: {e}. Output: {driver_stdout_full[:100]}"
                    final_status_determined = True
                if exit_code != 0 and not final_status_determined:
                    result["status"] = "CRASHED_DRIVER"; result["error_details"] = f"Driver exit {exit_code}."
            if JarTester._interrupted and not final_status_determined: result["status"] = "INTERRUPTED"; result["error_details"] = "Interrupted."
            if not final_status_determined: result["status"] = "COMPLETED_DRIVER"; result["error_details"] = "Driver finished; check JSON."
        except FileNotFoundError: result["status"] = "CRASHED_DRIVER"; result["error_details"] = f"Driver script not found."
        except Exception as e: result["status"] = "CRASHED_DRIVER"; result["error_details"] = f"Tester error: {e}"
        finally:
            if pid != -1 and driver_process and driver_process.poll() is None:
                try: JarTester._kill_process_tree(pid)
                except Exception: pass
            if stdout_reader_thread and stdout_reader_thread.is_alive(): stdout_reader_thread.join(timeout=0.1)
            if stderr_reader_thread and stderr_reader_thread.is_alive(): stderr_reader_thread.join(timeout=0.1)
        debug_print(f"Finished DRIVER run for JAR: {jar_basename}. Final Status: {result['status']}")
        return result

    @staticmethod
    def _display_and_log_results(round_num, results, round_preset_cmd_with_seed, calculated_round_wall_limit): # param renamed
        log_lines = []
        results.sort(key=lambda x: (0 if x.get("status") == "CORRECT" else 1, x.get("jar_file", "")))
        round_header = f"\n--- Test Round {round_num} Results (Preset: {round_preset_cmd_with_seed} | Wall Limit Used: {calculated_round_wall_limit:.1f}s) ---"
        header = f"{'JAR':<25} | {'Status':<18} | {'CPU(s)':<8} | {'Wall(s)':<8} | Details"
        separator = "-" * len(header)
        log_lines.append(round_header.replace(" Results ", " Summary "))
        log_lines.append(f"Seed Used: {results[0].get('seed_used', '<N/A>') if results else '<N/A>'}")
        log_lines.append(header); log_lines.append(separator)
        error_log_header_needed = True
        result_lines_for_console = []
        for r in results:
            status = r.get("status", "UNKNOWN")
            console_line = f"{r.get('jar_file', 'Unknown'):<25} | {status:<18} | {r.get('cpu_time', 0.0):<8.2f} | {r.get('wall_time', 0.0):<8.2f} | {r.get('error_details', '')[:100]}"
            result_lines_for_console.append(console_line)
            log_lines.append(f"{r.get('jar_file', 'Unknown'):<25} | {status:<18} | {r.get('cpu_time', 0.0):<8.2f} | {r.get('wall_time', 0.0):<8.2f} | {r.get('error_details', '')}")
            non_error_statuses = ["CORRECT", "PENDING", "RUNNING_DRIVER", "COMPLETED_DRIVER", "INTERRUPTED"]
            if status not in non_error_statuses:
                if error_log_header_needed:
                    log_lines.append(f"\n--- Test Round {round_num} Error Details ---"); log_lines.append(f"Seed Used: {r.get('seed_used', '<N/A>')}"); error_log_header_needed = False
                log_lines.append(f"\n--- Error for: {r['jar_file']} (Status: {status}) ---")
                log_lines.append(f"  Preset: {round_preset_cmd_with_seed}\n  Wall Limit Applied: {calculated_round_wall_limit:.1f}s\n  Error: {r.get('error_details', '')}")
                log_lines.append(f"  Driver SUT Input Log: {r.get('driver_input_log_path', '<N/A>')}\n  Driver SUT Output Log: {r.get('driver_sut_output_log_path', '<N/A>')}")
                log_lines.append("  --- Driver Stdout (JSON) ---\n" + "".join(r.get('driver_stdout', ['<empty>'])) + "\n  --- End Driver Stdout ---")
                log_lines.append("  --- Driver Stderr ---\n" + "".join(r.get('driver_stderr', ['<empty>'])) + "\n  --- End Driver Stderr ---")
        log_lines.append(separator)
        with JarTester._console_lock: # (Console print logic unchanged)
            print(round_header); print(header); print(separator)
            for line in result_lines_for_console: print(line)
            print(separator); print(f"--- End of Round {round_num} ---")
        if JarTester._log_file_path: # (Log write logic unchanged)
            try:
                with JarTester._log_lock:
                    with open(JarTester._log_file_path, "a", encoding="utf-8", errors='replace') as f: f.write("\n".join(log_lines) + "\n\n")
            except Exception as e: print(f"ERROR: Failed to write log for round {round_num}: {e}", file=sys.stderr)

    @staticmethod
    def _update_history(results): # (Unchanged)
        with JarTester._history_lock:
            for r in results:
                if r.get("status") == "INTERRUPTED": continue
                jar_name = r.get("jar_file", "UnknownJAR"); history = JarTester._all_results_history[jar_name]
                history['total_runs'] += 1
                if r.get("status") == "CORRECT": history['correct_runs'] += 1

    @staticmethod
    def _print_summary(): # (Unchanged)
        summary_lines = []; summary_lines.append("\n--- Testing Interrupted ---" if JarTester._interrupted else "\n--- Testing Finished ---")
        summary_lines.append(f"Total test rounds initiated: {JarTester._round_counter}")
        with JarTester._history_lock:
            if not JarTester._all_results_history: summary_lines.append("No completed test results."); return "\n".join(summary_lines)
            summary_lines.append("\n--- Final Summary ---"); summary_data = []
            history_items = list(JarTester._all_results_history.items())
        for jar_name, data in history_items:
            total = data.get('total_runs', 0); correct = data.get('correct_runs', 0)
            rate = (correct / total * 100) if total > 0 else 0.0
            summary_data.append({"jar": jar_name, "correct_rate": rate, "correct": correct, "total": total})
        summary_data.sort(key=lambda x: (-x["correct_rate"], x["jar"]))
        header = f"{'JAR':<25} | {'Correct %':<10} | {'Passed/Total':<15}"
        summary_lines.append(header); summary_lines.append("-" * len(header))
        for item in summary_data: summary_lines.append(f"{item['jar']:<25} | {item['correct_rate']:<10.1f}% | {item['correct']}/{item['total']:<15}")
        summary_lines.append("-" * len(header)); return "\n".join(summary_lines)

    @staticmethod
    def _signal_handler(sig, frame): # (Unchanged)
        if not JarTester._interrupted: print("\nCtrl+C detected. Stopping...", file=sys.stderr); JarTester._interrupted = True

    # MODIFIED: _initialize_presets to find --max_cycles
    @staticmethod
    def _initialize_presets():
        JarTester._gen_arg_presets = [] # List of dicts
        JarTester._raw_preset_commands = [] # List of strings
        if not JarTester._loaded_preset_commands:
            print("ERROR: No driver presets loaded from gen_presets.yml.", file=sys.stderr); return False
        for cmd_str in JarTester._loaded_preset_commands:
            parts = cmd_str.split()
            args_dict = {}
            i = 0
            while i < len(parts):
                arg = parts[i]
                if not arg.startswith('-'): i += 1; continue
                # Check for --max_cycles or -mc
                if arg in ["--max_cycles", "-mc"]:
                    if i + 1 < len(parts) and not parts[i+1].startswith('-'):
                        try:
                            args_dict['_max_cycles_for_wall_time'] = int(parts[i+1]) # Store specially
                        except ValueError:
                            print(f"WARNING: Invalid value for {arg} in preset '{cmd_str}'. Ignoring for wall time calculation.", file=sys.stderr)
                # Generic argument parsing
                if i + 1 < len(parts) and not parts[i+1].startswith('-'):
                    value_str = parts[i+1]
                    try: value = int(value_str)
                    except ValueError:
                        try: value = float(value_str)
                        except ValueError: value = value_str
                    args_dict[arg] = value; i += 2
                else: args_dict[arg] = True; i += 1
            JarTester._gen_arg_presets.append(args_dict)
            JarTester._raw_preset_commands.append(cmd_str)
        num_presets = len(JarTester._gen_arg_presets)
        print(f"INFO: Parsed {num_presets} valid driver presets.")
        return num_presets > 0

    @staticmethod
    def _preset_dict_to_arg_list(preset_dict): # (Unchanged from previous driver integration)
        args_list = []
        for key, value in preset_dict.items():
            if key == '_max_cycles_for_wall_time': continue # Don't pass this internal key to driver
            args_list.append(key)
            if value is not True: args_list.append(str(value))
        return args_list

    # MODIFIED: _run_one_round for wall time calculation
    @staticmethod
    def _run_one_round(round_num):
        if JarTester._interrupted: return None
        thread_name = threading.current_thread().name
        print(f"INFO [{thread_name}]: Starting Test Round {round_num}")

        # Wall time calculation based on preset
        round_wall_time_limit = DEFAULT_ESTIMATED_WALL_TIME # Fallback
        selected_preset_cmd_str = "<Not Selected>"
        current_seed = -1
        full_driver_args_str_with_seed = "<Not Set>"

        try:
            if not JarTester._gen_arg_presets: print(f"ERROR [{thread_name}]: No driver presets.", file=sys.stderr); return None
            preset_index = random.randrange(len(JarTester._gen_arg_presets))
            selected_preset_dict = JarTester._gen_arg_presets[preset_index] # This is a dict
            selected_preset_cmd_str = JarTester._raw_preset_commands[preset_index] # This is a string
            
            # Calculate wall time limit
            max_cycles_from_preset = selected_preset_dict.get('_max_cycles_for_wall_time')
            if isinstance(max_cycles_from_preset, int) and max_cycles_from_preset > 0:
                estimated_time = (max_cycles_from_preset * BASE_WALL_TIME_PER_CYCLE) + BASE_FIXED_OVERHEAD_TIME
                round_wall_time_limit = max(MIN_WALL_TIME_LIMIT, estimated_time)
                debug_print(f"Round {round_num}: Using {max_cycles_from_preset} cycles for wall time. Estimated: {estimated_time:.1f}s. Actual limit: {round_wall_time_limit:.1f}s.")
            else:
                round_wall_time_limit = DEFAULT_ESTIMATED_WALL_TIME # Use default if no/invalid max_cycles
                debug_print(f"Round {round_num}: --max_cycles not in preset or invalid. Using default wall limit: {round_wall_time_limit:.1f}s (min enforced: {MIN_WALL_TIME_LIMIT:.1f}s).")
                round_wall_time_limit = max(MIN_WALL_TIME_LIMIT, round_wall_time_limit)


            driver_args_list_from_preset = JarTester._preset_dict_to_arg_list(selected_preset_dict)
            current_seed = int(time.time() * 1000) + round_num
            driver_args_list_with_seed = driver_args_list_from_preset + ["--seed", str(current_seed)]
            full_driver_args_str_with_seed = f"{selected_preset_cmd_str} --seed {current_seed}"
            debug_print(f"Round {round_num}: Driver Args: {full_driver_args_str_with_seed}, Final Wall Limit: {round_wall_time_limit:.2f}s")

            if JarTester._interrupted: return None

            results_this_round = []
            max_workers_per_round = min(len(JarTester._jar_files), (os.cpu_count() or 4) + 1)
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers_per_round, thread_name_prefix=f'DriverExec_R{round_num}') as executor:
                if JarTester._interrupted: return None
                future_to_jar = {
                    executor.submit(JarTester._run_single_driver_instance, jar_file, list(driver_args_list_with_seed), round_wall_time_limit, round_num, current_seed): jar_file
                    for jar_file in JarTester._jar_files
                }
                for future in concurrent.futures.as_completed(future_to_jar): # (Rest of _run_one_round logic unchanged from previous driver integration)
                    if JarTester._interrupted: break
                    jar_file = future_to_jar[future]
                    try:
                        result = future.result(); result["round_num"] = round_num; results_this_round.append(result)
                    except Exception as exc:
                        results_this_round.append({
                            "jar_file": os.path.basename(jar_file), "status": "TESTER_ERROR", "error_details": f"Tester thread exc: {exc}",
                            "cpu_time": 0, "wall_time": 0, "driver_stdout": [], "driver_stderr": [f"Tester exc: {exc}", traceback.format_exc()],
                            "seed_used": current_seed, "round_num": round_num })
            if JarTester._interrupted: return None
            # (Error log file generation for failed JARs - unchanged)
            failed_jars_in_round = [r for r in results_this_round if r.get("status") not in ["CORRECT", "INTERRUPTED"]]

            if failed_jars_in_round:
                error_log_filename = f"errors_round_{round_num}_seed_{current_seed}.log"
                error_log_filepath = os.path.abspath(os.path.join(LOG_DIR, error_log_filename))
                debug_print(f"Round {round_num}: Failures detected. Logging errors to separate file: {error_log_filepath}")
                try:
                    os.makedirs(LOG_DIR, exist_ok=True) # 确保日志目录存在
                    with open(error_log_filepath, "w", encoding="utf-8", errors='replace') as f_err:
                        f_err.write(f"--- Error Log for Test Round {round_num} ---\n")
                        f_err.write(f"Seed Used: {current_seed}\n")
                        f_err.write(f"Driver Args (Preset + Seed): {full_driver_args_str_with_seed}\n")
                        f_err.write(f"Wall Time Limit Applied: {round_wall_time_limit:.1f}s\n")
                        f_err.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f_err.write("-" * 40 + "\n\n")

                        for r_fail in failed_jars_in_round:
                            jar_name = r_fail.get("jar_file", "UnknownJAR")
                            status = r_fail.get("status", "UNKNOWN")
                            f_err.write(f"--- Failing JAR: {jar_name} ---\n")
                            f_err.write(f"Status: {status}\n")
                            f_err.write(f"Error Details: {r_fail.get('error_details', '')}\n")
                            f_err.write(f"Driver SUT Input Log Path: {r_fail.get('driver_input_log_path', '<Not Available>')}\n")
                            f_err.write(f"Driver SUT Output Log Path: {r_fail.get('driver_sut_output_log_path', '<Not Available>')}\n")

                            f_err.write("--- Driver Stdout (JSON if any) ---\n")
                            driver_stdout_content = "".join(r_fail.get('driver_stdout', ['<No stdout captured from driver>']))
                            f_err.write(driver_stdout_content.strip() + "\n")
                            f_err.write("--- End Driver Stdout ---\n\n")

                            f_err.write("--- Driver Stderr ---\n")
                            driver_stderr_content = "".join(r_fail.get('driver_stderr', ['<No stderr captured from driver>']))
                            MAX_ERR_LOG_LINES = 200 # 限制stderr的行数，避免日志过大
                            stderr_lines = driver_stderr_content.strip().splitlines()
                            for i, err_line in enumerate(stderr_lines):
                                if i < MAX_ERR_LOG_LINES:
                                    f_err.write(f"  {err_line.strip()}\n")
                                elif i == MAX_ERR_LOG_LINES:
                                    f_err.write(f"  ... (driver stderr truncated after {MAX_ERR_LOG_LINES} lines)\n")
                                    break
                            if not stderr_lines:
                                f_err.write("  <No stderr content>\n")
                            elif len(stderr_lines) <= MAX_ERR_LOG_LINES:
                                f_err.write("  <End of Driver Stderr>\n")
                            f_err.write("--- End Driver Stderr ---\n\n")
                            f_err.write("-" * 20 + "\n\n")
                    
                    print(f"INFO [{thread_name}] Round {round_num}: Errors occurred. Details saved to {error_log_filepath}")

                except Exception as e_err_log:
                    print(f"ERROR [{thread_name}] Round {round_num}: Failed to write separate error log file {error_log_filepath}: {e_err_log}", file=sys.stderr)
            # (Cleanup logic - unchanged)
            if CLEANUP_SUCCESSFUL_ROUNDS and results_this_round: # (cleanup logic as before)
                all_passed_this_round = all(r.get("status") == "CORRECT" for r in results_this_round)
                files_to_remove_in_cleanup = []
                if all_passed_this_round:
                    debug_print(f"Round {round_num}: All JARs passed. Cleaning up all driver SUT log files for this round...")
                    for r_clean in results_this_round:
                        sut_input_log = r_clean.get("driver_input_log_path")
                        sut_output_log = r_clean.get("driver_sut_output_log_path")
                        if sut_input_log and os.path.exists(sut_input_log): files_to_remove_in_cleanup.append(sut_input_log)
                        if sut_output_log and os.path.exists(sut_output_log): files_to_remove_in_cleanup.append(sut_output_log)
                else: # Some JARs failed
                    debug_print(f"Round {round_num}: Some JARs failed. Cleaning up driver SUT log files only for CORRECT runs...")
                    for r_clean in results_this_round:
                        if r_clean.get("status") == "CORRECT":
                            sut_input_log = r_clean.get("driver_input_log_path")
                            sut_output_log = r_clean.get("driver_sut_output_log_path")
                            if sut_input_log and os.path.exists(sut_input_log): files_to_remove_in_cleanup.append(sut_input_log)
                            if sut_output_log and os.path.exists(sut_output_log): files_to_remove_in_cleanup.append(sut_output_log)
                        else: # Failed JAR, keep its logs
                            sut_input_log = r_clean.get("driver_input_log_path")
                            sut_output_log = r_clean.get("driver_sut_output_log_path")
                            if sut_input_log: debug_print(f"  Keeping failed SUT input log: {sut_input_log}")
                            if sut_output_log: debug_print(f"  Keeping failed SUT output log: {sut_output_log}")
                
                for file_path_to_remove in files_to_remove_in_cleanup:
                    try:
                        os.remove(file_path_to_remove)
                        debug_print(f"  Deleted (cleanup): {file_path_to_remove}")
                    except OSError as e_del:
                        print(f"WARNING [{thread_name}] Round {round_num}: Failed to delete temp file {file_path_to_remove}: {e_del}", file=sys.stderr)
            round_results_package = {
                "round_num": round_num, "results": results_this_round, "preset_cmd": full_driver_args_str_with_seed,
                "wall_limit": round_wall_time_limit, "seed_used": current_seed }
            print(f"INFO [{thread_name}]: Finished Test Round {round_num} (Args: {selected_preset_cmd_str})")
            return round_results_package
        except Exception as e_round:
            print(f"\nFATAL ERROR in worker for Round {round_num}: {e_round}", file=sys.stderr); return None

    @staticmethod
    def test():
        global ENABLE_DETAILED_DEBUG, LOG_DIR, TMP_DIR, CLEANUP_SUCCESSFUL_ROUNDS, MIN_WALL_TIME_LIMIT, BASE_WALL_TIME_PER_CYCLE, BASE_FIXED_OVERHEAD_TIME, DEFAULT_ESTIMATED_WALL_TIME
        start_time_main = time.monotonic()
        try:
            config_path = 'config.yml'
            if not os.path.exists(config_path): print(f"ERROR: config.yml not found.", file=sys.stderr); return
            with open(config_path, 'r', encoding='utf-8') as f: config = yaml.safe_load(f)
            if not config: print(f"ERROR: config.yml is empty/invalid.", file=sys.stderr); return
            hw_n = config.get('hw'); jar_base_dir = config.get('jar_base_dir')
            LOG_DIR = config.get('logs_dir', LOG_DIR); TMP_DIR = config.get('tmp_dir', TMP_DIR)
            test_config = config.get('test', {})
            parallel_rounds_config = test_config.get('parallel', DEFAULT_PARALLEL_ROUNDS)
            ENABLE_DETAILED_DEBUG = bool(test_config.get('debug', ENABLE_DETAILED_DEBUG))
            CLEANUP_SUCCESSFUL_ROUNDS = bool(test_config.get('cleanup', CLEANUP_SUCCESSFUL_ROUNDS))
            # Load wall time parameters from config
            MIN_WALL_TIME_LIMIT = float(test_config.get('min_wall_time_limit', MIN_WALL_TIME_LIMIT))
            BASE_WALL_TIME_PER_CYCLE = float(test_config.get('base_wall_time_per_cycle', BASE_WALL_TIME_PER_CYCLE))
            BASE_FIXED_OVERHEAD_TIME = float(test_config.get('base_fixed_overhead_time', BASE_FIXED_OVERHEAD_TIME))
            DEFAULT_ESTIMATED_WALL_TIME = float(test_config.get('default_estimated_wall_time', DEFAULT_ESTIMATED_WALL_TIME))

            if hw_n is None or not jar_base_dir: print("ERROR: 'hw' or 'jar_base_dir' missing.", file=sys.stderr); return
            m = hw_n // 4 + 1; hw_n_str = os.path.join(f"unit_{m}", f"hw_{hw_n}")
            JarTester._jar_dir = jar_base_dir
            JarTester._driver_script_path = os.path.abspath(os.path.join(hw_n_str, "driver.py"))
            presets_yaml_path = os.path.abspath(os.path.join(hw_n_str, "gen_presets.yml"))
            try:
                if not os.path.exists(presets_yaml_path): print(f"ERROR: Presets '{presets_yaml_path}' not found.", file=sys.stderr); return
                with open(presets_yaml_path, 'r') as f: JarTester._loaded_preset_commands = yaml.safe_load(f)
                if not isinstance(JarTester._loaded_preset_commands, list) or not all(isinstance(i, str) for i in JarTester._loaded_preset_commands):
                    print(f"ERROR: Presets file must be a YAML list of strings.", file=sys.stderr); return
            except Exception as e: print(f"ERROR: Loading presets: {e}", file=sys.stderr); return
            os.makedirs(LOG_DIR, exist_ok=True); os.makedirs(TMP_DIR, exist_ok=True)
            JarTester._log_file_path = os.path.abspath(os.path.join(LOG_DIR, f"{time.strftime('%Y%m%d-%H%M%S')}_driver_run.log"))
            print(f"INFO: Target: {hw_n_str}, Logs: {JarTester._log_file_path}")
            print(f"INFO: Wall Time Params: Min={MIN_WALL_TIME_LIMIT:.1f}s, PerCycle={BASE_WALL_TIME_PER_CYCLE:.1f}s, Overhead={BASE_FIXED_OVERHEAD_TIME:.1f}s, DefaultEst={DEFAULT_ESTIMATED_WALL_TIME:.1f}s")

            if not os.path.exists(JarTester._driver_script_path): print(f"ERROR: Driver script not found: {JarTester._driver_script_path}", file=sys.stderr); return
            if not JarTester._find_jar_files(): print("ERROR: No JARs found.", file=sys.stderr); return
            if not JarTester._initialize_presets(): print("ERROR: Failed to init presets.", file=sys.stderr); return
            signal.signal(signal.SIGINT, JarTester._signal_handler)
            if not ENABLE_DETAILED_DEBUG: input("Setup complete. Press Enter to begin testing...")
            # (Main parallel round execution loop - unchanged from previous driver integration)
            active_futures = set()
            with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_rounds_config, thread_name_prefix='RoundRunner') as executor:
                while not JarTester._interrupted:
                    while len(active_futures) < parallel_rounds_config and not JarTester._interrupted:
                        round_num = JarTester._get_next_round_number()
                        active_futures.add(executor.submit(JarTester._run_one_round, round_num))
                    if JarTester._interrupted: break
                    done, active_futures = concurrent.futures.wait(active_futures, return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in done:
                        try:
                            pkg = future.result()
                            if pkg: JarTester._display_and_log_results(pkg["round_num"], pkg["results"], pkg["preset_cmd"], pkg["wall_limit"])
                            if pkg and not JarTester._interrupted: JarTester._update_history(pkg["results"])
                        except Exception as exc: print(f"ERROR processing round future: {exc}")
                if JarTester._interrupted and active_futures:
                    print("\nInterrupt: Waiting for active rounds..."); (done_after, _) = concurrent.futures.wait(active_futures, return_when=concurrent.futures.ALL_COMPLETED)
                    for future in done_after:
                        try:
                            pkg = future.result()
                            if pkg: JarTester._display_and_log_results(pkg["round_num"],pkg["results"],pkg["preset_cmd"],pkg["wall_limit"])
                        except Exception: pass
        except Exception as e: print(f"\nFATAL ERROR in main: {e}", file=sys.stderr); JarTester._interrupted = True
        finally:
            summary = JarTester._print_summary() # (Summary and cleanup info unchanged)
            print(summary)
            if JarTester._log_file_path:
                try:
                     with JarTester._log_lock: open(JarTester._log_file_path, "a").write("\n\n" + "="*20 + " FINAL SUMMARY " + "="*20 + "\n" + summary + "\n")
                except Exception: pass
            end_time_main = time.monotonic()
            print(f"\nTotal execution time: {end_time_main - start_time_main:.2f} seconds.")

# if __name__ == "__main__":
#     # Example config.yml:
#     # hw: 13
#     # jar_base_dir: "path/to/jars_hw13"
#     # test:
#     #   parallel: 4
#     #   debug: false
#     #   cleanup: true
#     #   min_wall_time_limit: 10.0 # Floor for wall time
#     #   base_wall_time_per_cycle: 2.5 # Time per --max_cycles
#     #   base_fixed_overhead_time: 5.0 # Fixed driver overhead
#     #   default_estimated_wall_time: 60.0 # If --max_cycles not in preset
#     JarTester.test()