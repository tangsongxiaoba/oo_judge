# state.py
# FINAL CORRECTED VERSION ALIGNED WITH HW15.MD MANUAL

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple, Set

class BookCopy:
    # ... (此部分无变化)
    def __init__(self, book_id: str, isbn: str, book_type: str, copy_num: int):
        self.id: str = book_id
        self.isbn: str = isbn
        self.type: str = book_type
        self.copy_num: int = copy_num
        self.current_location: str = "bookshelf"
        self.current_holder_student_id: Optional[str] = None
        self.ao_reserved_for_student_id: Optional[str] = None
        self.ao_pickup_deadline: Optional[date] = None
        self.trace: List[Tuple[str, str, str]] = []

    def __repr__(self):
        return (f"BookCopy(id='{self.id}', loc='{self.current_location}')")

class Student:
    # --- CHANGE: Removed overdue_penalized_books as it's no longer needed with corrected logic ---
    def __init__(self, student_id: str):
        self.id: str = student_id
        self.credit_score: int = 100
        self.held_b_book: Optional[Tuple[str, date]] = None
        self.held_c_books_by_isbn: Dict[str, Tuple[str, date]] = {}
        self.pending_order_isbn: Optional[str] = None
        self.reserved_book_copy_id_at_ao: Optional[str] = None
        self.pickup_deadline_for_reserved_book: Optional[date] = None
        self.reading_book_copy_id_today: Optional[str] = None
        self.has_generated_restore_for_current_read: bool = False

    def _update_credit(self, change: int):
        self.credit_score = max(0, min(180, self.credit_score + change))

    def __repr__(self):
        return (f"Student(id='{self.id}', credit={self.credit_score})")

class LibrarySystem:
    # ... (常量定义无变化) ...
    LOCATION_SHORT_MAP = {"bookshelf": "bs", "hot_bookshelf": "hbs", "borrow_return_office": "bro", "appointment_office": "ao", "reading_room": "rr", "user": "user"}
    REVERSE_LOCATION_SHORT_MAP = {v: k for k, v in LOCATION_SHORT_MAP.items()}
    SHELF_LOCATIONS = ["bookshelf", "hot_bookshelf"]
    TIDY_INTERNAL_LOCATIONS = ["bookshelf", "hot_bookshelf", "borrow_return_office", "appointment_office", "reading_room"]

    LOAN_PERIOD_B = 30
    LOAN_PERIOD_C = 60
    CREDIT_ON_TIME_RETURN = 10
    CREDIT_SAME_DAY_RESTORE = 10
    CREDIT_PENALTY_READ_NOT_RESTORED = -10
    CREDIT_PENALTY_OVERDUE_INITIAL = -5
    CREDIT_PENALTY_OVERDUE_DAILY = -5
    CREDIT_PENALTY_ORDER_NOT_PICKED = -15
    
    def __init__(self):
        self.all_book_copies: Dict[str, BookCopy] = {}
        self.students: Dict[str, Student] = {}
        self.books_on_shelf_by_isbn: Dict[str, List[str]] = {}
        self.current_date_obj: Optional[date] = None
        self.hot_isbns_for_current_open_tidy: Set[str] = set()
        self.isbns_becoming_hot_this_open_period: Set[str] = set()
        self.last_open_date: Optional[date] = None
    
    def _parse_date(self, date_str: str) -> date:
        return date.fromisoformat(date_str)

    def _get_student(self, student_id: str) -> Student:
        if student_id not in self.students:
            self.students[student_id] = Student(student_id)
        return self.students[student_id]

    def _get_book_copy(self, book_id: str) -> Optional[BookCopy]:
        return self.all_book_copies.get(book_id)

    def _get_book_type_from_id_or_isbn(self, id_or_isbn: str) -> str:
        return id_or_isbn[0]
        
    def advance_time_to(self, new_date: date):
        if not self.current_date_obj:
            self.current_date_obj = new_date
            return
        
        if new_date <= self.current_date_obj:
            return

        day_to_process = self.current_date_obj
        while day_to_process < new_date:
            # Process penalties for the end of 'day_to_process'
            for student in self.students.values():
                
                # --- START OF CORRECTED PENALTY LOGIC ---
                # This logic now strictly follows the manual.
                
                # Check held B-type books
                if student.held_b_book:
                    _, due_date = student.held_b_book
                    # Case 1: The book becomes overdue today (initial penalty)
                    if due_date == day_to_process:
                        student._update_credit(self.CREDIT_PENALTY_OVERDUE_INITIAL)
                    # Case 2: The book was already overdue (daily penalty)
                    elif due_date < day_to_process:
                        student._update_credit(self.CREDIT_PENALTY_OVERDUE_DAILY)

                # Check held C-type books
                for book_id, due_date in student.held_c_books_by_isbn.values():
                    # Case 1: The book becomes overdue today (initial penalty)
                    if due_date == day_to_process:
                        student._update_credit(self.CREDIT_PENALTY_OVERDUE_INITIAL)
                    # Case 2: The book was already overdue (daily penalty)
                    elif due_date < day_to_process:
                        student._update_credit(self.CREDIT_PENALTY_OVERDUE_DAILY)
                # --- END OF CORRECTED PENALTY LOGIC ---
            
            # Penalty for appointment not picked up by deadline (this logic was already correct)
            for book in self.all_book_copies.values():
                if book.current_location == "appointment_office" and \
                   book.ao_pickup_deadline == day_to_process and \
                   book.ao_reserved_for_student_id:
                    student_to_penalize = self._get_student(book.ao_reserved_for_student_id)
                    student_to_penalize._update_credit(self.CREDIT_PENALTY_ORDER_NOT_PICKED)

            day_to_process += timedelta(days=1)

        self.current_date_obj = new_date

    # ... (other init/helper methods without changes) ...
    def initialize_books(self, book_lines: List[str]):
        self.all_book_copies.clear()
        self.students.clear()
        self.books_on_shelf_by_isbn.clear()
        self.hot_isbns_for_current_open_tidy.clear()
        self.isbns_becoming_hot_this_open_period.clear()

        for line in book_lines:
            parts = line.split()
            if len(parts) != 2: continue
            isbn_str, count_str = parts
            try:
                count = int(count_str)
                if count <=0: continue
            except ValueError: continue
                
            book_type = self._get_book_type_from_id_or_isbn(isbn_str)
            if isbn_str not in self.books_on_shelf_by_isbn:
                self.books_on_shelf_by_isbn[isbn_str] = []

            for i in range(1, count + 1):
                copy_num_str = f"{i:02d}"
                book_id = f"{isbn_str}-{copy_num_str}"
                book_copy = BookCopy(book_id, isbn_str, book_type, i)
                book_copy.current_location = "bookshelf"
                self.all_book_copies[book_id] = book_copy
                if book_id not in self.books_on_shelf_by_isbn[isbn_str]:
                    self.books_on_shelf_by_isbn[isbn_str].append(book_id)
        
        for isbn in self.books_on_shelf_by_isbn:
            self.books_on_shelf_by_isbn[isbn].sort(key=lambda bid: self.all_book_copies[bid].copy_num)

    def _record_move_in_trace(self, book_copy: BookCopy, from_location_full: str, to_location_full: str, date_str: str):
        if from_location_full != to_location_full:
            from_short = self.LOCATION_SHORT_MAP.get(from_location_full)
            to_short = self.LOCATION_SHORT_MAP.get(to_location_full)
            if from_short is None or to_short is None: return
            book_copy.trace.append((date_str, from_short, to_short))

    def _update_book_location_datastructures(self, book_copy: BookCopy, 
                                            old_location_full: str, new_location_full: str, 
                                            old_holder_student_id: Optional[str] = None, 
                                            new_holder_student_id: Optional[str] = None):
        book_id = book_copy.id
        isbn = book_copy.isbn

        if old_location_full in self.SHELF_LOCATIONS:
            if isbn in self.books_on_shelf_by_isbn and book_id in self.books_on_shelf_by_isbn[isbn]:
                self.books_on_shelf_by_isbn[isbn].remove(book_id)
                if not self.books_on_shelf_by_isbn[isbn]:
                    del self.books_on_shelf_by_isbn[isbn]
        elif old_location_full == "user" and old_holder_student_id:
            student = self._get_student(old_holder_student_id)
            if book_copy.type == 'B' and student.held_b_book and student.held_b_book[0] == book_id:
                student.held_b_book = None
                # --- CHANGE: Removed overdue_penalized_books logic ---
            elif book_copy.type == 'C' and student.held_c_books_by_isbn.get(isbn) and student.held_c_books_by_isbn[isbn][0] == book_id:
                if isbn in student.held_c_books_by_isbn:
                    del student.held_c_books_by_isbn[isbn]
                # --- CHANGE: Removed overdue_penalized_books logic ---

        if new_location_full in self.SHELF_LOCATIONS:
            if isbn not in self.books_on_shelf_by_isbn:
                self.books_on_shelf_by_isbn[isbn] = []
            if book_id not in self.books_on_shelf_by_isbn[isbn]:
                 self.books_on_shelf_by_isbn[isbn].append(book_id)
            self.books_on_shelf_by_isbn[isbn].sort(key=lambda bid: self.all_book_copies[bid].copy_num)
        
    # --- The rest of the file has no logical changes and is omitted for brevity ---
    # ... all other methods from apply_book_movement onwards are unchanged ...
    def _apply_book_movement(self, book_id: str, 
                            from_location_full: str,
                            to_location_full: str, 
                            date_str: str, 
                            target_student_id_for_user_or_reader: Optional[str] = None, 
                            ao_reservation_student_id: Optional[str] = None, 
                            ao_pickup_deadline: Optional[date] = None):
        book_copy = self._get_book_copy(book_id)
        if not book_copy: return 
        if book_copy.current_location != from_location_full: return 
            
        old_location_full = book_copy.current_location 
        old_holder_student_id = book_copy.current_holder_student_id
        self._record_move_in_trace(book_copy, old_location_full, to_location_full, date_str)
        
        self._update_book_location_datastructures(book_copy, old_location_full, to_location_full,
                                                  old_holder_student_id=old_holder_student_id, 
                                                  new_holder_student_id=None)
        
        book_copy.current_location = to_location_full
        if to_location_full in ["user", "reading_room"]:
            book_copy.current_holder_student_id = target_student_id_for_user_or_reader
        else:
            book_copy.current_holder_student_id = None

        if to_location_full == "appointment_office":
            book_copy.ao_reserved_for_student_id = ao_reservation_student_id
            book_copy.ao_pickup_deadline = ao_pickup_deadline
        elif old_location_full == "appointment_office":
            book_copy.ao_reserved_for_student_id = None
            book_copy.ao_pickup_deadline = None
    
    def apply_open_action(self, date_str: str):
        new_date = self._parse_date(date_str)
        self.advance_time_to(new_date)

        if self.last_open_date != new_date:
            self.hot_isbns_for_current_open_tidy = self.isbns_becoming_hot_this_open_period.copy()
            self.isbns_becoming_hot_this_open_period.clear()
            self.last_open_date = new_date
            
        for student in self.students.values():
            student.reading_book_copy_id_today = None
            student.has_generated_restore_for_current_read = False

    def apply_close_action(self, date_str: str):
        if not self.current_date_obj: return
        
        for student in self.students.values():
            if student.reading_book_copy_id_today:
                student._update_credit(self.CREDIT_PENALTY_READ_NOT_RESTORED)
            student.reading_book_copy_id_today = None
            student.has_generated_restore_for_current_read = False

    def apply_validated_borrow_action(self, date_str: str, student_id: str, book_copy_id_borrowed: str):
        book_copy = self._get_book_copy(book_copy_id_borrowed)
        student = self._get_student(student_id)
        if not book_copy or not self.current_date_obj: return

        from_location = book_copy.current_location 
        if from_location not in self.SHELF_LOCATIONS: return

        loan_period = self.LOAN_PERIOD_B if book_copy.type == 'B' else self.LOAN_PERIOD_C
        due_date = self.current_date_obj + timedelta(days=loan_period)
        
        if book_copy.type == 'B':
            student.held_b_book = (book_copy_id_borrowed, due_date)
        elif book_copy.type == 'C':
            student.held_c_books_by_isbn[book_copy.isbn] = (book_copy_id_borrowed, due_date)

        self._apply_book_movement(book_copy_id_borrowed, from_location, "user", date_str,
                                  target_student_id_for_user_or_reader=student_id)
        self.isbns_becoming_hot_this_open_period.add(book_copy.isbn)

    def apply_validated_return_action(self, date_str: str, student_id: str, book_copy_id_returned: str) -> bool:
        book_copy = self._get_book_copy(book_copy_id_returned)
        student = self._get_student(student_id)
        if not book_copy or not self.current_date_obj: return False

        is_overdue = False
        due_date: Optional[date] = None

        if book_copy.type == 'B' and student.held_b_book and student.held_b_book[0] == book_copy_id_returned:
            due_date = student.held_b_book[1]
        elif book_copy.type == 'C' and student.held_c_books_by_isbn.get(book_copy.isbn) and \
             student.held_c_books_by_isbn[book_copy.isbn][0] == book_copy_id_returned:
            due_date = student.held_c_books_by_isbn[book_copy.isbn][1]
        
        if due_date:
            if self.current_date_obj > due_date:
                is_overdue = True
            else:
                student._update_credit(self.CREDIT_ON_TIME_RETURN)
        
        self._apply_book_movement(book_copy_id_returned, "user", "borrow_return_office", date_str,
                                  target_student_id_for_user_or_reader=student_id)
        
        return is_overdue

    def apply_validated_order_action(self, student_id: str, isbn_ordered: str):
        student = self._get_student(student_id)
        student.pending_order_isbn = isbn_ordered

    def apply_validated_pick_action(self, date_str: str, student_id: str, book_copy_id_picked: str):
        book_copy = self._get_book_copy(book_copy_id_picked)
        student = self._get_student(student_id)
        if not book_copy or not self.current_date_obj: return

        student.reserved_book_copy_id_at_ao = None
        student.pickup_deadline_for_reserved_book = None
        
        loan_period = self.LOAN_PERIOD_B if book_copy.type == 'B' else self.LOAN_PERIOD_C
        due_date = self.current_date_obj + timedelta(days=loan_period)

        if book_copy.type == 'B':
            student.held_b_book = (book_copy_id_picked, due_date)
        elif book_copy.type == 'C':
            student.held_c_books_by_isbn[book_copy.isbn] = (book_copy_id_picked, due_date)

        self._apply_book_movement(book_copy_id_picked, "appointment_office", "user", date_str,
                                  target_student_id_for_user_or_reader=student_id)

    def apply_validated_read_action(self, date_str: str, student_id: str, book_copy_id_read: str):
        book_copy = self._get_book_copy(book_copy_id_read)
        student = self._get_student(student_id)
        if not book_copy: return

        from_location = book_copy.current_location
        if from_location not in self.SHELF_LOCATIONS: return

        self._apply_book_movement(book_copy_id_read, from_location, "reading_room", date_str,
                                  target_student_id_for_user_or_reader=student_id)
        
        student.reading_book_copy_id_today = book_copy_id_read
        student.has_generated_restore_for_current_read = False
        
        self.isbns_becoming_hot_this_open_period.add(book_copy.isbn)

    def apply_validated_restore_action(self, date_str: str, student_id: str, book_copy_id_restored: str):
        book_copy = self._get_book_copy(book_copy_id_restored)
        student = self._get_student(student_id)
        if not book_copy: return

        self._apply_book_movement(book_copy_id_restored, "reading_room", "borrow_return_office", date_str,
                                   target_student_id_for_user_or_reader=student_id)
        
        if student.reading_book_copy_id_today == book_copy_id_restored:
            student.reading_book_copy_id_today = None
            student._update_credit(self.CREDIT_SAME_DAY_RESTORE)

    def apply_book_reservation_at_ao(self, book_id: str, student_id: str, pickup_deadline: date, is_opening_tidy: bool):
        book_copy = self._get_book_copy(book_id)
        student = self._get_student(student_id)
        if not book_copy or not student: return
        student.pending_order_isbn = None
        student.reserved_book_copy_id_at_ao = book_id
        student.pickup_deadline_for_reserved_book = pickup_deadline

    def clear_expired_ao_reservation_for_book(self, book_id: str):
        book_copy = self._get_book_copy(book_id)
        if not book_copy: return
        reserved_student_id = book_copy.ao_reserved_for_student_id
        if reserved_student_id:
            student = self._get_student(reserved_student_id)
            if student.reserved_book_copy_id_at_ao == book_id:
                student.reserved_book_copy_id_at_ao = None
                student.pickup_deadline_for_reserved_book = None
        book_copy.ao_reserved_for_student_id = None
        book_copy.ao_pickup_deadline = None

    def get_book_copy_details_for_trace(self, book_id_to_query: str) -> Optional[List[Tuple[str,str,str]]]:
        book_copy = self._get_book_copy(book_id_to_query)
        if not book_copy: return None
        return list(book_copy.trace)