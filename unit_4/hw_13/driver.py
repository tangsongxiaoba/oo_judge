# driver.py
import subprocess
import threading
import queue
import time
import json
import random
from datetime import date, timedelta
import argparse

from state import LibrarySystem
from gen import gen_open_close_cycle_data
from checker import check_cycle

# --- Constants ---
DEFAULT_MAX_CYCLES = 10
DEFAULT_MAX_TOTAL_COMMANDS = 200
# JAR_TIMEOUT_SECONDS = 5 # This was not directly used as a Popen timeout.
                          # Process termination timeouts are hardcoded later.
INITIAL_BOOK_TYPES = 5
INITIAL_BOOKS_MIN_COPIES = 1
INITIAL_BOOKS_MAX_COPIES = 10

# Configurable SUT output collection timeout per cycle
DEFAULT_CYCLE_TIMEOUT_SECONDS = 2.0 # Renamed and made default for the new arg
# Poll interval for checking SUT output queue (keep small for responsiveness)
SUT_OUTPUT_COLLECTION_POLL_INTERVAL = 0.05 # Usually kept fixed and small

DEFAULT_BORROW_WEIGHT = 3
DEFAULT_ORDER_WEIGHT = 2
DEFAULT_QUERY_WEIGHT = 3
DEFAULT_FAILED_ORDER_WEIGHT = 0
DEFAULT_NEW_STUDENT_RATIO = 0.2
DEFAULT_MIN_DAYS_TO_SKIP = 0
DEFAULT_MAX_DAYS_TO_SKIP = 1
DEFAULT_MIN_REQUESTS_PER_DAY = 1
DEFAULT_MAX_REQUESTS_PER_DAY = 5

DEFAULT_B_BOOK_PRIORITY = 0.5
DEFAULT_C_BOOK_PRIORITY = 0.5
DEFAULT_STUDENT_RETURN_PROPENSITY = 0.7
DEFAULT_STUDENT_PICK_PROPENSITY = 0.7

# --- I/O Thread for Java Process ---
def enqueue_output(out, q):
    try:
        for line in iter(out.readline, b''):
            q.put(line.decode('utf-8').strip())
    except ValueError: pass
    except Exception: pass
    finally:
        if hasattr(out, 'close') and not out.closed:
            try: out.close()
            except Exception: pass

# --- Main Driver Logic ---
def run_driver(
    jar_path: str,
    max_cycles: int = DEFAULT_MAX_CYCLES,
    max_total_commands: int = DEFAULT_MAX_TOTAL_COMMANDS,
    min_days_to_skip: int = DEFAULT_MIN_DAYS_TO_SKIP,
    max_days_to_skip: int = DEFAULT_MAX_DAYS_TO_SKIP,
    min_requests_per_day: int = DEFAULT_MIN_REQUESTS_PER_DAY,
    max_requests_per_day: int = DEFAULT_MAX_REQUESTS_PER_DAY,
    borrow_weight: int = DEFAULT_BORROW_WEIGHT,
    order_weight: int = DEFAULT_ORDER_WEIGHT,
    query_weight: int = DEFAULT_QUERY_WEIGHT,
    failed_order_weight: int = DEFAULT_FAILED_ORDER_WEIGHT,
    new_student_ratio: float = DEFAULT_NEW_STUDENT_RATIO,
    initial_book_types_count: int = INITIAL_BOOK_TYPES,
    initial_min_copies: int = INITIAL_BOOKS_MIN_COPIES,
    initial_max_copies: int = INITIAL_BOOKS_MAX_COPIES,
    start_year: int = 2025,
    start_month: int = 1,
    start_day: int = 1,
    b_book_priority: float = DEFAULT_B_BOOK_PRIORITY,
    c_book_priority: float = DEFAULT_C_BOOK_PRIORITY,
    student_return_propensity: float = DEFAULT_STUDENT_RETURN_PROPENSITY,
    student_pick_propensity: float = DEFAULT_STUDENT_PICK_PROPENSITY,
    sut_prints_user_ops_immediately: bool = True, # This is an assumption, not a timeout
    seed: int = None,
    verbose: bool = False,
    input_log_file_path_arg: str = None,
    output_log_file_path_arg: str = None,
    # --- New parameter for SUT cycle output collection timeout ---
    cycle_timeout_seconds: float = DEFAULT_CYCLE_TIMEOUT_SECONDS
) -> tuple[bool, str]:

    final_error_message = ""
    overall_success = True
    process = None
    stdout_thread = None
    stderr_thread = None
    stdout_q = None
    stderr_q = None

    _stdin_log_fh = None
    _stdout_log_fh = None

    try:
        final_input_log_path_to_use = None
        if input_log_file_path_arg:
            final_input_log_path_to_use = input_log_file_path_arg
        elif not verbose:
            final_input_log_path_to_use = "stdin.txt"

        final_output_log_path_to_use = None
        if output_log_file_path_arg:
            final_output_log_path_to_use = output_log_file_path_arg
        elif not verbose:
            final_output_log_path_to_use = "stdout.txt"

        if final_input_log_path_to_use:
            try:
                _stdin_log_fh = open(final_input_log_path_to_use, 'w', encoding='utf-8')
                if verbose: print(f"Logging SUT input to: {final_input_log_path_to_use}")
            except IOError as e:
                if verbose: print(f"Warning: Could not open input log file '{final_input_log_path_to_use}': {e}. Input logging disabled.")
        
        if final_output_log_path_to_use:
            try:
                _stdout_log_fh = open(final_output_log_path_to_use, 'w', encoding='utf-8')
                if verbose: print(f"Logging SUT output to: {final_output_log_path_to_use}")
            except IOError as e:
                if verbose: print(f"Warning: Could not open output log file '{final_output_log_path_to_use}': {e}. Output logging disabled.")

        if seed is not None:
            random.seed(seed)

        python_library_model = LibrarySystem()

        if verbose: print("--- Generating Initial Book Data ---")
        initial_book_commands_str_list = []
        isbn_set = set()
        book_types_available = ['A', 'B', 'C']
        initial_book_commands_str_list.append(str(initial_book_types_count))
        generated_types_count = 0
        attempts = 0
        max_attempts = initial_book_types_count * 5
        while generated_types_count < initial_book_types_count and attempts < max_attempts:
            book_type_choice = random.choice(book_types_available)
            seq_num = f"{random.randint(0, 9999):04d}"
            isbn = f"{book_type_choice}-{seq_num}"
            if isbn in isbn_set:
                attempts +=1; continue
            isbn_set.add(isbn)
            num_copies = random.randint(initial_min_copies, initial_max_copies)
            initial_book_commands_str_list.append(f"{isbn} {num_copies}")
            generated_types_count += 1; attempts +=1
        
        if generated_types_count < initial_book_types_count and initial_book_types_count > 0:
            msg = f"Warning: Could only generate {generated_types_count} unique book types out of {initial_book_types_count} requested."
            if verbose: print(msg)
            initial_book_commands_str_list[0] = str(generated_types_count)
            if generated_types_count == 0:
                final_error_message = "Error: No initial books generated. Exiting."
                if verbose: print(final_error_message)
                overall_success = False

        if overall_success:
            python_library_model.initialize_books(initial_book_commands_str_list[1:])
            if verbose:
                print("Python model initialized with books:")
                for isbn_item, book_ids in python_library_model.books_on_shelf_by_isbn.items():
                    print(f"  {isbn_item}: {len(book_ids)} copies ({book_ids[:3]}...)")

            if verbose: print(f"\n--- Starting Java Process: {jar_path} ---")
            try:
                process = subprocess.Popen(['java', '-jar', jar_path],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except FileNotFoundError:
                final_error_message = f"Error: JAR file not found at '{jar_path}'. Please check the path."
                if verbose: print(final_error_message)
                overall_success = False
            except Exception as e:
                final_error_message = f"Error starting JAR process: {e}"
                if verbose: print(final_error_message)
                overall_success = False

        if overall_success and process:
            stdout_q = queue.Queue(); stderr_q = queue.Queue()
            stdout_thread = threading.Thread(target=enqueue_output, args=(process.stdout, stdout_q), name="SUT_StdoutThread", daemon=True)
            stderr_thread = threading.Thread(target=enqueue_output, args=(process.stderr, stderr_q), name="SUT_StderrThread", daemon=True)
            stdout_thread.start(); stderr_thread.start()

            for line in initial_book_commands_str_list:
                if verbose: print(f"DRIVER -> SUT (Initial): {line}")
                try:
                    if process.stdin.closed:
                        final_error_message = "Error: SUT stdin closed unexpectedly during initial data send."
                        if verbose: print(final_error_message)
                        overall_success = False; break
                    
                    line_with_nl = line + '\n'
                    process.stdin.write(line_with_nl.encode('utf-8'))
                    if _stdin_log_fh: _stdin_log_fh.write(line_with_nl)
                    process.stdin.flush()
                except (IOError, BrokenPipeError) as e:
                    final_error_message = f"Error writing initial data to JAR stdin: {e}. SUT likely crashed."
                    if verbose: print(final_error_message)
                    overall_success = False; break
                # time.sleep(0.01) # Small fixed delay, can be removed if SUT is fast enough or if cycle_timeout is the main controller

        if overall_success and process:
            current_cycle_num = 0
            total_commands_processed_in_driver = 0
            next_cycle_start_date_obj = date(start_year, start_month, start_day)

            if verbose: print("\n--- Starting Interaction Loop (Batch Mode) ---")
            while current_cycle_num < max_cycles and \
                  total_commands_processed_in_driver < max_total_commands and \
                  overall_success:
                current_cycle_num += 1
                if verbose: print(f"\n--- Cycle {current_cycle_num}/{max_cycles} ---")

                cycle_commands_to_send, next_date_for_next_cycle = gen_open_close_cycle_data(
                    python_library_model, next_cycle_start_date_obj,
                    min_days_to_skip, max_days_to_skip,
                    min_requests_per_day, max_requests_per_day,
                    borrow_weight, order_weight, query_weight, failed_order_weight, new_student_ratio,
                    b_book_priority=b_book_priority,
                    c_book_priority=c_book_priority,
                    student_return_propensity=student_return_propensity,
                    student_pick_propensity=student_pick_propensity
                )

                if not cycle_commands_to_send:
                    if verbose: print("Generator produced no commands for this cycle. Ending early.")
                    break
                next_cycle_start_date_obj = next_date_for_next_cycle

                if verbose: print(f"DRIVER: Sending {len(cycle_commands_to_send)} commands for this cycle to SUT.")
                for command_str in cycle_commands_to_send:
                    if total_commands_processed_in_driver >= max_total_commands:
                        if verbose: print("Max total commands reached. Ending.")
                        break
                    total_commands_processed_in_driver += 1
                    if verbose: print(f"DRIVER -> SUT: {command_str}")
                    try:
                        if process.stdin.closed:
                            final_error_message = f"Error: SUT stdin closed before sending command '{command_str}'."
                            if verbose: print(final_error_message)
                            overall_success = False; break
                        
                        command_with_nl = command_str + '\n'
                        process.stdin.write(command_with_nl.encode('utf-8'))
                        if _stdin_log_fh: _stdin_log_fh.write(command_with_nl)
                        process.stdin.flush()
                    except (IOError, BrokenPipeError) as e:
                        final_error_message = f"Error writing command '{command_str}' to JAR stdin: {e}. SUT likely crashed."
                        if verbose: print(final_error_message)
                        overall_success = False; break
                    # time.sleep(0.01) # Small fixed delay between commands. If SUT is slow, this might sum up.
                                     # Usually, the SUT reading speed or the cycle_timeout dominates.

                if not overall_success or total_commands_processed_in_driver >= max_total_commands : break

                sut_all_output_for_this_cycle = []
                if verbose: print(f"DRIVER: Collecting SUT output for cycle {current_cycle_num} (timeout: {cycle_timeout_seconds}s)...")
                collection_start_time = time.monotonic()
                # Use the new cycle_timeout_seconds parameter here
                while time.monotonic() - collection_start_time < cycle_timeout_seconds:
                    try:
                        if stdout_q is None:
                            final_error_message = "Internal Error: stdout_q not initialized for output collection."
                            overall_success = False; break
                        # Poll interval remains fixed for responsiveness within the larger timeout window
                        line = stdout_q.get(timeout=SUT_OUTPUT_COLLECTION_POLL_INTERVAL)
                        sut_all_output_for_this_cycle.append(line)
                        if _stdout_log_fh: _stdout_log_fh.write(line + '\n')
                        if verbose: print(f"SUT -> DRIVER (Cycle Output): {line}")
                        collection_start_time = time.monotonic() # Reset timeout on new output, effectively making it an inactivity timeout
                    except queue.Empty:
                        if process.poll() is not None:
                            final_error_message = "SUT process terminated during output collection."
                            if verbose: print(final_error_message)
                            overall_success = False; break
                        pass
                if not overall_success: break
                
                # Check if timeout occurred without any output for the entire duration
                # This check is implicitly handled: if the loop finishes due to timeout and sut_all_output_for_this_cycle is empty
                # or deemed insufficient by the checker, it will be a failure.
                # The current logic resets collection_start_time on *any* output, so it's more of an
                # "inactivity timeout for the whole cycle's output block" rather than a strict total time.
                # If strict total time is needed, `collection_start_time` should not be reset.
                # For now, keeping the reset behavior, as it allows SUT to print lines spread out over `cycle_timeout_seconds`.

                if verbose: print(f"DRIVER: Collected {len(sut_all_output_for_this_cycle)} lines from SUT for cycle {current_cycle_num}.")

                cycle_check_result = check_cycle(
                    cycle_commands_to_send, sut_all_output_for_this_cycle, python_library_model
                )

                if not cycle_check_result["is_legal"]:
                    final_error_message = f"Cycle Validation FAILED (Cycle {current_cycle_num}): {cycle_check_result['error_message']}"
                    if cycle_check_result.get("first_failing_command"):
                        final_error_message += f" | First failing command context: {cycle_check_result['first_failing_command']}"
                    if verbose:
                        print(f"Cycle Validation FAILED (Cycle {current_cycle_num}):")
                        print(f"  Reason: {cycle_check_result['error_message']}")
                        if cycle_check_result.get("first_failing_command"):
                            print(f"  First failing command context: {cycle_check_result['first_failing_command']}")
                    overall_success = False; break
                else:
                    if verbose: print(f"Cycle {current_cycle_num} OK.")
                
                sut_stderr_output_this_cycle = []
                if stderr_q:
                    while not stderr_q.empty():
                        try:
                            err_line = stderr_q.get_nowait()
                            sut_stderr_output_this_cycle.append(err_line)
                            if verbose: print(f"SUT STDERR (End of Cycle {current_cycle_num}): {err_line}")
                        except queue.Empty: break
            
            if verbose: print("\n--- Interaction Loop Finished ---")

        sut_exit_code = process.poll() if process else -1
        if process and sut_exit_code is None:
            if verbose: print("Terminating SUT process...")
            try:
                if process.stdin and not process.stdin.closed: process.stdin.close()
            except Exception as e_close:
                if verbose: print(f"Note: Error closing SUT stdin: {e_close}")
            process.terminate()
            try:
                sut_exit_code = process.wait(timeout=1.0) # Fixed termination timeout
                if verbose: print(f"SUT terminated with exit code: {sut_exit_code}")
            except subprocess.TimeoutExpired:
                if verbose: print("SUT did not terminate gracefully, killing.")
                process.kill(); sut_exit_code = process.wait(timeout=0.5) # Fixed kill timeout
                if verbose: print(f"SUT killed, exit code: {sut_exit_code}")
            except Exception as e_term:
                 if verbose: print(f"Exception during SUT termination: {e_term}")
        
        if verbose and (stdout_q or stderr_q):
            def drain_queue(q, q_name):
                if q is None: return
                count = 0
                while not q.empty():
                    try: print(f"SUT {q_name} (remaining): {q.get_nowait()}"); count+=1
                    except queue.Empty: break
                if count > 0: print(f"Drained {count} lines from {q_name}.")
            drain_queue(stdout_q, "STDOUT")
            drain_queue(stderr_q, "STDERR")

        if stdout_thread and stdout_thread.is_alive(): stdout_thread.join(timeout=0.5)
        if stderr_thread and stderr_thread.is_alive(): stderr_thread.join(timeout=0.5)

    finally:
        if _stdin_log_fh:
            try: _stdin_log_fh.close()
            except Exception as e:
                if verbose: print(f"Note: Error closing SUT input log file: {e}")
        if _stdout_log_fh:
            try: _stdout_log_fh.close()
            except Exception as e:
                if verbose: print(f"Note: Error closing SUT output log file: {e}")

    if verbose:
        if overall_success:
            print("\n+++ Driver finished (Batch Mode): All checked cycles were valid. +++")
        else:
            print("\n--- Driver finished (Batch Mode): Errors encountered. ---")
            if not final_error_message:
                 final_error_message = "An unspecified error occurred during the run."

    return overall_success, final_error_message


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run interactive test driver for LibrarySystem (Batch Mode).")
    parser.add_argument("jar_path", help="Path to the student's JAR file.")
    parser.add_argument("--max_cycles", type=int, default=DEFAULT_MAX_CYCLES)
    parser.add_argument("--max_total_commands", type=int, default=DEFAULT_MAX_TOTAL_COMMANDS)
    parser.add_argument("--min_skip", type=int, default=DEFAULT_MIN_DAYS_TO_SKIP, help="Min days to skip between cycles.")
    parser.add_argument("--max_skip", type=int, default=DEFAULT_MAX_DAYS_TO_SKIP, help="Max days to skip between cycles.")
    parser.add_argument("--min_req", type=int, default=DEFAULT_MIN_REQUESTS_PER_DAY, help="Min requests per day in a cycle.")
    parser.add_argument("--max_req", type=int, default=DEFAULT_MAX_REQUESTS_PER_DAY, help="Max requests per day in a cycle.")
    parser.add_argument("--b_weight", type=int, default=DEFAULT_BORROW_WEIGHT, help="Weight for generating borrow commands.")
    parser.add_argument("--o_weight", type=int, default=DEFAULT_ORDER_WEIGHT, help="Weight for generating (successful) order commands.")
    parser.add_argument("--q_weight", type=int, default=DEFAULT_QUERY_WEIGHT, help="Weight for generating query commands.")
    parser.add_argument("--failed_o_weight", type=int, default=DEFAULT_FAILED_ORDER_WEIGHT, help="Weight for generating (expected to fail) order commands.")
    parser.add_argument("--new_s_ratio", type=float, default=DEFAULT_NEW_STUDENT_RATIO, help="Ratio of new students vs existing for command generation.")
    parser.add_argument("--init_types", type=int, default=INITIAL_BOOK_TYPES, help="Number of unique book ISBNs to initialize.")
    parser.add_argument("--init_min_cp", type=int, default=INITIAL_BOOKS_MIN_COPIES, help="Min copies per initial book ISBN.")
    parser.add_argument("--init_max_cp", type=int, default=INITIAL_BOOKS_MAX_COPIES, help="Max copies per initial book ISBN.")
    parser.add_argument("--start_year", type=int, default=2025)
    parser.add_argument("--start_month", type=int, default=1)
    parser.add_argument("--start_day", type=int, default=1)
    parser.add_argument("--b_prio", type=float, default=DEFAULT_B_BOOK_PRIORITY,
                        help=f"Priority for selecting B-type books (0.0-1.0 suggested, default: {DEFAULT_B_BOOK_PRIORITY}).")
    parser.add_argument("--c_prio", type=float, default=DEFAULT_C_BOOK_PRIORITY,
                        help=f"Priority for selecting C-type books (0.0-1.0 suggested, default: {DEFAULT_C_BOOK_PRIORITY}).")
    parser.add_argument("--ret_prop", type=float, default=DEFAULT_STUDENT_RETURN_PROPENSITY,
                        help=f"Propensity for student return (0.0-1.0, default: {DEFAULT_STUDENT_RETURN_PROPENSITY}).")
    parser.add_argument("--pick_prop", type=float, default=DEFAULT_STUDENT_PICK_PROPENSITY,
                        help=f"Propensity for student pick up (0.0-1.0, default: {DEFAULT_STUDENT_PICK_PROPENSITY}).")
    
    # --- New argument for SUT cycle output collection timeout ---
    parser.add_argument("--cycle_timeout", type=float, default=DEFAULT_CYCLE_TIMEOUT_SECONDS,
                        help=f"Timeout in seconds for SUT to produce all output for one cycle (default: {DEFAULT_CYCLE_TIMEOUT_SECONDS}).")

    parser.add_argument("--sut_immediate_print", action=argparse.BooleanOptionalAction, default=True, help="Assumption about SUT's output timing.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output. If not set, only a final JSON result is printed.")
    parser.add_argument("-i", "--input_log_file", type=str, default=None,
                        help="Path to log SUT input. Defaults to stdin.txt if not verbose and not specified.")
    parser.add_argument("-o", "--output_log_file", type=str, default=None,
                        help="Path to log SUT output. Defaults to stdout.txt if not verbose and not specified.")
    args = parser.parse_args()

    run_successful, error_msg_details = run_driver(
        jar_path=args.jar_path,
        max_cycles=args.max_cycles,
        max_total_commands=args.max_total_commands,
        min_days_to_skip=args.min_skip,
        max_days_to_skip=args.max_skip,
        min_requests_per_day=args.min_req,
        max_requests_per_day=args.max_req,
        borrow_weight=args.b_weight,
        order_weight=args.o_weight,
        query_weight=args.q_weight,
        failed_order_weight=args.failed_o_weight,
        new_student_ratio=args.new_s_ratio,
        initial_book_types_count=args.init_types,
        initial_min_copies=args.init_min_cp,
        initial_max_copies=args.init_max_cp,
        start_year=args.start_year,
        start_month=args.start_month,
        start_day=args.start_day,
        b_book_priority=args.b_prio,
        c_book_priority=args.c_prio,
        student_return_propensity=args.ret_prop,
        student_pick_propensity=args.pick_prop,
        sut_prints_user_ops_immediately=args.sut_immediate_print,
        seed=args.seed,
        verbose=args.verbose,
        input_log_file_path_arg=args.input_log_file,
        output_log_file_path_arg=args.output_log_file,
        # --- Pass the new timeout argument ---
        cycle_timeout_seconds=args.cycle_timeout
    )

    if not args.verbose:
        result_json = {}
        if run_successful:
            result_json["status"] = "success"
        else:
            result_json["status"] = "failure"
            result_json["reason"] = error_msg_details if error_msg_details else "Unknown error"
        print(json.dumps(result_json))
        exit(0 if run_successful else 1)
    else:
        if run_successful:
            print("Driver run successful (verbose).")
            exit(0)
        else:
            print(f"Driver run failed (verbose): {error_msg_details}")
            exit(1)