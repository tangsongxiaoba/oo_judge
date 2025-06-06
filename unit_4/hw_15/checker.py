# checker.py
import io
import sys
import json
import copy
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple, Any

try:
    # Uses the final corrected version of state.py
    from state import LibrarySystem, BookCopy, Student
except ImportError:
    print(json.dumps({"is_legal": False, "error_message": "Critical Checker Error: Could not import from state.py."}))
    sys.exit(1)

# --- SUT Output Parsers (Corrected) ---
def parse_sut_user_op_line(line: str) -> Optional[Dict[str, Any]]:
    parts = line.split()
    if not (5 <= len(parts) <= 7): return None

    if not (parts[0].startswith("[") and parts[0].endswith("]") and parts[1].startswith("[") and parts[1].endswith("]")): return None
    date_str = parts[0][1:-1]
    try: date.fromisoformat(date_str)
    except ValueError: return None
    
    status = parts[1][1:-1]
    if status not in ["accept", "reject"]: return None

    action = parts[3]
    result = {"date_str": date_str, "status": status, "student_id": parts[2], "action": action, "target_str": parts[4]}

    if action == "returned":
        if len(parts) == 6 and parts[5] == "overdue":
            result["overdue_status"] = "overdue"
        elif len(parts) == 7 and parts[5] == "not" and parts[6] == "overdue":
            result["overdue_status"] = "not overdue"
        else: return None
    elif len(parts) != 5: return None
    return result

def parse_sut_credit_query_line(line: str) -> Optional[Dict[str, Any]]:
    parts = line.split()
    if len(parts) != 3: return None
    if not (parts[0].startswith("[") and parts[0].endswith("]")): return None
    date_str = parts[0][1:-1]
    try: date.fromisoformat(date_str)
    except ValueError: return None
    student_id = parts[1]
    try: credit_score = int(parts[2])
    except ValueError: return None
    return {"date_str": date_str, "student_id": student_id, "credit_score": credit_score}

# ... (other parsers and helper functions remain unchanged from the previous correct version) ...
def parse_sut_query_header_line(line: str) -> Optional[Tuple[str, str, int]]:
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

def parse_sut_query_trace_detail_line(line: str) -> Optional[Tuple[int, str, str, str]]:
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

def parse_sut_tidy_move_line(line: str) -> Optional[Dict[str, Any]]:
    parts = line.split()
    if not (len(parts) == 7 or len(parts) == 9): return None
    if not (parts[0].startswith("[") and parts[0].endswith("]") and parts[1] == "move" and parts[3] == "from" and parts[5] == "to"): return None
    date_str = parts[0][1:-1]
    try: date.fromisoformat(date_str)
    except ValueError: return None
    book_copy_id, from_loc_short, to_loc_short = parts[2], parts[4], parts[6]
    
    valid_tidy_locs_short = [LibrarySystem.LOCATION_SHORT_MAP[loc] for loc in LibrarySystem.TIDY_INTERNAL_LOCATIONS]
    if from_loc_short not in valid_tidy_locs_short or to_loc_short not in valid_tidy_locs_short:
        return None
    
    target_student_for_ao = None
    if len(parts) == 9:
        if parts[7] != "for": return None
        target_student_for_ao = parts[8]
        if to_loc_short != LibrarySystem.LOCATION_SHORT_MAP["appointment_office"]: return None
    elif to_loc_short == LibrarySystem.LOCATION_SHORT_MAP["appointment_office"]: return None
    return {"date_str": date_str, "book_copy_id": book_copy_id, "from_loc_short": from_loc_short, "to_loc_short": to_loc_short, "target_student_for_ao": target_student_for_ao}

def _is_isbn_like(target_str: str) -> bool:
    parts = target_str.split('-')
    if len(parts) != 2: return False
    if not (len(parts[0]) == 1 and parts[0] in "ABC"): return False 
    if not (len(parts[1]) == 4 and parts[1].isdigit()): return False 
    return True

def _is_book_copy_id_like(target_str: str) -> bool:
    parts = target_str.split('-')
    if len(parts) != 3: return False
    if not (len(parts[0]) == 1 and parts[0] in "ABC"): return False
    if not (len(parts[1]) == 4 and parts[1].isdigit()): return False 
    if not (len(parts[2]) >= 1 and parts[2].isdigit()): return False 
    return True


class RuleChecker:
    # ... (the entire RuleChecker class from the previous corrected version remains the same) ...
    # It now uses the corrected state.py and the corrected parsers, so its logic will be correct.
    def __init__(self, library_state: LibrarySystem):
        self.current_state = library_state

    def _get_book_copy(self, book_id: str) -> Optional[BookCopy]:
        return self.current_state._get_book_copy(book_id)

    def _get_student(self, student_id: str) -> Student:
        return self.current_state._get_student(student_id)

    def _common_user_op_validation(self, sut_output_line: str, cmd_date_str: str, cmd_student_id: str, expected_action: str) -> Optional[Dict[str, Any]]:
        parsed_sut = parse_sut_user_op_line(sut_output_line)
        if not parsed_sut:
            return {"is_legal": False, "error_message": f"Format Error ({expected_action.capitalize()}): SUT output line '{sut_output_line}' is malformed."}
        
        if parsed_sut.get("is_legal") is False: return parsed_sut

        if parsed_sut["action"] != expected_action:
            return {"is_legal": False, "error_message": f"Context Error ({expected_action.capitalize()}): SUT action is '{parsed_sut['action']}', expected '{expected_action}'. Line: '{sut_output_line}'."}
        if parsed_sut["student_id"] != cmd_student_id:
            return {"is_legal": False, "error_message": f"Context Error ({expected_action.capitalize()}): SUT student ID '{parsed_sut['student_id']}', expected '{cmd_student_id}'. Line: '{sut_output_line}'."}
        if parsed_sut["date_str"] != cmd_date_str:
            return {"is_legal": False, "error_message": f"Context Error ({expected_action.capitalize()}): SUT date '{parsed_sut['date_str']}', expected '{cmd_date_str}'. Line: '{sut_output_line}'."}
        
        return parsed_sut

    def validate_sut_borrow(self, cmd_date_str:str, cmd_student_id: str, cmd_isbn: str, sut_output_line: str) -> Dict[str, Any]:
        validation_result = self._common_user_op_validation(sut_output_line, cmd_date_str, cmd_student_id, "borrowed")
        if validation_result and not validation_result.get("is_legal", True) : return validation_result
        parsed_sut = validation_result
        if not parsed_sut: return {"is_legal": False, "error_message": "Internal checker error during common validation for borrow."}
        
        sut_target_str = parsed_sut["target_str"]
        student = self._get_student(cmd_student_id)
        book_type_to_borrow = self.current_state._get_book_type_from_id_or_isbn(cmd_isbn)

        if parsed_sut["status"] == "reject":
            if not _is_isbn_like(sut_target_str) or sut_target_str != cmd_isbn:
                return {"is_legal": False, "error_message": f"Format Error (Borrow Reject): SUT target '{sut_target_str}' invalid or mismatch. Expected ISBN '{cmd_isbn}'. Line: '{sut_output_line}'."}

            can_be_borrowed_by_rule = True
            rejection_reason_checker = "Checker finds borrow permissible."
            
            copies_on_shelf_ids = [bc_id for bc_id, bc in self.current_state.all_book_copies.items() if bc.isbn == cmd_isbn and bc.current_location in LibrarySystem.SHELF_LOCATIONS]

            if student.credit_score < 60:
                can_be_borrowed_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' credit score is {student.credit_score}, which is less than 60."
            elif not copies_on_shelf_ids:
                can_be_borrowed_by_rule = False; rejection_reason_checker = f"No copies of ISBN '{cmd_isbn}' are currently on any shelf (bs/hbs)."
            elif book_type_to_borrow == 'A':
                can_be_borrowed_by_rule = False; rejection_reason_checker = "Book is Type A (cannot be borrowed)."
            elif book_type_to_borrow == 'B' and student.held_b_book is not None:
                can_be_borrowed_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already holds a B-type book ('{student.held_b_book[0]}')."
            elif book_type_to_borrow == 'C' and cmd_isbn in student.held_c_books_by_isbn:
                can_be_borrowed_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already holds a copy of this C-type ISBN '{cmd_isbn}' ('{student.held_c_books_by_isbn[cmd_isbn][0]}')."

            if not can_be_borrowed_by_rule: return {"is_legal": True} 
            else: return {"is_legal": False, "error_message": f"Logic Error (Borrow Reject): SUT rejected borrow of '{cmd_isbn}', but checker deems it permissible. Reason: {rejection_reason_checker} Line: '{sut_output_line}'."}

        elif parsed_sut["status"] == "accept":
            if not _is_book_copy_id_like(sut_target_str):
                return {"is_legal": False, "error_message": f"Format Error (Borrow Accept): SUT target '{sut_target_str}' not BookCopyID. Line: '{sut_output_line}'."}

            sut_book_copy_id = sut_target_str
            book_copy_sut_claims_to_lend = self._get_book_copy(sut_book_copy_id)

            if not book_copy_sut_claims_to_lend:
                return {"is_legal": False, "error_message": f"Logic Error (Borrow Accept): SUT lent non-existent BookCopyID '{sut_book_copy_id}'. Line: '{sut_output_line}'."}
            if book_copy_sut_claims_to_lend.isbn != cmd_isbn:
                return {"is_legal": False, "error_message": f"Logic Error (Borrow Accept): SUT lent BookCopyID '{sut_book_copy_id}' (ISBN '{book_copy_sut_claims_to_lend.isbn}'), command was for ISBN '{cmd_isbn}'. Line: '{sut_output_line}'."}

            accept_error_reason = ""
            if student.credit_score < 60:
                accept_error_reason = f"Student '{cmd_student_id}' credit score is {student.credit_score} (< 60), not allowed to borrow."
            elif book_copy_sut_claims_to_lend.type == 'A':
                accept_error_reason = f"Book '{sut_book_copy_id}' is Type A (cannot be borrowed)."
            elif book_copy_sut_claims_to_lend.current_location not in LibrarySystem.SHELF_LOCATIONS:
                accept_error_reason = f"Book '{sut_book_copy_id}' was at '{book_copy_sut_claims_to_lend.current_location}', not on a shelf (bs/hbs)."
            elif book_copy_sut_claims_to_lend.type == 'B' and student.held_b_book is not None:
                accept_error_reason = f"Student '{cmd_student_id}' already holds a B-type book ('{student.held_b_book[0]}')."
            elif book_copy_sut_claims_to_lend.type == 'C' and cmd_isbn in student.held_c_books_by_isbn:
                accept_error_reason = f"Student '{cmd_student_id}' already holds a copy of this C-type ISBN '{cmd_isbn}' ('{student.held_c_books_by_isbn[cmd_isbn][0]}')."

            if accept_error_reason:
                return {"is_legal": False, "error_message": f"Logic Error (Borrow Accept): SUT accepted borrow of '{sut_book_copy_id}', but {accept_error_reason} Line: '{sut_output_line}'."}

            self.current_state.apply_validated_borrow_action(cmd_date_str, cmd_student_id, sut_book_copy_id)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": "Internal Checker Error."}

    def validate_sut_return(self, cmd_date_str:str, cmd_student_id: str, cmd_book_copy_id: str, sut_output_line: str) -> Dict[str, Any]:
        validation_result = self._common_user_op_validation(sut_output_line, cmd_date_str, cmd_student_id, "returned")
        if validation_result and not validation_result.get("is_legal", True) : return validation_result
        parsed_sut = validation_result
        if not parsed_sut: return {"is_legal": False, "error_message": "Internal checker error during common validation for return."}

        sut_target_str = parsed_sut["target_str"]
        if not _is_book_copy_id_like(sut_target_str) or sut_target_str != cmd_book_copy_id:
            return {"is_legal": False, "error_message": f"Format Error (Return): SUT target '{sut_target_str}' invalid or mismatch. Expected BookCopyID '{cmd_book_copy_id}'. Line: '{sut_output_line}'."}
        
        sut_overdue_status_str = parsed_sut.get("overdue_status")
        if sut_overdue_status_str not in ["overdue", "not overdue"]:
            return {"is_legal": False, "error_message": f"Format Error (Return): Missing or invalid overdue status. Expected 'overdue' or 'not overdue'. Line: '{sut_output_line}'."}

        if parsed_sut["status"] == "reject":
            return {"is_legal": False, "error_message": f"Logic Error (Return Reject): SUT rejected return of '{cmd_book_copy_id}'. Returns should always be accepted. Line: '{sut_output_line}'."}
        
        elif parsed_sut["status"] == "accept":
            book_copy_to_return = self._get_book_copy(cmd_book_copy_id)
            if not book_copy_to_return:
                return {"is_legal": False, "error_message": f"Logic Error (Return Accept): SUT accepted return of non-existent book '{cmd_book_copy_id}'. Line: '{sut_output_line}'."}
            
            if not (book_copy_to_return.current_location == "user" and book_copy_to_return.current_holder_student_id == cmd_student_id):
                 return {"is_legal": False, "error_message": (f"Logic Error (Return Accept): SUT accepted return of '{cmd_book_copy_id}' by '{cmd_student_id}', "
                                                              f"but book state is inconsistent. Expected: held by student. "
                                                              f"Actual: loc='{book_copy_to_return.current_location}', holder='{book_copy_to_return.current_holder_student_id}'.")}
            
            is_overdue_in_state = self.current_state.apply_validated_return_action(cmd_date_str, cmd_student_id, cmd_book_copy_id)
            
            expected_overdue_str = "overdue" if is_overdue_in_state else "not overdue"
            if sut_overdue_status_str != expected_overdue_str:
                return {"is_legal": False, "error_message": f"Logic Error (Return Overdue Status): SUT reported overdue status as '{sut_overdue_status_str}', but checker state calculated it as '{expected_overdue_str}'. Line: '{sut_output_line}'."}

            return {"is_legal": True}
        return {"is_legal": False, "error_message": "Internal Checker Error."}

    def validate_sut_order(self, cmd_date_str:str, cmd_student_id: str, cmd_isbn: str, sut_output_line: str) -> Dict[str, Any]:
        validation_result = self._common_user_op_validation(sut_output_line, cmd_date_str, cmd_student_id, "ordered")
        if validation_result and not validation_result.get("is_legal", True) : return validation_result
        parsed_sut = validation_result
        if not parsed_sut: return {"is_legal": False, "error_message": "Internal checker error during common validation for order."}

        sut_target_str = parsed_sut["target_str"]
        if not _is_isbn_like(sut_target_str) or sut_target_str != cmd_isbn:
            return {"is_legal": False, "error_message": f"Format Error (Order): Target '{sut_target_str}' invalid or mismatch. Expected ISBN '{cmd_isbn}'. Line: '{sut_output_line}'."}

        student = self._get_student(cmd_student_id)
        book_type_to_order = self.current_state._get_book_type_from_id_or_isbn(cmd_isbn)

        if parsed_sut["status"] == "reject":
            can_be_ordered_by_rule = True; rejection_reason_checker = "Checker finds order permissible."
            if student.credit_score < 100:
                can_be_ordered_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' credit score is {student.credit_score}, which is less than 100."
            elif book_type_to_order == 'A':
                can_be_ordered_by_rule = False; rejection_reason_checker = "Book is Type A (cannot be ordered)."
            elif student.pending_order_isbn is not None or student.reserved_book_copy_id_at_ao is not None:
                can_be_ordered_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already has pending order ('{student.pending_order_isbn}') or reserved book at AO ('{student.reserved_book_copy_id_at_ao}')."
            elif book_type_to_order == 'B' and student.held_b_book is not None:
                can_be_ordered_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' holds a B-type book, cannot order another B."
            elif book_type_to_order == 'C' and cmd_isbn in student.held_c_books_by_isbn:
                can_be_ordered_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' holds this C-type ISBN."
            
            if not can_be_ordered_by_rule: return {"is_legal": True}
            else: return {"is_legal": False, "error_message": f"Logic Error (Order Reject): SUT rejected order for '{cmd_isbn}', but checker deems it permissible. Reason: {rejection_reason_checker} Line: '{sut_output_line}'."}

        elif parsed_sut["status"] == "accept":
            accept_error_reason = ""
            if student.credit_score < 100:
                accept_error_reason = f"Student '{cmd_student_id}' credit score is {student.credit_score} (< 100), not allowed to order."
            elif book_type_to_order == 'A':
                accept_error_reason = "Book is Type A (cannot be ordered)."
            elif student.pending_order_isbn is not None or student.reserved_book_copy_id_at_ao is not None:
                accept_error_reason = f"Student '{cmd_student_id}' already has pending order ('{student.pending_order_isbn}') or reserved book at AO ('{student.reserved_book_copy_id_at_ao}')."
            elif book_type_to_order == 'B' and student.held_b_book is not None:
                accept_error_reason = f"Student '{cmd_student_id}' holds a B-type book, cannot order another B."
            elif book_type_to_order == 'C' and cmd_isbn in student.held_c_books_by_isbn:
                accept_error_reason = f"Student '{cmd_student_id}' holds this C-type ISBN."

            if accept_error_reason:
                return {"is_legal": False, "error_message": f"Logic Error (Order Accept): SUT accepted order for '{cmd_isbn}', but {accept_error_reason} Line: '{sut_output_line}'."}
            
            self.current_state.apply_validated_order_action(cmd_student_id, cmd_isbn)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": "Internal Checker Error."}

    def validate_sut_pick(self, cmd_date_str:str, cmd_student_id: str, cmd_isbn_to_pick: str, sut_output_line: str) -> Dict[str, Any]:
        validation_result = self._common_user_op_validation(sut_output_line, cmd_date_str, cmd_student_id, "picked")
        if validation_result and not validation_result.get("is_legal", True) : return validation_result
        parsed_sut = validation_result
        if not parsed_sut: return {"is_legal": False, "error_message": "Internal checker error during common validation for pick."}

        current_date_obj = self.current_state.current_date_obj
        if not current_date_obj: return {"is_legal": False, "error_message": "Checker Internal Error: current_date_obj not set."}

        sut_target_str = parsed_sut["target_str"]
        student = self._get_student(cmd_student_id)

        if parsed_sut["status"] == "reject":
            if not _is_isbn_like(sut_target_str) or sut_target_str != cmd_isbn_to_pick:
                return {"is_legal": False, "error_message": f"Format Error (Pick Reject): Target '{sut_target_str}' invalid or mismatch. Expected ISBN '{cmd_isbn_to_pick}'. Line: '{sut_output_line}'."}
            
            can_be_picked_by_rule = True; rejection_reason_checker = "Checker finds pick permissible."
            book_id_student_reserved = student.reserved_book_copy_id_at_ao
            if not book_id_student_reserved:
                can_be_picked_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' has no book reserved at AO."
            else:
                reserved_book_copy = self._get_book_copy(book_id_student_reserved)
                if not reserved_book_copy:
                     can_be_picked_by_rule = False; rejection_reason_checker = f"Student has reservation for non-existent book '{book_id_student_reserved}'."
                elif student.credit_score < 60:
                     can_be_picked_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' credit score is {student.credit_score} (< 60), cannot pick/borrow."
                elif reserved_book_copy.isbn != cmd_isbn_to_pick: 
                    can_be_picked_by_rule = False; rejection_reason_checker = f"Student has book of ISBN '{reserved_book_copy.isbn}' reserved, but pick command is for different ISBN '{cmd_isbn_to_pick}'."
                elif reserved_book_copy.current_location != "appointment_office" or reserved_book_copy.ao_reserved_for_student_id != cmd_student_id:
                    can_be_picked_by_rule = False; rejection_reason_checker = f"Reserved book '{book_id_student_reserved}' is not at AO or not reserved for this student."
                elif student.pickup_deadline_for_reserved_book and current_date_obj > student.pickup_deadline_for_reserved_book:
                    can_be_picked_by_rule = False; rejection_reason_checker = f"Reservation for '{book_id_student_reserved}' expired on {student.pickup_deadline_for_reserved_book}."
                else: 
                    book_type_at_ao = reserved_book_copy.type
                    if book_type_at_ao == 'B' and student.held_b_book is not None:
                        can_be_picked_by_rule = False; rejection_reason_checker = f"Student already holds a B-type book ('{student.held_b_book[0]}')."
                    elif book_type_at_ao == 'C' and cmd_isbn_to_pick in student.held_c_books_by_isbn:
                        can_be_picked_by_rule = False; rejection_reason_checker = f"Student already holds this C-type ISBN ('{student.held_c_books_by_isbn[cmd_isbn_to_pick][0]}')."

            if not can_be_picked_by_rule: return {"is_legal": True}
            else: return {"is_legal": False, "error_message": f"Logic Error (Pick Reject): SUT rejected pick of '{cmd_isbn_to_pick}', but checker deems it permissible. Reason: {rejection_reason_checker} Line: '{sut_output_line}'."}

        elif parsed_sut["status"] == "accept":
            if not _is_book_copy_id_like(sut_target_str):
                return {"is_legal": False, "error_message": f"Format Error (Pick Accept): Target '{sut_target_str}' not BookCopyID. Line: '{sut_output_line}'."}
            
            sut_picked_book_copy_id = sut_target_str
            book_sut_claims_picked = self._get_book_copy(sut_picked_book_copy_id)

            if not book_sut_claims_picked:
                 return {"is_legal": False, "error_message": f"Logic Error (Pick Accept): SUT picked non-existent BookCopyID '{sut_picked_book_copy_id}'. Line: '{sut_output_line}'."}
            if book_sut_claims_picked.isbn != cmd_isbn_to_pick:
                 return {"is_legal": False, "error_message": f"Logic Error (Pick Accept): SUT picked BookCopyID '{sut_picked_book_copy_id}' (of ISBN '{book_sut_claims_picked.isbn}'), but command was for ISBN '{cmd_isbn_to_pick}'. Line: '{sut_output_line}'."}
            if student.reserved_book_copy_id_at_ao != sut_picked_book_copy_id :
                 return {"is_legal": False, "error_message": f"Logic Error (Pick Accept): SUT picked '{sut_picked_book_copy_id}', but student had '{student.reserved_book_copy_id_at_ao}' reserved. Line: '{sut_output_line}'."}

            accept_error_reason = ""
            if student.credit_score < 60:
                accept_error_reason = f"Student '{cmd_student_id}' credit score is {student.credit_score} (< 60), not allowed to pick/borrow."
            elif book_sut_claims_picked.current_location != "appointment_office" or book_sut_claims_picked.ao_reserved_for_student_id != cmd_student_id:
                accept_error_reason = f"Book '{sut_picked_book_copy_id}' is not at AO or not reserved for student '{cmd_student_id}'."
            elif student.pickup_deadline_for_reserved_book and current_date_obj > student.pickup_deadline_for_reserved_book:
                accept_error_reason = f"Reservation for '{sut_picked_book_copy_id}' expired on {student.pickup_deadline_for_reserved_book}."
            else: 
                book_type_picked = book_sut_claims_picked.type
                if book_type_picked == 'B' and student.held_b_book is not None:
                    accept_error_reason = f"Student already holds a B-type book ('{student.held_b_book[0]}')."
                elif book_type_picked == 'C' and cmd_isbn_to_pick in student.held_c_books_by_isbn:
                    accept_error_reason = f"Student already holds this C-type ISBN ('{student.held_c_books_by_isbn[cmd_isbn_to_pick][0]}')."
            
            if accept_error_reason:
                 return {"is_legal": False, "error_message": f"Logic Error (Pick Accept): SUT accepted pick of '{sut_picked_book_copy_id}', but {accept_error_reason} Line: '{sut_output_line}'."}

            self.current_state.apply_validated_pick_action(cmd_date_str, cmd_student_id, sut_picked_book_copy_id)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": "Internal Checker Error."}

    def validate_sut_read(self, cmd_date_str: str, cmd_student_id: str, cmd_isbn: str, sut_output_line: str) -> Dict[str, Any]:
        validation_result = self._common_user_op_validation(sut_output_line, cmd_date_str, cmd_student_id, "read")
        if validation_result and not validation_result.get("is_legal", True) : return validation_result
        parsed_sut = validation_result
        if not parsed_sut: return {"is_legal": False, "error_message": "Internal checker error during common validation for read."}

        sut_target_str = parsed_sut["target_str"]
        student = self._get_student(cmd_student_id)
        book_type_to_read = self.current_state._get_book_type_from_id_or_isbn(cmd_isbn)
        copies_on_shelf_ids = [bc_id for bc_id, bc in self.current_state.all_book_copies.items() if bc.isbn == cmd_isbn and bc.current_location in LibrarySystem.SHELF_LOCATIONS]

        if parsed_sut["status"] == "reject":
            if not _is_isbn_like(sut_target_str) or sut_target_str != cmd_isbn:
                return {"is_legal": False, "error_message": f"Format Error (Read Reject): Target '{sut_target_str}' invalid or mismatch. Expected ISBN '{cmd_isbn}'. Line: '{sut_output_line}'."}

            can_be_read_by_rule = True; rejection_reason_checker = "Checker finds read permissible."
            
            if student.credit_score <= 0:
                can_be_read_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' credit score is {student.credit_score} (<= 0), cannot read B/C books."
            elif book_type_to_read == 'A' and student.credit_score < 40:
                can_be_read_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' credit score is {student.credit_score} (< 40), cannot read A books."
            elif not copies_on_shelf_ids:
                can_be_read_by_rule = False; rejection_reason_checker = f"No copies of ISBN '{cmd_isbn}' are currently on any shelf."
            elif student.reading_book_copy_id_today is not None:
                can_be_read_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' is already reading book '{student.reading_book_copy_id_today}' today."

            if not can_be_read_by_rule: return {"is_legal": True} 
            else: return {"is_legal": False, "error_message": f"Logic Error (Read Reject): SUT rejected read of '{cmd_isbn}', but checker deems it permissible. Reason: {rejection_reason_checker} Line: '{sut_output_line}'."}

        elif parsed_sut["status"] == "accept":
            if not _is_book_copy_id_like(sut_target_str):
                return {"is_legal": False, "error_message": f"Format Error (Read Accept): Target '{sut_target_str}' not BookCopyID. Line: '{sut_output_line}'."}

            sut_book_copy_id = sut_target_str
            book_copy_sut_claims_to_read = self._get_book_copy(sut_book_copy_id)

            if not book_copy_sut_claims_to_read:
                return {"is_legal": False, "error_message": f"Logic Error (Read Accept): SUT read non-existent BookCopyID '{sut_book_copy_id}'. Line: '{sut_output_line}'."}
            if book_copy_sut_claims_to_read.isbn != cmd_isbn:
                return {"is_legal": False, "error_message": f"Logic Error (Read Accept): SUT read BookCopyID '{sut_book_copy_id}' (ISBN '{book_copy_sut_claims_to_read.isbn}'), command was for ISBN '{cmd_isbn}'. Line: '{sut_output_line}'."}

            accept_error_reason = ""
            if student.credit_score <= 0:
                accept_error_reason = f"Student '{cmd_student_id}' credit score is {student.credit_score} (<= 0), cannot read B/C books."
            elif book_copy_sut_claims_to_read.type == 'A' and student.credit_score < 40:
                accept_error_reason = f"Student '{cmd_student_id}' credit score is {student.credit_score} (< 40), cannot read A books."
            elif book_copy_sut_claims_to_read.current_location not in LibrarySystem.SHELF_LOCATIONS: 
                accept_error_reason = f"Book '{sut_book_copy_id}' was at '{book_copy_sut_claims_to_read.current_location}', not on a shelf."
            elif student.reading_book_copy_id_today is not None:
                accept_error_reason = f"Student '{cmd_student_id}' is already reading book '{student.reading_book_copy_id_today}' today."

            if accept_error_reason:
                return {"is_legal": False, "error_message": f"Logic Error (Read Accept): SUT accepted read of '{sut_book_copy_id}', but {accept_error_reason} Line: '{sut_output_line}'."}

            self.current_state.apply_validated_read_action(cmd_date_str, cmd_student_id, sut_book_copy_id)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": "Internal Checker Error."}

    def validate_sut_restore(self, cmd_date_str: str, cmd_student_id: str, cmd_book_copy_id: str, sut_output_line: str) -> Dict[str, Any]:
        validation_result = self._common_user_op_validation(sut_output_line, cmd_date_str, cmd_student_id, "restored")
        if validation_result and not validation_result.get("is_legal", True) : return validation_result
        parsed_sut = validation_result
        if not parsed_sut: return {"is_legal": False, "error_message": "Internal checker error during common validation for restore."}

        sut_target_str = parsed_sut["target_str"]
        if not _is_book_copy_id_like(sut_target_str) or sut_target_str != cmd_book_copy_id:
            return {"is_legal": False, "error_message": f"Format Error (Restore): Target '{sut_target_str}' invalid or mismatch. Expected BookCopyID '{cmd_book_copy_id}'. Line: '{sut_output_line}'."}

        if parsed_sut["status"] == "reject":
            book_copy_to_restore_check = self._get_book_copy(cmd_book_copy_id)
            student_check = self._get_student(cmd_student_id)
            if book_copy_to_restore_check and \
               book_copy_to_restore_check.current_location == "reading_room" and \
               book_copy_to_restore_check.current_holder_student_id == cmd_student_id and \
               student_check.reading_book_copy_id_today == cmd_book_copy_id:
                return {"is_legal": False, "error_message": f"Logic Error (Restore Reject): SUT rejected restore of '{cmd_book_copy_id}', but preconditions were met. Restores should succeed. Line: '{sut_output_line}'."}
            else:
                return {"is_legal": True} 
        
        elif parsed_sut["status"] == "accept":
            book_copy_to_restore = self._get_book_copy(cmd_book_copy_id)
            student = self._get_student(cmd_student_id)

            if not book_copy_to_restore:
                return {"is_legal": False, "error_message": f"Logic Error (Restore Accept): SUT accepted restore of non-existent book '{cmd_book_copy_id}'. Line: '{sut_output_line}'."}
            
            accept_error_reason = ""
            if not (book_copy_to_restore.current_location == "reading_room" and \
                    book_copy_to_restore.current_holder_student_id == cmd_student_id and \
                    student.reading_book_copy_id_today == cmd_book_copy_id):
                accept_error_reason = (f"Book was not in reading room under student's active read for today. "
                                      f"Book loc: {book_copy_to_restore.current_location}, holder: {book_copy_to_restore.current_holder_student_id}. "
                                      f"Student reading: {student.reading_book_copy_id_today}.")
            
            if accept_error_reason:
                return {"is_legal": False, "error_message": f"Logic Error (Restore Accept): SUT accepted restore, but {accept_error_reason} Line: '{sut_output_line}'."}

            self.current_state.apply_validated_restore_action(cmd_date_str, cmd_student_id, cmd_book_copy_id)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": "Internal Checker Error."}
    
    def validate_sut_query_credit(self, cmd_date_str: str, cmd_student_id: str, sut_output_line: str) -> Dict[str, Any]:
        parsed_sut = parse_sut_credit_query_line(sut_output_line)
        if not parsed_sut:
            return {"is_legal": False, "error_message": f"Format Error (Query Credit): Malformed SUT output line: '{sut_output_line}'"}
        
        if parsed_sut["date_str"] != cmd_date_str:
            return {"is_legal": False, "error_message": f"Context Error (Query Credit): SUT date mismatch. SUT: '{parsed_sut['date_str']}', Expected: '{cmd_date_str}'. Line: '{sut_output_line}'"}
        if parsed_sut["student_id"] != cmd_student_id:
            return {"is_legal": False, "error_message": f"Context Error (Query Credit): SUT student ID mismatch. SUT: '{parsed_sut['student_id']}', Expected: '{cmd_student_id}'. Line: '{sut_output_line}'"}

        student_in_state = self._get_student(cmd_student_id)
        expected_credit = student_in_state.credit_score
        sut_credit = parsed_sut["credit_score"]

        if sut_credit != expected_credit:
            return {"is_legal": False, "error_message": f"Logic Error (Query Credit): SUT reported credit score for '{cmd_student_id}' as {sut_credit}, but checker expected {expected_credit}. Line: '{sut_output_line}'"}

        return {"is_legal": True}

    def validate_sut_query_trace(self, cmd_date_str: str, cmd_book_copy_id_queried: str, sut_output_lines_for_query: List[str]) -> Dict[str, Any]:
        if not sut_output_lines_for_query:
            return {"is_legal": False, "error_message": f"Format Error (Query Trace): SUT produced no output for query of '{cmd_book_copy_id_queried}'."}

        parsed_header = parse_sut_query_header_line(sut_output_lines_for_query[0])
        if not parsed_header:
            return {"is_legal": False, "error_message": f"Format Error (Query Trace): Malformed SUT query header line: '{sut_output_lines_for_query[0]}'"}

        sut_date_str, sut_book_id_header, sut_trace_count = parsed_header
        if sut_date_str != cmd_date_str:
            return {"is_legal": False, "error_message": f"Context Error (Query Header): SUT date mismatch. SUT: '{sut_date_str}', Expected: '{cmd_date_str}'."}
        if sut_book_id_header != cmd_book_copy_id_queried:
            return {"is_legal": False, "error_message": f"Context Error (Query Header): SUT BookCopyID mismatch. SUT: '{sut_book_id_header}', Expected: '{cmd_book_copy_id_queried}'."}

        if len(sut_output_lines_for_query) != 1 + sut_trace_count:
            return {"is_legal": False, "error_message": f"Format Error (Query Trace): SUT query line count mismatch. Header declared: {sut_trace_count}, Actual: {len(sut_output_lines_for_query)-1}."}

        expected_trace_entries = self.current_state.get_book_copy_details_for_trace(cmd_book_copy_id_queried)
        if expected_trace_entries is None: 
            if sut_trace_count != 0:
                 return {"is_legal": False, "error_message": f"Logic Error (Query Trace Count): Queried non-existent book '{cmd_book_copy_id_queried}'. SUT reported {sut_trace_count} traces, expected 0."}
            expected_trace_entries = []

        if sut_trace_count != len(expected_trace_entries):
            return {"is_legal": False, "error_message": f"Logic Error (Query Trace Count): SUT reported {sut_trace_count} trace lines, but checker expected {len(expected_trace_entries)}."}

        for i in range(sut_trace_count):
            sut_detail_line_str = sut_output_lines_for_query[i + 1]
            parsed_detail = parse_sut_query_trace_detail_line(sut_detail_line_str)
            if not parsed_detail:
                return {"is_legal": False, "error_message": f"Format Error (Query Trace Detail): Malformed line {i+1}: '{sut_detail_line_str}'"}

            sut_seq, sut_detail_date, sut_from, sut_to = parsed_detail
            expected_seq_checker, (expected_detail_date_actual, expected_from_actual, expected_to_actual) = i + 1, expected_trace_entries[i]

            if sut_seq != expected_seq_checker:
                 return {"is_legal": False, "error_message": f"Logic Error (Query Trace Detail): Sequence number mismatch at trace line {i+1}. SUT: {sut_seq}, Expected: {expected_seq_checker}."}
            if sut_detail_date != expected_detail_date_actual:
                 return {"is_legal": False, "error_message": f"Logic Error (Query Trace Detail): Date mismatch at trace line {i+1}. SUT: '{sut_detail_date}', Expected: '{expected_detail_date_actual}'."}
            if sut_from != expected_from_actual:
                 return {"is_legal": False, "error_message": f"Logic Error (Query Trace Detail): 'from' location mismatch at trace line {i+1}. SUT: '{sut_from}', Expected: '{expected_from_actual}'."}
            if sut_to != expected_to_actual:
                 return {"is_legal": False, "error_message": f"Logic Error (Query Trace Detail): 'to' location mismatch at trace line {i+1}. SUT: '{sut_to}', Expected: '{expected_to_actual}'."}
        return {"is_legal": True}

    def validate_sut_tidy_moves(self, cmd_date_str:str, sut_move_output_lines: List[str], is_opening_tidy: bool) -> Dict[str, Any]:
        if not sut_move_output_lines:
            return {"is_legal": False, "error_message": "Format Error (Tidy): SUT produced no output for tidying phase." }
        try:
            num_sut_moves_declared = int(sut_move_output_lines[0])
            if num_sut_moves_declared < 0: raise ValueError()
        except ValueError:
            return {"is_legal": False, "error_message": f"Format Error (Tidy Count): SUT tidying move count ('{sut_move_output_lines[0]}') is not a non-negative integer."}

        if len(sut_move_output_lines) != 1 + num_sut_moves_declared:
            return {"is_legal": False, "error_message": f"Format Error (Tidy Line Count): SUT declared {num_sut_moves_declared} moves, but provided {len(sut_move_output_lines)-1}."}

        current_processing_date_obj = self.current_state.current_date_obj
        if not current_processing_date_obj:
            return {"is_legal": False, "error_message": "Checker Internal Error: current_date_obj not set."}

        for i in range(num_sut_moves_declared):
            move_line_str = sut_move_output_lines[i + 1]
            parsed_move = parse_sut_tidy_move_line(move_line_str)

            if not parsed_move:
                return {"is_legal": False, "error_message": f"Format Error (Tidy Move Detail): Malformed line {i+1}: '{move_line_str}'."}
            if parsed_move["date_str"] != cmd_date_str:
                 return {"is_legal": False, "error_message": f"Context Error (Tidy Move Date): SUT date mismatch. SUT: '{parsed_move['date_str']}', Expected: '{cmd_date_str}'."}

            book_copy_id_to_move = parsed_move["book_copy_id"]
            book_copy_object = self._get_book_copy(book_copy_id_to_move)
            if not book_copy_object:
                return {"is_legal": False, "error_message": f"Logic Error (Tidy Move): Attempt to move non-existent book '{book_copy_id_to_move}'. Line: '{move_line_str}'."}

            from_loc_short, to_loc_short = parsed_move["from_loc_short"], parsed_move["to_loc_short"]
            from_loc_full = LibrarySystem.REVERSE_LOCATION_SHORT_MAP.get(from_loc_short)
            to_loc_full = LibrarySystem.REVERSE_LOCATION_SHORT_MAP.get(to_loc_short)
            
            if from_loc_full == to_loc_full:
                return {"is_legal": False, "error_message": f"Logic Error (Tidy Move): 'from' and 'to' locations are the same ('{from_loc_short}'). Line: '{move_line_str}'."}

            if book_copy_object.current_location != from_loc_full:
                return {"is_legal": False, "error_message": (f"Logic Error (Tidy Move): SUT claims move from '{from_loc_full}', but book is at '{book_copy_object.current_location}'. Line: '{move_line_str}'." )}

            if from_loc_full == "appointment_office" and book_copy_object.ao_reserved_for_student_id and book_copy_object.ao_pickup_deadline:
                is_unmovable = False
                if is_opening_tidy:
                    if current_processing_date_obj <= book_copy_object.ao_pickup_deadline: is_unmovable = True
                else:
                    if current_processing_date_obj < book_copy_object.ao_pickup_deadline: is_unmovable = True
                
                if is_unmovable:
                    return {"is_legal": False, "error_message": (
                        f"Logic Error (Tidy Move): Attempted to move actively reserved book '{book_copy_id_to_move}' from AO "
                        f"(reserved until end of '{book_copy_object.ao_pickup_deadline}') on '{current_processing_date_obj}'. Line: '{move_line_str}'.")}
                else:
                    self.current_state.clear_expired_ao_reservation_for_book(book_copy_id_to_move)

            target_student_id_for_ao_move = parsed_move["target_student_for_ao"]
            calculated_pickup_deadline_for_ao_move: Optional[date] = None

            if to_loc_full == "appointment_office":
                if not target_student_id_for_ao_move:
                    return {"is_legal": False, "error_message": f"Logic Error (Tidy Move to AO): Missing student ID. Line: '{move_line_str}'."}
                
                student_for_ao = self._get_student(target_student_id_for_ao_move)
                if student_for_ao.pending_order_isbn != book_copy_object.isbn:
                    return {"is_legal": False, "error_message": (f"Logic Error (Tidy Move to AO): Moved '{book_copy_id_to_move}' for student '{target_student_id_for_ao_move}', "
                                                                 f"but student has pending order for '{student_for_ao.pending_order_isbn}'. Expected '{book_copy_object.isbn}'. Line: '{move_line_str}'.")}
                
                reservation_effective_date = current_processing_date_obj if is_opening_tidy else current_processing_date_obj + timedelta(days=1)
                calculated_pickup_deadline_for_ao_move = reservation_effective_date + timedelta(days=4)

            self.current_state._apply_book_movement(
                book_copy_id_to_move, from_loc_full, to_loc_full, cmd_date_str,
                ao_reservation_student_id=target_student_id_for_ao_move if to_loc_full == "appointment_office" else None,
                ao_pickup_deadline=calculated_pickup_deadline_for_ao_move if to_loc_full == "appointment_office" else None)
            
            if to_loc_full == "appointment_office" and target_student_id_for_ao_move and calculated_pickup_deadline_for_ao_move:
                self.current_state.apply_book_reservation_at_ao(
                    book_copy_id_to_move, target_student_id_for_ao_move, calculated_pickup_deadline_for_ao_move, is_opening_tidy)
            
        if is_opening_tidy:
            for book_id, book_obj in self.current_state.all_book_copies.items():
                if book_obj.current_location in ["borrow_return_office", "reading_room"]:
                    return {"is_legal": False, "error_message": f"Post-Tidy Logic Error (OPEN): Book '{book_id}' remains in '{book_obj.current_location}'."}
                if book_obj.current_location == "appointment_office" and book_obj.ao_pickup_deadline and current_processing_date_obj > book_obj.ao_pickup_deadline: 
                    return {"is_legal": False, "error_message": f"Post-Tidy Logic Error (OPEN): Overdue book '{book_id}' remains at AO."}
            
            hot_isbns = self.current_state.hot_isbns_for_current_open_tidy
            for book_id, book_obj in self.current_state.all_book_copies.items():
                if book_obj.current_location == "hot_bookshelf" and book_obj.isbn not in hot_isbns:
                    return {"is_legal": False, "error_message": f"Post-Tidy Logic Error (OPEN): Non-hot book '{book_id}' is on hbs."}
                elif book_obj.current_location == "bookshelf" and book_obj.isbn in hot_isbns:
                    return {"is_legal": False, "error_message": f"Post-Tidy Logic Error (OPEN): Hot book '{book_id}' is on bs."}
        return {"is_legal": True}


def check_cycle(cycle_command_strings: List[str],
                sut_all_output_lines_for_cycle: List[str],
                main_library_state: LibrarySystem) -> Dict[str, Any]:
    
    sut_output_idx = 0
    current_cycle_state_copy = copy.deepcopy(main_library_state)
    checker_instance = RuleChecker(current_cycle_state_copy) 

    for cmd_idx, command_str in enumerate(cycle_command_strings):
        parts = command_str.split()
        if not parts: continue

        cmd_date_str = parts[0][1:-1]
        cmd_date_obj = date.fromisoformat(cmd_date_str)
        
        # KEY CHANGE: Advance time BEFORE processing any command for the new date
        checker_instance.current_state.advance_time_to(cmd_date_obj)

        validation_result: Dict[str, Any] = {"is_legal": False, "error_message": "Checker Internal Error: Command not processed."}

        is_open_or_close_command = len(parts) == 2 and parts[1] in ["OPEN", "CLOSE"]

        if is_open_or_close_command:
            op_type = parts[1]
            if op_type == "OPEN":
                checker_instance.current_state.apply_open_action(cmd_date_str)
            else: # CLOSE
                checker_instance.current_state.apply_close_action(cmd_date_str)

            if sut_output_idx >= len(sut_all_output_lines_for_cycle):
                return {"is_legal": False, "error_message": f"Format Error ({op_type} Tidy): SUT ran out of output lines.", "first_failing_command": command_str}
            try:
                num_moves_sut = int(sut_all_output_lines_for_cycle[sut_output_idx])
                if num_moves_sut < 0: raise ValueError()
            except ValueError:
                return {"is_legal": False, "error_message": f"Format Error ({op_type} Tidy Count): Invalid count line '{sut_all_output_lines_for_cycle[sut_output_idx]}'.", "first_failing_command": command_str}

            if sut_output_idx + 1 + num_moves_sut > len(sut_all_output_lines_for_cycle):
                return {"is_legal": False, "error_message": f"Format Error ({op_type} Tidy Line Count): SUT declared {num_moves_sut} moves, but not enough lines provided.", "first_failing_command": command_str}

            sut_tidy_lines = sut_all_output_lines_for_cycle[sut_output_idx : sut_output_idx + 1 + num_moves_sut]
            sut_output_idx += (1 + num_moves_sut)
            validation_result = checker_instance.validate_sut_tidy_moves(cmd_date_str, sut_tidy_lines, is_opening_tidy=(op_type == "OPEN"))
        
        else:
            if len(parts) < 3:
                 validation_result = {"is_legal": False, "error_message": f"Format Error (User Op): Command '{command_str}' too short."}
            else:
                cmd_student_id, cmd_action = parts[1], parts[2]
                
                if cmd_action == "queried":
                    cmd_target_str = " ".join(parts[3:])
                    if cmd_target_str == "credit score":
                        if sut_output_idx >= len(sut_all_output_lines_for_cycle): return {"is_legal": False, "error_message": "SUT ran out of output for credit query.", "first_failing_command": command_str}
                        sut_op_line = sut_all_output_lines_for_cycle[sut_output_idx]; sut_output_idx += 1
                        validation_result = checker_instance.validate_sut_query_credit(cmd_date_str, cmd_student_id, sut_op_line)
                    else:
                        if sut_output_idx >= len(sut_all_output_lines_for_cycle): return {"is_legal": False, "error_message": "SUT ran out of output for trace query.", "first_failing_command": command_str}
                        sut_query_header_line = sut_all_output_lines_for_cycle[sut_output_idx]
                        parsed_q_header = parse_sut_query_header_line(sut_query_header_line)
                        if not parsed_q_header:
                            return {"is_legal": False, "error_message": f"Format Error: Malformed SUT header '{sut_query_header_line}'.", "first_failing_command": command_str}
                        _, _, num_traces = parsed_q_header
                        if sut_output_idx + 1 + num_traces > len(sut_all_output_lines_for_cycle):
                            return {"is_legal": False, "error_message": "Format Error: Not enough trace lines provided by SUT.", "first_failing_command": command_str}
                        sut_lines_for_query = sut_all_output_lines_for_cycle[sut_output_idx : sut_output_idx + 1 + num_traces]
                        sut_output_idx += (1 + num_traces)
                        validation_result = checker_instance.validate_sut_query_trace(cmd_date_str, parts[3], sut_lines_for_query)
                else: 
                    cmd_target = parts[3]
                    if sut_output_idx >= len(sut_all_output_lines_for_cycle):
                        return {"is_legal": False, "error_message": f"SUT ran out of output for command '{command_str}'.", "first_failing_command": command_str}
                    
                    sut_op_line = sut_all_output_lines_for_cycle[sut_output_idx]; sut_output_idx += 1
                    
                    if cmd_action == "borrowed": validation_result = checker_instance.validate_sut_borrow(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "returned": validation_result = checker_instance.validate_sut_return(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "ordered": validation_result = checker_instance.validate_sut_order(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "picked": validation_result = checker_instance.validate_sut_pick(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "read": validation_result = checker_instance.validate_sut_read(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "restored": validation_result = checker_instance.validate_sut_restore(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    else: validation_result = {"is_legal": False, "error_message": f"Checker Internal Error: Unknown action '{cmd_action}'."}
        
        if not validation_result.get("is_legal", False):
            err_msg = validation_result.get('error_message', 'Unknown validation error')
            return {"is_legal": False, "error_message": f"Validation failed for command '{command_str}': {err_msg}", "first_failing_command": command_str}

    if sut_output_idx < len(sut_all_output_lines_for_cycle):
        return {"is_legal": False, "error_message": f"Format Error (Extraneous Output): SUT produced extraneous output. First: '{sut_all_output_lines_for_cycle[sut_output_idx]}'", "first_failing_command": "End of cycle"}

    main_library_state.__dict__.update(current_cycle_state_copy.__dict__)
    return {"is_legal": True, "error_message": "", "first_failing_command": None}


if __name__ == "__main__":
    # The main block remains the same, it correctly uses the updated check_cycle function.
    import argparse
    parser = argparse.ArgumentParser(description="Checker for Library System SUT output (HW15 compliant).")
    parser.add_argument("input_file", help="Path to the input command file.")
    parser.add_argument("sut_output_file", help="Path to the SUT's output file.")
    args = parser.parse_args()

    all_input_commands, all_sut_output_lines = [], []
    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            all_input_commands = [line.strip() for line in f if line.strip()]
        with open(args.sut_output_file, 'r', encoding='utf-8') as f:
            all_sut_output_lines = [line.strip() for line in f if line.strip()]
    except FileNotFoundError as e:
        print(json.dumps({"status": "failure", "reason": f"Error reading files: {e}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"status": "failure", "reason": f"An unexpected error occurred: {e}"}))
        sys.exit(1)

    if not all_input_commands:
        print(json.dumps({"status": "success"} if not all_sut_output_lines else {"status": "failure", "reason": "Input empty, but SUT produced output."}))
        sys.exit(0)

    main_checker_library_state = LibrarySystem()
    input_cmd_idx_main = 0
    try:
        num_book_types_str = all_input_commands[input_cmd_idx_main]; input_cmd_idx_main += 1
        num_book_types = int(num_book_types_str)
        if num_book_types < 0: raise ValueError("Negative book types")
        if input_cmd_idx_main + num_book_types > len(all_input_commands):
            raise IndexError("Not enough lines for book initialization")
        book_init_lines = all_input_commands[input_cmd_idx_main : input_cmd_idx_main + num_book_types]
        input_cmd_idx_main += num_book_types
        main_checker_library_state.initialize_books(book_init_lines)
    except (ValueError, IndexError) as e:
        print(json.dumps({"status": "failure", "reason": f"Error during library initialization: {e}"}))
        sys.exit(1)

    remaining_commands_for_cycle = all_input_commands[input_cmd_idx_main:]
    
    if remaining_commands_for_cycle:
        cycle_validation_result = check_cycle(remaining_commands_for_cycle, all_sut_output_lines, main_checker_library_state)
        if not cycle_validation_result.get("is_legal", False):
            reason = cycle_validation_result.get('error_message', 'Unknown validation error')
            failing_cmd_context = cycle_validation_result.get('first_failing_command', 'N/A')
            print(json.dumps({"status": "failure", "reason": f"Validation failed: {reason}", "context": f"Command context: '{failing_cmd_context}'"}))
            sys.exit(1)
        else:
            print(json.dumps({"status": "success"}))
    elif not all_sut_output_lines:
        print(json.dumps({"status": "success"}))
    else:
        print(json.dumps({"status": "failure", "reason": "No commands after initialization, but SUT produced output."}))
        sys.exit(1)