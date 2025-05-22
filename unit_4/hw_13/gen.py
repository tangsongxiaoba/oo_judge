# gen.py
import random
from datetime import date, timedelta

from state import LibrarySystem, Student, BookCopy # Assuming state.py is accessible

STUDENT_IDS_POOL = [f"2337{i:04d}" for i in range(1, 75)]
DEFAULT_PICK_WEIGHT = 2

# --- New Default Propensities/Priorities ---
DEFAULT_B_BOOK_PRIORITY = 0.5
DEFAULT_C_BOOK_PRIORITY = 0.5
DEFAULT_STUDENT_RETURN_PROPENSITY = 0.7
DEFAULT_STUDENT_PICK_PROPENSITY = 0.7
# --- Helper functions (mostly unchanged, but some might use new params indirectly) ---

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

def _gen_failed_order_attempt(library_system: LibrarySystem, current_date_str: str,
                               b_book_priority: float, c_book_priority: float) -> str | None: # Added priorities
    students_with_active_orders = [
        s_id for s_id, s_obj in library_system.students.items()
        if s_obj.pending_order_isbn is not None or s_obj.reserved_book_copy_id_at_ao is not None
    ]
    if not students_with_active_orders: return None
    student_id_to_test = random.choice(students_with_active_orders)
    student_obj = library_system._get_student(student_id_to_test)
    all_isbns_available = _get_all_existing_isbns(library_system)
    if not all_isbns_available: return None

    current_order_isbn = student_obj.pending_order_isbn
    if not current_order_isbn and student_obj.reserved_book_copy_id_at_ao:
        reserved_book = library_system._get_book_copy(student_obj.reserved_book_copy_id_at_ao)
        if reserved_book: current_order_isbn = reserved_book.isbn

    candidate_isbns_for_failed_order = []
    b_candidates, c_candidates, other_candidates = [], [], []

    for isbn in all_isbns_available:
        book_type = library_system._get_book_type_from_id_or_isbn(isbn)
        is_different_from_current = (current_order_isbn is None or isbn != current_order_isbn)

        if book_type == 'A': # Ordering Type A is always a "failed" attempt if rules are strict.
            if is_different_from_current: # Prioritize ordering a new Type A if already has order
                 other_candidates.append(isbn) # Could be a specific category for A type if needed
            continue # Skip A for B/C specific logic below

        if not is_different_from_current: continue # Don't re-order same book if this is about a *new* failed order

        if book_type == 'B':
            b_candidates.append(isbn)
        elif book_type == 'C':
            c_candidates.append(isbn)

    # Apply priority for B and C books in failed order attempts
    total_priority = b_book_priority + c_book_priority
    if total_priority == 0 : total_priority = 1 # Avoid division by zero, fallback to equal

    if b_candidates and random.random() < (b_book_priority / total_priority if total_priority > 0 else 0.5):
        candidate_isbns_for_failed_order.extend(b_candidates)
    elif c_candidates: # If B not chosen or not available, consider C
        candidate_isbns_for_failed_order.extend(c_candidates)
    
    if not candidate_isbns_for_failed_order: # Fallback if no B/C or priority led to empty
        candidate_isbns_for_failed_order.extend(b_candidates) # Add all B
        candidate_isbns_for_failed_order.extend(c_candidates) # Add all C
    
    if not candidate_isbns_for_failed_order:
        candidate_isbns_for_failed_order.extend(other_candidates) # Try Type A books

    if not candidate_isbns_for_failed_order:
        if current_order_isbn : # Fallback to re-ordering current if no other option
             return f"[{current_date_str}] {student_id_to_test} ordered {current_order_isbn}"
        return None

    isbn_to_try_failed_order = random.choice(candidate_isbns_for_failed_order)
    return f"[{current_date_str}] {student_id_to_test} ordered {isbn_to_try_failed_order}"


def gen_day_commands(library_system: LibrarySystem,
                     num_user_requests: int,
                     current_date_str: str,
                     borrow_weight: int = 3,
                     order_weight: int = 2,
                     query_weight: int = 5,
                     failed_order_weight: int = 0,
                     new_student_ratio: float = 0.1,
                     # New parameters
                     b_book_priority: float = DEFAULT_B_BOOK_PRIORITY,
                     c_book_priority: float = DEFAULT_C_BOOK_PRIORITY,
                     student_return_propensity: float = DEFAULT_STUDENT_RETURN_PROPENSITY,
                     student_pick_propensity: float = DEFAULT_STUDENT_PICK_PROPENSITY
                    ) -> list[str]:

    all_book_ids = _get_all_existing_book_ids(library_system)
    all_isbns = _get_all_existing_isbns(library_system)

    if not all_book_ids and not all_isbns : return []

    potential_return_command_str = None
    if random.random() < student_return_propensity: # Apply return propensity
        students_with_books_to_return = []
        for student_id, student_obj in library_system.students.items():
            if student_obj.held_b_book_copy_id:
                students_with_books_to_return.append((student_id, student_obj.held_b_book_copy_id))
            for _, book_id in student_obj.held_c_books_by_isbn.items():
                students_with_books_to_return.append((student_id, book_id))
        if students_with_books_to_return:
            s_id, b_id = random.choice(students_with_books_to_return)
            potential_return_command_str = f"[{current_date_str}] {s_id} returned {b_id}"

    other_command_generators_weighted = []

    # Helper to select ISBN based on B/C priority
    def _select_isbn_with_priority(candidate_isbns: list[str]) -> str | None:
        if not candidate_isbns: return None
        
        b_isbns = [i for i in candidate_isbns if library_system._get_book_type_from_id_or_isbn(i) == 'B']
        c_isbns = [i for i in candidate_isbns if library_system._get_book_type_from_id_or_isbn(i) == 'C']
        
        chosen_isbn = None
        # Normalize priorities if both are zero, treat as equal
        norm_b_priority = b_book_priority
        norm_c_priority = c_book_priority
        if norm_b_priority == 0 and norm_c_priority == 0:
            norm_b_priority = 0.5
            norm_c_priority = 0.5
            
        total_priority = norm_b_priority + norm_c_priority
        if total_priority == 0: # Should not happen due to above, but defensive
            return random.choice(candidate_isbns)

        if b_isbns and c_isbns:
            if random.random() < norm_b_priority / total_priority:
                chosen_isbn = random.choice(b_isbns)
            else:
                chosen_isbn = random.choice(c_isbns)
        elif b_isbns:
            chosen_isbn = random.choice(b_isbns)
        elif c_isbns:
            chosen_isbn = random.choice(c_isbns)
        else: # Only non-B/C books (e.g. Type A, though borrow/order usually filters them)
            if candidate_isbns: # if candidate_isbns had only Type A initially
                chosen_isbn = random.choice(candidate_isbns)
        return chosen_isbn


    # Generator for 'borrowed'
    def _gen_borrow():
        s_id_candidate = _get_random_student_id(library_system, 1.0 - new_student_ratio)
        student_obj = library_system._get_student(s_id_candidate)
        
        borrowable_isbns_on_shelf = []
        for isbn, copies in library_system.books_on_shelf_by_isbn.items():
            if copies and any(library_system.all_book_copies[b_id].current_location == "bookshelf" for b_id in copies):
                book_type = library_system._get_book_type_from_id_or_isbn(isbn)
                if _can_student_borrow_isbn(student_obj, isbn, book_type, library_system): # Check rules AFTER confirming on shelf
                     borrowable_isbns_on_shelf.append(isbn)
        
        if not borrowable_isbns_on_shelf: return None

        isbn_candidate = _select_isbn_with_priority(borrowable_isbns_on_shelf)
        if isbn_candidate:
            return f"[{current_date_str}] {s_id_candidate} borrowed {isbn_candidate}"
        return None # Should not happen if borrowable_isbns_on_shelf was not empty
    if borrow_weight > 0 and all_isbns:
        other_command_generators_weighted.extend([_gen_borrow] * borrow_weight)

    # Generator for 'ordered' (successful attempt)
    def _gen_successful_order():
        s_id_candidate = _get_random_student_id(library_system, 1.0 - new_student_ratio)
        student_obj = library_system._get_student(s_id_candidate)
        
        potentially_orderable_isbns = []
        for isbn in all_isbns:
            book_type = library_system._get_book_type_from_id_or_isbn(isbn)
            if _can_student_order_isbn(student_obj, isbn, book_type): # Check rules first
                potentially_orderable_isbns.append(isbn)
        
        if not potentially_orderable_isbns: return None
        
        isbn_candidate = _select_isbn_with_priority(potentially_orderable_isbns)
        if isbn_candidate:
            return f"[{current_date_str}] {s_id_candidate} ordered {isbn_candidate}"
        return None
    if order_weight > 0 and all_isbns:
        other_command_generators_weighted.extend([_gen_successful_order] * order_weight)

    # Generator for 'queried'
    def _gen_query():
        if not all_book_ids: return None
        queried_book_id = random.choice(all_book_ids)
        s_id = _get_random_student_id(library_system, 0.5)
        return f"[{current_date_str}] {s_id} queried {queried_book_id}"
    if query_weight > 0 and all_book_ids:
        other_command_generators_weighted.extend([_gen_query] * query_weight)

    _failed_order_func_ref = _gen_failed_order_attempt
    def _gen_failed_order_wrapper():
        return _failed_order_func_ref(library_system, current_date_str, b_book_priority, c_book_priority)
    if failed_order_weight > 0 and all_isbns:
        other_command_generators_weighted.extend([_gen_failed_order_wrapper] * failed_order_weight)

    # Generator for 'picked' attempts
    def _gen_pick_attempt():
        if random.random() >= student_pick_propensity: # Apply pick propensity
            return None

        eligible_pick_candidates = []
        student_ids_shuffled = list(library_system.students.keys())
        random.shuffle(student_ids_shuffled)

        for student_id in student_ids_shuffled:
            student_obj = library_system.students[student_id]
            if student_obj.reserved_book_copy_id_at_ao:
                reserved_book = library_system.all_book_copies.get(student_obj.reserved_book_copy_id_at_ao)
                if reserved_book and _can_student_pick_isbn(student_obj, reserved_book.isbn, library_system):
                    eligible_pick_candidates.append((student_id, reserved_book.isbn))
            elif student_obj.pending_order_isbn:
                pending_isbn = student_obj.pending_order_isbn
                book_type_of_pending = library_system._get_book_type_from_id_or_isbn(pending_isbn)
                can_hold_after_pick = True
                if book_type_of_pending == 'B' and student_obj.held_b_book_copy_id is not None: can_hold_after_pick = False
                if book_type_of_pending == 'C' and pending_isbn in student_obj.held_c_books_by_isbn: can_hold_after_pick = False
                if can_hold_after_pick:
                    eligible_pick_candidates.append((student_id, pending_isbn))
        if not eligible_pick_candidates: return None
        s_id, isbn_pk = random.choice(eligible_pick_candidates)
        return f"[{current_date_str}] {s_id} picked {isbn_pk}"
    if DEFAULT_PICK_WEIGHT > 0:
        other_command_generators_weighted.extend([_gen_pick_attempt] * DEFAULT_PICK_WEIGHT)

    final_generated_commands_for_day = []
    if potential_return_command_str:
        final_generated_commands_for_day.append(potential_return_command_str)

    if other_command_generators_weighted:
        attempts_for_others = 0
        max_attempts_current_loop = (num_user_requests - len(final_generated_commands_for_day)) * 5 \
                                    + len(other_command_generators_weighted) + 5
        while len(final_generated_commands_for_day) < num_user_requests and attempts_for_others < max_attempts_current_loop:
            gen_func = random.choice(other_command_generators_weighted)
            command_str = gen_func()
            attempts_for_others += 1
            if command_str:
                is_failed_order_attempt_type = (gen_func is _gen_failed_order_wrapper)
                if command_str not in final_generated_commands_for_day or \
                   num_user_requests > 10 or \
                   is_failed_order_attempt_type or \
                   random.random() < 0.7:
                     final_generated_commands_for_day.append(command_str)
    random.shuffle(final_generated_commands_for_day)
    return final_generated_commands_for_day[:num_user_requests]


def gen_open_close_cycle_data(
    library_system: LibrarySystem,
    start_date_obj: date,
    min_days_to_skip: int = 0,
    max_days_to_skip: int = 3,
    min_requests_per_day: int = 0,
    max_requests_per_day: int = 10,
    borrow_weight: int = 3,
    order_weight: int = 2,
    query_weight: int = 5,
    failed_order_weight: int = 0,
    new_student_ratio: float = 0.1,
    # New parameters to pass through
    b_book_priority: float = DEFAULT_B_BOOK_PRIORITY,
    c_book_priority: float = DEFAULT_C_BOOK_PRIORITY,
    student_return_propensity: float = DEFAULT_STUDENT_RETURN_PROPENSITY,
    student_pick_propensity: float = DEFAULT_STUDENT_PICK_PROPENSITY
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
            order_weight,
            query_weight,
            failed_order_weight,
            new_student_ratio,
            # Pass new params
            b_book_priority,
            c_book_priority,
            student_return_propensity,
            student_pick_propensity
        )
        cycle_commands.extend(day_user_requests)

    cycle_commands.append(f"[{current_date_str}] CLOSE")

    library_system.current_date_str = original_ls_date_str
    library_system.current_date_obj = original_ls_date_obj

    days_to_skip = random.randint(min_days_to_skip, max_days_to_skip)
    next_cycle_start_date_obj = start_date_obj + timedelta(days=1 + days_to_skip)

    return cycle_commands, next_cycle_start_date_obj


if __name__ == '__main__':
    print("--- Mock Test for gen.py with new priority/propensity params ---")

    generator_library_model = LibrarySystem()
    initial_book_data = [
        "B-0001 2", "C-0001 3", "A-0001 1", "B-0002 1", "C-0002 2", "C-0003 1"
    ]
    generator_library_model.initialize_books(initial_book_data)

    s1_id = "23370010"
    s1 = generator_library_model._get_student(s1_id)
    s1.pending_order_isbn = "C-0001"
    print(f"Initial: {s1_id} has pending order for {s1.pending_order_isbn}")

    s2_id = "23370011"
    s2 = generator_library_model._get_student(s2_id)
    s2.held_b_book_copy_id = "B-0001-01"
    if "B-0001-01" in generator_library_model.all_book_copies: # Manual state update
        book_to_hold = generator_library_model.all_book_copies["B-0001-01"]
        book_to_hold.current_location = "user"; book_to_hold.current_holder_student_id = s2_id
        if book_to_hold.isbn in generator_library_model.books_on_shelf_by_isbn and \
           book_to_hold.id in generator_library_model.books_on_shelf_by_isbn[book_to_hold.isbn]:
            generator_library_model.books_on_shelf_by_isbn[book_to_hold.isbn].remove(book_to_hold.id)
    print(f"Initial: {s2_id} holds {s2.held_b_book_copy_id}")


    current_test_start_date = date(2025, 1, 5)
    next_date_for_cycle = current_test_start_date

    for i in range(3): # Generate 3 cycles
        print(f"\n--- Generating Cycle {i+1} starting {next_date_for_cycle.isoformat()} ---")
        # Example: High priority for B books, low for C. High return propensity, low pick.
        b_prio, c_prio = (0.8, 0.2) if i % 2 == 0 else (0.2, 0.8) # Alternate B/C prio
        ret_prop, pick_prop = (0.9, 0.3) if i % 2 == 0 else (0.3, 0.9) # Alternate ret/pick prop

        print(f"  Cycle params: B_prio={b_prio:.1f}, C_prio={c_prio:.1f}, Ret_prop={ret_prop:.1f}, Pick_prop={pick_prop:.1f}")

        cycle_cmds, next_cycle_start_dt = gen_open_close_cycle_data(
            generator_library_model,
            next_date_for_cycle,
            min_days_to_skip=0, max_days_to_skip=0,
            min_requests_per_day=4, max_requests_per_day=7,
            borrow_weight=2, order_weight=2, query_weight=1, failed_order_weight=1,
            new_student_ratio=0.1,
            # New params being tested
            b_book_priority=b_prio,
            c_book_priority=c_prio,
            student_return_propensity=ret_prop,
            student_pick_propensity=pick_prop
        )

        print(f"Commands for cycle starting {next_date_for_cycle.isoformat()}:")
        for cmd_idx, cmd in enumerate(cycle_cmds):
            print(f"  {cmd_idx+1}. {cmd}")
            if s1.pending_order_isbn == "C-0001" and f"{s1_id} picked C-0001" in cmd:
                 s1.pending_order_isbn = None; s1.held_c_books_by_isbn["C-0001"] = "C-0001-XX"
                 print(f"    (Gen model updating for {s1_id}: picked C-0001)")
            if s2.held_b_book_copy_id == "B-0001-01" and f"{s2_id} returned B-0001-01" in cmd:
                s2.held_b_book_copy_id = None
                print(f"    (Gen model updating for {s2_id}: returned B-0001-01)")

        next_date_for_cycle = next_cycle_start_dt
        print(f"Next cycle will start on or after: {next_date_for_cycle.isoformat()}")