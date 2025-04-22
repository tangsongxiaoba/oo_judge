# -*- coding: utf-8 -*-
import sys
import math
from collections import deque
import json

# --- 并查集 (DSU) 类 ---
# 注意：这个标准 DSU 不支持删除操作，因此在本次优化中 *不* 直接用于 is_circle
# 仅作为未来可能扩展或用于其他场景的参考
# class DSU:
#     def __init__(self, n):
#         self.parent = list(range(n + 1)) # +1 if IDs start from 1 or handle 0
#         self.num_sets = n
#         # Optional: for union by rank/size
#         # self.size = [1] * (n + 1)
#
#     def find(self, i):
#         if self.parent[i] == i:
#             return i
#         # Path compression
#         self.parent[i] = self.find(self.parent[i])
#         return self.parent[i]
#
#     def union(self, i, j):
#         root_i = self.find(i)
#         root_j = self.find(j)
#         if root_i != root_j:
#             # Optional: Union by size/rank heuristic
#             # if self.size[root_i] < self.size[root_j]:
#             #     root_i, root_j = root_j, root_i
#             self.parent[root_j] = root_i
#             # self.size[root_i] += self.size[root_j]
#             self.num_sets -= 1
#             return True # Union performed
#         return False # Already in the same set


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

# --- Simulator Classes (with minor changes for efficiency) ---

class TagSimulator:
    def __init__(self, tag_id):
        self.id = tag_id
        self.persons = set() # Set for O(1) add/remove/check

    def add_person(self, person_id):
        self.persons.add(person_id)

    def has_person(self, person_id):
        return person_id in self.persons

    def del_person(self, person_id):
        self.persons.discard(person_id)

    def get_size(self):
        return len(self.persons)

    def get_person_ids(self):
        # Returning a list might be required by users, but internal checks use the set
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
        # O(1) average time complexity for dict lookup
        return other_person_id == self.id or other_person_id in self.acquaintance

    def query_value(self, other_person_id):
        if other_person_id == self.id:
            return 0
        # O(1) average time complexity for dict get
        return self.acquaintance.get(other_person_id, 0)

    def add_link(self, other_person_id, value):
        if other_person_id != self.id:
             # O(1) average time complexity for dict set
             self.acquaintance[other_person_id] = value

    def remove_link(self, other_person_id):
        # O(1) average time complexity for dict pop
        self.acquaintance.pop(other_person_id, None) # Use pop with default

    def contains_tag(self, tag_id):
        # O(1) average time complexity for dict lookup
        return tag_id in self.tags

    def get_tag(self, tag_id):
        # O(1) average time complexity for dict get
        return self.tags.get(tag_id)

    def add_tag(self, tag):
        if not self.contains_tag(tag.id):
            # O(1) average time complexity for dict set
            self.tags[tag.id] = tag
            return True
        return False

    def del_tag(self, tag_id):
         # O(1) average time complexity for dict pop
        return self.tags.pop(tag_id, None) is not None

    def get_acquaintance_ids_and_values(self):
        # O(degree) to create the list
        return list(self.acquaintance.items())

    def get_neighbor_ids(self):
        # O(degree) to create the set view/copy keys
        return set(self.acquaintance.keys()) # Return a set for efficient intersection

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
        self.persons = {} # map person_id -> PersonSimulator object O(1) lookup
        self.exception_counts = {
            "anf": {"total": 0, "ids": {}}, "epi": {"total": 0, "ids": {}},
            "er": {"total": 0, "ids": {}}, "eti": {"total": 0, "ids": {}},
            "pinf": {"total": 0, "ids": {}}, "rnf": {"total": 0, "ids": {}},
            "tinf": {"total": 0, "ids": {}},
        }
        self.er_static_count = 0
        # Optimization: Store triple sum count incrementally
        self.triple_sum_count = 0

    # _record_exception and _format_exception remain the same

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

        if exc_type == "anf": return f"anf-{total_count}, {fmt_id1}-{id1_count}"
        elif exc_type == "epi":
             trigger_id = id1; trigger_id_count = self.exception_counts[exc_type]["ids"].get(trigger_id, 0)
             return f"epi-{total_count}, {trigger_id}-{trigger_id_count}"
        elif exc_type == "er":
             id2_count = self.exception_counts[exc_type]["ids"].get(fmt_id2, 0)
             return f"er-{self.er_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "eti":
             tag_id = id1; tag_id_count = self.exception_counts[exc_type]["ids"].get(tag_id, 0)
             return f"eti-{total_count}, {tag_id}-{tag_id_count}"
        elif exc_type == "pinf": return f"pinf-{total_count}, {fmt_id1}-{id1_count}"
        elif exc_type == "rnf":
            id2_count = self.exception_counts[exc_type]["ids"].get(fmt_id2, 0); total_print_count = total_count // 2
            return f"rnf-{total_print_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "tinf":
             tag_id = id1; tag_id_count = self.exception_counts[exc_type]["ids"].get(tag_id, 0)
             return f"tinf-{total_count}, {tag_id}-{tag_id_count}"
        else: return "CHECKER_ERROR: Unknown exception type"

    def contains_person(self, person_id):
        # O(1) average dict lookup
        return person_id in self.persons

    def get_person(self, person_id):
        # O(1) average dict get
        return self.persons.get(person_id)

    # --- Command Simulation Methods ---

    def add_person(self, person_id, name, age):
        # Primarily O(1) operations
        if self.contains_person(person_id):
            self._record_exception("epi", person_id)
            return self._format_exception("epi", person_id)
        else:
            new_person = PersonSimulator(person_id, name, age)
            self.persons[person_id] = new_person
            return "Ok"

    def add_relation(self, id1, id2, value):
        # O(1) lookups + O(min(deg1, deg2)) for triple sum update
        if not self.contains_person(id1):
            self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
        if not self.contains_person(id2):
            self._record_exception("pinf", id2); return self._format_exception("pinf", id2)

        person1 = self.get_person(id1)
        person2 = self.get_person(id2)

        if person1.is_linked(id2):
            self._record_exception("er", id1, id2); return self._format_exception("er", id1, id2)
        else:
            if id1 != id2:
                # --- Optimization: Update triple sum count ---
                neighbors1 = person1.get_neighbor_ids()
                neighbors2 = person2.get_neighbor_ids()
                common_neighbors = neighbors1.intersection(neighbors2)
                self.triple_sum_count += len(common_neighbors)
                # --- End Optimization ---

                person1.add_link(id2, value)
                person2.add_link(id1, value)
            return "Ok"

    def modify_relation(self, id1, id2, value):
        # O(1) lookups. If removing, O(min(deg1, deg2)) for triple sum update + O(tag_size) loops.
        if not self.contains_person(id1):
            self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
        if not self.contains_person(id2):
            self._record_exception("pinf", id2); return self._format_exception("pinf", id2)
        if id1 == id2:
            self._record_exception("epi", id1); return self._format_exception("epi", id1)

        person1 = self.get_person(id1)
        person2 = self.get_person(id2)

        if not person1.is_linked(id2):
             self._record_exception("rnf", id1, id2); return self._format_exception("rnf", id1, id2)
        else:
            old_value = person1.query_value(id2)
            new_value = old_value + value
            if new_value > 0:
                # Only update value, no change in structure or triple count
                person1.add_link(id2, new_value)
                person2.add_link(id1, new_value)
            else:
                # --- Optimization: Update triple sum count BEFORE removing link ---
                neighbors1 = person1.get_neighbor_ids()
                neighbors2 = person2.get_neighbor_ids()
                common_neighbors = neighbors1.intersection(neighbors2)
                self.triple_sum_count -= len(common_neighbors)
                # --- End Optimization ---

                # Remove relation
                person1.remove_link(id2)
                person2.remove_link(id1)

                # Remove from tags (This part's efficiency depends on number of tags)
                # It iterates over tags of person1/2, checks if other person is present.
                # If tag.persons is a set, has_person is O(1), del_person is O(1).
                # Overall O(num_tags1 + num_tags2) in the worst case. Usually acceptable.
                for tag in person1.tags.values():
                    tag.del_person(id2) # discard is O(1)
                for tag in person2.tags.values():
                    tag.del_person(id1) # discard is O(1)
            return "Ok"


    def query_value(self, id1, id2):
        # O(1) lookups
        if not self.contains_person(id1):
            self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
        if not self.contains_person(id2):
            self._record_exception("pinf", id2); return self._format_exception("pinf", id2)

        person1 = self.get_person(id1)

        if id1 != id2 and not person1.is_linked(id2):
            self._record_exception("rnf", id1, id2); return self._format_exception("rnf", id1, id2)
        else:
            val = person1.query_value(id2)
            return str(val)

    def is_circle(self, id1, id2):
         # Kept BFS: O(N + E) in worst case for graph traversal
         # E is number of relations (edges)
         if not self.contains_person(id1):
            self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
         if not self.contains_person(id2):
            self._record_exception("pinf", id2); return self._format_exception("pinf", id2)

         if id1 == id2: return "true"

         # BFS Implementation
         queue = deque([id1])
         visited = {id1}
         while queue:
             current_id = queue.popleft()
             if current_id == id2:
                 return "true"

             current_person = self.get_person(current_id)
             if current_person: # Check if person exists (safety)
                 # Iterate through neighbor IDs only
                 for neighbor_id in current_person.acquaintance.keys(): # O(degree)
                     if neighbor_id not in visited:
                         visited.add(neighbor_id)
                         queue.append(neighbor_id)
         return "false"

    def query_triple_sum(self):
        # O(1) - Return the pre-calculated count
        return str(self.triple_sum_count)

    def add_tag(self, person_id, tag_id):
        # O(1) lookups/adds
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)

        person = self.get_person(person_id)
        if person.contains_tag(tag_id):
             self._record_exception("eti", tag_id); return self._format_exception("eti", tag_id)
        else:
            new_tag = TagSimulator(tag_id)
            person.add_tag(new_tag)
            return "Ok"

    def add_person_to_tag(self, person_id1, person_id2, tag_id):
        # O(1) complexity for most operations (lookups, set adds/checks)
        if not self.contains_person(person_id1):
            self._record_exception("pinf", person_id1); return self._format_exception("pinf", person_id1)
        if not self.contains_person(person_id2):
            self._record_exception("pinf", person_id2); return self._format_exception("pinf", person_id2)
        if person_id1 == person_id2:
             self._record_exception("epi", person_id1); return self._format_exception("epi", person_id1)

        person1 = self.get_person(person_id1)
        person2 = self.get_person(person_id2)

        if not person2.is_linked(person_id1):
            self._record_exception("rnf", person_id1, person_id2); return self._format_exception("rnf", person_id1, person_id2)
        if not person2.contains_tag(tag_id):
            self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)

        tag = person2.get_tag(tag_id)

        if tag.has_person(person_id1): # O(1) check in set
            self._record_exception("epi", person_id1); return self._format_exception("epi", person_id1)

        # Size check O(1), add O(1)
        if tag.get_size() < 1000:
             tag.add_person(person_id1)
        return "Ok"

    def query_tag_age_var(self, person_id, tag_id):
        # O(1) lookups + O(TagSize) to get ages + O(TagSize) for variance calc
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        if not person.contains_tag(tag_id):
            self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)

        tag = person.get_tag(tag_id)
        person_ids_in_tag = tag.get_person_ids() # O(TagSize) to create list copy
        ages = []
        for pid in person_ids_in_tag: # O(TagSize) loop
            p = self.get_person(pid) # O(1) lookup
            if p: ages.append(p.age)
            else: print(f"CHECKER WARNING: Person {pid} in tag {tag_id} not found.", file=sys.stderr)

        age_var = calculate_age_var(ages) # O(TagSize) calculation
        return str(age_var)

    def del_person_from_tag(self, person_id1, person_id2, tag_id):
        # O(1) complexity for lookups and set removal
        if not self.contains_person(person_id1):
            self._record_exception("pinf", person_id1); return self._format_exception("pinf", person_id1)
        if not self.contains_person(person_id2):
            self._record_exception("pinf", person_id2); return self._format_exception("pinf", person_id2)

        person2 = self.get_person(person_id2)
        if not person2.contains_tag(tag_id):
            self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)

        tag = person2.get_tag(tag_id)
        if not tag.has_person(person_id1): # O(1) check
            self._record_exception("pinf", person_id1); return self._format_exception("pinf", person_id1)

        tag.del_person(person_id1) # O(1) discard
        return "Ok"

    def del_tag(self, person_id, tag_id):
        # O(1) lookup and delete
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        if not person.contains_tag(tag_id):
            self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)

        person.del_tag(tag_id) # O(1) pop
        return "Ok"

    def query_best_acquaintance(self, person_id):
        # O(degree) to iterate through acquaintances
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)

        person = self.get_person(person_id)
        acquaintances = person.get_acquaintance_ids_and_values() # O(degree)

        if not acquaintances:
             self._record_exception("anf", person_id); return self._format_exception("anf", person_id)

        max_value = float('-inf')
        for _, value in acquaintances: # O(degree)
            max_value = max(max_value, value)

        best_id = float('inf')
        for acq_id, value in acquaintances: # O(degree)
             if value == max_value:
                 best_id = min(best_id, acq_id)

        if best_id == float('inf'): return "CHECKER_ERROR: Failed to find best_id"
        return str(int(best_id))


# --- Main Checker Logic (largely unchanged, relies on faster NetworkSimulator) ---

def run_checker(stdin_path, stdout_path):
    network = NetworkSimulator()
    result_status = "Accepted"
    error_details = []

    try:
        with open(stdin_path, 'r', encoding='utf-8') as f_in:
            input_lines = [line.strip() for line in f_in if line.strip()]
    except FileNotFoundError:
        result_status = "Rejected"; error_details.append({"reason": f"Checker Error: Input file not found: {stdin_path}"}); print(json.dumps({"result": result_status, "errors": error_details}, indent=4)); sys.exit(0)
    except Exception as e:
        result_status = "Rejected"; error_details.append({"reason": f"Checker Error: Failed to read input file {stdin_path}: {e}"}); print(json.dumps({"result": result_status, "errors": error_details}, indent=4)); sys.exit(0)

    try:
        with open(stdout_path, 'r', encoding='utf-8') as f_out:
            output_lines = [line.strip() for line in f_out if line.strip()]
    except FileNotFoundError:
        result_status = "Rejected"; error_details.append({"reason": f"Checker Error: Output file not found: {stdout_path}"}); print(json.dumps({"result": result_status, "errors": error_details}, indent=4)); sys.exit(0)
    except Exception as e:
        result_status = "Rejected"; error_details.append({"reason": f"Checker Error: Failed to read output file {stdout_path}: {e}"}); print(json.dumps({"result": result_status, "errors": error_details}, indent=4)); sys.exit(0)


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
        expected_output = "Checker_Error: Command not implemented" # Default placeholder

        # --- Handle load_network specially (Efficiency relies on base add_person/add_relation) ---
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
                       with open(filename, 'r', encoding='utf-8') as f_load:
                            source_lines = [line.strip() for line in f_load if line.strip()]
                       if len(source_lines) < n + 3: # Need n+3 lines: ids, names, ages, n relation lines
                            result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output, "reason": f"File {filename} insufficient data (expected {n+3} lines, got {len(source_lines)})"}); break
                  except FileNotFoundError: load_file_error = True; load_expected_output = "File not found"
                  except Exception as e: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Error reading load file {filename}: {e}"}); break
             else: # ln
                  # Need n+3 lines from stdin: ids, names, ages, n relation lines
                  required_lines = n + 3
                  if input_idx + required_lines -1 > len(input_lines): # -1 because cmd_line already read
                      result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Insufficient lines in stdin for {cmd} {n} (expected {required_lines})"}); break
                  source_lines = input_lines; source_idx_offset = input_idx; input_idx += required_lines

             if load_actual_output != load_expected_output:
                  result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": load_expected_output, "actual": load_actual_output, "reason": "Output mismatch for load command"}); break
             if load_file_error: continue

             # Simulate load - This now benefits from faster add_relation's triple sum update
             try:
                  ids_line = source_lines[source_idx_offset].split(); names_line = source_lines[source_idx_offset + 1].split(); ages_line = source_lines[source_idx_offset + 2].split()
                  if not (len(ids_line) == n and len(names_line) == n and len(ages_line) == n): raise ValueError("Mismatched counts")
                  ids = [parse_int(id_s) for id_s in ids_line]; names = names_line; ages = [parse_int(age_s) for age_s in ages_line]
                  if None in ids or None in ages: raise ValueError("Parse error IDs/Ages")
                  for i in range(n): network.add_person(ids[i], names[i], ages[i]) # Ignore "Ok" output

                  current_data_line_idx = source_idx_offset + 3
                  # Spec mistake: The relation lines should be n, not n-1 for standard format
                  # Assuming the format is: ids \n names \n ages \n rel_line_for_id[0] \n rel_line_for_id[1] ... id[n-1]
                  # The K-th line (0-indexed) after ages should have K values for relations with id[0]...id[K-1]
                  for i in range(n): # Process relation line for person ids[i]
                        if current_data_line_idx >= len(source_lines): raise ValueError(f"Missing relation line {i}")
                        value_line = source_lines[current_data_line_idx].split()
                        if len(value_line) != i: raise ValueError(f"Incorrect num values on relation line {i} (expected {i}, got {len(value_line)})")
                        current_data_line_idx += 1
                        for j in range(i): # Relates ids[i] with ids[j]
                            value = parse_int(value_line[j])
                            if value is None or value < 0: raise ValueError(f"Invalid value on line {i}")
                            if value > 0: network.add_relation(ids[i], ids[j], value) # Ignore "Ok"
             except Exception as e:
                  result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Checker error during load sim: {type(e).__name__} {e}"}); break
             continue # Move to next command from input

        # --- Handle regular commands ---
        actual_output = None
        if output_idx >= len(output_lines):
             result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": "???", "actual": None, "reason": "Missing output"}); break
        actual_output = output_lines[output_idx]
        output_idx += 1

        # Simulate command using the (now faster) NetworkSimulator methods
        try:
            # --- Command dispatching (same as before) ---
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
                expected_output = network.is_circle(id1, id2) # Still uses BFS
            elif cmd in ("qts", "query_triple_sum") and len(parts) == 1:
                expected_output = network.query_triple_sum() # Now O(1)
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
                expected_output = network.query_best_acquaintance(id_val)
            else:
                 raise ValueError(f"Unknown or malformed command: '{cmd_line}'")

        except ValueError as e:
             result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Checker Error: Invalid args/cmd: {e}"}); break
        except Exception as e:
             result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Checker Error: Sim Error: {type(e).__name__} {e}"}); break

        # Compare expected vs actual
        if actual_output != expected_output:
             result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": expected_output, "actual": actual_output, "reason": "Output mismatch"}); break

    # Final Check for Extra Output
    if result_status == "Accepted" and output_idx < len(output_lines):
        result_status = "Rejected"; error_details.append({"command_number": command_num + 1, "reason": "Extra output", "actual": output_lines[output_idx]})

    # Output JSON Result
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