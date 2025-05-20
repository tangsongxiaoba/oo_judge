#!/usr/bin/env python3
import sys

# --- Helper Validation Functions ---

def exit_with_error(message, line_num_for_msg):
    print(f"Error (Input Line ~{line_num_for_msg}): {message}")
    sys.exit(1)

def expect_int(val_str, arg_name, line_num, min_val=None, max_val=None):
    try:
        val = int(val_str)
        if min_val is not None and val < min_val:
            exit_with_error(f"{arg_name} '{val_str}' (value: {val}) is less than minimum {min_val}.", line_num)
        if max_val is not None and val > max_val:
            exit_with_error(f"{arg_name} '{val_str}' (value: {val}) is greater than maximum {max_val}.", line_num)
        return val
    except ValueError:
        exit_with_error(f"{arg_name} '{val_str}' is not a valid integer.", line_num)

def expect_str(val_str, arg_name, line_num, min_len=None, max_len=None):
    if not isinstance(val_str, str):
        exit_with_error(f"{arg_name} '{val_str}' is not a string.", line_num)
    if min_len is not None and len(val_str) < min_len:
        exit_with_error(f"{arg_name} (len {len(val_str)}) is shorter than minimum length {min_len}.", line_num)
    if max_len is not None and len(val_str) > max_len:
        exit_with_error(f"{arg_name} (len {len(val_str)}) is longer than maximum length {max_len}.", line_num)
    return val_str

# --- Main Validation Logic ---

def validate_file(filepath):
    try:
        with open(filepath, 'r') as f:
            all_file_lines = [(idx + 1, line.strip()) for idx, line in enumerate(f)]
            instruction_lines_with_num = [(ln_num, ln_content) for ln_num, ln_content in all_file_lines if ln_content]
    except FileNotFoundError:
        print(f"Error: File not found at '{filepath}'")
        sys.exit(1)

    if not instruction_lines_with_num:
        print("Valid input (effectively empty after stripping blank lines).")
        return

    num_instructions_limit = 3000 # Mutual test limit
    
    instruction_idx = 0
    is_first_instruction_processed = False
    seen_message_ids = set() # For checking uniqueness of message_id

    while instruction_idx < len(instruction_lines_with_num):
        current_line_num, current_line_content = instruction_lines_with_num[instruction_idx]

        if (instruction_idx + 1) > num_instructions_limit:
             exit_with_error(f"Exceeded maximum instruction count of {num_instructions_limit}.", current_line_num)

        parts = current_line_content.split()
        cmd = parts[0]
        args = parts[1:]

        if cmd == "ln":
            if is_first_instruction_processed:
                exit_with_error("'ln' (load_network) can only be the first instruction.", current_line_num)
            if len(args) != 1:
                exit_with_error(f"'ln' expects 1 argument (n), got {len(args)}.", current_line_num)
            
            n_val = expect_int(args[0], "n for ln", current_line_num, min_val=1, max_val=100) # Mutual test n limit
            
            original_ln_line_idx = -1
            for i, (ln_num, _) in enumerate(all_file_lines):
                if ln_num == current_line_num:
                    original_ln_line_idx = i
                    break
            
            data_lines_to_read = n_val + 2
            if original_ln_line_idx + 1 + data_lines_to_read > len(all_file_lines):
                exit_with_error(f"'ln {n_val}' expects {data_lines_to_read} data lines, but file ends too soon.", current_line_num)

            data_line_offset = original_ln_line_idx + 1

            # Line 1: n IDs (check for uniqueness among these IDs)
            ids_line_num, ids_line_content = all_file_lines[data_line_offset]
            ids_str = ids_line_content.strip().split()
            if len(ids_str) != n_val:
                exit_with_error(f"'ln' data: expected {n_val} IDs, got {len(ids_str)}.", ids_line_num)
            ln_person_ids = set()
            for id_str in ids_str:
                person_id = expect_int(id_str, "ID in ln data", ids_line_num)
                if person_id in ln_person_ids:
                    exit_with_error(f"Duplicate person ID '{person_id}' found in 'ln' data.", ids_line_num)
                ln_person_ids.add(person_id)
            data_line_offset += 1
            
            # Line 2: n names
            names_line_num, names_line_content = all_file_lines[data_line_offset]
            names_str = names_line_content.strip().split()
            if len(names_str) != n_val:
                exit_with_error(f"'ln' data: expected {n_val} names, got {len(names_str)}.", names_line_num)
            for name_str in names_str: expect_str(name_str, "name in ln data", names_line_num, min_len=1, max_len=100)
            data_line_offset += 1

            # Line 3: n ages
            ages_line_num, ages_line_content = all_file_lines[data_line_offset]
            ages_str = ages_line_content.strip().split()
            if len(ages_str) != n_val:
                exit_with_error(f"'ln' data: expected {n_val} ages, got {len(ages_str)}.", ages_line_num)
            for age_str in ages_str: expect_int(age_str, "age in ln data", ages_line_num, min_val=1, max_val=200)
            data_line_offset += 1

            for i in range(n_val - 1):
                rel_line_num, rel_line_content = all_file_lines[data_line_offset]
                rel_values_str = rel_line_content.strip().split()
                expected_rels_on_line = i + 1
                if len(rel_values_str) != expected_rels_on_line:
                    exit_with_error(f"'ln' data: relation line {i+1} expected {expected_rels_on_line} values, got {len(rel_values_str)}.", rel_line_num)
                for val_str in rel_values_str: expect_int(val_str, "relation value in ln data", rel_line_num, min_val=0) # value >= 0
                data_line_offset += 1
            
            last_data_line_num_original = all_file_lines[data_line_offset-1][0]
            temp_instr_idx = instruction_idx + 1
            while temp_instr_idx < len(instruction_lines_with_num) and \
                  instruction_lines_with_num[temp_instr_idx][0] <= last_data_line_num_original:
                temp_instr_idx +=1
            instruction_idx = temp_instr_idx -1

        elif cmd == "lnl":
            exit_with_error("'lnl' (load_network_local) is not allowed.", current_line_num) # Applies to both公测and互测

        elif cmd == "ap":
            if len(args) != 3: exit_with_error(f"'ap' expects 3 arguments, got {len(args)}.", current_line_num)
            expect_int(args[0], "id for ap", current_line_num)
            expect_str(args[1], "name for ap", current_line_num, min_len=1, max_len=100)
            expect_int(args[2], "age for ap", current_line_num, min_val=1, max_val=200)
        elif cmd == "ar":
            if len(args) != 3: exit_with_error(f"'ar' expects 3 arguments, got {len(args)}.", current_line_num)
            expect_int(args[0], "id1 for ar", current_line_num)
            expect_int(args[1], "id2 for ar", current_line_num)
            expect_int(args[2], "value for ar", current_line_num, min_val=1, max_val=200)
        elif cmd == "mr":
            if len(args) != 3: exit_with_error(f"'mr' expects 3 arguments, got {len(args)}.", current_line_num)
            expect_int(args[0], "id1 for mr", current_line_num)
            expect_int(args[1], "id2 for mr", current_line_num)
            expect_int(args[2], "m_val for mr", current_line_num, min_val=-200, max_val=200)

        elif cmd in ["at", "dt"]:
            if len(args) != 2: exit_with_error(f"'{cmd}' expects 2 arguments, got {len(args)}.", current_line_num)
            expect_int(args[0], f"person_id for {cmd}", current_line_num)
            expect_int(args[1], f"tag_id for {cmd}", current_line_num)
        elif cmd in ["att", "dft"]:
            if len(args) != 3: exit_with_error(f"'{cmd}' expects 3 arguments, got {len(args)}.", current_line_num)
            expect_int(args[0], f"person_id1 for {cmd}", current_line_num)
            expect_int(args[1], f"person_id2 for {cmd}", current_line_num)
            expect_int(args[2], f"tag_id for {cmd}", current_line_num)

        elif cmd == "coa":
            if len(args) != 3: exit_with_error(f"'coa' expects 3 arguments, got {len(args)}.", current_line_num)
            expect_int(args[0], "person_id for coa", current_line_num)
            expect_int(args[1], "account_id for coa", current_line_num)
            expect_str(args[2], "account_name for coa", current_line_num, min_len=1, max_len=100)
        elif cmd == "ca":
             if len(args) != 4: exit_with_error(f"'ca' expects 4 arguments, got {len(args)}.", current_line_num)
             expect_int(args[0], "person_id for ca", current_line_num)
             expect_int(args[1], "account_id for ca", current_line_num)
             expect_int(args[2], "article_id for ca", current_line_num)
             expect_str(args[3], "article_name for ca", current_line_num, min_len=1, max_len=100)
        elif cmd in ["doa", "foa"]:
            if len(args) != 2: exit_with_error(f"'{cmd}' expects 2 arguments, got {len(args)}.", current_line_num)
            expect_int(args[0], f"arg1 for {cmd}", current_line_num)
            expect_int(args[1], f"arg2 for {cmd}", current_line_num)
        elif cmd == "da":
            if len(args) != 3: exit_with_error(f"'da' expects 3 arguments, got {len(args)}.", current_line_num)
            expect_int(args[0], "person_id for da", current_line_num)
            expect_int(args[1], "account_id for da", current_line_num)
            expect_int(args[2], "article_id for da", current_line_num)

        elif cmd == "am":
            if len(args) != 5: exit_with_error(f"'am' expects 5 arguments, got {len(args)}.", current_line_num)
            msg_id = expect_int(args[0], "message_id for am", current_line_num)
            if msg_id in seen_message_ids: exit_with_error(f"Duplicate message_id {msg_id} found.", current_line_num)
            seen_message_ids.add(msg_id)
            expect_int(args[1], "social_value for am", current_line_num, min_val=-1000, max_val=1000)
            expect_int(args[2], "type for am", current_line_num, min_val=0, max_val=1)
            expect_int(args[3], "person_id1 for am", current_line_num)
            expect_int(args[4], "person_id2|tag_id for am", current_line_num)
        elif cmd == "arem":
            if len(args) != 5: exit_with_error(f"'arem' expects 5 arguments, got {len(args)}.", current_line_num)
            msg_id = expect_int(args[0], "message_id for arem", current_line_num)
            if msg_id in seen_message_ids: exit_with_error(f"Duplicate message_id {msg_id} found.", current_line_num)
            seen_message_ids.add(msg_id)
            expect_int(args[1], "money for arem", current_line_num, min_val=0, max_val=200)
            expect_int(args[2], "type for arem", current_line_num, min_val=0, max_val=1)
            expect_int(args[3], "person_id1 for arem", current_line_num)
            expect_int(args[4], "person_id2|tag_id for arem", current_line_num)
        elif cmd == "afm":
            if len(args) != 5: exit_with_error(f"'afm' expects 5 arguments, got {len(args)}.", current_line_num)
            msg_id = expect_int(args[0], "message_id for afm", current_line_num)
            if msg_id in seen_message_ids: exit_with_error(f"Duplicate message_id {msg_id} found.", current_line_num)
            seen_message_ids.add(msg_id)
            expect_int(args[1], "article_id for afm", current_line_num)
            expect_int(args[2], "type for afm", current_line_num, min_val=0, max_val=1)
            expect_int(args[3], "person_id1 for afm", current_line_num)
            expect_int(args[4], "person_id2|tag_id for afm", current_line_num)
        elif cmd == "aem":
            if len(args) != 5: exit_with_error(f"'aem' expects 5 arguments, got {len(args)}.", current_line_num)
            msg_id = expect_int(args[0], "message_id for aem", current_line_num)
            if msg_id in seen_message_ids: exit_with_error(f"Duplicate message_id {msg_id} found.", current_line_num)
            seen_message_ids.add(msg_id)
            expect_int(args[1], "emoji_id for aem", current_line_num)
            expect_int(args[2], "type for aem", current_line_num, min_val=0, max_val=1)
            expect_int(args[3], "person_id1 for aem", current_line_num)
            expect_int(args[4], "person_id2|tag_id for aem", current_line_num)
        
        elif cmd == "sm":
            if len(args) != 1: exit_with_error(f"'sm' expects 1 argument, got {len(args)}.", current_line_num)
            expect_int(args[0], "id for sm", current_line_num)
        elif cmd == "sei":
            if len(args) != 1: exit_with_error(f"'sei' expects 1 argument, got {len(args)}.", current_line_num)
            expect_int(args[0], "id for sei", current_line_num)
        elif cmd == "dce":
            if len(args) != 1: exit_with_error(f"'dce' expects 1 argument, got {len(args)}.", current_line_num)
            expect_int(args[0], "limit for dce", current_line_num) # limit is int

        elif cmd in ["qsv", "qrm", "qp", "qm", "qba", "qbc", "qra"]:
            if len(args) != 1: exit_with_error(f"'{cmd}' expects 1 argument, got {len(args)}.", current_line_num)
            expect_int(args[0], f"id for {cmd}", current_line_num)
        elif cmd in ["qv", "qci", "qsp", "qtav", "qtvs"]:
            if len(args) != 2: exit_with_error(f"'{cmd}' expects 2 arguments, got {len(args)}.", current_line_num)
            expect_int(args[0], f"arg1 for {cmd}", current_line_num)
            expect_int(args[1], f"arg2 for {cmd}", current_line_num)
        elif cmd in ["qts", "qcs"]:
            if len(args) != 0: exit_with_error(f"'{cmd}' expects 0 arguments, got {len(args)}.", current_line_num)
        
        else:
            exit_with_error(f"Unknown command '{cmd}'.", current_line_num)

        is_first_instruction_processed = True
        instruction_idx += 1

    if instruction_idx > num_instructions_limit :
         exit_with_error(f"Exceeded maximum instruction count of {num_instructions_limit} (counted {instruction_idx}).", instruction_lines_with_num[-1][0] if instruction_lines_with_num else 1)

    print("Valid input.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python_script_name.py <input_file_path>")
        sys.exit(1)
    
    input_filepath = sys.argv[1]
    validate_file(input_filepath)