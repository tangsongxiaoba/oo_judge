# --- START OF OPTIMIZED FILE gen.py ---

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
    # OPTIMIZATION: Avoid sorted()
    return random.choice(list(eligible)) if eligible else None

def get_existing_person_id():
    return get_random_person()

def get_non_existent_person_id(max_person_id):
    if not persons: return random.randint(0, max_person_id)
    attempts = 0
    max_attempts = max(len(persons) * 2, 20)
    max_possible_id = max(list(persons)) if persons else -1
    search_range_max = max(max_person_id + 10, max_possible_id + 10)

    while attempts < max_attempts:
        if random.random() < 0.7 and max_possible_id >=0 :
            pid = random.randint(max(0, max_possible_id - 5), max_possible_id + 10)
        else:
            pid = random.randint(0, search_range_max)

        if pid >= 0 and pid not in persons:
            return pid
        attempts += 1
    return max(max_person_id, max_possible_id) + 1

def get_two_random_persons(id_limit=None, require_different=True):
    eligible = get_eligible_persons(id_limit)
    if len(eligible) < (2 if require_different else 1):
        return None, None
    # OPTIMIZATION: Avoid sorted()
    eligible_list = list(eligible)
    p1 = random.choice(eligible_list)
    if not require_different:
        # OPTIMIZATION: Avoid sorted()
        p2 = random.choice(eligible_list)
        return p1, p2
    # OPTIMIZATION: Create list only if needed, avoid sort
    eligible_list_copy = [p for p in eligible_list if p != p1] # More direct than copy/remove
    if not eligible_list_copy: return p1, None
    p2 = random.choice(eligible_list_copy)
    return p1, p2

# --- Relation Helpers ---
def get_eligible_relations(id_limit=None):
    # OPTIMIZATION: Avoid full copy if possible, but still O(|R|) if used directly
    eligible = relations # Reference original set
    if id_limit is not None:
        # Filter on demand, creating a new set only if needed
        eligible = {(p1, p2) for p1, p2 in relations if p1 < id_limit and p2 < id_limit}
    return eligible

def get_random_relation(id_limit=None):
    # OPTIMIZATION: Avoid sort, avoid full copy if id_limit is None. List conversion is still O(|R|)
    if not relations: return None, None
    if id_limit is None:
        # Directly sample from the set keys if no limit
        relation_list = list(relations)
        return random.choice(relation_list) if relation_list else (None, None)
    else:
        # Filter first if limit applies
        eligible_keys = [(p1, p2) for p1, p2 in relations if p1 < id_limit and p2 < id_limit]
        return random.choice(eligible_keys) if eligible_keys else (None, None)

def get_existing_relation():
    return get_random_relation()

def get_non_existent_relation_pair():
    # OPTIMIZATION: Use person_neighbors for faster checks in dense graphs
    if len(persons) < 2: return None, None
    person_list = list(persons) # O(N)
    attempts = 0
    # Adjust attempts based on size, maybe increase for density?
    max_attempts = max(len(person_list) * 2, 50) # Heuristic

    while attempts < max_attempts:
        # Choose two distinct people randomly
        p1 = random.choice(person_list)
        p2 = random.choice(person_list)
        if p1 == p2:
            attempts += 1 # Count this as an attempt but don't check relation
            continue

        # Check using neighbors (faster than checking 'relations' set)
        # Ensure p1 is actually in neighbors keys before accessing
        # Check both directions for safety although neighbors should be symmetric
        if p1 not in person_neighbors or p2 not in person_neighbors.get(p1, set()):
             # Double check the other direction just in case state is slightly off
             if p2 not in person_neighbors or p1 not in person_neighbors.get(p2, set()):
                 return p1, p2 # Found a non-existent pair

        attempts += 1

    # Fallback: Very hard to find in extremely dense graphs.
    print("Warning: Fallback in get_non_existent_relation_pair (dense graph?)", file=sys.stderr)
    if len(person_list) >= 2:
        p1 = random.choice(person_list)
        eligible_p2 = [p for p in person_list if p != p1]
        if eligible_p2:
            p2 = random.choice(eligible_p2)
            return p1, p2
    return None, None # Cannot find two distinct people

# --- Path/Circle Helpers (Using optimized BFS) ---
def check_path_exists(start_node, end_node):
    """ Simple BFS to check reachability using person_neighbors """
    if start_node == end_node: return True
    # Check if nodes exist in the graph representation
    if start_node not in persons or end_node not in persons: return False

    q = deque([start_node])
    visited = {start_node}
    while q:
        curr = q.popleft()
        if curr == end_node:
            return True

        # OPTIMIZATION: Find neighbors using the precomputed list
        # Use .get() for safety in case a node exists in persons but not neighbors (shouldn't happen)
        neighbors = person_neighbors.get(curr, set())

        for neighbor in neighbors:
            # Ensure neighbor still exists in the main persons set (consistency check)
            if neighbor in persons and neighbor not in visited:
                visited.add(neighbor)
                q.append(neighbor)
    return False

def get_pair_with_path():
    # Relies on optimized check_path_exists
    if len(persons) < 2 or not relations: return None, None
    attempts = 0
    max_attempts = len(persons) * 5 # Might need more attempts
    while attempts < max_attempts:
        p1, p2 = get_two_random_persons()
        if p1 is not None and p2 is not None and check_path_exists(p1, p2):
            return p1, p2
        attempts += 1
    # Fallback: return a directly related pair if finding complex paths fails
    return get_existing_relation()

def get_pair_without_path():
     # Relies on optimized check_path_exists, but still potentially slow in dense graphs
     if len(persons) < 2: return None, None
     attempts = 0
     max_attempts = len(persons) * 5 # Finding non-existent paths can be hard
     while attempts < max_attempts:
         p1, p2 = get_two_random_persons()
         if p1 is not None and p2 is not None and p1 != p2 and not check_path_exists(p1, p2):
             return p1, p2
         attempts += 1
     # Fallback: difficult in dense graphs
     print("Warning: Fallback in get_pair_without_path (dense graph?)", file=sys.stderr)
     p1, p2 = get_non_existent_relation_pair() # Use the faster check here as fallback
     if p1 is not None and p2 is not None and not check_path_exists(p1, p2):
         return p1, p2
     return get_two_random_persons() # Final fallback

# --- Tag Helpers ---
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
    # OPTIMIZATION: Avoid sorted()
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
          if tag_id not in existing_tags:
               return tag_id
          attempts += 1
     return max_tag_id + random.randint(1,5)

def get_random_member_in_tag(owner_id, tag_id):
    tag_key = (owner_id, tag_id)
    members = tag_members.get(tag_key, set())
    # OPTIMIZATION: Avoid sorted()
    return random.choice(list(members)) if members else None

def get_related_person_not_in_tag(owner_id, tag_id):
    # OPTIMIZATION: Use person_neighbors instead of iterating relations
    if owner_id is None or tag_id is None or owner_id not in person_neighbors: return None
    related_persons = person_neighbors.get(owner_id, set()) # O(degree)
    tag_key = (owner_id, tag_id)
    current_members = tag_members.get(tag_key, set())
    # Possible members = (Neighbors of owner) - {owner itself} - {already in tag}
    possible_members = list(related_persons - {owner_id} - current_members) # Set difference is efficient
    # OPTIMIZATION: Avoid sorted()
    return random.choice(possible_members) if possible_members else None

def get_person_not_in_tag(owner_id, tag_id):
    tag_key = (owner_id, tag_id)
    current_members = tag_members.get(tag_key, set())
    # OPTIMIZATION: Avoid sorted()
    non_members = list(persons - current_members - {owner_id})
    return random.choice(non_members) if non_members else None

def get_random_empty_tag():
    empty_tags = []
    # OPTIMIZATION: Iterate through existing tag definitions, not all theoretical keys
    for (owner_id, tag_id), members in tag_members.items():
         # Check if owner and tag still technically exist
         if owner_id in persons and tag_id in person_tags.get(owner_id, set()):
             if not members:
                 empty_tags.append((owner_id, tag_id))
    # OPTIMIZATION: Avoid sorted()
    return random.choice(empty_tags) if empty_tags else (None, None)

def get_person_with_no_acquaintances():
     zero_degree_persons = [pid for pid in persons if person_degrees.get(pid, 0) == 0]
     # OPTIMIZATION: Avoid sorted()
     return random.choice(zero_degree_persons) if zero_degree_persons else None

# --- HW10 Account/Article Helpers ---
def get_random_account_id():
    # OPTIMIZATION: Avoid sorted()
    return random.choice(list(official_accounts)) if official_accounts else None

def get_non_existent_account_id(max_account_id):
    if not official_accounts: return random.randint(0, max_account_id)
    attempts = 0
    max_attempts = max(len(official_accounts) * 2, 20)
    max_possible_id = max(list(official_accounts)) if official_accounts else -1
    search_range_max = max(max_account_id + 10, max_possible_id + 10)

    while attempts < max_attempts:
        if random.random() < 0.7 and max_possible_id >= 0:
             aid = random.randint(max(0, max_possible_id - 5), max_possible_id + 10)
        else:
             aid = random.randint(0, search_range_max)
        if aid >= 0 and aid not in official_accounts:
            return aid
        attempts += 1
    return max(max_account_id, max_possible_id) + 1

def get_account_owner(account_id):
    return account_details.get(account_id, {}).get('owner')

def get_random_follower(account_id):
    followers = account_followers.get(account_id, set())
    # OPTIMIZATION: Avoid sorted()
    return random.choice(list(followers)) if followers else None

def get_person_not_following(account_id):
    if account_id not in official_accounts: return get_existing_person_id()
    followers = account_followers.get(account_id, set())
    # OPTIMIZATION: Avoid sorted()
    non_followers = list(persons - followers)
    return random.choice(non_followers) if non_followers else None

def get_random_account_with_followers():
     accounts_with_followers = [acc_id for acc_id in official_accounts if account_followers.get(acc_id)]
     # OPTIMIZATION: Avoid sorted()
     return random.choice(accounts_with_followers) if accounts_with_followers else None

def get_random_account_and_follower():
    acc_id = get_random_account_with_followers()
    if acc_id:
        follower_id = get_random_follower(acc_id)
        return acc_id, follower_id
    return None, None

def get_random_article_id():
    # OPTIMIZATION: Avoid sorted()
    return random.choice(list(all_articles)) if all_articles else None

def get_non_existent_article_id(max_article_id):
    if not all_articles: return random.randint(0, max_article_id)
    attempts = 0
    max_attempts = max(len(all_articles) * 2, 20)
    max_possible_id = max(list(all_articles)) if all_articles else -1
    search_range_max = max(max_article_id + 10, max_possible_id + 10)

    while attempts < max_attempts:
        if random.random() < 0.7 and max_possible_id >= 0:
            art_id = random.randint(max(0, max_possible_id - 5), max_possible_id + 10)
        else:
            art_id = random.randint(0, search_range_max)
        if art_id >= 0 and art_id not in all_articles:
            return art_id
        attempts += 1
    return max(max_article_id, max_possible_id) + 1

def get_random_article_in_account(account_id):
    articles_in_acc = account_articles.get(account_id, set())
    # OPTIMIZATION: Avoid sorted()
    return random.choice(list(articles_in_acc)) if articles_in_acc else None

def get_random_account_with_articles():
    acc_with_articles = [acc_id for acc_id, arts in account_articles.items() if arts]
    # OPTIMIZATION: Avoid sorted()
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
        person_neighbors[person_id] = set() # Initialize neighbor set
        return True
    return False

def add_relation_state(id1, id2, value, max_degree=None):
    # Ensure persons exist before adding relation/neighbors
    if id1 not in persons or id2 not in persons:
        print(f"Warning: Attempted to add relation between non-existent persons {id1}, {id2}", file=sys.stderr)
        return False
    if id1 == id2 or (min(id1, id2), max(id1, id2)) in relations:
         return False
    if max_degree is not None:
        if person_degrees.get(id1, 0) >= max_degree or person_degrees.get(id2, 0) >= max_degree:
            return False

    p1, p2 = min(id1, id2), max(id1, id2)
    rel_key = (p1, p2)
    relations.add(rel_key)
    relation_values[rel_key] = value
    person_degrees[id1] = person_degrees.get(id1, 0) + 1
    person_degrees[id2] = person_degrees.get(id2, 0) + 1
    # OPTIMIZATION: Maintain adjacency list
    person_neighbors[id1].add(id2)
    person_neighbors[id2].add(id1)
    return True

def remove_relation_state(id1, id2):
    # Handles removing people from each other's tags (existing logic)
    # Also handles removing from person_neighbors
    if id1 == id2: return False
    p1_orig, p2_orig = id1, id2
    p1, p2 = min(id1, id2), max(id1, id2)
    rel_key = (p1, p2)
    if rel_key in relations:
        relations.remove(rel_key)
        if rel_key in relation_values: del relation_values[rel_key]
        if p1_orig in person_degrees: person_degrees[p1_orig] -= 1
        if p2_orig in person_degrees: person_degrees[p2_orig] -= 1

        # OPTIMIZATION: Update adjacency list
        if id1 in person_neighbors: person_neighbors[id1].discard(id2)
        if id2 in person_neighbors: person_neighbors[id2].discard(id1)

        # JML: Remove from each other's tags (Keep this logic)
        tags_to_check_p1 = list(person_tags.get(p1_orig, set()))
        for tag_id in tags_to_check_p1:
             tag_key_p1_owns = (p1_orig, tag_id)
             if p2_orig in tag_members.get(tag_key_p1_owns, set()):
                 tag_members[tag_key_p1_owns].remove(p2_orig)
        tags_to_check_p2 = list(person_tags.get(p2_orig, set()))
        for tag_id in tags_to_check_p2:
             tag_key_p2_owns = (p2_orig, tag_id)
             if p1_orig in tag_members.get(tag_key_p2_owns, set()):
                 tag_members[tag_key_p2_owns].remove(p1_orig)
        return True
    return False

def add_tag_state(person_id, tag_id):
    if person_id not in persons: return False
    if tag_id not in person_tags[person_id]:
        person_tags[person_id].add(tag_id)
        # Ensure tag_members key exists even if empty initially
        if (person_id, tag_id) not in tag_members:
             tag_members[(person_id, tag_id)] = set()
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
    # OPTIMIZATION: Check relation using neighbors (faster)
    # Ensure both persons exist and check neighbors list
    related = (person_id1 in persons and
               person_id2 in persons and
               person_id1 in person_neighbors.get(person_id2, set()))

    # Preconditions (Match JML, using optimized relation check)
    if not (person_id1 in persons and person_id2 in persons): return False # PINF
    if person_id1 == person_id2: return False # EPI (p1==p2)
    # if p1_rel_p2_key not in relations: return False # RNF - Replaced check
    if not related: return False # RNF (using neighbors)
    if tag_id not in person_tags.get(person_id2, set()): return False # TINF
    if person_id1 in tag_members.get(tag_key, set()): return False # EPI (already in tag)

    current_size = len(tag_members.get(tag_key, set()))
    effective_max_size = 1000
    if max_tag_size is not None:
        effective_max_size = min(effective_max_size, max_tag_size)

    if current_size < effective_max_size:
        if tag_key not in tag_members: tag_members[tag_key] = set()
        tag_members[tag_key].add(person_id1)
        return True
    else: # Size limit reached
        return False

def remove_person_from_tag_state(person_id1, person_id2, tag_id):
    # Preconditions (Match JML)
    if person_id1 not in persons: return False # PINF (personId1)
    if person_id2 not in persons: return False # PINF (personId2)
    if tag_id not in person_tags.get(person_id2, set()): return False # TINF
    tag_key = (person_id2, tag_id)
    if person_id1 not in tag_members.get(tag_key, set()): return False # PINF (p1 not in tag)

    # Perform removal
    if tag_key in tag_members:
        tag_members[tag_key].remove(person_id1)
        return True
    return False


# --- HW10 State Updates (No direct relation to person_neighbors needed) ---
def create_official_account_state(person_id, account_id, name):
    if person_id not in persons: return False # PINF
    if account_id in official_accounts: return False # EOAI

    official_accounts.add(account_id)
    account_details[account_id] = {'owner': person_id, 'name': name}
    account_followers[account_id] = {person_id}
    account_contributions[account_id] = defaultdict(int)
    account_contributions[account_id][person_id] = 0
    account_articles[account_id] = set()
    return True

def delete_official_account_state(person_id, account_id):
    if person_id not in persons: return False # PINF
    if account_id not in official_accounts: return False # OAINF
    if account_details.get(account_id, {}).get('owner') != person_id: return False # DOAPD

    official_accounts.remove(account_id)
    if account_id in account_details: del account_details[account_id]
    if account_id in account_followers: del account_followers[account_id]
    if account_id in account_contributions: del account_contributions[account_id]

    articles_to_orphan = account_articles.get(account_id, set())
    for art_id in articles_to_orphan:
         if art_id in article_locations and article_locations[art_id] == account_id:
              del article_locations[art_id]
              # Keep in all_articles unless explicitly deleted by deleteArticle

    if account_id in account_articles: del account_articles[account_id]
    return True

def contribute_article_state(person_id, account_id, article_id):
    if person_id not in persons: return False # PINF
    if account_id not in official_accounts: return False # OAINF
    if article_id in all_articles: return False # EAI
    if person_id not in account_followers.get(account_id, set()): return False # CPD

    all_articles.add(article_id)
    article_contributors[article_id] = person_id
    article_locations[article_id] = account_id
    account_articles[account_id].add(article_id)
    account_contributions[account_id][person_id] = account_contributions[account_id].get(person_id, 0) + 1

    current_followers = account_followers.get(account_id, set())
    for follower_id in current_followers:
        if follower_id in person_received_articles:
            person_received_articles[follower_id].insert(0, article_id)
        else:
             person_received_articles[follower_id] = [article_id]

    return True

def delete_article_state(person_id, account_id, article_id):
    if person_id not in persons: return False # PINF
    if account_id not in official_accounts: return False # OAINF
    # AINF Check: Article must exist globally and be in this account's current list
    if article_id not in all_articles or article_id not in account_articles.get(account_id, set()): return False # AINF
    if account_details.get(account_id, {}).get('owner') != person_id: return False # DAPD

    if account_id in account_articles:
        account_articles[account_id].discard(article_id)

    if article_id in article_locations and article_locations[article_id] == account_id:
         del article_locations[article_id]

    original_contributor = article_contributors.get(article_id)
    if original_contributor is not None and account_id in account_contributions:
        if original_contributor in account_contributions[account_id]:
            account_contributions[account_id][original_contributor] -= 1
            # JML doesn't specify removing contributor key if count is 0

    current_followers = account_followers.get(account_id, set())
    for follower_id in current_followers:
        if follower_id in person_received_articles:
             try: # Use try-except in case list modified elsewhere or duplicates added (though shouldn't happen)
                  person_received_articles[follower_id].remove(article_id)
             except ValueError:
                  pass # Article not found in receiver's list, ignore

    # JML assignable doesn't include global articles or contributors.
    # So, we don't remove from all_articles or article_contributors here.
    # all_articles.discard(article_id) # DO NOT DO
    # if article_id in article_contributors: del article_contributors[article_id] # DO NOT DO

    return True


def follow_official_account_state(person_id, account_id):
    if person_id not in persons: return False # PINF
    if account_id not in official_accounts: return False # OAINF
    if person_id in account_followers.get(account_id, set()): return False # EPI

    account_followers[account_id].add(person_id)
    if account_id not in account_contributions:
        account_contributions[account_id] = defaultdict(int)
    account_contributions[account_id][person_id] = 0

    return True


# --- Command Weights Setup (Unchanged from previous version) ---
def get_command_weights(phase="default", tag_focus=0.3, account_focus=0.3):
    base_weights = {
        # --- Graph Structure / Person ---
        "ap": 10,  # Add Person (Keep relatively high for growth)
        "ar": 8,   # Add Relation (Moderate)
        "mr": 8,   # Modify Relation (Increased from 4, now same as ar)

        # --- Tags ---
        "at": 6,   # Add Tag (Moderate)
        "dt": 2,   # Delete Tag (Low)
        "att": 6,  # Add To Tag (Moderate)
        "dft": 3,  # Delete From Tag (Low)

        # --- Accounts / Articles ---
        "coa": 5,  # Create Official Account (Moderate Add)
        "doa": 1,  # Delete Official Account (Low Delete)
        "ca": 5,   # Contribute Article (Moderate Add)
        "da": 5,   # Delete Article (Increased significantly from 1, now same as ca/coa)
        "foa": 6,  # Follow Official Account (Moderate Add)

        # --- Queries ---
        "qv": 3,   # Query Value (Lowered from 10)
        "qci": 3,  # Query Circle (Lowered from 10)
        "qts": 2,  # Query Tag Size (Lowered from 4)
        "qtav": 8, # Query Tag Age Variance (Kept original)
        "qtvs": 8, # Query Tag Value Sum (Kept original)
        "qba": 3,  # Query Best Acquaintance (Lowered from 6)
        "qcs": 2,  # Query Couple Sum (Lowered from 3)
        "qsp": 3,  # Query Shortest Path (Lowered from 8)
        "qbc": 3,  # Query Best Contributor (Lowered from 5)
        "qra": 4,  # Query Received Articles (Lowered from 8)
    }
    # ... (rest of phase weights and focus adjustments remain the same as your provided version) ...
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

    # Adjust for tag_focus
    tag_cmds = {"at", "dt", "att", "dft", "qtav", "qtvs"}
    total_weight = sum(current_weights.values())
    if total_weight > 0 and tag_focus is not None:
        current_tag_weight = sum(w for cmd, w in current_weights.items() if cmd in tag_cmds)
        current_tag_ratio = current_tag_weight / total_weight if total_weight > 0 else 0
        non_tag_denominator = (1 - current_tag_ratio)
        if non_tag_denominator <= 1e-9: non_tag_denominator = 1 # Avoid division by zero/small number

        if abs(current_tag_ratio - tag_focus) > 0.05:
            scale_factor = (tag_focus / current_tag_ratio) if current_tag_ratio > 1e-9 else 1.5
            non_tag_scale = (1 - tag_focus) / non_tag_denominator

            for cmd in list(current_weights.keys()):
                weight = current_weights[cmd]
                if cmd in tag_cmds:
                    current_weights[cmd] = max(1, int(weight * scale_factor))
                else:
                    current_weights[cmd] = max(1, int(weight * non_tag_scale))
            total_weight = sum(current_weights.values()) # Recalculate total weight

    # Adjust for account_focus
    account_cmds = {"coa", "doa", "ca", "da", "foa", "qbc", "qra"}
    if total_weight > 0 and account_focus is not None:
        current_account_weight = sum(w for cmd, w in current_weights.items() if cmd in account_cmds)
        current_account_ratio = current_account_weight / total_weight if total_weight > 0 else 0
        # Denominator includes non-account AND non-tag commands if tag focus was also applied
        current_non_account_weight = total_weight - current_account_weight
        non_account_denominator = current_non_account_weight / total_weight if total_weight > 0 else 1
        if non_account_denominator <= 1e-9: non_account_denominator = 1

        if abs(current_account_ratio - account_focus) > 0.05:
            acc_scale_factor = (account_focus / current_account_ratio) if current_account_ratio > 1e-9 else 1.5
            # Scale only the non-account commands relative to their proportion
            non_acc_scale = (1 - account_focus) / non_account_denominator

            for cmd in list(current_weights.keys()):
                weight = current_weights[cmd]
                if cmd in account_cmds:
                    current_weights[cmd] = max(1, int(weight * acc_scale_factor))
                else: # Scale non-account commands
                    current_weights[cmd] = max(1, int(weight * non_acc_scale))

    return current_weights

# --- Phase Parsing (Unchanged) ---
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


# --- Exception Generation Logic (Added density param for qsp PNF) ---
def try_generate_exception_command(cmd_type, max_person_id, max_tag_id, max_account_id, max_article_id, density):
    """Attempts to generate parameters for cmd_type that cause a known exception."""
    cmd = None
    target_exception = None

    try:
        # --- HW9 Exceptions ---
        if cmd_type == "ap": # Target: EPI
            p_id = get_existing_person_id()
            if p_id is not None:
                name = generate_name(p_id)
                age = random.randint(1, 100)
                cmd = f"ap {p_id} {name} {age}"
                target_exception = "EqualPersonIdException (ap)"

        elif cmd_type == "ar": # Target: ER or PINF
            if random.random() < 0.6 and relations:
                p1, p2 = get_existing_relation()
                if p1 is not None and p2 is not None : # Ensure relation exists
                    value = random.randint(1, 100)
                    cmd = f"ar {p1} {p2} {value}"
                    target_exception = "EqualRelationException"
            else: # Target PINF
                p1 = get_existing_person_id()
                p2 = get_non_existent_person_id(max_person_id)
                if p1 is not None and p2 is not None:
                    if random.random() < 0.5: p1, p2 = p2, p1
                    value = random.randint(1, 100)
                    cmd = f"ar {p1} {p2} {value}"
                    target_exception = "PersonIdNotFoundException (ar)"

        elif cmd_type == "mr": # Target: PINF, EPI, RNF
            choice = random.random()
            if choice < 0.4: # Target PINF
                p1 = get_existing_person_id()
                p2 = get_non_existent_person_id(max_person_id)
                if p1 is not None and p2 is not None:
                    if random.random() < 0.5: p1, p2 = p2, p1
                    m_val = random.randint(-50, 50)
                    cmd = f"mr {p1} {p2} {m_val}"
                    target_exception = "PersonIdNotFoundException (mr)"
            elif choice < 0.7: # Target EPI (id1 == id2)
                 p1 = get_existing_person_id()
                 if p1 is not None:
                     m_val = random.randint(-50, 50)
                     cmd = f"mr {p1} {p1} {m_val}"
                     target_exception = "EqualPersonIdException (mr)"
            else: # Target RNF
                p1, p2 = get_non_existent_relation_pair() # Uses optimized helper
                if p1 is not None and p2 is not None:
                    m_val = random.randint(-50, 50)
                    cmd = f"mr {p1} {p2} {m_val}"
                    target_exception = "RelationNotFoundException (mr)"

        elif cmd_type == "at": # Target: PINF, ETI
            if random.random() < 0.5: # Target PINF
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None:
                     cmd = f"at {p_id} {tag_id}"
                     target_exception = "PersonIdNotFoundException (at)"
            else: # Target ETI
                owner_id, tag_id = get_random_tag_owner_and_tag()
                if owner_id is not None and tag_id is not None:
                    cmd = f"at {owner_id} {tag_id}"
                    target_exception = "EqualTagIdException"

        elif cmd_type == "dt": # Target: PINF, TINF
            if random.random() < 0.5: # Target PINF
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None:
                    cmd = f"dt {p_id} {tag_id}"
                    target_exception = "PersonIdNotFoundException (dt)"
            else: # Target TINF
                p_id = get_existing_person_id()
                if p_id is not None:
                    tag_id = get_non_existent_tag_id(p_id, max_tag_id)
                    cmd = f"dt {p_id} {tag_id}"
                    target_exception = "TagIdNotFoundException (dt)"

        elif cmd_type == "att": # Target: PINF, RNF, TINF, EPI
            choice = random.random()
            if choice < 0.2: # PINF (p1)
                p1 = get_non_existent_person_id(max_person_id)
                p2, tag_id = get_random_tag_owner_and_tag()
                if p1 is not None and p2 is not None and tag_id is not None:
                     cmd = f"att {p1} {p2} {tag_id}"
                     target_exception = "PersonIdNotFoundException (att p1)"
            elif choice < 0.4: # PINF (p2)
                 p1 = get_existing_person_id()
                 p2 = get_non_existent_person_id(max_person_id)
                 tag_id = random.randint(0, max_tag_id) # Tag doesn't need to exist on p2 for PINF
                 if p1 is not None and p2 is not None:
                      cmd = f"att {p1} {p2} {tag_id}"
                      target_exception = "PersonIdNotFoundException (att p2)"
            elif choice < 0.5: # EPI (p1 == p2)
                 p1 = get_existing_person_id()
                 tag_id = random.randint(0, max_tag_id) # Tag doesn't need to exist for EPI
                 if p1 is not None:
                      cmd = f"att {p1} {p1} {tag_id}"
                      target_exception = "EqualPersonIdException (att p1==p2)"
            elif choice < 0.65: # RNF
                p1, p2 = get_non_existent_relation_pair() # Find pair without relation
                # Need an existing tag owner (p2) and tag_id for TINF/EPI checks later
                owner_p2, tag_id_p2 = get_random_tag_owner_and_tag()
                if p1 is not None and p2 is not None and owner_p2 is not None and tag_id_p2 is not None:
                     # Use p2 as the target tag owner to ensure RNF is the likely exception
                     # We still need a valid tag ID, grab one from a random owner if p2 has none
                     if p2 in person_tags and person_tags[p2]:
                         tag_id_for_p2 = random.choice(list(person_tags[p2]))
                         cmd = f"att {p1} {p2} {tag_id_for_p2}"
                         target_exception = "RelationNotFoundException (att)"
                     else: # If p2 has no tags, use tag from random owner but target p2
                         cmd = f"att {p1} {p2} {tag_id_p2}" # p1 not related to p2, p2 has no tag tag_id_p2 -> RNF
                         target_exception = "RelationNotFoundException (att fallback RNF)"
            elif choice < 0.8: # TINF
                 p1, p2 = get_existing_relation() # p1 adds to p2's tag, need relation
                 if p1 is not None and p2 is not None:
                      tag_id = get_non_existent_tag_id(p2, max_tag_id) # Non-existent tag on p2
                      cmd = f"att {p1} {p2} {tag_id}"
                      target_exception = "TagIdNotFoundException (att)"
            else: # EPI (already in tag)
                owner_id, tag_id = get_random_tag_owner_and_tag(require_non_empty=True)
                if owner_id is not None and tag_id is not None:
                    member_id = get_random_member_in_tag(owner_id, tag_id)
                    # Ensure member is actually related to owner for EPI (att) to be possible
                    if member_id is not None and member_id in person_neighbors.get(owner_id, set()):
                        cmd = f"att {member_id} {owner_id} {tag_id}"
                        target_exception = "EqualPersonIdException (att already in tag)"
                    elif member_id is not None: # Member exists but not related - trigger RNF instead
                         cmd = f"att {member_id} {owner_id} {tag_id}"
                         target_exception = "RelationNotFoundException (att member not related)"


        elif cmd_type == "dft": # Target: PINF(p1), PINF(p2), TINF, PINF(p1 not in tag)
            choice = random.random()
            if choice < 0.2: # PINF (p1)
                p1 = get_non_existent_person_id(max_person_id)
                p2, tag_id = get_random_tag_owner_and_tag()
                if p1 is not None and p2 is not None and tag_id is not None:
                    cmd = f"dft {p1} {p2} {tag_id}"
                    target_exception = "PersonIdNotFoundException (dft p1)"
            elif choice < 0.4: # PINF (p2)
                p1 = get_existing_person_id()
                p2 = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p1 is not None and p2 is not None:
                    cmd = f"dft {p1} {p2} {tag_id}"
                    target_exception = "PersonIdNotFoundException (dft p2)"
            elif choice < 0.7: # TINF
                owner_id = get_existing_person_id()
                p1 = get_existing_person_id() # p1 needs to exist for TINF check
                if owner_id is not None and p1 is not None:
                    tag_id = get_non_existent_tag_id(owner_id, max_tag_id)
                    cmd = f"dft {p1} {owner_id} {tag_id}"
                    target_exception = "TagIdNotFoundException (dft)"
            else: # PINF (p1 not in tag)
                owner_id, tag_id = get_random_tag_owner_and_tag() # Find any tag
                if owner_id is not None and tag_id is not None:
                    # Find someone NOT in the tag (who exists)
                    p1 = get_person_not_in_tag(owner_id, tag_id)
                    if p1 is not None: # Ensure p1 exists
                        cmd = f"dft {p1} {owner_id} {tag_id}"
                        target_exception = "PersonIdNotFoundException (dft p1 not in tag)"

        elif cmd_type == "qv": # Target: PINF, RNF
             choice = random.random()
             if choice < 0.5: # PINF
                 p1 = get_existing_person_id()
                 p2 = get_non_existent_person_id(max_person_id)
                 if p1 is not None and p2 is not None:
                     if random.random() < 0.5: p1, p2 = p2, p1
                     cmd = f"qv {p1} {p2}"
                     target_exception = "PersonIdNotFoundException (qv)"
             else: # RNF
                 p1, p2 = get_non_existent_relation_pair() # Uses optimized helper
                 if p1 is not None and p2 is not None:
                     cmd = f"qv {p1} {p2}"
                     target_exception = "RelationNotFoundException (qv)"

        elif cmd_type == "qci": # Target: PINF
            p1 = get_existing_person_id()
            p2 = get_non_existent_person_id(max_person_id)
            if p1 is not None and p2 is not None:
                if random.random() < 0.5: p1, p2 = p2, p1
                cmd = f"qci {p1} {p2}"
                target_exception = "PersonIdNotFoundException (qci)"

        elif cmd_type == "qtav": # Target: PINF, TINF
            choice = random.random()
            if choice < 0.5: # PINF
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None:
                    cmd = f"qtav {p_id} {tag_id}"
                    target_exception = "PersonIdNotFoundException (qtav)"
            else: # TINF
                p_id = get_existing_person_id()
                if p_id is not None:
                    tag_id = get_non_existent_tag_id(p_id, max_tag_id)
                    cmd = f"qtav {p_id} {tag_id}"
                    target_exception = "TagIdNotFoundException (qtav)"

        elif cmd_type == "qtvs": # Target: PINF, TINF (Same as qtav)
            choice = random.random()
            if choice < 0.5: # PINF
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None:
                    cmd = f"qtvs {p_id} {tag_id}"
                    target_exception = "PersonIdNotFoundException (qtvs)"
            else: # TINF
                p_id = get_existing_person_id()
                if p_id is not None:
                    tag_id = get_non_existent_tag_id(p_id, max_tag_id)
                    cmd = f"qtvs {p_id} {tag_id}"
                    target_exception = "TagIdNotFoundException (qtvs)"

        elif cmd_type == "qba": # Target: PINF, ANF
            choice = random.random()
            if choice < 0.5: # PINF
                p_id = get_non_existent_person_id(max_person_id)
                if p_id is not None:
                    cmd = f"qba {p_id}"
                    target_exception = "PersonIdNotFoundException (qba)"
            else: # ANF
                p_id = get_person_with_no_acquaintances()
                if p_id is not None:
                    cmd = f"qba {p_id}"
                    target_exception = "AcquaintanceNotFoundException"

        elif cmd_type == "qsp": # Target: PINF, PNF
            choice = random.random()
            if choice < 0.4: # PINF (id1)
                p1 = get_non_existent_person_id(max_person_id)
                p2 = get_existing_person_id()
                if p1 is not None and p2 is not None:
                     cmd = f"qsp {p1} {p2}"
                     target_exception = "PersonIdNotFoundException (qsp p1)"
            elif choice < 0.7: # PINF (id2)
                 p1 = get_existing_person_id()
                 p2 = get_non_existent_person_id(max_person_id)
                 if p1 is not None and p2 is not None:
                      cmd = f"qsp {p1} {p2}"
                      target_exception = "PersonIdNotFoundException (qsp p2)"
            else: # PNF
                 p1, p2 = None, None
                 # OPTIMIZATION: Avoid slow get_pair_without_path in dense graphs
                 if density > 0.7:
                     # Use non-existent relation pair; less likely to have path, but much faster to find
                     p1, p2 = get_non_existent_relation_pair()
                     target_exception = "PathNotFoundException (dense graph heuristic)"
                 else:
                     # Use original BFS-based search for sparse graphs
                     p1, p2 = get_pair_without_path()
                     target_exception = "PathNotFoundException (sparse graph search)"

                 if p1 is not None and p2 is not None:
                      # Ensure p1 != p2 for qsp
                      if p1 == p2:
                           p1_alt, p2_alt = get_two_random_persons()
                           if p1_alt != p2_alt: p1, p2 = p1_alt, p2_alt

                      if p1 != p2 :
                          cmd = f"qsp {p1} {p2}"
                          # Keep target_exception assigned above based on density heuristic

        # --- HW10 Exceptions ---
        elif cmd_type == "coa": # Target: PINF, EOAI
            if random.random() < 0.5: # Target PINF
                p_id = get_non_existent_person_id(max_person_id)
                acc_id = get_non_existent_account_id(max_account_id)
                name = generate_name(acc_id, "Acc")
                if p_id is not None:
                     cmd = f"coa {p_id} {acc_id} {name}"
                     target_exception = "PersonIdNotFoundException (coa)"
            else: # Target EOAI
                 p_id = get_existing_person_id()
                 acc_id = get_random_account_id()
                 if p_id is not None and acc_id is not None:
                      name = generate_name(acc_id, "Acc")
                      cmd = f"coa {p_id} {acc_id} {name}"
                      target_exception = "EqualOfficialAccountIdException"

        elif cmd_type == "doa": # Target: PINF, OAINF, DOAPD
             choice = random.random()
             if choice < 0.3: # PINF
                 p_id = get_non_existent_person_id(max_person_id)
                 acc_id = get_random_account_id()
                 if p_id is not None and acc_id is not None:
                      cmd = f"doa {p_id} {acc_id}"
                      target_exception = "PersonIdNotFoundException (doa)"
             elif choice < 0.6: # OAINF
                  p_id = get_existing_person_id()
                  acc_id = get_non_existent_account_id(max_account_id)
                  if p_id is not None and acc_id is not None:
                       cmd = f"doa {p_id} {acc_id}"
                       target_exception = "OfficialAccountIdNotFoundException"
             else: # DOAPD
                  acc_id = get_random_account_id()
                  if acc_id is not None:
                      owner_id = get_account_owner(acc_id)
                      # Find someone who is NOT the owner (and exists)
                      non_owner_id = None
                      # OPTIMIZATION: Avoid sorted()
                      eligible_non_owners = list(persons - {owner_id})
                      if eligible_non_owners:
                          non_owner_id = random.choice(eligible_non_owners)

                      if non_owner_id is not None:
                           cmd = f"doa {non_owner_id} {acc_id}"
                           target_exception = "DeleteOfficialAccountPermissionDeniedException"

        elif cmd_type == "ca": # Target: PINF, OAINF, EAI, CPD
             choice = random.random()
             if choice < 0.2: # PINF
                 p_id = get_non_existent_person_id(max_person_id)
                 acc_id = get_random_account_id()
                 art_id = get_non_existent_article_id(max_article_id)
                 if p_id is not None and acc_id is not None:
                      cmd = f"ca {p_id} {acc_id} {art_id}"
                      target_exception = "PersonIdNotFoundException (ca)"
             elif choice < 0.4: # OAINF
                  p_id = get_existing_person_id()
                  acc_id = get_non_existent_account_id(max_account_id)
                  art_id = get_non_existent_article_id(max_article_id)
                  if p_id is not None and acc_id is not None:
                       cmd = f"ca {p_id} {acc_id} {art_id}"
                       target_exception = "OfficialAccountIdNotFoundException (ca)"
             elif choice < 0.6: # EAI
                  p_id = get_existing_person_id() # Needs to be follower
                  acc_id, art_id = get_random_account_and_article() # Get existing article
                  if p_id is not None and acc_id is not None and art_id is not None:
                       # Ensure p_id follows acc_id to isolate EAI
                       if p_id in account_followers.get(acc_id, set()):
                            cmd = f"ca {p_id} {acc_id} {art_id}"
                            target_exception = "EqualArticleIdException"
                       # else: if not follower, CPD would trigger first, so this is okay
             else: # CPD
                  acc_id = get_random_account_id()
                  art_id = get_non_existent_article_id(max_article_id)
                  if acc_id is not None:
                      p_id = get_person_not_following(acc_id) # Find non-follower (who exists)
                      if p_id is not None:
                           cmd = f"ca {p_id} {acc_id} {art_id}"
                           target_exception = "ContributePermissionDeniedException"

        elif cmd_type == "da": # Target: PINF, OAINF, AINF, DAPD
             choice = random.random()
             if choice < 0.2: # PINF
                 p_id = get_non_existent_person_id(max_person_id)
                 acc_id, art_id = get_random_account_and_article()
                 # Ensure acc_id and art_id were found
                 if p_id is not None and acc_id is not None and art_id is not None:
                      cmd = f"da {p_id} {acc_id} {art_id}"
                      target_exception = "PersonIdNotFoundException (da)"
             elif choice < 0.4: # OAINF
                  p_id = get_existing_person_id() # Needs to be owner later
                  acc_id = get_non_existent_account_id(max_account_id)
                  art_id = get_random_article_id() # Doesn't matter which article
                  if p_id is not None and acc_id is not None and art_id is not None: # Check art_id exists
                       cmd = f"da {p_id} {acc_id} {art_id}"
                       target_exception = "OfficialAccountIdNotFoundException (da)"
             elif choice < 0.6: # AINF
                  acc_id = get_random_account_id()
                  if acc_id is not None:
                      owner_id = get_account_owner(acc_id)
                      # Find an article NOT currently in this account
                      articles_in_acc = account_articles.get(acc_id, set())
                      # OPTIMIZATION: Avoid sorted()
                      other_articles = list(all_articles - articles_in_acc)
                      art_id_not_in_acc = random.choice(other_articles) if other_articles else None

                      if owner_id is not None and art_id_not_in_acc is not None : # Ensure owner exists and found other article
                          cmd = f"da {owner_id} {acc_id} {art_id_not_in_acc}"
                          target_exception = "ArticleIdNotFoundException"
                      elif owner_id is not None: # If no other articles, try non-existent ID
                           non_existent_art_id = get_non_existent_article_id(max_article_id)
                           cmd = f"da {owner_id} {acc_id} {non_existent_art_id}"
                           target_exception = "ArticleIdNotFoundException (non-existent)"

             else: # DAPD
                  acc_id, art_id = get_random_account_and_article()
                  if acc_id is not None and art_id is not None:
                      owner_id = get_account_owner(acc_id)
                      # Find someone who is NOT the owner (and exists)
                      non_owner_id = None
                      # OPTIMIZATION: Avoid sorted()
                      eligible_non_owners = list(persons - {owner_id})
                      if eligible_non_owners:
                          non_owner_id = random.choice(eligible_non_owners)

                      if non_owner_id is not None:
                           cmd = f"da {non_owner_id} {acc_id} {art_id}"
                           target_exception = "DeleteArticlePermissionDeniedException"


        elif cmd_type == "foa": # Target: PINF, OAINF, EPI (already follows)
             choice = random.random()
             if choice < 0.3: # PINF
                 p_id = get_non_existent_person_id(max_person_id)
                 acc_id = get_random_account_id()
                 if p_id is not None and acc_id is not None:
                      cmd = f"foa {p_id} {acc_id}"
                      target_exception = "PersonIdNotFoundException (foa)"
             elif choice < 0.6: # OAINF
                  p_id = get_existing_person_id()
                  acc_id = get_non_existent_account_id(max_account_id)
                  if p_id is not None and acc_id is not None:
                       cmd = f"foa {p_id} {acc_id}"
                       target_exception = "OfficialAccountIdNotFoundException (foa)"
             else: # EPI (already follows)
                  acc_id, follower_id = get_random_account_and_follower()
                  if acc_id is not None and follower_id is not None:
                       cmd = f"foa {follower_id} {acc_id}"
                       target_exception = "EqualPersonIdException (foa already follows)"

        elif cmd_type == "qbc": # Target: OAINF
            acc_id = get_non_existent_account_id(max_account_id)
            if acc_id is not None:
                cmd = f"qbc {acc_id}"
                target_exception = "OfficialAccountIdNotFoundException (qbc)"

        elif cmd_type == "qra": # Target: PINF
            p_id = get_non_existent_person_id(max_person_id)
            if p_id is not None:
                cmd = f"qra {p_id}"
                target_exception = "PersonIdNotFoundException (qra)"


    except Exception as e:
        print(f"ERROR during *exception* generation for {cmd_type}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return None # Failed to generate exception command

    # if cmd: print(f"DEBUG: Generated exception command for {target_exception}: {cmd}", file=sys.stderr)
    return cmd


# --- Main Generation Logic ---
def generate_commands(num_commands_target, max_person_id, max_tag_id, max_account_id, max_article_id,
                      max_rel_value, max_mod_value, max_age,
                      min_qci, min_qts, min_qtav, min_qba, min_qcs, min_qsp, min_qtvs, min_qbc, min_qra, # Min query counts
                      density, degree_focus_unused, max_degree, tag_focus, account_focus, max_tag_size, qci_focus, # degree_focus unused
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
    initial_people = min(num_commands_to_generate // 10 + 5, max_person_id + 1, 100)
    if hub_bias > 0: initial_people = max(initial_people, num_hubs)
    current_id = 0
    for _ in range(initial_people):
        if current_id > max_person_id: break
        person_id = current_id
        if person_id not in persons:
             name = generate_name(person_id, "Person")
             age = random.randint(1, max_age)
             if add_person_state(person_id, name, age):
                 cmd = f"ap {person_id} {name} {age}"
                 generated_cmds_list.append(cmd)
                 cmd_counts['ap'] += 1
        current_id += 1
    hub_ids = set(range(min(num_hubs, initial_people))) if num_hubs > 0 else set() # Ensure hubs actually exist

    # --- Main Generation Loop ---
    while len(generated_cmds_list) < num_commands_to_generate:
        # Determine current phase and get weights
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

        # --- Filter out impossible commands based on state ---
        can_add_person = any(i for i in range(max_person_id + 1) if i not in persons) or max_person_id + 1 not in persons # Check if any ID possible
        if not persons and not can_add_person:
             print("ERROR: Cannot add more persons and no persons exist. Stopping.", file=sys.stderr)
             break
        elif not persons:
             weights_dict = {'ap': 1} # Force add person if possible
        else:
            if len(persons) < 2:
                weights_dict.pop("ar", None); weights_dict.pop("mr", None); weights_dict.pop("qv", None)
                weights_dict.pop("qci", None); weights_dict.pop("att", None); weights_dict.pop("dft", None)
                weights_dict.pop("qsp", None)
            if not relations: # Check relations set, not neighbors dict
                weights_dict.pop("mr", None); # Cannot modify non-existent relation
                # Can still try RNF for qv, att
            if not person_neighbors: # Check neighbors dict for qba
                 weights_dict.pop("qba", None) # ANF impossible if no neighbors exist at all
            if not any(person_tags.values()):
                weights_dict.pop("dt", None); weights_dict.pop("qtav", None); weights_dict.pop("qtvs", None)
                # Can still try TINF for att, dft
            if not any(tag_members.values()):
                weights_dict.pop("dft", None) # Cannot remove from empty tags

            # HW10 Filters
            if not official_accounts:
                weights_dict.pop("doa", None); weights_dict.pop("ca", None); weights_dict.pop("da", None)
                weights_dict.pop("foa", None); weights_dict.pop("qbc", None)
            # Check if any account has followers (excluding owner if they haven't contributed)
            can_contribute = any(len(account_followers.get(acc_id, set())) > 0 for acc_id in official_accounts)
            if not can_contribute:
                 weights_dict.pop("ca", None) # CPD impossible if no accounts have any followers
            # Check if any account has contributors for qbc
            can_qbc = any(any(c > 0 for c in contribs.values()) for contribs in account_contributions.values())
            if not can_qbc:
                 weights_dict.pop("qbc", None)
            # Check if any article exists *and* is in an account for 'da'
            can_delete_article = any(art_id in account_articles.get(acc_id, set()) for acc_id in official_accounts for art_id in all_articles)
            if not all_articles or not can_delete_article:
                 weights_dict.pop("da", None)

        if not weights_dict:
             # Try to add person if state is completely stuck
             if can_add_person:
                 print("Warning: No commands possible with current state and weights! Trying to add person.", file=sys.stderr)
                 cmd_type = 'ap' # Force attempt to add person
             else:
                 print("ERROR: No commands possible and cannot add person. Breaking loop.", file=sys.stderr)
                 break # Truly stuck
        else:
             # --- Choose Command Type ---
             command_types = list(weights_dict.keys()) # No need to sort for random.choices
             weights = [weights_dict[cmd_type] for cmd_type in command_types]
             if sum(weights) <= 0:
                 # Fallback if all weights became zero
                 print("Warning: Zero total weight for command selection. Choosing random available.", file=sys.stderr)
                 cmd_type = random.choice(command_types) if command_types else 'ap' # Failsafe
             else:
                 cmd_type = random.choices(command_types, weights=weights, k=1)[0]


        cmd = None
        generated_successfully = False

        # --- Attempt Exception Generation ---
        if random.random() < exception_ratio:
            # Pass density for qsp PNF optimization
            cmd = try_generate_exception_command(cmd_type, max_person_id, max_tag_id, max_account_id, max_article_id, density)
            if cmd:
                generated_successfully = True
            # else: Fallback to normal generation

        # --- Normal Command Generation (or fallback) ---
        if not generated_successfully:
            try:
                # Force Edge Cases
                force_qba_empty = (cmd_type == "qba" and random.random() < force_qba_empty_ratio)
                force_qtav_empty = (cmd_type == "qtav" and random.random() < force_qtav_empty_ratio)

                # --- Command Generation ---
                if cmd_type == "ap":
                    # Try finding non-existent ID first
                    person_id = get_non_existent_person_id(max_person_id)
                    # Ensure generated ID is within the allowed range
                    if person_id >= 0 and person_id <= max_person_id:
                        name = generate_name(person_id, "Person")
                        age = random.randint(1, max_age)
                        if add_person_state(person_id, name, age):
                            cmd = f"ap {person_id} {name} {age}"
                            generated_successfully = True
                    # Else: couldn't find valid ID, try again next loop

                elif cmd_type == "ar":
                    p1, p2 = None, None
                    use_hub = (hub_ids and random.random() < hub_bias)
                    if use_hub:
                        # Ensure hub_id exists and there are others to connect to
                        valid_hubs = list(hub_ids.intersection(persons))
                        if valid_hubs:
                             hub_id = random.choice(valid_hubs)
                             # OPTIMIZATION: Avoid sorted()
                             eligible_others = list(persons - {hub_id})
                             if eligible_others:
                                 other_p = random.choice(eligible_others)
                                 p1, p2 = hub_id, other_p
                    # Fallback or no hub bias
                    if p1 is None or p2 is None:
                       p1, p2 = get_two_random_persons()

                    if p1 is not None and p2 is not None:
                        # Density check logic (simplified) - add if below target density
                        current_nodes = len(persons)
                        max_possible_edges = (current_nodes * (current_nodes - 1)) // 2 if current_nodes > 1 else 0
                        current_density = len(relations) / max_possible_edges if max_possible_edges > 0 else 0.0
                        # Add more readily if below target, less readily if above
                        prob_add = 0.5 + (density - current_density) * 2.0 # Stronger push towards target
                        prob_add = max(0.01, min(0.99, prob_add)) # Clamp probability

                        if random.random() < prob_add:
                            value = random.randint(1, max_rel_value)
                            if add_relation_state(p1, p2, value, max_degree):
                                cmd = f"ar {p1} {p2} {value}"
                                generated_successfully = True

                elif cmd_type == "mr":
                    p1, p2 = get_random_relation()
                    if p1 is not None and p2 is not None: # Check relation was found
                        rel_key = (min(p1,p2), max(p1,p2)) # Ensure canonical key
                        current_value = relation_values.get(rel_key, 0) # Default to 0 if somehow missing
                        m_val = 0
                        if current_value > 0 and random.random() < mr_delete_ratio:
                            m_val = -current_value - random.randint(0, 10)
                        else:
                            effective_max_mod = max(1, max_mod_value)
                            m_val = random.randint(-effective_max_mod, effective_max_mod)
                            # Ensure m_val is not 0 unless max_mod_value is 0
                            if m_val == 0 and max_mod_value != 0:
                                m_val = random.choice([-1, 1]) * random.randint(1, effective_max_mod)

                        if hce_active: m_val = max(-200, min(200, m_val))

                        cmd = f"mr {p1} {p2} {m_val}"
                        generated_successfully = True

                        # State update handled AFTER generating command string
                        new_value = current_value + m_val
                        if new_value <= 0:
                            remove_relation_state(p1, p2) # Uses optimized version
                        else:
                            relation_values[rel_key] = new_value # Update existing value

                elif cmd_type == "at":
                    person_id = get_existing_person_id()
                    if person_id is not None:
                        tag_id = random.randint(0, max_tag_id)
                        if add_tag_state(person_id, tag_id):
                             cmd = f"at {person_id} {tag_id}"
                             generated_successfully = True

                elif cmd_type == "dt":
                    owner_id, tag_id = get_random_tag_owner_and_tag()
                    if owner_id is not None and tag_id is not None:
                        if remove_tag_state(owner_id, tag_id):
                            cmd = f"dt {owner_id} {tag_id}"
                            generated_successfully = True

                elif cmd_type == "att":
                     owner_id, tag_id = get_random_tag_owner_and_tag()
                     if owner_id is not None and tag_id is not None:
                         # Uses optimized helper with neighbor check
                         person_id1 = get_related_person_not_in_tag(owner_id, tag_id)
                         if person_id1 is not None:
                             # add_person_to_tag_state already does necessary checks (incl. relation)
                             if add_person_to_tag_state(person_id1, owner_id, tag_id, max_tag_size):
                                cmd = f"att {person_id1} {owner_id} {tag_id}"
                                generated_successfully = True

                elif cmd_type == "dft":
                     owner_id, tag_id = get_random_tag_owner_and_tag(require_non_empty=True)
                     if owner_id is not None and tag_id is not None:
                         member_id = get_random_member_in_tag(owner_id, tag_id)
                         if member_id is not None:
                             if remove_person_from_tag_state(member_id, owner_id, tag_id):
                                cmd = f"dft {member_id} {owner_id} {tag_id}"
                                generated_successfully = True

                # --- HW10 Add/Delete/Follow ---
                elif cmd_type == "coa":
                    person_id = get_existing_person_id()
                    account_id = get_non_existent_account_id(max_account_id)
                    if person_id is not None and account_id >= 0 and account_id <= max_account_id:
                         name = generate_name(account_id, "Acc")
                         if create_official_account_state(person_id, account_id, name):
                              cmd = f"coa {person_id} {account_id} {name}"
                              generated_successfully = True

                elif cmd_type == "doa":
                    # Try to pick an account owned by an existing person
                    owner_id = None
                    acc_id = None
                    # Get accounts with existing owners efficiently
                    accounts_with_owners = {acc_id: details['owner'] for acc_id, details in account_details.items() if details['owner'] in persons}
                    if accounts_with_owners:
                         acc_id = random.choice(list(accounts_with_owners.keys()))
                         owner_id = accounts_with_owners[acc_id]

                    if owner_id is not None and acc_id is not None:
                        if delete_official_account_state(owner_id, acc_id):
                            cmd = f"doa {owner_id} {acc_id}"
                            generated_successfully = True

                elif cmd_type == "ca":
                     # Ensure the contributor (follower) exists
                     acc_id = get_random_account_id()
                     if acc_id:
                         eligible_followers = list(account_followers.get(acc_id, set()).intersection(persons))
                         if eligible_followers:
                             follower_id = random.choice(eligible_followers)
                             article_id = get_non_existent_article_id(max_article_id)
                             if article_id >= 0 and article_id <= max_article_id:
                                 if contribute_article_state(follower_id, acc_id, article_id):
                                      cmd = f"ca {follower_id} {acc_id} {article_id}"
                                      generated_successfully = True

                elif cmd_type == "da":
                     # Ensure the owner exists
                     acc_id, art_id = get_random_account_and_article()
                     if acc_id is not None and art_id is not None:
                         owner_id = get_account_owner(acc_id)
                         if owner_id is not None and owner_id in persons: # Check owner exists
                              if delete_article_state(owner_id, acc_id, art_id):
                                   cmd = f"da {owner_id} {acc_id} {art_id}"
                                   generated_successfully = True

                elif cmd_type == "foa":
                     acc_id = get_random_account_id()
                     if acc_id is not None:
                         person_id = get_person_not_following(acc_id) # Returns existing person
                         if person_id is not None:
                              if follow_official_account_state(person_id, acc_id):
                                   cmd = f"foa {person_id} {acc_id}"
                                   generated_successfully = True

                # --- Query Commands ---
                elif cmd_type == "qv":
                    # Prioritize existing relations slightly more in normal generation
                    if random.random() < 0.8 and relations:
                        p1, p2 = get_random_relation()
                    else:
                        p1, p2 = get_two_random_persons()
                    if p1 is not None and p2 is not None:
                        cmd = f"qv {p1} {p2}"
                        generated_successfully = True

                elif cmd_type == "qci":
                     p1, p2 = None, None
                     # Focus primarily on random pairs, let BFS handle reachability
                     if qci_focus == 'close' and relations and random.random() < 0.5: p1, p2 = get_random_relation()
                     elif qci_focus == 'far' and random.random() < 0.5: p1, p2 = get_non_existent_relation_pair()
                     # Fallback to any random pair
                     if p1 is None or p2 is None: p1, p2 = get_two_random_persons()

                     if p1 is not None and p2 is not None:
                          cmd = f"qci {p1} {p2}"
                          generated_successfully = True

                elif cmd_type == "qts":
                     cmd = "qts"
                     generated_successfully = True

                elif cmd_type == "qtav":
                    owner_id, tag_id = None, None
                    if force_qtav_empty: owner_id, tag_id = get_random_empty_tag()
                    if owner_id is None: # If not forcing empty or failed to find one
                        owner_id, tag_id = get_random_tag_owner_and_tag()
                        # If no tags exist, generate random params
                        if owner_id is None:
                             owner_id = get_existing_person_id()
                             tag_id = random.randint(0, max_tag_id)

                    if owner_id is not None and tag_id is not None:
                        cmd = f"qtav {owner_id} {tag_id}"
                        generated_successfully = True

                elif cmd_type == "qtvs":
                    owner_id, tag_id = None, None
                    # Similar logic to qtav for param selection
                    # if force_qtvs_empty: owner_id, tag_id = get_random_empty_tag() # Could add later
                    if owner_id is None:
                        owner_id, tag_id = get_random_tag_owner_and_tag()
                        if owner_id is None:
                             owner_id = get_existing_person_id()
                             tag_id = random.randint(0, max_tag_id)

                    if owner_id is not None and tag_id is not None:
                        cmd = f"qtvs {owner_id} {tag_id}"
                        generated_successfully = True

                elif cmd_type == "qba":
                     person_id = None
                     if force_qba_empty: person_id = get_person_with_no_acquaintances()
                     # If not forcing or failed, get a random person (preferably with degree > 0)
                     if person_id is None:
                         # Try harder to get someone with neighbors
                         person_id = get_random_person(require_degree_greater_than=0 if random.random() < 0.95 else None)
                         # Fallback if still None
                         if person_id is None: person_id = get_existing_person_id()

                     if person_id is not None:
                          cmd = f"qba {person_id}"
                          generated_successfully = True

                elif cmd_type == "qcs":
                     cmd = "qcs"
                     generated_successfully = True

                elif cmd_type == "qsp":
                    p1, p2 = None, None
                    # Prioritize pairs with likely path in normal generation
                    if random.random() < 0.8:
                        p1, p2 = get_pair_with_path()
                    else:
                        p1, p2 = get_two_random_persons() # Any random pair

                    # Fallback if path finding fails
                    if p1 is None or p2 is None:
                         p1, p2 = get_two_random_persons()

                    if p1 is not None and p2 is not None and p1 != p2: # Ensure distinct persons
                         cmd = f"qsp {p1} {p2}"
                         generated_successfully = True
                    elif p1 is not None and p2 is not None and p1 == p2 : # Try one more time if same person selected
                        p1_alt, p2_alt = get_two_random_persons()
                        if p1_alt is not None and p2_alt is not None and p1_alt != p2_alt:
                             cmd = f"qsp {p1_alt} {p2_alt}"
                             generated_successfully = True


                elif cmd_type == "qbc":
                     account_id = get_random_account_with_followers() # Prefer accounts with followers
                     if account_id is None: # Fallback to any account
                         account_id = get_random_account_id()

                     if account_id is not None:
                         cmd = f"qbc {account_id}"
                         generated_successfully = True

                elif cmd_type == "qra":
                     person_id = get_existing_person_id()
                     if person_id is not None:
                          cmd = f"qra {person_id}"
                          generated_successfully = True

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
        # else: Failed, loop continues

    # --- Supplementary loop for minimum query counts ---
    min_counts_map = {
        "qci": min_qci, "qts": min_qts, "qtav": min_qtav, "qba": min_qba,
        "qcs": min_qcs, "qsp": min_qsp, "qtvs": min_qtvs, "qbc": min_qbc, "qra": min_qra
    }
    supplementary_cmds = [] # Generate supplementary commands separately to avoid state side effects during loop

    for query_type, min_req in min_counts_map.items():
        needed = min_req - cmd_counts[query_type]
        if needed <= 0: continue

        attempts = 0
        max_attempts_supp = needed * 5 + 20 # Max attempts proportional to need
        generated_supp = 0

        while generated_supp < needed and attempts < max_attempts_supp:
            cmd = None
            attempts += 1
            try:
                # Generate parameters based on *current* state
                if query_type == "qci":
                    p1, p2 = get_two_random_persons()
                    if p1 is not None and p2 is not None: cmd = f"qci {p1} {p2}"
                elif query_type == "qts":
                    cmd = "qts"
                elif query_type == "qtav":
                    owner_id, tag_id = get_random_tag_owner_and_tag()
                    if owner_id is None: # Fallback
                        owner_id = get_existing_person_id()
                        if owner_id is not None: tag_id = random.randint(0, max_tag_id)
                        else: tag_id = None # Cannot generate if no owner
                    if owner_id is not None and tag_id is not None: cmd = f"qtav {owner_id} {tag_id}"
                elif query_type == "qtvs":
                    owner_id, tag_id = get_random_tag_owner_and_tag()
                    if owner_id is None: # Fallback
                        owner_id = get_existing_person_id()
                        if owner_id is not None: tag_id = random.randint(0, max_tag_id)
                        else: tag_id = None
                    if owner_id is not None and tag_id is not None: cmd = f"qtvs {owner_id} {tag_id}"
                elif query_type == "qba":
                    person_id = get_existing_person_id() # Get any existing person
                    if person_id is not None: cmd = f"qba {person_id}"
                elif query_type == "qcs":
                    cmd = "qcs"
                elif query_type == "qsp":
                    p1, p2 = get_two_random_persons()
                    if p1 is not None and p2 is not None and p1 != p2: cmd = f"qsp {p1} {p2}"
                    elif p1 is not None and p2 is not None: # Try again if same person
                        p1_alt, p2_alt = get_two_random_persons()
                        if p1_alt is not None and p2_alt is not None and p1_alt != p2_alt:
                            cmd = f"qsp {p1_alt} {p2_alt}"
                elif query_type == "qbc":
                    account_id = get_random_account_id() # Get any existing account
                    if account_id is not None: cmd = f"qbc {account_id}"
                elif query_type == "qra":
                    person_id = get_existing_person_id() # Get any existing person
                    if person_id is not None: cmd = f"qra {person_id}"

            except Exception as e:
                 print(f"ERROR generating supplementary command {query_type}: {e}", file=sys.stderr)
                 traceback.print_exc(file=sys.stderr)

            if cmd:
                supplementary_cmds.append(cmd)
                generated_supp += 1

        if generated_supp < needed:
             print(f"Warning: Could only generate {generated_supp}/{needed} required supplementary '{query_type}' commands after {attempts} attempts.", file=sys.stderr)

    # Add supplementary commands to the end
    generated_cmds_list.extend(supplementary_cmds)
    # Update counts for summary display (optional, main loop counts are more representative of generation process)
    for cmd_str in supplementary_cmds:
        cmd_type_supp = cmd_str.split()[0]
        cmd_counts[cmd_type_supp] += 1


    return generated_cmds_list, cmd_counts


# --- Argument Parsing (Added HW10 args) ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate test data for HW10 social network.")

    # Core Controls
    parser.add_argument("-n", "--num_commands", type=int, default=2000, help="Target number of commands (ignored if --phases is set).")
    parser.add_argument("--max_person_id", type=int, default=150, help="Maximum person ID (0 to max).")
    parser.add_argument("--max_tag_id", type=int, default=15, help="Maximum tag ID per person (0 to max).")
    parser.add_argument("--max_account_id", type=int, default=50, help="Maximum official account ID (0 to max).")
    parser.add_argument("--max_article_id", type=int, default=500, help="Maximum article ID (0 to max).")
    parser.add_argument("--max_age", type=int, default=200, help="Maximum person age (default 200).")
    parser.add_argument("-o", "--output_file", type=str, default=None, help="Output file name (default: stdout).")
    parser.add_argument("--hce", action='store_true', help="Enable HCE constraints (Mutual Test limits: N<=3000, max_person_id<=99, values<=200).")
    parser.add_argument("--seed", type=int, default=None, help="Seed for the random number generator.")

    # Relation/Value Controls
    parser.add_argument("--max_rel_value", type=int, default=200, help="Maximum initial relation value (default 200).")
    parser.add_argument("--max_mod_value", type=int, default=200, help="Maximum absolute modify relation value change (default 200).")
    parser.add_argument("--mr_delete_ratio", type=float, default=0.15, help="Approx. ratio of 'mr' commands targeting relation deletion (0.0-1.0).")

    # Graph Structure Controls
    parser.add_argument("--density", type=float, default=0.05, help="Target graph density (0.0-1.0).")
    parser.add_argument("--max_degree", type=int, default=None, help="Attempt to limit the maximum degree of any person.")
    parser.add_argument("--hub_bias", type=float, default=0.0, help="Probability (0.0-1.0) for 'ar' to connect to a designated hub node.")
    parser.add_argument("--num_hubs", type=int, default=5, help="Number of initial person IDs (0 to N-1) to treat as potential hubs.")

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
        hce_max_value = 200

        target_n = args.num_commands
        if args.phases:
            try:
                _, total_phase_commands = parse_phases(args.phases)
                target_n = total_phase_commands
            except ValueError: pass

        if target_n > hce_max_n:
            print(f"  num_commands/phase total capped from {target_n} to {hce_max_n}", file=sys.stderr)
            args.num_commands = hce_max_n
        else:
            args.num_commands = target_n

        if args.max_person_id > hce_max_pid:
            print(f"  max_person_id capped from {args.max_person_id} to {hce_max_pid}", file=sys.stderr)
            args.max_person_id = hce_max_pid
        if args.max_age > hce_max_value: args.max_age = hce_max_value
        if args.max_rel_value > hce_max_value: args.max_rel_value = hce_max_value
        if args.max_mod_value > hce_max_value: args.max_mod_value = hce_max_value

    # --- Validate Phases ---
    phases_config = None
    if args.phases:
        try:
            phases_config, total_phase_commands = parse_phases(args.phases)
            if not args.hce: # Use phase total if not HCE capped
                 args.num_commands = total_phase_commands
            # If HCE, args.num_commands is already capped or equals total_phase_commands
        except ValueError as e:
            print(f"ERROR: Invalid --phases argument: {e}", file=sys.stderr)
            sys.exit(1)

    # Validate hub params
    if args.hub_bias > 0 and args.num_hubs <= 0:
        print("ERROR: --num_hubs must be positive when --hub_bias is used.", file=sys.stderr)
        sys.exit(1)
    if args.num_hubs > args.max_person_id + 1:
        print(f"WARNING: --num_hubs ({args.num_hubs}) > max_person_id+1 ({args.max_person_id+1}). Effective hubs limited.", file=sys.stderr)
        args.num_hubs = args.max_person_id + 1


    # --- Prepare Output ---
    output_stream = open(args.output_file, 'w') if args.output_file else sys.stdout

    # --- Generate and Output ---
    try:
        # --- Clear Global State ---
        persons.clear(); relations.clear(); relation_values.clear()
        person_tags.clear(); tag_members.clear(); person_details.clear()
        person_degrees.clear(); person_neighbors.clear() # Clear neighbors too
        official_accounts.clear(); account_details.clear(); account_followers.clear()
        account_articles.clear(); account_contributions.clear(); all_articles.clear()
        article_contributors.clear(); article_locations.clear(); person_received_articles.clear()

        # Generate commands using the potentially capped args.num_commands
        all_commands, final_cmd_counts = generate_commands(
            args.num_commands, args.max_person_id, args.max_tag_id,
            args.max_account_id, args.max_article_id,
            args.max_rel_value, args.max_mod_value, args.max_age,
            # Min query counts
            args.min_qci, args.min_qts, args.min_qtav, args.min_qba,
            args.min_qcs, args.min_qsp, args.min_qtvs, args.min_qbc, args.min_qra,
            # Control params (pass density, ignore degree_focus)
            args.density, None, args.max_degree,
            args.tag_focus, args.account_focus, args.max_tag_size, args.qci_focus,
            args.mr_delete_ratio, args.exception_ratio,
            args.force_qba_empty_ratio, args.force_qtav_empty_ratio,
            args.hub_bias, args.num_hubs,
            phases_config,
            args.hce
        )

        # Print all generated commands
        for command in all_commands:
             output_stream.write(command.strip() + '\n')

        # Print summary to stderr
        final_command_count = len(all_commands)
        print(f"\n--- Generation Summary ---", file=sys.stderr)
        print(f"Target commands (effective): {args.num_commands}", file=sys.stderr)
        print(f"Actual commands generated: {final_command_count}", file=sys.stderr)
        print(f"Final State: {len(persons)} persons, {len(relations)} relations.", file=sys.stderr)
        total_tags = sum(len(tags) for tags in person_tags.values())
        total_tag_members = sum(len(mems) for mems in tag_members.values())
        print(f"           {total_tags} tags defined, {total_tag_members} total tag memberships.", file=sys.stderr)
        total_accounts = len(official_accounts)
        total_articles_global = len(all_articles)
        total_articles_in_accounts = sum(len(arts) for arts in account_articles.values())
        total_followers = sum(len(fols) for fols in account_followers.values())
        print(f"           {total_accounts} accounts, {total_articles_global} global articles ({total_articles_in_accounts} in accounts), {total_followers} total followings.", file=sys.stderr)

        print(f"Command Counts (incl. supplementary):", file=sys.stderr)
        for cmd_type, count in sorted(final_cmd_counts.items()):
            print(f"  {cmd_type}: {count}", file=sys.stderr)

        if args.output_file:
             print(f"Output written to: {args.output_file}", file=sys.stderr)
        else:
             print(f"Output printed to stdout.", file=sys.stderr)

    finally:
        if args.output_file and output_stream is not sys.stdout:
            output_stream.close()

# --- END OF OPTIMIZED FILE gen.py ---