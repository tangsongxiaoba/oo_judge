# gen.py
import random
from datetime import date, timedelta

from state import LibrarySystem, Student, BookCopy # Assuming state.py is accessible

STUDENT_IDS_POOL = [f"2337{i:04d}" for i in range(1, 75)] 

# --- Helper functions ---
def _get_random_student_id(library_system: LibrarySystem, existing_student_preference_ratio=0.8) -> str:
    if library_system.students and random.random() < existing_student_preference_ratio:
        return random.choice(list(library_system.students.keys()))
    return random.choice(STUDENT_IDS_POOL)

def _get_all_existing_book_ids(library_system: LibrarySystem) -> list[str]:
    return list(library_system.all_book_copies.keys())

def _get_all_existing_isbns(library_system: LibrarySystem) -> list[str]:
    isbns = set()
    for book_copy in library_system.all_book_copies.values():
        isbns.add(book_copy.isbn)
    return list(isbns) if isbns else []

def _can_student_borrow_isbn(student: Student, isbn: str, book_type: str, library_system: LibrarySystem) -> bool:
    if book_type == 'A': return False
    if book_type == 'B' and student.held_b_book_copy_id is not None: return False
    if book_type == 'C' and isbn in student.held_c_books_by_isbn: return False
    if not library_system.books_on_shelf_by_isbn.get(isbn): return False
    if not any(b_id for b_id in library_system.books_on_shelf_by_isbn.get(isbn, []) 
               if library_system.all_book_copies[b_id].current_location == "bookshelf"):
        return False
    return True

def _can_student_order_isbn(student: Student, isbn: str, book_type: str) -> bool:
    if book_type == 'A': return False
    if student.pending_order_isbn is not None or student.reserved_book_copy_id_at_ao is not None: return False
    if book_type == 'B' and student.held_b_book_copy_id is not None: return False
    if book_type == 'C' and isbn in student.held_c_books_by_isbn: return False
    return True

def _can_student_pick_isbn(student: Student, isbn_to_pick: str, library_system: LibrarySystem) -> bool:
    if not student.reserved_book_copy_id_at_ao: return False
    reserved_book_copy = library_system.all_book_copies.get(student.reserved_book_copy_id_at_ao)
    if not reserved_book_copy or \
       reserved_book_copy.isbn != isbn_to_pick or \
       reserved_book_copy.current_location != "appointment_office" or \
       reserved_book_copy.ao_reserved_for_student_id != student.id:
        return False
    if library_system.current_date_obj and student.pickup_deadline_for_reserved_book and \
       library_system.current_date_obj > student.pickup_deadline_for_reserved_book:
        return False
    book_type_to_pick = reserved_book_copy.type
    if book_type_to_pick == 'B' and student.held_b_book_copy_id is not None: return False
    if book_type_to_pick == 'C' and isbn_to_pick in student.held_c_books_by_isbn: return False
    return True

def _format_date_for_command(date_obj: date) -> str:
    return date_obj.strftime("%Y-%m-%d")

# --- New helper function for generating failed order attempts ---
def _gen_failed_order_attempt(library_system: LibrarySystem, current_date_str: str) -> str | None:
    """
    Tries to generate an 'ordered' command that is expected to fail because
    the student already has a pending or reserved order.
    """
    students_with_active_orders = [
        s_id for s_id, s_obj in library_system.students.items() 
        if s_obj.pending_order_isbn is not None or s_obj.reserved_book_copy_id_at_ao is not None
    ]

    if not students_with_active_orders:
        return None # No student has an active order to test against

    student_id_to_test = random.choice(students_with_active_orders)
    student_obj = library_system._get_student(student_id_to_test) # Get the student object

    all_isbns_available = _get_all_existing_isbns(library_system)
    if not all_isbns_available:
        return None # No books in the library to attempt ordering

    # Try to pick an ISBN that is NOT the student's current pending/reserved one, and not type 'A'
    # If student has pending_order_isbn, use that; otherwise, they must have reserved_book_copy_id_at_ao
    current_order_isbn = student_obj.pending_order_isbn
    if not current_order_isbn and student_obj.reserved_book_copy_id_at_ao:
        reserved_book = library_system._get_book_copy(student_obj.reserved_book_copy_id_at_ao)
        if reserved_book:
            current_order_isbn = reserved_book.isbn
            
    candidate_isbns_for_failed_order = [
        isbn for isbn in all_isbns_available
        if library_system._get_book_type_from_id_or_isbn(isbn) != 'A' and \
           (current_order_isbn is None or isbn != current_order_isbn) # Ensure it's a *different* book
    ]

    if not candidate_isbns_for_failed_order:
        # As a fallback, try to order any Type A book, which should also fail if student has pending order.
        # Or if no other books, try re-ordering their current one (though less interesting for this specific scenario)
        type_a_isbns = [isbn for isbn in all_isbns_available if library_system._get_book_type_from_id_or_isbn(isbn) == 'A']
        if type_a_isbns:
            isbn_to_try = random.choice(type_a_isbns)
            return f"[{current_date_str}] {student_id_to_test} ordered {isbn_to_try}"
        elif current_order_isbn : # Fallback to re-ordering current if no other option
             return f"[{current_date_str}] {student_id_to_test} ordered {current_order_isbn}"
        return None # Cannot find a suitable ISBN to attempt a failed order

    isbn_to_try_failed_order = random.choice(candidate_isbns_for_failed_order)
    return f"[{current_date_str}] {student_id_to_test} ordered {isbn_to_try_failed_order}"


def gen_day_commands(library_system: LibrarySystem,
                     num_user_requests: int,
                     current_date_str: str, 
                     borrow_weight: int = 3,
                     order_weight: int = 2, # For successful orders
                     query_weight: int = 5,
                     failed_order_weight: int = 0, # New: for expected-to-fail orders
                     new_student_ratio: float = 0.1
                    ) -> list[str]:
    generated_commands = []
    
    all_book_ids = _get_all_existing_book_ids(library_system)
    all_isbns = _get_all_existing_isbns(library_system)

    if not all_book_ids and not all_isbns: return []

    potential_return_command_str = None
    students_with_books_to_return = []
    for student_id, student_obj in library_system.students.items():
        if student_obj.held_b_book_copy_id:
            students_with_books_to_return.append((student_id, student_obj.held_b_book_copy_id))
        for _, book_id in student_obj.held_c_books_by_isbn.items():
            students_with_books_to_return.append((student_id, book_id))
    if students_with_books_to_return:
        s_id, b_id = random.choice(students_with_books_to_return)
        potential_return_command_str = f"[{current_date_str}] {s_id} returned {b_id}"

    potential_pick_command_str = None
    students_who_can_pick_isbns = []
    for student_id, student_obj in library_system.students.items():
        if student_obj.reserved_book_copy_id_at_ao:
            reserved_book = library_system.all_book_copies.get(student_obj.reserved_book_copy_id_at_ao)
            if reserved_book and _can_student_pick_isbn(student_obj, reserved_book.isbn, library_system):
                 students_who_can_pick_isbns.append((student_id, reserved_book.isbn))
    if students_who_can_pick_isbns:
        s_id, isbn_pk = random.choice(students_who_can_pick_isbns)
        potential_pick_command_str = f"[{current_date_str}] {s_id} picked {isbn_pk}"

    other_command_generators_weighted = []

    # Generator for 'borrowed' (successful attempt)
    if all_isbns:
        def _gen_borrow():
            s_id_candidate = _get_random_student_id(library_system, 1.0 - new_student_ratio)
            student_obj = library_system._get_student(s_id_candidate)
            available_isbns_on_shelf_strict = [
                isbn for isbn, copies in library_system.books_on_shelf_by_isbn.items() 
                if copies and any(library_system.all_book_copies[b_id].current_location == "bookshelf" for b_id in copies)
            ]
            if not available_isbns_on_shelf_strict: return None
            for _ in range(min(5, len(available_isbns_on_shelf_strict))):
                isbn_candidate = random.choice(available_isbns_on_shelf_strict)
                book_type_candidate = library_system._get_book_type_from_id_or_isbn(isbn_candidate)
                if _can_student_borrow_isbn(student_obj, isbn_candidate, book_type_candidate, library_system):
                    return f"[{current_date_str}] {s_id_candidate} borrowed {isbn_candidate}"
            return None
        if borrow_weight > 0: other_command_generators_weighted.extend([_gen_borrow] * borrow_weight)

    # Generator for 'ordered' (successful attempt)
    if all_isbns:
        def _gen_successful_order(): 
            s_id_candidate = _get_random_student_id(library_system, 1.0 - new_student_ratio)
            student_obj = library_system._get_student(s_id_candidate)
            orderable_isbns = [isbn for isbn in all_isbns if library_system._get_book_type_from_id_or_isbn(isbn) != 'A']
            if not orderable_isbns: return None
            for _ in range(min(5, len(orderable_isbns))): # Try a few times to find a valid one
                isbn_candidate = random.choice(orderable_isbns)
                book_type_candidate = library_system._get_book_type_from_id_or_isbn(isbn_candidate)
                if _can_student_order_isbn(student_obj, isbn_candidate, book_type_candidate):
                    return f"[{current_date_str}] {s_id_candidate} ordered {isbn_candidate}"
            return None
        if order_weight > 0: other_command_generators_weighted.extend([_gen_successful_order] * order_weight)

    # Generator for 'queried'
    if all_book_ids:
        def _gen_query():
            queried_book_id = random.choice(all_book_ids)
            s_id = _get_random_student_id(library_system, 0.5) # Query can be by any student
            return f"[{current_date_str}] {s_id} queried {queried_book_id}"
        if query_weight > 0: other_command_generators_weighted.extend([_gen_query] * query_weight)

    # New: Generator for 'failed ordered attempt'
    if failed_order_weight > 0:
        def _gen_failed_order_wrapper(): # Wrapper to match signature if other generators need it
            return _gen_failed_order_attempt(library_system, current_date_str)
        other_command_generators_weighted.extend([_gen_failed_order_wrapper] * failed_order_weight)


    # Fill up the commands
    if potential_return_command_str and len(generated_commands) < num_user_requests:
        generated_commands.append(potential_return_command_str)
    
    if potential_pick_command_str and len(generated_commands) < num_user_requests:
        generated_commands.append(potential_pick_command_str)
        
    if not other_command_generators_weighted and len(generated_commands) < num_user_requests:
        return generated_commands 

    attempts_to_generate_other = 0
    # Give more chances if request count is high or generators often return None
    max_attempts_for_others = num_user_requests * 3 + len(other_command_generators_weighted) 

    while len(generated_commands) < num_user_requests and \
          other_command_generators_weighted and \
          attempts_to_generate_other < max_attempts_for_others:
        
        gen_func = random.choice(other_command_generators_weighted)
        command_str = gen_func()
        attempts_to_generate_other +=1
        
        if command_str:
            # Avoid too many exact duplicates unless request count is high or it's a specific test
            # For failed_order_attempt, duplicates might be less of an issue if testing robustness
            is_failed_order_attempt_type = (gen_func.__name__ == '_gen_failed_order_wrapper')

            if command_str not in generated_commands or \
               num_user_requests > 10 or \
               is_failed_order_attempt_type or \
               random.random() < 0.7: # Allow some repetition
                 generated_commands.append(command_str)

    random.shuffle(generated_commands)
    return generated_commands[:num_user_requests]


def gen_open_close_cycle_data(
    library_system: LibrarySystem,
    start_date_obj: date,
    min_days_to_skip: int = 0,    
    max_days_to_skip: int = 3,      
    min_requests_per_day: int = 0,
    max_requests_per_day: int = 10,
    borrow_weight: int = 3,
    order_weight: int = 2,      # For successful orders
    query_weight: int = 5,
    failed_order_weight: int = 0, # New parameter for expected-to-fail orders
    new_student_ratio: float = 0.1
) -> tuple[list[str], date]:
    cycle_commands = []
    current_date_str = _format_date_for_command(start_date_obj)

    original_ls_date_str = library_system.current_date_str
    original_ls_date_obj = library_system.current_date_obj
    
    library_system.current_date_str = current_date_str
    library_system.current_date_obj = start_date_obj

    cycle_commands.append(f"[{current_date_str}] OPEN")

    num_requests_today = random.randint(min_requests_per_day, max_requests_per_day)
    if num_requests_today > 0:
        day_user_requests = gen_day_commands(
            library_system,
            num_requests_today,
            current_date_str, 
            borrow_weight,
            order_weight, # successful order weight
            query_weight,
            failed_order_weight, # pass the new weight
            new_student_ratio
        )
        cycle_commands.extend(day_user_requests)

    cycle_commands.append(f"[{current_date_str}] CLOSE")

    library_system.current_date_str = original_ls_date_str
    library_system.current_date_obj = original_ls_date_obj

    days_to_skip = random.randint(min_days_to_skip, max_days_to_skip)
    next_cycle_start_date_obj = start_date_obj + timedelta(days=1 + days_to_skip) 

    return cycle_commands, next_cycle_start_date_obj


if __name__ == '__main__':
    print("--- Mock Test for gen_open_close_cycle_data (gen.py with failed_order_weight) ---")
    
    generator_library_model = LibrarySystem() 
    initial_book_data = [
        "B-0001 2", "C-0001 3", "A-0001 1", "B-0002 1", "C-0002 2", "C-0003 1"
    ]
    generator_library_model.initialize_books(initial_book_data)
    
    # Simulate student s1 having a pending order to test failed_order_attempt
    s1_id = "23370010"
    s1 = generator_library_model._get_student(s1_id)
    s1.pending_order_isbn = "C-0001" # s1 has a pending order for C-0001
    print(f"Initial gen model state: {s1_id} has pending order for {s1.pending_order_isbn}")

    current_test_start_date = date(2025, 1, 5) 
    next_date_for_cycle = current_test_start_date
    total_generated_commands = []

    for i in range(2): # Generate 2 cycles to see variety
        print(f"\n--- Generating Cycle {i+1} starting {next_date_for_cycle.isoformat()} ---")
        
        cycle_cmds, next_cycle_start_dt = gen_open_close_cycle_data(
            generator_library_model, 
            next_date_for_cycle,
            min_days_to_skip=0,    
            max_days_to_skip=0, # Consecutive days for testing short term      
            min_requests_per_day=3, # Ensure enough requests to trigger different types
            max_requests_per_day=5,
            borrow_weight=1, 
            order_weight=1, # For successful orders
            query_weight=1, 
            failed_order_weight=2, # Give weight to generate failed order attempts
            new_student_ratio=0.1
        )
        
        print(f"Commands for cycle starting {next_date_for_cycle.isoformat()}:")
        for cmd_idx, cmd in enumerate(cycle_cmds):
            print(f"  {cmd_idx+1}. {cmd}")
            # In a real test harness, update generator_library_model based on SUT's valid actions
            # For example, if a "successful order" command is generated and SUT accepts it,
            # update s1.pending_order_isbn in generator_library_model.
            # If a "failed order attempt" for s1 is generated, its state shouldn't change for that op.

        total_generated_commands.extend(cycle_cmds)
        next_date_for_cycle = next_cycle_start_dt 
        print(f"Next cycle will start on or after: {next_date_for_cycle.isoformat()}")

        # Simple state update for the model if a successful order for a NEW student happened
        # This is a very simplified model update for demonstration
        if i == 0 : # After first cycle, if s1 made a new successful order, reflect it for next cycle gen
            for cmd in cycle_cmds:
                parts = cmd.split()
                if len(parts) > 3 and parts[2] == s1_id and parts[3] == "ordered" and s1.pending_order_isbn != parts[4]:
                    # This is a rough check, assumes SUT would accept if _can_student_order_isbn was true
                    # A real harness would base this on SUT's actual output + checker validation
                    is_successful_order_possible = False
                    temp_student_obj = generator_library_model._get_student(s1_id)
                    temp_isbn = parts[4]
                    temp_book_type = generator_library_model._get_book_type_from_id_or_isbn(temp_isbn)
                    
                    # Temporarily clear pending order to check if this new one would be valid *if it were the first*
                    original_pending = temp_student_obj.pending_order_isbn
                    temp_student_obj.pending_order_isbn = None 
                    if _can_student_order_isbn(temp_student_obj, temp_isbn, temp_book_type):
                        is_successful_order_possible = True
                    temp_student_obj.pending_order_isbn = original_pending # Restore

                    if is_successful_order_possible and original_pending is None: # Only if they had no prior order
                        print(f"  (Gen model updating: {s1_id} now has pending order for {parts[4]})")
                        s1.pending_order_isbn = parts[4] # Update our model
                        s1.reserved_book_copy_id_at_ao = None # Clear any AO reservation if new order
                        s1.pickup_deadline_for_reserved_book = None
                    break


    print(f"\n--- Total {len(total_generated_commands)} command lines generated. ---")