# checker.py
import io
import sys
import json
import copy
from datetime import date, timedelta

try:
    from state import LibrarySystem, BookCopy, Student
except ImportError:
    print(json.dumps({"is_legal": False, "error_message": "Critical Checker Error: Could not import from state.py."}))
    sys.exit(1)

# --- SUT Output Parsers ---
def parse_sut_user_op_line(line: str) -> dict | None:
    parts = line.split()
    if len(parts) != 5: return None
    if not (parts[0].startswith("[") and parts[0].endswith("]") and
            parts[1].startswith("[") and parts[1].endswith("]")): return None
    date_str = parts[0][1:-1]
    try:
        date.fromisoformat(date_str)
    except ValueError: return None
    status = parts[1][1:-1]
    if status not in ["accept", "reject"]: return None
    return {"date_str": date_str, "status": status, "student_id": parts[2], "action": parts[3], "target_str": parts[4]}

def parse_sut_query_header_line(line: str) -> tuple[str, str, int] | None:
    parts = line.split()
    if len(parts) != 5 or parts[2] != "moving" or parts[3] != "trace:": return None
    if not (parts[0].startswith("[") and parts[0].endswith("]")): return None
    date_str = parts[0][1:-1]
    try: date.fromisoformat(date_str)
    except ValueError: return None
    book_copy_id_sut = parts[1]
    try:
        trace_count = int(parts[4])
        if trace_count < 0: return None
    except ValueError: return None
    return date_str, book_copy_id_sut, trace_count

def parse_sut_query_trace_detail_line(line: str) -> tuple[int, str, str, str] | None:
    parts = line.split()
    if len(parts) != 6 or parts[2] != "from" or parts[4] != "to": return None
    try: seq_num = int(parts[0])
    except ValueError: return None
    if not (parts[1].startswith("[") and parts[1].endswith("]")): return None
    date_str = parts[1][1:-1]
    try: date.fromisoformat(date_str)
    except ValueError: return None
    from_loc_short, to_loc_short = parts[3], parts[5]
    valid_short_locs = LibrarySystem.LOCATION_SHORT_MAP.values()
    if from_loc_short not in valid_short_locs or to_loc_short not in valid_short_locs: return None
    return seq_num, date_str, from_loc_short, to_loc_short

def parse_sut_tidy_move_line(line: str) -> dict | None:
    parts = line.split()
    if not (len(parts) == 7 or len(parts) == 9): return None
    if not (parts[0].startswith("[") and parts[0].endswith("]") and parts[1] == "move" and parts[3] == "from" and parts[5] == "to"): return None
    date_str = parts[0][1:-1]
    try: date.fromisoformat(date_str)
    except ValueError: return None
    book_copy_id, from_loc_short, to_loc_short = parts[2], parts[4], parts[6]
    valid_tidy_locs_short = [LibrarySystem.LOCATION_SHORT_MAP[loc] for loc in ["bookshelf", "borrow_return_office", "appointment_office"]]
    if from_loc_short not in valid_tidy_locs_short or to_loc_short not in valid_tidy_locs_short: return None
    target_student_for_ao = None
    if len(parts) == 9:
        if parts[7] != "for": return None
        target_student_for_ao = parts[8]
        if to_loc_short != LibrarySystem.LOCATION_SHORT_MAP["appointment_office"]: return None # "for" only allowed if target is AO
    elif to_loc_short == LibrarySystem.LOCATION_SHORT_MAP["appointment_office"]: return None # Target AO must have "for"
    return {"date_str": date_str, "book_copy_id": book_copy_id, "from_loc_short": from_loc_short, "to_loc_short": to_loc_short, "target_student_for_ao": target_student_for_ao}

def _is_isbn_like(target_str: str) -> bool:
    # Example: B-0001
    parts = target_str.split('-')
    if len(parts) != 2: return False
    if not (len(parts[0]) == 1 and parts[0] in "ABC"): return False # Type
    if not (len(parts[1]) == 4 and parts[1].isdigit()): return False # Sequence
    return True


def _is_book_copy_id_like(target_str: str) -> bool:
    # Example: B-0001-01
    parts = target_str.split('-')
    if len(parts) != 3: return False
    if not (len(parts[0]) == 1 and parts[0] in "ABC"): return False # Type
    if not (len(parts[1]) == 4 and parts[1].isdigit()): return False # Sequence
    if not (len(parts[2]) >= 1 and parts[2].isdigit()): return False # Copy number (at least 1 digit, e.g. '1' or '01')
    try:
        copy_num_int = int(parts[2])
        if not (1 <= copy_num_int <= 99): # Allow up to 99 for flexibility, though problem says max 10
             pass
    except ValueError:
        return False
    return True


class RuleChecker:
    def __init__(self, library_state: LibrarySystem):
        self.current_state = library_state

    def _get_book_copy(self, book_id: str) -> BookCopy | None:
        return self.current_state._get_book_copy(book_id)

    def _get_student(self, student_id: str) -> Student:
        return self.current_state._get_student(student_id)

    def validate_sut_borrow(self, cmd_date_str:str, cmd_student_id: str, cmd_isbn: str, sut_output_line: str):
        parsed_sut = parse_sut_user_op_line(sut_output_line)

        # --- Step 1: Basic Parsing and Context Matching ---
        if not parsed_sut:
            return {"is_legal": False, "error_message": f"Format Error (Borrow): SUT output line '{sut_output_line}' is malformed and cannot be parsed as a standard operation response."}
        if parsed_sut["action"] != "borrowed":
            return {"is_legal": False, "error_message": f"Context Error (Borrow): SUT output action is '{parsed_sut['action']}', expected 'borrowed'. SUT line: '{sut_output_line}'."}
        if parsed_sut["student_id"] != cmd_student_id:
            return {"is_legal": False, "error_message": f"Context Error (Borrow): SUT output student ID is '{parsed_sut['student_id']}', expected '{cmd_student_id}'. SUT line: '{sut_output_line}'."}
        if parsed_sut["date_str"] != cmd_date_str:
            return {"is_legal": False, "error_message": f"Context Error (Borrow): SUT output date is '{parsed_sut['date_str']}', expected '{cmd_date_str}'. SUT line: '{sut_output_line}'."}

        sut_target_str = parsed_sut["target_str"]

        # --- Step 2: Target Format and Content Validation (depends on SUT status) ---
        if parsed_sut["status"] == "reject":
            if not _is_isbn_like(sut_target_str):
                return {"is_legal": False, "error_message": f"Format Error (Borrow Reject): SUT target '{sut_target_str}' is not in valid ISBN format (e.g., TYPE-SEQ). Expected command ISBN '{cmd_isbn}'. SUT line: '{sut_output_line}'."}
            if sut_target_str != cmd_isbn:
                return {"is_legal": False, "error_message": f"Format Error (Borrow Reject): SUT rejected for ISBN '{sut_target_str}', but command was for ISBN '{cmd_isbn}'. SUT line: '{sut_output_line}'."}

            student = self._get_student(cmd_student_id)
            book_type_to_borrow = self.current_state._get_book_type_from_id_or_isbn(cmd_isbn)
            can_be_borrowed_by_rule = True; rejection_reason_checker = "Checker finds borrow permissible."
            if book_type_to_borrow == 'A':
                can_be_borrowed_by_rule = False; rejection_reason_checker = "Book is Type A (cannot be borrowed)."
            elif not self.current_state.books_on_shelf_by_isbn.get(cmd_isbn) or \
                 not any(self._get_book_copy(bc_id).current_location == "bookshelf" for bc_id in self.current_state.books_on_shelf_by_isbn.get(cmd_isbn, [])):
                can_be_borrowed_by_rule = False; rejection_reason_checker = f"No copies of ISBN '{cmd_isbn}' are currently on the bookshelf."
            elif book_type_to_borrow == 'B' and student.held_b_book_copy_id is not None:
                can_be_borrowed_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already holds a B-type book ('{student.held_b_book_copy_id}')."
            elif book_type_to_borrow == 'C' and cmd_isbn in student.held_c_books_by_isbn:
                can_be_borrowed_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already holds a copy of this C-type ISBN '{cmd_isbn}' ('{student.held_c_books_by_isbn[cmd_isbn]}')."

            if not can_be_borrowed_by_rule:
                return {"is_legal": True} 
            else:
                return {"is_legal": False, "error_message": f"Logic Error (Borrow Reject): SUT rejected borrow of '{cmd_isbn}' by '{cmd_student_id}', but checker deems it permissible. Reason: {rejection_reason_checker} SUT line: '{sut_output_line}'."}

        elif parsed_sut["status"] == "accept":
            if not _is_book_copy_id_like(sut_target_str):
                err_detail = "is not in BookCopyID format (e.g., TYPE-SEQ-COPYNUM)."
                if _is_isbn_like(sut_target_str): err_detail = "is an ISBN; expected a specific BookCopyID."
                return {"is_legal": False, "error_message": f"Format Error (Borrow Accept): SUT target '{sut_target_str}' {err_detail} SUT line: '{sut_output_line}'."}

            sut_book_copy_id = sut_target_str 
            book_copy_sut_claims_to_lend = self._get_book_copy(sut_book_copy_id)

            if not book_copy_sut_claims_to_lend:
                return {"is_legal": False, "error_message": f"Logic Error (Borrow Accept): SUT accepted borrow with non-existent BookCopyID '{sut_book_copy_id}'. SUT line: '{sut_output_line}'."}
            if book_copy_sut_claims_to_lend.isbn != cmd_isbn:
                return {"is_legal": False, "error_message": f"Logic Error (Borrow Accept): SUT lent BookCopyID '{sut_book_copy_id}' (which is of ISBN '{book_copy_sut_claims_to_lend.isbn}'), but command was for ISBN '{cmd_isbn}'. SUT line: '{sut_output_line}'."}

            student = self._get_student(cmd_student_id)
            accept_error_reason = ""
            if book_copy_sut_claims_to_lend.type == 'A':
                accept_error_reason = f"Book '{sut_book_copy_id}' is Type A (cannot be borrowed)."
            elif book_copy_sut_claims_to_lend.current_location != "bookshelf":
                accept_error_reason = f"Book '{sut_book_copy_id}' was at location '{book_copy_sut_claims_to_lend.current_location}', not on 'bookshelf'."
            elif book_copy_sut_claims_to_lend.type == 'B' and student.held_b_book_copy_id is not None:
                accept_error_reason = f"Student '{cmd_student_id}' already holds a B-type book ('{student.held_b_book_copy_id}')."
            elif book_copy_sut_claims_to_lend.type == 'C' and book_copy_sut_claims_to_lend.isbn in student.held_c_books_by_isbn:
                accept_error_reason = f"Student '{cmd_student_id}' already holds a copy of this C-type ISBN '{cmd_isbn}' ('{student.held_c_books_by_isbn[cmd_isbn]}')."

            if accept_error_reason:
                return {"is_legal": False, "error_message": f"Logic Error (Borrow Accept): SUT accepted borrow of '{sut_book_copy_id}' by '{cmd_student_id}', but {accept_error_reason} SUT line: '{sut_output_line}'."}

            self.current_state.apply_validated_borrow_action(cmd_date_str, cmd_student_id, sut_book_copy_id)
            return {"is_legal": True}
        else: 
            return {"is_legal": False, "error_message": f"Internal Checker Error: Unknown SUT status '{parsed_sut['status']}' for borrow. SUT line: '{sut_output_line}'."}


    def validate_sut_return(self, cmd_date_str:str, cmd_student_id: str, cmd_book_copy_id: str, sut_output_line: str):
        parsed_sut = parse_sut_user_op_line(sut_output_line)

        if not parsed_sut:
            return {"is_legal": False, "error_message": f"Format Error (Return): SUT output line '{sut_output_line}' is malformed."}
        if parsed_sut["action"] != "returned":
            return {"is_legal": False, "error_message": f"Context Error (Return): SUT action is '{parsed_sut['action']}', expected 'returned'. SUT line: '{sut_output_line}'."}
        if parsed_sut["student_id"] != cmd_student_id:
            return {"is_legal": False, "error_message": f"Context Error (Return): SUT student ID is '{parsed_sut['student_id']}', expected '{cmd_student_id}'. SUT line: '{sut_output_line}'."}
        if parsed_sut["date_str"] != cmd_date_str:
            return {"is_legal": False, "error_message": f"Context Error (Return): SUT date is '{parsed_sut['date_str']}', expected '{cmd_date_str}'. SUT line: '{sut_output_line}'."}

        sut_target_str = parsed_sut["target_str"]

        if not _is_book_copy_id_like(sut_target_str):
            err_detail = "is not in BookCopyID format (e.g., TYPE-SEQ-COPYNUM)."
            if _is_isbn_like(sut_target_str): err_detail = "is an ISBN; expected a specific BookCopyID."
            return {"is_legal": False, "error_message": f"Format Error (Return): SUT target '{sut_target_str}' {err_detail} Expected command BookCopyID '{cmd_book_copy_id}'. SUT line: '{sut_output_line}'."}
        if sut_target_str != cmd_book_copy_id:
            return {"is_legal": False, "error_message": f"Format Error (Return): SUT returned BookCopyID '{sut_target_str}', but command was for BookCopyID '{cmd_book_copy_id}'. SUT line: '{sut_output_line}'."}

        if parsed_sut["status"] == "reject":
            # Problem implies return is always successful ("还书立即成功")
            return {"is_legal": False, "error_message": f"Logic Error (Return Reject): SUT rejected return of '{cmd_book_copy_id}' by '{cmd_student_id}'. Returns should always be accepted. SUT line: '{sut_output_line}'."}

        elif parsed_sut["status"] == "accept":
            book_copy_to_return = self._get_book_copy(cmd_book_copy_id) 
            if not book_copy_to_return: 
                return {"is_legal": False, "error_message": f"Logic Error (Return Accept): SUT accepted return of non-existent book '{cmd_book_copy_id}'. SUT line: '{sut_output_line}'."}

            if not (book_copy_to_return.current_location == "user" and book_copy_to_return.current_holder_student_id == cmd_student_id):
                 return {"is_legal": False, "error_message": (f"Logic Error (Return Accept): SUT accepted return of '{cmd_book_copy_id}' by '{cmd_student_id}', "
                                                              f"but book state is inconsistent. Expected: held by student at 'user'. "
                                                              f"Actual state: location='{book_copy_to_return.current_location}', holder='{book_copy_to_return.current_holder_student_id}'. SUT line: '{sut_output_line}'." )}
            self.current_state.apply_validated_return_action(cmd_date_str, cmd_student_id, cmd_book_copy_id)
            return {"is_legal": True}
        else: 
            return {"is_legal": False, "error_message": f"Internal Checker Error: Unknown SUT status '{parsed_sut['status']}' for return. SUT line: '{sut_output_line}'."}


    def validate_sut_order(self, cmd_date_str:str, cmd_student_id: str, cmd_isbn: str, sut_output_line: str):
        parsed_sut = parse_sut_user_op_line(sut_output_line)

        if not parsed_sut:
            return {"is_legal": False, "error_message": f"Format Error (Order): SUT output line '{sut_output_line}' is malformed."}
        if parsed_sut["action"] != "ordered":
            return {"is_legal": False, "error_message": f"Context Error (Order): SUT action is '{parsed_sut['action']}', expected 'ordered'. SUT line: '{sut_output_line}'."}
        if parsed_sut["student_id"] != cmd_student_id:
            return {"is_legal": False, "error_message": f"Context Error (Order): SUT student ID is '{parsed_sut['student_id']}', expected '{cmd_student_id}'. SUT line: '{sut_output_line}'."}
        if parsed_sut["date_str"] != cmd_date_str:
            return {"is_legal": False, "error_message": f"Context Error (Order): SUT date is '{parsed_sut['date_str']}', expected '{cmd_date_str}'. SUT line: '{sut_output_line}'."}

        sut_target_str = parsed_sut["target_str"]

        if not _is_isbn_like(sut_target_str):
            err_detail = "is not in ISBN format (e.g., TYPE-SEQ)."
            if _is_book_copy_id_like(sut_target_str): err_detail = "is a BookCopyID; expected an ISBN."
            return {"is_legal": False, "error_message": f"Format Error (Order): SUT target '{sut_target_str}' {err_detail} Expected command ISBN '{cmd_isbn}'. SUT line: '{sut_output_line}'."}
        if sut_target_str != cmd_isbn:
            return {"is_legal": False, "error_message": f"Format Error (Order): SUT processed order for ISBN '{sut_target_str}', but command was for ISBN '{cmd_isbn}'. SUT line: '{sut_output_line}'."}

        student = self._get_student(cmd_student_id)
        book_type_to_order = self.current_state._get_book_type_from_id_or_isbn(cmd_isbn)

        if parsed_sut["status"] == "reject":
            can_be_ordered_by_rule = True; rejection_reason_checker = "Checker finds order permissible."
            if book_type_to_order == 'A':
                can_be_ordered_by_rule = False; rejection_reason_checker = "Book is Type A (cannot be ordered)."
            elif student.pending_order_isbn is not None or student.reserved_book_copy_id_at_ao is not None:
                can_be_ordered_by_rule = False; rejection_reason_checker = (f"Student '{cmd_student_id}' already has a pending order ('{student.pending_order_isbn}') "
                                           f"or a reserved book at AO ('{student.reserved_book_copy_id_at_ao}').")
            elif book_type_to_order == 'B' and student.held_b_book_copy_id is not None:
                can_be_ordered_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already holds a B-type book ('{student.held_b_book_copy_id}') and cannot order another B-type."
            elif book_type_to_order == 'C' and cmd_isbn in student.held_c_books_by_isbn:
                can_be_ordered_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already holds a copy of this C-type ISBN '{cmd_isbn}' ('{student.held_c_books_by_isbn[cmd_isbn]}')."

            if not can_be_ordered_by_rule:
                return {"is_legal": True} 
            else:
                return {"is_legal": False, "error_message": f"Logic Error (Order Reject): SUT rejected order for '{cmd_isbn}' by '{cmd_student_id}', but checker deems it permissible. Reason: {rejection_reason_checker} SUT line: '{sut_output_line}'."}

        elif parsed_sut["status"] == "accept":
            accept_error_reason = ""
            if book_type_to_order == 'A':
                accept_error_reason = f"Book ISBN '{cmd_isbn}' is Type A (cannot be ordered)."
            elif student.pending_order_isbn is not None or student.reserved_book_copy_id_at_ao is not None:
                accept_error_reason = (f"Student '{cmd_student_id}' already has a pending order ('{student.pending_order_isbn}') "
                                       f"or a reserved book at AO ('{student.reserved_book_copy_id_at_ao}').")
            elif book_type_to_order == 'B' and student.held_b_book_copy_id is not None:
                accept_error_reason = f"Student '{cmd_student_id}' already holds a B-type book ('{student.held_b_book_copy_id}') and cannot order another B-type."
            elif book_type_to_order == 'C' and cmd_isbn in student.held_c_books_by_isbn:
                accept_error_reason = f"Student '{cmd_student_id}' already holds a copy of this C-type ISBN '{cmd_isbn}' ('{student.held_c_books_by_isbn[cmd_isbn]}')."

            if accept_error_reason:
                return {"is_legal": False, "error_message": f"Logic Error (Order Accept): SUT accepted order for '{cmd_isbn}' by '{cmd_student_id}', but {accept_error_reason} SUT line: '{sut_output_line}'."}

            self.current_state.apply_validated_order_action(cmd_student_id, cmd_isbn)
            return {"is_legal": True}
        else: 
            return {"is_legal": False, "error_message": f"Internal Checker Error: Unknown SUT status '{parsed_sut['status']}' for order. SUT line: '{sut_output_line}'."}


    def validate_sut_pick(self, cmd_date_str:str, cmd_student_id: str, cmd_isbn_to_pick: str, sut_output_line: str):
        parsed_sut = parse_sut_user_op_line(sut_output_line)
        current_date_obj = self.current_state.current_date_obj
        if not current_date_obj:
            return {"is_legal": False, "error_message": "Checker Internal Error: current_date_obj not set for pick validation."}

        if not parsed_sut:
            return {"is_legal": False, "error_message": f"Format Error (Pick): SUT output line '{sut_output_line}' is malformed."}
        if parsed_sut["action"] != "picked":
            return {"is_legal": False, "error_message": f"Context Error (Pick): SUT action is '{parsed_sut['action']}', expected 'picked'. SUT line: '{sut_output_line}'."}
        if parsed_sut["student_id"] != cmd_student_id:
            return {"is_legal": False, "error_message": f"Context Error (Pick): SUT student ID is '{parsed_sut['student_id']}', expected '{cmd_student_id}'. SUT line: '{sut_output_line}'."}
        if parsed_sut["date_str"] != cmd_date_str:
            return {"is_legal": False, "error_message": f"Context Error (Pick): SUT date is '{parsed_sut['date_str']}', expected '{cmd_date_str}'. SUT line: '{sut_output_line}'."}

        sut_target_str = parsed_sut["target_str"]
        student = self._get_student(cmd_student_id)

        if parsed_sut["status"] == "reject":
            if not _is_isbn_like(sut_target_str):
                err_detail = "is not in ISBN format (e.g., TYPE-SEQ)."
                if _is_book_copy_id_like(sut_target_str): err_detail = "is a BookCopyID; expected an ISBN."
                return {"is_legal": False, "error_message": f"Format Error (Pick Reject): SUT target '{sut_target_str}' {err_detail} Expected command ISBN '{cmd_isbn_to_pick}'. SUT line: '{sut_output_line}'."}
            if sut_target_str != cmd_isbn_to_pick:
                return {"is_legal": False, "error_message": f"Format Error (Pick Reject): SUT rejected pick for ISBN '{sut_target_str}', but command was for ISBN '{cmd_isbn_to_pick}'. SUT line: '{sut_output_line}'."}

            can_be_picked_by_rule = True; rejection_reason_checker = "Checker finds pick permissible."
            book_id_student_reserved = student.reserved_book_copy_id_at_ao
            if not book_id_student_reserved:
                can_be_picked_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' has no book reserved at AO."
            else:
                reserved_book_copy = self._get_book_copy(book_id_student_reserved)
                if not reserved_book_copy:
                     can_be_picked_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' has reservation for non-existent book '{book_id_student_reserved}' (internal state error)."
                elif reserved_book_copy.isbn != cmd_isbn_to_pick: 
                    can_be_picked_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' has book of ISBN '{reserved_book_copy.isbn}' reserved, but pick command is for different ISBN '{cmd_isbn_to_pick}'."
                elif reserved_book_copy.current_location != "appointment_office" or reserved_book_copy.ao_reserved_for_student_id != cmd_student_id:
                    can_be_picked_by_rule = False; rejection_reason_checker = f"Reserved book '{book_id_student_reserved}' is not at AO or not currently reserved for this student (loc: {reserved_book_copy.current_location}, res_for: {reserved_book_copy.ao_reserved_for_student_id})."
                elif student.pickup_deadline_for_reserved_book and current_date_obj > student.pickup_deadline_for_reserved_book:
                    can_be_picked_by_rule = False; rejection_reason_checker = f"Reservation for '{book_id_student_reserved}' by '{cmd_student_id}' expired on {student.pickup_deadline_for_reserved_book} (current date: {current_date_obj})."
                else: 
                    book_type_at_ao = reserved_book_copy.type
                    if book_type_at_ao == 'B' and student.held_b_book_copy_id is not None:
                        can_be_picked_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already holds a B-type book ('{student.held_b_book_copy_id}') and cannot pick another B-type."
                    elif book_type_at_ao == 'C' and cmd_isbn_to_pick in student.held_c_books_by_isbn:
                        can_be_picked_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already holds a copy of this C-type ISBN '{cmd_isbn_to_pick}' ('{student.held_c_books_by_isbn[cmd_isbn_to_pick]}')."

            if not can_be_picked_by_rule:
                return {"is_legal": True} 
            else:
                return {"is_legal": False, "error_message": f"Logic Error (Pick Reject): SUT rejected pick of '{cmd_isbn_to_pick}' by '{cmd_student_id}', but checker deems it permissible. Reason: {rejection_reason_checker} SUT line: '{sut_output_line}'."}

        elif parsed_sut["status"] == "accept":
            if not _is_book_copy_id_like(sut_target_str):
                err_detail = "is not in BookCopyID format (e.g., TYPE-SEQ-COPYNUM)."
                if _is_isbn_like(sut_target_str): err_detail = "is an ISBN; expected the specific BookCopyID reserved by student."
                return {"is_legal": False, "error_message": f"Format Error (Pick Accept): SUT target '{sut_target_str}' {err_detail} SUT line: '{sut_output_line}'."}

            sut_picked_book_copy_id = sut_target_str
            book_sut_claims_picked = self._get_book_copy(sut_picked_book_copy_id)

            if not book_sut_claims_picked:
                 return {"is_legal": False, "error_message": f"Logic Error (Pick Accept): SUT accepted pick of non-existent BookCopyID '{sut_picked_book_copy_id}'. SUT line: '{sut_output_line}'."}
            if book_sut_claims_picked.isbn != cmd_isbn_to_pick:
                 return {"is_legal": False, "error_message": f"Logic Error (Pick Accept): SUT picked BookCopyID '{sut_picked_book_copy_id}' (of ISBN '{book_sut_claims_picked.isbn}'), but command was for ISBN '{cmd_isbn_to_pick}'. SUT line: '{sut_output_line}'."}

            accept_error_reason = ""
            if student.reserved_book_copy_id_at_ao != sut_picked_book_copy_id:
                accept_error_reason = (f"SUT picked '{sut_picked_book_copy_id}', but student '{cmd_student_id}' had a different copy ID "
                                      f"'{student.reserved_book_copy_id_at_ao}' (for the same ISBN '{cmd_isbn_to_pick}') reserved at AO.")

            elif book_sut_claims_picked.current_location != "appointment_office" or book_sut_claims_picked.ao_reserved_for_student_id != cmd_student_id:
                accept_error_reason = (f"Book '{sut_picked_book_copy_id}' is not at AO or not currently reserved for student '{cmd_student_id}'. "
                                      f"(Actual loc: '{book_sut_claims_picked.current_location}', reserved_for: '{book_sut_claims_picked.ao_reserved_for_student_id}')")
            elif student.pickup_deadline_for_reserved_book and current_date_obj > student.pickup_deadline_for_reserved_book:
                accept_error_reason = f"Reservation for '{sut_picked_book_copy_id}' by '{cmd_student_id}' expired on {student.pickup_deadline_for_reserved_book} (current date: {current_date_obj})."
            else: 
                book_type_picked = book_sut_claims_picked.type
                if book_type_picked == 'B' and student.held_b_book_copy_id is not None:
                    accept_error_reason = f"Student '{cmd_student_id}' already holds a B-type book ('{student.held_b_book_copy_id}') and cannot pick another B-type."
                elif book_type_picked == 'C' and cmd_isbn_to_pick in student.held_c_books_by_isbn:
                    accept_error_reason = f"Student '{cmd_student_id}' already holds a copy of this C-type ISBN '{cmd_isbn_to_pick}' ('{student.held_c_books_by_isbn[cmd_isbn_to_pick]}')."

            if accept_error_reason:
                return {"is_legal": False, "error_message": f"Logic Error (Pick Accept): SUT accepted pick of '{sut_picked_book_copy_id}' by '{cmd_student_id}', but {accept_error_reason} SUT line: '{sut_output_line}'."}

            self.current_state.apply_validated_pick_action(cmd_date_str, cmd_student_id, sut_picked_book_copy_id)
            return {"is_legal": True}
        else: 
            return {"is_legal": False, "error_message": f"Internal Checker Error: Unknown SUT status '{parsed_sut['status']}' for pick. SUT line: '{sut_output_line}'."}


    def validate_sut_query(self, cmd_date_str: str, cmd_book_copy_id_queried: str, sut_output_lines_for_query: list[str]):
        if not sut_output_lines_for_query:
            return {"is_legal": False, "error_message": f"Format Error (Query): SUT produced no output for query of '{cmd_book_copy_id_queried}' on {cmd_date_str}."}

        parsed_header = parse_sut_query_header_line(sut_output_lines_for_query[0])
        if not parsed_header:
            return {"is_legal": False, "error_message": f"Format Error (Query): Malformed SUT query header line: '{sut_output_lines_for_query[0]}'"}

        sut_date_str, sut_book_id_header, sut_trace_count = parsed_header
        if sut_date_str != cmd_date_str:
            return {"is_legal": False, "error_message": f"Context Error (Query Header): SUT date mismatch. SUT: '{sut_date_str}', Expected: '{cmd_date_str}'. Line: '{sut_output_lines_for_query[0]}'"}
        if sut_book_id_header != cmd_book_copy_id_queried:
            return {"is_legal": False, "error_message": f"Context Error (Query Header): SUT BookCopyID mismatch. SUT: '{sut_book_id_header}', Expected: '{cmd_book_copy_id_queried}'. Line: '{sut_output_lines_for_query[0]}'"}

        if len(sut_output_lines_for_query) != 1 + sut_trace_count:
            return {"is_legal": False, "error_message": f"Format Error (Query): SUT query line count mismatch. Header declared: {sut_trace_count} trace lines, Actual lines provided (excluding header): {len(sut_output_lines_for_query)-1}."}

        expected_trace_entries = self.current_state.get_book_copy_details_for_trace(cmd_book_copy_id_queried)
        if expected_trace_entries is None: 
            if sut_trace_count != 0:
                 return {"is_legal": False, "error_message": f"Logic Error (Query Trace Count): Queried non-existent book '{cmd_book_copy_id_queried}' (checker has no record). SUT reported {sut_trace_count} traces, expected 0."}
            expected_trace_entries = []


        if sut_trace_count != len(expected_trace_entries):
            return {"is_legal": False, "error_message": f"Logic Error (Query Trace Count): SUT query for '{cmd_book_copy_id_queried}' reported {sut_trace_count} trace lines, but checker expected {len(expected_trace_entries)} based on current state."}

        for i in range(sut_trace_count):
            trace_line_num_sut_perspective = i + 1
            sut_detail_line_str = sut_output_lines_for_query[trace_line_num_sut_perspective]
            parsed_detail = parse_sut_query_trace_detail_line(sut_detail_line_str)
            if not parsed_detail:
                return {"is_legal": False, "error_message": f"Format Error (Query Trace Detail): Malformed SUT trace detail line {trace_line_num_sut_perspective}: '{sut_detail_line_str}'"}

            sut_seq, sut_detail_date, sut_from, sut_to = parsed_detail
            expected_seq_checker = i + 1 
            expected_detail_date_actual, expected_from_actual, expected_to_actual = expected_trace_entries[i]

            if sut_seq != expected_seq_checker:
                 return {"is_legal": False, "error_message": f"Logic Error (Query Trace Detail): For '{cmd_book_copy_id_queried}', sequence number mismatch at SUT trace line {trace_line_num_sut_perspective}. SUT seq: {sut_seq}, Expected seq: {expected_seq_checker}. Line: '{sut_detail_line_str}'."}
            if sut_detail_date != expected_detail_date_actual:
                 return {"is_legal": False, "error_message": f"Logic Error (Query Trace Detail): For '{cmd_book_copy_id_queried}', date mismatch at SUT trace line {trace_line_num_sut_perspective} (seq {sut_seq}). SUT date: '{sut_detail_date}', Expected date: '{expected_detail_date_actual}'. Line: '{sut_detail_line_str}'."}
            if sut_from != expected_from_actual:
                 return {"is_legal": False, "error_message": f"Logic Error (Query Trace Detail): For '{cmd_book_copy_id_queried}', 'from' location mismatch at SUT trace line {trace_line_num_sut_perspective} (seq {sut_seq}). SUT from: '{sut_from}', Expected from: '{expected_from_actual}'. Line: '{sut_detail_line_str}'."}
            if sut_to != expected_to_actual:
                 return {"is_legal": False, "error_message": f"Logic Error (Query Trace Detail): For '{cmd_book_copy_id_queried}', 'to' location mismatch at SUT trace line {trace_line_num_sut_perspective} (seq {sut_seq}). SUT to: '{sut_to}', Expected to: '{expected_to_actual}'. Line: '{sut_detail_line_str}'."}
        return {"is_legal": True}

    def validate_sut_tidy_moves(self, cmd_date_str:str, sut_move_output_lines: list[str], is_opening_tidy: bool):
        if not sut_move_output_lines:
            return {"is_legal": False, "error_message": "Format Error (Tidy): SUT produced no output for tidying phase (expected at least a count line)." }
        try:
            num_sut_moves_declared = int(sut_move_output_lines[0])
            if num_sut_moves_declared < 0: raise ValueError("Count cannot be negative")
        except ValueError as e:
            return {"is_legal": False, "error_message": f"Format Error (Tidy Count): SUT tidying move count line ('{sut_move_output_lines[0]}') is not a non-negative integer. Error: {e}"}

        if len(sut_move_output_lines) != 1 + num_sut_moves_declared:
            return {"is_legal": False, "error_message": f"Format Error (Tidy Line Count): SUT declared {num_sut_moves_declared} tidy moves, but provided {len(sut_move_output_lines)-1} move lines (expected {num_sut_moves_declared})."}

        current_processing_date_obj = self.current_state.current_date_obj
        if not current_processing_date_obj:
            return {"is_legal": False, "error_message": "Checker Internal Error: current_date_obj not set before tidy validation."}

        for i in range(num_sut_moves_declared):
            move_line_index_sut = i + 1 
            move_line_str = sut_move_output_lines[move_line_index_sut]
            parsed_move = parse_sut_tidy_move_line(move_line_str)

            if not parsed_move:
                return {"is_legal": False, "error_message": f"Format Error (Tidy Move Detail): Malformed SUT tidy move line {move_line_index_sut}: '{move_line_str}'."}

            if parsed_move["date_str"] != cmd_date_str:
                 return {"is_legal": False, "error_message": f"Context Error (Tidy Move Date): SUT tidy move line {move_line_index_sut} date mismatch. SUT date: '{parsed_move['date_str']}', Expected: '{cmd_date_str}'. Line: '{move_line_str}'."}

            book_copy_id_to_move = parsed_move["book_copy_id"]
            book_copy_object = self._get_book_copy(book_copy_id_to_move)
            if not book_copy_object:
                return {"is_legal": False, "error_message": f"Logic Error (Tidy Move): SUT tidy move line {move_line_index_sut}: attempt to move non-existent book '{book_copy_id_to_move}'. Line: '{move_line_str}'."}

            from_loc_short = parsed_move["from_loc_short"]
            to_loc_short = parsed_move["to_loc_short"]
            from_loc_full = LibrarySystem.REVERSE_LOCATION_SHORT_MAP.get(from_loc_short)
            to_loc_full = LibrarySystem.REVERSE_LOCATION_SHORT_MAP.get(to_loc_short)

            if from_loc_full == to_loc_full:
                return {"is_legal": False, "error_message": f"Logic Error (Tidy Move): SUT tidy move line {move_line_index_sut} for '{book_copy_id_to_move}': 'from' and 'to' locations are the same ('{from_loc_short}'). Line: '{move_line_str}'."}

            if book_copy_object.current_location != from_loc_full:
                return {"is_legal": False, "error_message": (f"Logic Error (Tidy Move): SUT tidy move line {move_line_index_sut} for '{book_copy_id_to_move}': "
                                                             f"SUT claims move from '{from_loc_full}', but book is at '{book_copy_object.current_location}' in checker state. Line: '{move_line_str}'." )}

            if from_loc_full == "appointment_office" and \
               book_copy_object.ao_reserved_for_student_id and \
               book_copy_object.ao_pickup_deadline:
                
                is_unmovable_due_to_active_reservation = False
                if is_opening_tidy:
                    if current_processing_date_obj <= book_copy_object.ao_pickup_deadline:
                        is_unmovable_due_to_active_reservation = True
                else: # CLOSE tidy
                    if current_processing_date_obj < book_copy_object.ao_pickup_deadline:
                        is_unmovable_due_to_active_reservation = True
                
                if is_unmovable_due_to_active_reservation:
                    return {"is_legal": False, "error_message": (
                        f"Logic Error (Tidy Move): SUT tidy move line {move_line_index_sut}: "
                        f"attempted to move reserved book '{book_copy_id_to_move}' "
                        f"(reserved for '{book_copy_object.ao_reserved_for_student_id}' "
                        f"until end of day '{book_copy_object.ao_pickup_deadline}') from AO "
                        f"on '{current_processing_date_obj}' during {'OPEN' if is_opening_tidy else 'CLOSE'} tidy. "
                        f"Book is still actively reserved and cannot be moved. Line: '{move_line_str}'.")}
                else:
                    self.current_state.clear_expired_ao_reservation_for_book(book_copy_id_to_move)


            target_student_id_for_ao = parsed_move["target_student_for_ao"]
            actual_pickup_deadline_for_ao_move = None

            if to_loc_full == "appointment_office":
                student_for_ao = self._get_student(target_student_id_for_ao)
                if student_for_ao.pending_order_isbn != book_copy_object.isbn:
                    return {"is_legal": False, "error_message": (f"Logic Error (Tidy Move to AO): SUT tidy move line {move_line_index_sut}: moved '{book_copy_id_to_move}' (ISBN: {book_copy_object.isbn}) to AO for student '{target_student_id_for_ao}', "
                                                                 f"but student has pending order for '{student_for_ao.pending_order_isbn}' (or no order for this ISBN). Expected pending order for ISBN '{book_copy_object.isbn}'. Line: '{move_line_str}'.")}

                reservation_effective_date = current_processing_date_obj
                if not is_opening_tidy: 
                    reservation_effective_date += timedelta(days=1)
                actual_pickup_deadline_for_ao_move = reservation_effective_date + timedelta(days=4)

                self.current_state._apply_book_movement(
                    book_copy_id_to_move, from_loc_full, to_loc_full, cmd_date_str,
                    ao_reservation_student_id=target_student_id_for_ao,
                    ao_pickup_deadline=actual_pickup_deadline_for_ao_move 
                )
                # ******** BUG FIX: Added missing argument 'is_opening_tidy' ********
                self.current_state.apply_book_reservation_at_ao( 
                    book_copy_id_to_move, target_student_id_for_ao, actual_pickup_deadline_for_ao_move, is_opening_tidy
                )
            else: 
                self.current_state._apply_book_movement(
                    book_copy_id_to_move, from_loc_full, to_loc_full, cmd_date_str
                )

        if is_opening_tidy:
            for book_id_check, book_obj_check in self.current_state.all_book_copies.items():
                if book_obj_check.current_location == "borrow_return_office":
                    return {"is_legal": False, "error_message": f"Post-Tidy Logic Error (OPEN): After OPEN tidy on {cmd_date_str}, book '{book_id_check}' remains in Borrow/Return Office (BRO). BRO should be empty."}
                
                if book_obj_check.current_location == "appointment_office" and \
                   book_obj_check.ao_reserved_for_student_id and \
                   book_obj_check.ao_pickup_deadline and \
                   current_processing_date_obj > book_obj_check.ao_pickup_deadline: 
                    return {"is_legal": False, "error_message": (f"Post-Tidy Logic Error (OPEN): After OPEN tidy on {cmd_date_str}, overdue book '{book_id_check}' "
                                                                 f"(reserved for '{book_obj_check.ao_reserved_for_student_id}', expired '{book_obj_check.ao_pickup_deadline}') "
                                                                 f"remains at Appointment Office (AO). Overdue books should be moved out during OPEN tidy.")}
        return {"is_legal": True}


def check_cycle(cycle_command_strings: list[str],
                sut_all_output_lines_for_cycle: list[str],
                main_library_state: LibrarySystem):
    sut_output_idx = 0
    current_cycle_state_copy = copy.deepcopy(main_library_state)
    checker_instance = RuleChecker(current_cycle_state_copy) 

    for cmd_idx, command_str in enumerate(cycle_command_strings):
        parts = command_str.split()
        cmd_date_str = parts[0][1:-1] 
        validation_result = {"is_legal": False, "error_message": "Checker Internal Error: Command not processed."}

        is_open_or_close_command = len(parts) == 2 and parts[1] in ["OPEN", "CLOSE"]

        if is_open_or_close_command:
            op_type = parts[1]
            is_opening_tidy_local = (op_type == "OPEN") # Renamed to avoid conflict with loop var
            if is_opening_tidy_local:
                checker_instance.current_state.apply_open_action(cmd_date_str)
            else: # CLOSE
                checker_instance.current_state.apply_close_action(cmd_date_str)

            if sut_output_idx >= len(sut_all_output_lines_for_cycle):
                return {"is_legal": False, "error_message": f"Format Error ({op_type} Tidy): SUT ran out of output lines before {op_type} tidy count.", "first_failing_command": command_str}
            try:
                num_moves_sut = int(sut_all_output_lines_for_cycle[sut_output_idx])
                if num_moves_sut < 0: raise ValueError("Negative move count")
            except ValueError:
                return {"is_legal": False, "error_message": f"Format Error ({op_type} Tidy Count): SUT {op_type} tidy count ('{sut_all_output_lines_for_cycle[sut_output_idx]}') is not a non-negative int.", "first_failing_command": command_str}

            if sut_output_idx + 1 + num_moves_sut > len(sut_all_output_lines_for_cycle):
                return {"is_legal": False, "error_message": f"Format Error ({op_type} Tidy Line Count): SUT declared {num_moves_sut} moves, not enough lines. Needed {1+num_moves_sut}, got {len(sut_all_output_lines_for_cycle) - sut_output_idx}.", "first_failing_command": command_str}

            sut_tidy_lines = sut_all_output_lines_for_cycle[sut_output_idx : sut_output_idx + 1 + num_moves_sut]
            sut_output_idx += (1 + num_moves_sut)
            validation_result = checker_instance.validate_sut_tidy_moves(cmd_date_str, sut_tidy_lines, is_opening_tidy=is_opening_tidy_local)
        
        else: # User operation command
            cmd_student_id, cmd_action, cmd_target = parts[1], parts[2], parts[3]
            if cmd_action == "queried":
                if sut_output_idx >= len(sut_all_output_lines_for_cycle):
                    return {"is_legal": False, "error_message": f"Format Error (Query): SUT ran out of output for query '{command_str}'.", "first_failing_command": command_str}
                parsed_q_header = parse_sut_query_header_line(sut_all_output_lines_for_cycle[sut_output_idx])
                if not parsed_q_header:
                    return {"is_legal": False, "error_message": f"Format Error (Query Header): Malformed header '{sut_all_output_lines_for_cycle[sut_output_idx]}' for '{command_str}'.", "first_failing_command": command_str}
                _, _, num_trace_lines_sut_declared = parsed_q_header
                
                if sut_output_idx + 1 + num_trace_lines_sut_declared > len(sut_all_output_lines_for_cycle):
                    return {"is_legal": False, "error_message": f"Format Error (Query Line Count): SUT declared {num_trace_lines_sut_declared} traces, not enough lines for '{command_str}'.", "first_failing_command": command_str}
                sut_lines_for_this_query = sut_all_output_lines_for_cycle[sut_output_idx : sut_output_idx + 1 + num_trace_lines_sut_declared]
                sut_output_idx += (1 + num_trace_lines_sut_declared)
                validation_result = checker_instance.validate_sut_query(cmd_date_str, cmd_target, sut_lines_for_this_query)
            else: 
                if sut_output_idx >= len(sut_all_output_lines_for_cycle):
                    return {"is_legal": False, "error_message": f"Format Error (User Op): SUT ran out of output for '{command_str}'.", "first_failing_command": command_str}
                sut_op_line = sut_all_output_lines_for_cycle[sut_output_idx]; sut_output_idx += 1
                
                if cmd_action == "borrowed": validation_result = checker_instance.validate_sut_borrow(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                elif cmd_action == "returned": validation_result = checker_instance.validate_sut_return(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                elif cmd_action == "ordered": validation_result = checker_instance.validate_sut_order(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                elif cmd_action == "picked": validation_result = checker_instance.validate_sut_pick(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                else: validation_result = {"is_legal": False, "error_message": f"Checker Internal Error: Unknown action '{cmd_action}' in '{command_str}'."}
        
        if not validation_result.get("is_legal", False):
            err_msg = validation_result.get('error_message', 'Unknown validation error')
            return {"is_legal": False, "error_message": f"Validation failed for command {cmd_idx+1} ('{command_str}'): {err_msg}", "first_failing_command": command_str}

    if sut_output_idx < len(sut_all_output_lines_for_cycle):
        return {"is_legal": False, "error_message": f"Format Error (Extraneous Output): SUT produced extraneous output. First: '{sut_all_output_lines_for_cycle[sut_output_idx]}'", "first_failing_command": "End of cycle (extraneous SUT output)"}

    main_library_state.__dict__.update(current_cycle_state_copy.__dict__)
    return {"is_legal": True, "error_message": "", "first_failing_command": None}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Checker for Library System SUT output.")
    parser.add_argument("input_file", help="Path to the input command file (e.g., input.txt).")
    parser.add_argument("sut_output_file", help="Path to the SUT's output file (e.g., output.txt).")
    args = parser.parse_args()

    all_input_commands: list[str] = []
    all_sut_output_lines: list[str] = []

    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            all_input_commands = [line.strip() for line in f if line.strip()]
        with open(args.sut_output_file, 'r', encoding='utf-8') as f:
            all_sut_output_lines = [line.strip() for line in f if line.strip()]
    except FileNotFoundError as e:
        print(json.dumps({"status": "failure", "reason": f"Error reading files: {e}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"status": "failure", "reason": f"An unexpected error occurred while reading files: {e}"}))
        sys.exit(1)

    if not all_input_commands:
        if all_sut_output_lines:
            print(json.dumps({"status": "failure", "reason": "Input file is empty, but SUT produced output."}))
        else:
            print(json.dumps({"status": "success"})) 
        sys.exit(0)

    main_library_state = LibrarySystem()
    sut_output_idx = 0
    input_cmd_idx = 0
    current_command_str_for_error_reporting = "Initial book loading"

    try:
        if input_cmd_idx >= len(all_input_commands):
            print(json.dumps({"status": "failure", "reason": "Input file does not contain initial book count."}))
            sys.exit(1)

        num_book_types_str = all_input_commands[input_cmd_idx]; input_cmd_idx += 1
        try:
            num_book_types = int(num_book_types_str)
            if num_book_types < 0:
                 print(json.dumps({"status": "failure", "reason": "Negative number of book types in input."}))
                 sys.exit(1)
        except ValueError:
            print(json.dumps({"status": "failure", "reason": f"Invalid format for initial book count: '{num_book_types_str}'."}))
            sys.exit(1)

        if input_cmd_idx + num_book_types > len(all_input_commands):
            print(json.dumps({"status": "failure", "reason": "Input file too short for declared number of book types."}))
            sys.exit(1)
        
        book_init_lines = all_input_commands[input_cmd_idx : input_cmd_idx + num_book_types]
        input_cmd_idx += num_book_types
        main_library_state.initialize_books(book_init_lines) 
    
    except ValueError as e: 
        print(json.dumps({"status": "failure", "reason": f"Error during library initialization: {e}"}))
        sys.exit(1)
    except Exception as e: 
        print(json.dumps({"status": "failure", "reason": f"Critical error during library initialization: {e}"}))
        sys.exit(1)

    checker_instance = RuleChecker(main_library_state) 
    validation_result = {"is_legal": True} 

    try:
        while input_cmd_idx < len(all_input_commands):
            command_str = all_input_commands[input_cmd_idx]
            current_command_str_for_error_reporting = command_str 
            input_cmd_idx += 1

            parts = command_str.split()
            if not parts: continue 

            if not (parts[0].startswith("[") and parts[0].endswith("]")):
                validation_result = {"is_legal": False, "error_message": f"Command '{command_str}' missing or malformed date part."}
                break 
            cmd_date_str = parts[0][1:-1]
            
            is_open_close_local_scope = len(parts) == 2 and parts[1] in ["OPEN", "CLOSE"] # Renamed to avoid conflict

            if is_open_close_local_scope:
                op_type = parts[1]
                current_is_opening_tidy = (op_type == "OPEN") # Variable specific to this scope
                if current_is_opening_tidy:
                    checker_instance.current_state.apply_open_action(cmd_date_str)
                else: # CLOSE
                    checker_instance.current_state.apply_close_action(cmd_date_str)

                if sut_output_idx >= len(all_sut_output_lines):
                    validation_result = {"is_legal": False, "error_message": f"Format Error ({op_type} Tidy): SUT ran out of output before {op_type} tidy count."}
                    break 
                
                num_moves_sut_str = all_sut_output_lines[sut_output_idx]
                try:
                    num_moves_sut = int(num_moves_sut_str)
                    if num_moves_sut < 0: raise ValueError("Negative move count")
                except ValueError:
                    validation_result = {"is_legal": False, "error_message": f"Format Error ({op_type} Tidy Count): SUT count ('{num_moves_sut_str}') not non-negative int."}
                    break

                if sut_output_idx + 1 + num_moves_sut > len(all_sut_output_lines):
                    validation_result = {"is_legal": False, "error_message": f"Format Error ({op_type} Tidy Line Count): SUT declared {num_moves_sut} moves, not enough lines."}
                    break
                
                sut_tidy_lines = all_sut_output_lines[sut_output_idx : sut_output_idx + 1 + num_moves_sut]
                sut_output_idx += (1 + num_moves_sut)
                validation_result = checker_instance.validate_sut_tidy_moves(cmd_date_str, sut_tidy_lines, is_opening_tidy=current_is_opening_tidy) # Pass the correct variable

            else: # User operation command
                if len(parts) < 4: 
                    validation_result = {"is_legal": False, "error_message": f"Format Error (User Op): Command '{command_str}' malformed."}
                    break
                cmd_student_id, cmd_action, cmd_target = parts[1], parts[2], parts[3]

                if cmd_action == "queried":
                    if sut_output_idx >= len(all_sut_output_lines):
                        validation_result = {"is_legal": False, "error_message": f"Format Error (Query): SUT ran out of output for query '{command_str}'."}
                        break
                    sut_header_line = all_sut_output_lines[sut_output_idx]
                    parsed_q_header = parse_sut_query_header_line(sut_header_line)
                    if not parsed_q_header:
                        validation_result = {"is_legal": False, "error_message": f"Format Error (Query Header): Malformed SUT header '{sut_header_line}' for '{command_str}'."}
                        break
                    _, _, num_trace_lines_sut_declared = parsed_q_header
                    
                    if sut_output_idx + 1 + num_trace_lines_sut_declared > len(all_sut_output_lines):
                        validation_result = {"is_legal": False, "error_message": f"Format Error (Query Line Count): SUT declared {num_trace_lines_sut_declared} traces, not enough lines for '{command_str}'."}
                        break
                    sut_lines_for_this_query = all_sut_output_lines[sut_output_idx : sut_output_idx + 1 + num_trace_lines_sut_declared]
                    sut_output_idx += (1 + num_trace_lines_sut_declared)
                    validation_result = checker_instance.validate_sut_query(cmd_date_str, cmd_target, sut_lines_for_this_query)
                else: 
                    if sut_output_idx >= len(all_sut_output_lines):
                        validation_result = {"is_legal": False, "error_message": f"Format Error (User Op): SUT ran out of output for '{command_str}'."}
                        break
                    sut_op_line = all_sut_output_lines[sut_output_idx]; sut_output_idx += 1
                    
                    if cmd_action == "borrowed": validation_result = checker_instance.validate_sut_borrow(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "returned": validation_result = checker_instance.validate_sut_return(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "ordered": validation_result = checker_instance.validate_sut_order(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "picked": validation_result = checker_instance.validate_sut_pick(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    else:
                        validation_result = {"is_legal": False, "error_message": f"Checker Internal Error: Unknown action '{cmd_action}' in '{command_str}'."}
            
            if not validation_result.get("is_legal", False):
                break 
        
        if not validation_result.get("is_legal", False):
            reason = validation_result.get('error_message', 'Unknown validation error')
            print(json.dumps({"status": "failure", "reason": f"Validation failed for command '{current_command_str_for_error_reporting}': {reason}"}))
            sys.exit(1)

        if sut_output_idx < len(all_sut_output_lines):
            print(json.dumps({"status": "failure", "reason": f"Format Error (Extraneous Output): SUT produced extraneous output. First: '{all_sut_output_lines[sut_output_idx]}'."}))
            sys.exit(1)

        print(json.dumps({"status": "success"}))
        sys.exit(0)

    except Exception as e:
        import traceback
        error_details = f"{type(e).__name__} - {e}\n{traceback.format_exc()}"
        error_context = f"An unexpected critical error occurred during processing of command '{current_command_str_for_error_reporting}': {error_details}"
        print(json.dumps({"status": "failure", "reason": error_context}))
        sys.exit(1)