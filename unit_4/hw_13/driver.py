# driver.py
import subprocess
import threading
import queue
import time
# import json # Not used in current driver, but often useful
import random
from datetime import date, timedelta
import argparse

# Assuming state.py, gen.py, checker.py are in the same directory or accessible
from state import LibrarySystem
from gen import gen_open_close_cycle_data # gen.py now has failed_order_weight
from checker import check_cycle 

# --- Constants ---
DEFAULT_MAX_CYCLES = 10
DEFAULT_MAX_TOTAL_COMMANDS = 200
JAR_TIMEOUT_SECONDS = 5 
INITIAL_BOOK_TYPES = 5
INITIAL_BOOKS_MIN_COPIES = 1
INITIAL_BOOKS_MAX_COPIES = 10
SUT_OUTPUT_COLLECTION_TIMEOUT = 2.0 
SUT_OUTPUT_COLLECTION_POLL_INTERVAL = 0.05

# Default weights for command generation
DEFAULT_BORROW_WEIGHT = 3
DEFAULT_ORDER_WEIGHT = 2          # For successful/valid order attempts
DEFAULT_QUERY_WEIGHT = 3
DEFAULT_FAILED_ORDER_WEIGHT = 0   # Default to 0, enable explicitly for testing this scenario
DEFAULT_NEW_STUDENT_RATIO = 0.2
DEFAULT_MIN_DAYS_TO_SKIP = 0
DEFAULT_MAX_DAYS_TO_SKIP = 1
DEFAULT_MIN_REQUESTS_PER_DAY = 1
DEFAULT_MAX_REQUESTS_PER_DAY = 5


# --- I/O Thread for Java Process ---
def enqueue_output(out, q):
    """Reads lines from a stream and puts them into a queue."""
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
    order_weight: int = DEFAULT_ORDER_WEIGHT,         # For successful/valid order attempts
    query_weight: int = DEFAULT_QUERY_WEIGHT,
    failed_order_weight: int = DEFAULT_FAILED_ORDER_WEIGHT, # New: For expected-to-fail orders
    new_student_ratio: float = DEFAULT_NEW_STUDENT_RATIO,
    initial_book_types_count: int = INITIAL_BOOK_TYPES,
    initial_min_copies: int = INITIAL_BOOKS_MIN_COPIES,
    initial_max_copies: int = INITIAL_BOOKS_MAX_COPIES,
    start_year: int = 2025,
    start_month: int = 1,
    start_day: int = 1,
    sut_prints_user_ops_immediately: bool = True, 
    seed: int = None,
    verbose: bool = False
):
    if seed is not None:
        random.seed(seed)

    python_library_model = LibrarySystem()

    print("--- Generating Initial Book Data ---")
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
            attempts +=1
            continue
        isbn_set.add(isbn)
        num_copies = random.randint(initial_min_copies, initial_max_copies)
        initial_book_commands_str_list.append(f"{isbn} {num_copies}")
        generated_types_count += 1
        attempts +=1
    
    if generated_types_count < initial_book_types_count:
        print(f"Warning: Could only generate {generated_types_count} unique book types out of {initial_book_types_count} requested.")
        initial_book_commands_str_list[0] = str(generated_types_count) 
        if generated_types_count == 0:
            print("Error: No initial books generated. Exiting.")
            return False

    python_library_model.initialize_books(initial_book_commands_str_list[1:])
    if verbose:
        print("Python model initialized with books:")
        for isbn_item, book_ids in python_library_model.books_on_shelf_by_isbn.items(): # Renamed isbn to isbn_item
            print(f"  {isbn_item}: {len(book_ids)} copies ({book_ids[:3]}...)")


    print(f"\n--- Starting Java Process: {jar_path} ---")
    try:
        process = subprocess.Popen(['java', '-jar', jar_path],
                                   stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
    except FileNotFoundError:
        print(f"Error: JAR file not found at '{jar_path}'. Please check the path.")
        return False
    except Exception as e:
        print(f"Error starting JAR process: {e}")
        return False

    stdout_q = queue.Queue()
    stderr_q = queue.Queue()
    stdout_thread = threading.Thread(target=enqueue_output, args=(process.stdout, stdout_q), name="SUT_StdoutThread", daemon=True)
    stderr_thread = threading.Thread(target=enqueue_output, args=(process.stderr, stderr_q), name="SUT_StderrThread", daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    overall_success = True 
    for line in initial_book_commands_str_list:
        if verbose: print(f"DRIVER -> SUT (Initial): {line}")
        try:
            if process.stdin.closed:
                print("Error: SUT stdin closed unexpectedly during initial data send.")
                overall_success = False; break
            process.stdin.write((line + '\n').encode('utf-8'))
            process.stdin.flush()
        except (IOError, BrokenPipeError) as e:
            print(f"Error writing initial data to JAR stdin: {e}. SUT likely crashed.")
            overall_success = False; break # Set overall_success to False and break
        time.sleep(0.01) 
    
    if not overall_success: # Check if loop was broken due to error
        if process.poll() is None: process.terminate()
        return False

    current_cycle_num = 0
    total_commands_processed_in_driver = 0
    next_cycle_start_date_obj = date(start_year, start_month, start_day)

    print("\n--- Starting Interaction Loop (Batch Mode) ---")
    while current_cycle_num < max_cycles and total_commands_processed_in_driver < max_total_commands:
        current_cycle_num += 1
        print(f"\n--- Cycle {current_cycle_num}/{max_cycles} ---")

        cycle_commands_to_send, next_date_for_next_cycle = gen_open_close_cycle_data(
            python_library_model, next_cycle_start_date_obj,
            min_days_to_skip, max_days_to_skip, 
            min_requests_per_day, max_requests_per_day,
            borrow_weight, 
            order_weight, # For successful orders
            query_weight,
            failed_order_weight, # Pass the new weight here
            new_student_ratio
        )
        
        if not cycle_commands_to_send:
            print("Generator produced no commands for this cycle. Ending early.")
            break
        next_cycle_start_date_obj = next_date_for_next_cycle

        if verbose: print(f"DRIVER: Sending {len(cycle_commands_to_send)} commands for this cycle to SUT.")
        for command_str in cycle_commands_to_send:
            if total_commands_processed_in_driver >= max_total_commands:
                print("Max total commands reached. Ending.")
                break
            total_commands_processed_in_driver += 1
            
            if verbose: print(f"DRIVER -> SUT: {command_str}")
            try:
                if process.stdin.closed:
                    print(f"Error: SUT stdin closed before sending command '{command_str}'.")
                    overall_success = False; break
                process.stdin.write((command_str + '\n').encode('utf-8'))
                process.stdin.flush()
            except (IOError, BrokenPipeError) as e:
                print(f"Error writing command '{command_str}' to JAR stdin: {e}. SUT likely crashed.")
                overall_success = False; break
            time.sleep(0.01) 
        
        if not overall_success or total_commands_processed_in_driver >= max_total_commands : break

        sut_all_output_for_this_cycle = []
        if verbose: print(f"DRIVER: Collecting SUT output for cycle {current_cycle_num} (timeout: {SUT_OUTPUT_COLLECTION_TIMEOUT}s)...")
        
        collection_start_time = time.monotonic()
        while time.monotonic() - collection_start_time < SUT_OUTPUT_COLLECTION_TIMEOUT:
            try:
                line = stdout_q.get(timeout=SUT_OUTPUT_COLLECTION_POLL_INTERVAL)
                sut_all_output_for_this_cycle.append(line)
                if verbose: print(f"SUT -> DRIVER (Cycle Output): {line}")
                collection_start_time = time.monotonic() 
            except queue.Empty:
                if process.poll() is not None: 
                    print("SUT process terminated during output collection.")
                    overall_success = False; break
                pass 
        if not overall_success: break

        if verbose: print(f"DRIVER: Collected {len(sut_all_output_for_this_cycle)} lines from SUT for cycle {current_cycle_num}.")

        cycle_check_result = check_cycle( # Assumes check_cycle is imported from checker.py
            cycle_commands_to_send,
            sut_all_output_for_this_cycle,
            python_library_model
        )

        if not cycle_check_result["is_legal"]:
            print(f"Cycle Validation FAILED (Cycle {current_cycle_num}):")
            print(f"  Reason: {cycle_check_result['error_message']}")
            if cycle_check_result.get("first_failing_command"):
                print(f"  First failing command context: {cycle_check_result['first_failing_command']}")
            overall_success = False
            break 
        else:
            if verbose: print(f"Cycle {current_cycle_num} OK.")

        while not stderr_q.empty():
            try:
                err_line = stderr_q.get_nowait()
                print(f"SUT STDERR (End of Cycle {current_cycle_num}): {err_line}")
            except queue.Empty: break
        
        if not overall_success: break

    print("\n--- Interaction Loop Finished ---")
    sut_exit_code = process.poll()
    if sut_exit_code is None: 
        print("Terminating SUT process...")
        try:
            if process.stdin and not process.stdin.closed:
                 process.stdin.close() 
        except Exception as e_close:
            if verbose: print(f"Note: Error closing SUT stdin: {e_close}")
        
        process.terminate() 
        try:
            sut_exit_code = process.wait(timeout=1.0) 
            if verbose: print(f"SUT terminated with exit code: {sut_exit_code}")
        except subprocess.TimeoutExpired:
            if verbose: print("SUT did not terminate gracefully, killing.")
            process.kill() 
            sut_exit_code = process.wait(timeout=0.5)
            if verbose: print(f"SUT killed, exit code: {sut_exit_code}")
        except Exception as e_term:
             if verbose: print(f"Exception during SUT termination: {e_term}")

    def drain_queue(q, q_name):
        count = 0
        while not q.empty():
            try:
                print(f"SUT {q_name} (remaining): {q.get_nowait()}")
                count+=1
            except queue.Empty: break
        if verbose and count > 0: print(f"Drained {count} lines from {q_name}.")

    drain_queue(stdout_q, "STDOUT")
    drain_queue(stderr_q, "STDERR")

    if stdout_thread.is_alive(): stdout_thread.join(timeout=0.5)
    if stderr_thread.is_alive(): stderr_thread.join(timeout=0.5)

    if overall_success:
        print("\n+++ Driver finished (Batch Mode): All checked cycles were valid. +++")
        return True
    else:
        print("\n--- Driver finished (Batch Mode): Errors encountered. ---")
        return False

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run interactive test driver for LibrarySystem (Batch Mode).")
    parser.add_argument("jar_path", help="Path to the student's JAR file.")
    parser.add_argument("--max_cycles", type=int, default=DEFAULT_MAX_CYCLES, help="Maximum number of OPEN/CLOSE cycles.")
    parser.add_argument("--max_total_commands", type=int, default=DEFAULT_MAX_TOTAL_COMMANDS, help="Maximum total commands to send.")
    
    # Generation parameters
    parser.add_argument("--min_skip", type=int, default=DEFAULT_MIN_DAYS_TO_SKIP, help="Min days to skip between CLOSE and next OPEN for generator.")
    parser.add_argument("--max_skip", type=int, default=DEFAULT_MAX_DAYS_TO_SKIP, help="Max days to skip for generator.")
    parser.add_argument("--min_req", type=int, default=DEFAULT_MIN_REQUESTS_PER_DAY, help="Min requests per day for generator.")
    parser.add_argument("--max_req", type=int, default=DEFAULT_MAX_REQUESTS_PER_DAY, help="Max requests per day for generator.")
    
    # Command type weights
    parser.add_argument("--b_weight", type=int, default=DEFAULT_BORROW_WEIGHT, help="Borrow weight for generator.")
    parser.add_argument("--o_weight", type=int, default=DEFAULT_ORDER_WEIGHT, help="Successful/Valid Order attempt weight for generator.")
    parser.add_argument("--q_weight", type=int, default=DEFAULT_QUERY_WEIGHT, help="Query weight for generator.")
    parser.add_argument("--failed_o_weight", type=int, default=DEFAULT_FAILED_ORDER_WEIGHT, help="Weight for generating 'expected-to-fail' order attempts (e.g., student already has pending order).")
    parser.add_argument("--new_s_ratio", type=float, default=DEFAULT_NEW_STUDENT_RATIO, help="New student ratio for generator.")
    
    # Initial library setup
    parser.add_argument("--init_types", type=int, default=INITIAL_BOOK_TYPES, help="Number of initial book ISBNs.")
    parser.add_argument("--init_min_cp", type=int, default=INITIAL_BOOKS_MIN_COPIES, help="Min copies per initial ISBN.")
    parser.add_argument("--init_max_cp", type=int, default=INITIAL_BOOKS_MAX_COPIES, help="Max copies per initial ISBN.")
    
    # Simulation start date
    parser.add_argument("--start_year", type=int, default=2025, help="Start year for simulation.")
    parser.add_argument("--start_month", type=int, default=1, help="Start month.")
    parser.add_argument("--start_day", type=int, default=1, help="Start day.")
    
    parser.add_argument("--sut_immediate_print", action=argparse.BooleanOptionalAction, default=True, 
                        help="Set if SUT prints user op results immediately. (Note: Current driver does not pass this to checker). Default: True.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output.")

    args = parser.parse_args()

    success = run_driver(
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
        failed_order_weight=args.failed_o_weight, # Pass the new argument
        new_student_ratio=args.new_s_ratio,
        initial_book_types_count=args.init_types,
        initial_min_copies=args.init_min_cp,
        initial_max_copies=args.init_max_cp,
        start_year=args.start_year,
        start_month=args.start_month,
        start_day=args.start_day,
        sut_prints_user_ops_immediately=args.sut_immediate_print,
        seed=args.seed,
        verbose=args.verbose
    )

    if success:
        print("Driver run successful.")
        exit(0)
    else:
        print("Driver run failed.")
        exit(1)
