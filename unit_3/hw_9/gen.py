import random
import argparse
import os
import sys
import math
from contextlib import redirect_stdout
from collections import defaultdict

# --- State Tracking ---
persons = set() # {person_id, ...}
relations = set() # {(person_id1, person_id2), ...} where id1 < id2
relation_values = {} # {(person_id1, person_id2): value, ...} where id1 < id2
person_tags = defaultdict(set) # {person_id: {tag_id1, tag_id2, ...}, ...}
tag_members = defaultdict(set) # {(owner_person_id, tag_id): {member_person_id1, ...}, ...}
person_details = {} # {person_id: {'name': name, 'age': age}, ...}
person_degrees = defaultdict(int) # {person_id: degree, ...}

# --- Helper Functions ---

def generate_name(person_id):
    # Use a more structured name based on seed for reproducibility if needed
    # For now, keep it simple
    return f"Name_{person_id}"

# (get_eligible_persons, get_random_person, get_two_random_persons - modified slightly for clarity)
def get_eligible_persons(id_limit=None):
    eligible = persons.copy()
    if id_limit is not None:
        eligible = {p for p in eligible if p < id_limit}
    return eligible

def get_random_person(id_limit=None):
    eligible = get_eligible_persons(id_limit)
    # Convert set to list for reproducible random.choice with seeding
    return random.choice(sorted(list(eligible))) if eligible else None

def get_two_random_persons(id_limit=None):
    eligible = get_eligible_persons(id_limit)
    if len(eligible) < 2:
        return None, None
    # Convert set to list for reproducible random.choice with seeding
    eligible_list = sorted(list(eligible))
    p1 = random.choice(eligible_list)
    eligible.remove(p1)
    eligible_list.remove(p1) # Also remove from list
    p2 = random.choice(eligible_list)
    return p1, p2

# (get_eligible_relations, get_random_relation - remain similar)
def get_eligible_relations(id_limit=None):
    eligible = relations.copy()
    if id_limit is not None:
        eligible = {(p1, p2) for p1, p2 in eligible if p1 < id_limit and p2 < id_limit}
    return eligible

def get_random_relation(id_limit=None):
    eligible = get_eligible_relations(id_limit)
    # Convert set to list for reproducible random.choice with seeding
    return random.choice(sorted(list(eligible))) if eligible else (None, None)

# (get_random_tag_owner_and_tag, get_random_member_in_tag - remain similar)
def get_random_tag_owner_and_tag(owner_id_limit=None):
    eligible_owners = get_eligible_persons(owner_id_limit)
    owners_with_tags = [pid for pid, tags in person_tags.items() if tags and pid in eligible_owners]
    if not owners_with_tags: return None, None
    # Sort for reproducibility
    owner_id = random.choice(sorted(owners_with_tags))
    # Sort tags for reproducibility
    tag_id = random.choice(sorted(list(person_tags[owner_id])))
    return owner_id, tag_id

def get_random_member_in_tag(owner_id, tag_id):
    tag_key = (owner_id, tag_id)
    members = tag_members.get(tag_key, set())
    # Convert set to list for reproducible random.choice with seeding
    return random.choice(sorted(list(members))) if members else None

# --- State Update Functions (with degree updates) ---
def add_person_state(person_id, name, age):
    if person_id not in persons:
        persons.add(person_id)
        person_details[person_id] = {'name': name, 'age': age}
        person_degrees[person_id] = 0 # Initialize degree
        return True
    return False

def add_relation_state(id1, id2, value, max_degree=None):
    if id1 == id2 or (min(id1, id2), max(id1, id2)) in relations:
         return False # Self-relation or already exists

    # Check max_degree constraint *before* adding
    if max_degree is not None:
         # Use .get() with default 0 in case a person was just added but degree not yet set? (Should be set by add_person_state)
        if person_degrees.get(id1, 0) >= max_degree or person_degrees.get(id2, 0) >= max_degree:
            # print(f"DEBUG: Max degree blocked ar {id1}({person_degrees.get(id1, 0)}) {id2}({person_degrees.get(id2, 0)}) vs {max_degree}", file=sys.stderr)
            return False # Would exceed max degree

    p1, p2 = min(id1, id2), max(id1, id2)
    rel_key = (p1, p2)
    relations.add(rel_key)
    relation_values[rel_key] = value
    person_degrees[p1] += 1
    person_degrees[p2] += 1
    return True

def remove_relation_state(id1, id2):
    if id1 == id2: return False
    p1, p2 = min(id1, id2), max(id1, id2)
    rel_key = (p1, p2)
    if rel_key in relations:
        relations.remove(rel_key)
        if rel_key in relation_values:
            del relation_values[rel_key]
        # Decrement degrees only if they exist (should always exist if relation existed)
        if p1 in person_degrees: person_degrees[p1] -= 1
        if p2 in person_degrees: person_degrees[p2] -= 1
        # Optional: Clean up degree entry if it becomes 0? Maybe not necessary.
        return True
    return False

def add_tag_state(person_id, tag_id):
    if tag_id not in person_tags[person_id]:
        person_tags[person_id].add(tag_id)
        # Ensure tag_members key exists even if empty initially
        tag_members[(person_id, tag_id)] = tag_members.get((person_id, tag_id), set())
        return True
    return False

def remove_tag_state(person_id, tag_id):
    if tag_id in person_tags[person_id]:
        person_tags[person_id].remove(tag_id)
        # Don't remove person_id key from person_tags if set becomes empty
        # Remove the member list for this tag
        tag_key = (person_id, tag_id)
        if tag_key in tag_members:
            del tag_members[tag_key]
        return True
    return False

def add_person_to_tag_state(person_id1, person_id2, tag_id, max_tag_size):
    tag_key = (person_id2, tag_id)
    p1_rel_p2_key = (min(person_id1, person_id2), max(person_id1, person_id2))

    # Preconditions check
    if not (person_id1 in persons and person_id2 in persons and
            person_id1 != person_id2 and
            p1_rel_p2_key in relations and
            tag_id in person_tags.get(person_id2, set()) and
            person_id1 not in tag_members.get(tag_key, set())):
        return False # Preconditions fail or already member

    # Size check
    current_size = len(tag_members.get(tag_key, set()))
    # Use JML limit (1000) and user limit (max_tag_size)
    effective_max_size = 1000
    if max_tag_size is not None:
        effective_max_size = min(effective_max_size, max_tag_size)

    if current_size < effective_max_size:
        tag_members[tag_key].add(person_id1)
        return True
    else:
        # print(f"DEBUG: Max tag size {current_size}/{effective_max_size} blocked att {person_id1} to {tag_key}", file=sys.stderr)
        return False # Size limit reached

def remove_person_from_tag_state(person_id1, person_id2, tag_id):
    tag_key = (person_id2, tag_id)
    if tag_id not in person_tags.get(person_id2, set()):
        return False # Tag doesn't exist for owner

    if person_id1 in tag_members.get(tag_key, set()):
        tag_members[tag_key].remove(person_id1)
        return True
    return False # Person not in tag

# --- Command Weights Setup ---
def get_command_weights(phase="default", tag_focus=0.3):
    # Base weights, adjust as needed
    base_weights = {
        "ap": 15, "ar": 10, "mr": 5, "at": 8, "dt": 3,
        "att": 8, "dft": 4, "qv": 10, "qci": 10, "qts": 3,
        "qtav": 8, "qba": 6
    }
    # Define weights for different phases
    phase_weights = {
        "build": {**base_weights, "ap": 30, "ar": 25, "mr": 2, "qv": 2, "qci": 1, "qts": 0, "qtav": 1, "qba": 1},
        "query": {**base_weights, "ap": 1, "ar": 2, "mr": 2, "qv": 20, "qci": 20, "qts": 10, "qtav": 15, "qba": 15},
        "modify":{**base_weights, "ap": 2, "ar": 5, "mr": 20, "at": 10, "dt": 10, "att": 15, "dft": 10, "qtav": 5},
        "default": base_weights
    }
    current_weights = phase_weights.get(phase, base_weights).copy()

    # Adjust for tag_focus
    tag_cmds = {"at", "dt", "att", "dft", "qtav"}
    total_weight = sum(current_weights.values())
    current_tag_weight = sum(w for cmd, w in current_weights.items() if cmd in tag_cmds)
    current_tag_ratio = current_tag_weight / total_weight if total_weight > 0 else 0

    # Simple adjustment: Scale tag/non-tag weights towards the focus ratio
    # More complex scaling could be used, this is a basic approach
    if total_weight > 0 and abs(current_tag_ratio - tag_focus) > 0.05: # Adjust if ratio differs significantly
        scale_factor = (tag_focus / current_tag_ratio) if current_tag_ratio > 0 else 1.5 # Boost tags if none exist
        non_tag_scale = ((1-tag_focus)/(1-current_tag_ratio)) if (1-current_tag_ratio) > 0 else 0.5

        for cmd in list(current_weights.keys()):
             if cmd in tag_cmds:
                 current_weights[cmd] = max(1, int(current_weights[cmd] * scale_factor)) # Ensure weight is at least 1
             else:
                 current_weights[cmd] = max(1, int(current_weights[cmd] * non_tag_scale))

    return current_weights


# --- Phase Parsing ---
def parse_phases(phase_string):
    if not phase_string:
        return None, None
    phases = []
    total_commands = 0
    try:
        parts = phase_string.split(',')
        for part in parts:
            name, count_str = part.split(':')
            count = int(count_str)
            if count <= 0: raise ValueError("Phase count must be positive")
            phases.append({'name': name.strip().lower(), 'count': count})
            total_commands += count
        return phases, total_commands
    except Exception as e:
        raise ValueError(f"Invalid phase string format: '{phase_string}'. Use 'name1:count1,name2:count2,...'. Error: {e}")


# --- Main Generation Logic ---
def generate_commands(num_commands_target, max_person_id, max_tag_id, max_rel_value, max_mod_value, max_age,
                      rel_id_limit, min_qci, min_qts, min_qtav, min_qba,
                      density, degree_focus, max_degree, tag_focus, max_tag_size, qci_focus, mr_delete_ratio, phases_config):

    generated_cmds_list = []
    cmd_counts = defaultdict(int)
    current_phase_index = 0
    commands_in_current_phase = 0
    num_commands_to_generate = num_commands_target

    # Override target command count if phases define the total
    if phases_config:
        num_commands_to_generate = sum(p['count'] for p in phases_config)
        print(f"INFO: Phases defined. Target commands set to {num_commands_to_generate}", file=sys.stderr)


    # --- Initial Population ---
    # Use random.sample for initial population if we want non-sequential IDs,
    # but sequential starting from 0 is simpler and fine.
    initial_people = min(num_commands_to_generate // 10 + 5, 50, max_person_id + 1)
    current_id = 0
    for _ in range(initial_people):
        if current_id > max_person_id: break
        person_id = current_id
        if person_id not in persons:
             name = generate_name(person_id)
             age = random.randint(1, max_age)
             if add_person_state(person_id, name, age):
                 cmd = f"ap {person_id} {name} {age}"
                 generated_cmds_list.append(cmd)
                 cmd_counts['ap'] += 1
        current_id += 1

    # --- Main Generation Loop ---
    while len(generated_cmds_list) < num_commands_to_generate:
        # Determine current phase and get weights
        current_phase_name = "default"
        if phases_config:
            current_phase_info = phases_config[current_phase_index]
            current_phase_name = current_phase_info['name']
            if commands_in_current_phase >= current_phase_info['count']:
                current_phase_index += 1
                commands_in_current_phase = 0
                if current_phase_index >= len(phases_config):
                     print("INFO: All defined phases completed.", file=sys.stderr)
                     break # Stop if all phases are done, even if target N not reached
                current_phase_info = phases_config[current_phase_index]
                current_phase_name = current_phase_info['name']


        weights_dict = get_command_weights(current_phase_name, tag_focus)

        # Filter out impossible commands based on state
        can_relate = len(persons) >= 2
        can_modify_rel = bool(relations)
        can_tag = bool(persons)
        has_tags = any(person_tags.values())
        can_add_to_tag = any(r for r in relations if any(t for t in person_tags.get(r[0], [])) or any(t for t in person_tags.get(r[1], []))) # Rough check: need relations and tags
        has_tag_members = any(tag_members.values())

        if not can_relate:
            for cmd_type in ["ar", "mr", "qv", "qci", "att", "dft"]: weights_dict.pop(cmd_type, None)
        if not can_modify_rel:
            for cmd_type in ["mr", "qv"]: weights_dict.pop(cmd_type, None) # qv might still query non-existent
        if not has_tags:
             for cmd_type in ["dt", "qtav"]: weights_dict.pop(cmd_type, None)
        if not can_add_to_tag: # If no one has tags or no relations exist
             weights_dict.pop("att", None)
        if not has_tag_members: # If no tag has any members yet
             weights_dict.pop("dft", None)

        # Need at least one person for these
        if not persons:
            for cmd_type in ["ap", "at", "qba", "qts"]: weights_dict.pop(cmd_type, None)

        if not weights_dict:
             print("Warning: No commands possible with current state and weights! Breaking generation loop.", file=sys.stderr)
             # Add a default person if possible, otherwise break
             if 'ap' in get_command_weights(current_phase_name, tag_focus) and len(persons) <= max_person_id:
                 person_id = random.randint(0, max_person_id)
                 name = generate_name(person_id)
                 age = random.randint(1, max_age)
                 if add_person_state(person_id, name, age):
                    cmd = f"ap {person_id} {name} {age}"
                    generated_cmds_list.append(cmd)
                    cmd_counts['ap'] += 1
                    if phases_config: commands_in_current_phase += 1
                    continue # Try the main loop again
                 else:
                    break # Couldn't even add a person
             else:
                 break


        # Ensure reproducibility of choice based on weights
        # Convert weights dict to lists
        command_types = sorted(list(weights_dict.keys()))
        weights = [weights_dict[cmd_type] for cmd_type in command_types]

        cmd_type = random.choices(command_types, weights=weights, k=1)[0]
        cmd = None

        try:
            # --- Command Generation ---
            if cmd_type == "ap":
                # Try to find an unused ID first, then maybe overwrite
                unused_ids = [i for i in range(max_person_id + 1) if i not in persons]
                if unused_ids:
                    person_id = random.choice(unused_ids)
                else: # Only overwrite if absolutely necessary and allowed (implicitly here)
                    person_id = random.randint(0, max_person_id) # Might overwrite existing, ap handles this

                name = generate_name(person_id)
                age = random.randint(1, max_age)
                if add_person_state(person_id, name, age): # State updated internally
                    cmd = f"ap {person_id} {name} {age}"
                # Else: Person already exists, command failed state update, cmd remains None

            elif cmd_type == "ar":
                p1, p2 = get_two_random_persons(id_limit=rel_id_limit)
                if p1 is not None and p2 is not None:
                    # Density check
                    current_nodes = len(persons)
                    max_possible_edges = (current_nodes * (current_nodes - 1)) // 2 if current_nodes > 1 else 0
                    current_density = len(relations) / max_possible_edges if max_possible_edges > 0 else 0
                    # Add relation with higher probability if density is low, lower if high
                    # Bias towards adding if density is below target
                    prob_add = 0.6 + (density - current_density) # Centered around 0.6, adjusts based on diff
                    prob_add = max(0.05, min(0.95, prob_add)) # Clamp probability

                    if random.random() < prob_add:
                        value = random.randint(1, max_rel_value)
                        # Degree focus / max_degree check is inside add_relation_state
                        if add_relation_state(p1, p2, value, max_degree):
                            cmd = f"ar {p1} {p2} {value}"

            elif cmd_type == "mr":
                p1, p2 = get_random_relation(id_limit=rel_id_limit)
                if p1 is not None and p2 is not None:
                    rel_key = (p1, p2)
                    current_value = relation_values.get(rel_key, 0) # Should exist if get_random_relation worked
                    m_val = 0
                    if current_value > 0 and random.random() < mr_delete_ratio:
                        # Target deletion - make value <= 0
                        m_val = -current_value - random.randint(0, 10) # Ensure it goes <= 0
                    else:
                        # Random modification
                        m_val = random.randint(-max_mod_value, max_mod_value)
                        # Ensure modification isn't zero unless it's the only option
                        if m_val == 0 and max_mod_value != 0:
                             m_val = random.choice([-1, 1]) * random.randint(1, max(1, max_mod_value))


                    cmd = f"mr {p1} {p2} {m_val}"
                    # State update (remove or modify value)
                    new_value = current_value + m_val
                    if new_value <= 0:
                        remove_relation_state(p1, p2) # State updated internally
                    else:
                        relation_values[rel_key] = new_value
                        # Degree doesn't change when only value is modified

            elif cmd_type == "at":
                person_id = get_random_person()
                if person_id is not None:
                    tag_id = random.randint(0, max_tag_id)
                    if add_tag_state(person_id, tag_id):
                         cmd = f"at {person_id} {tag_id}"

            elif cmd_type == "dt":
                owner_id, tag_id = get_random_tag_owner_and_tag()
                if owner_id is not None:
                    if remove_tag_state(owner_id, tag_id):
                        cmd = f"dt {owner_id} {tag_id}"

            elif cmd_type == "att":
                 owner_id, tag_id = get_random_tag_owner_and_tag()
                 if owner_id is not None:
                     # Find someone related to owner_id who is not already in the tag
                     related_persons = set()
                     # Sort relations for reproducibility before iterating
                     for r_p1, r_p2 in sorted(list(relations)):
                         if r_p1 == owner_id: related_persons.add(r_p2)
                         if r_p2 == owner_id: related_persons.add(r_p1)

                     tag_key = (owner_id, tag_id)
                     current_members = tag_members.get(tag_key, set())
                     # Sort potential members for reproducibility
                     possible_members = sorted(list(related_persons - {owner_id} - current_members))

                     if possible_members:
                         person_id1 = random.choice(possible_members)
                         # State update handles size check internally now
                         if add_person_to_tag_state(person_id1, owner_id, tag_id, max_tag_size):
                            cmd = f"att {person_id1} {owner_id} {tag_id}"

            elif cmd_type == "dft":
                 owner_id, tag_id = get_random_tag_owner_and_tag()
                 if owner_id is not None:
                     member_id = get_random_member_in_tag(owner_id, tag_id)
                     if member_id is not None:
                         if remove_person_from_tag_state(member_id, owner_id, tag_id):
                            cmd = f"dft {member_id} {owner_id} {tag_id}"

            elif cmd_type == "qv":
                # Maybe prioritize existing relations slightly more?
                if random.random() < 0.9 and relations:
                    p1, p2 = get_random_relation()
                else:
                    p1, p2 = get_two_random_persons()
                if p1 is not None and p2 is not None:
                    cmd = f"qv {p1} {p2}"

            elif cmd_type == "qci":
                 # Implement qci_focus
                 p1, p2 = None, None
                 if qci_focus == 'close' and relations:
                     p1, p2 = get_random_relation() # Query connected people
                 elif qci_focus == 'far': # Hard to guarantee 'far', use random but avoid direct links?
                      p1, p2 = get_two_random_persons()
                      if p1 is not None and (min(p1,p2), max(p1,p2)) in relations:
                          # Try one more time to get non-related
                          p1_alt, p2_alt = get_two_random_persons()
                          # Check if the alternative pair is valid and not related
                          if p1_alt is not None and (min(p1_alt,p2_alt), max(p1_alt,p2_alt)) not in relations:
                               p1, p2 = p1_alt, p2_alt
                          # If still related or alt failed, just use the first random pair
                 # elif qci_focus == 'disconnected': # Very hard to guarantee without full connectivity tracking
                 #      pass # Fallback to mixed/random
                 else: # mixed (default) or fallback
                      p1, p2 = get_two_random_persons()

                 if p1 is not None and p2 is not None:
                      cmd = f"qci {p1} {p2}"

            elif cmd_type == "qts":
                 cmd = "qts" # No parameters needed

            elif cmd_type == "qtav":
                owner_id, tag_id = get_random_tag_owner_and_tag()
                # Occasionally query non-existent tags/persons or empty tags
                if owner_id is None or random.random() < 0.15:
                     owner_id = get_random_person() # Could be None if no persons exist
                     tag_id = random.randint(0, max_tag_id) # Might not exist for this person
                elif random.random() < 0.05: # Small chance to query valid owner but non-existent tag
                    tag_id = random.randint(0, max_tag_id)
                    while tag_id in person_tags.get(owner_id, set()): # Ensure it's a non-existent tag for this owner
                         tag_id = random.randint(0, max_tag_id)

                if owner_id is not None: # Only generate command if we have an owner ID
                    cmd = f"qtav {owner_id} {tag_id}"

            elif cmd_type == "qba":
                 person_id = get_random_person()
                 if person_id is not None:
                      cmd = f"qba {person_id}"
                 # else: No person exists, cmd remains None

        except Exception as e:
            print(f"ERROR generating command {cmd_type}: {e}", file=sys.stderr)
            # Optionally add more debug info like traceback
            # import traceback
            # traceback.print_exc(file=sys.stderr)
            continue # Skip this command attempt

        if cmd:
            generated_cmds_list.append(cmd)
            cmd_counts[cmd_type] += 1
            if phases_config:
                 commands_in_current_phase += 1
        # else: The command generation attempt failed (e.g., preconditions not met),
        #      no command added, loop continues.


    # --- Supplementary loop for minimum query counts ---
    min_counts_map = { "qci": min_qci, "qts": min_qts, "qtav": min_qtav, "qba": min_qba }
    for query_type, min_req in min_counts_map.items():
        attempts = 0
        max_attempts = min_req * 3 + 10 # Limit attempts to avoid infinite loops if state prevents generation

        while cmd_counts[query_type] < min_req and attempts < max_attempts:
            cmd = None
            attempts += 1
            try:
                if query_type == "qci":
                    p1, p2 = get_two_random_persons()
                    if p1 is not None and p2 is not None: cmd = f"qci {p1} {p2}"
                elif query_type == "qts":
                    cmd = "qts"
                elif query_type == "qtav":
                    owner_id, tag_id = get_random_tag_owner_and_tag()
                    if owner_id is None: # If no tags exist, pick random person/tag
                        owner_id = get_random_person()
                        if owner_id is not None:
                            tag_id = random.randint(0, max_tag_id)
                        # else: no people exist, cannot generate qtav
                    if owner_id is not None: # Ensure owner exists
                        cmd = f"qtav {owner_id} {tag_id}"

                elif query_type == "qba":
                    person_id = get_random_person()
                    if person_id is not None: cmd = f"qba {person_id}"

            except Exception as e:
                 print(f"ERROR generating supplementary command {query_type}: {e}", file=sys.stderr)
                 break # Stop trying for this query type on error

            if cmd:
                generated_cmds_list.append(cmd)
                cmd_counts[query_type] += 1
                # Reset attempts counter after success if needed (though linear limit is likely fine)
            # else: Generation failed, loop continues (up to max_attempts)

        if cmd_counts[query_type] < min_req:
             print(f"Warning: Could not generate {min_req} required '{query_type}' commands after {attempts} attempts. Generated {cmd_counts[query_type]}. State might be prohibitive.", file=sys.stderr)


    return generated_cmds_list, cmd_counts


# --- Argument Parsing ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate test data for HW9 social network with performance focus.")

    # Core Controls
    parser.add_argument("-n", "--num_commands", type=int, default=1000, help="Target number of commands (ignored if --phases is set).")
    parser.add_argument("--max_person_id", type=int, default=100, help="Maximum person ID (0 to max).")
    parser.add_argument("--max_tag_id", type=int, default=10, help="Maximum tag ID per person (0 to max).")
    parser.add_argument("--max_age", type=int, default=99, help="Maximum person age.")
    parser.add_argument("-o", "--output_file", type=str, default=None, help="Output file name (default: stdout).")
    parser.add_argument("--hce", action='store_true', help="Enable HCE constraints (n<=3000, max_person_id<=99).")
    parser.add_argument("--seed", type=int, default=None, help="Seed for the random number generator for reproducible results.") # ADDED SEED ARG

    # Relation/Value Controls
    parser.add_argument("--max_rel_value", type=int, default=200, help="Maximum initial relation value.")
    parser.add_argument("--max_mod_value", type=int, default=200, help="Maximum absolute modify relation value change.")
    parser.add_argument("--mr_delete_ratio", type=float, default=0.1, help="Approx. ratio of 'mr' commands targeting relation deletion (0.0-1.0).")

    # Graph Structure Controls
    parser.add_argument("--density", type=float, default=0.1, help="Target graph density (approx. ratio of actual/possible edges, 0.0-1.0).")
    parser.add_argument("--degree_focus", choices=['uniform', 'hub'], default='uniform', help="Influence degree distribution ('hub' not fully implemented yet).")
    parser.add_argument("--max_degree", type=int, default=None, help="Attempt to limit the maximum degree of any person.")
    parser.add_argument("--rel_id_limit", type=int, default=None, help="Explicitly limit ar/mr commands to IDs < LIMIT.")

    # Tag Controls
    parser.add_argument("--tag_focus", type=float, default=0.3, help="Approx. ratio of total commands related to tags (0.0-1.0).")
    parser.add_argument("--max_tag_size", type=int, default=50, help="Attempt to limit the max number of persons in a tag (up to JML limit).")

    # Query Controls
    parser.add_argument("--qci_focus", choices=['mixed', 'close', 'far'], default='mixed', help="Influence the type of pairs queried by 'qci'.")
    parser.add_argument("--min_qci", type=int, default=0, help="Minimum number of qci commands.")
    parser.add_argument("--min_qts", type=int, default=0, help="Minimum number of qts commands.")
    parser.add_argument("--min_qtav", type=int, default=0, help="Minimum number of qtav commands.")
    parser.add_argument("--min_qba", type=int, default=0, help="Minimum number of qba commands.")

    # Generation Flow Control
    parser.add_argument("--phases", type=str, default=None, help="Define generation phases, e.g., 'build:500,query:1000,modify:500'. Overrides -n.")

    args = parser.parse_args()

    # --- Apply Seed --- ADDED SEEDING LOGIC
    if args.seed is not None:
        print(f"INFO: Using random seed: {args.seed}", file=sys.stderr)
        random.seed(args.seed)
    else:
        # Default behavior: random seed is initialized based on system time or OS sources implicitly.
        print(f"INFO: No seed provided, using default random seeding.", file=sys.stderr)


    # --- Apply HCE Constraints ---
    if args.hce:
        print("INFO: HCE mode enabled. Adjusting parameters...", file=sys.stderr)
        hce_max_n = 3000
        hce_max_pid = 99
        # Adjust N only if phases are not set
        if not args.phases:
             if args.num_commands > hce_max_n:
                 print(f"  num_commands capped from {args.num_commands} to {hce_max_n}", file=sys.stderr)
                 args.num_commands = hce_max_n
        # Always cap max_person_id
        if args.max_person_id > hce_max_pid:
            print(f"  max_person_id capped from {args.max_person_id} to {hce_max_pid}", file=sys.stderr)
            args.max_person_id = hce_max_pid

    # --- Validate Phases ---
    phases_config = None
    if args.phases:
        try:
            phases_config, total_phase_commands = parse_phases(args.phases)
            if args.hce and total_phase_commands > hce_max_n:
                 print(f"WARNING: Total commands in --phases ({total_phase_commands}) exceeds HCE limit ({hce_max_n}). Generator might stop early or behavior might be unexpected.", file=sys.stderr)
            args.num_commands = total_phase_commands # Use phase total as the target
        except ValueError as e:
            print(f"ERROR: Invalid --phases argument: {e}", file=sys.stderr)
            sys.exit(1)

    # --- Prepare Output ---
    output_stream = open(args.output_file, 'w') if args.output_file else sys.stdout

    # --- Generate and Output ---
    try:
        # Clear global state (important if run multiple times in same process, less so for script execution)
        persons.clear(); relations.clear(); relation_values.clear()
        person_tags.clear(); tag_members.clear(); person_details.clear()
        person_degrees.clear()

        all_commands, final_cmd_counts = generate_commands(
            args.num_commands, args.max_person_id, args.max_tag_id,
            args.max_rel_value, args.max_mod_value, args.max_age,
            args.rel_id_limit, args.min_qci, args.min_qts,
            args.min_qtav, args.min_qba,
            args.density, args.degree_focus, args.max_degree,
            args.tag_focus, args.max_tag_size, args.qci_focus,
            args.mr_delete_ratio, phases_config
        )

        # Print all generated commands to the designated stream
        for command in all_commands:
             output_stream.write(command + '\n')

        # Print summary to stderr
        final_command_count = len(all_commands)
        print(f"\n--- Generation Summary ---", file=sys.stderr)
        print(f"Target commands: {args.num_commands} (based on -n or --phases)", file=sys.stderr)
        print(f"Actual commands generated: {final_command_count}", file=sys.stderr)
        print(f"Command Counts:", file=sys.stderr)
        for cmd_type, count in sorted(final_cmd_counts.items()):
            print(f"  {cmd_type}: {count}", file=sys.stderr)
        if args.output_file:
             print(f"Output written to: {args.output_file}", file=sys.stderr)
        else:
             print(f"Output printed to stdout.", file=sys.stderr)


    finally:
        if args.output_file and output_stream is not sys.stdout:
            output_stream.close()