# --- START OF UPDATED FILE gen.py ---

import random
import argparse
import os
import sys
import math
from contextlib import redirect_stdout
from collections import defaultdict, deque # deque for BFS in qsp exception check
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


# --- Helper Functions (Existing + HW10 additions) ---

def generate_name(base_id, prefix="Name"):
    """Generates a name (for Person or Account) ensuring length <= 100."""
    base_name = f"{prefix}_{base_id}"
    if len(base_name) > 100:
        return f"{prefix[0]}_{base_id}"[:100]
    return base_name

# --- Person Helpers (Mostly unchanged) ---
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

def get_existing_person_id():
    return get_random_person()

def get_non_existent_person_id(max_person_id):
    if not persons: return random.randint(0, max_person_id)
    attempts = 0
    max_attempts = max(len(persons) * 2, 20) # Avoid infinite loop if dense
    max_possible_id = max(list(persons)) if persons else -1
    search_range_max = max(max_person_id + 10, max_possible_id + 10)

    while attempts < max_attempts:
        # Focus search around existing IDs and the max limit
        if random.random() < 0.7 and max_possible_id >=0 :
            pid = random.randint(max(0, max_possible_id - 5), max_possible_id + 10)
        else:
            pid = random.randint(0, search_range_max)

        if pid >= 0 and pid not in persons:
            return pid
        attempts += 1
    # Fallback if search fails (e.g., graph is full up to max_person_id)
    return max(max_person_id, max_possible_id) + 1


def get_two_random_persons(id_limit=None, require_different=True):
    eligible = get_eligible_persons(id_limit)
    if len(eligible) < (2 if require_different else 1):
        return None, None
    eligible_list = sorted(list(eligible))
    p1 = random.choice(eligible_list)
    if not require_different:
        p2 = random.choice(eligible_list)
        return p1, p2
    eligible_list_copy = eligible_list[:]
    eligible_list_copy.remove(p1)
    if not eligible_list_copy: return p1, None
    p2 = random.choice(eligible_list_copy)
    return p1, p2

# --- Relation Helpers (Unchanged) ---
def get_eligible_relations(id_limit=None):
    eligible = relations.copy()
    if id_limit is not None:
        eligible = {(p1, p2) for p1, p2 in eligible if p1 < id_limit and p2 < id_limit}
    return eligible

def get_random_relation(id_limit=None):
    eligible = get_eligible_relations(id_limit)
    return random.choice(sorted(list(eligible))) if eligible else (None, None)

def get_existing_relation():
    return get_random_relation()

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
    return get_two_random_persons() # Fallback

# --- Path/Circle Helpers (For qsp, qci exception check) ---
def check_path_exists(start_node, end_node):
    """ Simple BFS to check reachability (for PNF / qci check) """
    if start_node == end_node: return True
    if start_node not in persons or end_node not in persons: return False

    q = deque([start_node])
    visited = {start_node}
    while q:
        curr = q.popleft()
        if curr == end_node:
            return True
        # Find neighbors
        neighbors = set()
        for p1, p2 in relations:
            if p1 == curr and p2 in persons: neighbors.add(p2)
            elif p2 == curr and p1 in persons: neighbors.add(p1)

        for neighbor in neighbors:
            if neighbor not in visited:
                visited.add(neighbor)
                q.append(neighbor)
    return False

def get_pair_with_path():
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
     if len(persons) < 2: return None, None
     attempts = 0
     max_attempts = len(persons) * 5
     while attempts < max_attempts:
         p1, p2 = get_two_random_persons()
         if p1 is not None and p2 is not None and not check_path_exists(p1, p2):
             return p1, p2
         attempts += 1
     # Fallback: difficult in dense graphs, maybe return non-existent relation?
     # Or just return any random pair hoping they are disconnected.
     p1, p2 = get_non_existent_relation_pair()
     if p1 is not None and p2 is not None and not check_path_exists(p1, p2):
         return p1, p2
     return get_two_random_persons() # Final fallback

# --- Tag Helpers (Unchanged) ---
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
    owner_id, tag_id = random.choice(sorted(owners_with_tags))
    return owner_id, tag_id

def get_non_existent_tag_id(person_id, max_tag_id):
     if person_id not in persons: return random.randint(0, max_tag_id)
     existing_tags = person_tags.get(person_id, set())
     if len(existing_tags) > max_tag_id + 1 : return max_tag_id + random.randint(1,5) # Already full
     attempts = 0
     max_attempts = max(len(existing_tags) * 2, 20)
     search_range_max = max_tag_id + 10
     while attempts < max_attempts:
          tag_id = random.randint(0, search_range_max)
          if tag_id not in existing_tags:
               return tag_id
          attempts += 1
     return max_tag_id + random.randint(1,5) # Fallback

def get_random_member_in_tag(owner_id, tag_id):
    tag_key = (owner_id, tag_id)
    members = tag_members.get(tag_key, set())
    return random.choice(sorted(list(members))) if members else None

def get_related_person_not_in_tag(owner_id, tag_id):
    if owner_id is None or tag_id is None: return None
    related_persons = set()
    for r_p1, r_p2 in relations:
        if r_p1 == owner_id and r_p2 in persons : related_persons.add(r_p2)
        if r_p2 == owner_id and r_p1 in persons : related_persons.add(r_p1)
    tag_key = (owner_id, tag_id)
    current_members = tag_members.get(tag_key, set())
    possible_members = sorted(list(related_persons - {owner_id} - current_members))
    return random.choice(possible_members) if possible_members else None

def get_person_not_in_tag(owner_id, tag_id):
    tag_key = (owner_id, tag_id)
    current_members = tag_members.get(tag_key, set())
    non_members = sorted(list(persons - current_members - {owner_id}))
    return random.choice(non_members) if non_members else None

def get_random_empty_tag():
    empty_tags = []
    all_tag_keys = list(tag_members.keys()) # Get all defined tag keys
    for (owner_id, tag_id) in all_tag_keys:
         members = tag_members.get((owner_id, tag_id), set())
         # Check if owner and tag still technically exist
         if owner_id in persons and tag_id in person_tags.get(owner_id, set()):
             if not members:
                 empty_tags.append((owner_id, tag_id))
    return random.choice(sorted(empty_tags)) if empty_tags else (None, None)

def get_person_with_no_acquaintances():
     zero_degree_persons = [pid for pid in persons if person_degrees.get(pid, 0) == 0]
     return random.choice(sorted(zero_degree_persons)) if zero_degree_persons else None

# --- HW10 Account/Article Helpers ---
def get_random_account_id():
    return random.choice(sorted(list(official_accounts))) if official_accounts else None

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
    return random.choice(sorted(list(followers))) if followers else None

def get_person_not_following(account_id):
    if account_id not in official_accounts: return get_existing_person_id() # Or None?
    followers = account_followers.get(account_id, set())
    non_followers = sorted(list(persons - followers))
    return random.choice(non_followers) if non_followers else None

def get_random_account_with_followers():
     accounts_with_followers = [acc_id for acc_id in official_accounts if account_followers.get(acc_id)]
     return random.choice(sorted(accounts_with_followers)) if accounts_with_followers else None

def get_random_account_and_follower():
    acc_id = get_random_account_with_followers()
    if acc_id:
        follower_id = get_random_follower(acc_id)
        return acc_id, follower_id
    return None, None

def get_random_article_id():
    return random.choice(sorted(list(all_articles))) if all_articles else None

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
    return random.choice(sorted(list(articles_in_acc))) if articles_in_acc else None

def get_random_account_with_articles():
    acc_with_articles = [acc_id for acc_id, arts in account_articles.items() if arts]
    return random.choice(sorted(acc_with_articles)) if acc_with_articles else None

def get_random_account_and_article():
    acc_id = get_random_account_with_articles()
    if acc_id:
        article_id = get_random_article_in_account(acc_id)
        return acc_id, article_id
    return None, None

def get_contributor_of_article(article_id):
     return article_contributors.get(article_id)

def get_account_of_article(article_id):
    # Returns the *current* account it's in, or None if orphaned/deleted
    return article_locations.get(article_id)


# --- State Update Functions (Existing + HW10 additions) ---

# --- Person/Relation/Tag State (Mostly Unchanged, ensure MR tag removal is kept) ---
def add_person_state(person_id, name, age):
    if person_id not in persons:
        persons.add(person_id)
        person_details[person_id] = {'name': name, 'age': age}
        person_degrees[person_id] = 0
        person_received_articles[person_id] = [] # Initialize received articles list
        return True
    return False

def add_relation_state(id1, id2, value, max_degree=None):
    if id1 == id2 or (min(id1, id2), max(id1, id2)) in relations:
         return False
    if max_degree is not None:
        if person_degrees.get(id1, 0) >= max_degree or person_degrees.get(id2, 0) >= max_degree:
            return False
    p1, p2 = min(id1, id2), max(id1, id2)
    rel_key = (p1, p2)
    relations.add(rel_key)
    relation_values[rel_key] = value
    person_degrees[p1] = person_degrees.get(p1, 0) + 1
    person_degrees[p2] = person_degrees.get(p2, 0) + 1
    return True

def remove_relation_state(id1, id2):
    # This function ALREADY correctly handles removing people from each other's tags
    # based on HW9 requirements, which matches the MR JML postcondition.
    if id1 == id2: return False
    p1_orig, p2_orig = id1, id2
    p1, p2 = min(id1, id2), max(id1, id2)
    rel_key = (p1, p2)
    if rel_key in relations:
        relations.remove(rel_key)
        if rel_key in relation_values: del relation_values[rel_key]
        if p1 in person_degrees: person_degrees[p1] -= 1
        if p2 in person_degrees: person_degrees[p2] -= 1

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
        tag_members[(person_id, tag_id)] = tag_members.get((person_id, tag_id), set())
        return True
    return False

def remove_tag_state(person_id, tag_id):
    if person_id not in persons: return False
    if tag_id in person_tags[person_id]:
        person_tags[person_id].remove(tag_id)
        tag_key = (person_id, tag_id)
        if tag_key in tag_members:
            del tag_members[tag_key] # Remove members list as well
        # JML doesn't specify cleaning tag_members if person_tags entry is gone,
        # but it makes sense for state consistency.
        # Check if other code relies on tag_members existing even if tag is gone? Unlikely.
        return True
    return False

def add_person_to_tag_state(person_id1, person_id2, tag_id, max_tag_size):
    tag_key = (person_id2, tag_id)
    p1_rel_p2_key = (min(person_id1, person_id2), max(person_id1, person_id2))

    # Preconditions (Match JML)
    if not (person_id1 in persons and person_id2 in persons): return False # PINF
    if person_id1 == person_id2: return False # EPI (p1==p2)
    if p1_rel_p2_key not in relations: return False # RNF
    if tag_id not in person_tags.get(person_id2, set()): return False # TINF
    if person_id1 in tag_members.get(tag_key, set()): return False # EPI (already in tag)

    # Size check (JML limit 1000, user limit max_tag_size)
    current_size = len(tag_members.get(tag_key, set()))
    effective_max_size = 1000 # JML limit is <= 999 means max size is 1000
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
    return False # Should not happen if checks pass


# --- HW10 State Updates ---
def create_official_account_state(person_id, account_id, name):
    # Preconditions
    if person_id not in persons: return False # PINF
    if account_id in official_accounts: return False # EOAI

    # Add account
    official_accounts.add(account_id)
    account_details[account_id] = {'owner': person_id, 'name': name}
    # Owner automatically follows with 0 contribution initially
    account_followers[account_id] = {person_id}
    account_contributions[account_id] = defaultdict(int)
    account_contributions[account_id][person_id] = 0
    account_articles[account_id] = set() # Initialize articles set
    return True

def delete_official_account_state(person_id, account_id):
    # Preconditions
    if person_id not in persons: return False # PINF
    if account_id not in official_accounts: return False # OAINF
    if account_details.get(account_id, {}).get('owner') != person_id: return False # DOAPD

    # Remove account and associated info
    official_accounts.remove(account_id)
    if account_id in account_details: del account_details[account_id]
    if account_id in account_followers: del account_followers[account_id]
    if account_id in account_contributions: del account_contributions[account_id]
    # Remove articles *from this account's list*. Global article state is not specified
    # in JML postcondition for DOA, so we only update the account's state.
    # We might need to orphan articles in article_locations.
    articles_to_orphan = account_articles.get(account_id, set())
    for art_id in articles_to_orphan:
         if art_id in article_locations and article_locations[art_id] == account_id:
              # Mark as orphaned (no longer in a valid account)
              # Or simply delete? Let's just delete the location link.
              del article_locations[art_id]
              # Should we remove from all_articles? JML doesn't say. Let's keep it in all_articles
              # but without a location. Maybe deleteArticle is the only way to remove globally?

    if account_id in account_articles: del account_articles[account_id]

    return True

def contribute_article_state(person_id, account_id, article_id):
    # Preconditions
    if person_id not in persons: return False # PINF
    if account_id not in official_accounts: return False # OAINF
    if article_id in all_articles: return False # EAI
    if person_id not in account_followers.get(account_id, set()): return False # CPD

    # Add article
    all_articles.add(article_id)
    article_contributors[article_id] = person_id
    article_locations[article_id] = account_id
    account_articles[account_id].add(article_id)

    # Increment contribution count
    account_contributions[account_id][person_id] = account_contributions[account_id].get(person_id, 0) + 1

    # Add to received articles for *all* followers (at the beginning - index 0)
    current_followers = account_followers.get(account_id, set())
    for follower_id in current_followers:
        if follower_id in person_received_articles:
            person_received_articles[follower_id].insert(0, article_id)
        else: # Should not happen if follower is in persons, but safety
             person_received_articles[follower_id] = [article_id]

    return True

def delete_article_state(person_id, account_id, article_id):
    # Preconditions
    if person_id not in persons: return False # PINF
    if account_id not in official_accounts: return False # OAINF
    if article_id not in account_articles.get(account_id, set()): return False # AINF (article not in account)
    if account_details.get(account_id, {}).get('owner') != person_id: return False # DAPD

    # Remove article from account
    if account_id in account_articles:
        account_articles[account_id].discard(article_id) # Use discard to avoid error if somehow missing

    # Remove from article location tracking
    if article_id in article_locations and article_locations[article_id] == account_id:
         del article_locations[article_id]

    # Decrement contribution count (find original contributor)
    original_contributor = article_contributors.get(article_id)
    if original_contributor is not None and account_id in account_contributions:
        if original_contributor in account_contributions[account_id]:
            account_contributions[account_id][original_contributor] -= 1
            # We don't remove the contributor key even if count is 0, JML doesn't specify

    # Remove from received articles for all current followers
    current_followers = account_followers.get(account_id, set())
    for follower_id in current_followers:
        if follower_id in person_received_articles:
             # Need to handle potential duplicates? JML doesn't specify, assume unique add
             if article_id in person_received_articles[follower_id]:
                  person_received_articles[follower_id].remove(article_id)

    # Does it remove from all_articles? JML assignable doesn't include global 'articles'.
    # Let's assume deleteArticle only removes it *from the account*.
    # all_articles.discard(article_id) # <-- Probably should NOT do this based on JML

    return True


def follow_official_account_state(person_id, account_id):
    # Preconditions
    if person_id not in persons: return False # PINF
    if account_id not in official_accounts: return False # OAINF
    if person_id in account_followers.get(account_id, set()): return False # EPI (already following)

    # Add follower
    account_followers[account_id].add(person_id)
    # Initialize contribution count
    if account_id not in account_contributions: # Should exist if account exists, but safety
        account_contributions[account_id] = defaultdict(int)
    account_contributions[account_id][person_id] = 0 # JML: ensures contributions[i] == 0

    return True


# --- Command Weights Setup (Added HW10 commands) ---
def get_command_weights(phase="default", tag_focus=0.3, account_focus=0.3):
    # Base weights - Include new commands
    base_weights = {
        "ap": 10, "ar": 8, "mr": 4, "at": 6, "dt": 2,
        "att": 6, "dft": 3,
        "coa": 5, "doa": 1, "ca": 5, "da": 1, "foa": 6, # HW10 Add/Delete
        "qv": 10, "qci": 10, "qts": 4, "qtav": 8, "qba": 6, "qcs": 3, "qsp": 8, "qtvs": 8, # HW9 Queries + qsp/qcs/qtvs
        "qbc": 5, "qra": 8 # HW10 Queries
    }

    phase_weights = {
        "build": {**base_weights, "ap": 20, "ar": 15, "coa": 10, "foa": 8, "ca": 5, "at": 8, "att": 6,
                   "mr": 1, "dt": 1, "dft": 1, "doa": 0, "da": 0,
                   "qv": 3, "qci": 3, "qts": 1, "qtav": 2, "qba": 2, "qcs": 1, "qsp": 2, "qtvs": 2, "qbc": 1, "qra": 2},
        "query": {**base_weights, "ap": 1, "ar": 1, "mr": 1, "at":1, "dt": 1, "att": 1, "dft": 1,
                  "coa": 1, "doa": 1, "ca": 1, "da": 1, "foa": 1,
                   "qv": 15, "qci": 15, "qts": 8, "qtav": 12, "qba": 12, "qcs": 8, "qsp": 15, "qtvs": 12, "qbc": 10, "qra": 15},
        "modify":{**base_weights, "ap": 2, "ar": 3, "mr": 15, "at": 8, "dt": 8, "att": 12, "dft": 8,
                   "coa": 3, "doa": 5, "ca": 4, "da": 5, "foa": 5, # Moderate account mods
                   "qv": 5, "qci": 5, "qts": 2, "qtav": 5, "qba": 4, "qcs": 2, "qsp": 5, "qtvs": 5, "qbc": 3, "qra": 5},
        "churn": {**base_weights, "ap": 5, "ar": 10, "mr": 20, "at": 8, "dt": 12, "att": 8, "dft": 12,
                  "coa": 4, "doa": 15, "ca": 5, "da": 15, "foa": 6, # High account churn
                  "qv": 3, "qci": 3, "qts": 1, "qtav": 3, "qba": 2, "qcs": 1, "qsp": 3, "qtvs": 3, "qbc": 2, "qra": 3},
        "default": base_weights,

        # Existing custom phases (ensure new commands get some weight)
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
    }
    current_weights = phase_weights.get(phase, phase_weights['default']).copy()

    # Adjust for tag_focus (existing logic)
    tag_cmds = {"at", "dt", "att", "dft", "qtav", "qtvs"} # Added qtvs
    total_weight = sum(current_weights.values())
    if total_weight > 0 and tag_focus is not None:
        # ... (rest of tag_focus logic remains the same) ...
        current_tag_weight = sum(w for cmd, w in current_weights.items() if cmd in tag_cmds)
        current_tag_ratio = current_tag_weight / total_weight if total_weight else 0
        non_tag_denominator = (1 - current_tag_ratio)
        if non_tag_denominator <= 0: non_tag_denominator = 1

        # Avoid excessive scaling if focus is already close
        if abs(current_tag_ratio - tag_focus) > 0.05:
            scale_factor = (tag_focus / current_tag_ratio) if current_tag_ratio > 0 else 1.5
            non_tag_scale = (1 - tag_focus) / non_tag_denominator

            for cmd in list(current_weights.keys()):
                if cmd in tag_cmds:
                    current_weights[cmd] = max(1, int(current_weights[cmd] * scale_factor))
                else:
                    current_weights[cmd] = max(1, int(current_weights[cmd] * non_tag_scale))
            total_weight = sum(current_weights.values()) # Recalculate total weight

    # Adjust for account_focus (new logic)
    account_cmds = {"coa", "doa", "ca", "da", "foa", "qbc", "qra"}
    if total_weight > 0 and account_focus is not None:
        current_account_weight = sum(w for cmd, w in current_weights.items() if cmd in account_cmds)
        current_account_ratio = current_account_weight / total_weight if total_weight else 0
        non_account_denominator = (1 - current_account_ratio)
        if non_account_denominator <= 0: non_account_denominator = 1

        if abs(current_account_ratio - account_focus) > 0.05:
            acc_scale_factor = (account_focus / current_account_ratio) if current_account_ratio > 0 else 1.5
            non_acc_scale = (1 - account_focus) / non_account_denominator

            for cmd in list(current_weights.keys()):
                if cmd in account_cmds:
                    current_weights[cmd] = max(1, int(current_weights[cmd] * acc_scale_factor))
                else: # Scale non-account commands
                    current_weights[cmd] = max(1, int(current_weights[cmd] * non_acc_scale))

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


# --- Exception Generation Logic (Added HW10 commands) ---
def try_generate_exception_command(cmd_type, max_person_id, max_tag_id, max_account_id, max_article_id):
    """Attempts to generate parameters for cmd_type that cause a known exception."""
    cmd = None
    target_exception = None # For debugging/info

    try:
        # --- HW9 Exceptions (Mostly Unchanged, added PNF check for qsp) ---
        if cmd_type == "ap": # Target: EqualPersonIdException (EPI)
            p_id = get_existing_person_id()
            if p_id is not None:
                name = generate_name(p_id)
                age = random.randint(1, 100)
                cmd = f"ap {p_id} {name} {age}"
                target_exception = "EqualPersonIdException (ap)"

        elif cmd_type == "ar": # Target: EqualRelationException (ER) or PersonIdNotFoundException (PINF)
            if random.random() < 0.6 and relations: # Prioritize ER
                p1, p2 = get_existing_relation()
                if p1 is not None:
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

        elif cmd_type == "mr": # Target: PINF, EPI, RelationNotFoundException (RNF)
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
                p1, p2 = get_non_existent_relation_pair()
                if p1 is not None and p2 is not None:
                    m_val = random.randint(-50, 50)
                    cmd = f"mr {p1} {p2} {m_val}"
                    target_exception = "RelationNotFoundException (mr)"

        elif cmd_type == "at": # Target: PINF, EqualTagIdException (ETI)
            if random.random() < 0.5: # Target PINF
                p_id = get_non_existent_person_id(max_person_id)
                tag_id = random.randint(0, max_tag_id)
                if p_id is not None:
                     cmd = f"at {p_id} {tag_id}"
                     target_exception = "PersonIdNotFoundException (at)"
            else: # Target ETI
                owner_id, tag_id = get_random_tag_owner_and_tag()
                if owner_id is not None:
                    cmd = f"at {owner_id} {tag_id}"
                    target_exception = "EqualTagIdException"

        elif cmd_type == "dt": # Target: PINF, TagIdNotFoundException (TINF)
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
                if p1 is not None and p2 is not None:
                     cmd = f"att {p1} {p2} {tag_id}"
                     target_exception = "PersonIdNotFoundException (att p1)"
            elif choice < 0.4: # PINF (p2)
                 p1 = get_existing_person_id()
                 p2 = get_non_existent_person_id(max_person_id)
                 tag_id = random.randint(0, max_tag_id)
                 if p1 is not None and p2 is not None:
                      cmd = f"att {p1} {p2} {tag_id}"
                      target_exception = "PersonIdNotFoundException (att p2)"
            elif choice < 0.5: # EPI (p1 == p2)
                 p1 = get_existing_person_id()
                 tag_id = random.randint(0, max_tag_id)
                 if p1 is not None:
                      cmd = f"att {p1} {p1} {tag_id}"
                      target_exception = "EqualPersonIdException (att p1==p2)"
            elif choice < 0.65: # RNF
                p1, p2 = get_non_existent_relation_pair()
                owner_id, tag_id = get_random_tag_owner_and_tag() # Need an existing tag on *someone*
                if p1 is not None and p2 is not None and owner_id is not None:
                    # Try to use p2 as the tag owner to make RNF more likely
                    if p2 in person_tags and person_tags[p2]:
                        tag_id_for_p2 = random.choice(list(person_tags[p2]))
                        cmd = f"att {p1} {p2} {tag_id_for_p2}"
                        target_exception = "RelationNotFoundException (att)"
                    else: # Fallback: use a random owner/tag
                        cmd = f"att {p1} {owner_id} {tag_id}" # p1 adding to owner_id's tag
                        target_exception = "RelationNotFoundException (att fallback)"

            elif choice < 0.8: # TINF
                 p1, p2 = get_existing_relation() # p1 adds to p2's tag
                 if p1 is not None:
                      tag_id = get_non_existent_tag_id(p2, max_tag_id)
                      cmd = f"att {p1} {p2} {tag_id}"
                      target_exception = "TagIdNotFoundException (att)"
            else: # EPI (already in tag)
                owner_id, tag_id = get_random_tag_owner_and_tag(require_non_empty=True)
                if owner_id is not None:
                    member_id = get_random_member_in_tag(owner_id, tag_id)
                    if member_id is not None:
                        cmd = f"att {member_id} {owner_id} {tag_id}"
                        target_exception = "EqualPersonIdException (att already in tag)"

        elif cmd_type == "dft": # Target: PINF(p1), PINF(p2), TINF, PINF(p1 not in tag)
            choice = random.random()
            if choice < 0.2: # PINF (p1)
                p1 = get_non_existent_person_id(max_person_id)
                p2, tag_id = get_random_tag_owner_and_tag()
                if p1 is not None and p2 is not None:
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
                # Pick any person for p1, it doesn't matter for TINF
                p1 = get_existing_person_id()
                if owner_id is not None and p1 is not None:
                    tag_id = get_non_existent_tag_id(owner_id, max_tag_id)
                    cmd = f"dft {p1} {owner_id} {tag_id}"
                    target_exception = "TagIdNotFoundException (dft)"
            else: # PINF (p1 not in tag)
                owner_id, tag_id = get_random_tag_owner_and_tag() # Find any tag
                if owner_id is not None:
                    # Find someone NOT in the tag
                    p1 = get_person_not_in_tag(owner_id, tag_id)
                    if p1 is not None:
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
                 p1, p2 = get_non_existent_relation_pair()
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
            # NOTE: qci itself doesn't throw PNF, it returns false if no path

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

        elif cmd_type == "qba": # Target: PINF, AcquaintanceNotFoundException (ANF)
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

        elif cmd_type == "qsp": # Target: PINF, PathNotFoundException (PNF)
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
                 p1, p2 = get_pair_without_path()
                 if p1 is not None and p2 is not None:
                      cmd = f"qsp {p1} {p2}"
                      target_exception = "PathNotFoundException"

        # --- HW10 Exceptions ---
        elif cmd_type == "coa": # Target: PINF, EqualOfficialAccountIdException (EOAI)
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

        elif cmd_type == "doa": # Target: PINF, OfficialAccountIdNotFoundException (OAINF), DeleteOfficialAccountPermissionDeniedException (DOAPD)
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
                      # Find someone who is NOT the owner
                      non_owner_id = None
                      eligible_non_owners = sorted(list(persons - {owner_id}))
                      if eligible_non_owners:
                          non_owner_id = random.choice(eligible_non_owners)

                      if non_owner_id is not None:
                           cmd = f"doa {non_owner_id} {acc_id}"
                           target_exception = "DeleteOfficialAccountPermissionDeniedException"

        elif cmd_type == "ca": # Target: PINF, OAINF, EqualArticleIdException (EAI), ContributePermissionDeniedException (CPD)
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
                       if p_id not in account_followers.get(acc_id, set()):
                           follow_official_account_state(p_id, acc_id) # Force follow if needed
                       if p_id in account_followers.get(acc_id, set()):
                           cmd = f"ca {p_id} {acc_id} {art_id}"
                           target_exception = "EqualArticleIdException"
             else: # CPD
                  acc_id = get_random_account_id()
                  art_id = get_non_existent_article_id(max_article_id)
                  if acc_id is not None:
                      p_id = get_person_not_following(acc_id) # Find non-follower
                      if p_id is not None:
                           cmd = f"ca {p_id} {acc_id} {art_id}"
                           target_exception = "ContributePermissionDeniedException"

        elif cmd_type == "da": # Target: PINF, OAINF, ArticleIdNotFoundException (AINF), DeleteArticlePermissionDeniedException (DAPD)
             choice = random.random()
             if choice < 0.2: # PINF
                 p_id = get_non_existent_person_id(max_person_id)
                 acc_id, art_id = get_random_account_and_article()
                 if p_id is not None and acc_id is not None:
                      cmd = f"da {p_id} {acc_id} {art_id}"
                      target_exception = "PersonIdNotFoundException (da)"
             elif choice < 0.4: # OAINF
                  p_id = get_existing_person_id() # Needs to be owner
                  acc_id = get_non_existent_account_id(max_account_id)
                  art_id = get_random_article_id() # Doesn't matter which article
                  if p_id is not None and acc_id is not None and art_id is not None:
                       cmd = f"da {p_id} {acc_id} {art_id}"
                       target_exception = "OfficialAccountIdNotFoundException (da)"
             elif choice < 0.6: # AINF
                  acc_id = get_random_account_id()
                  if acc_id is not None:
                      owner_id = get_account_owner(acc_id)
                      # Find an article NOT in this account
                      articles_in_acc = account_articles.get(acc_id, set())
                      other_articles = sorted(list(all_articles - articles_in_acc))
                      art_id = random.choice(other_articles) if other_articles else get_non_existent_article_id(max_article_id)

                      if owner_id is not None: # Ensure owner exists
                          cmd = f"da {owner_id} {acc_id} {art_id}"
                          target_exception = "ArticleIdNotFoundException"
             else: # DAPD
                  acc_id, art_id = get_random_account_and_article()
                  if acc_id is not None and art_id is not None:
                      owner_id = get_account_owner(acc_id)
                      # Find someone who is NOT the owner
                      non_owner_id = None
                      eligible_non_owners = sorted(list(persons - {owner_id}))
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


# --- Main Generation Logic (Integrates HW10) ---
def generate_commands(num_commands_target, max_person_id, max_tag_id, max_account_id, max_article_id,
                      max_rel_value, max_mod_value, max_age,
                      min_qci, min_qts, min_qtav, min_qba, min_qcs, min_qsp, min_qtvs, min_qbc, min_qra, # Min query counts
                      density, degree_focus, max_degree, tag_focus, account_focus, max_tag_size, qci_focus,
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

    # --- Initial Population (Unchanged) ---
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
    hub_ids = set(range(num_hubs)) if num_hubs > 0 else set()

    # --- Main Generation Loop ---
    while len(generated_cmds_list) < num_commands_to_generate:
        # Determine current phase and get weights
        current_phase_name = "default"
        if phases_config:
            if current_phase_index >= len(phases_config): break # Completed phases
            current_phase_info = phases_config[current_phase_index]
            current_phase_name = current_phase_info['name']
            if commands_in_current_phase >= current_phase_info['count']:
                current_phase_index += 1
                commands_in_current_phase = 0
                if current_phase_index >= len(phases_config): break # Completed phases
                current_phase_info = phases_config[current_phase_index]
                current_phase_name = current_phase_info['name']

        weights_dict = get_command_weights(current_phase_name, tag_focus, account_focus)

        # --- Filter out impossible commands based on state ---
        if len(persons) < 1:
            weights_dict = {'ap': 1}
        else:
            if len(persons) < 2:
                weights_dict.pop("ar", None); weights_dict.pop("mr", None); weights_dict.pop("qv", None)
                weights_dict.pop("qci", None); weights_dict.pop("att", None); weights_dict.pop("dft", None)
                weights_dict.pop("qsp", None) # Requires 2 potentially different people
            if not relations:
                weights_dict.pop("mr", None); weights_dict.pop("att", None) # RNF impossible
                # qv, qci, qsp might still query non-existent/unreachable
            if not any(person_tags.values()):
                weights_dict.pop("dt", None); weights_dict.pop("qtav", None); weights_dict.pop("qtvs", None)
                weights_dict.pop("att", None); weights_dict.pop("dft", None) # TINF impossible
            if not any(tag_members.values()):
                weights_dict.pop("dft", None) # PINF (not in tag) impossible
            # HW10 Filters
            if not official_accounts:
                weights_dict.pop("doa", None); weights_dict.pop("ca", None); weights_dict.pop("da", None)
                weights_dict.pop("foa", None); weights_dict.pop("qbc", None)
            if not any(account_followers.values()):
                 weights_dict.pop("ca", None) # Need followers to contribute
                 weights_dict.pop("qbc", None) # Need followers for best contributor
            if not all_articles or not any(account_articles.values()):
                 weights_dict.pop("da", None) # Need articles in accounts to delete
            if not any(person_received_articles.values()):
                 pass # qra can still be called, returns empty list

        if not weights_dict:
             print("Warning: No commands possible with current state and weights! Trying to add person.", file=sys.stderr)
             person_id = get_non_existent_person_id(max_person_id)
             if person_id <= max_person_id and person_id >= 0:
                 name = generate_name(person_id, "Person")
                 age = random.randint(1, max_age)
                 if add_person_state(person_id, name, age):
                    cmd = f"ap {person_id} {name} {age}"
                    generated_cmds_list.append(cmd)
                    cmd_counts['ap'] += 1
                    if phases_config: commands_in_current_phase += 1
                    continue
             print("ERROR: Could not add fallback person. Breaking loop.", file=sys.stderr)
             break

        # --- Choose Command Type ---
        command_types = sorted(list(weights_dict.keys()))
        weights = [weights_dict[cmd_type] for cmd_type in command_types]
        if sum(weights) <= 0:
             print("Warning: Zero total weight for command selection. Trying 'ap'.", file=sys.stderr)
             cmd_type = 'ap'
        else:
             cmd_type = random.choices(command_types, weights=weights, k=1)[0]

        cmd = None
        generated_successfully = False

        # --- Attempt Exception Generation ---
        if random.random() < exception_ratio:
            cmd = try_generate_exception_command(cmd_type, max_person_id, max_tag_id, max_account_id, max_article_id)
            if cmd:
                generated_successfully = True # Count exception commands
            # else: Fallback to normal generation

        # --- Normal Command Generation (or fallback) ---
        if not generated_successfully:
            try:
                # --- Force Edge Cases (Unchanged) ---
                force_qba_empty = (cmd_type == "qba" and random.random() < force_qba_empty_ratio)
                force_qtav_empty = (cmd_type == "qtav" and random.random() < force_qtav_empty_ratio)
                # Could add force_qbc_empty (no contributors) or force_qra_empty later

                # --- Command Generation ---
                if cmd_type == "ap":
                    potential_ids = [i for i in range(max_person_id + 1) if i not in persons]
                    person_id = -1
                    if potential_ids:
                         person_id = random.choice(potential_ids)
                    # Allow generating existing ID only if no potential IDs left or low probability
                    elif not potential_ids or random.random() < 0.05:
                         person_id = random.randint(0, max_person_id)
                    # If still -1 (shouldn't happen often), try non-existent logic
                    if person_id == -1 or person_id in persons:
                         person_id = get_non_existent_person_id(max_person_id)

                    if person_id >= 0 and person_id <= max_person_id: # Ensure valid ID range
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
                        hub_id = random.choice(list(hub_ids))
                        eligible_others = sorted(list(get_eligible_persons() - {hub_id}))
                        if eligible_others:
                            other_p = random.choice(eligible_others)
                            p1, p2 = hub_id, other_p # Connect hub to other
                    if p1 is None or p2 is None: # Fallback or no hub bias
                       p1, p2 = get_two_random_persons()

                    if p1 is not None and p2 is not None:
                        current_nodes = len(persons)
                        max_possible_edges = (current_nodes * (current_nodes - 1)) // 2 if current_nodes > 1 else 0
                        current_density = len(relations) / max_possible_edges if max_possible_edges > 0 else 0
                        prob_add = 0.6 + (density - current_density) # Target density
                        prob_add = max(0.05, min(0.95, prob_add))

                        if random.random() < prob_add:
                            value = random.randint(1, max_rel_value)
                            if add_relation_state(p1, p2, value, max_degree):
                                cmd = f"ar {p1} {p2} {value}"
                                generated_successfully = True

                elif cmd_type == "mr":
                    p1, p2 = get_random_relation()
                    if p1 is not None:
                        rel_key = (p1, p2)
                        current_value = relation_values.get(rel_key, 0)
                        m_val = 0
                        if current_value > 0 and random.random() < mr_delete_ratio:
                            m_val = -current_value - random.randint(0, 10) # Target deletion
                        else:
                            effective_max_mod = max(1, max_mod_value)
                            m_val = random.randint(-effective_max_mod, effective_max_mod)
                            if m_val == 0 and max_mod_value != 0:
                                m_val = random.choice([-1, 1]) * random.randint(1, effective_max_mod)

                        if hce_active: # HCE Clamping
                            m_val = max(-200, min(200, m_val))

                        cmd = f"mr {p1} {p2} {m_val}"
                        generated_successfully = True

                        # State update handled AFTER generating command
                        new_value = current_value + m_val
                        if new_value <= 0:
                            remove_relation_state(p1, p2) # This handles degrees AND tag removal
                        else:
                            relation_values[rel_key] = new_value

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
                         # Find related person *not* already in tag
                         person_id1 = get_related_person_not_in_tag(owner_id, tag_id)
                         if person_id1 is not None:
                             if add_person_to_tag_state(person_id1, owner_id, tag_id, max_tag_size):
                                cmd = f"att {person_id1} {owner_id} {tag_id}"
                                generated_successfully = True

                elif cmd_type == "dft":
                     owner_id, tag_id = get_random_tag_owner_and_tag(require_non_empty=True)
                     if owner_id is not None:
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
                    eligible_owners = [p for p in persons if any(a for a in official_accounts if get_account_owner(a) == p)]
                    if eligible_owners:
                         owner_id = random.choice(eligible_owners)
                         accounts_owned = [a for a in official_accounts if get_account_owner(a) == owner_id]
                         if accounts_owned:
                             acc_id = random.choice(accounts_owned)

                    if owner_id is not None and acc_id is not None:
                        if delete_official_account_state(owner_id, acc_id):
                            cmd = f"doa {owner_id} {acc_id}"
                            generated_successfully = True

                elif cmd_type == "ca":
                     acc_id, follower_id = get_random_account_and_follower()
                     if acc_id is not None and follower_id is not None:
                         article_id = get_non_existent_article_id(max_article_id)
                         if article_id >= 0 and article_id <= max_article_id:
                             if contribute_article_state(follower_id, acc_id, article_id):
                                  cmd = f"ca {follower_id} {acc_id} {article_id}"
                                  generated_successfully = True

                elif cmd_type == "da":
                     acc_id, art_id = get_random_account_and_article()
                     if acc_id is not None and art_id is not None:
                         owner_id = get_account_owner(acc_id)
                         if owner_id is not None and owner_id in persons: # Ensure owner exists
                              if delete_article_state(owner_id, acc_id, art_id):
                                   cmd = f"da {owner_id} {acc_id} {art_id}"
                                   generated_successfully = True

                elif cmd_type == "foa":
                     acc_id = get_random_account_id()
                     if acc_id is not None:
                         person_id = get_person_not_following(acc_id)
                         if person_id is not None:
                              if follow_official_account_state(person_id, acc_id):
                                   cmd = f"foa {person_id} {acc_id}"
                                   generated_successfully = True

                # --- Query Commands (Existing + HW10) ---
                elif cmd_type == "qv":
                    if random.random() < 0.9 and relations: p1, p2 = get_random_relation()
                    else: p1, p2 = get_two_random_persons()
                    if p1 is not None and p2 is not None:
                        cmd = f"qv {p1} {p2}"
                        generated_successfully = True

                elif cmd_type == "qci":
                     p1, p2 = None, None
                     if qci_focus == 'close' and relations: p1, p2 = get_random_relation()
                     elif qci_focus == 'far': p1, p2 = get_non_existent_relation_pair() # Simplification
                     else: p1, p2 = get_two_random_persons()
                     if p1 is not None and p2 is not None:
                          cmd = f"qci {p1} {p2}"
                          generated_successfully = True

                elif cmd_type == "qts":
                     cmd = "qts"
                     generated_successfully = True

                elif cmd_type == "qtav": # Query Tag Age Variance
                    owner_id, tag_id = None, None
                    if force_qtav_empty: owner_id, tag_id = get_random_empty_tag()
                    if owner_id is None:
                        if random.random() < 0.15 or not any(person_tags.values()):
                             owner_id = get_random_person()
                             tag_id = random.randint(0, max_tag_id)
                        else:
                             owner_id, tag_id = get_random_tag_owner_and_tag()
                             if owner_id is not None and random.random() < 0.05:
                                  tag_id = get_non_existent_tag_id(owner_id, max_tag_id)
                    if owner_id is not None and tag_id is not None:
                        cmd = f"qtav {owner_id} {tag_id}"
                        generated_successfully = True

                elif cmd_type == "qtvs": # Query Tag Value Sum (New Command Name)
                    # Logic is similar to qtav for picking params
                    owner_id, tag_id = None, None
                    # Maybe add force_qtvs_empty later?
                    if owner_id is None:
                        if random.random() < 0.15 or not any(person_tags.values()):
                             owner_id = get_random_person()
                             tag_id = random.randint(0, max_tag_id)
                        else:
                             owner_id, tag_id = get_random_tag_owner_and_tag()
                             if owner_id is not None and random.random() < 0.05:
                                  tag_id = get_non_existent_tag_id(owner_id, max_tag_id)
                    if owner_id is not None and tag_id is not None:
                        cmd = f"qtvs {owner_id} {tag_id}"
                        generated_successfully = True


                elif cmd_type == "qba": # Query Best Acquaintance
                     person_id = None
                     if force_qba_empty: person_id = get_person_with_no_acquaintances()
                     if person_id is None:
                         person_id = get_random_person(require_degree_greater_than=0 if random.random() < 0.9 else None)
                     if person_id is not None:
                          cmd = f"qba {person_id}"
                          generated_successfully = True

                elif cmd_type == "qcs": # Query Couple Sum
                     cmd = "qcs"
                     generated_successfully = True

                elif cmd_type == "qsp": # Query Shortest Path
                    p1, p2 = None, None
                    # Try to pick pairs with/without path sometimes
                    if random.random() < 0.7: # Usually existing path
                        p1, p2 = get_pair_with_path()
                    else: # Occasionally non-existent path
                        p1, p2 = get_pair_without_path()

                    # Fallback if path finding fails
                    if p1 is None or p2 is None:
                         p1, p2 = get_two_random_persons()

                    if p1 is not None and p2 is not None:
                         cmd = f"qsp {p1} {p2}"
                         generated_successfully = True

                elif cmd_type == "qbc": # Query Best Contributor
                     account_id = get_random_account_id()
                     if account_id is not None:
                         cmd = f"qbc {account_id}"
                         generated_successfully = True

                elif cmd_type == "qra": # Query Received Articles
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
    for query_type, min_req in min_counts_map.items():
        attempts = 0
        max_attempts = min_req * 5 + 20

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
                    if owner_id is None: # Fallback
                        owner_id = get_random_person()
                        if owner_id is not None: tag_id = random.randint(0, max_tag_id)
                    if owner_id is not None and tag_id is not None: cmd = f"qtav {owner_id} {tag_id}"
                elif query_type == "qtvs": # Added
                    owner_id, tag_id = get_random_tag_owner_and_tag()
                    if owner_id is None: # Fallback
                        owner_id = get_random_person()
                        if owner_id is not None: tag_id = random.randint(0, max_tag_id)
                    if owner_id is not None and tag_id is not None: cmd = f"qtvs {owner_id} {tag_id}"
                elif query_type == "qba":
                    person_id = get_random_person()
                    if person_id is not None: cmd = f"qba {person_id}"
                elif query_type == "qcs":
                    cmd = "qcs"
                elif query_type == "qsp":
                    p1, p2 = get_two_random_persons()
                    if p1 is not None and p2 is not None: cmd = f"qsp {p1} {p2}"
                elif query_type == "qbc":
                    account_id = get_random_account_id()
                    if account_id is not None: cmd = f"qbc {account_id}"
                elif query_type == "qra":
                    person_id = get_random_person()
                    if person_id is not None: cmd = f"qra {person_id}"

            except Exception as e:
                 print(f"ERROR generating supplementary command {query_type}: {e}", file=sys.stderr)
                 traceback.print_exc(file=sys.stderr)

            if cmd:
                generated_cmds_list.append(cmd)
                cmd_counts[query_type] += 1

        if cmd_counts[query_type] < min_req:
             print(f"Warning: Could not generate {min_req} required '{query_type}' commands after {attempts} attempts. Generated {cmd_counts[query_type]}. State might be prohibitive.", file=sys.stderr)

    return generated_cmds_list, cmd_counts


# --- Argument Parsing (Added HW10 args) ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate test data for HW10 social network.")

    # Core Controls
    parser.add_argument("-n", "--num_commands", type=int, default=2000, help="Target number of commands (ignored if --phases is set).")
    parser.add_argument("--max_person_id", type=int, default=150, help="Maximum person ID (0 to max).")
    parser.add_argument("--max_tag_id", type=int, default=15, help="Maximum tag ID per person (0 to max).")
    parser.add_argument("--max_account_id", type=int, default=50, help="Maximum official account ID (0 to max).") # New
    parser.add_argument("--max_article_id", type=int, default=500, help="Maximum article ID (0 to max).") # New
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
    # parser.add_argument("--degree_focus", choices=['uniform', 'hub'], default='uniform', help="Influence degree distribution ('hub' partially implemented via --hub_bias).")
    parser.add_argument("--max_degree", type=int, default=None, help="Attempt to limit the maximum degree of any person.")
    parser.add_argument("--hub_bias", type=float, default=0.0, help="Probability (0.0-1.0) for 'ar' to connect to a designated hub node.")
    parser.add_argument("--num_hubs", type=int, default=5, help="Number of initial person IDs (0 to N-1) to treat as potential hubs.")

    # Tag & Account Controls
    parser.add_argument("--tag_focus", type=float, default=0.25, help="Approx. ratio of total commands related to tags (0.0-1.0).") # Adjusted default
    parser.add_argument("--account_focus", type=float, default=0.25, help="Approx. ratio of total commands related to accounts/articles (0.0-1.0).") # New
    parser.add_argument("--max_tag_size", type=int, default=50, help="Attempt to limit the max number of persons in a tag (up to JML limit 1000).")

    # Query & Exception Controls
    parser.add_argument("--qci_focus", choices=['mixed', 'close', 'far'], default='mixed', help="Influence 'qci' pair selection.")
    parser.add_argument("--min_qci", type=int, default=10, help="Minimum number of qci commands.")
    parser.add_argument("--min_qts", type=int, default=5, help="Minimum number of qts commands.")
    parser.add_argument("--min_qtav", type=int, default=10, help="Minimum number of qtav commands.")
    parser.add_argument("--min_qtvs", type=int, default=10, help="Minimum number of qtvs commands.") # New
    parser.add_argument("--min_qba", type=int, default=5, help="Minimum number of qba commands.")
    parser.add_argument("--min_qcs", type=int, default=3, help="Minimum number of qcs commands.") # New
    parser.add_argument("--min_qsp", type=int, default=5, help="Minimum number of qsp commands.") # New
    parser.add_argument("--min_qbc", type=int, default=5, help="Minimum number of qbc commands.") # New
    parser.add_argument("--min_qra", type=int, default=5, help="Minimum number of qra commands.") # New
    parser.add_argument("--exception_ratio", type=float, default=0.08, help="Probability (0.0-1.0) to attempt generating an exception command.") # Increased slightly
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
        hce_max_pid = 99 # Person ID limit
        hce_max_value = 200 # Age, Relation Value, Mod Value limit

        # Note: HCE doesn't specify limits for Account/Article IDs, Tag IDs, or Tag Size.
        # We'll keep the defaults or user-provided values unless they seem unreasonable.
        # The primary HCE limits applied are N, PersonID, and Values.

        target_n = args.num_commands # Default target
        if args.phases:
            try:
                _, total_phase_commands = parse_phases(args.phases)
                target_n = total_phase_commands
            except ValueError: pass # Error handled later

        if target_n > hce_max_n:
            print(f"  num_commands/phase total capped from {target_n} to {hce_max_n}", file=sys.stderr)
            args.num_commands = hce_max_n # Cap the final target number
        else:
            args.num_commands = target_n # Use the original target if within limits

        if args.max_person_id > hce_max_pid:
            print(f"  max_person_id capped from {args.max_person_id} to {hce_max_pid}", file=sys.stderr)
            args.max_person_id = hce_max_pid

        # Apply value caps
        if args.max_age > hce_max_value:
            print(f"  max_age capped from {args.max_age} to {hce_max_value}", file=sys.stderr)
            args.max_age = hce_max_value
        if args.max_rel_value > hce_max_value:
            print(f"  max_rel_value capped from {args.max_rel_value} to {hce_max_value}", file=sys.stderr)
            args.max_rel_value = hce_max_value
        if args.max_mod_value > hce_max_value:
             print(f"  max_mod_value capped from {args.max_mod_value} to {hce_max_value}", file=sys.stderr)
             args.max_mod_value = hce_max_value

    # --- Validate Phases ---
    phases_config = None
    if args.phases:
        try:
            phases_config, total_phase_commands = parse_phases(args.phases)
            # If HCE is active, args.num_commands was already capped above.
            # If HCE is not active, set num_commands to the phase total.
            if not args.hce:
                 args.num_commands = total_phase_commands
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
        person_degrees.clear()
        official_accounts.clear(); account_details.clear(); account_followers.clear()
        account_articles.clear(); account_contributions.clear(); all_articles.clear()
        article_contributors.clear(); article_locations.clear(); person_received_articles.clear()

        # Generate commands using the potentially capped args.num_commands
        all_commands, final_cmd_counts = generate_commands(
            args.num_commands, args.max_person_id, args.max_tag_id,
            args.max_account_id, args.max_article_id, # New max IDs
            args.max_rel_value, args.max_mod_value, args.max_age,
            # Min query counts
            args.min_qci, args.min_qts, args.min_qtav, args.min_qba,
            args.min_qcs, args.min_qsp, args.min_qtvs, args.min_qbc, args.min_qra,
            # Control params
            args.density, 'uniform', args.max_degree, # degree_focus removed for now
            args.tag_focus, args.account_focus, args.max_tag_size, args.qci_focus, # Added account_focus
            args.mr_delete_ratio, args.exception_ratio,
            args.force_qba_empty_ratio, args.force_qtav_empty_ratio,
            args.hub_bias, args.num_hubs,
            phases_config,
            args.hce
        )

        # Print all generated commands
        for command in all_commands:
             # Ensure newline consistency
             output_stream.write(command.strip() + '\n')

        # Print summary to stderr
        final_command_count = len(all_commands)
        print(f"\n--- Generation Summary ---", file=sys.stderr)
        print(f"Target commands: {args.num_commands}", file=sys.stderr)
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


        print(f"Command Counts:", file=sys.stderr)
        # Sort alphabetically, but maybe group add/del/query later?
        for cmd_type, count in sorted(final_cmd_counts.items()):
            print(f"  {cmd_type}: {count}", file=sys.stderr)

        if args.output_file:
             print(f"Output written to: {args.output_file}", file=sys.stderr)
        else:
             print(f"Output printed to stdout.", file=sys.stderr)

    finally:
        if args.output_file and output_stream is not sys.stdout:
            output_stream.close()

# --- END OF UPDATED FILE gen.py ---

