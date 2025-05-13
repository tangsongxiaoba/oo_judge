# --- START OF FULL MODIFIED FILE gen.py ---

import random
import argparse
import os
import sys
import math
from contextlib import redirect_stdout
from collections import defaultdict, deque # deque for BFS
import traceback # For debugging exceptions during generation
import json
# --- State Tracking ---
# HW9 State
persons = set() # {person_id, ...}
relations = set() # {(person_id1, person_id2), ...} where id1 < id2
relation_values = {} # {(person_id1, person_id2): value, ...} where id1 < id2
person_tags = defaultdict(set) # {person_id: {tag_id1, tag_id2, ...}, ...}
tag_members = defaultdict(lambda: set()) # {(owner_person_id, tag_id): {member_person_id1, ...}, ...}
person_details = {} # {person_id: {'name': name, 'age': age}, ...}
person_degrees = defaultdict(int) # {person_id: degree, ...}
# OPTIMIZATION: Adjacency list for faster neighbor lookups
person_neighbors = defaultdict(set) # {person_id: {neighbor1_id, neighbor2_id, ...}, ...}

# HW10 State
official_accounts = set() # {account_id, ...}
account_details = {} # {account_id: {'owner': person_id, 'name': name}, ...}
account_followers = defaultdict(set) # {account_id: {follower_person_id1, ...}, ...}
account_articles = defaultdict(set) # {account_id: {article_id1, ...}, ...}
account_contributions = defaultdict(lambda: defaultdict(int)) # {account_id: {person_id: count, ...}, ...}

all_articles = set() # {article_id, ...} Global set of all existing article IDs
article_contributors = {} # {article_id: contributor_person_id, ...}
article_locations = {} # {article_id: account_id, ...} Which account an article is *currently* in
article_names = {} # {article_id: name, ...}
person_received_articles = defaultdict(list) # {person_id: [article_id1, article_id2, ...], ...} In order received (newest first)

# HW11 State
messages = {} # {message_id: {'id': mid, 'type': 0/1, 'p1': pid1, 'p2': pid2/None, 'tag': tid/None, 'sv': social_val, 'kind': 'msg'/'emoji'/'rem'/'fwd', 'extra': emojiId/money/articleId}, ...}
emoji_ids = set() # {emoji_id1, ...}
emoji_heat = defaultdict(int) # {emoji_id: heat_count}
person_money = defaultdict(int) # {person_id: money}
person_social_value = defaultdict(int) # {person_id: social_value}
person_received_messages = defaultdict(list) # {person_id: [message_id1, message_id2, ...]} (newest first)


BASE_WEIGHTS = {
        # HW9 Basics
        "ap": 10, "ar": 8, "mr": 8,
        # HW9 Tags
        "at": 6, "dt": 2, "att": 6, "dft": 3,
        # HW9 Queries
        "qv": 3, "qci": 3, "qts": 2, "qtav": 8, "qtvs": 8, "qba": 3, "qcs": 2, "qsp": 3,
        # HW10 Accounts/Articles
        "coa": 5, "doa": 1, "ca": 5, "da": 5, "foa": 6,
        # HW10 Queries
        "qbc": 3, "qra": 4,
        # HW11
        "am": 1, "aem": 4, "arem": 3, "afm": 3, # Add messages
        "sm": 10, # Send messages frequently
        "sei": 3, # Store emojis
        "dce": 1, # Delete cold emojis (less frequent)
        "qsv": 5, "qrm": 5, "qp": 4, "qm": 5, # Queries
    }

# --- Global Phase Definitions (will be loaded from JSON) ---
LOADED_PHASE_DEFINITIONS = {}

# --- Helper Functions (Optimized where possible) ---

def generate_name(base_id, prefix="Name"):
    """Generates a name (for Person or Account) ensuring length <= 100."""
    base_name = f"{prefix}_{base_id}"
    if len(base_name) > 100:
        return f"{prefix[0]}_{base_id}"[:100]
    return base_name

# --- Person Helpers ---
def get_eligible_persons(id_limit=None, require_degree_greater_than=None):
    eligible = persons.copy()
    if id_limit is not None:
        eligible = {p for p in eligible if p < id_limit}
    if require_degree_greater_than is not None:
        eligible = {p for p in eligible if person_degrees.get(p, 0) > require_degree_greater_than}
    return eligible

def get_random_person(id_limit=None, require_degree_greater_than=None):
    eligible = get_eligible_persons(id_limit, require_degree_greater_than)
    return random.choice(list(eligible)) if eligible else None

def get_existing_person_id():
    return get_random_person()

def get_non_existent_person_id(max_person_id):
    if not persons: return random.randint(0, max_person_id)
    attempts = 0
    max_attempts = max(len(persons) * 2, 20)
    max_possible_id_in_state = max(list(persons)) if persons else -1
    search_range_max = max(max_person_id + 10, max_possible_id_in_state + 10)

    while attempts < max_attempts:
        if random.random() < 0.7 and max_possible_id_in_state >=0 :
            pid = random.randint(max(0, max_possible_id_in_state - 5), max_possible_id_in_state + 10)
        else:
            pid = random.randint(0, search_range_max)

        if pid > max_person_id:
            pid = random.randint(0, max_person_id)

        if pid >= 0 and pid not in persons:
            return pid
        attempts += 1

    # Fallback linear scan if random attempts fail
    for i in range(max_person_id + 1):
        if i not in persons:
            return i
    # If all IDs up to max_person_id are taken, but state has gaps after max_person_id
    if max_possible_id_in_state < max_person_id:
        # Check if there's space immediately after the highest ID in state
        potential_id = max_possible_id_in_state + 1
        if potential_id <= max_person_id:
             return potential_id # Should have been found by linear scan, but double check

    # If truly all spots up to max_person_id are filled
    # Or if the only available IDs are > max_person_id
    return -1 # Indicate failure to find a valid non-existent ID within the limit

def get_two_random_persons(id_limit=None, require_different=True):
    eligible = get_eligible_persons(id_limit)

    if not eligible:
        return None, None

    if not require_different:
        eligible_list = list(eligible)
        if not eligible_list: return None, None
        p1 = random.choice(eligible_list)
        p2 = random.choice(eligible_list)
        return p1, p2

    if len(eligible) < 2:
        return None, None

    p1, p2 = random.sample(list(eligible), 2)
    return p1, p2

# --- Relation Helpers ---
def get_eligible_relations(id_limit=None):
    eligible = relations
    if id_limit is not None:
        eligible = {(p1, p2) for p1, p2 in relations if p1 < id_limit and p2 < id_limit}
    return eligible

def get_random_relation(id_limit=None):
    if not relations: return None, None
    if id_limit is None:
        relation_list = list(relations)
        return random.choice(relation_list) if relation_list else (None, None)
    else:
        eligible_keys = [(p1, p2) for p1, p2 in relations if p1 < id_limit and p2 < id_limit]
        return random.choice(eligible_keys) if eligible_keys else (None, None)

def get_existing_relation():
    p1, p2 = get_random_relation()
    # Return in original order potentially, not just min/max
    if p1 is not None and p2 is not None:
        if random.random() < 0.5:
            return p1, p2
        else:
            return p2, p1
    return None, None


def get_non_existent_relation_pair(approx_mode=False): # Added approx_mode
    num_persons_val = len(persons)
    if num_persons_val < 2:
        return None, None

    max_possible_edges_val = (num_persons_val * (num_persons_val - 1)) // 2
    current_num_relations = len(relations)

    # Handle edge case where graph is already a clique
    if current_num_relations >= max_possible_edges_val:
        return None, None

    is_very_dense = False
    current_density_val = 0.0
    if max_possible_edges_val > 0:
        current_density_val = current_num_relations / max_possible_edges_val
        if current_density_val > 0.9:
            is_very_dense = True

    person_list_val = list(persons)
    max_attempts_val = max(num_persons_val * 2, 50) # Adjusted base attempts slightly

    # Reduce attempts in approx mode for very dense graphs
    if approx_mode and is_very_dense:
        max_attempts_val = min(max_attempts_val, num_persons_val // 3 + 10, 25)

    # Random Sampling
    for _ in range(max_attempts_val):
        if len(person_list_val) < 2: break # Should not happen if num_persons_val >=2
        p1, p2 = random.sample(person_list_val, 2)
        # Check using optimized neighbor lookup
        if p2 not in person_neighbors.get(p1, set()):
            return p1, p2

    # Fallback Scan (skip if approx mode and very dense)
    if approx_mode and is_very_dense:
        # print(f"DEBUG:[approx] Skipping fallback scan for non-existent relation (density: {current_density_val:.2f})", file=sys.stderr)
        return None, None # Give up finding one quickly

    # Limited scan even in non-approx mode if dense, full scan if sparse
    scan_limit_p1 = num_persons_val # Scan all if sparse
    scan_limit_p2 = num_persons_val
    if current_density_val > 0.7: # Reduce scan if somewhat dense
        scan_limit_p1 = min(num_persons_val, 20)
        scan_limit_p2 = min(num_persons_val -1 if num_persons_val > 0 else 0 , 20)

    if num_persons_val >= 2:
        cand_p1_list_val = random.sample(person_list_val, min(num_persons_val, scan_limit_p1))

        for p1_scan in cand_p1_list_val:
            # Check neighbors of p1_scan
            p1_neighbors = person_neighbors.get(p1_scan, set())
            # Find potential p2 candidates (not p1 and not already neighbors)
            potential_p2s = [p for p in person_list_val if p != p1_scan and p not in p1_neighbors]

            if not potential_p2s: continue # p1 is connected to everyone else

            # Sample from potential_p2s
            num_to_check = min(len(potential_p2s), scan_limit_p2)
            for p2_scan in random.sample(potential_p2s, num_to_check):
                 # Double check (should be redundant due to how potential_p2s was built)
                 if p2_scan not in person_neighbors.get(p1_scan, set()):
                     return p1_scan, p2_scan

    # Should be rare to reach here unless graph is a clique (which is checked earlier)
    # print(f"Warning: Failed to find non-existent relation pair after scan (density: {current_density_val:.2f})", file=sys.stderr)
    return None, None

# --- Path/Circle Helpers (Using optimized BFS) ---
def check_path_exists(start_node, end_node):
    """Checks if a path exists between start_node and end_node using BFS."""
    if start_node == end_node: return True
    # Ensure both nodes are currently valid persons
    if start_node not in persons or end_node not in persons: return False

    q = deque([start_node])
    visited = {start_node}
    while q:
        curr = q.popleft()
        if curr == end_node:
            return True
        # Use the optimized neighbor lookup
        neighbors_of_curr = person_neighbors.get(curr, set())
        for neighbor in neighbors_of_curr:
            # Ensure neighbor is also a valid person before proceeding
            if neighbor in persons and neighbor not in visited:
                visited.add(neighbor)
                q.append(neighbor)
    return False

def get_pair_with_path(): # approx_mode not relevant here as we *want* a path
    num_persons_val = len(persons)
    if num_persons_val < 2 or not relations: return None, None # Need at least 2 people and 1 relation

    attempts = 0
    # Increase max attempts slightly, especially for larger graphs
    max_attempts = max(num_persons_val * 2, 50)
    person_list_val = list(persons)

    while attempts < max_attempts:
        attempts += 1
        # Strategy 1: Pick an existing edge (guaranteed path of length 1)
        if relations and random.random() < 0.6: # Higher chance to pick existing edge
            p1_rel, p2_rel = get_existing_relation() # This gets an existing (p1,p2) or (p2,p1)
            if p1_rel is not None and p2_rel is not None: return p1_rel, p2_rel

        # Strategy 2: Pick two random people and check path
        if len(person_list_val) >= 2:
            p1, p2 = get_two_random_persons(require_different=True)
            if p1 is not None and p2 is not None:
                 if check_path_exists(p1, p2): # Use BFS check
                    return p1, p2

    # Fallback: If random checks fail, explicitly return an existing relation pair
    p1_f, p2_f = get_existing_relation()
    if p1_f is not None and p2_f is not None:
        # print(f"DEBUG: get_pair_with_path fallback to existing relation {p1_f}-{p2_f}", file=sys.stderr)
        return p1_f, p2_f

    # Final desperate fallback (should be rare if relations exist)
    p1_ff, p2_ff = get_two_random_persons(require_different=True)
    # print(f"DEBUG: get_pair_with_path final fallback to random pair {p1_ff}-{p2_ff}", file=sys.stderr)
    return p1_ff, p2_ff


def get_pair_without_path(approx_mode=False): # Added approx_mode
     num_persons_val = len(persons)
     if num_persons_val < 2:
         return None, None

     current_max_possible_edges = (num_persons_val * (num_persons_val - 1)) // 2 if num_persons_val > 1 else 0
     current_num_relations_val = len(relations)
     current_density_val = 0.0
     if current_max_possible_edges > 0 :
         current_density_val = current_num_relations_val / current_max_possible_edges

     is_very_dense = current_density_val > 0.9

     # --- Approximation for very dense graphs ---
     if approx_mode and is_very_dense:
        # print(f"DEBUG:[approx] get_pair_without_path (density: {current_density_val:.2f}).", file=sys.stderr)
        # In approx mode for dense graphs, assume any non-existent relation means no path.
        p1_ner, p2_ner = get_non_existent_relation_pair(approx_mode=True)
        if p1_ner is not None and p2_ner is not None:
            # print(f"DEBUG:[approx] returning non-existent relation {p1_ner}-{p2_ner}, assuming no path.", file=sys.stderr)
            return p1_ner, p2_ner
        else:
            # If we can't even find a non-existent pair, graph is likely a clique.
            # print(f"DEBUG:[approx] no non-existent relation found, assuming clique, no pair without path.", file=sys.stderr)
            return None, None # No pair without path exists if it's a clique

     # --- Original logic for non-approx mode or not very_dense ---
     # Determine max attempts for BFS based on density
     max_bfs_attempts = num_persons_val # Default: check up to N pairs
     if current_density_val > 0.85 and num_persons_val > 50:
         max_bfs_attempts = max(10, int(num_persons_val * 0.1)) # Fewer checks if very dense
     elif current_density_val > 0.7:
         max_bfs_attempts = max(15, int(num_persons_val * 0.5)) # Moderate checks if dense

     person_list_val = list(persons)

     # Strategy 1: Check non-existent relation pairs first (more likely to lack path)
     # Limit the number of non-existent pairs we check to avoid slowdown
     non_relation_checks = min(5, max_bfs_attempts // 2 + 1)
     for _ in range(non_relation_checks):
         p1_ner, p2_ner = get_non_existent_relation_pair(approx_mode=False) # Not approx here
         if p1_ner is not None and p2_ner is not None:
             if not check_path_exists(p1_ner, p2_ner):
                 return p1_ner, p2_ner
         elif num_persons_val > 1 and current_num_relations_val >= current_max_possible_edges:
            # If get_non_existent_relation_pair returns None and graph is full, it's a clique
            # print(f"DEBUG: Graph likely clique ({current_num_relations_val}/{current_max_possible_edges}). Aborting get_pair_without_path.", file=sys.stderr)
            return None, None # Clique -> no pair without path

     # Strategy 2: Random pairs + BFS check
     for _ in range(max_bfs_attempts):
         if len(person_list_val) < 2: break
         # Select two *different* existing persons
         p1, p2 = get_two_random_persons(require_different=True)
         if p1 is None or p2 is None: continue # Should not happen if len >= 2

         if not check_path_exists(p1, p2):
             return p1, p2

     # --- Fallbacks if strategies above fail ---
     # print(f"Warning: Fallback in get_pair_without_path after {max_bfs_attempts} BFS attempts (density: {current_density_val:.2f}, approx: {approx_mode}).", file=sys.stderr)

     # Fallback 1: Try one last time to get a non-existent relation pair (might exist even if initial checks failed)
     p1_f, p2_f = get_non_existent_relation_pair(approx_mode=False)
     if p1_f is not None and p2_f is not None:
         # Optionally double-check path, but it's a fallback, so maybe just return it
         # if not check_path_exists(p1_f, p2_f): return p1_f, p2_f
         return p1_f, p2_f # Return the non-relation pair found

     # Fallback 2: If graph is a clique (checked earlier), we should have returned None.
     # If it's not a clique, but we failed to find a pair without path (e.g., small graph, unlucky sampling)
     # return a random pair, hoping for the best (least preferred option).
     if num_persons_val >= 2:
        p1_final, p2_final = get_two_random_persons(require_different=True)
        if p1_final is not None and p2_final is not None:
            # print(f"DEBUG: get_pair_without_path final desperate fallback, returning random pair {p1_final}-{p2_final}", file=sys.stderr)
            return p1_final, p2_final

     # Absolute failure
     # print(f"DEBUG: get_pair_without_path truly failed to find any pair.", file=sys.stderr)
     return None, None


# --- Tag Helpers ---
def get_random_tag_owner_and_tag(owner_id_limit=None, require_non_empty=False):
    """Finds a random (owner_id, tag_id) pair, optionally requiring the tag to have members."""
    eligible_owners = get_eligible_persons(owner_id_limit)
    owners_with_tags = []
    for pid in eligible_owners:
        tags_for_pid = person_tags.get(pid)
        if tags_for_pid:
            for tag_id in tags_for_pid:
                 tag_key = (pid, tag_id)
                 # Check if tag is required to be non-empty
                 if not require_non_empty or tag_members.get(tag_key):
                     # Ensure members, if required, actually exist in the persons set
                     if require_non_empty:
                         members = tag_members.get(tag_key, set())
                         if members.intersection(persons): # Check if any valid members exist
                            owners_with_tags.append((pid, tag_id))
                     else:
                         owners_with_tags.append((pid, tag_id))

    if not owners_with_tags: return None, None
    owner_id, tag_id = random.choice(owners_with_tags)
    return owner_id, tag_id

def get_non_existent_tag_id(person_id, max_tag_id):
     """Gets a tag ID that the given person_id does *not* currently own."""
     # If person doesn't exist, any ID is non-existent *for them*
     if person_id not in persons: return random.randint(0, max_tag_id)

     existing_tags = person_tags.get(person_id, set())
     # Optimization: If person has almost all possible tags, finding non-existent is hard
     if len(existing_tags) > max_tag_id * 0.95 :
         # Linear scan is faster in this case
         for i in range(max_tag_id + 1):
             if i not in existing_tags:
                 return i
         # If all tags up to max_tag_id are taken, return one slightly above
         return max_tag_id + random.randint(1,5) # Allow exceeding max slightly

     # Random sampling approach for sparser cases
     attempts = 0
     max_attempts = max(len(existing_tags) * 2, 20)
     search_range_max = max_tag_id + 10 # Search slightly above max_tag_id too
     while attempts < max_attempts:
          tag_id = random.randint(0, search_range_max)
          # Ensure generated tag_id doesn't exceed the *absolute* max allowed by parameter
          if tag_id > max_tag_id : tag_id = random.randint(0, max_tag_id)

          if tag_id not in existing_tags:
               return tag_id
          attempts += 1

     # Fallback linear scan if random sampling fails
     for i in range(max_tag_id + 1):
         if i not in existing_tags:
             return i

     # If all else fails (e.g., all tags 0..max_tag_id are used)
     return max_tag_id + random.randint(1,5) # Return an ID outside the usual range

def get_random_member_in_tag(owner_id, tag_id):
    """Gets a random person_id who is a member of the specified tag and still exists."""
    tag_key = (owner_id, tag_id)
    members = tag_members.get(tag_key, set())
    # Filter members to only include those currently in the global 'persons' set
    valid_members = list(members.intersection(persons))
    return random.choice(valid_members) if valid_members else None

def get_related_person_not_in_tag(owner_id, tag_id):
    """Finds a person related to owner_id (neighbor) who is not in the tag and exists."""
    # Ensure owner exists and has neighbors
    if owner_id is None or owner_id not in person_neighbors: return None
    # Ensure tag exists for the owner (or at least the key exists)
    tag_key = (owner_id, tag_id)
    # This check isn't strictly necessary if tag_members handles non-existent keys, but safer
    # if tag_id not in person_tags.get(owner_id, set()): return None # Might uncomment if needed

    related_persons = person_neighbors.get(owner_id, set())
    current_members = tag_members.get(tag_key, set())

    # Find persons who are:
    # 1. Neighbors of the owner
    # 2. Not the owner themselves
    # 3. Not already members of the tag
    # 4. Still exist in the global 'persons' set
    possible_members = list((related_persons - {owner_id} - current_members).intersection(persons))
    return random.choice(possible_members) if possible_members else None

def get_person_not_in_tag(owner_id, tag_id):
    """Finds a person (any person) who is not the owner and not in the tag."""
    # Ensure owner and tag are valid inputs (optional, depends on caller)
    if owner_id is None or tag_id is None: return None

    tag_key = (owner_id, tag_id)
    current_members = tag_members.get(tag_key, set())
    # Find persons who are:
    # 1. In the global 'persons' set
    # 2. Not the owner
    # 3. Not already members of the tag
    non_members = list(persons - current_members - {owner_id})
    return random.choice(non_members) if non_members else None

def get_random_empty_tag():
    """Finds a random (owner, tag) pair where the tag currently has no valid members."""
    empty_tags = []
    for (owner_id, tag_id), members in tag_members.items():
         # Ensure the owner still exists and the tag is still registered to them
         if owner_id in persons and tag_id in person_tags.get(owner_id, set()):
             # Check if the intersection of members and existing persons is empty
             if not members.intersection(persons):
                 empty_tags.append((owner_id, tag_id))
    return random.choice(empty_tags) if empty_tags else (None, None)

def get_person_with_no_acquaintances():
     """Finds a random person with a current degree of 0."""
     zero_degree_persons = [pid for pid in persons if person_degrees.get(pid, 0) == 0]
     return random.choice(zero_degree_persons) if zero_degree_persons else None

# --- HW10 Account/Article Helpers ---
def get_random_account_id():
    """Gets a random account ID that is currently official and exists."""
    # Ensure we only pick from accounts that are both in official_accounts and have details
    valid_accounts = list(official_accounts.intersection(account_details.keys()))
    return random.choice(valid_accounts) if valid_accounts else None

def get_non_existent_account_id(max_account_id):
    """Gets an account ID that is not currently in official_accounts."""
    if not official_accounts: return random.randint(0, max_account_id)

    attempts = 0
    max_attempts = max(len(official_accounts) * 2, 20)
    max_possible_id_in_state = max(list(official_accounts)) if official_accounts else -1
    search_range_max = max(max_account_id + 10, max_possible_id_in_state + 10)

    while attempts < max_attempts:
        # Prioritize searching near the max existing ID
        if random.random() < 0.7 and max_possible_id_in_state >= 0:
             aid = random.randint(max(0, max_possible_id_in_state - 5), max_possible_id_in_state + 10)
        else:
             aid = random.randint(0, search_range_max)

        # Clamp to the max_account_id limit
        if aid > max_account_id: aid = random.randint(0, max_account_id)

        if aid >= 0 and aid not in official_accounts:
            return aid
        attempts += 1

    # Fallback linear scan
    for i in range(max_account_id + 1):
        if i not in official_accounts:
            return i

    # If all IDs up to max_account_id are taken
    if max_possible_id_in_state < max_account_id:
        potential_id = max_possible_id_in_state + 1
        if potential_id <= max_account_id:
            return potential_id

    # Indicate failure
    return -1

def get_account_owner(account_id):
    """Gets the owner_id of a given account_id, or None if not found."""
    return account_details.get(account_id, {}).get('owner')

def get_random_follower(account_id):
    """Gets a random person_id who follows the account and still exists."""
    followers = account_followers.get(account_id, set())
    # Filter followers to only include those currently in the global 'persons' set
    valid_followers = list(followers.intersection(persons))
    return random.choice(valid_followers) if valid_followers else None

def get_person_not_following(account_id):
    """Gets a random person_id who exists but does not follow the account."""
    if account_id not in official_accounts: return get_existing_person_id() # Or None? Depends on intent.
    followers = account_followers.get(account_id, set())
    # Find persons who are in the global set but not in the followers set
    non_followers = list(persons - followers)
    return random.choice(non_followers) if non_followers else None

def get_random_account_with_followers():
     """Gets a random account ID that has at least one valid follower."""
     accounts_with_followers = [
         acc_id for acc_id in official_accounts
         if account_followers.get(acc_id, set()).intersection(persons) # Check for *valid* followers
     ]
     return random.choice(accounts_with_followers) if accounts_with_followers else None

def get_random_account_and_follower():
    """Gets a random (account_id, follower_id) pair where follower is valid."""
    acc_id = get_random_account_with_followers()
    if acc_id:
        follower_id = get_random_follower(acc_id)
        # get_random_follower already ensures the follower exists in persons set
        if follower_id is not None:
            return acc_id, follower_id
    return None, None

def get_random_article_id():
    """Gets a random article ID that exists globally and has a contributor."""
    # Ensure we only pick from articles that are in all_articles AND have contributor info
    valid_articles = list(all_articles.intersection(article_contributors.keys()))
    return random.choice(valid_articles) if valid_articles else None

def get_non_existent_article_id(max_article_id):
    """Gets an article ID that is not currently in all_articles."""
    if not all_articles: return random.randint(0, max_article_id)

    attempts = 0
    max_attempts = max(len(all_articles) * 2, 20)
    max_possible_id_in_state = max(list(all_articles)) if all_articles else -1
    search_range_max = max(max_article_id + 10, max_possible_id_in_state + 10)

    while attempts < max_attempts:
        if random.random() < 0.7 and max_possible_id_in_state >= 0:
            art_id = random.randint(max(0, max_possible_id_in_state - 5), max_possible_id_in_state + 10)
        else:
            art_id = random.randint(0, search_range_max)

        if art_id > max_article_id: art_id = random.randint(0, max_article_id)

        if art_id >= 0 and art_id not in all_articles:
            return art_id
        attempts += 1

    # Fallback linear scan
    for i in range(max_article_id + 1):
        if i not in all_articles:
            return i

    if max_possible_id_in_state < max_article_id:
         potential_id = max_possible_id_in_state + 1
         if potential_id <= max_article_id:
              return potential_id
    return -1 # Indicate failure

def get_random_article_in_account(account_id):
    """Gets a random article ID currently located in the specified account and exists globally."""
    articles_in_acc = account_articles.get(account_id, set())
    # Filter to articles that are both in the account's list AND the global 'all_articles' set
    valid_articles = list(articles_in_acc.intersection(all_articles))
    return random.choice(valid_articles) if valid_articles else None

def get_random_account_with_articles():
    """Gets a random account ID that contains at least one valid article."""
    acc_with_articles = [
        acc_id for acc_id in official_accounts
        if account_articles.get(acc_id, set()).intersection(all_articles) # Check for *valid* articles
    ]
    return random.choice(acc_with_articles) if acc_with_articles else None

def get_random_account_and_article():
    """Gets a random (account_id, article_id) pair where the article is valid and in the account."""
    acc_id = get_random_account_with_articles()
    if acc_id:
        article_id = get_random_article_in_account(acc_id)
        # get_random_article_in_account ensures the article exists globally
        if article_id is not None:
            return acc_id, article_id
    return None, None

def get_contributor_of_article(article_id):
     """Gets the contributor_id of a given article_id, or None."""
     return article_contributors.get(article_id)

def get_account_of_article(article_id):
    """Gets the account_id where the article is currently located, or None."""
    return article_locations.get(article_id)

def get_random_article_received_by(person_id):
    """Gets a random article ID known to be received by the person."""
    received = person_received_articles.get(person_id, [])
    # Ensure the articles still exist globally before choosing one
    valid_received = [art_id for art_id in received if art_id in all_articles]
    return random.choice(valid_received) if valid_received else None


# --- HW11 Message/Emoji Helpers ---
def get_random_message_id():
    """Gets a random message ID from the pending messages."""
    return random.choice(list(messages.keys())) if messages else None

def get_non_existent_message_id(max_message_id):
    """Gets a message ID that is not currently in the pending messages dictionary."""
    if not messages: return random.randint(0, max_message_id)

    attempts = 0
    max_attempts = max(len(messages) * 2, 20)
    max_possible_id_in_state = max(list(messages.keys())) if messages else -1
    search_range_max = max(max_message_id + 10, max_possible_id_in_state + 10)

    while attempts < max_attempts:
        if random.random() < 0.7 and max_possible_id_in_state >= 0:
            mid = random.randint(max(0, max_possible_id_in_state - 5), max_possible_id_in_state + 10)
        else:
            mid = random.randint(0, search_range_max)

        if mid > max_message_id: mid = random.randint(0, max_message_id)

        if mid >= 0 and mid not in messages:
            return mid
        attempts += 1

    # Fallback linear scan
    for i in range(max_message_id + 1):
        if i not in messages:
            return i

    if max_possible_id_in_state < max_message_id:
         potential_id = max_possible_id_in_state + 1
         if potential_id <= max_message_id:
              return potential_id
    return -1 # Indicate failure

def get_random_emoji_id():
    """Gets a random emoji ID from the set of stored emoji IDs."""
    return random.choice(list(emoji_ids)) if emoji_ids else None

def get_non_existent_emoji_id(max_emoji_id):
    """Gets an emoji ID that is not currently in the stored emoji_ids set."""
    if not emoji_ids: return random.randint(0, max_emoji_id)

    attempts = 0
    max_attempts = max(len(emoji_ids) * 2, 20)
    max_possible_id_in_state = max(list(emoji_ids)) if emoji_ids else -1
    search_range_max = max(max_emoji_id + 10, max_possible_id_in_state + 10)

    while attempts < max_attempts:
        if random.random() < 0.7 and max_possible_id_in_state >= 0:
            eid = random.randint(max(0, max_possible_id_in_state - 5), max_possible_id_in_state + 10)
        else:
            eid = random.randint(0, search_range_max)

        if eid > max_emoji_id: eid = random.randint(0, max_emoji_id)

        if eid >= 0 and eid not in emoji_ids:
            return eid
        attempts += 1

    # Fallback linear scan
    for i in range(max_emoji_id + 1):
        if i not in emoji_ids:
            return i
    if max_possible_id_in_state < max_emoji_id:
         potential_id = max_possible_id_in_state + 1
         if potential_id <= max_emoji_id:
              return potential_id
    return -1 # Indicate failure

def get_sendable_message():
    """Tries to find a message ID whose preconditions for sending might be met."""
    if not messages: return None
    message_ids = list(messages.keys())
    random.shuffle(message_ids)
    attempts = 0
    # Limit checks to avoid performance hit if many messages are unsendable
    max_attempts = min(len(message_ids), 50)

    for mid in message_ids:
        if attempts >= max_attempts: break
        attempts += 1
        msg_details = messages.get(mid)
        if not msg_details: continue

        p1 = msg_details['p1']
        # Sender must exist
        if p1 not in persons: continue

        if msg_details['type'] == 0: # Direct message
            p2 = msg_details['p2']
            # Receiver must exist and be related to sender
            if p2 is not None and p2 in persons and p2 in person_neighbors.get(p1, set()):
                return mid # Found a potentially sendable type 0 message
        elif msg_details['type'] == 1: # Tag message
            tag_id = msg_details['tag']
            # Tag must exist for the sender
            if tag_id is not None and tag_id in person_tags.get(p1, set()):
                # Check if tag has any valid members currently
                tag_key = (p1, tag_id)
                current_members = tag_members.get(tag_key, set())
                if current_members.intersection(persons):
                    return mid # Found a potentially sendable type 1 message

    # Fallback: if no clearly sendable message found in sample, return any message ID
    # This might fail during send_message_state, which is acceptable behavior.
    # print(f"DEBUG: get_sendable_message fallback to random choice.", file=sys.stderr)
    return random.choice(list(messages.keys())) if messages else None


# --- State Update Functions (Maintain person_neighbors) ---

# --- Person/Relation/Tag State ---
def add_person_state(person_id, name, age):
    """Adds a person to the state if they don't exist."""
    if person_id not in persons:
        persons.add(person_id)
        person_details[person_id] = {'name': name, 'age': age}
        person_degrees[person_id] = 0
        person_neighbors[person_id] = set() # Initialize neighbor set
        # HW10/11 Init
        person_received_articles[person_id] = []
        person_money[person_id] = 0
        person_social_value[person_id] = 0
        person_received_messages[person_id] = []
        return True
    return False # Person already exists

def add_relation_state(id1, id2, value, max_degree=None):
    """Adds a relation between two existing persons."""
    # Check existence and distinctness
    if id1 not in persons or id2 not in persons: return False
    if id1 == id2: return False

    p1_key, p2_key = min(id1, id2), max(id1, id2)
    rel_key = (p1_key, p2_key)

    # Check if relation already exists
    if rel_key in relations: return False

    # Check degree constraints if provided
    if max_degree is not None:
        if person_degrees.get(id1, 0) >= max_degree or person_degrees.get(id2, 0) >= max_degree:
            return False # Adding relation would exceed max degree

    # Add relation
    relations.add(rel_key)
    relation_values[rel_key] = value
    # Update degrees
    person_degrees[id1] = person_degrees.get(id1, 0) + 1
    person_degrees[id2] = person_degrees.get(id2, 0) + 1
    # Update neighbor lists
    person_neighbors[id1].add(id2)
    person_neighbors[id2].add(id1)
    return True

def remove_relation_state(id1, id2):
    """Removes a relation and updates associated state (degrees, neighbors, tags)."""
    if id1 == id2: return False
    p1_orig, p2_orig = id1, id2 # Keep original IDs for tag checks
    p1_key, p2_key = min(id1, id2), max(id1, id2)
    rel_key = (p1_key, p2_key)

    if rel_key in relations:
        # Remove relation core info
        relations.remove(rel_key)
        if rel_key in relation_values: del relation_values[rel_key]

        # Update degrees (handle potential KeyError if person was deleted, though unlikely)
        if p1_orig in person_degrees: person_degrees[p1_orig] = max(0, person_degrees[p1_orig] - 1)
        if p2_orig in person_degrees: person_degrees[p2_orig] = max(0, person_degrees[p2_orig] - 1)

        # Update neighbor lists
        if id1 in person_neighbors: person_neighbors[id1].discard(id2)
        if id2 in person_neighbors: person_neighbors[id2].discard(id1)

        # Remove from tags if relation is broken (Person1 added by Person2 to Person2's tag)
        tags_to_check_p1 = list(person_tags.get(p1_orig, set())) # Tags owned by p1
        for tag_id_p1 in tags_to_check_p1:
             tag_key_p1_owns = (p1_orig, tag_id_p1)
             if p2_orig in tag_members.get(tag_key_p1_owns, set()):
                 tag_members[tag_key_p1_owns].discard(p2_orig) # Remove p2 from p1's tag

        tags_to_check_p2 = list(person_tags.get(p2_orig, set())) # Tags owned by p2
        for tag_id_p2 in tags_to_check_p2:
             tag_key_p2_owns = (p2_orig, tag_id_p2)
             if p1_orig in tag_members.get(tag_key_p2_owns, set()):
                 tag_members[tag_key_p2_owns].discard(p1_orig) # Remove p1 from p2's tag
        return True
    return False # Relation didn't exist

def add_tag_state(person_id, tag_id):
    """Adds a tag owned by a person."""
    if person_id not in persons: return False
    if tag_id not in person_tags.get(person_id, set()):
        person_tags[person_id].add(tag_id)
        # Ensure the tag_members entry exists even if empty initially
        tag_key = (person_id, tag_id)
        if tag_key not in tag_members:
             tag_members[tag_key] = set()
        return True
    return False # Tag already exists for this person

def remove_tag_state(person_id, tag_id):
    """Removes a tag owned by a person and its associated members."""
    if person_id not in persons: return False
    if tag_id in person_tags.get(person_id, set()):
        person_tags[person_id].remove(tag_id)
        # Clean up the tag_members entry completely
        tag_key = (person_id, tag_id)
        if tag_key in tag_members:
            del tag_members[tag_key]
        # Remove the owner entry if they have no more tags
        if not person_tags[person_id]:
             del person_tags[person_id]
        return True
    return False # Tag not found for this person

def add_person_to_tag_state(person_id1, person_id2, tag_id, max_tag_size):
    """Adds person1 to a tag owned by person2, checking preconditions."""
    tag_key = (person_id2, tag_id) # person2 owns the tag

    # Preconditions:
    # 1. Both persons exist
    if not (person_id1 in persons and person_id2 in persons): return False
    # 2. Persons are different
    if person_id1 == person_id2: return False
    # 3. They are related (neighbors)
    if person_id1 not in person_neighbors.get(person_id2, set()): return False
    # 4. The tag exists and is owned by person2
    if tag_id not in person_tags.get(person_id2, set()): return False
    # 5. Person1 is not already in the tag
    if person_id1 in tag_members.get(tag_key, set()): return False

    # Check size limit
    # Use the actual number of *valid* persons currently in the tag for size check
    current_valid_members = tag_members.get(tag_key, set()).intersection(persons)
    current_size = len(current_valid_members)

    effective_max_size = 1000 # JML hard limit is very high
    if max_tag_size is not None: # Allow generator parameter to impose a stricter limit
        effective_max_size = min(effective_max_size, max_tag_size)

    if current_size < effective_max_size:
        # Add person1 to the members set for the tag key
        if tag_key not in tag_members: tag_members[tag_key] = set() # Should exist from add_tag_state
        tag_members[tag_key].add(person_id1)
        return True
    else:
        # print(f"DEBUG: Add Person To Tag failed - size limit hit for ({person_id2}, {tag_id}). Size: {current_size}, Limit: {effective_max_size}", file=sys.stderr)
        return False # Hit size limit

def remove_person_from_tag_state(person_id1, person_id2, tag_id):
    """Removes person1 from a tag owned by person2."""
    # Preconditions:
    # 1. Both persons exist (optional check, might remove already deleted person)
    if person_id1 not in persons: return False # Person to remove must exist
    if person_id2 not in persons: return False # Tag owner must exist
    # 2. Tag exists for owner
    if tag_id not in person_tags.get(person_id2, set()): return False
    # 3. Person1 is actually in the tag
    tag_key = (person_id2, tag_id)
    if person_id1 not in tag_members.get(tag_key, set()): return False

    # Perform removal
    if tag_key in tag_members:
        tag_members[tag_key].discard(person_id1) # Use discard, safer than remove
        return True
    return False # Should not be reached if checks above pass


# --- HW10 State Updates ---
def create_official_account_state(person_id, account_id, name):
    """Creates a new official account."""
    if person_id not in persons: return False # Owner must exist
    if account_id in official_accounts: return False # Account ID must be unique

    official_accounts.add(account_id)
    account_details[account_id] = {'owner': person_id, 'name': name}
    # Owner automatically follows their own account
    account_followers[account_id] = {person_id}
    # Initialize contribution count for owner (and others later)
    account_contributions[account_id] = defaultdict(int)
    account_contributions[account_id][person_id] = 0
    # Initialize article set
    account_articles[account_id] = set()
    return True

def delete_official_account_state(person_id, account_id):
    """Deletes an official account, checking permissions."""
    if person_id not in persons: return False # Person attempting delete must exist
    if account_id not in official_accounts: return False # Account must exist
    # Permission check: Only owner can delete
    if account_details.get(account_id, {}).get('owner') != person_id: return False

    # Proceed with deletion
    official_accounts.remove(account_id)

    # Clean up associated data structures
    if account_id in account_details: del account_details[account_id]
    if account_id in account_followers: del account_followers[account_id]
    if account_id in account_contributions: del account_contributions[account_id]

    # Handle articles within the deleted account
    articles_to_remove = list(account_articles.get(account_id, set()))
    for art_id in articles_to_remove:
         # Remove from global location tracking
         if art_id in article_locations and article_locations[art_id] == account_id:
              del article_locations[art_id]
         # Remove article name
         if art_id in article_names:
              del article_names[art_id]
         # Remove from global article set and contributor map
         # Assume deleting account REMOVES its articles entirely
         if art_id in all_articles: all_articles.remove(art_id)
         if art_id in article_contributors: del article_contributors[art_id]
         # Remove from people's received lists (might be slow if many followers/articles)
         # This part might be simplified depending on exact spec interpretation
         for pid_recv in list(person_received_articles.keys()):
              if art_id in person_received_articles[pid_recv]:
                   person_received_articles[pid_recv] = [a for a in person_received_articles[pid_recv] if a != art_id]


    # Remove the account's article list itself
    if account_id in account_articles: del account_articles[account_id]
    return True

def contribute_article_state(person_id, account_id, article_id, article_name_param):
    """Adds an article to an account, checking permissions."""
    # Preconditions:
    if person_id not in persons: return False # Contributor must exist
    if account_id not in official_accounts: return False # Account must exist
    if article_id in all_articles: return False # Article ID must be new globally
    # Permission check: Contributor must follow the account
    if person_id not in account_followers.get(account_id, set()): return False

    # Add article
    all_articles.add(article_id)
    article_contributors[article_id] = person_id
    article_locations[article_id] = account_id
    article_names[article_id] = article_name_param
    account_articles[account_id].add(article_id)

    # Update contribution count for the contributor in this account
    # Ensure defaultdict entry exists
    if account_id not in account_contributions: account_contributions[account_id] = defaultdict(int)
    account_contributions[account_id][person_id] += 1

    # Add article to the received list of all *current* valid followers
    current_followers = list(account_followers.get(account_id, set()).intersection(persons))
    for follower_id in current_followers:
        # Ensure follower exists and has a list initialized (should exist due to intersection)
        if follower_id not in person_received_articles:
             person_received_articles[follower_id] = []
        person_received_articles[follower_id].insert(0, article_id) # Newest first
    return True

def delete_article_state(person_id, account_id, article_id):
    """Deletes an article from an account, checking permissions."""
    # Preconditions:
    if person_id not in persons: return False # Person attempting delete must exist
    if account_id not in official_accounts: return False # Account must exist
    # Article must exist globally AND be in this specific account currently
    if article_id not in all_articles or article_id not in account_articles.get(account_id, set()): return False
    # Permission check: Only the account owner can delete
    if account_details.get(account_id, {}).get('owner') != person_id: return False

    # Decrease contribution count for the original contributor (if tracked)
    original_contributor = article_contributors.get(article_id)
    if original_contributor is not None and account_id in account_contributions:
        if original_contributor in account_contributions[account_id]:
            account_contributions[account_id][original_contributor] = max(0, account_contributions[account_id][original_contributor] - 1)
            # Optional: clean up contributor entry if count becomes 0? Depends on spec.

    # Remove article from the account's list
    if account_id in account_articles:
        account_articles[account_id].discard(article_id)

    # Remove from global location tracking
    if article_id in article_locations and article_locations[article_id] == account_id:
         del article_locations[article_id]

    # Remove from name tracking
    if article_id in article_names:
         del article_names[article_id]

    # Update received lists for all people (remove the deleted article)
    # This is simpler than tracking followers at time of deletion.
    for pid_recv in list(person_received_articles.keys()):
        if article_id in person_received_articles[pid_recv]:
             person_received_articles[pid_recv] = [art for art in person_received_articles[pid_recv] if art != article_id]
             # Optional: Clean up empty list?
             # if not person_received_articles[pid_recv]: del person_received_articles[pid_recv]


    # Remove from global article set and contributor map
    if article_id in all_articles:
        all_articles.remove(article_id)
    if article_id in article_contributors:
        del article_contributors[article_id]

    return True


def follow_official_account_state(person_id, account_id):
    """Makes a person follow an official account."""
    if person_id not in persons: return False # Follower must exist
    if account_id not in official_accounts: return False # Account must exist
    # Check if already following
    if person_id in account_followers.get(account_id, set()): return False

    # Add follower
    account_followers[account_id].add(person_id)
    # Initialize contribution count for the new follower if they weren't tracked before
    if account_id not in account_contributions:
        account_contributions[account_id] = defaultdict(int)
    if person_id not in account_contributions[account_id]:
        account_contributions[account_id][person_id] = 0
    return True

# --- HW11 State Updates ---
def add_message_state(msg_id, msg_type, p1, p2_or_tag_id, social_value, kind, extra_data):
    """Adds a message to the pending messages state. Checks preconditions."""
    # Check 1: Message ID uniqueness (Safety check, should be guaranteed by caller)
    if msg_id in messages: return False, "emi" # EqualMessageIdException

    # Check 2: Validity of persons involved
    if p1 not in persons: return False, "pinf_sender" # Sender doesn't exist

    p2 = None
    tag = None
    if msg_type == 0: # Direct Message
        p2 = p2_or_tag_id
        if p2 is None or p2 not in persons: return False, "pinf_receiver" # Receiver doesn't exist
        if p1 == p2: return False, "epi" # EqualPersonIdException
    elif msg_type == 1: # Tag Message
        tag = p2_or_tag_id
        # Tag must exist for the sender (p1)
        if tag is None or tag not in person_tags.get(p1, set()): return False, "tinf_sender"
    else:
        return False, "invalid_type" # Invalid message type

    # Check 3: Validity of extra data based on kind
    if kind == 'emoji':
        emoji_id = extra_data
        # Emoji must exist globally
        if emoji_id is None or emoji_id not in emoji_ids: return False, "einf" # EmojiIdNotFoundException
    elif kind == 'fwd':
        article_id = extra_data
        # Article must exist globally
        if article_id is None or article_id not in all_articles: return False, "ainf_glob" # ArticleIdNotFoundException (global)
        # Sender (p1) must have received the article
        if article_id not in person_received_articles.get(p1, []): return False, "ainf_recv" # ArticleIdNotFoundException (sender hasn't received)
    elif kind == 'rem':
        money = extra_data
        if money is None or not isinstance(money, int) or money <= 0: return False, "invalid_money"
    elif kind == 'msg':
        # Basic message, no extra data validation needed here, SV is checked elsewhere if needed
        pass
    else:
        return False, "invalid_kind" # Unknown message kind

    # All checks passed, add the message to the pending state
    messages[msg_id] = {
        'id': msg_id, 'type': msg_type, 'p1': p1,
        'p2': p2, 'tag': tag, 'sv': social_value,
        'kind': kind, 'extra': extra_data
    }
    return True, None # Success

def store_emoji_state(emoji_id):
    """Stores a new emoji ID if it doesn't exist."""
    if emoji_id in emoji_ids: return False # EqualEmojiIdException
    emoji_ids.add(emoji_id)
    emoji_heat[emoji_id] = 0 # Initialize heat
    return True

def send_message_state(message_id):
    """Processes sending a message, updates states, and checks send preconditions."""
    # Check 1: Message exists in pending state
    if message_id not in messages: return False, "minf" # MessageIdNotFoundException

    msg = messages[message_id]
    p1 = msg['p1']
    msg_sv = msg['sv']
    msg_kind = msg['kind']
    msg_extra = msg['extra']

    # Check 2: Sender still exists
    if p1 not in persons:
        del messages[message_id] # Remove invalid message
        # print(f"DEBUG: Removed message {message_id} - sender {p1} deleted.", file=sys.stderr)
        return False, "pinf" # Effectively MINF from caller's perspective

    # Check 3: Send preconditions based on type
    receivers_list = []
    if msg['type'] == 0: # Direct Message
        p2 = msg['p2']
        # Receiver must still exist
        if p2 is None or p2 not in persons:
             del messages[message_id] # Remove invalid message
             # print(f"DEBUG: Removed message {message_id} - receiver {p2} deleted.", file=sys.stderr)
             return False, "pinf" # Effectively MINF
        # Relation must still exist between p1 and p2
        if p2 not in person_neighbors.get(p1, set()):
            # Don't delete the message here, just return the exception
            return False, "rnf" # RelationNotFoundException
        receivers_list.append(p2)
    elif msg['type'] == 1: # Tag Message
        tag_id = msg['tag']
        # Tag must still exist for the sender
        if tag_id is None or tag_id not in person_tags.get(p1, set()):
            # Don't delete the message here, just return the exception
            return False, "tinf" # TagIdNotFoundException
        # Find all *currently valid* members of the tag
        tag_key = (p1, tag_id)
        current_valid_members = tag_members.get(tag_key, set()).intersection(persons)
        if not current_valid_members:
             # If tag has no valid members, message effectively disappears silently
             # JML doesn't specify an exception here. We'll delete and return success.
             del messages[message_id]
             # print(f"DEBUG: Sent message {message_id} to tag ({p1},{tag_id}) with 0 valid members.", file=sys.stderr)
             return True, None # Or should this be an error? Let's treat as success with 0 delivery.
        receivers_list.extend(list(current_valid_members))

    # --- All Preconditions Met: Perform State Updates ---

    # Sender updates:
    person_social_value[p1] = person_social_value.get(p1, 0) + msg_sv

    # Money deduction for RedEnvelope messages
    money_to_send = 0
    total_deducted = 0
    money_per_person_tag = 0
    tag_size = len(receivers_list) if msg['type'] == 1 else 0

    if msg_kind == 'rem':
        money_to_send = msg_extra
        if msg['type'] == 0:
             total_deducted = money_to_send
        elif msg['type'] == 1 and tag_size > 0:
            money_per_person_tag = money_to_send // tag_size
            total_deducted = money_per_person_tag * tag_size
        person_money[p1] = person_money.get(p1, 0) - total_deducted


    # Receiver updates:
    for receiver_id in receivers_list:
        # Social Value update
        person_social_value[receiver_id] = person_social_value.get(receiver_id, 0) + msg_sv

        # Add to received messages list (newest first)
        if receiver_id not in person_received_messages: person_received_messages[receiver_id] = []
        person_received_messages[receiver_id].insert(0, message_id)

        # Money gain for RedEnvelope
        if msg_kind == 'rem':
             if msg['type'] == 0:
                 person_money[receiver_id] = person_money.get(receiver_id, 0) + money_to_send
             elif msg['type'] == 1:
                 person_money[receiver_id] = person_money.get(receiver_id, 0) + money_per_person_tag

        # Article received for Forwarded message
        elif msg_kind == 'fwd':
             forwarded_article_id = msg_extra
             if receiver_id not in person_received_articles: person_received_articles[receiver_id] = []
             # Add only if article still exists globally (safety check)
             if forwarded_article_id in all_articles:
                 person_received_articles[receiver_id].insert(0, forwarded_article_id) # Newest first

    # Emoji heat update
    if msg_kind == 'emoji':
        emoji_id = msg_extra
        if emoji_id in emoji_ids: # Check if emoji still exists (wasn't deleted by dce)
            emoji_heat[emoji_id] = emoji_heat.get(emoji_id, 0) + len(receivers_list) # Heat increases by number of recipients

    # Remove message from pending state AFTER successful processing
    del messages[message_id]

    return True, None # Indicate successful sending


def delete_cold_emoji_state(limit):
    """Deletes emojis with heat < limit and any pending messages using them."""
    # Identify cold emojis
    cold_emojis = {eid for eid, heat in emoji_heat.items() if heat < limit}
    if not cold_emojis:
        return 0 # No emojis deleted

    num_deleted_emojis = len(cold_emojis)

    # Remove emojis from state
    for eid in cold_emojis:
        if eid in emoji_ids: emoji_ids.remove(eid)
        if eid in emoji_heat: del emoji_heat[eid]

    # Find and remove pending messages using these cold emojis
    messages_to_delete = set()
    for mid, msg in list(messages.items()): # Iterate over a copy of items
        if msg['kind'] == 'emoji' and msg['extra'] in cold_emojis:
            messages_to_delete.add(mid)

    for mid in messages_to_delete:
        if mid in messages:
            del messages[mid]
            # Note: No need to update person_received_messages, as these were never sent.

    # print(f"DEBUG: Deleted {num_deleted_emojis} cold emojis (limit {limit}). Removed {len(messages_to_delete)} pending messages.", file=sys.stderr)
    return num_deleted_emojis


# --- Command Weights Setup ---
def get_command_weights(phase="default", tag_focus=0.2, account_focus=0.2, message_focus=0.2): # Added message_focus
    # --- Base Weights (Adjusted for HW11) ---

    current_weights = BASE_WEIGHTS.copy()
    adjustments = LOADED_PHASE_DEFINITIONS.get(phase, {})
    current_weights.update(adjustments)
    # Apply phase adjustments
    for cmd_key in current_weights:
        current_weights[cmd_key] = max(0, current_weights[cmd_key])

    # --- Focus Adjustment Logic ---
    # Define command groups for focus adjustment
    tag_cmds = {"at", "dt", "att", "dft", "qtav", "qtvs"}
    account_cmds = {"coa", "doa", "ca", "da", "foa", "qbc", "qra"}
    message_cmds = {"am", "aem", "arem", "afm", "sm", "sei", "dce", "qsv", "qrm", "qp", "qm"}
    # Basic graph ops (often prerequisites)
    basic_cmds = {"ap", "ar", "mr", "qv", "qci", "qts", "qba", "qcs", "qsp"}

    focus_map = {'tag': (tag_cmds, tag_focus),
                 'account': (account_cmds, account_focus),
                 'message': (message_cmds, message_focus)}

    # Simple focus boost: Increase weights for focused groups
    # More sophisticated normalization could be used, but this is often sufficient
    boost_factor = 2.0 # How much to multiply weights in focused groups

    temp_total_weight = sum(current_weights.values())
    if temp_total_weight == 0: temp_total_weight = 1 # Avoid division by zero

    for group, (cmds, target_focus) in focus_map.items():
         if target_focus is not None and target_focus > 0:
             current_group_weight = sum(current_weights.get(c, 0) for c in cmds)
             current_prop = current_group_weight / temp_total_weight
             # If current proportion is significantly lower than target, boost
             if current_prop < target_focus * 0.8: # Heuristic threshold
                  for cmd in cmds:
                       if cmd in current_weights:
                           current_weights[cmd] = int(current_weights[cmd] * boost_factor) + 1 # Add 1 ensures non-zero boost


    # --- Final Weights ---
    # Ensure all weights are at least 1 if they were non-zero after adjustments/boost
    final_weights = {cmd: max(1, w) for cmd, w in current_weights.items() if w > 0}
    # Add back commands that had 0 weight but might be needed (e.g., 'ap') with weight 1
    for cmd in BASE_WEIGHTS:
        if cmd not in final_weights and BASE_WEIGHTS[cmd] > 0 :
            # Check if any adjustment/focus might have intended it to be 0
             is_zeroed_by_phase = (adjustments.get(cmd, 0) + BASE_WEIGHTS[cmd] <= 0)
             # Allow focus to override zeroing? Maybe not. Stick to phase logic primarily.
             if not is_zeroed_by_phase:
                 final_weights[cmd] = 1 # Give it a minimal chance

    # Pruning impossible commands happens dynamically in the main loop based on state.
    return final_weights


# --- Phase Parsing ---
def parse_phases(phase_string):
    """Parses the phase string 'name1:count1,name2:count2,...'"""
    if not phase_string:
        return None, None
    phases = []
    total_commands = 0
    valid_phases = ['default'] + list(LOADED_PHASE_DEFINITIONS.keys())
    valid_phases = sorted(list(set(valid_phases))) # Remove duplicates and sort
    # import pprint
    # pprint.pprint(valid_phases)
    try:
        parts = phase_string.split(',')
        for part in parts:
            part = part.strip()
            if not part: continue # Skip empty parts
            name_count = part.split(':')
            if len(name_count) != 2: raise ValueError(f"Invalid format in part: '{part}'. Expected 'name:count'.")

            name, count_str = name_count[0].strip().lower(), name_count[1].strip()
            count = int(count_str)
            if count <= 0: raise ValueError(f"Phase count must be positive, got {count} for phase '{name}'.")

            if name not in valid_phases:
                 print(f"Warning: Unrecognized phase name '{name}'. Treating as 'default'. Valid names: {', '.join(valid_phases)}", file=sys.stderr)
                 name = 'default'

            phases.append({'name': name, 'count': count})
            total_commands += count

        if not phases:
             raise ValueError("No valid phases found in the string.")

        return phases, total_commands
    except ValueError as ve: # Catch specific errors like non-integer counts
        raise ValueError(f"Invalid phase string format: '{phase_string}'. Error: {ve}")
    except Exception as e: # Catch other potential errors
        raise ValueError(f"Error parsing phase string '{phase_string}': {e}")


# --- Exception Generation Logic ---
def try_generate_exception_command(cmd_type, max_person_id, max_tag_id, max_account_id, max_article_id,
                                   max_message_id, max_emoji_id, # HW11 params
                                   target_density_unused, approx_active): # Renamed density, added approx_active
    """Attempts to generate a command that is likely to cause a specific exception."""
    cmd = None
    target_exception = None # For debugging/tracking purposes

    try:
        # --- HW9/10 Exception Cases (Largely unchanged) ---
        if cmd_type == "ap": # EqualPersonIdException
            p_id = get_existing_person_id()
            if p_id is not None:
                name = generate_name(p_id)
                age = random.randint(1, 100)
                cmd = f"ap {p_id} {name} {age}"; target_exception = "EqualPersonIdException (ap)"
        elif cmd_type == "ar": # EqualRelationException or PersonIdNotFoundException
            if random.random() < 0.6 and relations: # Target EqualRelationException
                p1_rel, p2_rel = get_random_relation() # Get tuple
                if p1_rel is not None and p2_rel is not None :
                    value = random.randint(1, 100)
                    cmd = f"ar {p1_rel} {p2_rel} {value}"; target_exception = "EqualRelationException"
            else: # Target PersonIdNotFoundException
                p1 = get_existing_person_id()
                p2 = get_non_existent_person_id(max_person_id)
                if p1 is not None and p2 is not None and p2 != -1:
                    if random.random() < 0.5: p1, p2 = p2, p1 # Randomize order
                    value = random.randint(1, 100)
                    cmd = f"ar {p1} {p2} {value}"; target_exception = "PersonIdNotFoundException (ar)"
        elif cmd_type == "mr": # PersonIdNotFoundException, EqualPersonIdException, RelationNotFoundException
            choice = random.random()
            if choice < 0.4: # Target PersonIdNotFoundException (PINF)
                p1 = get_existing_person_id()
                p2 = get_non_existent_person_id(max_person_id)
                if p1 is not None and p2 is not None and p2 != -1:
                    if random.random() < 0.5: p1, p2 = p2, p1
                    m_val = random.randint(-50, 50)
                    cmd = f"mr {p1} {p2} {m_val}"; target_exception = "PersonIdNotFoundException (mr PINF)"
            elif choice < 0.7: # Target EqualPersonIdException (EPI)
                 p1 = get_existing_person_id()
                 if p1 is not None:
                     m_val = random.randint(-50, 50)
                     cmd = f"mr {p1} {p1} {m_val}"; target_exception = "EqualPersonIdException (mr EPI)"
            else: # Target RelationNotFoundException (RNF)
                p1, p2 = get_non_existent_relation_pair(approx_mode=approx_active) # Use approx_active
                if p1 is not None and p2 is not None:
                    m_val = random.randint(-50, 50)
                    cmd = f"mr {p1} {p2} {m_val}"; target_exception = "RelationNotFoundException (mr RNF)"
        elif cmd_type == "at": # PersonIdNotFoundException or EqualTagIdException
            if random.random() < 0.5: # Target PersonIdNotFoundException (PINF)
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None and p_id != -1:
                     cmd = f"at {p_id} {tag_id}"; target_exception = "PersonIdNotFoundException (at PINF)"
            else: # Target EqualTagIdException (ETI)
                owner_id, tag_id = get_random_tag_owner_and_tag()
                if owner_id is not None and tag_id is not None:
                    cmd = f"at {owner_id} {tag_id}"; target_exception = "EqualTagIdException (at ETI)"
        elif cmd_type == "dt": # PersonIdNotFoundException or TagIdNotFoundException
            if random.random() < 0.5: # Target PersonIdNotFoundException (PINF)
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None and p_id != -1:
                    cmd = f"dt {p_id} {tag_id}"; target_exception = "PersonIdNotFoundException (dt PINF)"
            else: # Target TagIdNotFoundException (TINF)
                p_id = get_existing_person_id()
                if p_id is not None:
                    tag_id = get_non_existent_tag_id(p_id, max_tag_id)
                    cmd = f"dt {p_id} {tag_id}"; target_exception = "TagIdNotFoundException (dt TINF)"
        elif cmd_type == "att": # PINF(p1), PINF(p2), EPI(p1==p2), RNF, TINF, EPI(already in tag)
            choice = random.random()
            if choice < 0.15: # Target PINF (p1)
                p1 = get_non_existent_person_id(max_person_id)
                p2, tag_id = get_random_tag_owner_and_tag() # Find existing tag owner p2
                if p1 is not None and p1 != -1 and p2 is not None and tag_id is not None:
                     cmd = f"att {p1} {p2} {tag_id}"; target_exception = "PersonIdNotFoundException (att p1)"
            elif choice < 0.30: # Target PINF (p2 - tag owner)
                 p1 = get_existing_person_id()
                 p2 = get_non_existent_person_id(max_person_id)
                 tag_id = random.randint(0, max_tag_id) # Tag ID doesn't matter much here
                 if p1 is not None and p2 is not None and p2 != -1:
                      cmd = f"att {p1} {p2} {tag_id}"; target_exception = "PersonIdNotFoundException (att p2)"
            elif choice < 0.40: # Target EPI (p1 == p2)
                 p1 = get_existing_person_id()
                 tag_id = random.randint(0, max_tag_id) # Tag ID doesn't matter
                 if p1 is not None:
                      cmd = f"att {p1} {p1} {tag_id}"; target_exception = "EqualPersonIdException (att p1==p2)"
            elif choice < 0.60: # Target RNF (p1 and p2 not related)
                # Find owner p2 who HAS tags
                owners_with_tags_list = list(person_tags.keys())
                if owners_with_tags_list:
                     p2_owner_cand = random.choice(owners_with_tags_list)
                     tag_id_for_p2 = random.choice(list(person_tags[p2_owner_cand]))
                     # Find p1 NOT related to p2_owner_cand
                     p1_not_related = None
                     non_neighbors = list(persons - person_neighbors.get(p2_owner_cand, set()) - {p2_owner_cand})
                     if non_neighbors: p1_not_related = random.choice(non_neighbors)

                     if p1_not_related is not None:
                         cmd = f"att {p1_not_related} {p2_owner_cand} {tag_id_for_p2}"
                         target_exception = "RelationNotFoundException (att)"
            elif choice < 0.80: # Target TINF (Tag doesn't exist for p2)
                 p1, p2 = get_existing_relation() # Get related pair
                 if p1 is not None and p2 is not None:
                      tag_id = get_non_existent_tag_id(p2, max_tag_id) # Get tag p2 DOESN'T have
                      cmd = f"att {p1} {p2} {tag_id}"; target_exception = "TagIdNotFoundException (att TINF)"
            else: # Target EPI (p1 already in tag)
                # Find a tag that's non-empty
                owner_id, tag_id = get_random_tag_owner_and_tag(require_non_empty=True)
                if owner_id is not None and tag_id is not None:
                    # Get a member p1 who is confirmed to be in the tag
                    member_id = get_random_member_in_tag(owner_id, tag_id)
                    # Crucially, also ensure p1 and owner are related (precondition for adding)
                    if member_id is not None and member_id in person_neighbors.get(owner_id, set()):
                        cmd = f"att {member_id} {owner_id} {tag_id}"; target_exception = "EqualPersonIdException (att already in tag)"
        elif cmd_type == "dft": # PINF(p1), PINF(p2), TINF, PINF(p1 not in tag)
            choice = random.random()
            if choice < 0.2: # Target PINF(p1)
                p1 = get_non_existent_person_id(max_person_id)
                p2, tag_id = get_random_tag_owner_and_tag() # Find existing tag owner p2
                if p1 is not None and p1 != -1 and p2 is not None and tag_id is not None:
                    cmd = f"dft {p1} {p2} {tag_id}"; target_exception = "PersonIdNotFoundException (dft p1)"
            elif choice < 0.4: # Target PINF(p2)
                p1 = get_existing_person_id() # Person to remove exists
                p2 = get_non_existent_person_id(max_person_id) # Tag owner doesn't
                tag_id = random.randint(0, max_tag_id)
                if p1 is not None and p2 is not None and p2 != -1:
                    cmd = f"dft {p1} {p2} {tag_id}"; target_exception = "PersonIdNotFoundException (dft p2)"
            elif choice < 0.7: # Target TINF (Tag doesn't exist for p2)
                # Find owner p2
                owner_id = get_existing_person_id()
                # Find person p1 (doesn't matter if related or in tag)
                p1_cand = get_existing_person_id()
                if owner_id is not None and p1_cand is not None:
                    tag_id = get_non_existent_tag_id(owner_id, max_tag_id) # Tag p2 doesn't own
                    cmd = f"dft {p1_cand} {owner_id} {tag_id}"; target_exception = "TagIdNotFoundException (dft TINF)"
            else: # Target PINF (p1 not in tag)
                # Find tag owner p2 and tag_id
                owner_id, tag_id = get_random_tag_owner_and_tag()
                if owner_id is not None and tag_id is not None:
                    # Find person p1 who is *not* in the tag
                    p1_not_in = get_person_not_in_tag(owner_id, tag_id)
                    if p1_not_in is not None:
                        cmd = f"dft {p1_not_in} {owner_id} {tag_id}"; target_exception = "PersonIdNotFoundException (dft p1 not in tag)"
        elif cmd_type == "qv": # PINF or RNF
             choice = random.random()
             if choice < 0.5: # Target PINF
                 p1 = get_existing_person_id()
                 p2 = get_non_existent_person_id(max_person_id)
                 if p1 is not None and p2 is not None and p2 != -1:
                     if random.random() < 0.5: p1, p2 = p2, p1
                     cmd = f"qv {p1} {p2}"; target_exception = "PersonIdNotFoundException (qv PINF)"
             else: # Target RNF
                 p1, p2 = get_non_existent_relation_pair(approx_mode=approx_active) # Use approx_active
                 if p1 is not None and p2 is not None:
                     cmd = f"qv {p1} {p2}"; target_exception = "RelationNotFoundException (qv RNF)"
        elif cmd_type == "qci": # PINF
            # Only PINF is easily targetable for qci
            p1 = get_existing_person_id()
            p2 = get_non_existent_person_id(max_person_id)
            if p1 is not None and p2 is not None and p2 != -1:
                if random.random() < 0.5: p1, p2 = p2, p1
                cmd = f"qci {p1} {p2}"; target_exception = "PersonIdNotFoundException (qci PINF)"
        elif cmd_type == "qtav" or cmd_type == "qtvs": # PINF or TINF
            exception_prefix = "qtav" if cmd_type == "qtav" else "qtvs"
            choice = random.random()
            if choice < 0.5: # Target PINF
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None and p_id != -1:
                    cmd = f"{cmd_type} {p_id} {tag_id}"; target_exception = f"PersonIdNotFoundException ({exception_prefix} PINF)"
            else: # Target TINF
                p_id = get_existing_person_id()
                if p_id is not None:
                    tag_id = get_non_existent_tag_id(p_id, max_tag_id)
                    cmd = f"{cmd_type} {p_id} {tag_id}"; target_exception = f"TagIdNotFoundException ({exception_prefix} TINF)"
        elif cmd_type == "qba": # PINF or AcquaintanceNotFoundException (ANF)
            choice = random.random()
            if choice < 0.5: # Target PINF
                p_id = get_non_existent_person_id(max_person_id)
                if p_id is not None and p_id != -1:
                    cmd = f"qba {p_id}"; target_exception = "PersonIdNotFoundException (qba PINF)"
            else: # Target ANF
                p_id = get_person_with_no_acquaintances() # Find person with degree 0
                if p_id is not None:
                    cmd = f"qba {p_id}"; target_exception = "AcquaintanceNotFoundException (qba ANF)"
        elif cmd_type == "qsp": # PINF(p1), PINF(p2), PathNotFoundException (PNF)
            choice = random.random()
            if choice < 0.3: # Target PINF (p1)
                p1 = get_non_existent_person_id(max_person_id)
                p2 = get_existing_person_id()
                if p1 is not None and p1 != -1 and p2 is not None:
                     cmd = f"qsp {p1} {p2}"; target_exception = "PersonIdNotFoundException (qsp p1)"
            elif choice < 0.6: # Target PINF (p2)
                 p1 = get_existing_person_id()
                 p2 = get_non_existent_person_id(max_person_id)
                 if p1 is not None and p2 is not None and p2 != -1:
                      cmd = f"qsp {p1} {p2}"; target_exception = "PersonIdNotFoundException (qsp p2)"
            else: # Target PathNotFoundException (PNF)
                 p1, p2 = get_pair_without_path(approx_mode=approx_active) # Use helper
                 if p1 is not None and p2 is not None and p1 != p2:
                      cmd = f"qsp {p1} {p2}"
                      target_exception = "PathNotFoundException (via get_pair_without_path)"
        elif cmd_type == "coa": # PINF or EqualOfficialAccountIdException (EOAI)
            if random.random() < 0.5: # Target PINF
                p_id = get_non_existent_person_id(max_person_id)
                # ID for new account doesn't strictly matter for PINF
                acc_id = get_non_existent_account_id(max_account_id)
                if acc_id == -1: acc_id = max_account_id + 1 # Ensure positive ID if possible
                name = generate_name(acc_id , "Acc")
                if p_id is not None and p_id != -1:
                     cmd = f"coa {p_id} {acc_id} {name}"; target_exception = "PersonIdNotFoundException (coa PINF)"
            else: # Target EOAI
                 p_id = get_existing_person_id() # Any existing person can try
                 acc_id = get_random_account_id() # Get an EXISTING account ID
                 if p_id is not None and acc_id is not None:
                      name = generate_name(acc_id, "Acc") # Name doesn't matter
                      cmd = f"coa {p_id} {acc_id} {name}"; target_exception = "EqualOfficialAccountIdException (coa EOAI)"
        elif cmd_type == "doa": # PINF, OfficialAccountIdNotFoundException (OAINF), Delete...PermissionDenied (DOAPD)
             choice = random.random()
             if choice < 0.3: # Target PINF
                p_id = get_non_existent_person_id(max_person_id)
                acc_id = get_random_account_id() # Existing account
                if p_id is not None and p_id != -1 and acc_id is not None:
                      cmd = f"doa {p_id} {acc_id}"; target_exception = "PersonIdNotFoundException (doa PINF)"
             elif choice < 0.6: # Target OAINF
                  p_id = get_existing_person_id() # Existing person
                  acc_id = get_non_existent_account_id(max_account_id) # NON-existent account
                  if p_id is not None and acc_id is not None and acc_id != -1:
                       cmd = f"doa {p_id} {acc_id}"; target_exception = "OfficialAccountIdNotFoundException (doa OAINF)"
             else: # Target DOAPD (Permission Denied)
                  acc_id = get_random_account_id() # Existing account
                  if acc_id is not None:
                      owner_id = get_account_owner(acc_id)
                      # Find a person who is NOT the owner
                      non_owner_id = None
                      eligible_non_owners = list(persons - {owner_id} if owner_id is not None else persons)
                      if eligible_non_owners: non_owner_id = random.choice(eligible_non_owners)

                      if non_owner_id is not None and owner_id is not None: # Ensure owner found
                           cmd = f"doa {non_owner_id} {acc_id}"; target_exception = "DeleteOfficialAccountPermissionDeniedException (doa DOAPD)"
        elif cmd_type == "ca": # PINF, OAINF, EqualArticleIdException (EAI), ContributePermissionDenied (CPD)
             choice = random.random()
             if choice < 0.2: # Target PINF
                 p_id = get_non_existent_person_id(max_person_id)
                 acc_id = get_random_account_id() # Existing account
                 art_id = get_non_existent_article_id(max_article_id) # New article ID
                 name = generate_name(art_id if art_id != -1 else 0, "Art")
                 if p_id is not None and p_id != -1 and acc_id is not None and art_id != -1:
                      cmd = f"ca {p_id} {acc_id} {art_id} {name}"; target_exception = "PersonIdNotFoundException (ca PINF)"
             elif choice < 0.4: # Target OAINF
                  p_id = get_existing_person_id() # Existing person
                  acc_id = get_non_existent_account_id(max_account_id) # Non-existent account
                  art_id = get_non_existent_article_id(max_article_id) # New article ID
                  name = generate_name(art_id if art_id != -1 else 0, "Art")
                  if p_id is not None and acc_id is not None and acc_id != -1 and art_id != -1:
                       cmd = f"ca {p_id} {acc_id} {art_id} {name}"; target_exception = "OfficialAccountIdNotFoundException (ca OAINF)"
             elif choice < 0.6: # Target EAI
                  acc_id, follower_id = get_random_account_and_follower() # Get follower (can contribute)
                  art_id_existing = get_random_article_id() # Get EXISTING article ID
                  name = generate_name(art_id_existing if art_id_existing is not None else random.randint(0, max_article_id), "ArtNew")
                  if follower_id is not None and acc_id is not None and art_id_existing is not None:
                       cmd = f"ca {follower_id} {acc_id} {art_id_existing} {name}"; target_exception = "EqualArticleIdException (ca EAI)"
             else: # Target CPD (Permission Denied - person not follower)
                  acc_id = get_random_account_id() # Existing account
                  art_id = get_non_existent_article_id(max_article_id) # New article ID
                  name = generate_name(art_id if art_id != -1 else 0, "Art")
                  if acc_id is not None and art_id != -1:
                      p_id_not_follower = get_person_not_following(acc_id) # Get person NOT following
                      if p_id_not_follower is not None:
                           cmd = f"ca {p_id_not_follower} {acc_id} {art_id} {name}"; target_exception = "ContributePermissionDeniedException (ca CPD)"
        elif cmd_type == "da": # PINF, OAINF, ArticleIdNotFoundException (AINF), DeleteArticlePermissionDenied (DAPD)
             choice = random.random()
             if choice < 0.2: # Target PINF
                 p_id = get_non_existent_person_id(max_person_id)
                 acc_id, art_id = get_random_account_and_article() # Existing acc/article
                 if p_id is not None and p_id != -1 and acc_id is not None and art_id is not None:
                      cmd = f"da {p_id} {acc_id} {art_id}"; target_exception = "PersonIdNotFoundException (da PINF)"
             elif choice < 0.4: # Target OAINF
                  p_id_owner_cand = get_existing_person_id() # Potential owner
                  acc_id = get_non_existent_account_id(max_account_id) # Non-existent account
                  art_id_any = get_random_article_id() # Article ID doesn't matter here
                  if art_id_any is None: art_id_any = 0 # Need some ID
                  if p_id_owner_cand is not None and acc_id is not None and acc_id != -1:
                       cmd = f"da {p_id_owner_cand} {acc_id} {art_id_any}"; target_exception = "OfficialAccountIdNotFoundException (da OAINF)"
             elif choice < 0.6: # Target AINF (Article not in account or doesn't exist)
                  acc_id = get_random_account_id() # Existing account
                  if acc_id is not None:
                      owner_id = get_account_owner(acc_id)
                      # Try non-existent article first
                      art_id_not_in_acc = get_non_existent_article_id(max_article_id)
                      if owner_id is not None and art_id_not_in_acc != -1 :
                          cmd = f"da {owner_id} {acc_id} {art_id_not_in_acc}"; target_exception = "ArticleIdNotFoundException (da AINF global)"
                      else: # Try article existing globally but not in this account
                          global_articles = list(all_articles)
                          account_articles_set = account_articles.get(acc_id, set())
                          articles_not_in_account = [a for a in global_articles if a not in account_articles_set]
                          if owner_id is not None and articles_not_in_account:
                               art_id_other = random.choice(articles_not_in_account)
                               cmd = f"da {owner_id} {acc_id} {art_id_other}"; target_exception = "ArticleIdNotFoundException (da AINF not in account)"

             else: # Target DAPD (Permission Denied - not owner)
                  acc_id, art_id = get_random_account_and_article() # Existing acc/article
                  if acc_id is not None and art_id is not None:
                      owner_id = get_account_owner(acc_id)
                      # Find person who is NOT the owner
                      non_owner_id = None
                      eligible_non_owners = list(persons - {owner_id} if owner_id is not None else persons)
                      if eligible_non_owners: non_owner_id = random.choice(eligible_non_owners)

                      if non_owner_id is not None and owner_id is not None:
                           cmd = f"da {non_owner_id} {acc_id} {art_id}"; target_exception = "DeleteArticlePermissionDeniedException (da DAPD)"
        elif cmd_type == "foa": # PINF, OAINF, EqualPersonIdException (already follows)
             choice = random.random()
             if choice < 0.3: # Target PINF
                 p_id = get_non_existent_person_id(max_person_id)
                 acc_id = get_random_account_id() # Existing account
                 if p_id is not None and p_id != -1 and acc_id is not None:
                      cmd = f"foa {p_id} {acc_id}"; target_exception = "PersonIdNotFoundException (foa PINF)"
             elif choice < 0.6: # Target OAINF
                  p_id = get_existing_person_id() # Existing person
                  acc_id = get_non_existent_account_id(max_account_id) # Non-existent account
                  if p_id is not None and acc_id is not None and acc_id != -1:
                       cmd = f"foa {p_id} {acc_id}"; target_exception = "OfficialAccountIdNotFoundException (foa OAINF)"
             else: # Target EPI (already follows)
                  acc_id, follower_id = get_random_account_and_follower() # Get existing follower
                  if acc_id is not None and follower_id is not None:
                       cmd = f"foa {follower_id} {acc_id}"; target_exception = "EqualPersonIdException (foa already follows)"
        elif cmd_type == "qbc": # OAINF
            acc_id = get_non_existent_account_id(max_account_id)
            if acc_id is not None and acc_id != -1:
                cmd = f"qbc {acc_id}"; target_exception = "OfficialAccountIdNotFoundException (qbc OAINF)"
        elif cmd_type == "qra": # PINF
            p_id = get_non_existent_person_id(max_person_id)
            if p_id is not None and p_id != -1:
                cmd = f"qra {p_id}"; target_exception = "PersonIdNotFoundException (qra PINF)"

        # --- HW11 Exception Cases ---
        elif cmd_type in ["am", "aem", "arem", "afm"]:
            # *** EqualMessageIdException generation REMOVED as per new requirement ***
            add_cmd_prefix = cmd_type
            # Generate a valid *new* message ID for exception testing purposes
            msg_id_add = get_non_existent_message_id(max_message_id)
            if msg_id_add == -1: msg_id_add = random.randint(max_message_id + 1, max_message_id + 100) # Fallback ID generation

            # Get potential participants
            p1_add = get_existing_person_id()
            p2_add = get_existing_person_id()
            owner_add, tag_id_add = get_random_tag_owner_and_tag()

            # Need at least one person to generate any exception
            if not persons: return None

            choice = random.random()
            # Adjusted probabilities after removing emi case (approx scaling)
            # Old: 0.2(emi), 0.4(einf), 0.6(ainf), 0.8(epi)
            # New:           0.25(einf),0.5(ainf), 0.75(epi)

            if choice < 0.25 and add_cmd_prefix == "aem": # Target EmojiIdNotFoundException (einf)
                emoji_id_non = get_non_existent_emoji_id(max_emoji_id)
                if emoji_id_non != -1:
                    m_type = random.choice([0, 1])
                    # Need valid p1, p2/tag targets even if emoji is wrong
                    if m_type == 0:
                        p1_einf = get_existing_person_id()
                        p2_einf = get_existing_person_id()
                        if p1_einf and p2_einf and p1_einf != p2_einf:
                             cmd = f"aem {msg_id_add} {emoji_id_non} {m_type} {p1_einf} {p2_einf}"
                             target_exception = f"EmojiIdNotFoundException (aem)"
                    else: # type 1
                        owner_einf, tag_id_einf = get_random_tag_owner_and_tag()
                        if owner_einf is not None and tag_id_einf is not None:
                             cmd = f"aem {msg_id_add} {emoji_id_non} {m_type} {owner_einf} {tag_id_einf}"
                             target_exception = f"EmojiIdNotFoundException (aem)"

            elif choice < 0.5 and add_cmd_prefix == "afm": # Target ArticleIdNotFoundException (ainf)
                 # Case 1: Article ID doesn't exist globally
                 article_id_non = get_non_existent_article_id(max_article_id)
                 if article_id_non != -1 and random.random() < 0.5: # 50% chance for global non-existence
                    m_type = random.choice([0, 1])
                    # Need valid p1, p2/tag targets
                    if m_type == 0:
                        p1_aglob = get_existing_person_id()
                        p2_aglob = get_existing_person_id()
                        if p1_aglob and p2_aglob and p1_aglob != p2_aglob:
                             cmd = f"afm {msg_id_add} {article_id_non} {m_type} {p1_aglob} {p2_aglob}"
                             target_exception = f"ArticleIdNotFoundException (afm global)"
                    else: # type 1
                        owner_aglob, tag_id_aglob = get_random_tag_owner_and_tag()
                        if owner_aglob is not None and tag_id_aglob is not None:
                             cmd = f"afm {msg_id_add} {article_id_non} {m_type} {owner_aglob} {tag_id_aglob}"
                             target_exception = f"ArticleIdNotFoundException (afm global)"
                 else: # Case 2: Article exists, but sender hasn't received it
                     sender_afm = get_existing_person_id()
                     article_id_exist = get_random_article_id() # Get any existing article
                     # Ensure sender *exists* and article *exists* and sender *hasn't received it*
                     if sender_afm and article_id_exist and article_id_exist not in person_received_articles.get(sender_afm, []):
                        m_type = random.choice([0, 1])
                        if m_type == 0:
                            # Need a valid receiver
                            receiver_afm = None
                            eligible_receivers = list(persons - {sender_afm})
                            if eligible_receivers: receiver_afm = random.choice(eligible_receivers)
                            if receiver_afm:
                                cmd = f"afm {msg_id_add} {article_id_exist} {m_type} {sender_afm} {receiver_afm}"
                                target_exception = f"ArticleIdNotFoundException (afm sender)"
                        else: # type 1
                            # Need a tag owned by the sender
                            sender_tags = list(person_tags.get(sender_afm, set()))
                            if sender_tags:
                                tag_id_afm = random.choice(sender_tags)
                                cmd = f"afm {msg_id_add} {article_id_exist} {m_type} {sender_afm} {tag_id_afm}"
                                target_exception = f"ArticleIdNotFoundException (afm sender)"

            elif choice < 0.75: # Target EqualPersonIdException (epi) for type 0 message
                 p1_epi = get_existing_person_id()
                 if p1_epi:
                    # Need to determine 'extra' based on command prefix (am/aem/arem/afm)
                    extra_val = 0 # Default for am (sv will be used)
                    if add_cmd_prefix == "aem":
                        extra_val = get_random_emoji_id() # Need *any* valid emoji
                        if extra_val is None: extra_val = -1 # Indicate failure
                    elif add_cmd_prefix == "arem":
                        extra_val = random.randint(1, 50) # Any valid money amount
                    elif add_cmd_prefix == "afm":
                        # Need an article the sender HAS received
                        extra_val = get_random_article_received_by(p1_epi)
                        if extra_val is None: extra_val = -1 # Indicate failure

                    # Only generate command if extra data is valid for the type
                    if extra_val is not None and extra_val != -1:
                         # For 'am', the command format uses SV, not extra_val. Use a dummy SV.
                         cmd_val = extra_val if add_cmd_prefix != 'am' else random.randint(-10, 10)
                         cmd = f"{add_cmd_prefix} {msg_id_add} {cmd_val} 0 {p1_epi} {p1_epi}"
                         target_exception = f"EqualPersonIdException ({add_cmd_prefix} type 0)"

        elif cmd_type == "sm": # MessageIdNotFoundException, RelationNotFoundException, TagIdNotFoundException
            choice = random.random()
            if choice < 0.3: # Target MessageIdNotFoundException (minf)
                msg_id_non = get_non_existent_message_id(max_message_id)
                if msg_id_non != -1:
                     cmd = f"sm {msg_id_non}"; target_exception = "MessageIdNotFoundException (sm)"
            elif choice < 0.6: # Target RelationNotFoundException (rnf) for type 0
                 # Find a *pending* type 0 message where p1, p2 exist but relation doesn't
                 sendable_ids = list(messages.keys())
                 random.shuffle(sendable_ids)
                 for mid_sm in sendable_ids[:min(len(sendable_ids), 50)]: # Check a sample
                     msg = messages.get(mid_sm)
                     if msg and msg['type'] == 0:
                         p1_sm, p2_sm = msg['p1'], msg['p2']
                         # Check if both exist BUT relation is now broken
                         if p1_sm in persons and p2_sm in persons and p2_sm not in person_neighbors.get(p1_sm, set()):
                              cmd = f"sm {mid_sm}"; target_exception = "RelationNotFoundException (sm type 0)"
                              break
            else: # Target TagIdNotFoundException (tinf) for type 1
                 # Find a *pending* type 1 message where p1 exists but tag was deleted for p1
                 sendable_ids = list(messages.keys())
                 random.shuffle(sendable_ids)
                 for mid_sm in sendable_ids[:min(len(sendable_ids), 50)]: # Check a sample
                     msg = messages.get(mid_sm)
                     if msg and msg['type'] == 1:
                         p1_sm, tag_id_sm = msg['p1'], msg['tag']
                         # Check if p1 exists BUT tag is no longer associated with p1
                         if p1_sm in persons and tag_id_sm not in person_tags.get(p1_sm, set()):
                              cmd = f"sm {mid_sm}"; target_exception = "TagIdNotFoundException (sm type 1)"
                              break
        elif cmd_type == "sei": # Target EqualEmojiIdException (eei)
            emoji_id_exist = get_random_emoji_id() # Get an existing emoji ID
            if emoji_id_exist is not None:
                 cmd = f"sei {emoji_id_exist}"; target_exception = "EqualEmojiIdException (sei)"
        elif cmd_type == "qp": # Target EmojiIdNotFoundException (einf)
             emoji_id_non = get_non_existent_emoji_id(max_emoji_id) # Get non-existent emoji ID
             if emoji_id_non != -1:
                  cmd = f"qp {emoji_id_non}"; target_exception = "EmojiIdNotFoundException (qp)"
        elif cmd_type in ["qsv", "qrm", "qm"]: # Target PersonIdNotFoundException (pinf)
            p_id_non = get_non_existent_person_id(max_person_id)
            if p_id_non != -1:
                cmd = f"{cmd_type} {p_id_non}"; target_exception = f"PersonIdNotFoundException ({cmd_type})"


    except Exception as e:
        # print(f"ERROR during *exception* generation for {cmd_type}: {e}", file=sys.stderr)
        # traceback.print_exc(file=sys.stderr) # More detail if needed
        return None # Failed to generate exception command
    # if cmd: print(f"DEBUG: Generated EXCEPTION command ({target_exception}): {cmd}", file=sys.stderr)
    return cmd


# --- Main Generation Logic ---
def generate_commands(num_commands_target, max_person_id, max_tag_id, max_account_id, max_article_id,
                      max_message_id, max_emoji_id, max_rem_money, # HW11 params
                      max_rel_value, max_mod_value, max_age,
                      min_qci, min_qts, min_qtav, min_qba, min_qcs, min_qsp, min_qtvs, min_qbc, min_qra,
                      min_qsv, min_qrm, min_qp, min_qm, # HW11 mins
                      density, degree_focus_unused, max_degree,
                      tag_focus, account_focus, message_focus, # HW11 focus
                      max_tag_size, qci_focus,
                      mr_delete_ratio, exception_ratio, force_qba_empty_ratio, force_qtav_empty_ratio,
                      hub_bias, num_hubs,
                      phases_config,
                      hce_active,
                      use_ln_setup, ln_nodes, ln_default_value,
                      approx_active): # Added approx_active

    generated_cmds_list = []
    cmd_counts = defaultdict(int)
    current_phase_index = 0
    commands_in_current_phase = 0
    num_commands_to_generate = num_commands_target

    # --- Phase Setup ---
    if phases_config:
        num_commands_to_generate = sum(p['count'] for p in phases_config)
        # print(f"INFO: Using phases, total commands set to {num_commands_to_generate}", file=sys.stderr)
    # else:
        # print(f"INFO: Not using phases, target commands: {num_commands_to_generate}", file=sys.stderr)


    # --- Initial Setup (ln or ap/ar) ---
    initial_cmds_count = 0
    hub_ids = set() # Initialize hub_ids

    if use_ln_setup and ln_nodes >= 2:
        # print(f"INFO: Using 'ln' setup with {ln_nodes} nodes, density {density:.2f}", file=sys.stderr)
        ln_command_str = f"ln {ln_nodes}\n"

        # Generate person details
        ln_person_ids = list(range(ln_nodes))
        ln_command_str += " ".join(map(str, ln_person_ids)) + "\n"
        ln_person_names = [generate_name(i, "P") for i in ln_person_ids]
        ln_command_str += " ".join(ln_person_names) + "\n"
        ln_person_ages = [str(random.randint(1, max_age)) for _ in ln_person_ids]
        ln_command_str += " ".join(ln_person_ages) + "\n"

        # Update state for ln persons
        for i in range(ln_nodes):
            add_person_state(ln_person_ids[i], ln_person_names[i], int(ln_person_ages[i]))

        # Generate relation matrix based on density
        target_edges = int(density * (ln_nodes * (ln_nodes - 1)) / 2)
        current_edges = 0
        # Use dict for sparse matrix representation - faster than list of lists for low density
        adj_matrix_values_dict = defaultdict(lambda: defaultdict(int))

        # Create list of potential edges (r, c) where r > c
        possible_edges_coords = []
        for r in range(1, ln_nodes):
            for c in range(r):
                 possible_edges_coords.append((r,c))
        random.shuffle(possible_edges_coords)

        # Add edges until target density is reached or no more possible edges
        for r, c in possible_edges_coords:
            if current_edges < target_edges:
                # Attempt to add relation state (checks degree limits if applicable)
                if add_relation_state(ln_person_ids[r], ln_person_ids[c], ln_default_value, max_degree):
                    adj_matrix_values_dict[r][c] = ln_default_value
                    current_edges += 1
            else:
                break # Reached target density

        # Format the adjacency matrix string (lower triangle)
        for r in range(1, ln_nodes): # Iterate through rows (person index 1 to N-1)
             row_values = [str(adj_matrix_values_dict[r].get(c, 0)) for c in range(r)] # Get values for c < r
             ln_command_str += " ".join(row_values) + "\n"

        generated_cmds_list.append(ln_command_str.strip())
        cmd_counts['ln'] += 1
        initial_cmds_count = 1 # Count 'ln' as one command block

        # Define hubs after 'ln' setup
        hub_ids = set(range(min(num_hubs, ln_nodes))) if num_hubs > 0 else set()
        # print(f"INFO: 'ln' setup complete. Persons: {len(persons)}, Relations: {len(relations)}", file=sys.stderr)

    else: # Standard ap/ar initial setup
        # Determine initial people count (heuristic)
        initial_people_target = min(num_commands_to_generate // 10 + 5, max_person_id + 1, 100)
        if hub_bias > 0: initial_people_target = max(initial_people_target, num_hubs)
        initial_people_target = max(2, initial_people_target) # Ensure at least 2 people if possible

        # print(f"INFO: Using 'ap' setup, target initial people: {initial_people_target}", file=sys.stderr)
        initial_people_added = 0
        for _ in range(initial_people_target):
            person_id_val = get_non_existent_person_id(max_person_id)
            # Stop if we can't find a valid ID within the limit
            if person_id_val == -1:
                 # print(f"Warning: Could not find non-existent person ID <= {max_person_id}. Stopping initial 'ap'.", file=sys.stderr)
                 break

            name = generate_name(person_id_val, "Person")
            age = random.randint(1, max_age)
            if add_person_state(person_id_val, name, age):
                cmd_ap = f"ap {person_id_val} {name} {age}"
                generated_cmds_list.append(cmd_ap)
                cmd_counts['ap'] += 1
                initial_cmds_count +=1
                initial_people_added += 1
            # else: # Should not happen with get_non_existent_person_id
            #     print(f"Warning: add_person_state failed for allegedly non-existent ID {person_id_val}", file=sys.stderr)

        # Define hubs based on the first few people added
        if num_hubs > 0:
            hub_ids = set(p for p in list(persons)[:num_hubs]) # Take the first N added persons as hubs

        # Optionally add some initial relations if density > 0 and ln wasn't used
        if density > 0 and len(persons) >= 2:
             initial_target_edges = int(density * (len(persons) * (len(persons) - 1)) / 2)
             initial_relations_to_add = max(0, initial_target_edges - len(relations))
             initial_relations_added = 0
             add_rel_attempts = 0
             # print(f"INFO: Adding initial relations. Target: {initial_relations_to_add}", file=sys.stderr)
             while initial_relations_added < initial_relations_to_add and add_rel_attempts < initial_relations_to_add * 5 + 10:
                 add_rel_attempts += 1
                 p1_init, p2_init = get_non_existent_relation_pair(approx_mode=False) # Try to add missing ones
                 if p1_init is None or p2_init is None: # Fallback if dense or failed
                      p1_init,p2_init = get_two_random_persons(require_different=True)

                 if p1_init is not None and p2_init is not None:
                     init_val = random.randint(1, max_rel_value)
                     if add_relation_state(p1_init, p2_init, init_val, max_degree):
                         cmd_ar_init = f"ar {p1_init} {p2_init} {init_val}"
                         generated_cmds_list.append(cmd_ar_init)
                         cmd_counts['ar'] += 1
                         initial_cmds_count +=1
                         initial_relations_added += 1

             # print(f"INFO: Initial setup complete. Persons: {len(persons)}, Relations: {len(relations)}", file=sys.stderr)


    # --- Main Generation Loop ---
    commands_generated_this_run = 0
    max_total_commands = num_commands_to_generate # Use phase total or -n target

    while commands_generated_this_run < (max_total_commands - initial_cmds_count) :
        current_phase_name = "default"
        # Determine current phase if using phases
        if phases_config:
            if current_phase_index >= len(phases_config): break # All phases completed
            current_phase_info = phases_config[current_phase_index]
            current_phase_name = current_phase_info['name']
            # Check if current phase is finished
            if commands_in_current_phase >= current_phase_info['count']:
                # print(f"INFO: Finished phase '{current_phase_name}' ({commands_in_current_phase} commands).", file=sys.stderr)
                current_phase_index += 1
                commands_in_current_phase = 0
                # Check if we are done after incrementing phase
                if current_phase_index >= len(phases_config):
                     # print(f"INFO: All phases complete.", file=sys.stderr)
                     break
                # Get next phase info
                current_phase_info = phases_config[current_phase_index]
                current_phase_name = current_phase_info['name']
                # print(f"INFO: Starting phase '{current_phase_name}' (target: {current_phase_info['count']} commands).", file=sys.stderr)


        # Get weighted commands for the current phase/settings
        weights_dict = get_command_weights(current_phase_name, tag_focus, account_focus, message_focus)

        # --- Dynamic Weight Pruning Based on Current State ---
        # Check if adding persons is possible
        can_add_person = any(i <= max_person_id and i not in persons for i in range(max_person_id + 1))

        # If no persons exist and cannot add more, break
        if not persons and not can_add_person:
            # print("Error: No persons exist and cannot add more. Stopping generation.", file=sys.stderr)
            break
        # If no persons exist, but can add, force 'ap'
        elif not persons:
            weights_dict = {'ap': 1} if can_add_person else {}

        # Prune based on state if persons exist
        if persons:
            # Person Count Pruning
            if len(persons) < 2:
                for k in ["ar", "mr", "qv", "qci", "att", "dft", "qsp", "am", "aem", "arem", "afm", "coa", "foa"]: # Ops requiring >= 2 people or specific interactions
                    if k in weights_dict: weights_dict[k] = 0
            # Relation Pruning
            if not relations:
                for k in ["mr", "qv", "att", "dft"]: # Require existing relations or ability to add people to tags based on relation
                    if k in weights_dict: weights_dict[k] = 0
                if "qsp" in weights_dict: weights_dict["qsp"] = 0 # qsp needs relations for paths
                if "qci" in weights_dict and random.random() < 0.8: weights_dict["qci"] = 0 # Less likely meaningful without relations
            # Neighbor/Degree Pruning
            if not any(person_neighbors.values()): # Check if anyone has neighbors
                 if "qba" in weights_dict: weights_dict["qba"] = 0
            # Tag Pruning
            if not person_tags: # Check if any tags exist at all
                for k in ["dt", "qtav", "qtvs", "att", "dft", "am", "aem", "arem", "afm"]: # dt removes tags, qtav/qtvs query them, att/dft manage members, type 1 messages need them
                     if k in weights_dict and (k in ["dt", "qtav", "qtvs"] or weights_dict.get(k,0) > 0): # Check if command is tag-related or message potentially of type 1
                         # Be careful with messages - maybe only reduce weight? Let's zero for now.
                         # Check if it's specifically a type 1 message target? Hard to know beforehand.
                         # Let's just zero out commands *solely* dependent on tags existing
                         if k in ["dt", "qtav", "qtvs", "att", "dft"]:
                              weights_dict[k] = 0
                         elif k in ["am", "aem", "arem", "afm"]: # Reduce weight for messages if no tags exist (can't send type 1)
                              weights_dict[k] = max(0, weights_dict.get(k, 0) // 2)
            if not any(tag_members.values()): # Check if any tag has members
                if "dft" in weights_dict: weights_dict["dft"] = 0 # dft requires members to remove
                # qtav can be called on empty tags
            # Account Pruning
            if not official_accounts:
                for k in ["doa", "ca", "da", "foa", "qbc"]: # Need existing accounts
                     if k in weights_dict: weights_dict[k]=0
            # Article/Follower Pruning
            if not all_articles:
                 if "da" in weights_dict: weights_dict["da"]=0 # Can't delete non-existent articles
                 if "afm" in weights_dict: weights_dict["afm"]=0 # Can't forward non-existent articles
            # Check if anyone can contribute (account exists AND has followers)
            can_contribute_ca = any(acc_id in official_accounts and account_followers.get(acc_id, set()).intersection(persons) for acc_id in official_accounts)
            if not can_contribute_ca:
                 if "ca" in weights_dict: weights_dict["ca"]=0
            # Check if any articles exist to be deleted
            can_delete_article_check = any(acc_id in official_accounts and account_articles.get(acc_id, set()).intersection(all_articles) for acc_id in official_accounts)
            if not can_delete_article_check:
                 if "da" in weights_dict: weights_dict["da"] = 0
            # Check if anyone can forward articles (sender has received one)
            can_forward_article = any(person_received_articles.get(pid) for pid in persons)
            if not can_forward_article:
                 if "afm" in weights_dict: weights_dict["afm"] = 0
            # Message/Emoji Pruning
            if not messages: # No pending messages
                if "sm" in weights_dict: weights_dict["sm"]=0 # Can't send
            if not emoji_ids: # No stored emojis
                for k in ["aem", "qp", "dce"]: # Need emojis
                    if k in weights_dict: weights_dict[k]=0

        # Remove 0-weight items before making choice
        active_weights_dict = {k:v for k, v in weights_dict.items() if v > 0}

        # If no commands are possible, break
        if not active_weights_dict:
             # print("Warning: No possible commands left based on current state and weights. Stopping.", file=sys.stderr)
             # Try to add a person as a last resort if possible
             if can_add_person:
                 cmd_type = 'ap'
                 # print("Attempting last resort 'ap'.", file=sys.stderr)
             else:
                 break # Truly stuck

        else:
             # Choose command type based on weights
             command_types = list(active_weights_dict.keys())
             type_weights = [active_weights_dict[cmd_t] for cmd_t in command_types]
             try:
                 cmd_type = random.choices(command_types, weights=type_weights, k=1)[0]
             except ValueError: # Can happen if weights somehow become invalid (e.g., negative)
                 # print(f"Warning: Invalid weights detected ({type_weights}). Choosing uniformly.", file=sys.stderr)
                 cmd_type = random.choice(command_types)


        # --- Generate Command (Exception or Normal) ---
        cmd = None
        generated_successfully = False
        state_changed = False # Track if the generated command modified the state

        # --- Attempt Exception Generation ---
        # Check if exception generation is feasible for this command type
        # (We have specific exception logic for most types)
        can_gen_exception = cmd_type not in ["ln", "qts", "qcs"] # Types with no specific exception logic
        if can_gen_exception and random.random() < exception_ratio:
            cmd = try_generate_exception_command(cmd_type, max_person_id, max_tag_id,
                                                 max_account_id, max_article_id,
                                                 max_message_id, max_emoji_id,
                                                 density, approx_active)
            if cmd:
                # print(f"DEBUG: Generated EXCEPTION cmd: {cmd}", file=sys.stderr)
                generated_successfully = True
                state_changed = False # Exceptions don't change state

        # --- Attempt Normal Command Generation ---
        if not generated_successfully:
            # Wrap normal generation in try-except to catch unexpected errors within helpers
            try:
                # --- Force Empty Queries (for coverage) ---
                force_qba_empty = (cmd_type == "qba" and random.random() < force_qba_empty_ratio)
                force_qtav_empty = (cmd_type == "qtav" and random.random() < force_qtav_empty_ratio)

                # --- HW9/10/11 Normal Command Generation ---
                # (Includes calls to state update functions)

                if cmd_type == "ap":
                    person_id = get_non_existent_person_id(max_person_id)
                    if person_id != -1 : # Check if valid ID found
                        name = generate_name(person_id, "Person")
                        age = random.randint(1, max_age)
                        if add_person_state(person_id, name, age):
                            cmd = f"ap {person_id} {name} {age}"; generated_successfully = True; state_changed = True
                elif cmd_type == "ar":
                    p1, p2 = None, None
                    # Try connecting to hub node if hub_bias is set
                    use_hub = (hub_ids and random.random() < hub_bias)
                    if use_hub:
                        valid_hubs = list(h for h in hub_ids if h in persons)
                        if valid_hubs:
                             hub_id = random.choice(valid_hubs)
                             # Find person NOT connected to hub
                             eligible_others = list(p for p in persons if p != hub_id and p not in person_neighbors.get(hub_id, set()))
                             if eligible_others:
                                 other_p = random.choice(eligible_others)
                                 p1, p2 = hub_id, other_p
                                 # print(f"DEBUG: Hub AR: {p1}-{p2}", file=sys.stderr)

                    # If hub connection wasn't made or not attempted, find non-existent pair
                    if p1 is None or p2 is None:
                       p1, p2 = get_non_existent_relation_pair(approx_mode=approx_active) # Bias towards adding non-existing
                       # Fallback if graph is dense / non-existent pair not found
                       if p1 is None or p2 is None:
                            # print("DEBUG: AR fallback to random pair", file=sys.stderr)
                            p1,p2 = get_two_random_persons(require_different=True)

                    if p1 is not None and p2 is not None and p1 != p2:
                        value = random.randint(1, max_rel_value)
                        if add_relation_state(p1, p2, value, max_degree):
                            cmd = f"ar {p1} {p2} {value}"; generated_successfully = True; state_changed = True
                        # else:
                            # print(f"DEBUG: add_relation_state failed for {p1}-{p2} (max_degree={max_degree})", file=sys.stderr)


                elif cmd_type == "mr":
                    p1_mr, p2_mr = get_existing_relation() # Need existing relation for MR
                    if p1_mr is not None and p2_mr is not None:
                        rel_key_mr = (min(p1_mr,p2_mr), max(p1_mr,p2_mr))
                        current_value_mr = relation_values.get(rel_key_mr, 0) # Default to 0 if somehow missing

                        m_val_mr = 0
                        # Decide whether to delete or modify
                        if current_value_mr > 0 and random.random() < mr_delete_ratio:
                            # Target deletion: ensure value becomes <= 0
                            m_val_mr = -current_value_mr - random.randint(0, 10)
                        else:
                            # Target modification
                            effective_max_mod_mr = max(1, max_mod_value)
                            m_val_mr = random.randint(-effective_max_mod_mr, effective_max_mod_mr)
                            # Avoid mr with 0 value if possible, unless max_mod_value itself is 0
                            if m_val_mr == 0 and max_mod_value != 0:
                                m_val_mr = random.choice([-1, 1]) * random.randint(1, effective_max_mod_mr)
                            # Avoid making value 0 unless explicitly deleting
                            if current_value_mr + m_val_mr == 0 and m_val_mr != 0:
                                m_val_mr += random.choice([-1, 1])

                        # Apply HCE limit if active
                        if hce_active:
                            m_val_mr = max(-hce_max_val_param, min(hce_max_val_param, m_val_mr))

                        cmd = f"mr {p1_mr} {p2_mr} {m_val_mr}"
                        generated_successfully = True

                        # Update state AFTER generating command string
                        new_value_mr = current_value_mr + m_val_mr
                        if new_value_mr <= 0:
                            if remove_relation_state(p1_mr, p2_mr): state_changed = True
                            else: generated_successfully=False # State update failed unexpectedly
                        else:
                            relation_values[rel_key_mr] = new_value_mr
                            state_changed = True
                elif cmd_type == "at":
                    person_id_at = get_existing_person_id()
                    if person_id_at is not None:
                        tag_id_at = get_non_existent_tag_id(person_id_at, max_tag_id)
                        if add_tag_state(person_id_at, tag_id_at):
                             cmd = f"at {person_id_at} {tag_id_at}"; generated_successfully = True; state_changed = True
                elif cmd_type == "dt":
                    owner_id_dt, tag_id_dt = get_random_tag_owner_and_tag()
                    if owner_id_dt is not None and tag_id_dt is not None:
                        if remove_tag_state(owner_id_dt, tag_id_dt):
                            cmd = f"dt {owner_id_dt} {tag_id_dt}"; generated_successfully = True; state_changed = True
                elif cmd_type == "att":
                     # Find an owner/tag pair first
                     owner_id_att, tag_id_att = get_random_tag_owner_and_tag()
                     if owner_id_att is not None and tag_id_att is not None:
                         # Find a person related to the owner but not yet in the tag
                         person_id1_att = get_related_person_not_in_tag(owner_id_att, tag_id_att)
                         if person_id1_att is not None:
                             if add_person_to_tag_state(person_id1_att, owner_id_att, tag_id_att, max_tag_size):
                                cmd = f"att {person_id1_att} {owner_id_att} {tag_id_att}"; generated_successfully = True; state_changed = True
                             # Else: failed (e.g., due to tag size limit), don't generate cmd
                elif cmd_type == "dft":
                     # Find an owner/tag pair that has members
                     owner_id_dft, tag_id_dft = get_random_tag_owner_and_tag(require_non_empty=True)
                     if owner_id_dft is not None and tag_id_dft is not None:
                         # Get a random valid member from that tag
                         member_id_dft = get_random_member_in_tag(owner_id_dft, tag_id_dft)
                         if member_id_dft is not None:
                             if remove_person_from_tag_state(member_id_dft, owner_id_dft, tag_id_dft):
                                cmd = f"dft {member_id_dft} {owner_id_dft} {tag_id_dft}"; generated_successfully = True; state_changed = True
                elif cmd_type == "coa":
                    person_id_coa = get_existing_person_id()
                    account_id_coa = get_non_existent_account_id(max_account_id)
                    if person_id_coa is not None and account_id_coa != -1:
                         name_coa = generate_name(account_id_coa, "Acc")
                         if create_official_account_state(person_id_coa, account_id_coa, name_coa):
                              cmd = f"coa {person_id_coa} {account_id_coa} {name_coa}"; generated_successfully = True; state_changed = True
                elif cmd_type == "doa":
                    # Find an account whose owner still exists
                    owner_id_doa = None; acc_id_doa = None
                    accounts_with_valid_owners_doa = {
                        acc: details['owner']
                        for acc, details in account_details.items()
                        if acc in official_accounts and details.get('owner') in persons # Check both official and owner exists
                    }
                    if accounts_with_valid_owners_doa:
                         acc_id_doa = random.choice(list(accounts_with_valid_owners_doa.keys()))
                         owner_id_doa = accounts_with_valid_owners_doa[acc_id_doa]

                    if owner_id_doa is not None and acc_id_doa is not None:
                        if delete_official_account_state(owner_id_doa, acc_id_doa):
                            cmd = f"doa {owner_id_doa} {acc_id_doa}"; generated_successfully = True; state_changed = True
                elif cmd_type == "ca":
                     # Find an account that has valid followers
                     acc_id_ca = get_random_account_with_followers()
                     if acc_id_ca:
                         # Pick a random valid follower
                         follower_id_ca = get_random_follower(acc_id_ca)
                         if follower_id_ca: # Ensure follower was found
                             article_id_ca = get_non_existent_article_id(max_article_id)
                             if article_id_ca != -1:
                                 name_ca = generate_name(article_id_ca, "Art")
                                 if contribute_article_state(follower_id_ca, acc_id_ca, article_id_ca, name_ca):
                                      cmd = f"ca {follower_id_ca} {acc_id_ca} {article_id_ca} {name_ca}"; generated_successfully = True; state_changed = True
                elif cmd_type == "da":
                     # Find an account with articles owned by a valid person
                     acc_id_da, art_id_da = None, None
                     owner_id_da = None
                     candidate_accounts = get_random_account_with_articles() # Get account known to have articles
                     if candidate_accounts:
                         temp_owner = get_account_owner(candidate_accounts)
                         # Ensure owner still exists
                         if temp_owner is not None and temp_owner in persons:
                              temp_article = get_random_article_in_account(candidate_accounts)
                              if temp_article is not None:
                                   acc_id_da = candidate_accounts
                                   art_id_da = temp_article
                                   owner_id_da = temp_owner

                     if owner_id_da is not None and acc_id_da is not None and art_id_da is not None:
                          if delete_article_state(owner_id_da, acc_id_da, art_id_da):
                               cmd = f"da {owner_id_da} {acc_id_da} {art_id_da}"; generated_successfully = True; state_changed = True
                elif cmd_type == "foa":
                     # Find an account
                     acc_id_foa = get_random_account_id()
                     if acc_id_foa is not None:
                         # Find a person who exists but doesn't follow this account
                         person_id_foa = get_person_not_following(acc_id_foa)
                         if person_id_foa is not None:
                              if follow_official_account_state(person_id_foa, acc_id_foa):
                                   cmd = f"foa {person_id_foa} {acc_id_foa}"; generated_successfully = True; state_changed = True

                # --- HW11 Normal Command Generation ---
                elif cmd_type == "sei":
                    emoji_id_sei = get_non_existent_emoji_id(max_emoji_id)
                    if emoji_id_sei != -1:
                        if store_emoji_state(emoji_id_sei):
                             cmd = f"sei {emoji_id_sei}"; generated_successfully = True; state_changed = True

                elif cmd_type == "am" or cmd_type == "aem" or cmd_type == "arem" or cmd_type == "afm":
                    # *** Use get_non_existent_message_id to ensure uniqueness ***
                    msg_id_am = get_non_existent_message_id(max_message_id)
                    if msg_id_am != -1:
                         p1_am = get_existing_person_id()
                         if p1_am is not None:
                             # Decide message type (0 or 1) - slightly prefer direct (0) if possible
                             m_type_am = 0
                             can_send_type1 = bool(person_tags.get(p1_am))
                             if can_send_type1 and random.random() < 0.4: # 40% chance for type 1 if possible
                                  m_type_am = 1

                             p2_or_tag_am = None
                             valid_target = False

                             if m_type_am == 0 and len(persons) >= 2: # Direct message
                                 # Find a different person for p2
                                 eligible_p2 = list(persons - {p1_am})
                                 if eligible_p2:
                                     p2_am = random.choice(eligible_p2)
                                     p2_or_tag_am = p2_am
                                     valid_target = True
                             elif m_type_am == 1 and can_send_type1: # Tag message
                                 # Pick a tag the sender owns
                                 tag_id_am = random.choice(list(person_tags[p1_am]))
                                 p2_or_tag_am = tag_id_am
                                 valid_target = True
                                 # Ensure the chosen tag *might* have members (optional optimization)
                                 # if not tag_members.get((p1_am, tag_id_am), set()).intersection(persons):
                                 #      valid_target = False # Skip if tag is known to be empty

                             # If a valid target (p2 or tag) was found:
                             if valid_target:
                                 # Determine kind, extra data, and social value based on cmd_type
                                 sv_am = 0; kind_am = 'msg'; extra_am = None; cmd_prefix_am = "am"
                                 command_value = 0 # Value to put in the command string

                                 if cmd_type == "aem":
                                     if not emoji_ids: continue # Skip if no emojis stored
                                     extra_am = get_random_emoji_id()
                                     if extra_am is None: continue # Should not happen if emoji_ids not empty
                                     # sv_am = emoji_heat.get(extra_am, 0) # Heat is not SV
                                     sv_am = extra_am # JML: socialValue == emojiId for EmojiMessage
                                     kind_am = 'emoji'; cmd_prefix_am = "aem"
                                     command_value = extra_am
                                 elif cmd_type == "arem":
                                     extra_am = random.randint(1, max_rem_money)
                                     sv_am = extra_am * 5 # JML: socialValue == money * 5 for RedEnvelopeMessage
                                     kind_am = 'rem'; cmd_prefix_am = "arem"
                                     command_value = extra_am
                                 elif cmd_type == "afm":
                                     if not all_articles: continue # Skip if no articles exist
                                     # Find an article the *sender* has received
                                     extra_am = get_random_article_received_by(p1_am)
                                     if extra_am is None: continue # Skip if sender hasn't received any
                                     sv_am = abs(extra_am) % 200 # JML: socialValue == abs(articleId) % 200
                                     kind_am = 'fwd'; cmd_prefix_am = "afm"
                                     command_value = extra_am
                                 elif cmd_type == "am": # Base message
                                     sv_am = random.randint(-1000, 1000) # Assign random SV for base message
                                     kind_am = 'msg'; cmd_prefix_am = "am"
                                     command_value = sv_am # Command value is the social value itself

                                 # Attempt to add the message to the pending state
                                 success_add, add_error_code = add_message_state(msg_id_am, m_type_am, p1_am, p2_or_tag_am, sv_am, kind_am, extra_am)
                                 if success_add:
                                     cmd = f"{cmd_prefix_am} {msg_id_am} {command_value} {m_type_am} {p1_am} {p2_or_tag_am}"
                                     generated_successfully = True
                                     state_changed = True
                                 # else:
                                     # print(f"DEBUG: add_message_state failed for {cmd_prefix_am} ({add_error_code})", file=sys.stderr)


                elif cmd_type == "sm":
                    # Try to find a message that is likely sendable
                    msg_id_sm = get_sendable_message()
                    if msg_id_sm is not None:
                         # Attempt to send it, which includes final checks
                         success_sm, exception_sm = send_message_state(msg_id_sm)
                         if success_sm:
                              cmd = f"sm {msg_id_sm}"; generated_successfully = True; state_changed = True
                         # else: # Send failed (RNF/TINF/PINF etc.) - Don't generate command, maybe log
                              # print(f"DEBUG: send_message_state failed for {msg_id_sm} ({exception_sm}). No 'sm' command generated.", file=sys.stderr)
                              pass # Allow generator to try another command

                elif cmd_type == "dce":
                     # Choose a limit, possibly based on current heat levels
                     current_heats = list(emoji_heat.values())
                     limit_dce = 0
                     if current_heats:
                          # Pick a limit somewhere between min and median heat?
                          limit_dce = random.randint(min(current_heats), int(statistics.median(current_heats)) + 1) if len(current_heats) > 1 else min(current_heats)
                     else: # No emojis, command won't do anything, but generate it anyway
                          limit_dce = random.randint(0, 10)

                     limit_dce = max(0, limit_dce) # Ensure non-negative limit

                     # Generate command first
                     cmd = f"dce {limit_dce}"; generated_successfully = True
                     # Then update state
                     deleted_count_dce = delete_cold_emoji_state(limit_dce)
                     if deleted_count_dce > 0: state_changed = True # State only changes if emojis were deleted

                # --- Query Command Generation (No State Change) ---
                elif cmd_type == "qv":
                    # Prefer existing relations for qv if they exist
                    if relations and random.random() < 0.8:
                        p1_qv, p2_qv = get_existing_relation()
                    else: # Fallback to any two different people
                        p1_qv, p2_qv = get_two_random_persons(require_different=True)
                    if p1_qv is not None and p2_qv is not None:
                        cmd = f"qv {p1_qv} {p2_qv}"; generated_successfully = True; state_changed = False
                elif cmd_type == "qci":
                     p1_qci, p2_qci = None, None
                     # Apply qci_focus hint
                     if qci_focus == 'close' and relations and random.random() < 0.7: # Higher chance for close pairs
                         p1_qci, p2_qci = get_pair_with_path() # Try getting pair known to have path
                         if p1_qci is None or p2_qci is None: p1_qci, p2_qci = get_existing_relation() # Fallback
                     elif qci_focus == 'far' and random.random() < 0.7: # Higher chance for far pairs
                         p1_qci, p2_qci = get_pair_without_path(approx_mode=approx_active)
                     # Default or fallback: random pair
                     if p1_qci is None or p2_qci is None:
                         p1_qci, p2_qci = get_two_random_persons(require_different=True)

                     if p1_qci is not None and p2_qci is not None:
                          cmd = f"qci {p1_qci} {p2_qci}"; generated_successfully = True; state_changed = False
                elif cmd_type == "qts":
                     cmd = "qts"; generated_successfully = True; state_changed = False
                elif cmd_type == "qtav":
                    owner_qtav, tag_qtav = None, None
                    # Try forcing empty tag if requested
                    if force_qtav_empty and random.random() < 0.5: # Add randomness to force empty
                        owner_qtav, tag_qtav = get_random_empty_tag()
                    # Otherwise, get any tag
                    if owner_qtav is None:
                        owner_qtav, tag_qtav = get_random_tag_owner_and_tag()
                    # Fallback if no tags exist at all
                    if owner_qtav is None:
                         owner_qtav = get_existing_person_id()
                         if owner_qtav is not None: tag_qtav = random.randint(0, max_tag_id) # Use random tag ID

                    if owner_qtav is not None and tag_qtav is not None:
                        cmd = f"qtav {owner_qtav} {tag_qtav}"; generated_successfully = True; state_changed = False
                elif cmd_type == "qtvs":
                    # qtvs usually targets non-empty tags, but can be called on any
                    owner_qtvs, tag_qtvs = get_random_tag_owner_and_tag()
                    # Fallback if no tags exist
                    if owner_qtvs is None:
                         owner_qtvs = get_existing_person_id()
                         if owner_qtvs is not None: tag_qtvs = random.randint(0, max_tag_id)

                    if owner_qtvs is not None and tag_qtvs is not None:
                        cmd = f"qtvs {owner_qtvs} {tag_qtvs}"; generated_successfully = True; state_changed = False
                elif cmd_type == "qba":
                     person_qba = None
                     # Try forcing person with no acquaintances if requested
                     if force_qba_empty:
                         person_qba = get_person_with_no_acquaintances()
                     # Otherwise, prefer person with degree > 0, but allow 0 sometimes
                     if person_qba is None:
                         if random.random() < 0.95: # High chance to pick someone with neighbors
                             person_qba = get_random_person(require_degree_greater_than=0)
                         if person_qba is None: # Fallback to any person
                             person_qba = get_existing_person_id()

                     if person_qba is not None:
                          cmd = f"qba {person_qba}"; generated_successfully = True; state_changed = False
                elif cmd_type == "qcs":
                     cmd = "qcs"; generated_successfully = True; state_changed = False
                elif cmd_type == "qsp":
                    p1_qsp, p2_qsp = None, None
                    # Prefer pairs known to have a path
                    if random.random() < 0.8:
                        p1_qsp, p2_qsp = get_pair_with_path()
                    else: # Fallback to random pair
                        p1_qsp, p2_qsp = get_two_random_persons(require_different=True)

                    # Ensure we got a valid pair
                    if p1_qsp is None or p2_qsp is None:
                        p1_qsp, p2_qsp = get_two_random_persons(require_different=True)

                    if p1_qsp is not None and p2_qsp is not None and p1_qsp != p2_qsp:
                         cmd = f"qsp {p1_qsp} {p2_qsp}"; generated_successfully = True; state_changed = False
                elif cmd_type == "qbc":
                     # Prefer accounts with followers/contributions if possible
                     account_qbc = get_random_account_with_followers()
                     if account_qbc is None: # Fallback to any account
                         account_qbc = get_random_account_id()

                     if account_qbc is not None:
                         cmd = f"qbc {account_qbc}"; generated_successfully = True; state_changed = False
                elif cmd_type == "qra":
                     # Just needs any existing person
                     person_qra = get_existing_person_id()
                     if person_qra is not None:
                          cmd = f"qra {person_qra}"; generated_successfully = True; state_changed = False
                # HW11 Queries
                elif cmd_type == "qsv":
                    person_qsv = get_existing_person_id()
                    if person_qsv is not None:
                        cmd = f"qsv {person_qsv}"; generated_successfully = True; state_changed = False
                elif cmd_type == "qrm":
                    person_qrm = get_existing_person_id()
                    if person_qrm is not None:
                        cmd = f"qrm {person_qrm}"; generated_successfully = True; state_changed = False
                elif cmd_type == "qp":
                    # Needs an existing emoji
                    emoji_id_qp = get_random_emoji_id()
                    if emoji_id_qp is not None:
                         cmd = f"qp {emoji_id_qp}"; generated_successfully = True; state_changed = False
                    # else: # No emojis exist, cannot generate qp
                    #     pass
                elif cmd_type == "qm":
                    person_qm = get_existing_person_id()
                    if person_qm is not None:
                         cmd = f"qm {person_qm}"; generated_successfully = True; state_changed = False

            except Exception as e_norm:
                # print(f"ERROR during normal generation attempt for {cmd_type}: {e_norm}", file=sys.stderr)
                # traceback.print_exc(file=sys.stderr) # More detail if needed
                generated_successfully = False # Ensure command isn't added
                cmd = None
                # Allow the loop to continue and try generating a different command

        # --- Append Command and Update Counts ---
        if generated_successfully and cmd:
            # Don't add 'ln' again if it was the initial command
            if cmd_type != 'ln':
                generated_cmds_list.append(cmd)
                cmd_counts[cmd_type] += 1
                commands_generated_this_run += 1
                if phases_config:
                     commands_in_current_phase += 1
            # else: handled at start

        # Safety break to prevent infinite loops if state prevents progress
        # (e.g., cannot add person, cannot add relation, etc.)
        # Check if we failed to generate *any* command in the last N attempts
        # This requires tracking attempts, let's simplify: check if weights got empty
        if not active_weights_dict and not generated_successfully and cmd_type != 'ap':
             # print("Error: Stuck! No commands possible or generated. Breaking loop.", file=sys.stderr)
             break # Exit loop if truly stuck


    # --- Supplementary Query Generation ---
    # print("INFO: Starting supplementary query generation phase.", file=sys.stderr)
    min_counts_map = {
        "qci": min_qci, "qts": min_qts, "qtav": min_qtav, "qba": min_qba,
        "qcs": min_qcs, "qsp": min_qsp, "qtvs": min_qtvs, "qbc": min_qbc, "qra": min_qra,
        # HW11 mins
        "qsv": min_qsv, "qrm": min_qrm, "qp": min_qp, "qm": min_qm
    }
    supplementary_cmds_list = []
    supplementary_cmds_count = 0

    # Use 'statistics' if available for median calculation in dce fallback
    try:
        import statistics
    except ImportError:
        statistics = None # Fallback if module not available

    for query_type_supp, min_req_supp in min_counts_map.items():
        needed_supp = min_req_supp - cmd_counts.get(query_type_supp, 0)
        if needed_supp <= 0: continue

        # print(f"DEBUG: Need {needed_supp} more '{query_type_supp}' commands.", file=sys.stderr)
        attempts_supp_loop = 0
        # Allow more attempts for supplementary generation
        max_attempts_supp_loop = needed_supp * 10 + 30
        generated_supp_count = 0

        while generated_supp_count < needed_supp and attempts_supp_loop < max_attempts_supp_loop:
            cmd_supp = None
            attempts_supp_loop += 1
            # Wrap generation in try-except
            try:
                # Use existing query generation logic (normal path, not exception path)
                if query_type_supp == "qci":
                     p1_supp, p2_supp = get_two_random_persons(require_different=True)
                     if p1_supp is not None and p2_supp is not None: cmd_supp = f"qci {p1_supp} {p2_supp}"
                elif query_type_supp == "qts": cmd_supp = "qts"
                elif query_type_supp == "qtav":
                    owner_supp, tag_supp = get_random_tag_owner_and_tag() # Get any tag
                    if owner_supp is None and persons : owner_supp = get_existing_person_id() # Fallback owner
                    if owner_supp is not None :
                        if tag_supp is None: tag_supp = random.randint(0, max_tag_id) # Fallback tag ID
                        cmd_supp = f"qtav {owner_supp} {tag_supp}"
                elif query_type_supp == "qtvs":
                    owner_supp_vs, tag_supp_vs = get_random_tag_owner_and_tag() # Get any tag
                    if owner_supp_vs is None and persons: owner_supp_vs = get_existing_person_id() # Fallback owner
                    if owner_supp_vs is not None :
                        if tag_supp_vs is None: tag_supp_vs = random.randint(0, max_tag_id) # Fallback tag ID
                        cmd_supp = f"qtvs {owner_supp_vs} {tag_supp_vs}"
                elif query_type_supp == "qba":
                    person_supp = get_existing_person_id() # Get any person
                    if person_supp is not None: cmd_supp = f"qba {person_supp}"
                elif query_type_supp == "qcs": cmd_supp = "qcs"
                elif query_type_supp == "qsp":
                    p1_sp_supp, p2_sp_supp = get_two_random_persons(require_different=True) # Get any pair
                    if p1_sp_supp is not None and p2_sp_supp is not None and p1_sp_supp != p2_sp_supp:
                        cmd_supp = f"qsp {p1_sp_supp} {p2_sp_supp}"
                elif query_type_supp == "qbc":
                    account_supp = get_random_account_id() # Get any account
                    if account_supp is not None: cmd_supp = f"qbc {account_supp}"
                elif query_type_supp == "qra":
                    person_ra_supp = get_existing_person_id() # Get any person
                    if person_ra_supp is not None: cmd_supp = f"qra {person_ra_supp}"
                # HW11 supplementary queries
                elif query_type_supp == "qsv":
                    person_qsv_supp = get_existing_person_id()
                    if person_qsv_supp is not None: cmd_supp = f"qsv {person_qsv_supp}"
                elif query_type_supp == "qrm":
                    person_qrm_supp = get_existing_person_id()
                    if person_qrm_supp is not None: cmd_supp = f"qrm {person_qrm_supp}"
                elif query_type_supp == "qp":
                    emoji_id_qp_supp = get_random_emoji_id() # Get any emoji
                    if emoji_id_qp_supp is not None: cmd_supp = f"qp {emoji_id_qp_supp}"
                elif query_type_supp == "qm":
                    person_qm_supp = get_existing_person_id()
                    if person_qm_supp is not None: cmd_supp = f"qm {person_qm_supp}"

            except Exception as e_supp:
                 # print(f"Error generating supplementary cmd {query_type_supp}: {e_supp}", file=sys.stderr)
                 cmd_supp = None # Ensure failed generation doesn't proceed

            # If a valid command was generated for the supplementary query
            if cmd_supp:
                supplementary_cmds_list.append(cmd_supp)
                generated_supp_count += 1
                supplementary_cmds_count += 1
                cmd_counts[query_type_supp] += 1 # Update count immediately

        # Warning if minimum not met
        if generated_supp_count < needed_supp:
             # print(f"Warning: Could not meet minimum for {query_type_supp}. Needed {needed_supp}, generated {generated_supp_count} supplementary.", file=sys.stderr)
             pass # Silently ignore if minimums not met

    # print(f"INFO: Added {supplementary_cmds_count} supplementary query commands.", file=sys.stderr)
    generated_cmds_list.extend(supplementary_cmds_list)
    # Counts are already updated within the loop


    return generated_cmds_list, cmd_counts


# --- Argument Parsing (Added HW11 args) ---
if __name__ == "__main__":
    # Use statistics module if available for dce limit generation
    try:
        import statistics
    except ImportError:
        statistics = None # Will handle absence later

    parser = argparse.ArgumentParser(description="Generate test data for HW11 social network.")
    # Core Controls
    parser.add_argument("-n", "--num_commands", type=int, default=3000, help="Target number of commands (ignored if --phases is set).") # Increased default
    parser.add_argument("--max_person_id", type=int, default=200, help="Maximum person ID (0 to max).")
    parser.add_argument("--max_tag_id", type=int, default=20, help="Maximum tag ID (0 to max).")
    parser.add_argument("--max_account_id", type=int, default=60, help="Maximum official account ID (0 to max).")
    parser.add_argument("--max_article_id", type=int, default=600, help="Maximum article ID (0 to max).")
    parser.add_argument("--max_message_id", type=int, default=3000, help="Maximum message ID (0 to max).") # HW11
    parser.add_argument("--max_emoji_id", type=int, default=120, help="Maximum emoji ID (0 to max).") # HW11
    parser.add_argument("--max_age", type=int, default=200, help="Maximum person age (default 200).")
    parser.add_argument("-o", "--output_file", type=str, default=None, help="Output file name (default: stdout).")
    parser.add_argument("--hce", action='store_true', help="Enable HCE constraints (Mutual Test limits: N_cmds<=3000, max_person_id<=99, values<=200).")
    parser.add_argument("--seed", type=int, default=None, help="Seed for the random number generator.")
    parser.add_argument("--approx", action='store_true', help="Enable approximation mode for high density scenarios (e.g., finding non-existent relations/paths faster).")


    # Relation/Value/Money Controls
    parser.add_argument("--max_rel_value", type=int, default=200, help="Maximum initial relation value (default 200).")
    parser.add_argument("--max_mod_value", type=int, default=200, help="Maximum absolute modify relation value change (default 200).")
    parser.add_argument("--mr_delete_ratio", type=float, default=0.15, help="Approx. ratio of 'mr' commands targeting relation deletion (0.0-1.0).")
    parser.add_argument("--max_rem_money", type=int, default=200, help="Maximum money for RedEnvelopeMessage (default 200).") # HW11

    # Graph Structure Controls
    parser.add_argument("--density", type=float, default=0.05, help="Target graph density (0.0-1.0). Used by 'ln' or guides 'ar'.")
    parser.add_argument("--max_degree", type=int, default=None, help="Attempt to limit the maximum degree of any person (checked during 'ar' and 'ln').")
    parser.add_argument("--hub_bias", type=float, default=0.0, help="Probability (0.0-1.0) for 'ar' to connect to a designated hub node.")
    parser.add_argument("--num_hubs", type=int, default=5, help="Number of initial person IDs (0 to N-1) to potentially treat as hubs.")

    # ln Setup Controls
    parser.add_argument("--use_ln_setup", action='store_true', help="Use 'ln' command for initial potentially dense network setup.")
    parser.add_argument("--ln_nodes", type=int, default=50, help="Number of nodes for 'ln' setup (if --use_ln_setup).")
    parser.add_argument("--ln_default_value", type=int, default=10, help="Default relation value for edges created by 'ln' (if --use_ln_setup).")


    # Focus Controls (Approximate ratios)
    parser.add_argument("--tag_focus", type=float, default=0.15, help="Approx. target ratio of commands related to tags (0.0-1.0).")
    parser.add_argument("--account_focus", type=float, default=0.15, help="Approx. target ratio of commands related to accounts/articles (0.0-1.0).")
    parser.add_argument("--message_focus", type=float, default=0.30, help="Approx. target ratio of commands related to messages/emojis (0.0-1.0).") # HW11 Focus
    parser.add_argument("--max_tag_size", type=int, default=50, help="Attempt to limit the max number of persons in a tag (checked during 'att', up to JML limit 1000).")

    # Query & Exception Controls
    parser.add_argument("--qci_focus", choices=['mixed', 'close', 'far'], default='mixed', help="Influence 'qci' pair selection (close=path, far=no path).")
    # HW9/10 Minimums
    parser.add_argument("--min_qci", type=int, default=5, help="Minimum number of qci commands.")
    parser.add_argument("--min_qts", type=int, default=2, help="Minimum number of qts commands.")
    parser.add_argument("--min_qtav", type=int, default=5, help="Minimum number of qtav commands.")
    parser.add_argument("--min_qtvs", type=int, default=5, help="Minimum number of qtvs commands.")
    parser.add_argument("--min_qba", type=int, default=3, help="Minimum number of qba commands.")
    parser.add_argument("--min_qcs", type=int, default=2, help="Minimum number of qcs commands.")
    parser.add_argument("--min_qsp", type=int, default=3, help="Minimum number of qsp commands.")
    parser.add_argument("--min_qbc", type=int, default=3, help="Minimum number of qbc commands.")
    parser.add_argument("--min_qra", type=int, default=3, help="Minimum number of qra commands.")
    # HW11 Minimums
    parser.add_argument("--min_qsv", type=int, default=5, help="Minimum number of qsv commands.")
    parser.add_argument("--min_qrm", type=int, default=5, help="Minimum number of qrm commands.")
    parser.add_argument("--min_qp", type=int, default=4, help="Minimum number of qp commands.")
    parser.add_argument("--min_qm", type=int, default=5, help="Minimum number of qm commands.")

    parser.add_argument("--exception_ratio", type=float, default=0.08, help="Probability (0.0-1.0) to attempt generating an exception-causing command.")
    parser.add_argument("--force_qba_empty_ratio", type=float, default=0.02, help="Probability (0.0-1.0) for normal 'qba' to target person with no acquaintances.")
    parser.add_argument("--force_qtav_empty_ratio", type=float, default=0.02, help="Probability (0.0-1.0) for normal 'qtav' to target an empty tag.")

    # Generation Flow Control
    parser.add_argument("--phases", type=str, default=None, help="Define generation phases, e.g., 'build:500,query:1000,message_heavy:500'. Overrides -n.")

    args = parser.parse_args()
 # --- Load Phase Definitions from phases.json ---
    # LOADED_PHASE_DEFINITIONS is global and will be filled here.
    phases_json_path = os.path.join(os.path.dirname(__file__), "phases.json")
    try:
        with open(phases_json_path, 'r') as f:
            loaded_data = json.load(f)
            if isinstance(loaded_data, dict):
                LOADED_PHASE_DEFINITIONS.update(loaded_data) # Populate the global dict
                print(f"INFO: Successfully loaded phase definitions from '{phases_json_path}'.", file=sys.stderr)
                # print(f"DEBUG: Loaded phases: {list(LOADED_PHASE_DEFINITIONS.keys())}", file=sys.stderr)

                # Ensure 'default' phase exists if not in JSON; it will use pure BASE_WEIGHTS
                if 'default' not in LOADED_PHASE_DEFINITIONS:
                    LOADED_PHASE_DEFINITIONS['default'] = {} # Represents using BASE_WEIGHTS unmodified
                    print(f"INFO: 'default' phase not in JSON, will use base weights.", file=sys.stderr)

            else:
                print(f"Warning: '{phases_json_path}' does not contain a valid JSON object (dictionary). No custom phases loaded. 'default' phase will use base weights.", file=sys.stderr)
                LOADED_PHASE_DEFINITIONS['default'] = {} # Ensure default exists
    except FileNotFoundError:
        print(f"INFO: '{phases_json_path}' not found. Only 'default' phase (using base weights) will be available unless specified in --phases.", file=sys.stderr)
        LOADED_PHASE_DEFINITIONS['default'] = {} # Ensure default exists
    except json.JSONDecodeError as e:
        print(f"ERROR: Could not decode '{phases_json_path}': {e}. Only 'default' phase (using base weights) will be available.", file=sys.stderr)
        LOADED_PHASE_DEFINITIONS['default'] = {} # Ensure default exists
    except Exception as e:
        print(f"ERROR: An unexpected error occurred while loading '{phases_json_path}': {e}. Only 'default' phase (using base weights) will be available.", file=sys.stderr)
        LOADED_PHASE_DEFINITIONS['default'] = {}
    # --- Seed Initialization ---
    if args.seed is not None:
        random.seed(args.seed)
        # print(f"INFO: Using specified random seed: {args.seed}", file=sys.stderr)
    else:
        seed_val = random.randrange(sys.maxsize)
        random.seed(seed_val)
        print(f"INFO: Using generated random seed: {seed_val}", file=sys.stderr) # Print seed if generated

    # --- HCE Constraint Application ---
    if args.hce:
        # print("INFO: HCE mode enabled. Applying constraints.", file=sys.stderr)
        hce_max_n_cmds = 3000
        hce_max_pid_val = 99
        hce_max_val_param = 200

        # Cap num_commands first (needed for phase parsing check)
        original_target_n = args.num_commands
        if args.phases:
            try:
                _, total_phase_commands_val = parse_phases(args.phases)
                original_target_n = total_phase_commands_val
            except ValueError: pass # Ignore error here, handled later
        args.num_commands = min(original_target_n, hce_max_n_cmds)
        # print(f"HCE: num_commands capped at {args.num_commands}", file=sys.stderr)

        # Cap IDs and Values
        args.max_person_id = min(args.max_person_id, hce_max_pid_val)
        args.max_account_id = min(args.max_account_id, hce_max_pid_val)
        # Message/emoji/article IDs might not be strictly limited by HCE? Check spec. Assume they scale with persons/commands.
        args.max_message_id = min(args.max_message_id, args.num_commands * 2)
        args.max_emoji_id = min(args.max_emoji_id, hce_max_pid_val * 2)
        args.max_article_id = min(args.max_article_id, hce_max_pid_val * 5 if hce_max_pid_val > 0 else 500)
        args.max_tag_id = min(args.max_tag_id, hce_max_pid_val) # Tags often related to persons

        args.max_age = min(args.max_age, hce_max_val_param)
        args.max_rel_value = min(args.max_rel_value, hce_max_val_param)
        args.max_mod_value = min(args.max_mod_value, hce_max_val_param) # MR value change
        args.ln_default_value = min(args.ln_default_value, hce_max_val_param)
        args.max_rem_money = min(args.max_rem_money, hce_max_val_param) # Red envelope money
        # print(f"HCE: max_person_id={args.max_person_id}, max_value={hce_max_val_param}", file=sys.stderr)


    # --- Phase Parsing and Final Command Count ---
    phases_config_val = None
    if args.phases:
        try:
            phases_config_val, total_phase_cmds_val = parse_phases(args.phases)
            # If phases total exceeds HCE limit (which already capped args.num_commands), use the capped value.
            if args.hce and total_phase_cmds_val > args.num_commands:
                 # print(f"Warning: Phase total ({total_phase_cmds_val}) exceeds HCE limit ({args.num_commands}). Using HCE limit.", file=sys.stderr)
                 pass # args.num_commands is already capped
            # Otherwise, phases dictate the total number of commands.
            elif total_phase_cmds_val != args.num_commands:
                 # print(f"INFO: Overriding -n. Total commands from phases: {total_phase_cmds_val}", file=sys.stderr)
                 args.num_commands = total_phase_cmds_val

        except ValueError as e_phase:
            print(f"ERROR: Invalid --phases argument: {e_phase}. Exiting.", file=sys.stderr)
            sys.exit(1)

    # --- Validate Other Arguments ---
    if args.hub_bias > 0 and args.num_hubs <= 0:
        # print("Warning: hub_bias > 0 requires num_hubs > 0. Disabling hub_bias.", file=sys.stderr)
        args.hub_bias = 0
    if args.num_hubs > args.max_person_id + 1:
        # print(f"Warning: num_hubs ({args.num_hubs}) > max_person_id+1 ({args.max_person_id+1}). Clamping num_hubs.", file=sys.stderr)
        args.num_hubs = args.max_person_id + 1

    if args.use_ln_setup:
        if args.ln_nodes > args.max_person_id + 1:
            # print(f"Warning: ln_nodes ({args.ln_nodes}) > max_person_id+1 ({args.max_person_id+1}). Clamping ln_nodes.", file=sys.stderr)
            args.ln_nodes = args.max_person_id + 1
        if args.ln_nodes < 2 :
            # print("Warning: ln_nodes < 2. Disabling 'ln' setup.", file=sys.stderr)
            args.use_ln_setup = False


    # --- Setup Output Stream ---
    output_stream_val = None
    try:
        output_stream_val = open(args.output_file, 'w') if args.output_file else sys.stdout
        # print(f"INFO: Outputting to {'stdout' if output_stream_val is sys.stdout else args.output_file}", file=sys.stderr)

        # --- Clear All State Before Generation ---
        persons.clear(); relations.clear(); relation_values.clear()
        person_tags.clear(); tag_members.clear(); person_details.clear()
        person_degrees.clear(); person_neighbors.clear()
        official_accounts.clear(); account_details.clear(); account_followers.clear()
        account_articles.clear(); account_contributions.clear(); all_articles.clear()
        article_contributors.clear(); article_locations.clear(); person_received_articles.clear()
        article_names.clear()
        # HW11 State Clear
        messages.clear(); emoji_ids.clear(); emoji_heat.clear();
        person_money.clear(); person_social_value.clear(); person_received_messages.clear();

        # --- Generate Commands ---
        all_commands_list, final_cmd_counts_map = generate_commands(
            args.num_commands, args.max_person_id, args.max_tag_id,
            args.max_account_id, args.max_article_id,
            args.max_message_id, args.max_emoji_id, args.max_rem_money,
            args.max_rel_value, args.max_mod_value, args.max_age,
            args.min_qci, args.min_qts, args.min_qtav, args.min_qba,
            args.min_qcs, args.min_qsp, args.min_qtvs, args.min_qbc, args.min_qra,
            args.min_qsv, args.min_qrm, args.min_qp, args.min_qm,
            args.density, None, args.max_degree, # degree_focus unused
            args.tag_focus, args.account_focus, args.message_focus,
            args.max_tag_size, args.qci_focus,
            args.mr_delete_ratio, args.exception_ratio,
            args.force_qba_empty_ratio, args.force_qtav_empty_ratio,
            args.hub_bias, args.num_hubs,
            phases_config_val,
            args.hce,
            args.use_ln_setup, args.ln_nodes, args.ln_default_value,
            args.approx # Pass the approx flag
        )

        # --- Write Commands to Output ---
        # print(f"INFO: Writing {len(all_commands_list)} generated commands...", file=sys.stderr)
        for command_item in all_commands_list:
             # Ensure command is a string before stripping/writing
             if isinstance(command_item, str):
                 output_stream_val.write(command_item.strip() + '\n')
             else:
                 print(f"Warning: Generated non-string command item: {command_item}. Skipping.", file=sys.stderr)
        # print(f"INFO: Finished writing commands.", file=sys.stderr)


        # --- Debug Print Final Counts (Optional - uncomment to enable) ---
        print("--- Final Command Counts ---", file=sys.stderr)
        total_final_cmds = 0
        for cmd_type_final, count_final in sorted(final_cmd_counts_map.items()):
            print(f"{cmd_type_final}: {count_final}", file=sys.stderr)
            total_final_cmds += count_final
        print(f"Total commands generated (counted): {total_final_cmds}", file=sys.stderr)
        print(f"Total commands in list (output): {len(all_commands_list)}", file=sys.stderr)
        print("--- Final State Summary ---", file=sys.stderr)
        print(f"Persons: {len(persons)}, Relations: {len(relations)}", file=sys.stderr)
        print(f"Tags: {sum(len(t) for t in person_tags.values())} (across {len(person_tags)} owners)", file=sys.stderr)
        print(f"Accounts: {len(official_accounts)}, Articles: {len(all_articles)}", file=sys.stderr)
        print(f"Pending Messages: {len(messages)}, Stored Emojis: {len(emoji_ids)}", file=sys.stderr)


    except Exception as main_e:
        print(f"\n!!! UNEXPECTED ERROR DURING GENERATION !!!", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    finally:
        # Ensure output file is closed if it was opened
        if args.output_file and output_stream_val is not None and output_stream_val is not sys.stdout:
            output_stream_val.close()
            # print(f"INFO: Closed output file '{args.output_file}'.", file=sys.stderr)


# --- END OF FULL MODIFIED FILE gen.py ---