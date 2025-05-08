# --- START OF MODIFIED FILE gen.py ---

import random
import argparse
import os
import sys
import math
from contextlib import redirect_stdout
from collections import defaultdict, deque # deque for BFS
import traceback # For debugging exceptions during generation

# --- State Tracking ---
# HW9 State
persons = set() # {person_id, ...}
relations = set() # {(person_id1, person_id2), ...} where id1 < id2
relation_values = {} # {(person_id1, person_id2): value, ...} where id1 < id2
person_tags = defaultdict(set) # {person_id: {tag_id1, tag_id2, ...}, ...}
tag_members = defaultdict(set) # {(owner_person_id, tag_id): {member_person_id1, ...}, ...}
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
article_names = {} # {article_id: name, ...}  <<<<< ADDED FOR ARTICLE NAME TRACKING
person_received_articles = defaultdict(list) # {person_id: [article_id1, article_id2, ...], ...} In order received


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

    for i in range(max_person_id + 1):
        if i not in persons:
            return i
    if max_possible_id_in_state < max_person_id:
        return max_possible_id_in_state + 1

    return -1

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
    return get_random_relation()

def get_non_existent_relation_pair(approx_mode=False): # Added approx_mode
    num_persons_val = len(persons)
    if num_persons_val < 2:
        return None, None

    max_possible_edges_val = (num_persons_val * (num_persons_val - 1)) // 2
    current_num_relations = len(relations)

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

    if approx_mode and is_very_dense:
        # Reduce attempts significantly in approx mode for very dense graphs
        max_attempts_val = min(max_attempts_val, num_persons_val // 3 + 10, 25)
        # if max_attempts_val < 25: # For debugging
        #     print(f"DEBUG:[approx] get_non_existent_relation_pair, dense ({current_density_val:.2f}), attempts: {max_attempts_val}", file=sys.stderr)


    for _ in range(max_attempts_val):
        if len(person_list_val) < 2: break # Should not happen if num_persons_val >=2
        p1, p2 = random.sample(person_list_val, 2)
        if p2 not in person_neighbors.get(p1, set()):
            return p1, p2

    # Fallback scan
    if approx_mode and is_very_dense:
        # print(f"DEBUG:[approx] Skipping fallback scan in get_non_existent_relation_pair for dense graph.", file=sys.stderr)
        return None, None # Give up early in approx mode if random attempts fail for very dense graph

    # Original fallback scan for non-approx mode or not-so-dense graphs
    # print(f"Warning: Fallback scan in get_non_existent_relation_pair (dense: {current_density_val:.2f}, approx: {approx_mode})", file=sys.stderr)
    if num_persons_val >= 2:
        cand_p1_list_val = random.sample(person_list_val, min(num_persons_val, 10)) # Reduced scan candidates

        for p1_scan in cand_p1_list_val:
            others_list_val = [p for p in person_list_val if p != p1_scan]
            if not others_list_val:
                continue

            cand_p2_list_val = random.sample(others_list_val, min(len(others_list_val), 10)) # Reduced scan candidates
            for p2_scan in cand_p2_list_val:
                if p2_scan not in person_neighbors.get(p1_scan, set()):
                    return p1_scan, p2_scan

    # print(f"Warning: get_non_existent_relation_pair truly failed after random and scan.", file=sys.stderr)
    return None, None

# --- Path/Circle Helpers (Using optimized BFS) ---
def check_path_exists(start_node, end_node):
    if start_node == end_node: return True
    if start_node not in persons or end_node not in persons: return False

    q = deque([start_node])
    visited = {start_node}
    while q:
        curr = q.popleft()
        if curr == end_node:
            return True
        neighbors_of_curr = person_neighbors.get(curr, set())
        for neighbor in neighbors_of_curr:
            if neighbor in persons and neighbor not in visited:
                visited.add(neighbor)
                q.append(neighbor)
    return False

def get_pair_with_path(): # approx_mode not relevant here as we *want* a path
    if len(persons) < 2 or not relations: return None, None
    attempts = 0
    max_attempts = len(persons) * 3
    person_list_val = list(persons)

    while attempts < max_attempts:
        if relations and random.random() < 0.5:
            p1, p2 = get_existing_relation()
            if p1 is not None and p2 is not None: return p1, p2

        if len(person_list_val) >=2:
            p1, p2 = get_two_random_persons(require_different=True)
            if p1 is not None and p2 is not None:
                 if check_path_exists(p1, p2):
                    return p1, p2
        attempts += 1

    return get_existing_relation()


def get_pair_without_path(approx_mode=False): # Added approx_mode
     num_persons_val = len(persons)
     if num_persons_val < 2:
         return None, None

     current_max_possible_edges = (num_persons_val * (num_persons_val - 1)) // 2 if num_persons_val > 1 else 0
     current_density_val = 0.0
     if current_max_possible_edges > 0 :
         current_density_val = len(relations) / current_max_possible_edges

     is_very_dense = current_density_val > 0.9

     if approx_mode and is_very_dense:
        # print(f"DEBUG:[approx] get_pair_without_path (density: {current_density_val:.2f}).", file=sys.stderr)
        # In very dense approx mode, if a non-relation exists, *assume* it has no path.
        p1_ner, p2_ner = get_non_existent_relation_pair(approx_mode=True)
        if p1_ner is not None and p2_ner is not None:
            # print(f"DEBUG:[approx] returning non-existent relation {p1_ner}-{p2_ner}, assuming no path.", file=sys.stderr)
            return p1_ner, p2_ner
        else:
            # If get_non_existent_relation_pair returns None (clique/near-clique in approx), then no pair without path.
            # print(f"DEBUG:[approx] no non-existent relation found, assuming clique, no pair without path.", file=sys.stderr)
            return None, None

     # --- Original logic for non-approx mode or not very_dense ---
     max_bfs_attempts = num_persons_val
     if current_density_val > 0.85 and num_persons_val > 50:
         max_bfs_attempts = max(10, int(num_persons_val * 0.1))
     elif current_density_val > 0.7:
         max_bfs_attempts = max(15, int(num_persons_val * 0.5))

     person_list_val = list(persons)

     for _ in range(min(5, max_bfs_attempts // 2 + 1)):
         p1_ner, p2_ner = get_non_existent_relation_pair(approx_mode=False) # Not approx here, we need real non-relation if possible
         if p1_ner is not None and p2_ner is not None:
             if not check_path_exists(p1_ner, p2_ner):
                 return p1_ner, p2_ner
         elif num_persons_val > 1 :
            # print(f"DEBUG: get_non_existent_relation_pair returned None; graph likely clique. Aborting get_pair_without_path.", file=sys.stderr)
            return None, None

     for _ in range(max_bfs_attempts):
         if len(person_list_val) < 2: break
         p1, p2 = get_two_random_persons(require_different=True)
         if p1 is None or p2 is None: continue

         if not check_path_exists(p1, p2):
             return p1, p2

     # print(f"Warning: Fallback in get_pair_without_path after {max_bfs_attempts} BFS (density: {current_density_val:.2f}, approx: {approx_mode}).", file=sys.stderr)
     p1_f, p2_f = get_non_existent_relation_pair(approx_mode=False) # Try to give *something*
     if p1_f is not None and p2_f is not None:
         return p1_f, p2_f

     if num_persons_val >=2:
        p1_final, p2_final = get_two_random_persons(require_different=True)
        if p1_final is not None and p2_final is not None:
            return p1_final, p2_final

     return None, None


# --- Tag Helpers ---
def get_random_tag_owner_and_tag(owner_id_limit=None, require_non_empty=False):
    eligible_owners = get_eligible_persons(owner_id_limit)
    owners_with_tags = []
    for pid in eligible_owners:
        tags_for_pid = person_tags.get(pid)
        if tags_for_pid:
            for tag_id in tags_for_pid:
                 if not require_non_empty or tag_members.get((pid, tag_id)):
                     owners_with_tags.append((pid, tag_id))
    if not owners_with_tags: return None, None
    owner_id, tag_id = random.choice(owners_with_tags)
    return owner_id, tag_id

def get_non_existent_tag_id(person_id, max_tag_id):
     if person_id not in persons: return random.randint(0, max_tag_id)
     existing_tags = person_tags.get(person_id, set())
     if len(existing_tags) > max_tag_id + 1 : return max_tag_id + random.randint(1,5)
     attempts = 0
     max_attempts = max(len(existing_tags) * 2, 20)
     search_range_max = max_tag_id + 10
     while attempts < max_attempts:
          tag_id = random.randint(0, search_range_max)
          if tag_id > max_tag_id : tag_id = random.randint(0, max_tag_id)

          if tag_id not in existing_tags:
               return tag_id
          attempts += 1
     for i in range(max_tag_id + 1):
         if i not in existing_tags:
             return i
     return max_tag_id + random.randint(1,5)

def get_random_member_in_tag(owner_id, tag_id):
    tag_key = (owner_id, tag_id)
    members = tag_members.get(tag_key, set())
    return random.choice(list(members)) if members else None

def get_related_person_not_in_tag(owner_id, tag_id):
    if owner_id is None or tag_id is None or owner_id not in person_neighbors: return None
    related_persons = person_neighbors.get(owner_id, set())
    tag_key = (owner_id, tag_id)
    current_members = tag_members.get(tag_key, set())
    possible_members = list(related_persons - {owner_id} - current_members)
    return random.choice(possible_members) if possible_members else None

def get_person_not_in_tag(owner_id, tag_id):
    tag_key = (owner_id, tag_id)
    current_members = tag_members.get(tag_key, set())
    non_members = list(persons - current_members - {owner_id})
    return random.choice(non_members) if non_members else None

def get_random_empty_tag():
    empty_tags = []
    for (owner_id, tag_id), members in tag_members.items():
         if owner_id in persons and tag_id in person_tags.get(owner_id, set()):
             if not members:
                 empty_tags.append((owner_id, tag_id))
    return random.choice(empty_tags) if empty_tags else (None, None)

def get_person_with_no_acquaintances():
     zero_degree_persons = [pid for pid in persons if person_degrees.get(pid, 0) == 0]
     return random.choice(zero_degree_persons) if zero_degree_persons else None

# --- HW10 Account/Article Helpers ---
def get_random_account_id():
    return random.choice(list(official_accounts)) if official_accounts else None

def get_non_existent_account_id(max_account_id):
    if not official_accounts: return random.randint(0, max_account_id)
    attempts = 0
    max_attempts = max(len(official_accounts) * 2, 20)
    max_possible_id_in_state = max(list(official_accounts)) if official_accounts else -1
    search_range_max = max(max_account_id + 10, max_possible_id_in_state + 10)

    while attempts < max_attempts:
        if random.random() < 0.7 and max_possible_id_in_state >= 0:
             aid = random.randint(max(0, max_possible_id_in_state - 5), max_possible_id_in_state + 10)
        else:
             aid = random.randint(0, search_range_max)

        if aid > max_account_id: aid = random.randint(0, max_account_id)

        if aid >= 0 and aid not in official_accounts:
            return aid
        attempts += 1

    for i in range(max_account_id + 1):
        if i not in official_accounts:
            return i
    return -1

def get_account_owner(account_id):
    return account_details.get(account_id, {}).get('owner')

def get_random_follower(account_id):
    followers = account_followers.get(account_id, set())
    return random.choice(list(followers)) if followers else None

def get_person_not_following(account_id):
    if account_id not in official_accounts: return get_existing_person_id()
    followers = account_followers.get(account_id, set())
    non_followers = list(persons - followers)
    return random.choice(non_followers) if non_followers else None

def get_random_account_with_followers():
     accounts_with_followers = [acc_id for acc_id in official_accounts if account_followers.get(acc_id)]
     return random.choice(accounts_with_followers) if accounts_with_followers else None

def get_random_account_and_follower():
    acc_id = get_random_account_with_followers()
    if acc_id:
        follower_id = get_random_follower(acc_id)
        return acc_id, follower_id
    return None, None

def get_random_article_id():
    return random.choice(list(all_articles)) if all_articles else None

def get_non_existent_article_id(max_article_id):
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

    for i in range(max_article_id + 1):
        if i not in all_articles:
            return i
    return -1

def get_random_article_in_account(account_id):
    articles_in_acc = account_articles.get(account_id, set())
    return random.choice(list(articles_in_acc)) if articles_in_acc else None

def get_random_account_with_articles():
    acc_with_articles = [acc_id for acc_id, arts in account_articles.items() if arts]
    return random.choice(acc_with_articles) if acc_with_articles else None

def get_random_account_and_article():
    acc_id = get_random_account_with_articles()
    if acc_id:
        article_id = get_random_article_in_account(acc_id)
        return acc_id, article_id
    return None, None

def get_contributor_of_article(article_id):
     return article_contributors.get(article_id)

def get_account_of_article(article_id):
    return article_locations.get(article_id)


# --- State Update Functions (Maintain person_neighbors) ---

# --- Person/Relation/Tag State ---
def add_person_state(person_id, name, age):
    if person_id not in persons:
        persons.add(person_id)
        person_details[person_id] = {'name': name, 'age': age}
        person_degrees[person_id] = 0
        person_received_articles[person_id] = []
        person_neighbors[person_id] = set()
        return True
    return False

def add_relation_state(id1, id2, value, max_degree=None):
    if id1 not in persons or id2 not in persons:
        return False
    if id1 == id2 or (min(id1, id2), max(id1, id2)) in relations:
         return False
    if max_degree is not None:
        if person_degrees.get(id1, 0) >= max_degree or person_degrees.get(id2, 0) >= max_degree:
            return False

    p1_key, p2_key = min(id1, id2), max(id1, id2)
    rel_key = (p1_key, p2_key)
    relations.add(rel_key)
    relation_values[rel_key] = value
    person_degrees[id1] = person_degrees.get(id1, 0) + 1
    person_degrees[id2] = person_degrees.get(id2, 0) + 1
    person_neighbors[id1].add(id2)
    person_neighbors[id2].add(id1)
    return True

def remove_relation_state(id1, id2):
    if id1 == id2: return False
    p1_orig, p2_orig = id1, id2
    p1_key, p2_key = min(id1, id2), max(id1, id2)
    rel_key = (p1_key, p2_key)
    if rel_key in relations:
        relations.remove(rel_key)
        if rel_key in relation_values: del relation_values[rel_key]
        if p1_orig in person_degrees: person_degrees[p1_orig] -= 1
        if p2_orig in person_degrees: person_degrees[p2_orig] -= 1

        if id1 in person_neighbors: person_neighbors[id1].discard(id2)
        if id2 in person_neighbors: person_neighbors[id2].discard(id1)

        tags_to_check_p1 = list(person_tags.get(p1_orig, set()))
        for tag_id_p1 in tags_to_check_p1:
             tag_key_p1_owns = (p1_orig, tag_id_p1)
             if p2_orig in tag_members.get(tag_key_p1_owns, set()):
                 tag_members[tag_key_p1_owns].remove(p2_orig)
        tags_to_check_p2 = list(person_tags.get(p2_orig, set()))
        for tag_id_p2 in tags_to_check_p2:
             tag_key_p2_owns = (p2_orig, tag_id_p2)
             if p1_orig in tag_members.get(tag_key_p2_owns, set()):
                 tag_members[tag_key_p2_owns].remove(p1_orig)
        return True
    return False

def add_tag_state(person_id, tag_id):
    if person_id not in persons: return False
    if tag_id not in person_tags.get(person_id, set()):
        person_tags[person_id].add(tag_id)
        if (person_id, tag_id) not in tag_members:
             tag_members[(person_id, tag_id)] = set()
        return True
    return False

def remove_tag_state(person_id, tag_id):
    if person_id not in persons: return False
    if tag_id in person_tags.get(person_id, set()):
        person_tags[person_id].remove(tag_id)
        tag_key = (person_id, tag_id)
        if tag_key in tag_members:
            del tag_members[tag_key]
        return True
    return False

def add_person_to_tag_state(person_id1, person_id2, tag_id, max_tag_size):
    tag_key = (person_id2, tag_id)
    related = (person_id1 in persons and
               person_id2 in persons and
               person_id1 in person_neighbors.get(person_id2, set()))

    if not (person_id1 in persons and person_id2 in persons): return False
    if person_id1 == person_id2: return False
    if not related: return False
    if tag_id not in person_tags.get(person_id2, set()): return False
    if person_id1 in tag_members.get(tag_key, set()): return False

    current_size = len(tag_members.get(tag_key, set()))
    effective_max_size = 1000
    if max_tag_size is not None:
        effective_max_size = min(effective_max_size, max_tag_size)

    if current_size < effective_max_size:
        if tag_key not in tag_members: tag_members[tag_key] = set()
        tag_members[tag_key].add(person_id1)
        return True
    else:
        return False

def remove_person_from_tag_state(person_id1, person_id2, tag_id):
    if person_id1 not in persons: return False
    if person_id2 not in persons: return False
    if tag_id not in person_tags.get(person_id2, set()): return False
    tag_key = (person_id2, tag_id)
    if person_id1 not in tag_members.get(tag_key, set()): return False

    if tag_key in tag_members:
        tag_members[tag_key].remove(person_id1)
        return True
    return False


# --- HW10 State Updates (No direct relation to person_neighbors needed) ---
def create_official_account_state(person_id, account_id, name):
    if person_id not in persons: return False
    if account_id in official_accounts: return False

    official_accounts.add(account_id)
    account_details[account_id] = {'owner': person_id, 'name': name}
    account_followers[account_id] = {person_id}
    account_contributions[account_id] = defaultdict(int)
    account_contributions[account_id][person_id] = 0
    account_articles[account_id] = set()
    return True

def delete_official_account_state(person_id, account_id):
    if person_id not in persons: return False
    if account_id not in official_accounts: return False
    if account_details.get(account_id, {}).get('owner') != person_id: return False

    official_accounts.remove(account_id)
    if account_id in account_details: del account_details[account_id]
    if account_id in account_followers: del account_followers[account_id]
    if account_id in account_contributions: del account_contributions[account_id]

    articles_to_orphan = list(account_articles.get(account_id, set()))
    for art_id in articles_to_orphan:
         if art_id in article_locations and article_locations[art_id] == account_id:
              del article_locations[art_id]
         if art_id in article_names: # <<<<< CLEANUP ARTICLE NAME
              del article_names[art_id]


    if account_id in account_articles: del account_articles[account_id]
    return True

def contribute_article_state(person_id, account_id, article_id, article_name_param): # <<<<< ADDED article_name_param
    if person_id not in persons: return False
    if account_id not in official_accounts: return False
    if article_id in all_articles: return False
    if person_id not in account_followers.get(account_id, set()): return False

    all_articles.add(article_id)
    article_contributors[article_id] = person_id
    article_locations[article_id] = account_id
    article_names[article_id] = article_name_param # <<<<< STORE ARTICLE NAME
    account_articles[account_id].add(article_id)
    account_contributions[account_id][person_id] = account_contributions[account_id].get(person_id, 0) + 1

    current_followers = list(account_followers.get(account_id, set()))
    for follower_id in current_followers:
        if follower_id in person_received_articles:
            person_received_articles[follower_id].insert(0, article_id)
        else:
             person_received_articles[follower_id] = [article_id]
    return True

def delete_article_state(person_id, account_id, article_id):
    if person_id not in persons: return False
    if account_id not in official_accounts: return False
    if article_id not in all_articles or article_id not in account_articles.get(account_id, set()): return False
    if account_details.get(account_id, {}).get('owner') != person_id: return False

    if account_id in account_articles:
        account_articles[account_id].discard(article_id)

    if article_id in article_locations and article_locations[article_id] == account_id:
         del article_locations[article_id]

    if article_id in article_names: # <<<<< CLEANUP ARTICLE NAME
         del article_names[article_id]


    original_contributor = article_contributors.get(article_id)
    if original_contributor is not None and account_id in account_contributions:
        if original_contributor in account_contributions[account_id]:
            account_contributions[account_id][original_contributor] -= 1
            # Ensure it doesn't go negative if state is somehow inconsistent, though it shouldn't
            if account_contributions[account_id][original_contributor] < 0:
                account_contributions[account_id][original_contributor] = 0


    current_followers = list(account_followers.get(account_id, set()))
    for follower_id in current_followers:
        if follower_id in person_received_articles:
             new_received = [art for art in person_received_articles[follower_id] if art != article_id]
             person_received_articles[follower_id] = new_received
    
    # It's important to remove from all_articles and article_contributors last,
    # after all checks and updates related to its presence are done.
    if article_id in all_articles:
        all_articles.remove(article_id)
    if article_id in article_contributors:
        del article_contributors[article_id]

    return True


def follow_official_account_state(person_id, account_id):
    if person_id not in persons: return False
    if account_id not in official_accounts: return False
    if person_id in account_followers.get(account_id, set()): return False

    account_followers[account_id].add(person_id)
    if account_id not in account_contributions:
        account_contributions[account_id] = defaultdict(int)
    # Initialize contribution count for new follower if not already present (e.g. owner is auto-follower)
    if person_id not in account_contributions[account_id]:
        account_contributions[account_id][person_id] = 0
    return True


# --- Command Weights Setup ---
def get_command_weights(phase="default", tag_focus=0.3, account_focus=0.3):
    base_weights = {
        "ap": 10, "ar": 8, "mr": 8,
        "at": 6, "dt": 2, "att": 6, "dft": 3,
        "coa": 5, "doa": 1, "ca": 5, "da": 5, "foa": 6,
        "qv": 3, "qci": 3, "qts": 2, "qtav": 8, "qtvs": 8,
        "qba": 3, "qcs": 2, "qsp": 3, "qbc": 3, "qra": 4,
    }
    phase_weights = {
        "build": {**base_weights, "ap": 20, "ar": 15, "coa": 10, "foa": 8, "ca": 5, "at": 8, "att": 6,
                   "mr": 1, "dt": 1, "dft": 1, "doa": 0, "da": 0,
                   "qv": 3, "qci": 3, "qts": 1, "qtav": 2, "qba": 2, "qcs": 1, "qsp": 2, "qtvs": 2, "qbc": 1, "qra": 2},
        "query": {**base_weights, "ap": 1, "ar": 1, "mr": 1, "at":1, "dt": 1, "att": 1, "dft": 1,
                  "coa": 1, "doa": 1, "ca": 1, "da": 1, "foa": 1,
                   "qv": 15, "qci": 15, "qts": 8, "qtav": 12, "qba": 12, "qcs": 8, "qsp": 15, "qtvs": 12, "qbc": 10, "qra": 15},
        "modify":{**base_weights, "ap": 2, "ar": 3, "mr": 15, "at": 8, "dt": 8, "att": 12, "dft": 8,
                   "coa": 3, "doa": 5, "ca": 4, "da": 5, "foa": 5,
                   "qv": 5, "qci": 5, "qts": 2, "qtav": 5, "qba": 4, "qcs": 2, "qsp": 5, "qtvs": 5, "qbc": 3, "qra": 5},
        "churn": {**base_weights, "ap": 5, "ar": 10, "mr": 20, "at": 8, "dt": 12, "att": 8, "dft": 12,
                  "coa": 4, "doa": 15, "ca": 5, "da": 15, "foa": 6,
                  "qv": 3, "qci": 3, "qts": 1, "qtav": 3, "qba": 2, "qcs": 1, "qsp": 3, "qtvs": 3, "qbc": 2, "qra": 3},
        "default": base_weights,
                "build_hub_rels": {**base_weights, "ap": 10, "ar": 30, "mr": 2, "at": 2, "att": 2, "coa": 3, "foa": 2, "ca": 1,
                         "qv": 1, "qci": 1, "qts": 1, "qtav": 1, "qba": 1, "qcs": 0, "qsp": 1, "qtvs": 1, "qbc": 0, "qra": 1},
        "setup_hub_tag": {**base_weights, "ap": 1, "ar": 1, "at": 20, "att": 5, "coa": 2, "foa": 1},
        "fill_hub_tag": {**base_weights, "ap": 2, "ar": 5, "at": 5, "att": 30, "dft": 5, "coa": 1, "foa": 2},
        "fill_and_query": {**base_weights, "ap": 2, "ar": 5, "at": 5, "att": 15, "dft": 3, "coa": 3, "foa": 5, "ca": 3,
                           "qv": 10, "qci": 10, "qts": 5, "qtav": 10, "qba": 8, "qcs": 4, "qsp": 10, "qtvs": 10, "qbc": 5, "qra": 10},
        "test_limit": {**base_weights, "ap": 0, "ar": 0, "mr": 0, "at": 0, "dt": 0, "att": 5, "dft": 5, "coa": 1, "doa": 1, "ca": 1, "da": 1, "foa": 1,
                       "qv": 10, "qci": 10, "qts": 10, "qtav": 10, "qba": 10, "qcs": 10, "qsp": 10, "qtvs": 10, "qbc": 10, "qra": 10},
        "modify_tags": {**base_weights, "ap": 1, "ar": 1, "mr": 2, "at": 15, "dt": 15, "att": 25, "dft": 25,
                        "coa": 1, "foa": 1,
                        "qv": 3, "qci": 3, "qts": 1, "qtav": 5, "qba": 2, "qcs": 1, "qsp": 2, "qtvs": 5, "qbc": 1, "qra": 2},
        "modify_rels": {**base_weights, "ap": 1, "ar": 5, "mr": 30, "at": 2, "dt": 2, "att": 3, "dft": 3,
                        "coa": 1, "foa": 1,
                        "qv": 5, "qci": 5, "qts": 1, "qtav": 3, "qba": 3, "qcs": 1, "qsp": 3, "qtvs": 3, "qbc": 1, "qra": 2},
        "modify_accounts": {**base_weights, "ap": 1, "ar": 1, "mr": 2, "at": 2, "dt": 2, "att": 2, "dft": 2,
                            "coa": 10, "doa": 15, "ca": 15, "da": 15, "foa": 20, # Focus on accounts
                            "qv": 2, "qci": 2, "qts": 1, "qtav": 1, "qba": 1, "qcs": 1, "qsp": 2, "qtvs": 1, "qbc": 5, "qra": 5},
        "build_accounts_articles": {
             # High focus on creating accounts, followers, articles
            **base_weights, # Start with base, then override
            "ap": 5, "ar": 3, "mr": 1, "at": 2, "dt": 1, "att": 2, "dft": 1, # Low graph/tag ops
            "coa": 20,  # High
            "doa": 1,   # Very Low
            "ca": 30,   # Very High
            "da": 1,    # Very Low
            "foa": 15,  # High
            "qv": 1, "qci": 1, "qts": 1, "qtav": 1, "qba": 1, "qcs": 1, "qsp": 1, "qtvs": 1, # Low queries
            "qbc": 2,   # Low account queries
            "qra": 2,   # Low account queries
        },
        "delete_churn": {
            # High focus on deleting articles, moderate replenishment, low everything else
            **base_weights, # Start with base, then override
            "ap": 1, "ar": 1, "mr": 1, "at": 1, "dt": 1, "att": 1, "dft": 1, # Very low base ops
            "coa": 2,   # Low
            "doa": 0,   # EXTREMELY Low (Set to 0 if possible, or 1 if 0 causes issues)
            "ca": 15,  # Moderate replenishment <<<<<<<<< ADJUST THIS if 'da' runs out too fast
            "da": 60,   # EXTREMELY High <<<<<<<<<<<<<<<<
            "foa": 2,   # Low
            "qv": 1, "qci": 1, "qts": 1, "qtav": 1, "qba": 1, "qcs": 1, "qsp": 1, "qtvs": 1, # Low queries
            "qbc": 3,   # Low account queries (keep slightly > 0 for realism?)
            "qra": 3,   # Low account queries
        },
        "query_qtvs_heavy": {
            **base_weights, "ap": 0, "ar": 5, "mr": 10,
            "at": 1, "dt": 1, "att": 3, "dft": 3,
            "coa":0, "doa":0, "ca":0, "da":0, "foa":0,
            "qv": 1, "qci": 1, "qts": 0, "qtav": 1, "qba": 1, "qcs": 0, "qsp": 1,
            "qtvs": 100, # Very high
            "qbc": 0, "qra": 0
        },
        "dynamic_qtvs_churn": {
            **base_weights, "ap": 0, "ar": 3, "mr": 20, # High MR for changes
            "at": 2, "dt": 2, "att": 15, "dft": 15, # High ATT/DFT
            "coa":0, "doa":0, "ca":0, "da":0, "foa":0,
            "qv": 1, "qci": 1, "qts": 0, "qtav": 1, "qba": 1, "qcs": 0, "qsp": 1,
            "qtvs": 50, # Still high
            "qbc": 0, "qra": 0
        },
        "fill_many_tags": {
             **base_weights, "ap": 2, "ar": 5,
             "at": 30, "att": 25, # High for creating and filling many tags
             "dt": 2, "dft": 2,
             "qtvs": 5 # some queries
        },
        "query_many_tags": {
            **base_weights, "ap":1, "ar":1, "mr":1, "at":1, "dt":1, "att":1, "dft":1,
            "qtvs": 100 # Focus on querying various tags
        },
        "churn_tags_light": {
            **base_weights, "ap":1, "ar":2, "mr": 5,
            "at":10, "dt":10, "att":10, "dft":10, # Balanced tag ops
            "qtvs":15 # Query after ops
        }
    }
    current_weights = phase_weights.get(phase, phase_weights['default']).copy()

    tag_cmds = {"at", "dt", "att", "dft", "qtav", "qtvs"}
    account_cmds = {"coa", "doa", "ca", "da", "foa", "qbc", "qra"}

    total_weight_before_focus = sum(current_weights.values())
    if total_weight_before_focus == 0: return current_weights

    normalized_weights = {cmd: w / total_weight_before_focus for cmd, w in current_weights.items()}

    if tag_focus is not None:
        current_tag_prop = sum(normalized_weights.get(cmd, 0) for cmd in tag_cmds)
        other_prop = 1.0 - current_tag_prop

        if abs(current_tag_prop - tag_focus) > 0.01:
            scale_t = (tag_focus / current_tag_prop) if current_tag_prop > 1e-9 else (1.0 if tag_focus == 0 else 10.0)
            scale_o_for_tag = ((1.0 - tag_focus) / other_prop) if other_prop > 1e-9 else (1.0 if (1.0-tag_focus) == 0 else 0.1)

            for cmd in list(normalized_weights.keys()):
                if cmd in tag_cmds:
                    normalized_weights[cmd] *= scale_t
                else:
                    normalized_weights[cmd] *= scale_o_for_tag

    total_after_tag_focus = sum(normalized_weights.values())
    if total_after_tag_focus > 1e-9:
        normalized_weights = {cmd: w / total_after_tag_focus for cmd, w in normalized_weights.items()}
    else:
        if tag_focus > 0 and account_focus == 0:
             for cmd in tag_cmds: normalized_weights[cmd] = 1.0 / len(tag_cmds) if tag_cmds else 1.0

    if account_focus is not None:
        current_acc_prop = sum(normalized_weights.get(cmd, 0) for cmd in account_cmds)
        other_prop_acc = 1.0 - current_acc_prop

        if abs(current_acc_prop - account_focus) > 0.01:
            scale_a = (account_focus / current_acc_prop) if current_acc_prop > 1e-9 else (1.0 if account_focus == 0 else 10.0)
            scale_o_for_acc = ((1.0 - account_focus) / other_prop_acc) if other_prop_acc > 1e-9 else (1.0 if (1.0-account_focus) == 0 else 0.1)

            for cmd in list(normalized_weights.keys()):
                if cmd in account_cmds:
                    normalized_weights[cmd] *= scale_a
                else:
                    normalized_weights[cmd] *= scale_o_for_acc

    final_weights = {}
    for cmd in base_weights.keys():
        if base_weights[cmd] > 0:
            final_weights[cmd] = max(1, int(normalized_weights.get(cmd, 0) * 1000))
        else:
            final_weights[cmd] = 0

    return final_weights


# --- Phase Parsing ---
def parse_phases(phase_string):
    if not phase_string:
        return None, None
    phases = []
    total_commands = 0
    try:
        parts = phase_string.split(',')
        for part in parts:
            name_count = part.split(':')
            if len(name_count) != 2: raise ValueError(f"Invalid format in part: {part}")
            name, count_str = name_count
            count = int(count_str)
            if count <= 0: raise ValueError("Phase count must be positive")
            phases.append({'name': name.strip().lower(), 'count': count})
            total_commands += count
        return phases, total_commands
    except Exception as e:
        raise ValueError(f"Invalid phase string format: '{phase_string}'. Use 'name1:count1,name2:count2,...'. Error: {e}")


# --- Exception Generation Logic ---
def try_generate_exception_command(cmd_type, max_person_id, max_tag_id, max_account_id, max_article_id,
                                   target_density_unused, approx_active): # Renamed density to target_density_unused, added approx_active
    cmd = None
    target_exception = None

    try:
        if cmd_type == "ap":
            p_id = get_existing_person_id()
            if p_id is not None:
                name = generate_name(p_id)
                age = random.randint(1, 100)
                cmd = f"ap {p_id} {name} {age}"; target_exception = "EqualPersonIdException (ap)"
        elif cmd_type == "ar":
            if random.random() < 0.6 and relations:
                p1, p2 = get_existing_relation()
                if p1 is not None and p2 is not None :
                    value = random.randint(1, 100)
                    cmd = f"ar {p1} {p2} {value}"; target_exception = "EqualRelationException"
            else:
                p1 = get_existing_person_id()
                p2 = get_non_existent_person_id(max_person_id)
                if p1 is not None and p2 is not None and p2 != -1:
                    if random.random() < 0.5: p1, p2 = p2, p1
                    value = random.randint(1, 100)
                    cmd = f"ar {p1} {p2} {value}"; target_exception = "PersonIdNotFoundException (ar)"
        elif cmd_type == "mr":
            choice = random.random()
            if choice < 0.4:
                p1 = get_existing_person_id()
                p2 = get_non_existent_person_id(max_person_id)
                if p1 is not None and p2 is not None and p2 != -1:
                    if random.random() < 0.5: p1, p2 = p2, p1
                    m_val = random.randint(-50, 50)
                    cmd = f"mr {p1} {p2} {m_val}"; target_exception = "PersonIdNotFoundException (mr PINF)"
            elif choice < 0.7:
                 p1 = get_existing_person_id()
                 if p1 is not None:
                     m_val = random.randint(-50, 50)
                     cmd = f"mr {p1} {p1} {m_val}"; target_exception = "EqualPersonIdException (mr EPI)"
            else:
                p1, p2 = get_non_existent_relation_pair(approx_mode=approx_active) # Use approx_active
                if p1 is not None and p2 is not None:
                    m_val = random.randint(-50, 50)
                    cmd = f"mr {p1} {p2} {m_val}"; target_exception = "RelationNotFoundException (mr RNF)"
        elif cmd_type == "at":
            if random.random() < 0.5:
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None and p_id != -1:
                     cmd = f"at {p_id} {tag_id}"; target_exception = "PersonIdNotFoundException (at PINF)"
            else:
                owner_id, tag_id = get_random_tag_owner_and_tag()
                if owner_id is not None and tag_id is not None:
                    cmd = f"at {owner_id} {tag_id}"; target_exception = "EqualTagIdException (at ETI)"
        elif cmd_type == "dt":
            if random.random() < 0.5:
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None and p_id != -1:
                    cmd = f"dt {p_id} {tag_id}"; target_exception = "PersonIdNotFoundException (dt PINF)"
            else:
                p_id = get_existing_person_id()
                if p_id is not None:
                    tag_id = get_non_existent_tag_id(p_id, max_tag_id)
                    cmd = f"dt {p_id} {tag_id}"; target_exception = "TagIdNotFoundException (dt TINF)"
        elif cmd_type == "att":
            choice = random.random()
            if choice < 0.15:
                p1 = get_non_existent_person_id(max_person_id)
                p2, tag_id = get_random_tag_owner_and_tag()
                if p1 is not None and p1 != -1 and p2 is not None and tag_id is not None:
                     cmd = f"att {p1} {p2} {tag_id}"; target_exception = "PersonIdNotFoundException (att p1)"
            elif choice < 0.3:
                 p1 = get_existing_person_id()
                 p2 = get_non_existent_person_id(max_person_id)
                 tag_id = random.randint(0, max_tag_id)
                 if p1 is not None and p2 is not None and p2 != -1:
                      cmd = f"att {p1} {p2} {tag_id}"; target_exception = "PersonIdNotFoundException (att p2)"
            elif choice < 0.4:
                 p1 = get_existing_person_id()
                 tag_id = random.randint(0, max_tag_id)
                 if p1 is not None:
                      cmd = f"att {p1} {p1} {tag_id}"; target_exception = "EqualPersonIdException (att p1==p2)"
            elif choice < 0.6:
                p1, p2_owner_cand = get_non_existent_relation_pair(approx_mode=approx_active) # Use approx_active
                if p1 is not None and p2_owner_cand is not None:
                    if p2_owner_cand in person_tags and person_tags[p2_owner_cand]:
                        tag_id_for_p2 = random.choice(list(person_tags[p2_owner_cand]))
                        cmd = f"att {p1} {p2_owner_cand} {tag_id_for_p2}"
                        target_exception = "RelationNotFoundException (att)"
            elif choice < 0.8:
                 p1, p2 = get_existing_relation()
                 if p1 is not None and p2 is not None:
                      tag_id = get_non_existent_tag_id(p2, max_tag_id)
                      cmd = f"att {p1} {p2} {tag_id}"; target_exception = "TagIdNotFoundException (att TINF)"
            else:
                owner_id, tag_id = get_random_tag_owner_and_tag(require_non_empty=True)
                if owner_id is not None and tag_id is not None:
                    member_id = get_random_member_in_tag(owner_id, tag_id)
                    if member_id is not None and member_id in person_neighbors.get(owner_id, set()):
                        cmd = f"att {member_id} {owner_id} {tag_id}"; target_exception = "EqualPersonIdException (att already in tag)"
        elif cmd_type == "dft":
            choice = random.random()
            if choice < 0.2:
                p1 = get_non_existent_person_id(max_person_id)
                p2, tag_id = get_random_tag_owner_and_tag()
                if p1 is not None and p1 != -1 and p2 is not None and tag_id is not None:
                    cmd = f"dft {p1} {p2} {tag_id}"; target_exception = "PersonIdNotFoundException (dft p1)"
            elif choice < 0.4:
                p1 = get_existing_person_id()
                p2 = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p1 is not None and p2 is not None and p2 != -1:
                    cmd = f"dft {p1} {p2} {tag_id}"; target_exception = "PersonIdNotFoundException (dft p2)"
            elif choice < 0.7:
                owner_id = get_existing_person_id()
                p1_cand = get_existing_person_id()
                if owner_id is not None and p1_cand is not None:
                    tag_id = get_non_existent_tag_id(owner_id, max_tag_id)
                    cmd = f"dft {p1_cand} {owner_id} {tag_id}"; target_exception = "TagIdNotFoundException (dft TINF)"
            else:
                owner_id, tag_id = get_random_tag_owner_and_tag()
                if owner_id is not None and tag_id is not None:
                    p1_not_in = get_person_not_in_tag(owner_id, tag_id)
                    if p1_not_in is not None:
                        cmd = f"dft {p1_not_in} {owner_id} {tag_id}"; target_exception = "PersonIdNotFoundException (dft p1 not in tag)"
        elif cmd_type == "qv":
             choice = random.random()
             if choice < 0.5:
                 p1 = get_existing_person_id()
                 p2 = get_non_existent_person_id(max_person_id)
                 if p1 is not None and p2 is not None and p2 != -1:
                     if random.random() < 0.5: p1, p2 = p2, p1
                     cmd = f"qv {p1} {p2}"; target_exception = "PersonIdNotFoundException (qv PINF)"
             else:
                 p1, p2 = get_non_existent_relation_pair(approx_mode=approx_active) # Use approx_active
                 if p1 is not None and p2 is not None:
                     cmd = f"qv {p1} {p2}"; target_exception = "RelationNotFoundException (qv RNF)"
        elif cmd_type == "qci":
            p1 = get_existing_person_id()
            p2 = get_non_existent_person_id(max_person_id)
            if p1 is not None and p2 is not None and p2 != -1:
                if random.random() < 0.5: p1, p2 = p2, p1
                cmd = f"qci {p1} {p2}"; target_exception = "PersonIdNotFoundException (qci PINF)"
        elif cmd_type == "qtav" or cmd_type == "qtvs":
            exception_prefix = "qtav" if cmd_type == "qtav" else "qtvs"
            choice = random.random()
            if choice < 0.5:
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None and p_id != -1:
                    cmd = f"{cmd_type} {p_id} {tag_id}"; target_exception = f"PersonIdNotFoundException ({exception_prefix} PINF)"
            else:
                p_id = get_existing_person_id()
                if p_id is not None:
                    tag_id = get_non_existent_tag_id(p_id, max_tag_id)
                    cmd = f"{cmd_type} {p_id} {tag_id}"; target_exception = f"TagIdNotFoundException ({exception_prefix} TINF)"
        elif cmd_type == "qba":
            choice = random.random()
            if choice < 0.5:
                p_id = get_non_existent_person_id(max_person_id)
                if p_id is not None and p_id != -1:
                    cmd = f"qba {p_id}"; target_exception = "PersonIdNotFoundException (qba PINF)"
            else:
                p_id = get_person_with_no_acquaintances()
                if p_id is not None:
                    cmd = f"qba {p_id}"; target_exception = "AcquaintanceNotFoundException (qba ANF)"
        elif cmd_type == "qsp":
            choice = random.random()
            if choice < 0.3:
                p1 = get_non_existent_person_id(max_person_id)
                p2 = get_existing_person_id()
                if p1 is not None and p1 != -1 and p2 is not None:
                     cmd = f"qsp {p1} {p2}"; target_exception = "PersonIdNotFoundException (qsp p1)"
            elif choice < 0.6:
                 p1 = get_existing_person_id()
                 p2 = get_non_existent_person_id(max_person_id)
                 if p1 is not None and p2 is not None and p2 != -1:
                      cmd = f"qsp {p1} {p2}"; target_exception = "PersonIdNotFoundException (qsp p2)"
            else: # PNF - PathNotFoundException
                 p1, p2 = get_pair_without_path(approx_mode=approx_active) # Use approx_active
                 if p1 is not None and p2 is not None and p1 != p2:
                      cmd = f"qsp {p1} {p2}"
                      target_exception = "PathNotFoundException (via get_pair_without_path)"
        # HW10 Exceptions
        elif cmd_type == "coa":
            if random.random() < 0.5:
                p_id = get_non_existent_person_id(max_person_id)
                acc_id = get_non_existent_account_id(max_account_id)
                name = generate_name(acc_id if acc_id != -1 else 0, "Acc")
                if p_id is not None and p_id != -1 and acc_id != -1:
                     cmd = f"coa {p_id} {acc_id} {name}"; target_exception = "PersonIdNotFoundException (coa PINF)"
            else:
                 p_id = get_existing_person_id()
                 acc_id = get_random_account_id()
                 if p_id is not None and acc_id is not None:
                      name = generate_name(acc_id, "Acc")
                      cmd = f"coa {p_id} {acc_id} {name}"; target_exception = "EqualOfficialAccountIdException (coa EOAI)"
        elif cmd_type == "doa":
             choice = random.random()
             if choice < 0.3:
                p_id = get_non_existent_person_id(max_person_id)
                acc_id = get_random_account_id()
                if p_id is not None and p_id != -1 and acc_id is not None:
                      cmd = f"doa {p_id} {acc_id}"; target_exception = "PersonIdNotFoundException (doa PINF)"
             elif choice < 0.6:
                  p_id = get_existing_person_id()
                  acc_id = get_non_existent_account_id(max_account_id)
                  if p_id is not None and acc_id is not None and acc_id != -1:
                       cmd = f"doa {p_id} {acc_id}"; target_exception = "OfficialAccountIdNotFoundException (doa OAINF)"
             else:
                  acc_id = get_random_account_id()
                  if acc_id is not None:
                      owner_id = get_account_owner(acc_id)
                      non_owner_id = get_existing_person_id()
                      if non_owner_id is not None and owner_id is not None and non_owner_id != owner_id:
                           cmd = f"doa {non_owner_id} {acc_id}"; target_exception = "DeleteOfficialAccountPermissionDeniedException (doa DOAPD)"
        elif cmd_type == "ca":
             choice = random.random()
             if choice < 0.2:
                 p_id = get_non_existent_person_id(max_person_id)
                 acc_id = get_random_account_id()
                 art_id = get_non_existent_article_id(max_article_id)
                 name = generate_name(art_id if art_id != -1 else 0, "Art") # Name is generated
                 if p_id is not None and p_id != -1 and acc_id is not None and art_id != -1:
                      cmd = f"ca {p_id} {acc_id} {art_id} {name}"; target_exception = "PersonIdNotFoundException (ca PINF)"
             elif choice < 0.4:
                  p_id = get_existing_person_id()
                  acc_id = get_non_existent_account_id(max_account_id)
                  art_id = get_non_existent_article_id(max_article_id)
                  name = generate_name(art_id if art_id != -1 else 0, "Art") # Name is generated
                  if p_id is not None and acc_id is not None and acc_id != -1 and art_id != -1:
                       cmd = f"ca {p_id} {acc_id} {art_id} {name}"; target_exception = "OfficialAccountIdNotFoundException (ca OAINF)"
             elif choice < 0.6:
                  acc_id, follower_id = get_random_account_and_follower()
                  art_id_existing = get_random_article_id()
                  # For EqualArticleIdException, the name param might be for a *new* article conceptually, even if id clashes
                  name = generate_name(art_id_existing if art_id_existing is not None else random.randint(0, max_article_id), "ArtNew") # Name is generated
                  if follower_id is not None and acc_id is not None and art_id_existing is not None:
                       cmd = f"ca {follower_id} {acc_id} {art_id_existing} {name}"; target_exception = "EqualArticleIdException (ca EAI)"
             else:
                  acc_id = get_random_account_id()
                  art_id = get_non_existent_article_id(max_article_id)
                  name = generate_name(art_id if art_id != -1 else 0, "Art") # Name is generated
                  if acc_id is not None and art_id != -1:
                      p_id_not_follower = get_person_not_following(acc_id)
                      if p_id_not_follower is not None:
                           cmd = f"ca {p_id_not_follower} {acc_id} {art_id} {name}"; target_exception = "ContributePermissionDeniedException (ca CPD)"
        elif cmd_type == "da":
             choice = random.random()
             if choice < 0.2:
                 p_id = get_non_existent_person_id(max_person_id)
                 acc_id, art_id = get_random_account_and_article()
                 if p_id is not None and p_id != -1 and acc_id is not None and art_id is not None:
                      cmd = f"da {p_id} {acc_id} {art_id}"; target_exception = "PersonIdNotFoundException (da PINF)"
             elif choice < 0.4:
                  p_id_owner_cand = get_existing_person_id()
                  acc_id = get_non_existent_account_id(max_account_id)
                  art_id_any = get_random_article_id() # Could be any article, not necessarily in this non-existent account
                  if p_id_owner_cand is not None and acc_id is not None and acc_id != -1 and art_id_any is not None:
                       cmd = f"da {p_id_owner_cand} {acc_id} {art_id_any}"; target_exception = "OfficialAccountIdNotFoundException (da OAINF)"
             elif choice < 0.6:
                  acc_id = get_random_account_id()
                  if acc_id is not None:
                      owner_id = get_account_owner(acc_id)
                      # Get an article ID that is guaranteed not to be in *any* account, or specifically this one.
                      # Using get_non_existent_article_id is safer for AINF.
                      art_id_not_in_acc = get_non_existent_article_id(max_article_id)
                      if owner_id is not None and art_id_not_in_acc != -1 :
                          cmd = f"da {owner_id} {acc_id} {art_id_not_in_acc}"; target_exception = "ArticleIdNotFoundException (da AINF)"
             else:
                  acc_id, art_id = get_random_account_and_article()
                  if acc_id is not None and art_id is not None:
                      owner_id = get_account_owner(acc_id)
                      non_owner_id = get_existing_person_id()
                      # Ensure non_owner_id is actually different from owner_id
                      if non_owner_id is not None and owner_id is not None and non_owner_id != owner_id:
                           cmd = f"da {non_owner_id} {acc_id} {art_id}"; target_exception = "DeleteArticlePermissionDeniedException (da DAPD)"
                      elif non_owner_id is None and persons: # fallback if no other person
                           # This case is less likely to be hit if persons > 1
                           # Try to find any person who is not the owner
                           other_persons_list = [p for p in persons if p != owner_id]
                           if other_persons_list:
                               non_owner_id_fallback = random.choice(other_persons_list)
                               cmd = f"da {non_owner_id_fallback} {acc_id} {art_id}"; target_exception = "DeleteArticlePermissionDeniedException (da DAPD fallback)"

        elif cmd_type == "foa":
             choice = random.random()
             if choice < 0.3:
                 p_id = get_non_existent_person_id(max_person_id)
                 acc_id = get_random_account_id()
                 if p_id is not None and p_id != -1 and acc_id is not None:
                      cmd = f"foa {p_id} {acc_id}"; target_exception = "PersonIdNotFoundException (foa PINF)"
             elif choice < 0.6:
                  p_id = get_existing_person_id()
                  acc_id = get_non_existent_account_id(max_account_id)
                  if p_id is not None and acc_id is not None and acc_id != -1:
                       cmd = f"foa {p_id} {acc_id}"; target_exception = "OfficialAccountIdNotFoundException (foa OAINF)"
             else:
                  acc_id, follower_id = get_random_account_and_follower()
                  if acc_id is not None and follower_id is not None:
                       cmd = f"foa {follower_id} {acc_id}"; target_exception = "EqualPersonIdException (foa already follows)"
        elif cmd_type == "qbc":
            acc_id = get_non_existent_account_id(max_account_id)
            if acc_id is not None and acc_id != -1:
                cmd = f"qbc {acc_id}"; target_exception = "OfficialAccountIdNotFoundException (qbc OAINF)"
        elif cmd_type == "qra":
            p_id = get_non_existent_person_id(max_person_id)
            if p_id is not None and p_id != -1:
                cmd = f"qra {p_id}"; target_exception = "PersonIdNotFoundException (qra PINF)"

    except Exception as e:
        # print(f"ERROR during *exception* generation for {cmd_type}: {e}", file=sys.stderr)
        # traceback.print_exc(file=sys.stderr)
        return None
    # if cmd: print(f"DEBUG: Generated EXCEPTION command ({target_exception}): {cmd}", file=sys.stderr)
    return cmd


# --- Main Generation Logic ---
def generate_commands(num_commands_target, max_person_id, max_tag_id, max_account_id, max_article_id,
                      max_rel_value, max_mod_value, max_age,
                      min_qci, min_qts, min_qtav, min_qba, min_qcs, min_qsp, min_qtvs, min_qbc, min_qra,
                      density, degree_focus_unused, max_degree, tag_focus, account_focus, max_tag_size, qci_focus,
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

    if phases_config:
        num_commands_to_generate = sum(p['count'] for p in phases_config)

    initial_cmds_count = 0
    if use_ln_setup and ln_nodes >= 2:
        ln_command_str = f"ln {ln_nodes}\n"

        ln_person_ids = list(range(ln_nodes))
        ln_command_str += " ".join(map(str, ln_person_ids)) + "\n"

        ln_person_names = [generate_name(i, "P") for i in ln_person_ids]
        ln_command_str += " ".join(ln_person_names) + "\n"

        ln_person_ages = [str(random.randint(1, max_age)) for _ in ln_person_ids]
        ln_command_str += " ".join(ln_person_ages) + "\n"

        for i in range(ln_nodes):
            add_person_state(ln_person_ids[i], ln_person_names[i], int(ln_person_ages[i]))

        target_edges = int(density * (ln_nodes * (ln_nodes - 1)) / 2)
        current_edges = 0
        adj_matrix_values = [[0]*k for k in range(1, ln_nodes)]

        possible_edges_coords = []
        for r in range(1, ln_nodes):
            for c in range(r):
                 possible_edges_coords.append((r,c))
        random.shuffle(possible_edges_coords)

        for r, c in possible_edges_coords:
            if current_edges < target_edges:
                if add_relation_state(ln_person_ids[r], ln_person_ids[c], ln_default_value, max_degree):
                    adj_matrix_values[r-1][c] = ln_default_value
                    current_edges += 1
            else:
                break

        for r_idx in range(len(adj_matrix_values)):
            ln_command_str += " ".join(map(str, adj_matrix_values[r_idx])) + "\n"

        generated_cmds_list.append(ln_command_str.strip())
        cmd_counts['ln'] += 1
        initial_cmds_count = 1

        hub_ids = set(range(min(num_hubs, ln_nodes))) if num_hubs > 0 else set()
    else:
        initial_people = min(num_commands_to_generate // 10 + 5, max_person_id + 1, 100)
        if hub_bias > 0: initial_people = max(initial_people, num_hubs)
        current_id_gen = 0

        for _ in range(initial_people):
            person_id_val = get_non_existent_person_id(max_person_id)
            if person_id_val == -1 or person_id_val > max_person_id:
                break

            name = generate_name(person_id_val, "Person")
            age = random.randint(1, max_age)
            if add_person_state(person_id_val, name, age):
                cmd_ap = f"ap {person_id_val} {name} {age}"
                generated_cmds_list.append(cmd_ap)
                cmd_counts['ap'] += 1
                initial_cmds_count +=1
            current_id_gen +=1
        hub_ids = set(p for p in persons if p < num_hubs) if num_hubs > 0 else set()

    while (len(generated_cmds_list) - initial_cmds_count) < (num_commands_to_generate - initial_cmds_count) :
        current_phase_name = "default"
        if phases_config:
            if current_phase_index >= len(phases_config): break
            current_phase_info = phases_config[current_phase_index]
            current_phase_name = current_phase_info['name']
            if commands_in_current_phase >= current_phase_info['count']:
                current_phase_index += 1
                commands_in_current_phase = 0
                if current_phase_index >= len(phases_config): break
                current_phase_info = phases_config[current_phase_index]
                current_phase_name = current_phase_info['name']

        weights_dict = get_command_weights(current_phase_name, tag_focus, account_focus)

        can_add_person = any(i <= max_person_id and i not in persons for i in range(max_person_id + 1))

        if not persons and not can_add_person:
             break
        elif not persons:
             if can_add_person: weights_dict = {'ap': 1}
             else: break
        else:
            if len(persons) < 2:
                for k in ["ar", "mr", "qv", "qci", "att", "dft", "qsp"]: weights_dict.pop(k, None)
            if not relations:
                weights_dict.pop("mr", None)
            if not any(person_neighbors.values()):
                 weights_dict.pop("qba", None)
            if not any(person_tags.values()):
                for k in ["dt", "qtav", "qtvs"]: weights_dict.pop(k, None)
            if not any(tag_members.values()):
                weights_dict.pop("dft", None)

            if not official_accounts:
                for k in ["doa", "ca", "da", "foa", "qbc"]: weights_dict.pop(k, None)
            can_contribute_ca = any(len(account_followers.get(acc_id, set())) > 0 for acc_id in official_accounts)
            if not can_contribute_ca: weights_dict.pop("ca", None)

            # qbc check should be for accounts with *contributions*, not just followers
            can_qbc_check = False
            if official_accounts:
                 for acc_id_qbc in official_accounts:
                     # Check if any contributor to this account has a non-zero (or even existing) contribution count
                     if acc_id_qbc in account_contributions and any(count > 0 for count in account_contributions[acc_id_qbc].values()):
                         can_qbc_check = True
                         break
            if not can_qbc_check: weights_dict.pop("qbc", None)


            can_delete_article_check = False
            if all_articles:
                for acc_id_check in official_accounts:
                    if account_articles.get(acc_id_check):
                        can_delete_article_check = True; break
            if not can_delete_article_check: weights_dict.pop("da", None)


        if not weights_dict or sum(weights_dict.values()) == 0:
             if can_add_person:
                 cmd_type = 'ap'
             else:
                 break
        else:
             command_types = list(weights_dict.keys())
             type_weights = [weights_dict[cmd_t] for cmd_t in command_types]
             cmd_type = random.choices(command_types, weights=type_weights, k=1)[0]

        cmd = None
        generated_successfully = False

        if random.random() < exception_ratio:
            cmd = try_generate_exception_command(cmd_type, max_person_id, max_tag_id,
                                                 max_account_id, max_article_id, density, approx_active)
            if cmd:
                generated_successfully = True

        if not generated_successfully:
            try:
                force_qba_empty = (cmd_type == "qba" and random.random() < force_qba_empty_ratio)
                force_qtav_empty = (cmd_type == "qtav" and random.random() < force_qtav_empty_ratio)

                if cmd_type == "ap":
                    person_id = get_non_existent_person_id(max_person_id)
                    if person_id != -1 and person_id <= max_person_id :
                        name = generate_name(person_id, "Person")
                        age = random.randint(1, max_age)
                        if add_person_state(person_id, name, age):
                            cmd = f"ap {person_id} {name} {age}"; generated_successfully = True
                elif cmd_type == "ar":
                    p1, p2 = None, None
                    use_hub = (hub_ids and random.random() < hub_bias)
                    if use_hub:
                        valid_hubs = list(h for h in hub_ids if h in persons)
                        if valid_hubs:
                             hub_id = random.choice(valid_hubs)
                             eligible_others = list(p for p in persons if p != hub_id)
                             if eligible_others:
                                 other_p = random.choice(eligible_others)
                                 p1, p2 = hub_id, other_p
                    if p1 is None or p2 is None:
                       p1, p2 = get_two_random_persons(require_different=True)

                    if p1 is not None and p2 is not None:
                        current_nodes_ar = len(persons)
                        max_possible_edges_ar = (current_nodes_ar * (current_nodes_ar - 1)) // 2 if current_nodes_ar > 1 else 0
                        current_density_ar = len(relations) / max_possible_edges_ar if max_possible_edges_ar > 0 else 0.0
                        prob_add_ar = 0.5 + (density - current_density_ar)
                        prob_add_ar = max(0.01, min(0.99, prob_add_ar))

                        if random.random() < prob_add_ar:
                            value = random.randint(1, max_rel_value)
                            if add_relation_state(p1, p2, value, max_degree):
                                cmd = f"ar {p1} {p2} {value}"; generated_successfully = True

                elif cmd_type == "mr":
                    p1, p2 = get_random_relation()
                    if p1 is not None and p2 is not None:
                        rel_key_mr = (min(p1,p2), max(p1,p2))
                        current_value_mr = relation_values.get(rel_key_mr, 0)
                        m_val_mr = 0
                        if current_value_mr > 0 and random.random() < mr_delete_ratio:
                            m_val_mr = -current_value_mr - random.randint(0, 10) # Ensure it goes <= 0
                        else:
                            effective_max_mod_mr = max(1, max_mod_value)
                            m_val_mr = random.randint(-effective_max_mod_mr, effective_max_mod_mr)
                            if m_val_mr == 0 and max_mod_value != 0: # Avoid mr with 0 value if possible
                                m_val_mr = random.choice([-1, 1]) * random.randint(1, effective_max_mod_mr)
                        
                        if hce_active: # Apply HCE limits for mr value if active
                            # JML limits are implicitly handled by sum not exceeding int limits.
                            # The direct mr value itself has a limit.
                            if m_val_mr > 200: m_val_mr = 200
                            if m_val_mr < -200: m_val_mr = -200
                            
                            # Also ensure the resulting value stays within reasonable bounds if HCE implies general value limits
                            # For now, assume HCE's 200 limit applies to the delta 'm_val_mr' and initial relation value.
                            # The sum can exceed 200. If JML specifies sum limit, that needs to be handled too.

                        cmd = f"mr {p1} {p2} {m_val_mr}"
                        generated_successfully = True

                        new_value_mr = current_value_mr + m_val_mr
                        if new_value_mr <= 0:
                            remove_relation_state(p1, p2)
                        else:
                            relation_values[rel_key_mr] = new_value_mr
                elif cmd_type == "at":
                    person_id_at = get_existing_person_id()
                    if person_id_at is not None:
                        tag_id_at = get_non_existent_tag_id(person_id_at, max_tag_id)
                        if add_tag_state(person_id_at, tag_id_at):
                             cmd = f"at {person_id_at} {tag_id_at}"; generated_successfully = True
                elif cmd_type == "dt":
                    owner_id_dt, tag_id_dt = get_random_tag_owner_and_tag()
                    if owner_id_dt is not None and tag_id_dt is not None:
                        if remove_tag_state(owner_id_dt, tag_id_dt):
                            cmd = f"dt {owner_id_dt} {tag_id_dt}"; generated_successfully = True
                elif cmd_type == "att":
                     owner_id_att, tag_id_att = get_random_tag_owner_and_tag()
                     if owner_id_att is not None and tag_id_att is not None:
                         person_id1_att = get_related_person_not_in_tag(owner_id_att, tag_id_att)
                         if person_id1_att is not None:
                             if add_person_to_tag_state(person_id1_att, owner_id_att, tag_id_att, max_tag_size):
                                cmd = f"att {person_id1_att} {owner_id_att} {tag_id_att}"; generated_successfully = True
                elif cmd_type == "dft":
                     owner_id_dft, tag_id_dft = get_random_tag_owner_and_tag(require_non_empty=True)
                     if owner_id_dft is not None and tag_id_dft is not None:
                         member_id_dft = get_random_member_in_tag(owner_id_dft, tag_id_dft)
                         if member_id_dft is not None:
                             if remove_person_from_tag_state(member_id_dft, owner_id_dft, tag_id_dft):
                                cmd = f"dft {member_id_dft} {owner_id_dft} {tag_id_dft}"; generated_successfully = True
                elif cmd_type == "coa":
                    person_id_coa = get_existing_person_id()
                    account_id_coa = get_non_existent_account_id(max_account_id)
                    if person_id_coa is not None and account_id_coa != -1 and account_id_coa <= max_account_id:
                         name_coa = generate_name(account_id_coa, "Acc")
                         if create_official_account_state(person_id_coa, account_id_coa, name_coa):
                              cmd = f"coa {person_id_coa} {account_id_coa} {name_coa}"; generated_successfully = True
                elif cmd_type == "doa":
                    owner_id_doa = None; acc_id_doa = None
                    # Ensure we only pick accounts whose owners are still in 'persons' set
                    accounts_with_valid_owners_doa = {
                        acc: details['owner']
                        for acc, details in account_details.items()
                        if details.get('owner') in persons and acc in official_accounts
                    }
                    if accounts_with_valid_owners_doa:
                         acc_id_doa = random.choice(list(accounts_with_valid_owners_doa.keys()))
                         owner_id_doa = accounts_with_valid_owners_doa[acc_id_doa]

                    if owner_id_doa is not None and acc_id_doa is not None:
                        if delete_official_account_state(owner_id_doa, acc_id_doa):
                            cmd = f"doa {owner_id_doa} {acc_id_doa}"; generated_successfully = True
                elif cmd_type == "ca":
                     acc_id_ca = get_random_account_id()
                     if acc_id_ca: # Ensure account exists
                         eligible_followers_ca = list(f for f in account_followers.get(acc_id_ca, set()) if f in persons)
                         if eligible_followers_ca: # Ensure there are followers who are existing persons
                             follower_id_ca = random.choice(eligible_followers_ca)
                             article_id_ca = get_non_existent_article_id(max_article_id)
                             if article_id_ca != -1 and article_id_ca <= max_article_id: # Ensure valid new article ID
                                 name_ca = generate_name(article_id_ca, "Art") # <<<<< GENERATE NAME
                                 if contribute_article_state(follower_id_ca, acc_id_ca, article_id_ca, name_ca): # <<<<< PASS NAME TO STATE
                                      cmd = f"ca {follower_id_ca} {acc_id_ca} {article_id_ca} {name_ca}"; generated_successfully = True # <<<<< ADD NAME TO CMD
                elif cmd_type == "da":
                     acc_id_da, art_id_da = get_random_account_and_article() # This ensures article is in the account
                     if acc_id_da is not None and art_id_da is not None:
                         owner_id_da = get_account_owner(acc_id_da)
                         if owner_id_da is not None and owner_id_da in persons: # Ensure owner is an existing person
                              if delete_article_state(owner_id_da, acc_id_da, art_id_da):
                                   cmd = f"da {owner_id_da} {acc_id_da} {art_id_da}"; generated_successfully = True
                elif cmd_type == "foa":
                     acc_id_foa = get_random_account_id()
                     if acc_id_foa is not None:
                         person_id_foa = get_person_not_following(acc_id_foa)
                         if person_id_foa is not None: # Ensure we found a person not following
                              if follow_official_account_state(person_id_foa, acc_id_foa):
                                   cmd = f"foa {person_id_foa} {acc_id_foa}"; generated_successfully = True
                # Queries
                elif cmd_type == "qv":
                    if random.random() < 0.8 and relations: p1_qv, p2_qv = get_random_relation()
                    else: p1_qv, p2_qv = get_two_random_persons(require_different=True)
                    if p1_qv is not None and p2_qv is not None:
                        cmd = f"qv {p1_qv} {p2_qv}"; generated_successfully = True
                elif cmd_type == "qci":
                     p1_qci, p2_qci = None, None
                     if qci_focus == 'close' and relations and random.random() < 0.5: p1_qci, p2_qci = get_random_relation()
                     elif qci_focus == 'far' and random.random() < 0.5: p1_qci, p2_qci = get_non_existent_relation_pair(approx_mode=approx_active)
                     if p1_qci is None or p2_qci is None: p1_qci, p2_qci = get_two_random_persons(require_different=True)
                     if p1_qci is not None and p2_qci is not None:
                          cmd = f"qci {p1_qci} {p2_qci}"; generated_successfully = True
                elif cmd_type == "qts": cmd = "qts"; generated_successfully = True
                elif cmd_type == "qtav":
                    owner_qtav, tag_qtav = None, None
                    if force_qtav_empty: owner_qtav, tag_qtav = get_random_empty_tag()
                    if owner_qtav is None: owner_qtav, tag_qtav = get_random_tag_owner_and_tag()
                    if owner_qtav is None:
                         owner_qtav = get_existing_person_id()
                         if owner_qtav is not None: tag_qtav = random.randint(0, max_tag_id) # Fallback tag_id
                    if owner_qtav is not None and tag_qtav is not None:
                        cmd = f"qtav {owner_qtav} {tag_qtav}"; generated_successfully = True
                elif cmd_type == "qtvs":
                    owner_qtvs, tag_qtvs = get_random_tag_owner_and_tag()
                    if owner_qtvs is None:
                         owner_qtvs = get_existing_person_id()
                         if owner_qtvs is not None: tag_qtvs = random.randint(0, max_tag_id) # Fallback tag_id
                    if owner_qtvs is not None and tag_qtvs is not None:
                        cmd = f"qtvs {owner_qtvs} {tag_qtvs}"; generated_successfully = True
                elif cmd_type == "qba":
                     person_qba = None
                     if force_qba_empty: person_qba = get_person_with_no_acquaintances()
                     if person_qba is None:
                         # Try to get someone with relations, otherwise any existing person
                         person_qba = get_random_person(require_degree_greater_than=0 if random.random() < 0.95 else None)
                         if person_qba is None: person_qba = get_existing_person_id() # Fallback if no one has degree > 0
                     if person_qba is not None:
                          cmd = f"qba {person_qba}"; generated_successfully = True
                elif cmd_type == "qcs": cmd = "qcs"; generated_successfully = True
                elif cmd_type == "qsp":
                    p1_qsp, p2_qsp = None, None
                    if random.random() < 0.8: p1_qsp, p2_qsp = get_pair_with_path()
                    else: p1_qsp, p2_qsp = get_two_random_persons(require_different=True)
                    if p1_qsp is None or p2_qsp is None: # Fallback if get_pair_with_path failed
                        p1_qsp, p2_qsp = get_two_random_persons(require_different=True)
                    if p1_qsp is not None and p2_qsp is not None and p1_qsp != p2_qsp: # Ensure they are different for qsp
                         cmd = f"qsp {p1_qsp} {p2_qsp}"; generated_successfully = True
                elif cmd_type == "qbc":
                     account_qbc = get_random_account_with_followers() # Followers is a good proxy for potential contributions
                     if account_qbc is None: account_qbc = get_random_account_id() # Fallback to any account
                     if account_qbc is not None:
                         cmd = f"qbc {account_qbc}"; generated_successfully = True
                elif cmd_type == "qra":
                     person_qra = get_existing_person_id()
                     if person_qra is not None:
                          cmd = f"qra {person_qra}"; generated_successfully = True
            except Exception as e:
                # print(f"ERROR during normal generation for {cmd_type}: {e}", file=sys.stderr)
                # traceback.print_exc(file=sys.stderr)
                pass

        if generated_successfully and cmd:
            if cmd_type != 'ln':
                generated_cmds_list.append(cmd)
            cmd_counts[cmd_type] += 1
            if phases_config:
                 commands_in_current_phase +=1

    min_counts_map = {
        "qci": min_qci, "qts": min_qts, "qtav": min_qtav, "qba": min_qba,
        "qcs": min_qcs, "qsp": min_qsp, "qtvs": min_qtvs, "qbc": min_qbc, "qra": min_qra
    }
    supplementary_cmds_list = []

    for query_type_supp, min_req_supp in min_counts_map.items():
        needed_supp = min_req_supp - cmd_counts[query_type_supp]
        if needed_supp <= 0: continue

        attempts_supp_loop = 0
        max_attempts_supp_loop = needed_supp * 5 + 20 # Increased attempts for supplementary
        generated_supp_count = 0

        while generated_supp_count < needed_supp and attempts_supp_loop < max_attempts_supp_loop:
            cmd_supp = None
            attempts_supp_loop += 1
            try:
                if query_type_supp == "qci":
                    p1_supp, p2_supp = get_two_random_persons(require_different=True)
                    if p1_supp is not None and p2_supp is not None: cmd_supp = f"qci {p1_supp} {p2_supp}"
                elif query_type_supp == "qts": cmd_supp = "qts"
                elif query_type_supp == "qtav":
                    owner_supp, tag_supp = get_random_tag_owner_and_tag()
                    if owner_supp is None : owner_supp = get_existing_person_id()
                    if owner_supp is not None :
                        if tag_supp is None: tag_supp = random.randint(0, max_tag_id)
                        cmd_supp = f"qtav {owner_supp} {tag_supp}"
                elif query_type_supp == "qtvs":
                    owner_supp_vs, tag_supp_vs = get_random_tag_owner_and_tag()
                    if owner_supp_vs is None : owner_supp_vs = get_existing_person_id()
                    if owner_supp_vs is not None :
                        if tag_supp_vs is None: tag_supp_vs = random.randint(0, max_tag_id)
                        cmd_supp = f"qtvs {owner_supp_vs} {tag_supp_vs}"
                elif query_type_supp == "qba":
                    person_supp = get_existing_person_id() # Get any person for qba
                    if person_supp is not None: cmd_supp = f"qba {person_supp}"
                elif query_type_supp == "qcs": cmd_supp = "qcs"
                elif query_type_supp == "qsp":
                    p1_sp_supp, p2_sp_supp = get_two_random_persons(require_different=True)
                    if p1_sp_supp is not None and p2_sp_supp is not None and p1_sp_supp != p2_sp_supp: # ensure different
                        cmd_supp = f"qsp {p1_sp_supp} {p2_sp_supp}"
                elif query_type_supp == "qbc":
                    account_supp = get_random_account_id()
                    if account_supp is not None: cmd_supp = f"qbc {account_supp}"
                elif query_type_supp == "qra":
                    person_ra_supp = get_existing_person_id()
                    if person_ra_supp is not None: cmd_supp = f"qra {person_ra_supp}"
            except Exception as e_supp:
                 # print(f"Error generating supplementary cmd {query_type_supp}: {e_supp}", file=sys.stderr)
                 pass # Silently ignore errors during supplementary generation
            if cmd_supp:
                supplementary_cmds_list.append(cmd_supp)
                generated_supp_count += 1

        if generated_supp_count < needed_supp:
             # print(f"Warning: Could not meet minimum for {query_type_supp}. Needed {needed_supp}, got {generated_supp_count}", file=sys.stderr)
             pass


    generated_cmds_list.extend(supplementary_cmds_list)
    for cmd_str_supp in supplementary_cmds_list:
        cmd_type_val_supp = cmd_str_supp.split()[0]
        cmd_counts[cmd_type_val_supp] += 1

    return generated_cmds_list, cmd_counts


# --- Argument Parsing (Added HW10 args) ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate test data for HW10 social network.")
    # Core Controls
    parser.add_argument("-n", "--num_commands", type=int, default=2000, help="Target number of commands (ignored if --phases is set).")
    parser.add_argument("--max_person_id", type=int, default=150, help="Maximum person ID (0 to max).")
    parser.add_argument("--max_tag_id", type=int, default=15, help="Maximum tag ID (0 to max).")
    parser.add_argument("--max_account_id", type=int, default=50, help="Maximum official account ID (0 to max).")
    parser.add_argument("--max_article_id", type=int, default=500, help="Maximum article ID (0 to max).")
    parser.add_argument("--max_age", type=int, default=200, help="Maximum person age (default 200).")
    parser.add_argument("-o", "--output_file", type=str, default=None, help="Output file name (default: stdout).")
    parser.add_argument("--hce", action='store_true', help="Enable HCE constraints (Mutual Test limits: N_cmds<=3000, max_person_id<=99, values<=200).")
    parser.add_argument("--seed", type=int, default=None, help="Seed for the random number generator.")
    parser.add_argument("--approx", action='store_true', help="Enable approximation mode for high density scenarios to improve performance.")


    # Relation/Value Controls
    parser.add_argument("--max_rel_value", type=int, default=200, help="Maximum initial relation value (default 200).")
    parser.add_argument("--max_mod_value", type=int, default=200, help="Maximum absolute modify relation value change (default 200).")
    parser.add_argument("--mr_delete_ratio", type=float, default=0.15, help="Approx. ratio of 'mr' commands targeting relation deletion (0.0-1.0).")

    # Graph Structure Controls
    parser.add_argument("--density", type=float, default=0.05, help="Target graph density (0.0-1.0). Used by 'ln' or guides 'ar'.")
    parser.add_argument("--max_degree", type=int, default=None, help="Attempt to limit the maximum degree of any person.")
    parser.add_argument("--hub_bias", type=float, default=0.0, help="Probability (0.0-1.0) for 'ar' to connect to a designated hub node.")
    parser.add_argument("--num_hubs", type=int, default=5, help="Number of initial person IDs (0 to N-1) to treat as potential hubs.")

    # ln Setup Controls
    parser.add_argument("--use_ln_setup", action='store_true', help="Use 'ln' command for initial dense network setup.")
    parser.add_argument("--ln_nodes", type=int, default=50, help="Number of nodes for 'ln' setup (if --use_ln_setup).")
    parser.add_argument("--ln_default_value", type=int, default=10, help="Default relation value for edges created by 'ln' (if --use_ln_setup).")


    # Tag & Account Controls
    parser.add_argument("--tag_focus", type=float, default=0.25, help="Approx. ratio of total commands related to tags (0.0-1.0).")
    parser.add_argument("--account_focus", type=float, default=0.25, help="Approx. ratio of total commands related to accounts/articles (0.0-1.0).")
    parser.add_argument("--max_tag_size", type=int, default=50, help="Attempt to limit the max number of persons in a tag (up to JML limit 1000).")

    # Query & Exception Controls
    parser.add_argument("--qci_focus", choices=['mixed', 'close', 'far'], default='mixed', help="Influence 'qci' pair selection.")
    parser.add_argument("--min_qci", type=int, default=10, help="Minimum number of qci commands.")
    parser.add_argument("--min_qts", type=int, default=5, help="Minimum number of qts commands.")
    parser.add_argument("--min_qtav", type=int, default=10, help="Minimum number of qtav commands.")
    parser.add_argument("--min_qtvs", type=int, default=10, help="Minimum number of qtvs commands.")
    parser.add_argument("--min_qba", type=int, default=5, help="Minimum number of qba commands.")
    parser.add_argument("--min_qcs", type=int, default=3, help="Minimum number of qcs commands.")
    parser.add_argument("--min_qsp", type=int, default=5, help="Minimum number of qsp commands.")
    parser.add_argument("--min_qbc", type=int, default=5, help="Minimum number of qbc commands.")
    parser.add_argument("--min_qra", type=int, default=5, help="Minimum number of qra commands.")
    parser.add_argument("--exception_ratio", type=float, default=0.08, help="Probability (0.0-1.0) to attempt generating an exception command.")
    parser.add_argument("--force_qba_empty_ratio", type=float, default=0.02, help="Probability (0.0-1.0) for 'qba' to target person with no acquaintances.")
    parser.add_argument("--force_qtav_empty_ratio", type=float, default=0.02, help="Probability (0.0-1.0) for 'qtav'/'qtvs' to target an empty tag.")

    # Generation Flow Control
    parser.add_argument("--phases", type=str, default=None, help="Define generation phases, e.g., 'build:500,query:1000,churn:500'. Overrides -n.")

    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
    else:
        seed_val = random.randrange(sys.maxsize)
        random.seed(seed_val)
        # print(f"Using random seed: {seed_val}", file=sys.stderr)


    if args.hce:
        hce_max_n_cmds = 3000
        hce_max_pid_val = 99
        hce_max_val_param = 200

        target_n_cmds = args.num_commands
        if args.phases:
            try:
                _, total_phase_commands_val = parse_phases(args.phases)
                target_n_cmds = total_phase_commands_val
            except ValueError: pass

        args.num_commands = min(target_n_cmds, hce_max_n_cmds)

        args.max_person_id = min(args.max_person_id, hce_max_pid_val)
        args.max_account_id = min(args.max_account_id, hce_max_pid_val) # Assuming account IDs also constrained if person IDs are
        # Article IDs might not be directly constrained by HCE person_id limit, but good to keep reasonable
        args.max_article_id = min(args.max_article_id, hce_max_pid_val * 5 if hce_max_pid_val * 5 > 0 else 500)


        args.max_age = min(args.max_age, hce_max_val_param)
        args.max_rel_value = min(args.max_rel_value, hce_max_val_param)
        args.max_mod_value = min(args.max_mod_value, hce_max_val_param) # This is the delta
        args.ln_default_value = min(args.ln_default_value, hce_max_val_param)


    phases_config_val = None
    if args.phases:
        try:
            phases_config_val, total_phase_cmds_val = parse_phases(args.phases)
            if not (args.hce and total_phase_cmds_val > args.num_commands) :
                args.num_commands = total_phase_cmds_val
        except ValueError as e_phase:
            print(f"ERROR: Invalid --phases argument: {e_phase}", file=sys.stderr)
            sys.exit(1)

    if args.hub_bias > 0 and args.num_hubs <= 0:
        # print("ERROR: --num_hubs must be positive when --hub_bias is used.", file=sys.stderr)
        args.hub_bias = 0 # Disable hub bias if num_hubs is not set appropriately
        # sys.exit(1)
    if args.num_hubs > args.max_person_id + 1:
        args.num_hubs = args.max_person_id + 1

    if args.use_ln_setup and args.ln_nodes > args.max_person_id + 1:
        args.ln_nodes = args.max_person_id + 1
    if args.use_ln_setup and args.ln_nodes < 2 :
        args.use_ln_setup = False


    output_stream_val = open(args.output_file, 'w') if args.output_file else sys.stdout

    try:
        persons.clear(); relations.clear(); relation_values.clear()
        person_tags.clear(); tag_members.clear(); person_details.clear()
        person_degrees.clear(); person_neighbors.clear()
        official_accounts.clear(); account_details.clear(); account_followers.clear()
        account_articles.clear(); account_contributions.clear(); all_articles.clear()
        article_contributors.clear(); article_locations.clear(); person_received_articles.clear()
        article_names.clear() # <<<<< CLEAR NEW STATE

        all_commands_list, final_cmd_counts_map = generate_commands(
            args.num_commands, args.max_person_id, args.max_tag_id,
            args.max_account_id, args.max_article_id,
            args.max_rel_value, args.max_mod_value, args.max_age,
            args.min_qci, args.min_qts, args.min_qtav, args.min_qba,
            args.min_qcs, args.min_qsp, args.min_qtvs, args.min_qbc, args.min_qra,
            args.density, None, args.max_degree,
            args.tag_focus, args.account_focus, args.max_tag_size, args.qci_focus,
            args.mr_delete_ratio, args.exception_ratio,
            args.force_qba_empty_ratio, args.force_qtav_empty_ratio,
            args.hub_bias, args.num_hubs,
            phases_config_val,
            args.hce,
            args.use_ln_setup, args.ln_nodes, args.ln_default_value,
            args.approx # Pass the approx flag
        )

        for command_item in all_commands_list:
             output_stream_val.write(command_item.strip() + '\n')

        # Debug print final counts to stderr (optional)
        # print("--- Final Command Counts ---", file=sys.stderr)
        # for cmd_type_final, count_final in sorted(final_cmd_counts_map.items()):
        #     print(f"{cmd_type_final}: {count_final}", file=sys.stderr)
        # print(f"Total commands generated: {len(all_commands_list)}", file=sys.stderr)
        # print(f"Persons: {len(persons)}, Relations: {len(relations)}, Tags: {sum(len(t) for t in person_tags.values())}", file=sys.stderr)
        # print(f"Accounts: {len(official_accounts)}, Articles: {len(all_articles)}", file=sys.stderr)


    finally:
        if args.output_file and output_stream_val is not sys.stdout:
            output_stream_val.close()

# --- END OF MODIFIED FILE gen.py ---