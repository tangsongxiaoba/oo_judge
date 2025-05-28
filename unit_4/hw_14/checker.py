# checker.py
import io
import sys
import json
import copy
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple, Any

try:
    from state import LibrarySystem, BookCopy, Student
except ImportError:
    print(json.dumps({"is_legal": False, "error_message": "Critical Checker Error: Could not import from state.py."}))
    sys.exit(1)

# --- SUT Output Parsers ---
def parse_sut_user_op_line(line: str) -> Optional[Dict[str, str]]:
    parts = line.split()
    if len(parts) != 5: return None
    if not (parts[0].startswith("[") and parts[0].endswith("]") and
            parts[1].startswith("[") and parts[1].endswith("]")): return None
    date_str = parts[0][1:-1]
    try:
        date.fromisoformat(date_str)
    except ValueError: return None
    status = parts[1][1:-1]
    # "restored" always accepts per problem, but SUT might output [reject] if malformed, so keep "reject"
    # For other operations, SUT can genuinely reject.
    if status not in ["accept", "reject"]: return None 
    return {"date_str": date_str, "status": status, "student_id": parts[2], "action": parts[3], "target_str": parts[4]}

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
    # Use LibrarySystem's map for validation of short codes (includes bs, hbs, bro, ao, rr, user)
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
    
    # Valid locations for tidying: bs, hbs, bro, ao, rr
    valid_tidy_locs_short = [LibrarySystem.LOCATION_SHORT_MAP[loc] for loc in LibrarySystem.TIDY_INTERNAL_LOCATIONS]
    if from_loc_short not in valid_tidy_locs_short or to_loc_short not in valid_tidy_locs_short:
        # print(f"Debug: Invalid tidy loc short: from='{from_loc_short}', to='{to_loc_short}'. Valid: {valid_tidy_locs_short}")
        return None
    
    target_student_for_ao = None
    if len(parts) == 9:
        if parts[7] != "for": return None
        target_student_for_ao = parts[8]
        if to_loc_short != LibrarySystem.LOCATION_SHORT_MAP["appointment_office"]: return None # "for" only allowed if target is AO
    elif to_loc_short == LibrarySystem.LOCATION_SHORT_MAP["appointment_office"]: return None # Target AO must have "for"
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
    try:
        copy_num_int = int(parts[2]) 
        if not (1 <= copy_num_int <= 99): # Problem says max 10, but SUT might use more digits for copy_num if it makes them unique
             pass
    except ValueError:
        return False
    return True


class RuleChecker:
    def __init__(self, library_state: LibrarySystem):
        self.current_state = library_state # This will be a deepcopy per cycle

    def _get_book_copy(self, book_id: str) -> Optional[BookCopy]:
        return self.current_state._get_book_copy(book_id)

    def _get_student(self, student_id: str) -> Student:
        return self.current_state._get_student(student_id)

    def _common_user_op_validation(self, sut_output_line: str, cmd_date_str: str, cmd_student_id: str, expected_action: str) -> Optional[Dict[str, str]]:
        parsed_sut = parse_sut_user_op_line(sut_output_line)
        if not parsed_sut:
            return {"is_legal": False, "error_message": f"Format Error ({expected_action.capitalize()}): SUT output line '{sut_output_line}' is malformed."}
        if parsed_sut["action"] != expected_action:
            return {"is_legal": False, "error_message": f"Context Error ({expected_action.capitalize()}): SUT action is '{parsed_sut['action']}', expected '{expected_action}'. Line: '{sut_output_line}'."}
        if parsed_sut["student_id"] != cmd_student_id:
            return {"is_legal": False, "error_message": f"Context Error ({expected_action.capitalize()}): SUT student ID '{parsed_sut['student_id']}', expected '{cmd_student_id}'. Line: '{sut_output_line}'."}
        if parsed_sut["date_str"] != cmd_date_str:
            return {"is_legal": False, "error_message": f"Context Error ({expected_action.capitalize()}): SUT date '{parsed_sut['date_str']}', expected '{cmd_date_str}'. Line: '{sut_output_line}'."}
        return parsed_sut # Return parsed if basic checks pass

    def validate_sut_borrow(self, cmd_date_str:str, cmd_student_id: str, cmd_isbn: str, sut_output_line: str) -> Dict[str, Any]:
        validation_result = self._common_user_op_validation(sut_output_line, cmd_date_str, cmd_student_id, "borrowed")
        if validation_result and not validation_result.get("is_legal", True) : return validation_result # Error from common check
        if not validation_result: return {"is_legal": False, "error_message": "Internal checker error during common validation for borrow."} # Should not happen
        parsed_sut = validation_result
        
        sut_target_str = parsed_sut["target_str"]
        student = self._get_student(cmd_student_id)
        book_type_to_borrow = self.current_state._get_book_type_from_id_or_isbn(cmd_isbn)

        if parsed_sut["status"] == "reject":
            if not _is_isbn_like(sut_target_str) or sut_target_str != cmd_isbn:
                return {"is_legal": False, "error_message": f"Format Error (Borrow Reject): SUT target '{sut_target_str}' invalid or mismatch. Expected ISBN '{cmd_isbn}'. Line: '{sut_output_line}'."}

            can_be_borrowed_by_rule = True; rejection_reason_checker = "Checker finds borrow permissible."
            
            copies_on_shelf_ids = []
            if self.current_state.books_on_shelf_by_isbn.get(cmd_isbn):
                for bc_id in self.current_state.books_on_shelf_by_isbn[cmd_isbn]: # This list only contains books on bs/hbs
                    bc = self._get_book_copy(bc_id)
                    # Redundant check for location if books_on_shelf_by_isbn is correctly maintained by state.py
                    if bc and bc.current_location in LibrarySystem.SHELF_LOCATIONS:
                         copies_on_shelf_ids.append(bc_id)
            if not copies_on_shelf_ids:
                can_be_borrowed_by_rule = False; rejection_reason_checker = f"No copies of ISBN '{cmd_isbn}' are currently on any shelf (bs/hbs)."
            elif book_type_to_borrow == 'A':
                can_be_borrowed_by_rule = False; rejection_reason_checker = "Book is Type A (cannot be borrowed)."
            elif book_type_to_borrow == 'B' and student.held_b_book_copy_id is not None:
                can_be_borrowed_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already holds a B-type book ('{student.held_b_book_copy_id}')."
            elif book_type_to_borrow == 'C' and cmd_isbn in student.held_c_books_by_isbn:
                can_be_borrowed_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already holds a copy of this C-type ISBN '{cmd_isbn}' ('{student.held_c_books_by_isbn[cmd_isbn]}')."

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
            if book_copy_sut_claims_to_lend.type == 'A':
                accept_error_reason = f"Book '{sut_book_copy_id}' is Type A (cannot be borrowed)."
            elif book_copy_sut_claims_to_lend.current_location not in LibrarySystem.SHELF_LOCATIONS:
                accept_error_reason = f"Book '{sut_book_copy_id}' was at '{book_copy_sut_claims_to_lend.current_location}', not on a shelf (bs/hbs)."
            elif book_copy_sut_claims_to_lend.type == 'B' and student.held_b_book_copy_id is not None:
                accept_error_reason = f"Student '{cmd_student_id}' already holds a B-type book ('{student.held_b_book_copy_id}')."
            elif book_copy_sut_claims_to_lend.type == 'C' and cmd_isbn in student.held_c_books_by_isbn:
                accept_error_reason = f"Student '{cmd_student_id}' already holds a copy of this C-type ISBN '{cmd_isbn}' ('{student.held_c_books_by_isbn[cmd_isbn]}')."

            if accept_error_reason:
                return {"is_legal": False, "error_message": f"Logic Error (Borrow Accept): SUT accepted borrow of '{sut_book_copy_id}', but {accept_error_reason} Line: '{sut_output_line}'."}

            self.current_state.apply_validated_borrow_action(cmd_date_str, cmd_student_id, sut_book_copy_id)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": f"Internal Checker Error: Unknown SUT status '{parsed_sut['status']}'. Line: '{sut_output_line}'."} 

    def validate_sut_return(self, cmd_date_str:str, cmd_student_id: str, cmd_book_copy_id: str, sut_output_line: str) -> Dict[str, Any]:
        validation_result = self._common_user_op_validation(sut_output_line, cmd_date_str, cmd_student_id, "returned")
        if validation_result and not validation_result.get("is_legal", True) : return validation_result
        if not validation_result: return {"is_legal": False, "error_message": "Internal checker error during common validation for return."}
        parsed_sut = validation_result
        
        sut_target_str = parsed_sut["target_str"]
        if not _is_book_copy_id_like(sut_target_str) or sut_target_str != cmd_book_copy_id:
            return {"is_legal": False, "error_message": f"Format Error (Return): SUT target '{sut_target_str}' invalid or mismatch. Expected BookCopyID '{cmd_book_copy_id}'. Line: '{sut_output_line}'."}

        if parsed_sut["status"] == "reject":
            return {"is_legal": False, "error_message": f"Logic Error (Return Reject): SUT rejected return of '{cmd_book_copy_id}'. Returns should always be accepted. Line: '{sut_output_line}'."}
        
        elif parsed_sut["status"] == "accept":
            book_copy_to_return = self._get_book_copy(cmd_book_copy_id)
            if not book_copy_to_return:
                return {"is_legal": False, "error_message": f"Logic Error (Return Accept): SUT accepted return of non-existent book '{cmd_book_copy_id}'. Line: '{sut_output_line}'."}
            
            if not (book_copy_to_return.current_location == "user" and book_copy_to_return.current_holder_student_id == cmd_student_id):
                 return {"is_legal": False, "error_message": (f"Logic Error (Return Accept): SUT accepted return of '{cmd_book_copy_id}' by '{cmd_student_id}', "
                                                              f"but book state is inconsistent. Expected: held by student at 'user'. "
                                                              f"Actual: loc='{book_copy_to_return.current_location}', holder='{book_copy_to_return.current_holder_student_id}'. Line: '{sut_output_line}'." )}
            self.current_state.apply_validated_return_action(cmd_date_str, cmd_student_id, cmd_book_copy_id)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": f"Internal Checker Error: Unknown SUT status '{parsed_sut['status']}'. Line: '{sut_output_line}'."}

    def validate_sut_order(self, cmd_date_str:str, cmd_student_id: str, cmd_isbn: str, sut_output_line: str) -> Dict[str, Any]:
        validation_result = self._common_user_op_validation(sut_output_line, cmd_date_str, cmd_student_id, "ordered")
        if validation_result and not validation_result.get("is_legal", True) : return validation_result
        if not validation_result: return {"is_legal": False, "error_message": "Internal checker error during common validation for order."}
        parsed_sut = validation_result

        sut_target_str = parsed_sut["target_str"]
        if not _is_isbn_like(sut_target_str) or sut_target_str != cmd_isbn:
            return {"is_legal": False, "error_message": f"Format Error (Order): Target '{sut_target_str}' invalid or mismatch. Expected ISBN '{cmd_isbn}'. Line: '{sut_output_line}'."}

        student = self._get_student(cmd_student_id)
        book_type_to_order = self.current_state._get_book_type_from_id_or_isbn(cmd_isbn)

        if parsed_sut["status"] == "reject":
            can_be_ordered_by_rule = True; rejection_reason_checker = "Checker finds order permissible."
            if book_type_to_order == 'A':
                can_be_ordered_by_rule = False; rejection_reason_checker = "Book is Type A (cannot be ordered)."
            elif student.pending_order_isbn is not None or student.reserved_book_copy_id_at_ao is not None: # "若此前已经预定过书籍且还未取书，则预约失败"
                can_be_ordered_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already has pending order ('{student.pending_order_isbn}') or reserved book at AO ('{student.reserved_book_copy_id_at_ao}')."
            elif book_type_to_order == 'B' and student.held_b_book_copy_id is not None:
                can_be_ordered_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' holds a B-type book, cannot order another B."
            elif book_type_to_order == 'C' and cmd_isbn in student.held_c_books_by_isbn:
                can_be_ordered_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' holds this C-type ISBN."
            
            if not can_be_ordered_by_rule: return {"is_legal": True}
            else: return {"is_legal": False, "error_message": f"Logic Error (Order Reject): SUT rejected order for '{cmd_isbn}', but checker deems it permissible. Reason: {rejection_reason_checker} Line: '{sut_output_line}'."}

        elif parsed_sut["status"] == "accept":
            accept_error_reason = ""
            if book_type_to_order == 'A':
                accept_error_reason = "Book is Type A (cannot be ordered)."
            elif student.pending_order_isbn is not None or student.reserved_book_copy_id_at_ao is not None:
                accept_error_reason = f"Student '{cmd_student_id}' already has pending order ('{student.pending_order_isbn}') or reserved book at AO ('{student.reserved_book_copy_id_at_ao}')."
            elif book_type_to_order == 'B' and student.held_b_book_copy_id is not None:
                accept_error_reason = f"Student '{cmd_student_id}' holds a B-type book, cannot order another B."
            elif book_type_to_order == 'C' and cmd_isbn in student.held_c_books_by_isbn:
                accept_error_reason = f"Student '{cmd_student_id}' holds this C-type ISBN."

            if accept_error_reason:
                return {"is_legal": False, "error_message": f"Logic Error (Order Accept): SUT accepted order for '{cmd_isbn}', but {accept_error_reason} Line: '{sut_output_line}'."}
            
            self.current_state.apply_validated_order_action(cmd_student_id, cmd_isbn)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": f"Internal Checker Error (Order): Unknown SUT status '{parsed_sut['status']}'. Line: '{sut_output_line}'."}

    def validate_sut_pick(self, cmd_date_str:str, cmd_student_id: str, cmd_isbn_to_pick: str, sut_output_line: str) -> Dict[str, Any]:
        validation_result = self._common_user_op_validation(sut_output_line, cmd_date_str, cmd_student_id, "picked")
        if validation_result and not validation_result.get("is_legal", True) : return validation_result
        if not validation_result: return {"is_legal": False, "error_message": "Internal checker error during common validation for pick."}
        parsed_sut = validation_result

        current_date_obj = self.current_state.current_date_obj
        if not current_date_obj: return {"is_legal": False, "error_message": "Checker Internal Error: current_date_obj not set for pick."}

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
                if not reserved_book_copy: # Should not happen if state is consistent
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
                    elif book_type_at_ao == 'C' and cmd_isbn_to_pick in student.held_c_books_by_isbn: # Check specific ISBN for C type
                        can_be_picked_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' already holds a copy of this C-type ISBN '{cmd_isbn_to_pick}' ('{student.held_c_books_by_isbn[cmd_isbn_to_pick]}')."

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
            
            # Crucial: Student must pick the *specific copy* that was reserved for them.
            if student.reserved_book_copy_id_at_ao != sut_picked_book_copy_id :
                 return {"is_legal": False, "error_message": f"Logic Error (Pick Accept): SUT picked '{sut_picked_book_copy_id}', but student '{cmd_student_id}' had a different copy ID '{student.reserved_book_copy_id_at_ao}' reserved at AO (even if for the same ISBN '{cmd_isbn_to_pick}'). Line: '{sut_output_line}'."}


            accept_error_reason = ""
            if book_sut_claims_picked.current_location != "appointment_office" or book_sut_claims_picked.ao_reserved_for_student_id != cmd_student_id:
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
                 return {"is_legal": False, "error_message": f"Logic Error (Pick Accept): SUT accepted pick of '{sut_picked_book_copy_id}', but {accept_error_reason} Line: '{sut_output_line}'."}

            self.current_state.apply_validated_pick_action(cmd_date_str, cmd_student_id, sut_picked_book_copy_id)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": f"Internal Checker Error (Pick): Unknown SUT status '{parsed_sut['status']}'. Line: '{sut_output_line}'."}

    def validate_sut_read(self, cmd_date_str: str, cmd_student_id: str, cmd_isbn: str, sut_output_line: str) -> Dict[str, Any]:
        validation_result = self._common_user_op_validation(sut_output_line, cmd_date_str, cmd_student_id, "read")
        if validation_result and not validation_result.get("is_legal", True) : return validation_result
        if not validation_result: return {"is_legal": False, "error_message": "Internal checker error during common validation for read."}
        parsed_sut = validation_result

        sut_target_str = parsed_sut["target_str"]
        student = self._get_student(cmd_student_id)

        if parsed_sut["status"] == "reject":
            if not _is_isbn_like(sut_target_str) or sut_target_str != cmd_isbn:
                return {"is_legal": False, "error_message": f"Format Error (Read Reject): Target '{sut_target_str}' invalid or mismatch. Expected ISBN '{cmd_isbn}'. Line: '{sut_output_line}'."}

            can_be_read_by_rule = True; rejection_reason_checker = "Checker finds read permissible."
            
            copies_on_shelf_ids = []
            if self.current_state.books_on_shelf_by_isbn.get(cmd_isbn):
                for bc_id in self.current_state.books_on_shelf_by_isbn[cmd_isbn]:
                    bc = self._get_book_copy(bc_id)
                    if bc and bc.current_location in LibrarySystem.SHELF_LOCATIONS: # bs or hbs
                         copies_on_shelf_ids.append(bc_id)
            if not copies_on_shelf_ids:
                can_be_read_by_rule = False; rejection_reason_checker = f"No copies of ISBN '{cmd_isbn}' are currently on any shelf (bs/hbs)."
            elif student.reading_book_copy_id_today is not None:
                can_be_read_by_rule = False; rejection_reason_checker = f"Student '{cmd_student_id}' is already reading book '{student.reading_book_copy_id_today}' today and has not restored it."
            # Type A can be read. No other holding restrictions for reading.

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
            if book_copy_sut_claims_to_read.current_location not in LibrarySystem.SHELF_LOCATIONS: 
                accept_error_reason = f"Book '{sut_book_copy_id}' was at '{book_copy_sut_claims_to_read.current_location}', not on a shelf (bs/hbs)."
            elif student.reading_book_copy_id_today is not None:
                accept_error_reason = f"Student '{cmd_student_id}' is already reading book '{student.reading_book_copy_id_today}' today and has not restored it."

            if accept_error_reason:
                return {"is_legal": False, "error_message": f"Logic Error (Read Accept): SUT accepted read of '{sut_book_copy_id}', but {accept_error_reason} Line: '{sut_output_line}'."}

            self.current_state.apply_validated_read_action(cmd_date_str, cmd_student_id, sut_book_copy_id)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": f"Internal Checker Error (Read): Unknown SUT status '{parsed_sut['status']}'. Line: '{sut_output_line}'."}

    def validate_sut_restore(self, cmd_date_str: str, cmd_student_id: str, cmd_book_copy_id: str, sut_output_line: str) -> Dict[str, Any]:
        validation_result = self._common_user_op_validation(sut_output_line, cmd_date_str, cmd_student_id, "restored")
        if validation_result and not validation_result.get("is_legal", True) : return validation_result
        if not validation_result: return {"is_legal": False, "error_message": "Internal checker error during common validation for restore."}
        parsed_sut = validation_result

        sut_target_str = parsed_sut["target_str"]
        if not _is_book_copy_id_like(sut_target_str) or sut_target_str != cmd_book_copy_id:
            return {"is_legal": False, "error_message": f"Format Error (Restore): Target '{sut_target_str}' invalid or mismatch. Expected BookCopyID '{cmd_book_copy_id}'. Line: '{sut_output_line}'."}

        # Problem: "阅读归还立即成功" - implies SUT should always accept if student *is* reading that book.
        # However, SUT could output "reject" if the command itself is malformed from SUT's perspective,
        # or if student isn't actually reading the book. The checker checks the *premise* for acceptance.
        if parsed_sut["status"] == "reject":
            # SUT rejected. If the student was NOT reading this book, SUT's reject is "correct" in a sense,
            # even if the problem says "restore always succeeds". "Succeeds" implies the precondition (student is reading it) is met.
            # For this checker, we will be strict: if preconditions for restore are met, SUT *must* accept.
            # If preconditions are not met, SUT *should* ideally reject (or problem implies command won't be generated).
            # Let's assume if SUT rejects, it must be because preconditions weren't met.
            book_copy_to_restore_check = self._get_book_copy(cmd_book_copy_id)
            student_check = self._get_student(cmd_student_id)
            if book_copy_to_restore_check and \
               book_copy_to_restore_check.current_location == "reading_room" and \
               book_copy_to_restore_check.current_holder_student_id == cmd_student_id and \
               student_check.reading_book_copy_id_today == cmd_book_copy_id:
                # Preconditions were met, SUT should have accepted.
                return {"is_legal": False, "error_message": f"Logic Error (Restore Reject): SUT rejected restore of '{cmd_book_copy_id}', but preconditions were met (student was reading it). Restores should succeed. Line: '{sut_output_line}'."}
            else:
                # Preconditions not met (e.g., student wasn't reading this book). SUT's reject is fine.
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
                accept_error_reason = (f"Book '{cmd_book_copy_id}' was not in reading room under student '{cmd_student_id}'s active read for today according to checker state. "
                                      f"Book loc: {book_copy_to_restore.current_location}, holder: {book_copy_to_restore.current_holder_student_id}. "
                                      f"Student reading: {student.reading_book_copy_id_today}.")
            
            if accept_error_reason:
                return {"is_legal": False, "error_message": f"Logic Error (Restore Accept): SUT accepted restore, but {accept_error_reason} Line: '{sut_output_line}'."}

            self.current_state.apply_validated_restore_action(cmd_date_str, cmd_student_id, cmd_book_copy_id)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": f"Internal Checker Error (Restore): Unknown SUT status '{parsed_sut['status']}'. Line: '{sut_output_line}'."}

    def validate_sut_query(self, cmd_date_str: str, cmd_book_copy_id_queried: str, sut_output_lines_for_query: List[str]) -> Dict[str, Any]:
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
            # This means the book_id itself doesn't exist in our state.
            # SUT should ideally also report 0 traces or handle it gracefully.
            # The problem implies SUT will receive valid book IDs for query.
            # If checker has no record, but SUT gives traces, it's an issue.
            if sut_trace_count != 0:
                 return {"is_legal": False, "error_message": f"Logic Error (Query Trace Count): Queried book '{cmd_book_copy_id_queried}' for which checker has no record. SUT reported {sut_trace_count} traces, expected 0."}
            expected_trace_entries = []


        if sut_trace_count != len(expected_trace_entries):
            return {"is_legal": False, "error_message": f"Logic Error (Query Trace Count): SUT query for '{cmd_book_copy_id_queried}' reported {sut_trace_count} trace lines, but checker expected {len(expected_trace_entries)} based on current state."}

        for i in range(sut_trace_count):
            trace_line_num_sut_perspective = i + 1
            sut_detail_line_str = sut_output_lines_for_query[trace_line_num_sut_perspective]
            parsed_detail = parse_sut_query_trace_detail_line(sut_detail_line_str) # Uses updated LOCATION_SHORT_MAP
            if not parsed_detail:
                return {"is_legal": False, "error_message": f"Format Error (Query Trace Detail): Malformed SUT trace detail line {trace_line_num_sut_perspective}: '{sut_detail_line_str}'"}

            sut_seq, sut_detail_date, sut_from, sut_to = parsed_detail
            expected_seq_checker = i + 1 
            # expected_trace_entries[i] is (date_str, from_short, to_short)
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

    def validate_sut_tidy_moves(self, cmd_date_str:str, sut_move_output_lines: List[str], is_opening_tidy: bool) -> Dict[str, Any]:
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

        # Simulate SUT's moves on a temporary copy of book states for this validation phase
        # This is important because one SUT move might affect the precondition for a subsequent SUT move in the same tidy batch.
        # The self.current_state will only be updated if *all* SUT moves in the batch are valid.
        # For simplicity in this step-by-step update, we will apply moves to self.current_state
        # and rely on the overall check_cycle to use a deepcopy for the whole cycle.
        # If a move is invalid, we'll return error immediately.

        for i in range(num_sut_moves_declared):
            move_line_index_sut = i + 1 
            move_line_str = sut_move_output_lines[move_line_index_sut]
            parsed_move = parse_sut_tidy_move_line(move_line_str) # Uses updated TIDY_INTERNAL_LOCATIONS

            if not parsed_move:
                return {"is_legal": False, "error_message": f"Format Error (Tidy Move Detail): Malformed SUT tidy move line {move_line_index_sut}: '{move_line_str}'."}

            if parsed_move["date_str"] != cmd_date_str:
                 return {"is_legal": False, "error_message": f"Context Error (Tidy Move Date): SUT tidy move line {move_line_index_sut} date mismatch. SUT date: '{parsed_move['date_str']}', Expected: '{cmd_date_str}'. Line: '{move_line_str}'."}

            book_copy_id_to_move = parsed_move["book_copy_id"]
            book_copy_object = self._get_book_copy(book_copy_id_to_move) # Get from current checker state
            if not book_copy_object:
                return {"is_legal": False, "error_message": f"Logic Error (Tidy Move): SUT tidy move line {move_line_index_sut}: attempt to move non-existent book '{book_copy_id_to_move}'. Line: '{move_line_str}'."}

            from_loc_short = parsed_move["from_loc_short"]
            to_loc_short = parsed_move["to_loc_short"]
            from_loc_full = LibrarySystem.REVERSE_LOCATION_SHORT_MAP.get(from_loc_short)
            to_loc_full = LibrarySystem.REVERSE_LOCATION_SHORT_MAP.get(to_loc_short)
            
            if not from_loc_full or not to_loc_full: # Should be caught by parse_sut_tidy_move_line
                 return {"is_legal": False, "error_message": f"Internal Error (Tidy Move): Invalid short codes '{from_loc_short}' or '{to_loc_short}'. Line: '{move_line_str}'."}


            if from_loc_full == to_loc_full: # Rule: "起点和终点不能相同"
                return {"is_legal": False, "error_message": f"Logic Error (Tidy Move): SUT tidy move line {move_line_index_sut} for '{book_copy_id_to_move}': 'from' and 'to' locations are the same ('{from_loc_short}'). Line: '{move_line_str}'."}

            if book_copy_object.current_location != from_loc_full:
                return {"is_legal": False, "error_message": (f"Logic Error (Tidy Move): SUT tidy move line {move_line_index_sut} for '{book_copy_id_to_move}': "
                                                             f"SUT claims move from '{from_loc_full}', but book is at '{book_copy_object.current_location}' in checker state. Line: '{move_line_str}'." )}

            # Check if moving a reserved book from AO prematurely
            if from_loc_full == "appointment_office" and \
               book_copy_object.ao_reserved_for_student_id and \
               book_copy_object.ao_pickup_deadline:
                
                is_unmovable_due_to_active_reservation = False
                # "在此期间，该书不能在整理流程中移动。"
                # "第五天闭馆时，该书不再视作为该用户保留...从次日起...图书馆可对该书进行整理。"
                # Example: Reserved on Jan 1 (OPEN tidy) -> deadline Jan 5.
                #   Cannot move on Jan 1,2,3,4,5 (OPEN or CLOSE tidy).
                #   On Jan 5 CLOSE tidy, it becomes "no longer reserved".
                #   On Jan 6 OPEN tidy, it can be moved.
                # Example: Reserved on Jan 1 (CLOSE tidy) -> effective Jan 2, deadline Jan 6.
                #   Cannot move on Jan 2,3,4,5,6 (OPEN or CLOSE tidy).
                #   On Jan 6 CLOSE tidy, it becomes "no longer reserved".
                #   On Jan 7 OPEN tidy, it can be moved.

                if is_opening_tidy: # OPEN tidy on current_processing_date_obj
                    # If deadline is *today or later*, it's still active.
                    if current_processing_date_obj <= book_copy_object.ao_pickup_deadline:
                        is_unmovable_due_to_active_reservation = True
                else: # CLOSE tidy on current_processing_date_obj
                    # If deadline is *tomorrow or later* (i.e. > today), it's still active through today's close.
                    if current_processing_date_obj < book_copy_object.ao_pickup_deadline:
                        is_unmovable_due_to_active_reservation = True
                
                if is_unmovable_due_to_active_reservation:
                    return {"is_legal": False, "error_message": (
                        f"Logic Error (Tidy Move): SUT tidy move line {move_line_index_sut}: "
                        f"attempted to move actively reserved book '{book_copy_id_to_move}' "
                        f"(reserved for '{book_copy_object.ao_reserved_for_student_id}' "
                        f"until end of day '{book_copy_object.ao_pickup_deadline}') from AO "
                        f"on '{current_processing_date_obj}' during {'OPEN' if is_opening_tidy else 'CLOSE'} tidy. "
                        f"Book is still actively reserved and cannot be moved. Line: '{move_line_str}'.")}
                else: # Reservation has expired or will expire by end of this CLOSE tidy
                    # If SUT moves it, its reservation details in state must be cleared.
                    self.current_state.clear_expired_ao_reservation_for_book(book_copy_id_to_move)


            target_student_id_for_ao_move = parsed_move["target_student_for_ao"]
            calculated_pickup_deadline_for_ao_move: Optional[date] = None

            if to_loc_full == "appointment_office":
                if not target_student_id_for_ao_move: # Should be caught by parser
                    return {"is_legal": False, "error_message": f"Logic Error (Tidy Move to AO): Missing student ID for reservation. Line: '{move_line_str}'."}
                
                student_for_ao = self._get_student(target_student_id_for_ao_move)
                if student_for_ao.pending_order_isbn != book_copy_object.isbn:
                    return {"is_legal": False, "error_message": (f"Logic Error (Tidy Move to AO): SUT tidy move line {move_line_index_sut}: moved '{book_copy_id_to_move}' (ISBN: {book_copy_object.isbn}) to AO for student '{target_student_id_for_ao_move}', "
                                                                 f"but student has pending order for '{student_for_ao.pending_order_isbn}' (or no order for this ISBN). Expected pending order for ISBN '{book_copy_object.isbn}'. Line: '{move_line_str}'.")}
                # Rule: "不可以为没有预定特定书籍的用户预留该书籍"

                # Calculate the correct deadline based on rules
                reservation_effective_date = current_processing_date_obj
                if not is_opening_tidy: # If moved during CLOSE tidy
                    reservation_effective_date += timedelta(days=1) # Effective next day
                calculated_pickup_deadline_for_ao_move = reservation_effective_date + timedelta(days=4) # Preserved for 5 days (day 0 to day 4)

            # Apply the move to the current_state (which is a cycle's deepcopy)
            self.current_state._apply_book_movement(
                book_copy_id_to_move, from_loc_full, to_loc_full, cmd_date_str,
                ao_reservation_student_id=target_student_id_for_ao_move if to_loc_full == "appointment_office" else None,
                ao_pickup_deadline=calculated_pickup_deadline_for_ao_move if to_loc_full == "appointment_office" else None
            )
            
            # If moved to AO for reservation, also update student's state
            if to_loc_full == "appointment_office" and target_student_id_for_ao_move and calculated_pickup_deadline_for_ao_move:
                self.current_state.apply_book_reservation_at_ao(
                    book_copy_id_to_move, target_student_id_for_ao_move, calculated_pickup_deadline_for_ao_move, is_opening_tidy
                )
            
        # --- Post-Tidy Checks (after all SUT moves for this tidy phase are processed) ---
        if is_opening_tidy:
            # 1. BRO and RR should be empty
            for book_id_check, book_obj_check in self.current_state.all_book_copies.items():
                if book_obj_check.current_location == "borrow_return_office":
                    return {"is_legal": False, "error_message": f"Post-Tidy Logic Error (OPEN on {cmd_date_str}): Book '{book_id_check}' remains in Borrow/Return Office (bro). BRO should be empty."}
                if book_obj_check.current_location == "reading_room":
                    return {"is_legal": False, "error_message": f"Post-Tidy Logic Error (OPEN on {cmd_date_str}): Book '{book_id_check}' remains in Reading Room (rr). RR should be empty."}
            
            # 2. AO should not have overdue books
            for book_id_check, book_obj_check in self.current_state.all_book_copies.items():
                if book_obj_check.current_location == "appointment_office" and \
                   book_obj_check.ao_reserved_for_student_id and \
                   book_obj_check.ao_pickup_deadline and \
                   current_processing_date_obj > book_obj_check.ao_pickup_deadline: 
                    return {"is_legal": False, "error_message": (f"Post-Tidy Logic Error (OPEN on {cmd_date_str}): Overdue book '{book_id_check}' "
                                                                 f"(reserved for '{book_obj_check.ao_reserved_for_student_id}', expired '{book_obj_check.ao_pickup_deadline}') "
                                                                 f"remains at Appointment Office (ao). Overdue books should be moved out.")}
            # 3. Hot/Non-hot bookshelf checks
            hot_isbns_for_this_tidy = self.current_state.hot_isbns_for_current_open_tidy
            for book_id_check, book_obj_check in self.current_state.all_book_copies.items():
                if book_obj_check.current_location == "hot_bookshelf": # hbs
                    if book_obj_check.isbn not in hot_isbns_for_this_tidy:
                        return {"is_legal": False, "error_message": (f"Post-Tidy Logic Error (OPEN on {cmd_date_str}): Book '{book_id_check}' (ISBN '{book_obj_check.isbn}') is on Hot Bookshelf (hbs), "
                                                                     f"but its ISBN is not in the set of hot ISBNs for this tidy ({hot_isbns_for_this_tidy}).")}
                elif book_obj_check.current_location == "bookshelf": # bs
                    if book_obj_check.isbn in hot_isbns_for_this_tidy:
                        return {"is_legal": False, "error_message": (f"Post-Tidy Logic Error (OPEN on {cmd_date_str}): Book '{book_id_check}' (ISBN '{book_obj_check.isbn}') is on Ordinary Bookshelf (bs), "
                                                                     f"but its ISBN IS in the set of hot ISBNs for this tidy ({hot_isbns_for_this_tidy}). Should be on hbs.")}
        return {"is_legal": True}


def check_cycle(cycle_command_strings: List[str],
                sut_all_output_lines_for_cycle: List[str],
                main_library_state: LibrarySystem) -> Dict[str, Any]:
    
    sut_output_idx = 0
    # Crucial: operate on a deep copy for this cycle's validation
    # If validation passes, main_library_state will be updated with this copy.
    current_cycle_state_copy = copy.deepcopy(main_library_state)
    checker_instance = RuleChecker(current_cycle_state_copy) 

    for cmd_idx, command_str in enumerate(cycle_command_strings):
        parts = command_str.split()
        if not parts: continue # Skip empty lines if any

        cmd_date_str = parts[0][1:-1] # Assuming all commands start with [YYYY-mm-dd]
        validation_result: Dict[str, Any] = {"is_legal": False, "error_message": "Checker Internal Error: Command not processed."}

        is_open_or_close_command = len(parts) == 2 and parts[1] in ["OPEN", "CLOSE"]

        if is_open_or_close_command:
            op_type = parts[1]
            is_opening_tidy_local = (op_type == "OPEN")
            
            if is_opening_tidy_local:
                # This applies changes like resetting daily student states, and finalizing hot ISBNs from *previous* period.
                checker_instance.current_state.apply_open_action(cmd_date_str)
            else: # CLOSE
                checker_instance.current_state.apply_close_action(cmd_date_str) # Mainly a marker for date progression.

            # Validate SUT's tidy moves for this OPEN/CLOSE
            if sut_output_idx >= len(sut_all_output_lines_for_cycle):
                return {"is_legal": False, "error_message": f"Format Error ({op_type} Tidy): SUT ran out of output lines before {op_type} tidy count.", "first_failing_command": command_str}
            try:
                num_moves_sut = int(sut_all_output_lines_for_cycle[sut_output_idx])
                if num_moves_sut < 0: raise ValueError("Negative move count")
            except ValueError:
                return {"is_legal": False, "error_message": f"Format Error ({op_type} Tidy Count): SUT {op_type} tidy count ('{sut_all_output_lines_for_cycle[sut_output_idx]}') is not a non-negative int.", "first_failing_command": command_str}

            if sut_output_idx + 1 + num_moves_sut > len(sut_all_output_lines_for_cycle):
                return {"is_legal": False, "error_message": f"Format Error ({op_type} Tidy Line Count): SUT declared {num_moves_sut} moves, but not enough lines provided. Needed {1+num_moves_sut}, got {len(sut_all_output_lines_for_cycle) - sut_output_idx}.", "first_failing_command": command_str}

            sut_tidy_lines_for_this_phase = sut_all_output_lines_for_cycle[sut_output_idx : sut_output_idx + 1 + num_moves_sut]
            sut_output_idx += (1 + num_moves_sut)
            validation_result = checker_instance.validate_sut_tidy_moves(cmd_date_str, sut_tidy_lines_for_this_phase, is_opening_tidy=is_opening_tidy_local)
        
        else: # User operation command
            if len(parts) < 4: # [date] student_id action target
                 validation_result = {"is_legal": False, "error_message": f"Format Error (User Op): Command '{command_str}' too short."}
            else:
                cmd_student_id, cmd_action, cmd_target = parts[1], parts[2], parts[3]
                
                if cmd_action == "queried":
                    if sut_output_idx >= len(sut_all_output_lines_for_cycle):
                        return {"is_legal": False, "error_message": f"Format Error (Query): SUT ran out of output for query '{command_str}'.", "first_failing_command": command_str}
                    
                    sut_query_header_line = sut_all_output_lines_for_cycle[sut_output_idx]
                    parsed_q_header = parse_sut_query_header_line(sut_query_header_line)
                    if not parsed_q_header:
                        return {"is_legal": False, "error_message": f"Format Error (Query Header): Malformed SUT header '{sut_query_header_line}' for query '{command_str}'.", "first_failing_command": command_str}
                    
                    _, _, num_trace_lines_sut_declared = parsed_q_header
                    
                    if sut_output_idx + 1 + num_trace_lines_sut_declared > len(sut_all_output_lines_for_cycle):
                        return {"is_legal": False, "error_message": f"Format Error (Query Line Count): SUT declared {num_trace_lines_sut_declared} traces, but not enough lines provided for query '{command_str}'.", "first_failing_command": command_str}
                    
                    sut_lines_for_this_query = sut_all_output_lines_for_cycle[sut_output_idx : sut_output_idx + 1 + num_trace_lines_sut_declared]
                    sut_output_idx += (1 + num_trace_lines_sut_declared)
                    validation_result = checker_instance.validate_sut_query(cmd_date_str, cmd_target, sut_lines_for_this_query)
                else: 
                    # All other user ops expect a single line of output
                    if sut_output_idx >= len(sut_all_output_lines_for_cycle):
                        return {"is_legal": False, "error_message": f"Format Error (User Op '{cmd_action}'): SUT ran out of output for command '{command_str}'.", "first_failing_command": command_str}
                    
                    sut_op_line = sut_all_output_lines_for_cycle[sut_output_idx]; sut_output_idx += 1
                    
                    if cmd_action == "borrowed": validation_result = checker_instance.validate_sut_borrow(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "returned": validation_result = checker_instance.validate_sut_return(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "ordered": validation_result = checker_instance.validate_sut_order(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "picked": validation_result = checker_instance.validate_sut_pick(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "read": validation_result = checker_instance.validate_sut_read(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    elif cmd_action == "restored": validation_result = checker_instance.validate_sut_restore(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                    else: validation_result = {"is_legal": False, "error_message": f"Checker Internal Error: Unknown action '{cmd_action}' in command '{command_str}'."}
        
        if not validation_result.get("is_legal", False):
            err_msg = validation_result.get('error_message', 'Unknown validation error')
            return {"is_legal": False, "error_message": f"Validation failed for command {cmd_idx+1} ('{command_str}'): {err_msg}", "first_failing_command": command_str}

    # After all commands in the cycle are processed and validated:
    if sut_output_idx < len(sut_all_output_lines_for_cycle):
        return {"is_legal": False, "error_message": f"Format Error (Extraneous Output): SUT produced extraneous output. First extraneous line: '{sut_all_output_lines_for_cycle[sut_output_idx]}'", "first_failing_command": "End of cycle (extraneous SUT output detected)"}

    # If all checks passed, update the main_library_state with the validated state from the copy
    main_library_state.__dict__.update(current_cycle_state_copy.__dict__)
    return {"is_legal": True, "error_message": "", "first_failing_command": None}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Checker for Library System SUT output (hw14 compliant).")
    parser.add_argument("input_file", help="Path to the input command file (e.g., input.txt).")
    parser.add_argument("sut_output_file", help="Path to the SUT's output file (e.g., output.txt).")
    args = parser.parse_args()

    all_input_commands: List[str] = []
    all_sut_output_lines: List[str] = []

    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            all_input_commands = [line.strip() for line in f if line.strip()]
        with open(args.sut_output_file, 'r', encoding='utf-8') as f:
            all_sut_output_lines = [line.strip() for line in f if line.strip()]
    except FileNotFoundError as e:
        print(json.dumps({"status": "failure", "reason": f"Error reading files: {e}"}))
        sys.exit(1)
    except Exception as e: # Catch other potential IO errors
        print(json.dumps({"status": "failure", "reason": f"An unexpected error occurred while reading files: {e}"}))
        sys.exit(1)


    if not all_input_commands: # No input commands
        if all_sut_output_lines: # But SUT produced output
            print(json.dumps({"status": "failure", "reason": "Input file is empty, but SUT produced output."}))
        else: # No input, no output, considered success for an empty run
            print(json.dumps({"status": "success"})) 
        sys.exit(0)

    # --- Initialize Library State from Input ---
    # This part simulates the driver's initial book loading.
    # For standalone checker, this needs to be robust.
    main_checker_library_state = LibrarySystem()
    sut_output_idx_main = 0 # Tracks SUT output lines consumed by the main loop
    input_cmd_idx_main = 0
    current_command_str_for_error_reporting_main = "Initial book loading"

    try:
        if input_cmd_idx_main >= len(all_input_commands):
            print(json.dumps({"status": "failure", "reason": "Input file does not contain initial book count."}))
            sys.exit(1)

        num_book_types_str = all_input_commands[input_cmd_idx_main]; input_cmd_idx_main += 1
        try:
            num_book_types = int(num_book_types_str)
            if num_book_types < 0:
                 print(json.dumps({"status": "failure", "reason": "Negative number of book types in input."}))
                 sys.exit(1)
        except ValueError:
            print(json.dumps({"status": "failure", "reason": f"Invalid format for initial book count: '{num_book_types_str}'."}))
            sys.exit(1)

        if input_cmd_idx_main + num_book_types > len(all_input_commands):
            print(json.dumps({"status": "failure", "reason": "Input file too short for declared number of book types."}))
            sys.exit(1)
        
        book_init_lines = all_input_commands[input_cmd_idx_main : input_cmd_idx_main + num_book_types]
        input_cmd_idx_main += num_book_types
        main_checker_library_state.initialize_books(book_init_lines) 
    
    except ValueError as e: # Catch specific errors from initialize_books if any
        print(json.dumps({"status": "failure", "reason": f"Error during library initialization: {e}"}))
        sys.exit(1)
    except Exception as e: # Generic catch for other init errors
        # import traceback
        # tb_str = traceback.format_exc()
        print(json.dumps({"status": "failure", "reason": f"Critical error during library initialization: {e}"}))
        sys.exit(1)

    # --- Main Loop for Processing Commands (Simulates Driver Calling check_cycle) ---
    # For standalone checker, we process all commands as one "cycle" for simplicity,
    # but internally, check_cycle is designed for one open-close or part thereof.
    # The driver.py is responsible for batching commands into cycles.
    # Here, we'll treat all remaining commands as a single sequence for validation.
    
    # The check_cycle function is designed for a batch of commands typically representing
    # one OPEN -> user ops -> CLOSE sequence.
    # For standalone testing of checker.py with a full input/output log,
    # we can adapt its use or iterate command by command applying the logic.
    # For now, let's assume the provided input/output corresponds to one logical block
    # that `check_cycle` can handle (e.g., one or more full open/close days).
    
    remaining_commands_for_cycle = all_input_commands[input_cmd_idx_main:]
    
    # If there are commands after initialization, pass them to check_cycle
    if remaining_commands_for_cycle:
        cycle_validation_result = check_cycle(
            remaining_commands_for_cycle,
            all_sut_output_lines, # Pass all SUT output; check_cycle will consume as needed
            main_checker_library_state # Pass the main state object
        )

        if not cycle_validation_result.get("is_legal", False):
            reason = cycle_validation_result.get('error_message', 'Unknown validation error')
            failing_cmd_context = cycle_validation_result.get('first_failing_command', 'N/A')
            print(json.dumps({"status": "failure", 
                              "reason": f"Validation failed: {reason}",
                              "context": f"Command context: '{failing_cmd_context}'"}))
            sys.exit(1)
        else:
            # If check_cycle consumed all SUT output and commands, it's a success.
            # check_cycle itself checks for extraneous SUT output.
            print(json.dumps({"status": "success"}))
            sys.exit(0)
    elif not all_sut_output_lines: # No commands after init, and no SUT output either
        print(json.dumps({"status": "success"}))
        sys.exit(0)
    else: # No commands after init, but SUT produced some output (unexpected)
        print(json.dumps({"status": "failure", "reason": "No commands after initialization, but SUT produced output."}))
        sys.exit(1)