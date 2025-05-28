# gen.py
import random
from datetime import date, timedelta
from typing import List, Tuple, Optional, Callable, Dict, Set
import json
import sys
try:
    # We assume state.py (and its Student, BookCopy, LibrarySystem classes)
    # is available and has the 'has_generated_restore_for_current_read' flag in Student.
    from state import LibrarySystem, Student, BookCopy
except ImportError as e:
    # Fallback basic mock for gen.py if state.py is not found
    # This mock needs to be updated to include the new flag for testing gen.py standalone
    print(f"Critical Driver Error: Could not import required modules (state, gen, checker): {e}")
    try:
        print(json.dumps({"status": "failure", "reason": f"Critical import error: {e}"}))
    except Exception:
        pass
    sys.exit(1)


STUDENT_IDS_POOL = [f"2337{i:04d}" for i in range(1, 75)]

# --- Helper functions (mostly unchanged, ensure they use the new flag if relevant) ---
def _get_random_student_id(library_system: LibrarySystem, existing_student_preference_ratio=0.9) -> str:
    if library_system.students and random.random() < existing_student_preference_ratio:
        # Ensure student objects are created if chosen from keys, though _get_student handles this.
        return random.choice(list(library_system.students.keys()))
    return random.choice(STUDENT_IDS_POOL)

def _get_all_existing_book_copy_ids(library_system: LibrarySystem) -> List[str]:
    return list(library_system.all_book_copies.keys())

def _get_all_existing_isbns(library_system: LibrarySystem) -> List[str]:
    isbns = set()
    for book_copy_obj_val in library_system.all_book_copies.values(): # Renamed var
        isbns.add(book_copy_obj_val.isbn) # type: ignore
    return list(isbns) if isbns else []

def _get_all_isbns_on_shelf(library_system: LibrarySystem) -> List[str]:
    isbns_on_shelf = set()
    for isbn, book_copy_ids in library_system.books_on_shelf_by_isbn.items():
        if book_copy_ids:
            isbns_on_shelf.add(isbn)
    return list(isbns_on_shelf)

def _can_student_borrow_isbn(student: Student, isbn: str, book_type: str, library_system: LibrarySystem) -> bool:
    if book_type == 'A': return False
    if book_type == 'B' and student.held_b_book_copy_id is not None: return False
    if book_type == 'C' and isbn in student.held_c_books_by_isbn: return False
    if not library_system.books_on_shelf_by_isbn.get(isbn): return False
    return True

def _can_student_order_isbn(student: Student, isbn: str, book_type: str) -> bool:
    if book_type == 'A': return False
    if student.pending_order_isbn is not None or student.reserved_book_copy_id_at_ao is not None: return False
    if book_type == 'B' and student.held_b_book_copy_id is not None: return False
    if book_type == 'C' and isbn in student.held_c_books_by_isbn: return False
    return True

def _can_student_pick_isbn(student: Student, isbn_to_pick: str, library_system: LibrarySystem) -> bool:
    if not student.reserved_book_copy_id_at_ao: return False
    reserved_book_copy_obj = library_system.all_book_copies.get(student.reserved_book_copy_id_at_ao) # type: ignore
    if not reserved_book_copy_obj or \
       reserved_book_copy_obj.isbn != isbn_to_pick or \
       reserved_book_copy_obj.current_location != "appointment_office" or \
       reserved_book_copy_obj.ao_reserved_for_student_id != student.id: # type: ignore
        return False
    if library_system.current_date_obj and student.pickup_deadline_for_reserved_book and \
       library_system.current_date_obj > student.pickup_deadline_for_reserved_book:
        return False
    book_type_to_pick = reserved_book_copy_obj.type # type: ignore
    if book_type_to_pick == 'B' and student.held_b_book_copy_id is not None: return False
    if book_type_to_pick == 'C' and isbn_to_pick in student.held_c_books_by_isbn: return False
    return True

def _format_date_for_command(date_obj: date) -> str:
    return date_obj.strftime("%Y-%m-%d")

def _select_isbn_with_type_priority(
    candidate_isbns: List[str],
    library_system: LibrarySystem,
    a_prio: float, b_prio: float, c_prio: float
) -> Optional[str]:
    if not candidate_isbns: return None
    a_isbns = [i for i in candidate_isbns if library_system._get_book_type_from_id_or_isbn(i) == 'A']
    b_isbns = [i for i in candidate_isbns if library_system._get_book_type_from_id_or_isbn(i) == 'B']
    c_isbns = [i for i in candidate_isbns if library_system._get_book_type_from_id_or_isbn(i) == 'C']
    total_prio = a_prio + b_prio + c_prio
    if total_prio <= 0: return random.choice(candidate_isbns) if candidate_isbns else None
    rand_val = random.random() * total_prio
    if rand_val < a_prio and a_isbns: return random.choice(a_isbns)
    rand_val -= a_prio
    if rand_val < b_prio and b_isbns: return random.choice(b_isbns)
    rand_val -= b_prio
    # Ensure c_prio is positive before checking c_isbns with it
    if c_prio > 0 and rand_val < c_prio and c_isbns: return random.choice(c_isbns)
    # Fallback logic
    if a_prio > 0 and a_isbns: return random.choice(a_isbns)
    if b_prio > 0 and b_isbns: return random.choice(b_isbns)
    if c_prio > 0 and c_isbns: return random.choice(c_isbns)
    all_available_isbns = a_isbns + b_isbns + c_isbns
    if all_available_isbns: return random.choice(all_available_isbns)
    return random.choice(candidate_isbns) if candidate_isbns else None


def generate_requests_for_one_day(
    library_system: LibrarySystem, # This is the python_library_model from driver.py
    num_user_requests: int,
    current_date_str: str, # Needed for command formatting and for _gen_restore to pass to apply
    borrow_weight: int, order_weight: int, query_weight: int, pick_weight: int,
    failed_order_weight: int, read_weight: int, restore_weight: int,
    new_student_ratio: float, student_return_propensity: float,
    student_pick_propensity: float, student_restore_propensity: float,
    b_book_priority: float, c_book_priority: float, a_book_read_priority: float
) -> List[str]:
    all_book_copy_ids = _get_all_existing_book_copy_ids(library_system)
    all_isbns_in_library = _get_all_existing_isbns(library_system)
    # isbns_on_shelf = _get_all_isbns_on_shelf(library_system) # Not directly used here, but helpers might

    if num_user_requests <= 0: return []

    opportunistic_commands = []
    if random.random() < student_return_propensity:
        students_with_borrowed_books = []
        for student_id, student_obj in library_system.students.items():
            if student_obj.held_b_book_copy_id: students_with_borrowed_books.append((student_id, student_obj.held_b_book_copy_id))
            for _, book_id in student_obj.held_c_books_by_isbn.items(): students_with_borrowed_books.append((student_id, book_id))
        if students_with_borrowed_books:
            s_id, b_id_to_return = random.choice(students_with_borrowed_books)
            opportunistic_commands.append(f"[{current_date_str}] {s_id} returned {b_id_to_return}")

    if random.random() < student_pick_propensity and pick_weight > 0 :
        eligible_pick_candidates = []
        student_ids_shuffled = list(library_system.students.keys())
        random.shuffle(student_ids_shuffled)
        for student_id in student_ids_shuffled:
            student_obj = library_system._get_student(student_id) # Use getter
            if student_obj.reserved_book_copy_id_at_ao:
                # Assuming all_book_copies has actual BookCopy objects if state.py is used
                reserved_book_copy_obj = library_system.all_book_copies.get(student_obj.reserved_book_copy_id_at_ao) # type: ignore
                if reserved_book_copy_obj and _can_student_pick_isbn(student_obj, reserved_book_copy_obj.isbn, library_system): # type: ignore
                    eligible_pick_candidates.append((student_id, reserved_book_copy_obj.isbn)) # type: ignore
        if eligible_pick_candidates:
            s_id, isbn_pk = random.choice(eligible_pick_candidates)
            opportunistic_commands.append(f"[{current_date_str}] {s_id} picked {isbn_pk}")

    random.shuffle(opportunistic_commands)
    weighted_command_generators: List[Tuple[Callable[[], Optional[str]], int]] = []

    def _gen_borrow() -> Optional[str]:
        current_isbns_on_shelf = _get_all_isbns_on_shelf(library_system)
        if not current_isbns_on_shelf: return None
        s_id = _get_random_student_id(library_system, 1.0 - new_student_ratio)
        student_obj = library_system._get_student(s_id)
        borrowable_isbns = [
            isbn for isbn in current_isbns_on_shelf
            if _can_student_borrow_isbn(student_obj, isbn, library_system._get_book_type_from_id_or_isbn(isbn), library_system)
        ]
        if not borrowable_isbns: return None
        isbn_to_borrow = _select_isbn_with_type_priority(borrowable_isbns, library_system, 0, b_book_priority, c_book_priority)
        return f"[{current_date_str}] {s_id} borrowed {isbn_to_borrow}" if isbn_to_borrow else None
    if borrow_weight > 0: weighted_command_generators.append((_gen_borrow, borrow_weight))

    def _gen_successful_order() -> Optional[str]:
        if not all_isbns_in_library: return None
        s_id = _get_random_student_id(library_system, 1.0 - new_student_ratio)
        student_obj = library_system._get_student(s_id)
        orderable_isbns = [
            isbn for isbn in all_isbns_in_library
            if _can_student_order_isbn(student_obj, isbn, library_system._get_book_type_from_id_or_isbn(isbn))
        ]
        if not orderable_isbns: return None
        isbn_to_order = _select_isbn_with_type_priority(orderable_isbns, library_system, 0, b_book_priority, c_book_priority)
        return f"[{current_date_str}] {s_id} ordered {isbn_to_order}" if isbn_to_order else None
    if order_weight > 0: weighted_command_generators.append((_gen_successful_order, order_weight))

    def _gen_query() -> Optional[str]:
        if not all_book_copy_ids: return None
        queried_book_id = random.choice(all_book_copy_ids)
        # No need to check if book is held for query, as per problem, query any book
        s_id = _get_random_student_id(library_system, 0.5)
        return f"[{current_date_str}] {s_id} queried {queried_book_id}"
    if query_weight > 0: weighted_command_generators.append((_gen_query, query_weight))

    def _gen_failed_order_attempt() -> Optional[str]:
        if not all_isbns_in_library: return None
        student_id_to_test = _get_random_student_id(library_system, 0.95)
        student_obj = library_system._get_student(student_id_to_test)
        a_isbns = [i for i in all_isbns_in_library if library_system._get_book_type_from_id_or_isbn(i) == 'A']
        if a_isbns and random.random() < 0.3: return f"[{current_date_str}] {student_id_to_test} ordered {random.choice(a_isbns)}"
        if (student_obj.pending_order_isbn or student_obj.reserved_book_copy_id_at_ao) and random.random() < 0.5:
            isbn_to_try = random.choice(all_isbns_in_library)
            return f"[{current_date_str}] {student_id_to_test} ordered {isbn_to_try}"
        if student_obj.held_b_book_copy_id and random.random() < 0.5:
            b_isbns_for_fail = [i for i in all_isbns_in_library if library_system._get_book_type_from_id_or_isbn(i) == 'B']
            if b_isbns_for_fail: return f"[{current_date_str}] {student_id_to_test} ordered {random.choice(b_isbns_for_fail)}"
        if student_obj.held_c_books_by_isbn and random.random() < 0.5:
            held_c_isbns = list(student_obj.held_c_books_by_isbn.keys())
            if held_c_isbns: return f"[{current_date_str}] {student_id_to_test} ordered {random.choice(held_c_isbns)}"
        return None
    if failed_order_weight > 0: weighted_command_generators.append((_gen_failed_order_attempt, failed_order_weight))

    def _gen_read() -> Optional[str]:
        current_isbns_on_shelf = _get_all_isbns_on_shelf(library_system)
        if not current_isbns_on_shelf: return None

        eligible_students_for_read = []
        # Consider all students in the system and potentially new ones from the pool
        potential_student_ids = list(library_system.students.keys()) + STUDENT_IDS_POOL
        random.shuffle(potential_student_ids)

        s_id_to_read = None
        for potential_s_id in potential_student_ids:
            student_obj = library_system._get_student(potential_s_id) # Ensures student exists
            if student_obj.reading_book_copy_id_today is None or student_obj.reading_book_copy_id_today == "":
                s_id_to_read = potential_s_id
                break
        
        if not s_id_to_read: return None # No student available to read

        isbn_to_read = _select_isbn_with_type_priority(
            current_isbns_on_shelf, library_system,
            a_book_read_priority, b_book_priority, c_book_priority # A can be read
        )
        if isbn_to_read:
            # Gen.py does NOT update library_system state here for 'read'.
            # That happens in driver via checker AFTER SUT accepts the read.
            # The apply_validated_read_action in state.py will reset the restore flag.
            return f"[{current_date_str}] {s_id_to_read} read {isbn_to_read}"
        return None
    if read_weight > 0: weighted_command_generators.append((_gen_read, read_weight))

    def _gen_restore() -> Optional[str]:
        if not (random.random() < student_restore_propensity):
            return None

        candidates_for_restore = []
        # Iterate over a shuffled list of student IDs to avoid bias if multiple are eligible
        student_ids_to_check = list(library_system.students.keys())
        random.shuffle(student_ids_to_check)

        for student_id in student_ids_to_check:
            student_obj = library_system._get_student(student_id) # Use getter
            # CRUCIAL CHECK: Only if reading AND restore not yet generated for this read
            if student_obj.reading_book_copy_id_today and \
               student_obj.reading_book_copy_id_today != "" and \
               not student_obj.has_generated_restore_for_current_read: # Use the new flag
                candidates_for_restore.append((student_id, student_obj.reading_book_copy_id_today))
        
        if not candidates_for_restore:
            return None

        s_id_to_restore, book_id_to_restore = random.choice(candidates_for_restore)
        
        # --- MODIFICATION POINT FOR GEN.PY ---
        # Gen.py is ONLY allowed to set this flag.
        student_to_update_flag = library_system._get_student(s_id_to_restore)
        student_to_update_flag.has_generated_restore_for_current_read = True
        # --- END MODIFICATION POINT ---
        
        return f"[{current_date_str}] {s_id_to_restore} restored {book_id_to_restore}"
    if restore_weight > 0: weighted_command_generators.append((_gen_restore, restore_weight))

    final_commands_for_day = []
    max_opportunistic = min(len(opportunistic_commands), max(0, num_user_requests // 3), 3)
    final_commands_for_day.extend(opportunistic_commands[:max_opportunistic])
    remaining_slots = num_user_requests - len(final_commands_for_day)

    if remaining_slots > 0 and weighted_command_generators:
        flat_generators: List[Callable[[], Optional[str]]] = []
        for gen_func, weight in weighted_command_generators:
            flat_generators.extend([gen_func] * weight)
        if not flat_generators: return final_commands_for_day # Should not happen if weights > 0

        attempts_for_weighted = 0
        # Increased max_attempts to allow more chances if many gens return None
        max_attempts_for_weighted = remaining_slots * 10 + len(flat_generators)
        generated_command_types_today: Set[str] = set()

        while len(final_commands_for_day) < num_user_requests and attempts_for_weighted < max_attempts_for_weighted:
            gen_func_choice = random.choice(flat_generators)
            command_str = gen_func_choice() # This now might set the restore flag inside _gen_restore
            attempts_for_weighted += 1
            if command_str:
                # Parse command type for diversity check
                # Example: "[DATE] S_ID OP ARGS" -> parts[1] is S_ID, parts[2] is OP
                cmd_parts = command_str.split()
                # Check if there are enough parts to determine command type
                actual_cmd_type = "UNKNOWN"
                if len(cmd_parts) > 2 : # e.g. [DATE] S_ID OP ...
                    actual_cmd_type = cmd_parts[2]
                elif len(cmd_parts) == 2: # e.g. [DATE] OPEN/CLOSE
                    actual_cmd_type = cmd_parts[1]

                if remaining_slots < 3 and actual_cmd_type in generated_command_types_today and random.random() < 0.5:
                    continue
                final_commands_for_day.append(command_str)
                if actual_cmd_type != "UNKNOWN":
                    generated_command_types_today.add(actual_cmd_type)
    
    random.shuffle(final_commands_for_day)
    return final_commands_for_day[:num_user_requests]


def generate_command_cycle(
    library_system: LibrarySystem, # This is the python_library_model from driver.py
    current_system_date: date,
    is_library_logically_closed: bool, # Passed by driver
    num_requests_in_batch: int,      # Target user requests for this batch (day/multi-day)
    close_probability: float,        # Probability gen will decide to CLOSE this batch
    min_skip_days_post_close: int,
    max_skip_days_post_close: int,
    # Weights and propensities for generate_requests_for_one_day
    borrow_weight: int, order_weight: int, query_weight: int, pick_weight: int,
    failed_order_weight: int, read_weight: int, restore_weight: int,
    new_student_ratio: float, student_return_propensity: float,
    student_pick_propensity: float, student_restore_propensity: float,
    b_book_priority: float, c_book_priority: float, a_book_read_priority: float
) -> Tuple[List[str], date, bool]:
    """
    Generates a cycle of commands: [OPEN if needed] + user_requests + [CLOSE if decided by close_probability].
    Relies on library_system (python_library_model) for state, but only modifies the
    Student.has_generated_restore_for_current_read flag within _gen_restore.
    Returns: (commands_list, next_date_for_ops, system_closed_after_this_cycle)
    """
    commands_this_cycle: List[str] = []
    date_for_ops = current_system_date
    # This reflects the state *after* this function's generated commands are hypothetically applied.
    system_closed_after_this_cycle = is_library_logically_closed
    next_date_for_ops = current_system_date

    # The library_system passed here is python_library_model from driver.py.
    # Its state (student.reading_book_copy_id_today, student.has_generated_restore_for_current_read)
    # should reflect updates from checker.py after previous SUT interactions.

    if is_library_logically_closed:
        date_str_for_open = _format_date_for_command(date_for_ops)
        commands_this_cycle.append(f"[{date_str_for_open}] OPEN")
        # Gen.py does NOT call library_system.apply_open_action().
        # Driver.py handles that through checker.py after SUT output.
        # For gen's internal logic for THIS batch, we assume OPEN just happened.
        # The key is that state.py's apply_open_action (called by checker)
        # will reset reading_book_copy_id_today and has_generated_restore_for_current_read.
        system_closed_after_this_cycle = False # It will be open after this OPEN command
    # else: library is already open, continue generating for the same day 'date_for_ops'

    if not system_closed_after_this_cycle and num_requests_in_batch > 0:
        date_str_for_requests = _format_date_for_command(date_for_ops)
        # generate_requests_for_one_day will use library_system to make decisions
        # and _gen_restore within it will set the has_generated_restore_for_current_read flag.
        user_requests = generate_requests_for_one_day(
            library_system, # python_library_model
            num_requests_in_batch,
            date_str_for_requests, # Pass current_date_str
            borrow_weight, order_weight, query_weight, pick_weight,
            failed_order_weight, read_weight, restore_weight,
            new_student_ratio, student_return_propensity,
            student_pick_propensity, student_restore_propensity,
            b_book_priority, c_book_priority, a_book_read_priority
        )
        commands_this_cycle.extend(user_requests)

    # Decide if this batch/day ends with a CLOSE
    if not system_closed_after_this_cycle and random.random() < close_probability:
        date_str_for_close = _format_date_for_command(date_for_ops)
        commands_this_cycle.append(f"[{date_str_for_close}] CLOSE")
        system_closed_after_this_cycle = True
        # If closed, determine next date for operations (after skipping some days)
        days_to_skip = random.randint(min_skip_days_post_close, max_skip_days_post_close)
        next_date_for_ops = date_for_ops + timedelta(days=1 + days_to_skip)
        # Gen.py does NOT call library_system.apply_close_action().
    elif not system_closed_after_this_cycle:
        # No CLOSE generated in this batch, so operations continue on the same day
        # if driver calls again with is_library_logically_closed = False for this date.
        next_date_for_ops = date_for_ops
    # If it was already closed and no OPEN happened (e.g. num_requests_in_batch was 0),
    # next_date_for_ops remains current_system_date, system_closed_after_this_cycle remains True.

    return (commands_this_cycle, next_date_for_ops, system_closed_after_this_cycle)


# --- Main execution for testing gen.py standalone (Optional) ---
if __name__ == '__main__':
    print("--- Mock Test for gen.py (using new restore flag logic) ---")

    # Using the fallback mock LibrarySystem defined in this file for standalone test
    mock_lib_sys_gen = LibrarySystem() # Fallback mock from gen.py

    # Setup initial state for the mock
    mock_lib_sys_gen.initialize_books(["A-0001 2", "B-0001 1", "C-0001 1"]) # Minimal books

    # Simulate a student reading a book
    test_student_id = "23370001"
    test_book_id_read = "B-0001-01" # Assume this is a valid book ID
    
    # Manually set up the mock student and book for testing _gen_restore
    # This simulates what checker.py would do to python_library_model after a successful read
    _ = mock_lib_sys_gen._get_student(test_student_id) # Ensure student exists
    # In a real scenario, state.py's apply_validated_read_action would do this:
    mock_lib_sys_gen.students[test_student_id].reading_book_copy_id_today = test_book_id_read
    mock_lib_sys_gen.students[test_student_id].has_generated_restore_for_current_read = False


    print(f"Initial state for student {test_student_id}: reading='{mock_lib_sys_gen.students[test_student_id].reading_book_copy_id_today}', restore_flag='{mock_lib_sys_gen.students[test_student_id].has_generated_restore_for_current_read}'")

    # Test generate_requests_for_one_day focusing on restore
    # High restore weight and propensity to trigger it
    # `current_date_str` needs to be set for command generation
    mock_lib_sys_gen.current_date_str = "2025-01-01" # Set a current date for the mock system
    
    print("\nGenerating requests (attempt 1 for restore):")
    day_commands1 = generate_requests_for_one_day(
        mock_lib_sys_gen, num_user_requests=5, current_date_str="2025-01-01",
        borrow_weight=0, order_weight=0, query_weight=0, pick_weight=0,
        failed_order_weight=0, read_weight=0, restore_weight=10, # High restore weight
        new_student_ratio=0, student_return_propensity=0,
        student_pick_propensity=0, student_restore_propensity=1.0, # High propensity
        b_book_priority=1, c_book_priority=1, a_book_read_priority=1
    )
    print("Generated commands (1st attempt):")
    for cmd in day_commands1: print(cmd)
    print(f"State after 1st gen for student {test_student_id}: reading='{mock_lib_sys_gen.students[test_student_id].reading_book_copy_id_today}', restore_flag='{mock_lib_sys_gen.students[test_student_id].has_generated_restore_for_current_read}'")

    print("\nGenerating requests (attempt 2 for restore - should not generate another restore for same book):")
    day_commands2 = generate_requests_for_one_day(
        mock_lib_sys_gen, num_user_requests=5, current_date_str="2025-01-01",
        borrow_weight=0, order_weight=0, query_weight=0, pick_weight=0,
        failed_order_weight=0, read_weight=0, restore_weight=10,
        new_student_ratio=0, student_return_propensity=0,
        student_pick_propensity=0, student_restore_propensity=1.0,
        b_book_priority=1, c_book_priority=1, a_book_read_priority=1
    )
    print("Generated commands (2nd attempt):")
    for cmd in day_commands2: print(cmd)
    print(f"State after 2nd gen for student {test_student_id}: reading='{mock_lib_sys_gen.students[test_student_id].reading_book_copy_id_today}', restore_flag='{mock_lib_sys_gen.students[test_student_id].has_generated_restore_for_current_read}'")

    # Test generate_command_cycle
    print("\n--- Testing generate_command_cycle ---")
    mock_lib_sys_cycle_test = LibrarySystem() # Fresh mock for cycle test
    mock_lib_sys_cycle_test.initialize_books(["B-0002 1"])
    
    # Simulate student reading B-0002-01
    # In driver, this state would be set by checker after SUT confirms a read.
    # For gen.py standalone test, we set it up.
    student_cycle = mock_lib_sys_cycle_test._get_student("S9999")
    student_cycle.reading_book_copy_id_today = "B-0002-01"
    student_cycle.has_generated_restore_for_current_read = False


    sim_date = date(2025, 2, 1)
    is_closed = False # Start as open for this test
    
    print(f"Before cycle: Date={sim_date}, IsClosed={is_closed}, Student S9999 reading='{student_cycle.reading_book_copy_id_today}', restore_flag='{student_cycle.has_generated_restore_for_current_read}'")

    cycle_cmds, next_d, closed_after = generate_command_cycle(
        mock_lib_sys_cycle_test, sim_date, is_closed,
        num_requests_in_batch=3, close_probability=1.0, # Force close
        min_skip_days_post_close=1, max_skip_days_post_close=1,
        borrow_weight=0, order_weight=0, query_weight=1, pick_weight=0,
        failed_order_weight=0, read_weight=0, restore_weight=5, # Try to get a restore
        new_student_ratio=0.1, student_return_propensity=0.1,
        student_pick_propensity=0.1, student_restore_propensity=1.0,
        b_book_priority=1, c_book_priority=1, a_book_read_priority=0.1
    )
    print("Generated cycle commands:")
    for cmd_str in cycle_cmds: print(cmd_str)
    print(f"After cycle: NextDate={next_d}, ClosedAfter={closed_after}, Student S9999 reading='{student_cycle.reading_book_copy_id_today}', restore_flag='{student_cycle.has_generated_restore_for_current_read}' (Note: reading_book_copy_id_today is not cleared by gen.py itself)")

    print("--- Test Complete ---")