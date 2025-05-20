# checker.py (Revised - Omitting strict "unconditional refusal to reserve" check)
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

# --- SUT Output Parsers (Assume these are correct from previous version) ---
def parse_sut_user_op_line(line: str) -> dict | None:
    parts = line.split()
    if len(parts) != 5: return None
    if not (parts[0].startswith("[") and parts[0].endswith("]") and
            parts[1].startswith("[") and parts[1].endswith("]")): return None
    date_str = parts[0][1:-1]
    try: date.fromisoformat(date_str)
    except ValueError: return None
    status = parts[1][1:-1]
    if status not in ["accept", "reject"]: return None
    return {"date_str": date_str, "status": status, "student_id": parts[2], "action": parts[3], "target": parts[4]}

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
        if to_loc_short != LibrarySystem.LOCATION_SHORT_MAP["appointment_office"]: return None
    elif to_loc_short == LibrarySystem.LOCATION_SHORT_MAP["appointment_office"]: return None
    return {"date_str": date_str, "book_copy_id": book_copy_id, "from_loc_short": from_loc_short, "to_loc_short": to_loc_short, "target_student_for_ao": target_student_for_ao}


class RuleChecker:
    def __init__(self, library_state: LibrarySystem):
        self.current_state = library_state

    def _get_book_copy(self, book_id: str) -> BookCopy | None:
        return self.current_state._get_book_copy(book_id)

    def _get_student(self, student_id: str) -> Student:
        return self.current_state._get_student(student_id)

    # --- validate_sut_borrow, validate_sut_return, validate_sut_order, validate_sut_pick, validate_sut_query ---
    # (Assume these are largely correct from the previous full version, focusing on their specific rules)
    # For brevity, I'll keep the structure and you can refer to the prior complete version for their detailed logic.
    # Ensure they compare SUT output date/student_id with command, and check specific operation rules.

    def validate_sut_borrow(self, cmd_date_str:str, cmd_student_id: str, cmd_isbn: str, sut_output_line: str):
        parsed_sut = parse_sut_user_op_line(sut_output_line)
        if not parsed_sut or parsed_sut["action"] != "borrowed" or \
           parsed_sut["student_id"] != cmd_student_id or parsed_sut["date_str"] != cmd_date_str :
            return {"is_legal": False, "error_message": f"Malformed or mismatched SUT output for borrow: '{sut_output_line}' for command student {cmd_student_id} on {cmd_date_str}."}
        student = self._get_student(cmd_student_id)
        book_type_to_borrow = self.current_state._get_book_type_from_id_or_isbn(cmd_isbn)
        if parsed_sut["status"] == "reject":
            if parsed_sut["target"] != cmd_isbn: return {"is_legal": False, "error_message": f"SUT reject for borrow, ISBN mismatch."}
            if book_type_to_borrow == 'A': return {"is_legal": True}
            if not self.current_state.books_on_shelf_by_isbn.get(cmd_isbn) or \
               not any(self.current_state._get_book_copy(bc_id).current_location == "bookshelf" for bc_id in self.current_state.books_on_shelf_by_isbn.get(cmd_isbn, [])):
                return {"is_legal": True}
            if book_type_to_borrow == 'B' and student.held_b_book_copy_id is not None: return {"is_legal": True}
            if book_type_to_borrow == 'C' and cmd_isbn in student.held_c_books_by_isbn: return {"is_legal": True}
            return {"is_legal": False, "error_message": "SUT rejected borrow, but checker finds it permissible."}
        elif parsed_sut["status"] == "accept":
            sut_book_copy_id = parsed_sut["target"]
            book_copy_sut_claims_to_lend = self._get_book_copy(sut_book_copy_id)
            if not book_copy_sut_claims_to_lend or book_copy_sut_claims_to_lend.isbn != cmd_isbn:
                return {"is_legal": False, "error_message": f"SUT accepted borrow with invalid/mismatched BookCopyID."}
            if book_copy_sut_claims_to_lend.type == 'A': return {"is_legal": False, "error_message": "SUT accepted borrow of A-type."}
            if book_copy_sut_claims_to_lend.current_location != "bookshelf": return {"is_legal": False, "error_message": f"SUT accepted borrow, but book not on bookshelf."}
            if book_copy_sut_claims_to_lend.type == 'B' and student.held_b_book_copy_id is not None: return {"is_legal": False, "error_message": "SUT accepted B borrow, student holds B."}
            if book_copy_sut_claims_to_lend.type == 'C' and book_copy_sut_claims_to_lend.isbn in student.held_c_books_by_isbn: return {"is_legal": False, "error_message": "SUT accepted C borrow, student holds this C ISBN."}
            self.current_state.apply_validated_borrow_action(cmd_date_str, cmd_student_id, sut_book_copy_id)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": f"SUT borrow output unknown status."}

    def validate_sut_return(self, cmd_date_str:str, cmd_student_id: str, cmd_book_copy_id: str, sut_output_line: str):
        parsed_sut = parse_sut_user_op_line(sut_output_line)
        if not parsed_sut or parsed_sut["action"] != "returned" or \
           parsed_sut["student_id"] != cmd_student_id or \
           parsed_sut["target"] != cmd_book_copy_id or parsed_sut["date_str"] != cmd_date_str:
            return {"is_legal": False, "error_message": f"Malformed/mismatched SUT output for return."}
        if parsed_sut["status"] == "reject": return {"is_legal": False, "error_message": "SUT rejected return."}
        elif parsed_sut["status"] == "accept":
            book_copy_to_return = self._get_book_copy(cmd_book_copy_id)
            if not book_copy_to_return: return {"is_legal": False, "error_message": f"SUT accepted return of non-existent book."}
            if book_copy_to_return.current_location != "user" or book_copy_to_return.current_holder_student_id != cmd_student_id:
                 return {"is_legal": False, "error_message": f"SUT accepted return, but book state inconsistent."}
            self.current_state.apply_validated_return_action(cmd_date_str, cmd_student_id, cmd_book_copy_id)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": f"SUT return output unknown status."}

    def validate_sut_order(self, cmd_date_str:str, cmd_student_id: str, cmd_isbn: str, sut_output_line: str):
        parsed_sut = parse_sut_user_op_line(sut_output_line)
        if not parsed_sut or parsed_sut["action"] != "ordered" or \
           parsed_sut["student_id"] != cmd_student_id or \
           parsed_sut["target"] != cmd_isbn or parsed_sut["date_str"] != cmd_date_str:
            return {"is_legal": False, "error_message": f"Malformed/mismatched SUT output for order."}
        student = self._get_student(cmd_student_id)
        book_type_to_order = self.current_state._get_book_type_from_id_or_isbn(cmd_isbn)
        if parsed_sut["status"] == "reject":
            if book_type_to_order == 'A': return {"is_legal": True}
            if student.pending_order_isbn is not None or student.reserved_book_copy_id_at_ao is not None: return {"is_legal": True}
            if book_type_to_order == 'B' and student.held_b_book_copy_id is not None: return {"is_legal": True}
            if book_type_to_order == 'C' and cmd_isbn in student.held_c_books_by_isbn: return {"is_legal": True}
            return {"is_legal": False, "error_message": "SUT rejected order, but checker finds it permissible."}
        elif parsed_sut["status"] == "accept":
            if book_type_to_order == 'A': return {"is_legal": False, "error_message": "SUT accepted order for A-type."}
            if student.pending_order_isbn is not None or student.reserved_book_copy_id_at_ao is not None: return {"is_legal": False, "error_message": "SUT accepted order, student has pending/reserved."}
            if book_type_to_order == 'B' and student.held_b_book_copy_id is not None: return {"is_legal": False, "error_message": "SUT accepted B order, student holds B."}
            if book_type_to_order == 'C' and cmd_isbn in student.held_c_books_by_isbn: return {"is_legal": False, "error_message": "SUT accepted C order, student holds this C ISBN."}
            self.current_state.apply_validated_order_action(cmd_student_id, cmd_isbn)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": f"SUT order output unknown status."}

    def validate_sut_pick(self, cmd_date_str:str, cmd_student_id: str, cmd_isbn_to_pick: str, sut_output_line: str):
        parsed_sut = parse_sut_user_op_line(sut_output_line)
        if not parsed_sut or parsed_sut["action"] != "picked" or \
           parsed_sut["student_id"] != cmd_student_id or parsed_sut["date_str"] != cmd_date_str:
            return {"is_legal": False, "error_message": f"Malformed/mismatched SUT output for pick."}
        student = self._get_student(cmd_student_id)
        current_date_obj = self.current_state.current_date_obj
        if not current_date_obj: return {"is_legal": False, "error_message": "Checker Error: current_date_obj not set."}
        
        if parsed_sut["status"] == "reject":
            if parsed_sut["target"] != cmd_isbn_to_pick: return {"is_legal": False, "error_message": f"SUT reject for pick, ISBN mismatch."}
            book_id_reserved = student.reserved_book_copy_id_at_ao
            if not book_id_reserved: return {"is_legal": True}
            reserved_book_copy = self._get_book_copy(book_id_reserved)
            if not reserved_book_copy or reserved_book_copy.isbn != cmd_isbn_to_pick or reserved_book_copy.current_location != "appointment_office" or reserved_book_copy.ao_reserved_for_student_id != cmd_student_id:
                return {"is_legal": True}
            if student.pickup_deadline_for_reserved_book and current_date_obj > student.pickup_deadline_for_reserved_book: return {"is_legal": True}
            book_type_at_ao = reserved_book_copy.type
            if book_type_at_ao == 'B' and student.held_b_book_copy_id is not None: return {"is_legal": True}
            if book_type_at_ao == 'C' and cmd_isbn_to_pick in student.held_c_books_by_isbn: return {"is_legal": True}
            return {"is_legal": False, "error_message": "SUT rejected pick, but checker finds it permissible."}
        elif parsed_sut["status"] == "accept":
            sut_picked_book_copy_id = parsed_sut["target"]
            if student.reserved_book_copy_id_at_ao != sut_picked_book_copy_id: return {"is_legal": False, "error_message": f"SUT accepted pick, but student reservation mismatch."}
            book_to_pick = self._get_book_copy(sut_picked_book_copy_id)
            if not book_to_pick or book_to_pick.isbn != cmd_isbn_to_pick: return {"is_legal": False, "error_message": f"SUT accepted pick, but book's actual ISBN mismatch."}
            if book_to_pick.current_location != "appointment_office" or book_to_pick.ao_reserved_for_student_id != cmd_student_id: return {"is_legal": False, "error_message": "SUT accepted pick, book state inconsistent."}
            if student.pickup_deadline_for_reserved_book and current_date_obj > student.pickup_deadline_for_reserved_book: return {"is_legal": False, "error_message": "SUT accepted pick of expired reservation."}
            book_type_picked = book_to_pick.type
            if book_type_picked == 'B' and student.held_b_book_copy_id is not None: return {"is_legal": False, "error_message": "SUT accepted B pick, student holds B."}
            if book_type_picked == 'C' and cmd_isbn_to_pick in student.held_c_books_by_isbn: return {"is_legal": False, "error_message": "SUT accepted C pick, student holds this C ISBN."}
            self.current_state.apply_validated_pick_action(cmd_date_str, cmd_student_id, sut_picked_book_copy_id)
            return {"is_legal": True}
        return {"is_legal": False, "error_message": f"SUT pick output unknown status."}

    def validate_sut_query(self, cmd_date_str: str, cmd_book_copy_id_queried: str, sut_output_lines_for_query: list[str]):
        if not sut_output_lines_for_query: return {"is_legal": False, "error_message": "SUT no output for query."}
        parsed_header = parse_sut_query_header_line(sut_output_lines_for_query[0])
        if not parsed_header: return {"is_legal": False, "error_message": f"Malformed query header."}
        sut_date_str, sut_book_id_header, sut_trace_count = parsed_header
        if sut_date_str != cmd_date_str or sut_book_id_header != cmd_book_copy_id_queried: return {"is_legal": False, "error_message": f"Query header mismatch."}
        if len(sut_output_lines_for_query) != 1 + sut_trace_count: return {"is_legal": False, "error_message": f"Query line count mismatch."}
        expected_trace_entries = self.current_state.get_book_copy_details_for_trace(cmd_book_copy_id_queried)
        if expected_trace_entries is None:
            if sut_trace_count != 0: return {"is_legal": False, "error_message": f"Queried book not in state, but SUT trace count > 0."}
            return {"is_legal": True}
        if sut_trace_count != len(expected_trace_entries): return {"is_legal": False, "error_message": f"Query trace count mismatch with expected."}
        for i in range(sut_trace_count):
            parsed_detail = parse_sut_query_trace_detail_line(sut_output_lines_for_query[i+1])
            if not parsed_detail: return {"is_legal": False, "error_message": f"Malformed query trace detail line."}
            sut_seq, sut_detail_date, sut_from, sut_to = parsed_detail
            expected_seq, (expected_detail_date, expected_from, expected_to) = i + 1, expected_trace_entries[i]
            if not (sut_seq == expected_seq and sut_detail_date == expected_detail_date and sut_from == expected_from and sut_to == expected_to):
                return {"is_legal": False, "error_message": f"Query trace detail mismatch at line {i+1}."}
        return {"is_legal": True}
    
    def validate_sut_tidy_moves(self, cmd_date_str:str, sut_move_output_lines: list[str], is_opening_tidy: bool):
        if not sut_move_output_lines:
            return {"is_legal": False, "error_message": "SUT produced no output for tidying phase." }
        try:
            num_sut_moves_declared = int(sut_move_output_lines[0])
            if num_sut_moves_declared < 0: raise ValueError()
        except ValueError:
            return {"is_legal": False, "error_message": f"Tidying move count not valid int: '{sut_move_output_lines[0]}'"}

        if len(sut_move_output_lines) != 1 + num_sut_moves_declared:
            return {"is_legal": False, "error_message": f"Tidying output line count mismatch."}

        # MODIFICATION: The "unconditional refusal" check logic is removed/commented out.
        # # For "不允许无条件拒绝为预约预留书籍"
        # fulfillable_orders_before_sut_moves = {} 
        # # ... (logic to populate fulfillable_orders_before_sut_moves) ...
        # sut_fulfilled_orders_this_tidy = set()

        for i in range(num_sut_moves_declared):
            move_line = sut_move_output_lines[i+1]
            parsed_move = parse_sut_tidy_move_line(move_line)
            if not parsed_move:
                return {"is_legal": False, "error_message": f"Malformed SUT tidy move line: '{move_line}'."}
            
            if parsed_move["date_str"] != cmd_date_str:
                 return {"is_legal": False, "error_message": f"SUT tidy move line date mismatch."}

            book_copy_to_move = self._get_book_copy(parsed_move["book_copy_id"])
            if not book_copy_to_move:
                return {"is_legal": False, "error_message": f"SUT tidy move: non-existent book: {parsed_move['book_copy_id']}."}

            from_loc_full = LibrarySystem.REVERSE_LOCATION_SHORT_MAP.get(parsed_move["from_loc_short"])
            to_loc_full = LibrarySystem.REVERSE_LOCATION_SHORT_MAP.get(parsed_move["to_loc_short"])

            if from_loc_full == to_loc_full:
                return {"is_legal": False, "error_message": f"SUT tidy move same source/destination."}
            
            if book_copy_to_move.current_location != from_loc_full:
                return {"is_legal": False, "error_message": f"SUT tidy move from '{from_loc_full}', but book is at '{book_copy_to_move.current_location}'."}

            if from_loc_full == "appointment_office" and book_copy_to_move.ao_reserved_for_student_id:
                if self.current_state.current_date_obj and book_copy_to_move.ao_pickup_deadline and \
                   self.current_state.current_date_obj <= book_copy_to_move.ao_pickup_deadline:
                    return {"is_legal": False, "error_message": f"SUT moved unexpired reserved book {book_copy_to_move.id} from AO."}
                else:
                    self.current_state.clear_expired_ao_reservation_for_book(book_copy_to_move.id)
            
            if to_loc_full == "appointment_office":
                target_student_id_for_ao = parsed_move["target_student_for_ao"]
                student_for_ao = self._get_student(target_student_id_for_ao)
                if student_for_ao.pending_order_isbn != book_copy_to_move.isbn:
                    return {"is_legal": False, "error_message": f"SUT moved {book_copy_to_move.id} to AO for {target_student_id_for_ao}, but student pending order mismatch."}
                
                reservation_effective_date = self.current_state.current_date_obj
                if not is_opening_tidy: reservation_effective_date += timedelta(days=1)
                expected_pickup_deadline = reservation_effective_date + timedelta(days=4)
                
                self.current_state._apply_book_movement(
                    book_copy_to_move.id, from_loc_full, to_loc_full, cmd_date_str,
                    ao_reservation_student_id=target_student_id_for_ao,
                    ao_pickup_deadline=expected_pickup_deadline
                )
                self.current_state.apply_book_reservation_at_ao(
                    book_copy_to_move.id, target_student_id_for_ao, expected_pickup_deadline, is_opening_tidy
                )
                # sut_fulfilled_orders_this_tidy.add(target_student_id_for_ao) # Related to removed check
            else:
                self.current_state._apply_book_movement(
                    book_copy_to_move.id, from_loc_full, to_loc_full, cmd_date_str
                )
        
        # --- Global state checks after all SUT moves ---
        if is_opening_tidy:
            for book_id_check, book_obj_check in self.current_state.all_book_copies.items():
                if book_obj_check.current_location == "borrow_return_office":
                    return {"is_legal": False, "error_message": f"After OPEN tidy, book {book_id_check} in BRO."}
        
        if is_opening_tidy: # Also check at end of OPEN tidy for overdue books at AO
             for book_obj_check in self.current_state.all_book_copies.values():
                if book_obj_check.current_location == "appointment_office" and \
                   book_obj_check.ao_reserved_for_student_id and \
                   book_obj_check.ao_pickup_deadline and \
                   self.current_state.current_date_obj > book_obj_check.ao_pickup_deadline:
                    return {"is_legal": False, "error_message": f"After OPEN tidy, overdue book {book_obj_check.id} at AO."}

        # MODIFICATION: "Unconditional refusal" check removed
        # for student_id_fulfillable, isbn_fulfillable in fulfillable_orders_before_sut_moves.items():
        #     if student_id_fulfillable not in sut_fulfilled_orders_this_tidy:
        #          # ... (previous logic for this check, now omitted) ...
        #          pass # Not checking this rule strictly anymore

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
        
        validation_result = {"is_legal": False, "error_message": "Checker Error: Command not processed."}

        if parts[1] == "OPEN":
            checker_instance.current_state.apply_open_action(cmd_date_str) 
            if sut_output_idx >= len(sut_all_output_lines_for_cycle): return {"is_legal": False, "error_message": "SUT OOM for OPEN tidy count.", "first_failing_command": command_str}
            try:
                num_moves_sut = int(sut_all_output_lines_for_cycle[sut_output_idx])
                if num_moves_sut < 0: raise ValueError()
            except ValueError: return {"is_legal": False, "error_message": f"SUT OPEN tidy count not valid.", "first_failing_command": command_str}
            if sut_output_idx + 1 + num_moves_sut > len(sut_all_output_lines_for_cycle): return {"is_legal": False, "error_message": "SUT insufficient lines for OPEN tidy.", "first_failing_command": command_str}
            sut_tidy_lines = sut_all_output_lines_for_cycle[sut_output_idx : sut_output_idx + 1 + num_moves_sut]
            sut_output_idx += (1 + num_moves_sut)
            validation_result = checker_instance.validate_sut_tidy_moves(cmd_date_str, sut_tidy_lines, is_opening_tidy=True)
        elif parts[1] == "CLOSE":
            checker_instance.current_state.apply_close_action(cmd_date_str) 
            if sut_output_idx >= len(sut_all_output_lines_for_cycle): return {"is_legal": False, "error_message": "SUT OOM for CLOSE tidy count.", "first_failing_command": command_str}
            try:
                num_moves_sut = int(sut_all_output_lines_for_cycle[sut_output_idx])
                if num_moves_sut < 0: raise ValueError()
            except ValueError: return {"is_legal": False, "error_message": f"SUT CLOSE tidy count not valid.", "first_failing_command": command_str}
            if sut_output_idx + 1 + num_moves_sut > len(sut_all_output_lines_for_cycle): return {"is_legal": False, "error_message": "SUT insufficient lines for CLOSE tidy.", "first_failing_command": command_str}
            sut_tidy_lines = sut_all_output_lines_for_cycle[sut_output_idx : sut_output_idx + 1 + num_moves_sut]
            sut_output_idx += (1 + num_moves_sut)
            validation_result = checker_instance.validate_sut_tidy_moves(cmd_date_str, sut_tidy_lines, is_opening_tidy=False)
        else: # User operation
            cmd_student_id, cmd_action, cmd_target = parts[1], parts[2], parts[3]
            if cmd_action == "queried":
                if sut_output_idx >= len(sut_all_output_lines_for_cycle): return {"is_legal": False, "error_message": "SUT OOM for query header.", "first_failing_command": command_str}
                parsed_q_header = parse_sut_query_header_line(sut_all_output_lines_for_cycle[sut_output_idx])
                if not parsed_q_header: return {"is_legal": False, "error_message": f"SUT malformed query header.", "first_failing_command": command_str}
                _, _, num_trace_lines_sut = parsed_q_header
                if sut_output_idx + 1 + num_trace_lines_sut > len(sut_all_output_lines_for_cycle): return {"is_legal": False, "error_message": "SUT insufficient lines for query trace.", "first_failing_command": command_str}
                sut_lines_for_query = sut_all_output_lines_for_cycle[sut_output_idx : sut_output_idx + 1 + num_trace_lines_sut]
                sut_output_idx += (1 + num_trace_lines_sut)
                validation_result = checker_instance.validate_sut_query(cmd_date_str, cmd_target, sut_lines_for_query) # cmd_target is BookCopyID for query
            else:
                if sut_output_idx >= len(sut_all_output_lines_for_cycle): return {"is_legal": False, "error_message": f"SUT OOM for user op {cmd_action}.", "first_failing_command": command_str}
                sut_op_line = sut_all_output_lines_for_cycle[sut_output_idx]; sut_output_idx += 1
                if cmd_action == "borrowed": validation_result = checker_instance.validate_sut_borrow(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                elif cmd_action == "returned": validation_result = checker_instance.validate_sut_return(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                elif cmd_action == "ordered": validation_result = checker_instance.validate_sut_order(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
                elif cmd_action == "picked": validation_result = checker_instance.validate_sut_pick(cmd_date_str, cmd_student_id, cmd_target, sut_op_line)
        
        if not validation_result.get("is_legal", False):
            return {"is_legal": False, "error_message": f"Validation failed for command {cmd_idx+1} ('{command_str}'): {validation_result.get('error_message', 'Unknown')}", "first_failing_command": command_str}

    if sut_output_idx < len(sut_all_output_lines_for_cycle):
        return {"is_legal": False, "error_message": f"SUT extraneous output. First: '{sut_all_output_lines_for_cycle[sut_output_idx]}'", "first_failing_command": "End of cycle"}

    main_library_state.__dict__.update(current_cycle_state_copy.__dict__)
    return {"is_legal": True, "error_message": "", "first_failing_command": None}