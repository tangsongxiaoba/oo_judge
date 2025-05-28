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
    from gen import generate_command_cycle # Assuming this is the function from your gen.py
    from checker import check_cycle, parse_sut_query_header_line
except ImportError as e:
    print(f"Critical Driver Error: Could not import required modules (state, gen, checker): {e}")
    try:
        print(json.dumps({"status": "failure", "reason": f"Critical import error: {e}"}))
    except Exception:
        pass
    sys.exit(1)

# --- Constants ---
DEFAULT_MAX_CYCLES = 5 # Max OPEN-CLOSE cycles
DEFAULT_MAX_TOTAL_COMMANDS = 200
INITIAL_BOOK_TYPES_COUNT = 5
INITIAL_BOOKS_MIN_COPIES = 1
INITIAL_BOOKS_MAX_COPIES = 10

SUT_OUTPUT_COLLECTION_POLL_INTERVAL = 0.05
DEFAULT_MAX_WAIT_PER_LINE_SUT_OUTPUT = 2.0

# Default parameters for gen.py's generate_command_cycle
DEFAULT_MIN_SKIP_DAYS_POST_CLOSE_FOR_GEN = 0
DEFAULT_MAX_SKIP_DAYS_POST_CLOSE_FOR_GEN = 1
DEFAULT_MIN_REQUESTS_PER_DAY_FOR_GEN = 1
DEFAULT_MAX_REQUESTS_PER_DAY_FOR_GEN = 5

# Dynamic close_probability parameters (driver controlled)
DEFAULT_INITIAL_CLOSE_PROBABILITY = 0.1
DEFAULT_CLOSE_PROBABILITY_INCREMENT = 0.15 # Increase a bit faster
DEFAULT_MAX_CLOSE_PROBABILITY = 0.9 # Allow it to go higher

# Default weights and ratios for gen.py
DEFAULT_BORROW_WEIGHT = 3
DEFAULT_ORDER_WEIGHT = 2
DEFAULT_QUERY_WEIGHT = 3
DEFAULT_PICK_WEIGHT = 2
DEFAULT_FAILED_ORDER_WEIGHT = 1
DEFAULT_READ_WEIGHT = 2
DEFAULT_RESTORE_WEIGHT = 1
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
    except ValueError:
        pass
    except Exception:
        pass
    finally:
        if hasattr(out, 'close') and not out.closed:
            try:
                out.close()
            except Exception:
                pass

def _format_date_cmd(date_obj: date) -> str:
    return date_obj.strftime("%Y-%m-%d")

# --- Smart Output Collection (unchanged) ---
class OutputCollectionContext:
    USER_OPERATION_SINGLE_LINE = 1
    USER_OPERATION_QUERY = 2
    TIDY_OPERATION_OPEN_OR_CLOSE = 3

def _collect_sut_output_smart(
    sut_stdout_q,
    sut_process: subprocess.Popen,
    context: OutputCollectionContext,
    poll_interval: float,
    max_wait_per_line_seconds: float,
    verbose: bool,
    log_fh: Optional[Any]
) -> Tuple[List[str], bool]:
    collected_lines: List[str] = []
    expected_lines_to_collect_current_block = 0
    lines_collected_this_block = 0

    if context == OutputCollectionContext.TIDY_OPERATION_OPEN_OR_CLOSE:
        line_start_time = time.monotonic()
        while True:
            if sut_process.poll() is not None:
                if verbose: print("DRIVER: SUT process terminated before Tidy count line.")
                return collected_lines, False
            try:
                first_line = sut_stdout_q.get(timeout=poll_interval)
                collected_lines.append(first_line)
                if log_fh: log_fh.write(first_line + '\n')
                if verbose: print(f"SUT -> DRIVER (Tidy Count Line): {first_line}")
                lines_collected_this_block += 1
                break
            except queue.Empty:
                if time.monotonic() - line_start_time > max_wait_per_line_seconds:
                    if verbose: print(f"DRIVER: Timeout waiting for Tidy count line ({max_wait_per_line_seconds}s).")
                    return collected_lines, False
        try:
            num_tidy_moves = int(first_line)
            if num_tidy_moves < 0:
                if verbose: print(f"DRIVER: Invalid Tidy move count: {num_tidy_moves}.")
                return collected_lines, False
            expected_lines_to_collect_current_block = 1 + num_tidy_moves
        except ValueError:
            if verbose: print(f"DRIVER: Error parsing Tidy move count from line: '{first_line}'.")
            return collected_lines, False

    elif context == OutputCollectionContext.USER_OPERATION_QUERY:
        line_start_time = time.monotonic()
        while True:
            if sut_process.poll() is not None:
                if verbose: print("DRIVER: SUT process terminated before Query header line.")
                return collected_lines, False
            try:
                query_header_line = sut_stdout_q.get(timeout=poll_interval)
                collected_lines.append(query_header_line)
                if log_fh: log_fh.write(query_header_line + '\n')
                if verbose: print(f"SUT -> DRIVER (Query Header): {query_header_line}")
                lines_collected_this_block += 1
                break
            except queue.Empty:
                if time.monotonic() - line_start_time > max_wait_per_line_seconds:
                    if verbose: print(f"DRIVER: Timeout waiting for Query header line ({max_wait_per_line_seconds}s).")
                    return collected_lines, False
        try:
            parsed_header = parse_sut_query_header_line(query_header_line)
            if not parsed_header:
                if verbose: print(f"DRIVER: Error parsing Query header line: '{query_header_line}'.")
                return collected_lines, False
            _, _, num_trace_lines = parsed_header
            if num_trace_lines < 0:
                if verbose: print(f"DRIVER: Invalid Query trace count: {num_trace_lines}.")
                return collected_lines, False
            expected_lines_to_collect_current_block = 1 + num_trace_lines
        except (ValueError, TypeError):
             if verbose: print(f"DRIVER: Error parsing trace count from query header: '{query_header_line}'.")
             return collected_lines, False

    elif context == OutputCollectionContext.USER_OPERATION_SINGLE_LINE:
        expected_lines_to_collect_current_block = 1
    else:
        if verbose: print(f"DRIVER: Unknown output collection context: {context}")
        return collected_lines, False

    lines_to_collect_remaining_for_block = expected_lines_to_collect_current_block - lines_collected_this_block
    for i in range(lines_to_collect_remaining_for_block):
        line_start_time = time.monotonic()
        while True:
            if sut_process.poll() is not None:
                if verbose: print(f"DRIVER: SUT process terminated while waiting for expected line {lines_collected_this_block + 1}/{expected_lines_to_collect_current_block}.")
                return collected_lines, False
            try:
                line = sut_stdout_q.get(timeout=poll_interval)
                collected_lines.append(line)
                if log_fh: log_fh.write(line + '\n')
                if verbose: print(f"SUT -> DRIVER (Line {lines_collected_this_block + 1}): {line}")
                lines_collected_this_block += 1
                break
            except queue.Empty:
                if time.monotonic() - line_start_time > max_wait_per_line_seconds:
                    if verbose: print(f"DRIVER: Timeout waiting for expected line {lines_collected_this_block +1}/{expected_lines_to_collect_current_block} ({max_wait_per_line_seconds}s).")
                    return collected_lines, False

    if lines_collected_this_block != expected_lines_to_collect_current_block:
        if verbose: print(f"DRIVER: Line count mismatch. Collected {lines_collected_this_block}, expected {expected_lines_to_collect_current_block}.")
        return collected_lines, False
    return collected_lines, True


# --- Main Driver Logic ---
def run_driver(
    jar_path: str,
    max_cycles: int = DEFAULT_MAX_CYCLES,
    max_total_commands: int = DEFAULT_MAX_TOTAL_COMMANDS,
    min_skip_days_post_close: int = DEFAULT_MIN_SKIP_DAYS_POST_CLOSE_FOR_GEN,
    max_skip_days_post_close: int = DEFAULT_MAX_SKIP_DAYS_POST_CLOSE_FOR_GEN,
    min_requests_per_day: int = DEFAULT_MIN_REQUESTS_PER_DAY_FOR_GEN,
    max_requests_per_day: int = DEFAULT_MAX_REQUESTS_PER_DAY_FOR_GEN,
    initial_close_probability: float = DEFAULT_INITIAL_CLOSE_PROBABILITY,
    close_probability_increment: float = DEFAULT_CLOSE_PROBABILITY_INCREMENT,
    max_close_probability: float = DEFAULT_MAX_CLOSE_PROBABILITY,
    borrow_weight: int = DEFAULT_BORROW_WEIGHT,
    order_weight: int = DEFAULT_ORDER_WEIGHT,
    query_weight: int = DEFAULT_QUERY_WEIGHT,
    pick_weight: int = DEFAULT_PICK_WEIGHT,
    failed_order_weight: int = DEFAULT_FAILED_ORDER_WEIGHT,
    read_weight: int = DEFAULT_READ_WEIGHT,
    restore_weight: int = DEFAULT_RESTORE_WEIGHT,
    new_student_ratio: float = DEFAULT_NEW_STUDENT_RATIO,
    student_return_propensity: float = DEFAULT_STUDENT_RETURN_PROPENSITY,
    student_pick_propensity: float = DEFAULT_STUDENT_PICK_PROPENSITY,
    student_restore_propensity: float = DEFAULT_STUDENT_RESTORE_PROPENSITY,
    b_book_priority: float = DEFAULT_B_BOOK_PRIORITY,
    c_book_priority: float = DEFAULT_C_BOOK_PRIORITY,
    a_book_read_priority: float = DEFAULT_A_BOOK_READ_PRIORITY,
    initial_book_types_count: int = INITIAL_BOOK_TYPES_COUNT,
    initial_min_copies: int = INITIAL_BOOKS_MIN_COPIES,
    initial_max_copies: int = INITIAL_BOOKS_MAX_COPIES,
    start_year: int = 2025, start_month: int = 1, start_day: int = 1,
    seed: Optional[int] = None,
    verbose: bool = False,
    input_log_file_path_arg: Optional[str] = None,
    output_log_file_path_arg: Optional[str] = None,
    max_wait_per_line_sut_output: float = DEFAULT_MAX_WAIT_PER_LINE_SUT_OUTPUT
) -> Tuple[bool, str]:

    final_error_message = ""
    overall_success = True
    process: Optional[subprocess.Popen] = None
    stdout_thread: Optional[threading.Thread] = None
    stderr_thread: Optional[threading.Thread] = None
    stdout_q: Optional[queue.Queue[str]] = None # Corrected type hint
    stderr_q: Optional[queue.Queue[str]] = None # Corrected type hint

    _stdin_log_fh = None
    _stdout_log_fh = None

    try:
        final_input_log_path_to_use = None
        if input_log_file_path_arg: final_input_log_path_to_use = input_log_file_path_arg
        elif not verbose: final_input_log_path_to_use = "stdin.txt"

        final_output_log_path_to_use = None
        if output_log_file_path_arg: final_output_log_path_to_use = output_log_file_path_arg
        elif not verbose: final_output_log_path_to_use = "stdout.txt"

        if final_input_log_path_to_use:
            try: _stdin_log_fh = open(final_input_log_path_to_use, 'w', encoding='utf-8')
            except IOError: pass

        if final_output_log_path_to_use:
            try: _stdout_log_fh = open(final_output_log_path_to_use, 'w', encoding='utf-8')
            except IOError: pass

        if seed is not None:
            random.seed(seed)

        python_library_model = LibrarySystem()

        if verbose: print("--- Generating Initial Book Data ---")
        initial_book_commands_str_list = []
        isbn_set = set()
        book_types_available = ['A', 'B', 'C']

        actual_initial_book_types_count = max(0, initial_book_types_count)
        initial_book_commands_str_list.append(str(actual_initial_book_types_count))

        generated_types_count = 0
        if actual_initial_book_types_count > 0:
            attempts = 0; max_attempts = actual_initial_book_types_count * 10
            while generated_types_count < actual_initial_book_types_count and attempts < max_attempts:
                book_type_choice = random.choice(book_types_available)
                seq_num = f"{random.randint(0, 9999):04d}"
                isbn = f"{book_type_choice}-{seq_num}"
                if isbn in isbn_set:
                    attempts +=1; continue
                isbn_set.add(isbn)
                num_copies = random.randint(initial_min_copies, initial_max_copies)
                initial_book_commands_str_list.append(f"{isbn} {num_copies}")
                generated_types_count += 1; attempts +=1

            if generated_types_count < actual_initial_book_types_count:
                initial_book_commands_str_list[0] = str(generated_types_count)
            if generated_types_count == 0 :
                final_error_message = f"Error: Failed to generate any initial books (requested {actual_initial_book_types_count})."
                overall_success = False

        if overall_success and generated_types_count > 0 :
            python_library_model.initialize_books(initial_book_commands_str_list[1:])

        if overall_success:
            if verbose: print(f"\n--- Starting Java Process: {jar_path} ---")
            try:
                process = subprocess.Popen(['java', '-jar', jar_path],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           universal_newlines=False)
            except FileNotFoundError:
                final_error_message = f"Error: JAR file not found at '{jar_path}'."; overall_success = False
            except Exception as e:
                final_error_message = f"Error starting JAR process: {e}"; overall_success = False

        if overall_success and process:
            stdout_q = queue.Queue()
            stderr_q = queue.Queue()
            stdout_thread = threading.Thread(target=enqueue_output, args=(process.stdout, stdout_q), name="SUT_StdoutThread", daemon=True)
            stderr_thread = threading.Thread(target=enqueue_output, args=(process.stderr, stderr_q), name="SUT_StderrThread", daemon=True)
            stdout_thread.start(); stderr_thread.start()

            for line_num, line in enumerate(initial_book_commands_str_list):
                if verbose: print(f"DRIVER -> SUT (Initial Line {line_num+1}): {line}")
                try:
                    if process.stdin and not process.stdin.closed:
                        line_with_nl = line + '\n'
                        process.stdin.write(line_with_nl.encode('utf-8'))
                        if _stdin_log_fh: _stdin_log_fh.write(line_with_nl)
                        process.stdin.flush()
                    else:
                        final_error_message = "Error: SUT stdin closed unexpectedly during initial data send."; overall_success = False; break
                except (IOError, BrokenPipeError) as e:
                    final_error_message = f"Error writing initial data to JAR stdin: {e}. SUT likely crashed."; overall_success = False; break

        current_sim_date = date(start_year, start_month, start_day)
        is_sim_library_closed = True
        total_commands_processed_in_driver = 0
        completed_open_close_cycles = 0

        if overall_success and process and stdout_q:
            while completed_open_close_cycles < max_cycles and \
                  total_commands_processed_in_driver < max_total_commands and \
                  overall_success:

                if verbose:
                    print(f"\n--- Starting OPEN-CLOSE Cycle {completed_open_close_cycles + 1}/{max_cycles} ---")

                current_dynamic_close_prob = initial_close_probability
                days_in_current_open_period_for_prob_increase = 0

                # Ensure library is treated as closed before starting a new OPEN-CLOSE cycle for gen.py
                # This `is_sim_library_closed` is the state *before* calling gen.generate_command_cycle
                # for the first batch of this OPEN-CLOSE cycle.
                is_sim_library_closed = True

                # Inner loop: represents one OPEN period (multiple days/batches until a CLOSE)
                while True: # Loop until this OPEN-CLOSE cycle is completed by a CLOSE
                    if total_commands_processed_in_driver >= max_total_commands:
                        if verbose: print("Max total commands reached. Breaking OPEN period."); break
                    if not overall_success: break

                    days_in_current_open_period_for_prob_increase +=1
                    if verbose:
                        print(f"  --- Batch {days_in_current_open_period_for_prob_increase} of current OPEN period (Driver Date: {current_sim_date}, LibClosedForGen: {is_sim_library_closed}) ---")
                        print(f"  Current dynamic_close_prob for gen: {current_dynamic_close_prob:.2f}")

                    num_requests_this_batch = random.randint(min_requests_per_day, max_requests_per_day)
                    if is_sim_library_closed and num_requests_this_batch == 0: # Ensure action if opening
                        num_requests_this_batch = 1

                    commands_for_batch, next_date_from_gen, closed_after_batch = \
                        generate_command_cycle(
                            python_library_model, current_sim_date, is_sim_library_closed,
                            num_requests_this_batch,
                            current_dynamic_close_prob, # Use the dynamic probability
                            min_skip_days_post_close, max_skip_days_post_close,
                            borrow_weight, order_weight, query_weight, pick_weight,
                            failed_order_weight, read_weight, restore_weight,
                            new_student_ratio, student_return_propensity,
                            student_pick_propensity, student_restore_propensity,
                            b_book_priority, c_book_priority, a_book_read_priority
                        )

                    if not commands_for_batch:
                        if verbose: print("  Generator produced no commands for this batch. Assuming CLOSE for this OPEN-CLOSE cycle.");
                        is_sim_library_closed = True # Effectively ends the OPEN period
                        break # Break inner loop, will increment completed_open_close_cycles

                    if verbose: print(f"  Generator produced {len(commands_for_batch)} commands for this batch.")

                    sut_output_for_this_batch: List[str] = []
                    actual_commands_sent_this_batch: List[str] = []

                    for cmd_idx, cmd_str in enumerate(commands_for_batch):
                        if total_commands_processed_in_driver >= max_total_commands:
                            if verbose: print("  Max total commands reached. Stopping mid-batch."); break

                        if verbose: print(f"  DRIVER -> SUT (Cmd {cmd_idx+1}/{len(commands_for_batch)}): {cmd_str}")
                        try:
                            if process.stdin and not process.stdin.closed:
                                process.stdin.write((cmd_str + '\n').encode('utf-8'))
                                if _stdin_log_fh: _stdin_log_fh.write(cmd_str + '\n')
                                process.stdin.flush()
                                actual_commands_sent_this_batch.append(cmd_str)
                                total_commands_processed_in_driver += 1
                            else:
                                final_error_message = f"Error: SUT stdin closed before sending cmd '{cmd_str}'."; overall_success = False; break
                        except (IOError, BrokenPipeError) as e:
                            final_error_message = f"Error writing cmd '{cmd_str}' to SUT: {e}."; overall_success = False; break
                        if not overall_success: break

                        cmd_parts = cmd_str.split()
                        # cmd_parts[0] is "[YYYY-MM-DD]", cmd_parts[1] is operation or student_id
                        action_type_or_student = cmd_parts[1]
                        op_context: OutputCollectionContext
                        if action_type_or_student == "OPEN" or action_type_or_student == "CLOSE":
                            op_context = OutputCollectionContext.TIDY_OPERATION_OPEN_OR_CLOSE
                        elif len(cmd_parts) > 2 and cmd_parts[2] == "queried": # Student command: [date] student_id queried book_id
                            op_context = OutputCollectionContext.USER_OPERATION_QUERY
                        else: # Other student commands or potentially malformed
                            op_context = OutputCollectionContext.USER_OPERATION_SINGLE_LINE

                        collected_op_output, success_flag = _collect_sut_output_smart(
                            stdout_q, process, op_context, # Use op_context here
                            SUT_OUTPUT_COLLECTION_POLL_INTERVAL, max_wait_per_line_sut_output, verbose, _stdout_log_fh
                        )
                        sut_output_for_this_batch.extend(collected_op_output)
                        if not success_flag:
                            final_error_message = f"SUT failed to provide expected output for command: {cmd_str}"
                            if process.poll() is not None: final_error_message += " SUT process terminated."
                            overall_success = False; break
                    # End of loop for commands within one batch from gen.py
                    if not overall_success: break # Break inner 'while True' for OPEN period

                    if actual_commands_sent_this_batch:
                        if verbose:
                            print(f"  DRIVER: Validating batch (Driver Date Ref: {current_sim_date}) with {len(actual_commands_sent_this_batch)} driver commands and {len(sut_output_for_this_batch)} SUT output lines.")

                        batch_check_result = check_cycle(
                            actual_commands_sent_this_batch, sut_output_for_this_batch, python_library_model
                        )
                        if not batch_check_result["is_legal"]:
                            final_error_message = f"Batch Validation FAILED (Driver Date Ref: {current_sim_date}): {batch_check_result['error_message']}"
                            if batch_check_result.get("first_failing_command"):
                                final_error_message += f" | Context: {batch_check_result['first_failing_command']}"
                            overall_success = False; break
                        else:
                            if verbose: print(f"  Batch (Driver Date Ref: {current_sim_date}) OK.")
                    elif verbose:
                        print(f"  DRIVER: No commands were sent/validated in this batch (Driver Date Ref: {current_sim_date}).")
                    if not overall_success: break # Break inner 'while True' for OPEN period

                    # Update driver's state for the next call to gen.py or next OPEN-CLOSE cycle
                    current_sim_date = next_date_from_gen
                    is_sim_library_closed = closed_after_batch # This is CRUCIAL

                    if is_sim_library_closed: # This batch ended with a CLOSE
                        if verbose: print(f"  Library CLOSED by generator for date {current_sim_date}. Ending current OPEN period.")
                        break # Exit inner 'while True' loop, completing the OPEN-CLOSE cycle
                    else: # Library still OPEN, increase close_probability for the next batch in this OPEN period
                        current_dynamic_close_prob = min(max_close_probability, current_dynamic_close_prob + close_probability_increment)
                # End of inner 'while True' loop (one OPEN period finishes)

                if not overall_success: break # Break outer 'completed_open_close_cycles' loop

                if is_sim_library_closed: # Successfully completed an OPEN -> ... -> CLOSE sequence
                    completed_open_close_cycles += 1
                    if verbose: print(f"--- Completed OPEN-CLOSE Cycle {completed_open_close_cycles}/{max_cycles} ---")
                else: # Inner loop exited for other reasons (e.g. max_total_commands) before a CLOSE
                    if verbose: print("Warning: Inner OPEN period loop exited without the library being closed. Test run may end prematurely.")
                    break # Terminate outer loop as well, as an OPEN-CLOSE cycle wasn't completed.
            # End of outer 'completed_open_close_cycles' loop

        if verbose: print("\n--- Interaction Loop Finished ---")

        sut_exit_code = -1
        if process:
            sut_exit_code = process.poll()
            if sut_exit_code is None:
                if verbose: print("Terminating SUT process...")
                try:
                    if process.stdin and not process.stdin.closed: process.stdin.close()
                except Exception: pass
                process.terminate()
                try:
                    sut_exit_code = process.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    if verbose: print("SUT did not terminate gracefully, killing."); process.kill()
                    try: sut_exit_code = process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired: sut_exit_code = -99
                except Exception: sut_exit_code = -98

        if verbose and stdout_q and stderr_q : # Check if queues were initialized
            def drain_queue(q_to_drain, q_name: str):
                if q_to_drain is None: return
                drained_count = 0
                while not q_to_drain.empty():
                    try:
                        item = q_to_drain.get_nowait()
                        if verbose and drained_count < 5:
                             print(f"DRIVER: Draining SUT {q_name} (lingering): {item}")
                        drained_count+=1
                    except queue.Empty: break
                if drained_count > 0 and verbose: print(f"DRIVER: Drained {drained_count} items from SUT {q_name} queue.")
            drain_queue(stdout_q, "STDOUT")
            drain_queue(stderr_q, "STDERR")

        if stdout_thread and stdout_thread.is_alive(): stdout_thread.join(timeout=0.5)
        if stderr_thread and stderr_thread.is_alive(): stderr_thread.join(timeout=0.5)

    finally:
        if _stdin_log_fh:
            try: _stdin_log_fh.close()
            except Exception: pass
        if _stdout_log_fh:
            try: _stdout_log_fh.close()
            except Exception: pass

    if verbose:
        if overall_success: print("\n+++ Driver finished: All checked operations were valid. +++")
        else: print(f"\n--- Driver finished: Errors encountered. Last error: {final_error_message} ---")

    if not overall_success and not final_error_message:
         final_error_message = "An unspecified error occurred."

    return overall_success, final_error_message


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run interactive test driver for LibrarySystem (hw14 compliant, uses gen.py for command cycles, dynamic close_prob).")
    parser.add_argument("jar_path", help="Path to the student's JAR file.")
    parser.add_argument("--max_cycles", type=int, default=DEFAULT_MAX_CYCLES, help="Max number of full OPEN-CLOSE cycles.")
    parser.add_argument("--max_total_commands", type=int, default=DEFAULT_MAX_TOTAL_COMMANDS, help="Max total commands sent to SUT.")

    parser.add_argument("--min_skip_post_close", type=int, dest="min_skip_days_post_close", default=DEFAULT_MIN_SKIP_DAYS_POST_CLOSE_FOR_GEN)
    parser.add_argument("--max_skip_post_close", type=int, dest="max_skip_days_post_close", default=DEFAULT_MAX_SKIP_DAYS_POST_CLOSE_FOR_GEN)
    parser.add_argument("--min_req_per_day", type=int, dest="min_requests_per_day", default=DEFAULT_MIN_REQUESTS_PER_DAY_FOR_GEN)
    parser.add_argument("--max_req_per_day", type=int, dest="max_requests_per_day", default=DEFAULT_MAX_REQUESTS_PER_DAY_FOR_GEN)

    parser.add_argument("--init_close_prob", type=float, dest="initial_close_probability", default=DEFAULT_INITIAL_CLOSE_PROBABILITY, help="Initial close probability after an OPEN.")
    parser.add_argument("--close_prob_inc", type=float, dest="close_probability_increment", default=DEFAULT_CLOSE_PROBABILITY_INCREMENT, help="Increment for close probability per batch in an OPEN period.")
    parser.add_argument("--max_close_prob", type=float, dest="max_close_probability", default=DEFAULT_MAX_CLOSE_PROBABILITY, help="Maximum close probability.")

    parser.add_argument("--b_w", type=int, dest="borrow_weight", default=DEFAULT_BORROW_WEIGHT)
    parser.add_argument("--o_w", type=int, dest="order_weight", default=DEFAULT_ORDER_WEIGHT)
    parser.add_argument("--q_w", type=int, dest="query_weight", default=DEFAULT_QUERY_WEIGHT)
    parser.add_argument("--p_w", type=int, dest="pick_weight", default=DEFAULT_PICK_WEIGHT)
    parser.add_argument("--fo_w", type=int, dest="failed_order_weight", default=DEFAULT_FAILED_ORDER_WEIGHT)
    parser.add_argument("--read_w", type=int, dest="read_weight", default=DEFAULT_READ_WEIGHT)
    parser.add_argument("--restore_w", type=int, dest="restore_weight", default=DEFAULT_RESTORE_WEIGHT)
    parser.add_argument("--new_s_ratio", type=float, dest="new_student_ratio", default=DEFAULT_NEW_STUDENT_RATIO)
    parser.add_argument("--ret_prop", type=float, dest="student_return_propensity", default=DEFAULT_STUDENT_RETURN_PROPENSITY)
    parser.add_argument("--pick_prop", type=float, dest="student_pick_propensity", default=DEFAULT_STUDENT_PICK_PROPENSITY)
    parser.add_argument("--restore_prop", type=float, dest="student_restore_propensity", default=DEFAULT_STUDENT_RESTORE_PROPENSITY)
    parser.add_argument("--b_prio", type=float, dest="b_book_priority", default=DEFAULT_B_BOOK_PRIORITY)
    parser.add_argument("--c_prio", type=float, dest="c_book_priority", default=DEFAULT_C_BOOK_PRIORITY)
    parser.add_argument("--a_read_prio", type=float, dest="a_book_read_priority", default=DEFAULT_A_BOOK_READ_PRIORITY)
    parser.add_argument("--init_types", type=int, dest="initial_book_types_count", default=INITIAL_BOOK_TYPES_COUNT)
    parser.add_argument("--init_min_cp", type=int, dest="initial_min_copies", default=INITIAL_BOOKS_MIN_COPIES)
    parser.add_argument("--init_max_cp", type=int, dest="initial_max_copies", default=INITIAL_BOOKS_MAX_COPIES)
    parser.add_argument("--start_year", type=int, default=2025); parser.add_argument("--start_month", type=int, default=1); parser.add_argument("--start_day", type=int, default=1)
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output.")
    parser.add_argument("-i", "--input_log_file", dest="input_log_file_path_arg", type=str, default=None)
    parser.add_argument("-o", "--output_log_file", dest="output_log_file_path_arg", type=str, default=None)
    parser.add_argument("--cycle_timeout", dest="max_wait_per_line_sut_output", type=float, default=DEFAULT_MAX_WAIT_PER_LINE_SUT_OUTPUT, help="Max wait time (sec) for each line of SUT output.")

    args = parser.parse_args()

    run_successful, error_msg_details = run_driver(
        jar_path=args.jar_path,
        max_cycles=args.max_cycles, max_total_commands=args.max_total_commands,
        min_skip_days_post_close=args.min_skip_days_post_close,
        max_skip_days_post_close=args.max_skip_days_post_close,
        min_requests_per_day=args.min_requests_per_day,
        max_requests_per_day=args.max_requests_per_day,
        initial_close_probability=args.initial_close_probability,
        close_probability_increment=args.close_probability_increment,
        max_close_probability=args.max_close_probability,
        borrow_weight=args.borrow_weight, order_weight=args.order_weight, query_weight=args.query_weight,
        pick_weight=args.pick_weight, failed_order_weight=args.failed_order_weight, read_weight=args.read_weight,
        restore_weight=args.restore_weight,
        new_student_ratio=args.new_student_ratio,
        student_return_propensity=args.student_return_propensity, student_pick_propensity=args.student_pick_propensity,
        student_restore_propensity=args.student_restore_propensity,
        b_book_priority=args.b_book_priority, c_book_priority=args.c_book_priority, a_book_read_priority=args.a_book_read_priority,
        initial_book_types_count=args.initial_book_types_count, initial_min_copies=args.initial_min_copies, initial_max_copies=args.initial_max_copies,
        start_year=args.start_year, start_month=args.start_month, start_day=args.start_day,
        seed=args.seed, verbose=args.verbose,
        input_log_file_path_arg=args.input_log_file_path_arg, output_log_file_path_arg=args.output_log_file_path_arg,
        max_wait_per_line_sut_output=args.max_wait_per_line_sut_output
    )

    if not args.verbose:
        result_json = {}
        if run_successful:
            result_json["status"] = "success"
        else:
            result_json["status"] = "failure"
            result_json["reason"] = error_msg_details if error_msg_details else "Unknown error."
        print(json.dumps(result_json))
        sys.exit(0 if run_successful else 1)
    else:
        if not run_successful and error_msg_details:
            print(f"Driver run final error: {error_msg_details}")
        sys.exit(0 if run_successful else 1)