# gen.py
import random
from datetime import date, timedelta
from typing import List, Tuple, Optional, Callable, Dict, Set
import json
import sys
try:
    from state import LibrarySystem, Student, BookCopy
except ImportError as e:
    print(f"Critical Driver Error: Could not import required modules (state, gen, checker): {e}")
    try:
        print(json.dumps({"status": "failure", "reason": f"Critical import error: {e}"}))
    except Exception:
        pass
    sys.exit(1)


STUDENT_IDS_POOL = [f"2337{i:04d}" for i in range(1, 75)]

# --- Helper functions (Corrected and updated for HW15 rules) ---
def _get_random_student_id(library_system: LibrarySystem, existing_student_preference_ratio=0.9) -> str:
    if library_system.students and random.random() < existing_student_preference_ratio:
        return random.choice(list(library_system.students.keys()))
    return random.choice(STUDENT_IDS_POOL)

def _get_all_existing_book_copy_ids(library_system: LibrarySystem) -> List[str]:
    return list(library_system.all_book_copies.keys())

def _get_all_existing_isbns(library_system: LibrarySystem) -> List[str]:
    return list({b.isbn for b in library_system.all_book_copies.values()})

def _get_all_isbns_on_shelf(library_system: LibrarySystem) -> List[str]:
    return list(library_system.books_on_shelf_by_isbn.keys())

def _can_student_read_isbn(student: Student, book_type: str) -> bool:
    """Checks if a student has enough credit to read a book of a given type."""
    if book_type == 'A':
        return student.credit_score >= 40
    if book_type in ['B', 'C']:
        return student.credit_score > 0
    return False

def _can_student_borrow_isbn(student: Student, isbn: str, book_type: str, library_system: LibrarySystem) -> bool:
    if student.credit_score < 60: return False
    if book_type == 'A': return False
    if book_type == 'B' and student.held_b_book is not None: return False
    if book_type == 'C' and isbn in student.held_c_books_by_isbn: return False
    if not library_system.books_on_shelf_by_isbn.get(isbn): return False
    return True

def _can_student_order_isbn(student: Student, isbn: str, book_type: str) -> bool:
    if student.credit_score < 100: return False
    if book_type == 'A': return False
    if student.pending_order_isbn is not None or student.reserved_book_copy_id_at_ao is not None: return False
    if book_type == 'B' and student.held_b_book is not None: return False
    if book_type == 'C' and isbn in student.held_c_books_by_isbn: return False
    return True

def _can_student_pick_isbn(student: Student, isbn_to_pick: str, library_system: LibrarySystem) -> bool:
    if not student.reserved_book_copy_id_at_ao: return False
    reserved_book_copy_obj = library_system.all_book_copies.get(student.reserved_book_copy_id_at_ao)
    if not reserved_book_copy_obj or \
       reserved_book_copy_obj.isbn != isbn_to_pick or \
       reserved_book_copy_obj.current_location != "appointment_office" or \
       reserved_book_copy_obj.ao_reserved_for_student_id != student.id:
        return False
    if library_system.current_date_obj and student.pickup_deadline_for_reserved_book and \
       library_system.current_date_obj > student.pickup_deadline_for_reserved_book:
        return False
    if student.credit_score < 60: return False
    book_type_to_pick = reserved_book_copy_obj.type
    if book_type_to_pick == 'B' and student.held_b_book is not None: return False
    if book_type_to_pick == 'C' and isbn_to_pick in student.held_c_books_by_isbn: return False
    return True

def _format_date_for_command(date_obj: date) -> str:
    return date_obj.strftime("%Y-%m-%d")

def _select_isbn_with_type_priority(
    candidate_isbns: List[str], library_system: LibrarySystem,
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
    if c_prio > 0 and rand_val < c_prio and c_isbns: return random.choice(c_isbns)
    all_available = a_isbns + b_isbns + c_isbns
    if all_available: return random.choice(all_available)
    return None

def generate_requests_for_one_day(
    library_system: LibrarySystem,
    num_user_requests: int,
    current_date_str: str,
    borrow_weight: int, order_weight: int, pick_weight: int,
    read_weight: int, restore_weight: int,
    trace_query_weight: int,
    credit_query_weight: int,
    failed_borrow_weight: int,
    failed_order_weight: int,
    new_student_ratio: float, student_return_propensity: float,
    student_pick_propensity: float, student_restore_propensity: float,
    b_book_priority: float, c_book_priority: float, a_book_read_priority: float
) -> List[str]:
    
    if num_user_requests <= 0: return []

    opportunistic_commands = []
    if random.random() < student_return_propensity:
        students_with_borrowed_books = []
        for sid, s in library_system.students.items():
            if s.held_b_book: students_with_borrowed_books.append((sid, s.held_b_book[0]))
            for b_id, _ in s.held_c_books_by_isbn.values(): students_with_borrowed_books.append((sid, b_id))
        if students_with_borrowed_books:
            s_id, b_id = random.choice(students_with_borrowed_books)
            opportunistic_commands.append(f"[{current_date_str}] {s_id} returned {b_id}")
    
    if random.random() < student_pick_propensity and pick_weight > 0:
        eligible_pick_candidates = []
        shuffled_s_ids = list(library_system.students.keys()); random.shuffle(shuffled_s_ids)
        for s_id in shuffled_s_ids:
            s = library_system._get_student(s_id)
            if s.reserved_book_copy_id_at_ao:
                b = library_system.all_book_copies.get(s.reserved_book_copy_id_at_ao)
                if b and _can_student_pick_isbn(s, b.isbn, library_system):
                    eligible_pick_candidates.append((s_id, b.isbn))
        if eligible_pick_candidates:
            s_id, isbn = random.choice(eligible_pick_candidates)
            opportunistic_commands.append(f"[{current_date_str}] {s_id} picked {isbn}")

    random.shuffle(opportunistic_commands)
    weighted_command_generators: List[Tuple[Callable[[], Optional[str]], int]] = []

    def _gen_borrow() -> Optional[str]:
        isbns_on_shelf = _get_all_isbns_on_shelf(library_system)
        if not isbns_on_shelf: return None
        s_id = _get_random_student_id(library_system, 1.0 - new_student_ratio)
        s = library_system._get_student(s_id)
        borrowable = [i for i in isbns_on_shelf if _can_student_borrow_isbn(s, i, library_system._get_book_type_from_id_or_isbn(i), library_system)]
        if not borrowable: return None
        isbn = _select_isbn_with_type_priority(borrowable, library_system, 0, b_book_priority, c_book_priority)
        return f"[{current_date_str}] {s.id} borrowed {isbn}" if isbn else None
    if borrow_weight > 0: weighted_command_generators.append((_gen_borrow, borrow_weight))

    def _gen_successful_order() -> Optional[str]:
        all_isbns = _get_all_existing_isbns(library_system)
        if not all_isbns: return None
        s_id = _get_random_student_id(library_system, 1.0 - new_student_ratio)
        s = library_system._get_student(s_id)
        orderable = [i for i in all_isbns if _can_student_order_isbn(s, i, library_system._get_book_type_from_id_or_isbn(i))]
        if not orderable: return None
        isbn = _select_isbn_with_type_priority(orderable, library_system, 0, b_book_priority, c_book_priority)
        return f"[{current_date_str}] {s.id} ordered {isbn}" if isbn else None
    if order_weight > 0: weighted_command_generators.append((_gen_successful_order, order_weight))

    def _gen_trace_query() -> Optional[str]:
        all_book_ids = _get_all_existing_book_copy_ids(library_system)
        if not all_book_ids: return None
        book_id = random.choice(all_book_ids)
        s_id = _get_random_student_id(library_system, 0.5)
        return f"[{current_date_str}] {s_id} queried {book_id}"
    if trace_query_weight > 0: weighted_command_generators.append((_gen_trace_query, trace_query_weight))
    
    def _gen_credit_query() -> Optional[str]:
        if not library_system.students: return None
        s_id = random.choice(list(library_system.students.keys()))
        return f"[{current_date_str}] {s_id} queried credit score"
    if credit_query_weight > 0: weighted_command_generators.append((_gen_credit_query, credit_query_weight))

    def _gen_failed_borrow_by_credit() -> Optional[str]:
        low_credit_students = [s for s in library_system.students.values() if s.credit_score < 100]
        if not low_credit_students: return None
        student = random.choice(low_credit_students)
        isbns_on_shelf = _get_all_isbns_on_shelf(library_system)

        if student.credit_score < 60:
            b_or_c = [i for i in isbns_on_shelf if library_system._get_book_type_from_id_or_isbn(i) in 'BC']
            if b_or_c: return f"[{current_date_str}] {student.id} borrowed {random.choice(b_or_c)}"
        if student.credit_score < 40:
            a_isbns = [i for i in isbns_on_shelf if library_system._get_book_type_from_id_or_isbn(i) == 'A']
            if a_isbns: return f"[{current_date_str}] {student.id} read {random.choice(a_isbns)}"
        if student.credit_score < 100:
            all_isbns = _get_all_existing_isbns(library_system)
            b_or_c = [i for i in all_isbns if library_system._get_book_type_from_id_or_isbn(i) in 'BC']
            if b_or_c: return f"[{current_date_str}] {student.id} ordered {random.choice(b_or_c)}"
        return None
    if failed_borrow_weight > 0: weighted_command_generators.append((_gen_failed_borrow_by_credit, failed_borrow_weight))

    def _gen_read() -> Optional[str]:
        isbns_on_shelf = _get_all_isbns_on_shelf(library_system)
        if not isbns_on_shelf: return None
        potential_s_ids = list(library_system.students.keys()) + random.sample(STUDENT_IDS_POOL, k=min(10, len(STUDENT_IDS_POOL)))
        random.shuffle(potential_s_ids)
        for s_id in potential_s_ids:
            s = library_system._get_student(s_id)
            if s.reading_book_copy_id_today: continue
            readable = [i for i in isbns_on_shelf if _can_student_read_isbn(s, library_system._get_book_type_from_id_or_isbn(i))]
            if readable:
                isbn = _select_isbn_with_type_priority(readable, library_system, a_book_read_priority, b_book_priority, c_book_priority)
                if isbn: return f"[{current_date_str}] {s_id} read {isbn}"
        return None
    if read_weight > 0: weighted_command_generators.append((_gen_read, read_weight))

    def _gen_restore() -> Optional[str]:
        if not (random.random() < student_restore_propensity): return None
        candidates = []
        shuffled_s_ids = list(library_system.students.keys()); random.shuffle(shuffled_s_ids)
        for s_id in shuffled_s_ids:
            s = library_system._get_student(s_id)
            if s.reading_book_copy_id_today and not s.has_generated_restore_for_current_read:
                candidates.append((s_id, s.reading_book_copy_id_today))
        if not candidates: return None
        s_id, book_id = random.choice(candidates)
        library_system._get_student(s_id).has_generated_restore_for_current_read = True
        return f"[{current_date_str}] {s_id} restored {book_id}"
    if restore_weight > 0: weighted_command_generators.append((_gen_restore, restore_weight))

    def _gen_failed_order_attempt() -> Optional[str]:
        all_isbns = _get_all_existing_isbns(library_system);
        if not all_isbns: return None
        s_id = _get_random_student_id(library_system, 0.95)
        s = library_system._get_student(s_id)
        if (s.pending_order_isbn or s.reserved_book_copy_id_at_ao) and random.random() < 0.5:
            return f"[{current_date_str}] {s_id} ordered {random.choice(all_isbns)}"
        if s.held_b_book and random.random() < 0.5:
            b_isbns = [i for i in all_isbns if library_system._get_book_type_from_id_or_isbn(i) == 'B']
            if b_isbns: return f"[{current_date_str}] {s_id} ordered {random.choice(b_isbns)}"
        if s.held_c_books_by_isbn and random.random() < 0.5:
            held_c_isbn = random.choice(list(s.held_c_books_by_isbn.keys()))
            return f"[{current_date_str}] {s_id} ordered {held_c_isbn}"
        return None
    if failed_order_weight > 0: weighted_command_generators.append((_gen_failed_order_attempt, failed_order_weight))

    final_commands_for_day = []
    max_opportunistic = min(len(opportunistic_commands), max(0, num_user_requests // 3), 3)
    final_commands_for_day.extend(opportunistic_commands[:max_opportunistic])
    remaining_slots = num_user_requests - len(final_commands_for_day)

    if remaining_slots > 0 and weighted_command_generators:
        flat_generators = [gen for gen, w in weighted_command_generators for _ in range(w)]
        if flat_generators:
            for _ in range(remaining_slots * 5):
                if len(final_commands_for_day) >= num_user_requests: break
                cmd = random.choice(flat_generators)()
                if cmd: final_commands_for_day.append(cmd)
    
    random.shuffle(final_commands_for_day)
    return final_commands_for_day[:num_user_requests]

def generate_command_cycle(
    library_system: LibrarySystem,
    current_system_date: date,
    is_library_logically_closed: bool,
    num_requests_in_batch: int,
    close_probability: float,
    min_skip_days_post_close: int, max_skip_days_post_close: int,
    borrow_weight: int, order_weight: int, pick_weight: int,
    read_weight: int, restore_weight: int,
    trace_query_weight: int,
    credit_query_weight: int,
    failed_borrow_weight: int,
    failed_order_weight: int,
    new_student_ratio: float, student_return_propensity: float,
    student_pick_propensity: float, student_restore_propensity: float,
    b_book_priority: float, c_book_priority: float, a_book_read_priority: float
) -> Tuple[List[str], date, bool]:

    commands_this_cycle: List[str] = []
    date_for_ops = current_system_date
    system_closed_after_this_cycle = is_library_logically_closed
    next_date_for_ops = current_system_date

    if is_library_logically_closed:
        date_str_for_open = _format_date_for_command(date_for_ops)
        commands_this_cycle.append(f"[{date_str_for_open}] OPEN")
        system_closed_after_this_cycle = False

    if not system_closed_after_this_cycle and num_requests_in_batch > 0:
        date_str_for_requests = _format_date_for_command(date_for_ops)
        user_requests = generate_requests_for_one_day(
            library_system, num_requests_in_batch, date_str_for_requests,
            borrow_weight, order_weight, pick_weight, read_weight, restore_weight,
            trace_query_weight, credit_query_weight,
            failed_borrow_weight, failed_order_weight,
            new_student_ratio, student_return_propensity,
            student_pick_propensity, student_restore_propensity,
            b_book_priority, c_book_priority, a_book_read_priority
        )
        commands_this_cycle.extend(user_requests)
    
    if not system_closed_after_this_cycle and random.random() < close_probability:
        date_str_for_close = _format_date_for_command(date_for_ops)
        commands_this_cycle.append(f"[{date_str_for_close}] CLOSE")
        system_closed_after_this_cycle = True
        days_to_skip = random.randint(min_skip_days_post_close, max_skip_days_post_close)
        next_date_for_ops = date_for_ops + timedelta(days=1 + days_to_skip)
    elif not system_closed_after_this_cycle:
        next_date_for_ops = date_for_ops
    
    return (commands_this_cycle, next_date_for_ops, system_closed_after_this_cycle)


if __name__ == '__main__':
    print("--- Mock Test for gen.py (HW15 Rules with new parameters) ---")
    mock_lib_sys = LibrarySystem()
    mock_lib_sys.initialize_books(["A-0001 2", "B-0001 1", "C-0001 1"])
    mock_lib_sys.current_date_obj = date(2025, 1, 1)

    low_credit_student = mock_lib_sys._get_student("S_LOW")
    low_credit_student.credit_score = 30
    print(f"Test Student S_LOW credit: {low_credit_student.credit_score}")

    high_credit_student = mock_lib_sys._get_student("S_HIGH")
    high_credit_student.credit_score = 120
    print(f"Test Student S_HIGH credit: {high_credit_student.credit_score}")

    print("\n--- Generating one day of requests with new weights ---")
    day_commands = generate_requests_for_one_day(
        mock_lib_sys, num_user_requests=15, current_date_str="2025-01-01",
        borrow_weight=3, order_weight=2, pick_weight=1,
        read_weight=3, restore_weight=2,
        trace_query_weight=3,
        credit_query_weight=4,     # High weight for testing
        failed_borrow_weight=5,    # High weight for testing
        failed_order_weight=2,
        new_student_ratio=0.1, student_return_propensity=0.5,
        student_pick_propensity=0.5, student_restore_propensity=0.8,
        b_book_priority=1, c_book_priority=1, a_book_read_priority=1
    )
    
    print("Generated commands:")
    for cmd in day_commands:
        print(cmd)
    
    print("\n--- Test Complete ---")