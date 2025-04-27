# --- START OF FILE gen.py ---

import random
import argparse
import os
import sys
import math
from contextlib import redirect_stdout
from collections import defaultdict
import traceback # For debugging exceptions during generation

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
    # 保证生成的 name 长度不超过 100
    base_name = f"Name_{person_id}"
    if len(base_name) > 100:
        # 理论上对于 int 范围内的 id 几乎不可能超过，但为了安全加上
        return f"N_{person_id}"[:100]
    return base_name

def get_eligible_persons(id_limit=None, require_degree_greater_than=None):
    eligible = persons.copy()
    if id_limit is not None:
        eligible = {p for p in eligible if p < id_limit}
    if require_degree_greater_than is not None:
        eligible = {p for p in eligible if person_degrees.get(p, 0) > require_degree_greater_than}
    return eligible

def get_random_person(id_limit=None, require_degree_greater_than=None):
    eligible = get_eligible_persons(id_limit, require_degree_greater_than)
    return random.choice(sorted(list(eligible))) if eligible else None

# Helper to get an *existing* person ID
def get_existing_person_id():
    return get_random_person()

# Helper to get a *non-existent* person ID (within reasonable bounds)
def get_non_existent_person_id(max_person_id):
    if not persons: # If no persons exist, any ID is non-existent
        return random.randint(0, max_person_id)
    
    attempts = 0
    max_attempts = (max_person_id + 1) * 2 # Heuristic limit
    while attempts < max_attempts:
        pid = random.randint(0, max_person_id + 10) # Slightly exceed max_id for variety
        if pid not in persons:
            return pid
        attempts += 1
    # Fallback: Very unlikely, but return an existing one if we can't find non-existent
    # This indicates max_person_id might be too small or graph is full
    # print("WARN: Could not find non-existent person ID easily.", file=sys.stderr)
    existing_id = get_existing_person_id()
    return existing_id + 1 if existing_id is not None else 0 # Try one higher than existing


def get_two_random_persons(id_limit=None, require_different=True):
    eligible = get_eligible_persons(id_limit)
    if len(eligible) < (2 if require_different else 1):
        return None, None
        
    eligible_list = sorted(list(eligible))
    p1 = random.choice(eligible_list)
    
    if not require_different:
        p2 = random.choice(eligible_list)
        return p1,p2

    eligible_list_copy = eligible_list[:] # Work on a copy
    eligible_list_copy.remove(p1)
    if not eligible_list_copy: # Only one person exists
        return p1, None # Or None, None depending on expectation? Let's return p1, None
    p2 = random.choice(eligible_list_copy)
    return p1, p2

def get_eligible_relations(id_limit=None):
    eligible = relations.copy()
    if id_limit is not None:
        eligible = {(p1, p2) for p1, p2 in eligible if p1 < id_limit and p2 < id_limit}
    return eligible

def get_random_relation(id_limit=None):
    eligible = get_eligible_relations(id_limit)
    return random.choice(sorted(list(eligible))) if eligible else (None, None)

# Helper to get an *existing* relation
def get_existing_relation():
    return get_random_relation()

# Helper to get two persons *without* a relation
def get_non_existent_relation_pair():
    if len(persons) < 2: return None, None
    attempts = 0
    max_attempts = len(persons) * 2 # Heuristic
    while attempts < max_attempts:
        p1, p2 = get_two_random_persons()
        if p1 is not None and p2 is not None:
             rel_key = (min(p1, p2), max(p1, p2))
             if rel_key not in relations:
                 return p1, p2
        attempts += 1
    # Fallback: if highly dense, might be hard; return random pair
    # print("WARN: Could not find non-existent relation pair easily.", file=sys.stderr)
    return get_two_random_persons()


def get_random_tag_owner_and_tag(owner_id_limit=None, require_non_empty=False):
    eligible_owners = get_eligible_persons(owner_id_limit)
    
    owners_with_tags = []
    for pid in eligible_owners:
        tags = person_tags.get(pid)
        if tags:
            for tag_id in tags:
                 if not require_non_empty or tag_members.get((pid, tag_id)):
                     owners_with_tags.append((pid, tag_id))

    if not owners_with_tags: return None, None
    
    # Sort for reproducibility before choice
    owner_id, tag_id = random.choice(sorted(owners_with_tags))
    return owner_id, tag_id

# Helper to get a tag ID that *does not* exist for a given person
def get_non_existent_tag_id(person_id, max_tag_id):
     if person_id not in persons: return random.randint(0, max_tag_id) # Any tag is non-existent
     
     existing_tags = person_tags.get(person_id, set())
     if len(existing_tags) > max_tag_id: # Fully saturated?
          # print(f"WARN: Person {person_id} has {len(existing_tags)} tags, might exceed max_tag_id {max_tag_id}.", file=sys.stderr)
          return max_tag_id + 1 # Try one above max
          
     attempts = 0
     max_attempts = max_tag_id * 2 + 5
     while attempts < max_attempts:
          tag_id = random.randint(0, max_tag_id)
          if tag_id not in existing_tags:
               return tag_id
          attempts += 1
     # Fallback
     # print(f"WARN: Could not find non-existent tag ID easily for {person_id}.", file=sys.stderr)
     return max_tag_id + 1

# Helper to get a person *in* a specific tag
def get_random_member_in_tag(owner_id, tag_id):
    tag_key = (owner_id, tag_id)
    members = tag_members.get(tag_key, set())
    return random.choice(sorted(list(members))) if members else None

# Helper to get a person related to owner *not* in the tag
def get_related_person_not_in_tag(owner_id, tag_id):
    if owner_id is None or tag_id is None: return None
    related_persons = set()
    for r_p1, r_p2 in relations: # Check existing relations for neighbors
        if r_p1 == owner_id: related_persons.add(r_p2)
        if r_p2 == owner_id: related_persons.add(r_p1)

    tag_key = (owner_id, tag_id)
    current_members = tag_members.get(tag_key, set())
    possible_members = sorted(list(related_persons - {owner_id} - current_members))
    return random.choice(possible_members) if possible_members else None
    
# Helper to get a person *not* in a specific tag (could be unrelated)
def get_person_not_in_tag(owner_id, tag_id):
    tag_key = (owner_id, tag_id)
    current_members = tag_members.get(tag_key, set())
    non_members = sorted(list(persons - current_members - {owner_id}))
    return random.choice(non_members) if non_members else None
    
# Helper to find an owner/tag pair that is empty
def get_random_empty_tag():
    empty_tags = []
    for (owner_id, tag_id), members in tag_members.items():
         if not members and owner_id in persons and tag_id in person_tags.get(owner_id, set()): # Ensure owner/tag still valid
             empty_tags.append((owner_id, tag_id))
    return random.choice(sorted(empty_tags)) if empty_tags else (None, None)

# Helper to find a person with no acquaintances
def get_person_with_no_acquaintances():
     zero_degree_persons = [pid for pid, degree in person_degrees.items() if degree == 0 and pid in persons]
     return random.choice(sorted(zero_degree_persons)) if zero_degree_persons else None


# --- State Update Functions (with degree updates and MR tag removal) ---
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

    if max_degree is not None:
        if person_degrees.get(id1, 0) >= max_degree or person_degrees.get(id2, 0) >= max_degree:
            # print(f"DEBUG: Max degree blocked ar {id1}({person_degrees.get(id1, 0)}) {id2}({person_degrees.get(id2, 0)}) vs {max_degree}", file=sys.stderr)
            return False # Would exceed max degree

    p1, p2 = min(id1, id2), max(id1, id2)
    rel_key = (p1, p2)
    relations.add(rel_key)
    relation_values[rel_key] = value
    person_degrees[p1] = person_degrees.get(p1, 0) + 1 # Use get for safety
    person_degrees[p2] = person_degrees.get(p2, 0) + 1 # Use get for safety
    return True

# ** CRUCIAL UPDATE for JML Compliance **
def remove_relation_state(id1, id2):
    if id1 == id2: return False
    p1_orig, p2_orig = id1, id2 # Keep original order for tag checking if needed
    p1, p2 = min(id1, id2), max(id1, id2)
    rel_key = (p1, p2)
    if rel_key in relations:
        relations.remove(rel_key)
        if rel_key in relation_values:
            del relation_values[rel_key]

        # Decrement degrees
        if p1 in person_degrees: person_degrees[p1] -= 1
        if p2 in person_degrees: person_degrees[p2] -= 1

        # --- JML: Remove from each other's tags ---
        # Remove p2_orig from p1_orig's tags
        tags_to_check_p1 = list(person_tags.get(p1_orig, set())) # Iterate over copy
        for tag_id in tags_to_check_p1:
             tag_key_p1_owns = (p1_orig, tag_id)
             if p2_orig in tag_members.get(tag_key_p1_owns, set()):
                 tag_members[tag_key_p1_owns].remove(p2_orig)
                 # print(f"DEBUG: State removed {p2_orig} from tag {tag_key_p1_owns} due to relation removal", file=sys.stderr) # Optional debug

        # Remove p1_orig from p2_orig's tags
        tags_to_check_p2 = list(person_tags.get(p2_orig, set())) # Iterate over copy
        for tag_id in tags_to_check_p2:
             tag_key_p2_owns = (p2_orig, tag_id)
             if p1_orig in tag_members.get(tag_key_p2_owns, set()):
                 tag_members[tag_key_p2_owns].remove(p1_orig)
                 # print(f"DEBUG: State removed {p1_orig} from tag {tag_key_p2_owns} due to relation removal", file=sys.stderr) # Optional debug
        # ----------------------------------------

        return True
    return False

def add_tag_state(person_id, tag_id):
    if person_id not in persons: return False # Cannot add tag to non-existent person
    if tag_id not in person_tags[person_id]:
        person_tags[person_id].add(tag_id)
        tag_members[(person_id, tag_id)] = tag_members.get((person_id, tag_id), set()) # Ensure key exists
        return True
    return False

def remove_tag_state(person_id, tag_id):
    if person_id not in persons: return False
    if tag_id in person_tags[person_id]:
        person_tags[person_id].remove(tag_id)
        tag_key = (person_id, tag_id)
        if tag_key in tag_members:
            del tag_members[tag_key]
        return True
    return False

def add_person_to_tag_state(person_id1, person_id2, tag_id, max_tag_size):
    tag_key = (person_id2, tag_id)
    p1_rel_p2_key = (min(person_id1, person_id2), max(person_id1, person_id2))

    # Preconditions check (matching JML)
    if not (person_id1 in persons and person_id2 in persons): return False # PersonIdNotFound
    if person_id1 == person_id2: return False # EqualPersonIdException (for att, not mr)
    if p1_rel_p2_key not in relations: return False # RelationNotFound
    if tag_id not in person_tags.get(person_id2, set()): return False # TagIdNotFound
    if person_id1 in tag_members.get(tag_key, set()): return False # EqualPersonIdException (already in tag)


    # Size check (JML limit is 1000, user limit is max_tag_size)
    current_size = len(tag_members.get(tag_key, set()))
    effective_max_size = 1000 # JML limit
    if max_tag_size is not None:
        effective_max_size = min(effective_max_size, max_tag_size)

    if current_size < effective_max_size:
        # Ensure the key exists before adding
        if tag_key not in tag_members:
             tag_members[tag_key] = set() # Should have been created by add_tag_state, but safety check
        tag_members[tag_key].add(person_id1)
        return True
    else:
        # print(f"DEBUG: Max tag size {current_size}/{effective_max_size} blocked att {person_id1} to {tag_key}", file=sys.stderr)
        return False # Size limit reached, JML implies assignable \nothing in this case

def remove_person_from_tag_state(person_id1, person_id2, tag_id):
    # Preconditions check (matching JML)
    if person_id1 not in persons or person_id2 not in persons: return False # PersonIdNotFound (implicit)
    if tag_id not in person_tags.get(person_id2, set()): return False # TagIdNotFound

    tag_key = (person_id2, tag_id)
    if person_id1 not in tag_members.get(tag_key, set()): return False # PersonIdNotFound (person not in tag)

    # Perform removal
    if tag_key in tag_members: # Check existence before removing
        tag_members[tag_key].remove(person_id1)
        # Optional: Clean up tag_members entry if set becomes empty? Maybe not necessary.
        return True
    return False # Should not happen if above checks passed, but for safety


# --- Command Weights Setup ---
# --- Command Weights Setup (MODIFIED FOR MORE EVEN QUERY DISTRIBUTION) ---
def get_command_weights(phase="default", tag_focus=0.3):
    # Base weights - Slightly increased query weights baseline
    base_weights = {
        "ap": 15, "ar": 10, "mr": 5, "at": 8, "dt": 3,
        "att": 8, "dft": 4, "qv": 12, "qci": 12, "qts": 5, # Increased base query weights
        "qtav": 10, "qba": 8                              # Increased base query weights
    }
    # Define weights for different phases
    phase_weights = {
        # Build: Still focus on adding, but allow more queries than before
        "build": {**base_weights, "ap": 25, "ar": 20, "mr": 3, "at": 6, "att": 6,
                  "qv": 5, "qci": 5, "qts": 2, "qtav": 3, "qba": 3, # Increased query weights in build
                  "dt": 1, "dft": 1},
        # Query: Focus remains on all query types
        "query": {**base_weights, "ap": 1, "ar": 1, "mr": 2, "at":1, "dt": 1, "att": 1, "dft": 1,
                   "qv": 20, "qci": 20, "qts": 10, "qtav": 15, "qba": 15},
        # Modify: Still focus on changes, but slightly more queries allowed
        "modify":{**base_weights, "ap": 2, "ar": 3, "mr": 18, "at": 10, "dt": 10, "att": 15, "dft": 10,
                   "qv": 5, "qci": 5, "qts": 2, "qtav": 6, "qba": 4}, # Slightly increased query weights
        # Churn: High add/delete rate, allow some queries
        "churn": {**base_weights, "ap": 5, "ar": 15, "mr": 25, "at": 10, "dt": 15, "att": 10, "dft": 15,
                  "qv": 3, "qci": 3, "qts": 1, "qtav": 3, "qba": 2}, # Slightly increased query weights
        # Default: Balanced mix with reasonable query presence
        "default": base_weights, # Uses the updated base_weights

        # 支持预设中使用的自定义阶段名称，映射到现有逻辑阶段
        "build_hub_rels": {**base_weights, "ap": 10, "ar": 30, "mr": 2, "at": 2, "att": 2, # 偏重加人和加关系
                         "qv": 1, "qci": 1, "qts": 1, "qtav": 1, "qba": 1, "dt": 1, "dft": 1},
        "setup_hub_tag": {**base_weights, "ap": 1, "ar": 1, "at": 20, "att": 5}, # 偏重加tag
        "fill_hub_tag": {**base_weights, "ap": 2, "ar": 5, "at": 5, "att": 30, "dft": 5}, # 偏重向tag加人
        "fill_and_query": {**base_weights, "ap": 2, "ar": 5, "at": 5, "att": 15, "dft": 3, # 混合加tag成员和查询
                           "qv": 10, "qci": 10, "qts": 5, "qtav": 15, "qba": 10},
        "test_limit": {**base_weights, "ap": 0, "ar": 0, "mr": 0, "at": 0, "dt": 0, "att": 5, "dft": 5, # 主要测试边界，少量修改tag
                       "qv": 10, "qci": 10, "qts": 10, "qtav": 10, "qba": 10},
        "modify_tags": {**base_weights, "ap": 1, "ar": 1, "mr": 2, "at": 15, "dt": 15, "att": 25, "dft": 25, # 侧重 tag 修改
                        "qv": 3, "qci": 3, "qts": 1, "qtav": 5, "qba": 2},
        "modify_rels": {**base_weights, "ap": 1, "ar": 5, "mr": 30, "at": 2, "dt": 2, "att": 3, "dft": 3, # 侧重 relation 修改
                        "qv": 5, "qci": 5, "qts": 1, "qtav": 3, "qba": 3},
    }
    current_weights = phase_weights.get(phase, phase_weights['default']).copy()

    # Adjust for tag_focus (same logic as before)
    tag_cmds = {"at", "dt", "att", "dft", "qtav"}
    total_weight = sum(current_weights.values())
    if total_weight > 0 and tag_focus is not None:
        current_tag_weight = sum(w for cmd, w in current_weights.items() if cmd in tag_cmds)
        current_tag_ratio = current_tag_weight / total_weight if total_weight else 0

        # Prevent division by zero if 1-current_tag_ratio is 0 (i.e., all weight is on tags)
        non_tag_denominator = (1 - current_tag_ratio)
        if non_tag_denominator <= 0: non_tag_denominator = 1 # Avoid division by zero, assume non-tag scale is 1

        if abs(current_tag_ratio - tag_focus) > 0.05:
            scale_factor = (tag_focus / current_tag_ratio) if current_tag_ratio > 0 else 1.5
            non_tag_scale = (1 - tag_focus) / non_tag_denominator

            for cmd in list(current_weights.keys()):
                if cmd in tag_cmds:
                    current_weights[cmd] = max(1, int(current_weights[cmd] * scale_factor))
                else:
                    current_weights[cmd] = max(1, int(current_weights[cmd] * non_tag_scale))

    return current_weights



# --- Phase Parsing ---
def parse_phases(phase_string):
    # (Same as before)
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

# --- Exception Generation Logic ---
def try_generate_exception_command(cmd_type, max_person_id, max_tag_id):
    """Attempts to generate parameters for cmd_type that cause a known exception."""
    cmd = None
    target_exception = None # For debugging/info

    try:
        if cmd_type == "ap": # Target: EqualPersonIdException
            p_id = get_existing_person_id()
            if p_id is not None:
                name = generate_name(p_id) # Name/age don't matter for this exception
                age = random.randint(1, 100)
                cmd = f"ap {p_id} {name} {age}"
                target_exception = "EqualPersonIdException"
        
        elif cmd_type == "ar": # Target: EqualRelationException or PersonIdNotFoundException
            if random.random() < 0.6 and relations: # Prioritize EqualRelation
                p1, p2 = get_existing_relation()
                if p1 is not None:
                    value = random.randint(1, 100)
                    cmd = f"ar {p1} {p2} {value}"
                    target_exception = "EqualRelationException"
            else: # Target PersonIdNotFound
                p1 = get_existing_person_id()
                p2 = get_non_existent_person_id(max_person_id)
                if p1 is not None and p2 is not None:
                    # Randomly swap p1 and p2 order
                    if random.random() < 0.5: p1, p2 = p2, p1
                    value = random.randint(1, 100)
                    cmd = f"ar {p1} {p2} {value}"
                    target_exception = "PersonIdNotFoundException"
        
        elif cmd_type == "mr": # Target: PersonIdNotFound, EqualPersonId, RelationNotFound
            choice = random.random()
            if choice < 0.4: # Target PersonIdNotFound
                p1 = get_existing_person_id()
                p2 = get_non_existent_person_id(max_person_id)
                if p1 is not None and p2 is not None:
                    if random.random() < 0.5: p1, p2 = p2, p1
                    m_val = random.randint(-50, 50)
                    cmd = f"mr {p1} {p2} {m_val}"
                    target_exception = "PersonIdNotFoundException"
            elif choice < 0.7: # Target EqualPersonId
                 p1 = get_existing_person_id()
                 if p1 is not None:
                     m_val = random.randint(-50, 50)
                     cmd = f"mr {p1} {p1} {m_val}"
                     target_exception = "EqualPersonIdException"
            else: # Target RelationNotFound
                p1, p2 = get_non_existent_relation_pair()
                if p1 is not None and p2 is not None:
                    m_val = random.randint(-50, 50)
                    cmd = f"mr {p1} {p2} {m_val}"
                    target_exception = "RelationNotFoundException"

        elif cmd_type == "at": # Target: PersonIdNotFound, EqualTagId
            if random.random() < 0.5: # Target PersonIdNotFound
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None:
                     cmd = f"at {p_id} {tag_id}"
                     target_exception = "PersonIdNotFoundException"
            else: # Target EqualTagId
                owner_id, tag_id = get_random_tag_owner_and_tag()
                if owner_id is not None:
                    cmd = f"at {owner_id} {tag_id}"
                    target_exception = "EqualTagIdException"

        elif cmd_type == "dt": # Target: PersonIdNotFound, TagIdNotFound
            if random.random() < 0.5: # Target PersonIdNotFound
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None:
                    cmd = f"dt {p_id} {tag_id}"
                    target_exception = "PersonIdNotFoundException"
            else: # Target TagIdNotFound
                p_id = get_existing_person_id()
                if p_id is not None:
                    tag_id = get_non_existent_tag_id(p_id, max_tag_id)
                    cmd = f"dt {p_id} {tag_id}"
                    target_exception = "TagIdNotFoundException"

        elif cmd_type == "att": # Target: PINF, RNF, TINF, EPI (equal person or already in tag)
            choice = random.random()
            if choice < 0.2: # PINF (p1 non-existent)
                p1 = get_non_existent_person_id(max_person_id)
                p2, tag_id = get_random_tag_owner_and_tag()
                if p1 is not None and p2 is not None:
                     cmd = f"att {p1} {p2} {tag_id}"
                     target_exception = "PersonIdNotFoundException (p1)"
            elif choice < 0.4: # PINF (p2 non-existent)
                 p1 = get_existing_person_id()
                 p2 = get_non_existent_person_id(max_person_id)
                 tag_id = random.randint(0, max_tag_id) # Tag id doesn't matter much here
                 if p1 is not None and p2 is not None:
                      cmd = f"att {p1} {p2} {tag_id}"
                      target_exception = "PersonIdNotFoundException (p2)"
            elif choice < 0.5: # EPI (p1 == p2)
                 p1 = get_existing_person_id()
                 tag_id = random.randint(0, max_tag_id) # Doesn't matter
                 if p1 is not None:
                      cmd = f"att {p1} {p1} {tag_id}"
                      target_exception = "EqualPersonIdException (p1==p2)"
            elif choice < 0.65: # RNF
                p1, p2 = get_non_existent_relation_pair()
                tag_id = random.randint(0, max_tag_id) # Doesn't matter
                if p1 is not None and p2 is not None:
                     # Ensure p2 has *some* tag, even if not tag_id, otherwise TINF might preempt RNF
                     # This is tricky, RNF is more likely if p2 has tags but not tag_id
                     if not person_tags.get(p2): add_tag_state(p2, random.randint(0,max_tag_id)) # Add dummy tag if needed
                     if person_tags.get(p2): # Only proceed if p2 has a tag
                        tag_id = random.choice(list(person_tags[p2])) if person_tags[p2] else 0 # Pick existing tag or default
                        cmd = f"att {p1} {p2} {tag_id}"
                        target_exception = "RelationNotFoundException"
            elif choice < 0.8: # TINF
                 p1, p2 = get_existing_relation()
                 if p1 is not None:
                      tag_id = get_non_existent_tag_id(p2, max_tag_id)
                      cmd = f"att {p1} {p2} {tag_id}"
                      target_exception = "TagIdNotFoundException"
            else: # EPI (already in tag)
                owner_id, tag_id = get_random_tag_owner_and_tag(require_non_empty=True)
                if owner_id is not None:
                    member_id = get_random_member_in_tag(owner_id, tag_id)
                    if member_id is not None:
                        cmd = f"att {member_id} {owner_id} {tag_id}"
                        target_exception = "EqualPersonIdException (already in tag)"

        elif cmd_type == "dft": # Target: PINF, TINF, PINF (not in tag)
            choice = random.random()
            if choice < 0.25: # PINF (p1 non-existent)
                p1 = get_non_existent_person_id(max_person_id)
                p2, tag_id = get_random_tag_owner_and_tag()
                if p1 is not None and p2 is not None:
                    cmd = f"dft {p1} {p2} {tag_id}"
                    target_exception = "PersonIdNotFoundException (p1)"
            elif choice < 0.5: # PINF (p2 non-existent)
                p1 = get_existing_person_id()
                p2 = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p1 is not None and p2 is not None:
                    cmd = f"dft {p1} {p2} {tag_id}"
                    target_exception = "PersonIdNotFoundException (p2)"
            elif choice < 0.75: # TINF
                owner_id = get_existing_person_id()
                p1 = get_existing_person_id() # Doesn't matter who p1 is here
                if owner_id is not None and p1 is not None:
                    tag_id = get_non_existent_tag_id(owner_id, max_tag_id)
                    cmd = f"dft {p1} {owner_id} {tag_id}"
                    target_exception = "TagIdNotFoundException"
            else: # PINF (p1 not in tag)
                owner_id, tag_id = get_random_tag_owner_and_tag()
                if owner_id is not None:
                    # Find someone NOT in the tag
                    p1 = get_person_not_in_tag(owner_id, tag_id)
                    if p1 is not None:
                        cmd = f"dft {p1} {owner_id} {tag_id}"
                        target_exception = "PersonIdNotFoundException (p1 not in tag)"

        elif cmd_type == "qv": # Target: PINF, RNF
             choice = random.random()
             if choice < 0.5: # PINF
                 p1 = get_existing_person_id()
                 p2 = get_non_existent_person_id(max_person_id)
                 if p1 is not None and p2 is not None:
                     if random.random() < 0.5: p1, p2 = p2, p1
                     cmd = f"qv {p1} {p2}"
                     target_exception = "PersonIdNotFoundException"
             else: # RNF
                 p1, p2 = get_non_existent_relation_pair()
                 if p1 is not None and p2 is not None:
                     cmd = f"qv {p1} {p2}"
                     target_exception = "RelationNotFoundException"

        elif cmd_type == "qci": # Target: PINF
            p1 = get_existing_person_id()
            p2 = get_non_existent_person_id(max_person_id)
            if p1 is not None and p2 is not None:
                if random.random() < 0.5: p1, p2 = p2, p1
                cmd = f"qci {p1} {p2}"
                target_exception = "PersonIdNotFoundException"

        elif cmd_type == "qtav": # Target: PINF, TINF
            choice = random.random()
            if choice < 0.5: # PINF
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None:
                    cmd = f"qtav {p_id} {tag_id}"
                    target_exception = "PersonIdNotFoundException"
            else: # TINF
                p_id = get_existing_person_id()
                if p_id is not None:
                    tag_id = get_non_existent_tag_id(p_id, max_tag_id)
                    cmd = f"qtav {p_id} {tag_id}"
                    target_exception = "TagIdNotFoundException"
        
        elif cmd_type == "qba": # Target: PINF, ANF
            choice = random.random()
            if choice < 0.5: # PINF
                p_id = get_non_existent_person_id(max_person_id)
                if p_id is not None:
                    cmd = f"qba {p_id}"
                    target_exception = "PersonIdNotFoundException"
            else: # ANF (AcquaintanceNotFound)
                p_id = get_person_with_no_acquaintances()
                if p_id is not None:
                    cmd = f"qba {p_id}"
                    target_exception = "AcquaintanceNotFoundException"
                    
    except Exception as e:
        print(f"ERROR during *exception* generation for {cmd_type}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return None # Failed to generate exception command

    # if cmd: print(f"DEBUG: Generated exception command for {target_exception}: {cmd}", file=sys.stderr)
    return cmd


# --- Main Generation Logic ---
def generate_commands(num_commands_target, max_person_id, max_tag_id, max_rel_value, max_mod_value, max_age,
                      rel_id_limit, min_qci, min_qts, min_qtav, min_qba,
                      density, degree_focus, max_degree, tag_focus, max_tag_size, qci_focus,
                      mr_delete_ratio, exception_ratio, force_qba_empty_ratio, force_qtav_empty_ratio,
                      hub_bias, num_hubs,
                      phases_config,
                      hce_active):

    generated_cmds_list = []
    cmd_counts = defaultdict(int)
    current_phase_index = 0
    commands_in_current_phase = 0
    num_commands_to_generate = num_commands_target

    if phases_config:
        num_commands_to_generate = sum(p['count'] for p in phases_config)
        print(f"INFO: Phases defined. Target commands set to {num_commands_to_generate}", file=sys.stderr)


    # --- Initial Population ---
    initial_people = min(num_commands_to_generate // 10 + 5, max_person_id + 1, 100) # Added cap
    # Ensure hubs are created if bias is used
    if hub_bias > 0:
        initial_people = max(initial_people, num_hubs)
        
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
    
    # Define hubs (first num_hubs IDs)
    hub_ids = set(range(num_hubs)) if num_hubs > 0 else set()


    # --- Main Generation Loop ---
    while len(generated_cmds_list) < num_commands_to_generate:
        # Determine current phase and get weights
        current_phase_name = "default"
        if phases_config:
            if current_phase_index >= len(phases_config):
                 print("INFO: All defined phases completed.", file=sys.stderr)
                 break
            current_phase_info = phases_config[current_phase_index]
            current_phase_name = current_phase_info['name']
            if commands_in_current_phase >= current_phase_info['count']:
                current_phase_index += 1
                commands_in_current_phase = 0
                # Check again if we moved past the last phase
                if current_phase_index >= len(phases_config):
                     print("INFO: All defined phases completed after phase transition.", file=sys.stderr)
                     break 
                current_phase_info = phases_config[current_phase_index]
                current_phase_name = current_phase_info['name']

        weights_dict = get_command_weights(current_phase_name, tag_focus)

        # Filter out impossible commands based on state (Simplified)
        if len(persons) < 1: weights_dict = {'ap': 1} # Only allow adding people if none exist
        elif len(persons) < 2: weights_dict.pop("ar", None); weights_dict.pop("mr", None); weights_dict.pop("qv", None); weights_dict.pop("qci", None); weights_dict.pop("att", None); weights_dict.pop("dft", None)
        if not relations: weights_dict.pop("mr", None); # qv/qci might still query non-existent
        if not any(person_tags.values()): weights_dict.pop("dt", None); weights_dict.pop("qtav", None); weights_dict.pop("att", None); weights_dict.pop("dft", None)
        if not any(tag_members.values()): weights_dict.pop("dft", None) # Need members for dft
        # Add more fine-grained filtering if needed

        if not weights_dict:
             print("Warning: No commands possible with current state and weights! Trying to add person.", file=sys.stderr)
             # Try adding a person as a last resort
             person_id = get_non_existent_person_id(max_person_id)
             if person_id <= max_person_id:
                 name = generate_name(person_id)
                 age = random.randint(1, max_age)
                 if add_person_state(person_id, name, age):
                    cmd = f"ap {person_id} {name} {age}"
                    generated_cmds_list.append(cmd)
                    cmd_counts['ap'] += 1
                    if phases_config: commands_in_current_phase += 1
                    continue # Try the main loop again
                 else:
                    print("ERROR: Could not even add a fallback person. Breaking loop.", file=sys.stderr)
                    break # Couldn't add a person
             else:
                 print("ERROR: No more person IDs available. Breaking loop.", file=sys.stderr)
                 break


        # --- Choose Command Type ---
        command_types = sorted(list(weights_dict.keys()))
        weights = [weights_dict[cmd_type] for cmd_type in command_types]
        if sum(weights) <= 0: # Safety check
             print("Warning: Zero total weight for command selection. Trying 'ap'.", file=sys.stderr)
             cmd_type = 'ap' # Fallback
        else:
             cmd_type = random.choices(command_types, weights=weights, k=1)[0]
        
        cmd = None
        generated_successfully = False # Flag to track if a valid command string was generated

        # --- Attempt Exception Generation ---
        if random.random() < exception_ratio:
            cmd = try_generate_exception_command(cmd_type, max_person_id, max_tag_id)
            if cmd:
                generated_successfully = True # Even exceptions count as generated commands
                # State does not change for exceptions
            # else: Exception generation failed, fallback to normal generation below

        # --- Normal Command Generation (or fallback from failed exception gen) ---
        if not generated_successfully:
            try:
                # --- Force Edge Cases ---
                # Note: These find existing states rather than forcing them with extra commands
                force_qba_empty = (cmd_type == "qba" and random.random() < force_qba_empty_ratio)
                force_qtav_empty = (cmd_type == "qtav" and random.random() < force_qtav_empty_ratio)

                # --- Command Generation ---
                if cmd_type == "ap":
                    # Try unused ID first
                    potential_ids = [i for i in range(max_person_id + 1) if i not in persons]
                    if potential_ids:
                         person_id = random.choice(potential_ids)
                    else: # Overwrite only if necessary (or max_person_id is small)
                         person_id = random.randint(0, max_person_id)

                    name = generate_name(person_id)
                    age = random.randint(1, max_age)
                    if add_person_state(person_id, name, age):
                        cmd = f"ap {person_id} {name} {age}"
                        generated_successfully = True

                elif cmd_type == "ar":
                    p1, p2 = None, None
                    # Hub Bias Logic
                    use_hub = (hub_ids and random.random() < hub_bias)
                    if use_hub:
                        hub_id = random.choice(list(hub_ids))
                        # Try to connect hub to a non-hub, or hub to hub
                        non_hub_eligible = sorted(list(get_eligible_persons(rel_id_limit) - hub_ids))
                        if non_hub_eligible and random.random() < 0.8: # Prefer hub-non_hub
                             other_p = random.choice(non_hub_eligible)
                             p1, p2 = hub_id, other_p
                        else: # Connect hub to any other person (could be another hub)
                            p1 = hub_id
                            eligible_others = sorted(list(get_eligible_persons(rel_id_limit) - {p1}))
                            if eligible_others:
                                p2 = random.choice(eligible_others)
                            # else: cannot find partner for hub
                    
                    # If no hub bias or hub connection failed, use random
                    if p1 is None or p2 is None:
                       p1, p2 = get_two_random_persons(id_limit=rel_id_limit)

                    if p1 is not None and p2 is not None:
                        # Density check (same as before)
                        current_nodes = len(persons)
                        max_possible_edges = (current_nodes * (current_nodes - 1)) // 2 if current_nodes > 1 else 0
                        current_density = len(relations) / max_possible_edges if max_possible_edges > 0 else 0
                        prob_add = 0.6 + (density - current_density)
                        prob_add = max(0.05, min(0.95, prob_add))

                        if random.random() < prob_add:
                            value = random.randint(1, max_rel_value)
                            if add_relation_state(p1, p2, value, max_degree):
                                cmd = f"ar {p1} {p2} {value}"
                                generated_successfully = True

                elif cmd_type == "mr":
                    p1, p2 = get_random_relation(id_limit=rel_id_limit)
                    if p1 is not None: # Found a relation to modify
                        rel_key = (p1, p2)
                        current_value = relation_values.get(rel_key, 0)

                        # Decide modification value (m_val)
                        m_val = 0
                        # NOTE: max_mod_value used here is the one passed to the function,
                        # which should be capped by HCE logic *before* calling generate_commands.
                        if current_value > 0 and random.random() < mr_delete_ratio:
                            # Target deletion
                            m_val = -current_value - random.randint(0, 10)
                        else:
                            # Random modification
                            effective_max_mod = max(1, max_mod_value) # Ensure range is valid even if max_mod_value is 0
                            m_val = random.randint(-effective_max_mod, effective_max_mod)
                            if m_val == 0 and max_mod_value != 0: # Avoid zero modification unless necessary
                                m_val = random.choice([-1, 1]) * random.randint(1, effective_max_mod)


                        # --- START OF HCE CLAMPING FOR m_val ---
                        if hce_active:
                            hce_limit = 200
                            original_m_val = m_val # For potential debugging
                            m_val = max(-hce_limit, min(hce_limit, m_val))
                            # Optional: Print if clamping happened
                            # if m_val != original_m_val:
                            #    print(f"DEBUG: HCE Clamped mr m_val from {original_m_val} to {m_val}", file=sys.stderr)
                        # --- END OF HCE CLAMPING FOR m_val ---


                        cmd = f"mr {p1} {p2} {m_val}"
                        generated_successfully = True

                        # State update (remove or modify value) handled AFTER generating command string
                        # IMPORTANT: Use the *potentially clamped* m_val for state update
                        new_value = current_value + m_val
                        if new_value <= 0:
                            remove_relation_state(p1, p2) # Handles degree and tag updates
                        else:
                            relation_values[rel_key] = new_value
                            # Degree doesn't change when only value is modified

                elif cmd_type == "at":
                    person_id = get_random_person()
                    if person_id is not None:
                        tag_id = random.randint(0, max_tag_id)
                        if add_tag_state(person_id, tag_id):
                             cmd = f"at {person_id} {tag_id}"
                             generated_successfully = True

                elif cmd_type == "dt":
                    owner_id, tag_id = get_random_tag_owner_and_tag()
                    if owner_id is not None:
                        if remove_tag_state(owner_id, tag_id):
                            cmd = f"dt {owner_id} {tag_id}"
                            generated_successfully = True

                elif cmd_type == "att":
                     owner_id, tag_id = get_random_tag_owner_and_tag()
                     if owner_id is not None:
                         person_id1 = get_related_person_not_in_tag(owner_id, tag_id)
                         if person_id1 is not None:
                             if add_person_to_tag_state(person_id1, owner_id, tag_id, max_tag_size):
                                cmd = f"att {person_id1} {owner_id} {tag_id}"
                                generated_successfully = True
                             # else: Size limit reached or other precondition failed state update

                elif cmd_type == "dft":
                     owner_id, tag_id = get_random_tag_owner_and_tag(require_non_empty=True) # Ensure tag has members
                     if owner_id is not None:
                         member_id = get_random_member_in_tag(owner_id, tag_id)
                         if member_id is not None:
                             if remove_person_from_tag_state(member_id, owner_id, tag_id):
                                cmd = f"dft {member_id} {owner_id} {tag_id}"
                                generated_successfully = True

                elif cmd_type == "qv":
                    # Prioritize existing relations slightly? (Keep original logic)
                    if random.random() < 0.9 and relations:
                        p1, p2 = get_random_relation()
                    else:
                        p1, p2 = get_two_random_persons()
                    if p1 is not None and p2 is not None:
                        cmd = f"qv {p1} {p2}"
                        generated_successfully = True # Query always generates command string

                elif cmd_type == "qci":
                     # Use qci_focus (Keep original logic)
                     p1, p2 = None, None
                     if qci_focus == 'close' and relations: p1, p2 = get_random_relation()
                     elif qci_focus == 'far':
                          p1_try, p2_try = get_two_random_persons()
                          if p1_try is not None and (min(p1_try,p2_try), max(p1_try,p2_try)) not in relations:
                               p1, p2 = p1_try, p2_try
                          else: # Fallback if first try failed or was related
                               p1_alt, p2_alt = get_two_random_persons()
                               if p1_alt is not None: p1,p2 = p1_alt, p2_alt # Use alt pair even if related
                     else: # mixed or fallback
                          p1, p2 = get_two_random_persons()

                     if p1 is not None and p2 is not None:
                          cmd = f"qci {p1} {p2}"
                          generated_successfully = True # Query always generates command string

                elif cmd_type == "qts":
                     cmd = "qts"
                     generated_successfully = True # Query always generates command string

                elif cmd_type == "qtav":
                    owner_id, tag_id = None, None
                    if force_qtav_empty: # Try to find an empty tag first
                         owner_id, tag_id = get_random_empty_tag()
                         # print(f"DEBUG: qtav force empty found: {owner_id}, {tag_id}", file=sys.stderr)

                    if owner_id is None: # If not forcing or couldn't find empty, get random
                        # Occasionally query non-existent (Keep original logic)
                        if random.random() < 0.15 or not any(person_tags.values()):
                             owner_id = get_random_person()
                             tag_id = random.randint(0, max_tag_id)
                        else:
                             owner_id, tag_id = get_random_tag_owner_and_tag() # Get existing owner/tag
                             if owner_id is not None and random.random() < 0.05: # Small chance for existing owner, non-existent tag
                                  tag_id = get_non_existent_tag_id(owner_id, max_tag_id)

                    if owner_id is not None and tag_id is not None: # Check both exist
                        cmd = f"qtav {owner_id} {tag_id}"
                        generated_successfully = True # Query always generates command string

                elif cmd_type == "qba":
                     person_id = None
                     if force_qba_empty: # Try to find person with degree 0
                         person_id = get_person_with_no_acquaintances()
                         # print(f"DEBUG: qba force empty found: {person_id}", file=sys.stderr)

                     if person_id is None: # If not forcing or couldn't find 0-degree, get random
                         person_id = get_random_person(require_degree_greater_than=0 if random.random() < 0.9 else None) # Usually pick someone with acquaintances

                     if person_id is not None:
                          cmd = f"qba {person_id}"
                          generated_successfully = True # Query always generates command string

            except Exception as e:
                print(f"ERROR during normal generation for {cmd_type}: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                # Continue to next iteration

        # --- Add generated command to list if successful ---
        if generated_successfully and cmd:
            generated_cmds_list.append(cmd)
            cmd_counts[cmd_type] += 1
            if phases_config:
                 commands_in_current_phase += 1
        # else: Command generation failed (e.g., preconditions, state update failed, exception gen failed), loop continues.


    # --- Supplementary loop for minimum query counts ---
    # (Keep original logic, but use updated helper functions)
    min_counts_map = { "qci": min_qci, "qts": min_qts, "qtav": min_qtav, "qba": min_qba }
    for query_type, min_req in min_counts_map.items():
        attempts = 0
        max_attempts = min_req * 5 + 20 # Increased attempts limit slightly

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
                    owner_id, tag_id = get_random_tag_owner_and_tag() # Get any owner/tag
                    if owner_id is None: # Fallback if no tags exist
                        owner_id = get_random_person()
                        if owner_id is not None:
                            tag_id = random.randint(0, max_tag_id) # Query potentially non-existent
                    if owner_id is not None and tag_id is not None:
                         cmd = f"qtav {owner_id} {tag_id}"
                elif query_type == "qba":
                    person_id = get_random_person() # Get any person
                    if person_id is not None: cmd = f"qba {person_id}"

            except Exception as e:
                 print(f"ERROR generating supplementary command {query_type}: {e}", file=sys.stderr)
                 traceback.print_exc(file=sys.stderr)
                 # Don't break, just try next attempt

            if cmd:
                generated_cmds_list.append(cmd)
                cmd_counts[query_type] += 1
            # else: Generation failed for this attempt

        if cmd_counts[query_type] < min_req:
             print(f"Warning: Could not generate {min_req} required '{query_type}' commands after {attempts} attempts. Generated {cmd_counts[query_type]}. State might be prohibitive.", file=sys.stderr)


    return generated_cmds_list, cmd_counts


# --- Argument Parsing ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate test data for HW9 social network with enhanced complexity and testing features.")

    # Core Controls
    parser.add_argument("-n", "--num_commands", type=int, default=2000, help="Target number of commands (ignored if --phases is set).")
    parser.add_argument("--max_person_id", type=int, default=150, help="Maximum person ID (0 to max).")
    parser.add_argument("--max_tag_id", type=int, default=15, help="Maximum tag ID per person (0 to max).")
    # 确保默认值符合规范 (<= 200)
    parser.add_argument("--max_age", type=int, default=200, help="Maximum person age (default 200).")
    parser.add_argument("-o", "--output_file", type=str, default=None, help="Output file name (default: stdout).")
    # HCE flag 现在明确对应互测限制
    parser.add_argument("--hce", action='store_true', help="Enable HCE constraints (apply Mutual Test limits: N<=3000, max_person_id<=99, values<=200).")
    parser.add_argument("--seed", type=int, default=None, help="Seed for the random number generator.")

    # Relation/Value Controls
    # 确保默认值符合规范 (<= 200)
    parser.add_argument("--max_rel_value", type=int, default=200, help="Maximum initial relation value (default 200).")
    parser.add_argument("--max_mod_value", type=int, default=200, help="Maximum absolute modify relation value change (default 200).")
    parser.add_argument("--mr_delete_ratio", type=float, default=0.15, help="Approx. ratio of 'mr' commands targeting relation deletion (0.0-1.0).")

    # Graph Structure Controls
    parser.add_argument("--density", type=float, default=0.05, help="Target graph density (approx. ratio of actual/possible edges, 0.0-1.0). Higher values create denser graphs.")
    parser.add_argument("--degree_focus", choices=['uniform', 'hub'], default='uniform', help="Influence degree distribution ('hub' partially implemented via --hub_bias).") # Kept for potential future expansion
    parser.add_argument("--max_degree", type=int, default=None, help="Attempt to limit the maximum degree of any person.")
    parser.add_argument("--hub_bias", type=float, default=0.0, help="Probability (0.0-1.0) for 'ar' to connect to a designated hub node instead of random.")
    parser.add_argument("--num_hubs", type=int, default=5, help="Number of initial person IDs (0 to N-1) to treat as potential hubs when --hub_bias > 0.")
    # parser.add_argument("--rel_id_limit", type=int, default=None, help="Limit ar/mr commands to IDs < LIMIT. (Potentially redundant)") # Commented out based on previous discussion

    # Tag Controls
    parser.add_argument("--tag_focus", type=float, default=0.3, help="Approx. ratio of total commands related to tags (0.0-1.0).")
    parser.add_argument("--max_tag_size", type=int, default=50, help="Attempt to limit the max number of persons in a tag (up to JML limit of 1000).")

    # Query & Exception Controls
    parser.add_argument("--qci_focus", choices=['mixed', 'close', 'far'], default='mixed', help="Influence the type of pairs queried by 'qci'.")
    parser.add_argument("--min_qci", type=int, default=10, help="Minimum number of qci commands.")
    parser.add_argument("--min_qts", type=int, default=5, help="Minimum number of qts commands.")
    parser.add_argument("--min_qtav", type=int, default=10, help="Minimum number of qtav commands.")
    parser.add_argument("--min_qba", type=int, default=5, help="Minimum number of qba commands.")
    parser.add_argument("--exception_ratio", type=float, default=0.05, help="Probability (0.0-1.0) to attempt generating a command that triggers an exception.")
    parser.add_argument("--force_qba_empty_ratio", type=float, default=0.02, help="Probability (0.0-1.0) to try generating 'qba' for a person with no acquaintances.")
    parser.add_argument("--force_qtav_empty_ratio", type=float, default=0.02, help="Probability (0.0-1.0) to try generating 'qtav' for an empty tag.")


    # Generation Flow Control
    parser.add_argument("--phases", type=str, default=None, help="Define generation phases, e.g., 'build:500,query:1000,churn:500'. Overrides -n.")

    args = parser.parse_args()

    # --- Apply Seed ---
    if args.seed is not None:
        print(f"INFO: Using random seed: {args.seed}", file=sys.stderr)
        random.seed(args.seed)
    else:
        seed_val = random.randrange(sys.maxsize)
        print(f"INFO: No seed provided, using generated seed: {seed_val}", file=sys.stderr)
        random.seed(seed_val)


    # --- Apply HCE Constraints ---
    if args.hce:
        print("INFO: HCE mode enabled. Applying Mutual Test limits...", file=sys.stderr)
        hce_max_n = 3000
        hce_max_pid = 99
        # 强制限制指令数
        if args.phases:
            try:
                _, total_phase_commands = parse_phases(args.phases)
                if total_phase_commands > hce_max_n:
                    print(f"  Phase command total ({total_phase_commands}) exceeds HCE limit ({hce_max_n}). Capping total generated commands.", file=sys.stderr)
                    # 直接限制总生成数，而不是修改 phase 配置
                    args.num_commands = hce_max_n
                else:
                    args.num_commands = total_phase_commands # 正常使用 phase 总数
            except ValueError:
                 # 错误处理已在下面 validate phases 部分完成
                 pass # parse_phases will raise error later if invalid
        else:
            if args.num_commands > hce_max_n:
                print(f"  num_commands capped from {args.num_commands} to {hce_max_n}", file=sys.stderr)
                args.num_commands = hce_max_n

        # 强制限制 max_person_id
        if args.max_person_id > hce_max_pid:
            print(f"  max_person_id capped from {args.max_person_id} to {hce_max_pid}", file=sys.stderr)
            args.max_person_id = hce_max_pid

        # 强制限制其他数值参数
        hce_max_value = 200
        if args.max_age > hce_max_value:
            print(f"  max_age capped from {args.max_age} to {hce_max_value}", file=sys.stderr)
            args.max_age = hce_max_value
        if args.max_rel_value > hce_max_value:
            print(f"  max_rel_value capped from {args.max_rel_value} to {hce_max_value}", file=sys.stderr)
            args.max_rel_value = hce_max_value
        if args.max_mod_value > hce_max_value:
             print(f"  max_mod_value capped from {args.max_mod_value} to {hce_max_value}", file=sys.stderr)
             args.max_mod_value = hce_max_value
        if abs(args.max_mod_value) > hce_max_value: # Also check negative if relevant (it's not currently for this param)
             pass # Not needed as it's checked against positive cap

    # --- Validate Phases ---
    phases_config = None
    if args.phases:
        try:
            phases_config, total_phase_commands = parse_phases(args.phases)
            # 如果 HCE 生效，num_commands 已被上面的逻辑覆盖/限制
            if not args.hce: # 如果不是 HCE，则使用 phase 总数
                 args.num_commands = total_phase_commands
        except ValueError as e:
            print(f"ERROR: Invalid --phases argument: {e}", file=sys.stderr)
            sys.exit(1)

    # Validate hub params
    if args.hub_bias > 0 and args.num_hubs <= 0:
        print("ERROR: --num_hubs must be positive when --hub_bias is used.", file=sys.stderr)
        sys.exit(1)
    if args.num_hubs > args.max_person_id + 1:
        print(f"WARNING: --num_hubs ({args.num_hubs}) is larger than max_person_id+1 ({args.max_person_id+1}). Effective hubs limited.", file=sys.stderr)
        args.num_hubs = args.max_person_id + 1


    # --- Prepare Output ---
    output_stream = open(args.output_file, 'w') if args.output_file else sys.stdout

    # --- Generate and Output ---
    try:
        # Clear global state
        persons.clear(); relations.clear(); relation_values.clear()
        person_tags.clear(); tag_members.clear(); person_details.clear()
        person_degrees.clear()

        # 注意: generate_commands 函数内部现在使用 args.num_commands 作为循环上限
        # 这个值可能被 HCE 或 --phases 逻辑修改过
        all_commands, final_cmd_counts = generate_commands(
            args.num_commands, args.max_person_id, args.max_tag_id,
            args.max_rel_value, args.max_mod_value, args.max_age,
            None, # rel_id_limit removed
            args.min_qci, args.min_qts, args.min_qtav, args.min_qba,
            args.density, args.degree_focus, args.max_degree,
            args.tag_focus, args.max_tag_size, args.qci_focus,
            args.mr_delete_ratio, args.exception_ratio,
            args.force_qba_empty_ratio, args.force_qtav_empty_ratio,
            args.hub_bias, args.num_hubs,
            phases_config,
            args.hce # <--- 传递 HCE 状态
        )

        # Print all generated commands
        for command in all_commands:
             output_stream.write(command + '\n')

        # Print summary to stderr
        final_command_count = len(all_commands)
        print(f"\n--- Generation Summary ---", file=sys.stderr)
        print(f"Target commands: {args.num_commands} (from -n or --phases)", file=sys.stderr)
        print(f"Actual commands generated: {final_command_count}", file=sys.stderr)
        print(f"Final State: {len(persons)} persons, {len(relations)} relations.", file=sys.stderr)
        total_tags = sum(len(tags) for tags in person_tags.values())
        total_tag_members = sum(len(mems) for mems in tag_members.values())
        print(f"           {total_tags} tags defined, {total_tag_members} total tag memberships.", file=sys.stderr)

        print(f"Command Counts:", file=sys.stderr)
        for cmd_type, count in sorted(final_cmd_counts.items()):
            print(f"  {cmd_type}: {count}", file=sys.stderr)
            
        exception_triggers = sum(final_cmd_counts.get(f"{cmd}_exc", 0) for cmd in final_cmd_counts) # Heuristic count
        print(f"  (Estimated exception trigger attempts based on cmd count might be inaccurate)", file=sys.stderr)

        if args.output_file:
             print(f"Output written to: {args.output_file}", file=sys.stderr)
        else:
             print(f"Output printed to stdout.", file=sys.stderr)


    finally:
        if args.output_file and output_stream is not sys.stdout:
            output_stream.close()

# --- END OF FILE gen.py ---