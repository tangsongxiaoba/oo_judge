# driver.py
import subprocess
import sys
import threading
import queue # 标准库的 queue
import time
import json
import random
from datetime import date, timedelta
import argparse
from typing import Optional, Tuple, List, Any

try:
    from state import LibrarySystem
    from gen import generate_command_cycle
    from checker import check_cycle, parse_sut_query_header_line
except ImportError as e:
    print(f"Critical Driver Error: Could not import required modules (state, gen, checker): {e}")
    try:
        print(json.dumps({"status": "failure", "reason": f"Critical import error: {e}"}))
    except Exception:
        pass
    sys.exit(1)

# --- Constants ---
DEFAULT_MAX_CYCLES = 5
DEFAULT_MAX_TOTAL_COMMANDS = 200
INITIAL_BOOK_TYPES_COUNT = 5
INITIAL_BOOKS_MIN_COPIES = 1
INITIAL_BOOKS_MAX_COPIES = 10

SUT_OUTPUT_COLLECTION_POLL_INTERVAL = 0.05
DEFAULT_MAX_WAIT_PER_LINE_SUT_OUTPUT = 2.0

DEFAULT_MIN_SKIP_DAYS_POST_CLOSE_FOR_GEN = 0
DEFAULT_MAX_SKIP_DAYS_POST_CLOSE_FOR_GEN = 1
DEFAULT_MIN_REQUESTS_PER_DAY_FOR_GEN = 1
DEFAULT_MAX_REQUESTS_PER_DAY_FOR_GEN = 5

DEFAULT_INITIAL_CLOSE_PROBABILITY = 0.1
DEFAULT_CLOSE_PROBABILITY_INCREMENT = 0.15
DEFAULT_MAX_CLOSE_PROBABILITY = 0.9

# --- UPDATED/NEW PARAMETER DEFAULTS ---
DEFAULT_BORROW_WEIGHT = 3
DEFAULT_ORDER_WEIGHT = 2
DEFAULT_PICK_WEIGHT = 2
DEFAULT_READ_WEIGHT = 2
DEFAULT_RESTORE_WEIGHT = 1
DEFAULT_TRACE_QUERY_WEIGHT = 2
DEFAULT_CREDIT_QUERY_WEIGHT = 1
DEFAULT_FAILED_BORROW_WEIGHT = 1
DEFAULT_FAILED_ORDER_WEIGHT = 1
# --- END UPDATED/NEW DEFAULTS ---

DEFAULT_NEW_STUDENT_RATIO = 0.2
DEFAULT_B_BOOK_PRIORITY = 0.4
DEFAULT_C_BOOK_PRIORITY = 0.4
DEFAULT_A_BOOK_READ_PRIORITY = 0.2
DEFAULT_STUDENT_RETURN_PROPENSITY = 0.7
DEFAULT_STUDENT_PICK_PROPENSITY = 0.7
DEFAULT_STUDENT_RESTORE_PROPENSITY = 0.6


# --- I/O Thread for Java Process (unchanged) ---
def enqueue_output(out, q):
    try:
        for line in iter(out.readline, b''):
            q.put(line.decode('utf-8').strip())
    except (ValueError, Exception):
        pass
    finally:
        if hasattr(out, 'close') and not out.closed:
            try: out.close()
            except Exception: pass

def _format_date_cmd(date_obj: date) -> str:
    return date_obj.strftime("%Y-%m-%d")

# --- Smart Output Collection (unchanged) ---
class OutputCollectionContext:
    USER_OPERATION_SINGLE_LINE = 1
    USER_OPERATION_QUERY = 2
    TIDY_OPERATION_OPEN_OR_CLOSE = 3

def _collect_sut_output_smart(sut_stdout_q, sut_process, context, poll_interval, max_wait, verbose, log_fh):
    # This function's implementation remains unchanged.
    collected_lines: List[str] = []
    expected_lines_to_collect = 0
    lines_collected_this_block = 0
    
    if context == OutputCollectionContext.TIDY_OPERATION_OPEN_OR_CLOSE:
        start_time = time.monotonic()
        while True:
            if sut_process.poll() is not None: return collected_lines, False
            try:
                first_line = sut_stdout_q.get(timeout=poll_interval)
                collected_lines.append(first_line)
                if log_fh: log_fh.write(first_line + '\n'); log_fh.flush()
                if verbose: print(f"SUT -> DRIVER (Tidy Count Line): {first_line}")
                lines_collected_this_block += 1
                break
            except queue.Empty:
                if time.monotonic() - start_time > max_wait: return collected_lines, False
        try:
            expected_lines_to_collect = 1 + int(first_line)
        except (ValueError, TypeError): return collected_lines, False

    elif context == OutputCollectionContext.USER_OPERATION_QUERY:
        start_time = time.monotonic()
        while True:
            if sut_process.poll() is not None: return collected_lines, False
            try:
                header_line = sut_stdout_q.get(timeout=poll_interval)
                collected_lines.append(header_line)
                if log_fh: log_fh.write(header_line + '\n'); log_fh.flush()
                if verbose: print(f"SUT -> DRIVER (Query Header): {header_line}")
                lines_collected_this_block += 1
                break
            except queue.Empty:
                if time.monotonic() - start_time > max_wait: return collected_lines, False
        try:
            parsed = parse_sut_query_header_line(header_line)
            if not parsed: return collected_lines, False
            _, _, num_traces = parsed
            expected_lines_to_collect = 1 + num_traces
        except (ValueError, TypeError): return collected_lines, False

    elif context == OutputCollectionContext.USER_OPERATION_SINGLE_LINE:
        expected_lines_to_collect = 1
    
    else: return collected_lines, False

    remaining_lines = expected_lines_to_collect - lines_collected_this_block
    for _ in range(remaining_lines):
        start_time = time.monotonic()
        while True:
            if sut_process.poll() is not None: return collected_lines, False
            try:
                line = sut_stdout_q.get(timeout=poll_interval)
                collected_lines.append(line)
                if log_fh: log_fh.write(line + '\n'); log_fh.flush()
                if verbose: print(f"SUT -> DRIVER (Line {len(collected_lines)}): {line}")
                lines_collected_this_block += 1
                break
            except queue.Empty:
                if time.monotonic() - start_time > max_wait: return collected_lines, False
    
    return collected_lines, lines_collected_this_block == expected_lines_to_collect


# --- Main Driver Logic ---
def run_driver(
    jar_path: str,
    max_cycles: int, max_total_commands: int,
    min_skip_days_post_close: int, max_skip_days_post_close: int,
    min_requests_per_day: int, max_requests_per_day: int,
    initial_close_probability: float, close_probability_increment: float, max_close_probability: float,
    borrow_weight: int, order_weight: int, pick_weight: int,
    read_weight: int, restore_weight: int,
    trace_query_weight: int,
    credit_query_weight: int,
    failed_borrow_weight: int,
    failed_order_weight: int,
    new_student_ratio: float, student_return_propensity: float, student_pick_propensity: float, student_restore_propensity: float,
    b_book_priority: float, c_book_priority: float, a_book_read_priority: float,
    initial_book_types_count: int, initial_min_copies: int, initial_max_copies: int,
    start_year: int, start_month: int, start_day: int,
    seed: Optional[int], verbose: bool,
    input_log_file_path_arg: Optional[str], output_log_file_path_arg: Optional[str],
    max_wait_per_line_sut_output: float
) -> Tuple[bool, str]:

    final_error_message = ""
    overall_success = True
    process: Optional[subprocess.Popen] = None
    _stdin_log_fh, _stdout_log_fh = None, None

    try:
        if input_log_file_path_arg: _stdin_log_fh = open(input_log_file_path_arg, 'w', encoding='utf-8')
        if output_log_file_path_arg: _stdout_log_fh = open(output_log_file_path_arg, 'w', encoding='utf-8')
        
        if seed is not None:
            random.seed(seed)

        python_library_model = LibrarySystem()

        # Initial book generation remains unchanged
        initial_book_commands_str_list = []
        # ... (book generation logic)
        num_books = max(0, initial_book_types_count)
        initial_book_commands_str_list.append(str(num_books))
        isbns = set()
        for _ in range(num_books * 10):
            if len(isbns) >= num_books: break
            isbn = f"{random.choice(['A','B','C'])}-{random.randint(0,9999):04d}"
            if isbn not in isbns:
                isbns.add(isbn)
                copies = random.randint(initial_min_copies, initial_max_copies)
                initial_book_commands_str_list.append(f"{isbn} {copies}")
        initial_book_commands_str_list[0] = str(len(isbns))
        # ...
        if len(isbns) > 0:
            python_library_model.initialize_books(initial_book_commands_str_list[1:])
        
        try:
            process = subprocess.Popen(['java', '-jar', jar_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=False)
        except Exception as e:
            final_error_message = f"Error starting JAR process: {e}"; overall_success = False
        
        if overall_success and process:
            stdout_q = queue.Queue(); stderr_q = queue.Queue()
            stdout_thread = threading.Thread(target=enqueue_output, args=(process.stdout, stdout_q), daemon=True); stdout_thread.start()
            stderr_thread = threading.Thread(target=enqueue_output, args=(process.stderr, stderr_q), daemon=True); stderr_thread.start()

            for line in initial_book_commands_str_list:
                try:
                    if process.stdin and not process.stdin.closed:
                        line_with_nl = line + '\n'
                        process.stdin.write(line_with_nl.encode('utf-8'))
                        if _stdin_log_fh: _stdin_log_fh.write(line_with_nl); _stdin_log_fh.flush()
                        process.stdin.flush()
                    else: raise IOError("SUT stdin closed")
                except (IOError, BrokenPipeError) as e:
                    final_error_message = f"Error writing initial data to SUT: {e}."; overall_success = False; break
            if not overall_success: process = None
        
        if overall_success and process:
            current_sim_date = date(start_year, start_month, start_day)
            total_commands_processed = 0
            completed_cycles = 0

            while completed_cycles < max_cycles and total_commands_processed < max_total_commands and overall_success:
                if verbose: print(f"\n--- Starting Cycle {completed_cycles + 1}/{max_cycles} ---")
                current_close_prob = initial_close_probability
                is_sim_closed = True

                while True:
                    if total_commands_processed >= max_total_commands or not overall_success: break
                    if verbose: print(f"  --- Batch (Date: {current_sim_date}, Closed: {is_sim_closed}) ---")
                    
                    num_requests = random.randint(min_requests_per_day, max_requests_per_day)
                    
                    # --- UPDATED: Pass new args to generate_command_cycle ---
                    commands, next_date, closed_after = generate_command_cycle(
                        python_library_model, current_sim_date, is_sim_closed,
                        num_requests, current_close_prob,
                        min_skip_days_post_close, max_skip_days_post_close,
                        borrow_weight, order_weight, pick_weight,
                        read_weight, restore_weight,
                        trace_query_weight, credit_query_weight,
                        failed_borrow_weight, failed_order_weight,
                        new_student_ratio, student_return_propensity,
                        student_pick_propensity, student_restore_propensity,
                        b_book_priority, c_book_priority, a_book_read_priority
                    )

                    sent_commands, sut_output = [], []
                    for cmd_str in commands:
                        if total_commands_processed >= max_total_commands: break
                        if verbose: print(f"  DRIVER -> SUT: {cmd_str}")
                        try:
                            # ... (send command)
                            if process.stdin and not process.stdin.closed:
                                process.stdin.write((cmd_str + '\n').encode('utf-8'))
                                if _stdin_log_fh: _stdin_log_fh.write(cmd_str + '\n'); _stdin_log_fh.flush()
                                process.stdin.flush()
                                sent_commands.append(cmd_str)
                                total_commands_processed += 1
                            else: raise IOError("SUT stdin closed")
                        except (IOError, BrokenPipeError) as e:
                            final_error_message = f"Error writing cmd to SUT: {e}."; overall_success = False; break

                        # The logic to determine context remains the same and already handles credit queries
                        cmd_parts = cmd_str.split()
                        op_context = OutputCollectionContext.USER_OPERATION_SINGLE_LINE
                        if cmd_parts[1] in ["OPEN", "CLOSE"]:
                            op_context = OutputCollectionContext.TIDY_OPERATION_OPEN_OR_CLOSE
                        elif len(cmd_parts) > 2 and cmd_parts[2] == "queried":
                            if len(cmd_parts) > 3 and cmd_parts[3] == "credit":
                                op_context = OutputCollectionContext.USER_OPERATION_SINGLE_LINE
                            else:
                                op_context = OutputCollectionContext.USER_OPERATION_QUERY
                        
                        output, success_flag = _collect_sut_output_smart(
                            stdout_q, process, op_context, SUT_OUTPUT_COLLECTION_POLL_INTERVAL, max_wait_per_line_sut_output, verbose, _stdout_log_fh
                        )
                        sut_output.extend(output)
                        if not success_flag:
                            final_error_message = f"SUT failed to provide expected output for command: {cmd_str}"
                            if process.poll() is not None: final_error_message += " SUT process terminated."
                            overall_success = False; break
                    
                    if not overall_success: break
                    if sent_commands:
                        if verbose: print(f"  DRIVER: Validating batch...")
                        check_result = check_cycle(sent_commands, sut_output, python_library_model)
                        if not check_result["is_legal"]:
                            final_error_message = f"Validation FAILED: {check_result['error_message']}"
                            if check_result.get("first_failing_command"): final_error_message += f" | Context: {check_result['first_failing_command']}"
                            overall_success = False
                        else:
                            if verbose: print(f"  Batch OK.")

                    if not overall_success: break
                    current_sim_date = next_date
                    is_sim_closed = closed_after
                    if is_sim_closed: break
                    else: current_close_prob = min(max_close_probability, current_close_prob + close_probability_increment)
                
                if not overall_success: break
                completed_cycles += 1
        
        if verbose: print("\n--- Interaction Loop Finished ---")
        if process and process.poll() is None:
            if verbose: print("Terminating SUT process...")
            try:
                if process.stdin and not process.stdin.closed: process.stdin.close()
                process.terminate(); process.wait(timeout=1.5)
            except Exception:
                if process.poll() is None: process.kill()

    finally:
        if _stdin_log_fh: _stdin_log_fh.close()
        if _stdout_log_fh: _stdout_log_fh.close()

    if verbose:
        if overall_success: print("\n+++ Driver finished: All checked operations were valid. +++")
        else: print(f"\n--- Driver finished: Errors encountered. Last error: {final_error_message} ---")
    
    if not overall_success and not final_error_message:
        final_error_message = "An unspecified error occurred."
    return overall_success, final_error_message

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run interactive test driver for LibrarySystem (HW15).")
    parser.add_argument("jar_path", help="Path to the student's JAR file.")
    # General controls
    parser.add_argument("--max_cycles", type=int, default=DEFAULT_MAX_CYCLES)
    parser.add_argument("--max_total_commands", type=int, default=DEFAULT_MAX_TOTAL_COMMANDS)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    # Date and request controls
    parser.add_argument("--min_skip_post_close", type=int, dest="min_skip_days_post_close", default=DEFAULT_MIN_SKIP_DAYS_POST_CLOSE_FOR_GEN)
    parser.add_argument("--max_skip_post_close", type=int, dest="max_skip_days_post_close", default=DEFAULT_MAX_SKIP_DAYS_POST_CLOSE_FOR_GEN)
    parser.add_argument("--min_req_per_day", type=int, dest="min_requests_per_day", default=DEFAULT_MIN_REQUESTS_PER_DAY_FOR_GEN)
    parser.add_argument("--max_req_per_day", type=int, dest="max_requests_per_day", default=DEFAULT_MAX_REQUESTS_PER_DAY_FOR_GEN)
    # Book initialization
    parser.add_argument("--init_types", type=int, dest="initial_book_types_count", default=INITIAL_BOOK_TYPES_COUNT)
    parser.add_argument("--init_min_cp", type=int, dest="initial_min_copies", default=INITIAL_BOOKS_MIN_COPIES)
    parser.add_argument("--init_max_cp", type=int, dest="initial_max_copies", default=INITIAL_BOOKS_MAX_COPIES)
    # Log files
    parser.add_argument("-i", "--input_log_file", dest="input_log_file_path_arg", type=str, default="stdin.txt")
    parser.add_argument("-o", "--output_log_file", dest="output_log_file_path_arg", type=str, default="stdout.txt")
    
    # --- UPDATED: Argparse for command weights ---
    parser.add_argument("--b_w", type=int, dest="borrow_weight", default=DEFAULT_BORROW_WEIGHT)
    parser.add_argument("--o_w", type=int, dest="order_weight", default=DEFAULT_ORDER_WEIGHT)
    parser.add_argument("--p_w", type=int, dest="pick_weight", default=DEFAULT_PICK_WEIGHT)
    parser.add_argument("--read_w", type=int, dest="read_weight", default=DEFAULT_READ_WEIGHT)
    parser.add_argument("--restore_w", type=int, dest="restore_weight", default=DEFAULT_RESTORE_WEIGHT)
    parser.add_argument("--trace_q_w", type=int, dest="trace_query_weight", default=DEFAULT_TRACE_QUERY_WEIGHT, help="Weight for generating trace queries.")
    parser.add_argument("--credit_q_w", type=int, dest="credit_query_weight", default=DEFAULT_CREDIT_QUERY_WEIGHT, help="Weight for generating credit score queries.")
    parser.add_argument("--fail_b_w", type=int, dest="failed_borrow_weight", default=DEFAULT_FAILED_BORROW_WEIGHT, help="Weight for generating failed actions due to low credit.")
    parser.add_argument("--fail_o_w", type=int, dest="failed_order_weight", default=DEFAULT_FAILED_ORDER_WEIGHT, help="Weight for generating failed orders due to existing holds.")

    # Propensity and priority arguments
    parser.add_argument("--ret_prop", type=float, dest="student_return_propensity", default=DEFAULT_STUDENT_RETURN_PROPENSITY)
    parser.add_argument("--pick_prop", type=float, dest="student_pick_propensity", default=DEFAULT_STUDENT_PICK_PROPENSITY)
    parser.add_argument("--restore_prop", type=float, dest="student_restore_propensity", default=DEFAULT_STUDENT_RESTORE_PROPENSITY)
    parser.add_argument("--b_prio", type=float, dest="b_book_priority", default=DEFAULT_B_BOOK_PRIORITY)
    parser.add_argument("--c_prio", type=float, dest="c_book_priority", default=DEFAULT_C_BOOK_PRIORITY)
    parser.add_argument("--a_read_prio", type=float, dest="a_book_read_priority", default=DEFAULT_A_BOOK_READ_PRIORITY)

    # Other driver settings
    parser.add_argument("--start_year", type=int, default=2025)
    parser.add_argument("--start_month", type=int, default=1)
    parser.add_argument("--start_day", type=int, default=1)
    parser.add_argument("--new_s_ratio", type=float, dest="new_student_ratio", default=DEFAULT_NEW_STUDENT_RATIO)
    parser.add_argument("--init_close_prob", type=float, dest="initial_close_probability", default=DEFAULT_INITIAL_CLOSE_PROBABILITY)
    parser.add_argument("--close_prob_inc", type=float, dest="close_probability_increment", default=DEFAULT_CLOSE_PROBABILITY_INCREMENT)
    parser.add_argument("--max_close_prob", type=float, dest="max_close_probability", default=DEFAULT_MAX_CLOSE_PROBABILITY)
    parser.add_argument("--cycle_timeout", dest="max_wait_per_line_sut_output", type=float, default=DEFAULT_MAX_WAIT_PER_LINE_SUT_OUTPUT)

    args = parser.parse_args()

    # --- UPDATED: Pass new args to run_driver ---
    run_successful, error_msg_details = run_driver(
        jar_path=args.jar_path,
        max_cycles=args.max_cycles, max_total_commands=args.max_total_commands,
        min_skip_days_post_close=args.min_skip_days_post_close, max_skip_days_post_close=args.max_skip_days_post_close,
        min_requests_per_day=args.min_requests_per_day, max_requests_per_day=args.max_requests_per_day,
        initial_close_probability=args.initial_close_probability, close_probability_increment=args.close_probability_increment, max_close_probability=args.max_close_probability,
        borrow_weight=args.borrow_weight, order_weight=args.order_weight, pick_weight=args.pick_weight,
        read_weight=args.read_weight, restore_weight=args.restore_weight,
        trace_query_weight=args.trace_query_weight,
        credit_query_weight=args.credit_query_weight,
        failed_borrow_weight=args.failed_borrow_weight,
        failed_order_weight=args.failed_order_weight,
        new_student_ratio=args.new_student_ratio, student_return_propensity=args.student_return_propensity, student_pick_propensity=args.student_pick_propensity, student_restore_propensity=args.student_restore_propensity,
        b_book_priority=args.b_book_priority, c_book_priority=args.c_book_priority, a_book_read_priority=args.a_book_read_priority,
        initial_book_types_count=args.initial_book_types_count, initial_min_copies=args.initial_min_copies, initial_max_copies=args.initial_max_copies,
        start_year=args.start_year, start_month=args.start_month, start_day=args.start_day,
        seed=args.seed, verbose=args.verbose,
        input_log_file_path_arg=args.input_log_file_path_arg, output_log_file_path_arg=args.output_log_file_path_arg,
        max_wait_per_line_sut_output=args.max_wait_per_line_sut_output
    )

    if not args.verbose:
        result_json = {"status": "success" if run_successful else "failure"}
        if not run_successful: result_json["reason"] = error_msg_details
        print(json.dumps(result_json))
        sys.exit(0 if run_successful else 1)
    else:
        sys.exit(0 if run_successful else 1)