# -*- coding: utf-8 -*-
import sys
import math
from collections import deque
import json # Import the json library

# --- Helper Functions ---

def parse_int(s):
    try:
        return int(s)
    except ValueError:
        print(f"CHECKER WARNING: Could not parse integer '{s}'", file=sys.stderr)
        return None

def calculate_age_var(ages):
    n = len(ages)
    if n == 0:
        return 0
    mean = sum(ages) // n if n > 0 else 0
    variance_sum_sq_diff = sum((age - mean) ** 2 for age in ages)
    variance = int(variance_sum_sq_diff // n) if n > 0 else 0
    return variance

# --- Simulator Classes ---

class TagSimulator:
    def __init__(self, tag_id):
        self.id = tag_id
        self.persons = set() # Store person IDs

    def add_person(self, person_id):
        self.persons.add(person_id)

    def has_person(self, person_id):
        return person_id in self.persons

    def del_person(self, person_id):
        self.persons.discard(person_id)

    def get_size(self):
        return len(self.persons)

    def get_person_ids(self):
        return list(self.persons)

    def __eq__(self, other):
        if not isinstance(other, TagSimulator):
            return NotImplemented
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

class PersonSimulator:
    def __init__(self, person_id, name, age):
        self.id = person_id
        self.name = name
        self.age = age
        self.acquaintance = {} # maps acquaintance_id -> value
        self.tags = {} # maps tag_id -> TagSimulator object

    def is_linked(self, other_person_id):
        return other_person_id == self.id or other_person_id in self.acquaintance

    def query_value(self, other_person_id):
        if other_person_id == self.id:
            return 0
        return self.acquaintance.get(other_person_id, 0)

    def add_link(self, other_person_id, value):
        if other_person_id != self.id:
             self.acquaintance[other_person_id] = value

    def remove_link(self, other_person_id):
        if other_person_id in self.acquaintance:
            del self.acquaintance[other_person_id]

    def contains_tag(self, tag_id):
        return tag_id in self.tags

    def get_tag(self, tag_id):
        return self.tags.get(tag_id)

    def add_tag(self, tag):
        if not self.contains_tag(tag.id):
            self.tags[tag.id] = tag
            return True
        return False

    def del_tag(self, tag_id):
        if self.contains_tag(tag_id):
            del self.tags[tag_id]
            return True
        return False

    def get_acquaintance_ids_and_values(self):
        return list(self.acquaintance.items())

    def __eq__(self, other):
        if not isinstance(other, PersonSimulator):
            return NotImplemented
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __str__(self):
        return f"Person(id={self.id}, name='{self.name}', age={self.age})"


class NetworkSimulator:
    def __init__(self):
        self.persons = {} # map person_id -> PersonSimulator
        self.exception_counts = {
            "anf": {"total": 0, "ids": {}},
            "epi": {"total": 0, "ids": {}},
            "er": {"total": 0, "ids": {}},
            "eti": {"total": 0, "ids": {}},
            "pinf": {"total": 0, "ids": {}},
            "rnf": {"total": 0, "ids": {}},
            "tinf": {"total": 0, "ids": {}},
        }
        self.er_static_count = 0

    def _record_exception(self, exc_type, id1, id2=None):
        if exc_type == "er":
             self.er_static_count += 1
        elif exc_type == "rnf":
            self.exception_counts[exc_type]["total"] += 2
        else:
             self.exception_counts[exc_type]["total"] += 1

        counts_id1 = self.exception_counts[exc_type]["ids"].get(id1, 0)
        self.exception_counts[exc_type]["ids"][id1] = counts_id1 + 1

        if id2 is not None:
             counts_id2 = self.exception_counts[exc_type]["ids"].get(id2, 0)
             self.exception_counts[exc_type]["ids"][id2] = counts_id2 + 1


    def _format_exception(self, exc_type, id1, id2=None):
        fmt_id1, fmt_id2 = id1, id2
        if exc_type in ("er", "rnf") and id2 is not None and id1 > id2:
             fmt_id1, fmt_id2 = id2, id1

        id1_count = self.exception_counts[exc_type]["ids"].get(fmt_id1, 0)
        total_count = self.exception_counts[exc_type]["total"]

        if exc_type == "anf":
             return f"anf-{total_count}, {fmt_id1}-{id1_count}"
        elif exc_type == "epi":
             trigger_id = id1
             trigger_id_count = self.exception_counts[exc_type]["ids"].get(trigger_id, 0)
             return f"epi-{total_count}, {trigger_id}-{trigger_id_count}"
        elif exc_type == "er":
             id2_count = self.exception_counts[exc_type]["ids"].get(fmt_id2, 0)
             return f"er-{self.er_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "eti":
             tag_id = id1
             tag_id_count = self.exception_counts[exc_type]["ids"].get(tag_id, 0)
             return f"eti-{total_count}, {tag_id}-{tag_id_count}"
        elif exc_type == "pinf":
             return f"pinf-{total_count}, {fmt_id1}-{id1_count}"
        elif exc_type == "rnf":
            id2_count = self.exception_counts[exc_type]["ids"].get(fmt_id2, 0)
            total_print_count = total_count // 2
            return f"rnf-{total_print_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "tinf":
             tag_id = id1
             tag_id_count = self.exception_counts[exc_type]["ids"].get(tag_id, 0)
             return f"tinf-{total_count}, {tag_id}-{tag_id_count}"
        else:
             return "CHECKER_ERROR: Unknown exception type"

    def contains_person(self, person_id):
        return person_id in self.persons

    def get_person(self, person_id):
        return self.persons.get(person_id)

    def add_person(self, person_id, name, age):
        if self.contains_person(person_id):
            self._record_exception("epi", person_id)
            return self._format_exception("epi", person_id)
        else:
            new_person = PersonSimulator(person_id, name, age)
            self.persons[person_id] = new_person
            return "Ok"

    def add_relation(self, id1, id2, value):
        if not self.contains_person(id1):
            self._record_exception("pinf", id1)
            return self._format_exception("pinf", id1)
        if not self.contains_person(id2):
            self._record_exception("pinf", id2)
            return self._format_exception("pinf", id2)

        person1 = self.get_person(id1)
        person2 = self.get_person(id2)

        if person1.is_linked(id2):
            self._record_exception("er", id1, id2)
            return self._format_exception("er", id1, id2)
        else:
            if id1 != id2:
                 person1.add_link(id2, value)
                 person2.add_link(id1, value)
            return "Ok"

    def modify_relation(self, id1, id2, value):
        if not self.contains_person(id1):
            self._record_exception("pinf", id1)
            return self._format_exception("pinf", id1)
        if not self.contains_person(id2):
            self._record_exception("pinf", id2)
            return self._format_exception("pinf", id2)
        if id1 == id2:
            self._record_exception("epi", id1)
            return self._format_exception("epi", id1)

        person1 = self.get_person(id1)
        person2 = self.get_person(id2)

        if not person1.is_linked(id2):
             self._record_exception("rnf", id1, id2)
             return self._format_exception("rnf", id1, id2)
        else:
            old_value = person1.query_value(id2)
            new_value = old_value + value
            if new_value > 0:
                person1.add_link(id2, new_value)
                person2.add_link(id1, new_value)
            else:
                person1.remove_link(id2)
                person2.remove_link(id1)
                for tag in person1.tags.values():
                    if tag.has_person(id2):
                         tag.del_person(id2)
                for tag in person2.tags.values():
                     if tag.has_person(id1):
                          tag.del_person(id1)
            return "Ok"

    def query_value(self, id1, id2):
        if not self.contains_person(id1):
            self._record_exception("pinf", id1)
            return self._format_exception("pinf", id1)
        if not self.contains_person(id2):
            self._record_exception("pinf", id2)
            return self._format_exception("pinf", id2)

        person1 = self.get_person(id1)

        if id1 != id2 and not person1.is_linked(id2):
            self._record_exception("rnf", id1, id2)
            return self._format_exception("rnf", id1, id2)
        else:
            val = person1.query_value(id2)
            return str(val)

    def is_circle(self, id1, id2):
         if not self.contains_person(id1):
            self._record_exception("pinf", id1)
            return self._format_exception("pinf", id1)
         if not self.contains_person(id2):
            self._record_exception("pinf", id2)
            return self._format_exception("pinf", id2)

         if id1 == id2:
             return "true"

         queue = deque([id1])
         visited = {id1}
         while queue:
             current_id = queue.popleft()
             if current_id == id2:
                 return "true"

             current_person = self.get_person(current_id)
             for neighbor_id in current_person.acquaintance.keys():
                 if neighbor_id not in visited:
                     visited.add(neighbor_id)
                     queue.append(neighbor_id)

         return "false"

    def query_triple_sum(self):
        count = 0
        person_ids = list(self.persons.keys())
        n = len(person_ids)
        if n < 3:
             return "0"

        for i in range(n):
            person_i = self.get_person(person_ids[i])
            id_i = person_ids[i]
            for j in range(i + 1, n):
                person_j = self.get_person(person_ids[j])
                id_j = person_ids[j]
                if person_i.is_linked(id_j):
                    for k in range(j + 1, n):
                        person_k = self.get_person(person_ids[k])
                        id_k = person_ids[k]
                        if person_j.is_linked(id_k) and \
                           person_k.is_linked(id_i):
                            count += 1
        return str(count)

    def add_tag(self, person_id, tag_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id)
            return self._format_exception("pinf", person_id)

        person = self.get_person(person_id)
        if person.contains_tag(tag_id):
             self._record_exception("eti", tag_id)
             return self._format_exception("eti", tag_id)
        else:
            new_tag = TagSimulator(tag_id)
            person.add_tag(new_tag)
            return "Ok"

    def add_person_to_tag(self, person_id1, person_id2, tag_id):
        if not self.contains_person(person_id1):
            self._record_exception("pinf", person_id1)
            return self._format_exception("pinf", person_id1)
        if not self.contains_person(person_id2):
            self._record_exception("pinf", person_id2)
            return self._format_exception("pinf", person_id2)

        if person_id1 == person_id2:
             self._record_exception("epi", person_id1)
             return self._format_exception("epi", person_id1)

        person1 = self.get_person(person_id1)
        person2 = self.get_person(person_id2)

        if not person2.is_linked(person_id1):
            self._record_exception("rnf", person_id1, person_id2)
            return self._format_exception("rnf", person_id1, person_id2)

        if not person2.contains_tag(tag_id):
            self._record_exception("tinf", tag_id)
            return self._format_exception("tinf", tag_id)

        tag = person2.get_tag(tag_id)

        if tag.has_person(person_id1):
            self._record_exception("epi", person_id1)
            return self._format_exception("epi", person_id1)

        if tag.get_size() < 1000:
             tag.add_person(person_id1)
        return "Ok"

    def query_tag_age_var(self, person_id, tag_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id)
            return self._format_exception("pinf", person_id)

        person = self.get_person(person_id)
        if not person.contains_tag(tag_id):
            self._record_exception("tinf", tag_id)
            return self._format_exception("tinf", tag_id)

        tag = person.get_tag(tag_id)
        person_ids_in_tag = tag.get_person_ids()
        ages = []
        for pid in person_ids_in_tag:
            p = self.get_person(pid)
            if p:
                ages.append(p.age)
            else:
                print(f"CHECKER WARNING: Person {pid} in tag {tag_id} of person {person_id} not found in network.", file=sys.stderr)

        age_var = calculate_age_var(ages)
        return str(age_var)

    def del_person_from_tag(self, person_id1, person_id2, tag_id):
        if not self.contains_person(person_id1):
            self._record_exception("pinf", person_id1)
            return self._format_exception("pinf", person_id1)
        if not self.contains_person(person_id2):
            self._record_exception("pinf", person_id2)
            return self._format_exception("pinf", person_id2)

        person2 = self.get_person(person_id2)

        if not person2.contains_tag(tag_id):
            self._record_exception("tinf", tag_id)
            return self._format_exception("tinf", tag_id)

        tag = person2.get_tag(tag_id)

        if not tag.has_person(person_id1):
            self._record_exception("pinf", person_id1)
            return self._format_exception("pinf", person_id1)

        tag.del_person(person_id1)
        return "Ok"

    def del_tag(self, person_id, tag_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id)
            return self._format_exception("pinf", person_id)

        person = self.get_person(person_id)
        if not person.contains_tag(tag_id):
            self._record_exception("tinf", tag_id)
            return self._format_exception("tinf", tag_id)

        person.del_tag(tag_id)
        return "Ok"

    def query_best_acquaintance(self, person_id):
        # JML: requires containsPerson(id) && getPerson(id).acquaintance.length != 0;
        # JML: ensures \result == (\min int bestId; (\exists ... acquaintance[i].getId() == bestId ...);
        #                           (\forall ... value[j] <= value[i] ...)); bestId)
        # Interpretation: Find MAX value, then find MIN ID among those with MAX value.

        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id)
            return self._format_exception("pinf", person_id)

        person = self.get_person(person_id)
        acquaintances = person.get_acquaintance_ids_and_values()

        if not acquaintances:
             self._record_exception("anf", person_id)
             return self._format_exception("anf", person_id)

        # --- CORRECTED LOGIC ---
        # 1. Find the maximum value among acquaintances
        max_value = float('-inf') # Initialize with negative infinity
        for _, value in acquaintances:
            max_value = max(max_value, value) # Find the maximum value

        # 2. Find the minimum ID among those with the maximum value
        best_id = float('inf') # Initialize with positive infinity to find the minimum ID
        for acq_id, value in acquaintances:
             if value == max_value: # Check if this acquaintance has the maximum value
                 best_id = min(best_id, acq_id) # Update best_id if this ID is smaller
        # --- END CORRECTED LOGIC ---

        # Check if best_id remained infinity (shouldn't happen if acquaintances is not empty)
        if best_id == float('inf'):
             # This indicates an internal logic error or impossible state
             return "CHECKER_ERROR: Failed to find best_id"

        return str(int(best_id))


# --- Main Checker Logic ---

def run_checker(stdin_path, stdout_path):
    network = NetworkSimulator()
    result_status = "Accepted" # Assume success initially
    error_details = []         # Store error info if found

    try:
        with open(stdin_path, 'r', encoding='utf-8') as f_in: # Specify encoding
            input_lines = [line.strip() for line in f_in if line.strip()]
    except FileNotFoundError:
        result_status = "Rejected"; error_details.append({"command_number": 0, "command": None, "expected": None, "actual": None, "reason": f"Checker Error: Input file not found: {stdin_path}"}); print(json.dumps({"result": result_status, "errors": error_details}, indent=4)); sys.exit(0)
    except Exception as e:
        result_status = "Rejected"; error_details.append({"command_number": 0, "command": None, "expected": None, "actual": None, "reason": f"Checker Error: Failed to read input file {stdin_path}: {e}"}); print(json.dumps({"result": result_status, "errors": error_details}, indent=4)); sys.exit(0)

    try:
        with open(stdout_path, 'r', encoding='utf-8') as f_out: # Specify encoding
            output_lines = [line.strip() for line in f_out if line.strip()]
    except FileNotFoundError:
        result_status = "Rejected"; error_details.append({"command_number": 0, "command": None, "expected": None, "actual": None, "reason": f"Checker Error: Output file not found: {stdout_path}"}); print(json.dumps({"result": result_status, "errors": error_details}, indent=4)); sys.exit(0)
    except Exception as e:
        result_status = "Rejected"; error_details.append({"command_number": 0, "command": None, "expected": None, "actual": None, "reason": f"Checker Error: Failed to read output file {stdout_path}: {e}"}); print(json.dumps({"result": result_status, "errors": error_details}, indent=4)); sys.exit(0)


    input_idx = 0
    output_idx = 0
    command_num = 0

    while input_idx < len(input_lines):
        if result_status == "Rejected": break

        command_num += 1
        cmd_line = input_lines[input_idx]
        input_idx += 1
        parts = cmd_line.split()
        if not parts: continue
        cmd = parts[0]
        expected_output = "Checker_Error: Command not implemented"


        # --- Handle load_network specially ---
        if cmd in ("ln", "load_network", "lnl", "load_network_local"):
             load_expected_output = "Ok"
             load_actual_output = None

             if output_idx >= len(output_lines):
                 result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": load_expected_output, "actual": None, "reason": f"Missing output for {cmd}"}); break
             load_actual_output = output_lines[output_idx]
             output_idx += 1

             if len(parts) < 2:
                  result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output, "reason": f"Malformed {cmd} command"}); break

             n_str = parts[1]; n = parse_int(n_str)
             if n is None or n < 0:
                  result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output, "reason": f"Invalid count '{n_str}' in {cmd}"}); break

             source_lines = []; source_idx_offset = 0; load_file_error = False

             if cmd in ("lnl", "load_network_local"):
                  if len(parts) < 3:
                       result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output, "reason": f"Missing filename for {cmd}"}); break
                  filename = parts[2]
                  try:
                       with open(filename, 'r', encoding='utf-8') as f_load: # Specify encoding
                            source_lines = [line.strip() for line in f_load if line.strip()]
                       if len(source_lines) < n + 2:
                            result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output, "reason": f"File {filename} has insufficient data (expected {n+2} lines, got {len(source_lines)})"}); break
                  except FileNotFoundError:
                       load_file_error = True; load_expected_output = "File not found"
                  except Exception as e: # Catch other potential file errors
                        result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output, "reason": f"Error reading load file {filename}: {e}"}); break
             else: # ln command
                  if input_idx + n + 2 > len(input_lines):
                       result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output, "reason": f"Insufficient lines in stdin for {cmd} {n}"}); break
                  source_lines = input_lines; source_idx_offset = input_idx; input_idx += (n + 2)

             if load_actual_output != load_expected_output:
                  result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": load_expected_output, "actual": load_actual_output, "reason": "Output mismatch for load command"}); break
             if load_file_error: continue

             try: # Simulate the load process additions
                  ids_line = source_lines[source_idx_offset].split(); names_line = source_lines[source_idx_offset + 1].split(); ages_line = source_lines[source_idx_offset + 2].split()
                  if not (len(ids_line) == n and len(names_line) == n and len(ages_line) == n): raise ValueError("Mismatched counts in data lines")
                  ids = [parse_int(id_s) for id_s in ids_line]; names = names_line; ages = [parse_int(age_s) for age_s in ages_line]
                  if None in ids or None in ages: raise ValueError("Failed to parse IDs or Ages")
                  for i in range(n): # Add Persons
                      sim_out = network.add_person(ids[i], names[i], ages[i])
                      if sim_out != "Ok": raise RuntimeError(f"Internal Sim Error: add_person failed: {sim_out}")
                  current_data_line_idx = source_idx_offset + 3
                  for i in range(n - 1): # Add Relations
                      value_line = source_lines[current_data_line_idx].split()
                      if len(value_line) != i + 1: raise ValueError(f"Incorrect number of values on relation line {i+1}")
                      current_data_line_idx += 1
                      for j in range(i + 1):
                          value = parse_int(value_line[j])
                          if value is None or value < 0: raise ValueError(f"Invalid value '{value_line[j]}' on relation line {i+1}")
                          if value > 0:
                              sim_out = network.add_relation(ids[i + 1], ids[j], value)
                              if sim_out != "Ok": raise RuntimeError(f"Internal Sim Error: add_relation failed: {sim_out}")
             except Exception as e:
                  result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output, "reason": f"Checker error during load simulation: {type(e).__name__} {e}"}); break
             continue

        # --- Handle regular commands ---
        actual_output = None
        if output_idx >= len(output_lines):
             result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": "???", "actual": None, "reason": "Missing output"}); break
        actual_output = output_lines[output_idx]
        output_idx += 1

        try:
            if cmd in ("ap", "add_person") and len(parts) == 4:
                id_val, name, age = parse_int(parts[1]), parts[2], parse_int(parts[3])
                if id_val is None or age is None: raise ValueError("Bad arguments")
                expected_output = network.add_person(id_val, name, age)
            elif cmd in ("ar", "add_relation") and len(parts) == 4:
                id1, id2, val = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                if id1 is None or id2 is None or val is None: raise ValueError("Bad arguments")
                expected_output = network.add_relation(id1, id2, val)
            elif cmd in ("mr", "modify_relation") and len(parts) == 4:
                 id1, id2, m_val = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                 if id1 is None or id2 is None or m_val is None: raise ValueError("Bad arguments")
                 expected_output = network.modify_relation(id1, id2, m_val)
            elif cmd in ("qv", "query_value") and len(parts) == 3:
                id1, id2 = parse_int(parts[1]), parse_int(parts[2])
                if id1 is None or id2 is None: raise ValueError("Bad arguments")
                expected_output = network.query_value(id1, id2)
            elif cmd in ("qci", "query_circle") and len(parts) == 3:
                id1, id2 = parse_int(parts[1]), parse_int(parts[2])
                if id1 is None or id2 is None: raise ValueError("Bad arguments")
                expected_output = network.is_circle(id1, id2)
            elif cmd in ("qts", "query_triple_sum") and len(parts) == 1:
                expected_output = network.query_triple_sum()
            elif cmd in ("at", "add_tag") and len(parts) == 3:
                 p_id, t_id = parse_int(parts[1]), parse_int(parts[2])
                 if p_id is None or t_id is None: raise ValueError("Bad arguments")
                 expected_output = network.add_tag(p_id, t_id)
            elif cmd in ("att", "add_to_tag") and len(parts) == 4:
                 id1, id2, t_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                 if id1 is None or id2 is None or t_id is None: raise ValueError("Bad arguments")
                 expected_output = network.add_person_to_tag(id1, id2, t_id)
            elif cmd in ("qtav", "query_tag_age_var") and len(parts) == 3:
                 p_id, t_id = parse_int(parts[1]), parse_int(parts[2])
                 if p_id is None or t_id is None: raise ValueError("Bad arguments")
                 expected_output = network.query_tag_age_var(p_id, t_id)
            elif cmd in ("dft", "del_from_tag") and len(parts) == 4:
                 id1, id2, t_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                 if id1 is None or id2 is None or t_id is None: raise ValueError("Bad arguments")
                 expected_output = network.del_person_from_tag(id1, id2, t_id)
            elif cmd in ("dt", "del_tag") and len(parts) == 3:
                 p_id, t_id = parse_int(parts[1]), parse_int(parts[2])
                 if p_id is None or t_id is None: raise ValueError("Bad arguments")
                 expected_output = network.del_tag(p_id, t_id)
            elif cmd in ("qba", "query_best_acquaintance") and len(parts) == 2:
                id_val = parse_int(parts[1])
                if id_val is None: raise ValueError("Bad arguments")
                expected_output = network.query_best_acquaintance(id_val) # Using corrected logic here
            else:
                 raise ValueError(f"Unknown or malformed command: '{cmd_line}'")

        except ValueError as e:
             result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": actual_output, "reason": f"Checker Error: Invalid arguments or command: {e}"}); break
        except Exception as e:
             result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": actual_output, "reason": f"Checker Error: Unexpected error during simulation: {type(e).__name__} {e}"}); break

        # --- Compare expected vs actual ---
        if actual_output != expected_output:
             result_status = "Rejected"
             error_details.append({
                 "command_number": command_num,
                 "command": cmd_line,
                 "expected": expected_output,
                 "actual": actual_output,
                 "reason": "Output mismatch"
             })
             # print(f"Debug: Mismatch at command {command_num}") # Optional debug print
             # print(f"Debug: Acquaintances of {parts[1]} were: {network.get_person(int(parts[1])).get_acquaintance_ids_and_values() if len(parts)>1 and network.contains_person(int(parts[1])) else 'N/A'}")
             break

    # --- Final Check for Extra Output ---
    if result_status == "Accepted" and output_idx < len(output_lines):
        result_status = "Rejected"
        error_details.append({
            "command_number": command_num + 1,
            "command": None, "expected": None, "actual": output_lines[output_idx],
            "reason": "Extra output found"
        })

    # --- Output JSON Result ---
    final_result = {"result": result_status, "errors": error_details}
    print(json.dumps(final_result, indent=4, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python checker.py <stdin_file> <stdout_file>", file=sys.stderr)
        print(json.dumps({"result": "Rejected", "errors": [{"reason": "Checker usage error: Incorrect number of arguments"}]}, indent=4))
        sys.exit(1)

    stdin_file = sys.argv[1]
    stdout_file = sys.argv[2]

    run_checker(stdin_file, stdout_file)