# state.py
from datetime import date, timedelta

class BookCopy:
    """Represents a single physical copy of a book."""
    def __init__(self, book_id: str, isbn: str, book_type: str, copy_num: int):
        self.id: str = book_id
        self.isbn: str = isbn
        self.type: str = book_type  # 'A', 'B', or 'C'
        self.copy_num: int = copy_num

        self.current_location: str = "bookshelf"  # "bookshelf", "bro", "ao", "user"
        self.current_holder_student_id: str | None = None

        self.ao_reserved_for_student_id: str | None = None
        self.ao_pickup_deadline: date | None = None

        self.trace: list[tuple[str, str, str]] = []

    def __repr__(self):
        return (f"BookCopy(id='{self.id}', loc='{self.current_location}', "
                f"holder='{self.current_holder_student_id}', "
                f"ao_res_for='{self.ao_reserved_for_student_id}', "
                f"ao_deadline='{self.ao_pickup_deadline}')")

class Student:
    """Represents a library user."""
    def __init__(self, student_id: str):
        self.id: str = student_id
        self.held_b_book_copy_id: str | None = None
        self.held_c_books_by_isbn: dict[str, str] = {} # ISBN -> book_id

        self.pending_order_isbn: str | None = None
        self.reserved_book_copy_id_at_ao: str | None = None
        self.pickup_deadline_for_reserved_book: date | None = None

    def __repr__(self):
        return (f"Student(id='{self.id}', b_held='{self.held_b_book_copy_id}', "
                f"c_held_isbns='{list(self.held_c_books_by_isbn.keys())}', "
                f"pending_order='{self.pending_order_isbn}', "
                f"reserved_at_ao='{self.reserved_book_copy_id_at_ao}')")

class LibrarySystem:
    """Manages the library's state. Applies changes validated by the checker."""

    LOCATION_SHORT_MAP = {
        "bookshelf": "bs",
        "borrow_return_office": "bro",
        "appointment_office": "ao",
        "user": "user"
    }
    REVERSE_LOCATION_SHORT_MAP = {v: k for k, v in LOCATION_SHORT_MAP.items()}


    def __init__(self):
        self.all_book_copies: dict[str, BookCopy] = {}
        self.students: dict[str, Student] = {}
        self.books_on_shelf_by_isbn: dict[str, list[str]] = {}

        self.current_date_str: str = ""
        self.current_date_obj: date | None = None
        # output_buffer is removed as SUT controls output timing.
        # Checker will validate SUT output directly.

    def _parse_date(self, date_str: str) -> date:
        return date.fromisoformat(date_str)

    def _get_student(self, student_id: str) -> Student:
        if student_id not in self.students:
            self.students[student_id] = Student(student_id)
        return self.students[student_id]

    def _get_book_copy(self, book_id: str) -> BookCopy | None:
        return self.all_book_copies.get(book_id)

    def _get_book_type_from_id_or_isbn(self, id_or_isbn: str) -> str:
        return id_or_isbn[0]

    def initialize_books(self, book_lines: list[str]):
        for line in book_lines:
            isbn_str, count_str = line.split()
            count = int(count_str)
            book_type = self._get_book_type_from_id_or_isbn(isbn_str)
            
            self.books_on_shelf_by_isbn[isbn_str] = []
            for i in range(1, count + 1):
                copy_num_str = f"{i:02d}"
                book_id = f"{isbn_str}-{copy_num_str}"
                
                book_copy = BookCopy(book_id, isbn_str, book_type, i)
                self.all_book_copies[book_id] = book_copy
                self.books_on_shelf_by_isbn[isbn_str].append(book_id)
        # Initial sort by copy_num is implicit, but good to ensure if needed later
        for isbn in self.books_on_shelf_by_isbn:
            self.books_on_shelf_by_isbn[isbn].sort(key=lambda bid: self.all_book_copies[bid].copy_num)


    def _record_move_in_trace(self, book_copy: BookCopy, from_location_full: str, to_location_full: str, date_str: str):
        if from_location_full != to_location_full:
            from_short = self.LOCATION_SHORT_MAP[from_location_full]
            to_short = self.LOCATION_SHORT_MAP[to_location_full]
            book_copy.trace.append((date_str, from_short, to_short))

    def _update_book_location_datastructures(self, book_copy: BookCopy, old_location_full: str, new_location_full: str, 
                                            old_holder_student_id: str | None = None, 
                                            new_holder_student_id: str | None = None):
        book_id = book_copy.id
        isbn = book_copy.isbn

        if old_location_full == "bookshelf":
            if isbn in self.books_on_shelf_by_isbn and book_id in self.books_on_shelf_by_isbn[isbn]:
                self.books_on_shelf_by_isbn[isbn].remove(book_id)
        elif old_location_full == "user" and old_holder_student_id:
            student = self._get_student(old_holder_student_id)
            if book_copy.type == 'B' and student.held_b_book_copy_id == book_id:
                student.held_b_book_copy_id = None
            elif book_copy.type == 'C' and student.held_c_books_by_isbn.get(isbn) == book_id:
                del student.held_c_books_by_isbn[isbn]
        
        if new_location_full == "bookshelf":
            if isbn not in self.books_on_shelf_by_isbn: self.books_on_shelf_by_isbn[isbn] = []
            if book_id not in self.books_on_shelf_by_isbn[isbn]:
                 self.books_on_shelf_by_isbn[isbn].append(book_id)
            self.books_on_shelf_by_isbn[isbn].sort(key=lambda bid: self.all_book_copies[bid].copy_num)
        elif new_location_full == "user" and new_holder_student_id:
            student = self._get_student(new_holder_student_id)
            if book_copy.type == 'B': student.held_b_book_copy_id = book_id
            elif book_copy.type == 'C': student.held_c_books_by_isbn[isbn] = book_id

    def _apply_book_movement(self, book_id: str, 
                            from_location_full: str, # Checker must verify this was the actual old location
                            to_location_full: str, 
                            date_str: str, 
                            target_student_id_for_user: str | None = None, 
                            ao_reservation_student_id: str | None = None, 
                            ao_pickup_deadline: date | None = None):
        """
        Low-level method to apply a validated book movement.
        Assumes 'from_location_full' is correct as per current state before this call.
        The checker is responsible for ensuring the move is valid according to rules.
        """
        book_copy = self._get_book_copy(book_id)
        if not book_copy: return # Should be caught by checker

        # Ensure from_location_full matches book's current state
        # This is a sanity check; primary validation is in checker.
        if book_copy.current_location != from_location_full:
            # This would indicate a severe desync or checker error
            print(f"STATE SYNC ERROR: _apply_book_movement called for {book_id} from {from_location_full}, "
                  f"but book is at {book_copy.current_location}.")
            return 
            
        old_location_full = book_copy.current_location # Should be same as from_location_full
        old_holder_student_id = book_copy.current_holder_student_id
        
        self._record_move_in_trace(book_copy, old_location_full, to_location_full, date_str)
        
        self._update_book_location_datastructures(book_copy, old_location_full, to_location_full,
                                                  old_holder_student_id=old_holder_student_id, 
                                                  new_holder_student_id=target_student_id_for_user)
        
        book_copy.current_location = to_location_full
        if to_location_full == "user":
            book_copy.current_holder_student_id = target_student_id_for_user
            book_copy.ao_reserved_for_student_id = None 
            book_copy.ao_pickup_deadline = None
        else:
            book_copy.current_holder_student_id = None

        if to_location_full == "appointment_office":
            book_copy.ao_reserved_for_student_id = ao_reservation_student_id
            book_copy.ao_pickup_deadline = ao_pickup_deadline
        elif book_copy.current_location != "appointment_office": # Moved out of AO
            book_copy.ao_reserved_for_student_id = None
            book_copy.ao_pickup_deadline = None

    # --- Methods for applying SUT's validated actions ---

    def apply_open_action(self, date_str: str):
        """Applies state changes for an OPEN command day start."""
        self.current_date_str = date_str
        self.current_date_obj = self._parse_date(date_str)

    def apply_close_action(self, date_str: str):
        """Applies state changes for a CLOSE command day end. (Date already set by OPEN)"""
        # Primarily, this might be relevant if there were any date-dependent logic
        # that state itself needs to finalize, independent of SUT's tidying moves.
        # For now, mainly a marker.
        pass

    def apply_validated_borrow_action(self, date_str: str, student_id: str, book_copy_id_borrowed: str):
        book_copy = self._get_book_copy(book_copy_id_borrowed)
        if not book_copy: return
        
        # Move is from bookshelf to user
        self._apply_book_movement(book_copy_id_borrowed, "bookshelf", "user", date_str,
                                  target_student_id_for_user=student_id)
        
        # Student state update (also handled by _update_book_location_datastructures -> new_holder)
        # Redundant explicit update here, but harmless.
        student = self._get_student(student_id)
        if book_copy.type == 'B': student.held_b_book_copy_id = book_copy_id_borrowed
        elif book_copy.type == 'C': student.held_c_books_by_isbn[book_copy.isbn] = book_copy_id_borrowed


    def apply_validated_return_action(self, date_str: str, student_id: str, book_copy_id_returned: str):
        book_copy = self._get_book_copy(book_copy_id_returned)
        if not book_copy: return
        
        # Student state update (also handled by _update_book_location_datastructures -> old_holder)
        student = self._get_student(student_id)
        if book_copy.type == 'B' and student.held_b_book_copy_id == book_copy_id_returned:
            student.held_b_book_copy_id = None
        elif book_copy.type == 'C' and student.held_c_books_by_isbn.get(book_copy.isbn) == book_copy_id_returned:
            del student.held_c_books_by_isbn[book_copy.isbn]
            
        # Move is from user to borrow_return_office
        self._apply_book_movement(book_copy_id_returned, "user", "borrow_return_office", date_str)


    def apply_validated_order_action(self, student_id: str, isbn_ordered: str):
        student = self._get_student(student_id)
        student.pending_order_isbn = isbn_ordered
        # No book movement here, only student state change.

    def apply_validated_pick_action(self, date_str: str, student_id: str, book_copy_id_picked: str):
        book_copy = self._get_book_copy(book_copy_id_picked)
        student = self._get_student(student_id)
        if not book_copy: return

        # Student clears their AO reservation details
        student.reserved_book_copy_id_at_ao = None
        student.pickup_deadline_for_reserved_book = None
        
        # Move is from appointment_office to user
        self._apply_book_movement(book_copy_id_picked, "appointment_office", "user", date_str,
                                  target_student_id_for_user=student_id)
        
        # Student holding state update (also handled by _update_book_location_datastructures -> new_holder)
        if book_copy.type == 'B': student.held_b_book_copy_id = book_copy_id_picked
        elif book_copy.type == 'C': student.held_c_books_by_isbn[book_copy.isbn] = book_copy_id_picked


    def apply_validated_tidy_move_action(self, date_str: str, book_id: str, 
                                         from_loc_short: str, to_loc_short: str, 
                                         target_student_id_for_ao: str | None):
        """Applies a single validated tidying move from SUT's output."""
        from_location_full = self.REVERSE_LOCATION_SHORT_MAP.get(from_loc_short)
        to_location_full = self.REVERSE_LOCATION_SHORT_MAP.get(to_loc_short)

        if not from_location_full or not to_location_full: return # Invalid short codes

        book_copy = self._get_book_copy(book_id)
        if not book_copy: return

        ao_deadline = None
        # If moving to AO for a student, calculate deadline based on current date
        # This logic needs to be robust if checker has already validated this deadline.
        # For now, state.py will re-calculate if it's moving to AO.
        # Problem states: "若在开馆后整理中送达，则从当日保留5天"
        # "若在闭馆后整理中送达，从次日保留5天"
        # This depends on whether it's an OPEN or CLOSE tidy move.
        # The checker should determine if target_student_id_for_ao is valid for this move.
        # And should also determine the *correct* deadline SUT should be adhering to.
        # Let's assume for now checker has validated the move AND the deadline implicit in it.
        # State.py will need to be told the deadline if book is moved to AO.

        if to_location_full == "appointment_office" and target_student_id_for_ao:
            student = self._get_student(target_student_id_for_ao)
            # The checker must have verified the SUT's deadline logic.
            # For now, we will assume the student's pickup_deadline_for_reserved_book
            # would be set by the checker if this move fulfills an order.
            # This is a tricky part of separating validation and state update.
            # Let's make apply_validated_tidy_move_action take the deadline.
            
            # The checker needs to calculate the deadline that *should* be set
            # based on problem rules (5 days from today/tomorrow) and pass it here.
            # For now, this state update is simplified.
            # The student object's AO reservation fields MUST be updated after this move by the checker logic.
            
            # This simplified version just moves the book. The student's AO reservation status
            # (reserved_book_copy_id_at_ao, pickup_deadline_for_reserved_book) and
            # book's (ao_reserved_for_student_id, ao_pickup_deadline) needs careful handling.
            pass # Deferring complex deadline logic to checker, which will call specific methods.


        # Simplified: assume checker passes all necessary details for _apply_book_movement
        # For a move TO AO for reservation, the checker must also update student state
        # and provide ao_reservation_student_id and ao_pickup_deadline.
        
        # If a book is moved to AO for a student, update student state too
        if to_location_full == "appointment_office" and target_student_id_for_ao:
            student_obj = self._get_student(target_student_id_for_ao)
            student_obj.pending_order_isbn = None # Order fulfilled
            # student_obj.reserved_book_copy_id_at_ao = book_id # Set by checker
            # student_obj.pickup_deadline_for_reserved_book = ... # Set by checker

        # If a book reserved at AO becomes overdue and is moved out by SUT:
        if from_location_full == "appointment_office" and book_copy.ao_reserved_for_student_id:
            reserved_student = self._get_student(book_copy.ao_reserved_for_student_id)
            if reserved_student.reserved_book_copy_id_at_ao == book_id:
                reserved_student.reserved_book_copy_id_at_ao = None
                reserved_student.pickup_deadline_for_reserved_book = None
        
        # This is a generic move.
        # If target is AO for a specific student, the checker needs to handle setting the ao_deadline on the book.
        # And updating student's reserved_book_copy_id_at_ao and pickup_deadline_for_reserved_book.
        # Let's assume for now that if it's a move to AO for reservation, checker calls a more specific method.

        # Let's assume the checker will call apply_book_reservation_at_ao after this for moves to AO.
        self._apply_book_movement(book_id, from_location_full, to_location_full, date_str,
                                  ao_reservation_student_id = target_student_id_for_ao if to_location_full == "appointment_office" else None,
                                  # ao_pickup_deadline needs to be passed if moving to AO for reservation
                                  )


    def apply_book_reservation_at_ao(self, book_id: str, student_id: str, pickup_deadline: date, is_opening_tidy: bool):
        """Called by checker after a validated move to AO for reservation."""
        book_copy = self._get_book_copy(book_id)
        student = self._get_student(student_id)
        if not book_copy or not student: return

        book_copy.ao_reserved_for_student_id = student_id
        book_copy.ao_pickup_deadline = pickup_deadline
        
        student.pending_order_isbn = None # Order is now fulfilled at AO
        student.reserved_book_copy_id_at_ao = book_id
        student.pickup_deadline_for_reserved_book = pickup_deadline

    def clear_expired_ao_reservation_for_book(self, book_id: str):
        """Called by checker if SUT moves an expired book from AO or if it implies expiry."""
        book_copy = self._get_book_copy(book_id)
        if not book_copy or book_copy.current_location != "appointment_office": return

        if book_copy.ao_reserved_for_student_id:
            student = self._get_student(book_copy.ao_reserved_for_student_id)
            if student.reserved_book_copy_id_at_ao == book_id:
                student.reserved_book_copy_id_at_ao = None
                student.pickup_deadline_for_reserved_book = None
        
        book_copy.ao_reserved_for_student_id = None
        book_copy.ao_pickup_deadline = None

    def get_book_copy_details_for_trace(self, book_id_to_query: str) -> list[tuple[str,str,str]] | None:
        book_copy = self._get_book_copy(book_id_to_query)
        if not book_copy:
            return None
        return list(book_copy.trace) # Return a copy