# state.py
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple, Set

class BookCopy:
    """Represents a single physical copy of a book."""
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
        return (f"BookCopy(id='{self.id}', isbn='{self.isbn}', type='{self.type}', loc='{self.current_location}', "
                f"holder='{self.current_holder_student_id}', "
                f"ao_res_for='{self.ao_reserved_for_student_id}', "
                f"ao_deadline='{self.ao_pickup_deadline}')")

class Student:
    """Represents a library user."""
    def __init__(self, student_id: str):
        self.id: str = student_id
        self.held_b_book_copy_id: Optional[str] = None
        self.held_c_books_by_isbn: Dict[str, str] = {}
        self.pending_order_isbn: Optional[str] = None
        self.reserved_book_copy_id_at_ao: Optional[str] = None
        self.pickup_deadline_for_reserved_book: Optional[date] = None
        
        self.reading_book_copy_id_today: Optional[str] = None
        # NEW FLAG: Tracks if a 'restored' command has been generated for the current read
        self.has_generated_restore_for_current_read: bool = False

    def __repr__(self):
        return (f"Student(id='{self.id}', b_held='{self.held_b_book_copy_id}', "
                f"c_held_isbns='{list(self.held_c_books_by_isbn.keys())}', "
                f"pending_order='{self.pending_order_isbn}', "
                f"reserved_at_ao='{self.reserved_book_copy_id_at_ao}', "
                f"reading_today='{self.reading_book_copy_id_today}', "
                f"restore_gen='{self.has_generated_restore_for_current_read}')") # Added new flag to repr

class LibrarySystem:
    """Manages the library's state. Applies changes validated by the checker."""

    LOCATION_SHORT_MAP = {
        "bookshelf": "bs",
        "hot_bookshelf": "hbs",
        "borrow_return_office": "bro",
        "appointment_office": "ao",
        "reading_room": "rr",
        "user": "user"
    }
    REVERSE_LOCATION_SHORT_MAP = {v: k for k, v in LOCATION_SHORT_MAP.items()}
    SHELF_LOCATIONS = ["bookshelf", "hot_bookshelf"]
    TIDY_INTERNAL_LOCATIONS = ["bookshelf", "hot_bookshelf", "borrow_return_office", "appointment_office", "reading_room"]

    def __init__(self):
        self.all_book_copies: Dict[str, BookCopy] = {}
        self.students: Dict[str, Student] = {}
        self.books_on_shelf_by_isbn: Dict[str, List[str]] = {}
        self.current_date_str: str = ""
        self.current_date_obj: Optional[date] = None
        self.hot_isbns_for_current_open_tidy: Set[str] = set()
        self.isbns_becoming_hot_this_open_period: Set[str] = set()

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
            if book_copy.type == 'B' and student.held_b_book_copy_id == book_id:
                student.held_b_book_copy_id = None
            elif book_copy.type == 'C' and student.held_c_books_by_isbn.get(isbn) == book_id:
                if isbn in student.held_c_books_by_isbn:
                    del student.held_c_books_by_isbn[isbn]

        if new_location_full in self.SHELF_LOCATIONS:
            if isbn not in self.books_on_shelf_by_isbn:
                self.books_on_shelf_by_isbn[isbn] = []
            if book_id not in self.books_on_shelf_by_isbn[isbn]:
                 self.books_on_shelf_by_isbn[isbn].append(book_id)
            self.books_on_shelf_by_isbn[isbn].sort(key=lambda bid: self.all_book_copies[bid].copy_num)
        elif new_location_full == "user" and new_holder_student_id:
            student = self._get_student(new_holder_student_id)
            if book_copy.type == 'B': student.held_b_book_copy_id = book_id
            elif book_copy.type == 'C': student.held_c_books_by_isbn[isbn] = book_id

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
        
        new_holder_for_datastructure = target_student_id_for_user_or_reader if to_location_full == "user" else None
        self._update_book_location_datastructures(book_copy, old_location_full, to_location_full,
                                                  old_holder_student_id=old_holder_student_id, 
                                                  new_holder_student_id=new_holder_for_datastructure)
        
        book_copy.current_location = to_location_full
        if to_location_full == "user" or to_location_full == "reading_room":
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
        self.current_date_str = date_str
        self.current_date_obj = self._parse_date(date_str)
        self.hot_isbns_for_current_open_tidy = self.isbns_becoming_hot_this_open_period.copy()
        self.isbns_becoming_hot_this_open_period.clear()

        for student in self.students.values():
            student.reading_book_copy_id_today = None
            student.has_generated_restore_for_current_read = False # Reset flag on OPEN

    def apply_close_action(self, date_str: str):
        # On CLOSE, clear daily reading states for the next day's OPEN.
        # The actual reset for generation purposes happens in the next OPEN.
        for student in self.students.values():
            student.reading_book_copy_id_today = None
            # If a student was reading but didn't restore, the book remains in 'reading_room'
            # but their 'reading_book_copy_id_today' and flag are reset at the next OPEN.
            # For consistency, we can also clear the flag here if desired, though OPEN handles it.
            # student.reading_book_copy_id_today = None # This might be too aggressive if SUT expects it to persist until next OPEN
            student.has_generated_restore_for_current_read = False # Reset flag on CLOSE as well

    def apply_validated_borrow_action(self, date_str: str, student_id: str, book_copy_id_borrowed: str):
        book_copy = self._get_book_copy(book_copy_id_borrowed)
        if not book_copy: return
        from_location = book_copy.current_location 
        if from_location not in self.SHELF_LOCATIONS: return
        self._apply_book_movement(book_copy_id_borrowed, from_location, "user", date_str,
                                  target_student_id_for_user_or_reader=student_id)
        self.isbns_becoming_hot_this_open_period.add(book_copy.isbn)

    def apply_validated_return_action(self, date_str: str, student_id: str, book_copy_id_returned: str):
        book_copy = self._get_book_copy(book_copy_id_returned)
        if not book_copy: return
        self._apply_book_movement(book_copy_id_returned, "user", "borrow_return_office", date_str,
                                  target_student_id_for_user_or_reader=student_id)

    def apply_validated_order_action(self, student_id: str, isbn_ordered: str):
        student = self._get_student(student_id)
        student.pending_order_isbn = isbn_ordered

    def apply_validated_pick_action(self, date_str: str, student_id: str, book_copy_id_picked: str):
        book_copy = self._get_book_copy(book_copy_id_picked)
        student = self._get_student(student_id)
        if not book_copy: return
        student.reserved_book_copy_id_at_ao = None
        student.pickup_deadline_for_reserved_book = None
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
        # When a new read starts, reset the flag for this specific read
        student.has_generated_restore_for_current_read = False
        
        self.isbns_becoming_hot_this_open_period.add(book_copy.isbn)

    def apply_validated_restore_action(self, date_str: str, student_id: str, book_copy_id_restored: str):
        # This method is called by the checker AFTER a restore command from SUT is validated.
        # Gen.py will NOT call this. Gen.py will only *set* the student.has_generated_restore_for_current_read flag.
        book_copy = self._get_book_copy(book_copy_id_restored)
        student = self._get_student(student_id)
        if not book_copy: return

        self._apply_book_movement(book_copy_id_restored, "reading_room", "borrow_return_office", date_str,
                                   target_student_id_for_user_or_reader=student_id)
        
        if student.reading_book_copy_id_today == book_copy_id_restored:
            student.reading_book_copy_id_today = None
            # The flag student.has_generated_restore_for_current_read would have been set by gen.py
            # when it *generated* the restore command.
            # Here, upon actual successful restoration, the reading session ends.
            # The flag is reset by OPEN/CLOSE or a new READ.
            # No need to change has_generated_restore_for_current_read here, as its purpose
            # is to prevent gen.py from generating multiple restores for the *same* reading session.
            pass


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