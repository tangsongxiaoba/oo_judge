# -*- coding: utf-8 -*-
import sys
import math
from collections import deque, defaultdict # Added defaultdict
import json

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
    # JML uses integer division for mean
    mean = sum(ages) // n if n > 0 else 0
    variance_sum_sq_diff = sum((age - mean) ** 2 for age in ages)
    # JML uses integer division for variance
    variance = int(variance_sum_sq_diff // n) if n > 0 else 0
    return variance

# --- Simulator Classes ---

class TagSimulator:
    def __init__(self, tag_id):
        self.id = tag_id
        self.persons = set() # Set of person_ids

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

class OfficialAccountSimulator:
    def __init__(self, account_id, owner_id, name):
        self.id = account_id
        self.owner_id = owner_id
        self.name = name
        # Using dict for followers: follower_id -> contribution_count
        self.followers = {}
        # Set of article_ids belonging to this account
        self.articles = set()

    def add_follower(self, person_id):
        # JML ensures !containsFollower before calling this
        if person_id not in self.followers:
             self.followers[person_id] = 0

    def contains_follower(self, person_id):
        return person_id in self.followers

    def add_article(self, person_id, article_id):
        # JML ensures !containsArticle, containsFollower(person) before calling
        if person_id in self.followers:
            self.articles.add(article_id)
            self.followers[person_id] = self.followers.get(person_id, 0) + 1
        else:
            # This case should ideally not happen if JML pre-conditions are met
            # by the calling method (NetworkSimulator.contributeArticle)
             print(f"CHECKER WARNING: add_article called for non-follower {person_id} on account {self.id}", file=sys.stderr)


    def contains_article(self, article_id):
        return article_id in self.articles

    def remove_article(self, article_id, original_contributor_id):
        # JML ensures containsArticle before calling
        self.articles.discard(article_id)
        # JML ensures the contributor exists among followers when deleting
        if original_contributor_id in self.followers:
            self.followers[original_contributor_id] -= 1
            # Note: JML doesn't explicitly say what happens if contribution becomes < 0,
            # but based on adding +1, decrementing by 1 seems correct.
        else:
             print(f"CHECKER WARNING: remove_article called, but original contributor {original_contributor_id} not found in followers of account {self.id}", file=sys.stderr)


    def get_best_contributor(self):
        if not self.followers:
            # JML doesn't explicitly define this, common practice might be 0 or error.
            # The JML formula implies min ID over non-empty set.
            # Let's return 0 if no followers, assuming IDs are > 0 or tests handle this.
            # Or perhaps the calling code should handle empty follower list.
            # Following the spec's min logic: if no one qualifies, there's no min.
            # Let's assume test cases won't query best contributor on accounts with 0 followers
            # or expect a specific value like 0. If they do, we might need adjustment.
            # For now, let's find the max contribution and then the min ID.
             return 0 # Default or needs clarification based on test cases

        max_contribution = -1 # Contributions are >= 0
        for contribution in self.followers.values():
            max_contribution = max(max_contribution, contribution)

        best_id = float('inf')
        for person_id, contribution in self.followers.items():
            if contribution == max_contribution:
                best_id = min(best_id, person_id)

        # Should always find a best_id if followers is not empty
        return best_id if best_id != float('inf') else 0 # Fallback


class PersonSimulator:
    def __init__(self, person_id, name, age):
        self.id = person_id
        self.name = name
        self.age = age
        self.acquaintance = {} # maps acquaintance_id -> value
        self.tags = {} # maps tag_id -> TagSimulator object
        # Use deque for efficient adding to front (most recent)
        self.received_articles = deque()

    def add_received_article(self, article_id):
        self.received_articles.appendleft(article_id) # Add to the front

    def remove_received_article(self, article_id):
        # Removing can be O(N) for deque/list if not at ends
        try:
            # Create a new deque excluding the article_id
            # This is simpler than finding and removing all occurrences in place
             new_deque = deque(a_id for a_id in self.received_articles if a_id != article_id)
             self.received_articles = new_deque
        except ValueError:
             pass # Article not found, ignore

    def get_received_articles_list(self):
        # Returns the full list (as required by internal model)
        return list(self.received_articles)

    def query_received_articles_list(self):
         # Returns first 5 (or fewer) for the query method
         count = min(len(self.received_articles), 5)
         return [self.received_articles[i] for i in range(count)]

    # --- Existing PersonSimulator methods ---
    def is_linked(self, other_person_id):
        return other_person_id == self.id or other_person_id in self.acquaintance

    def query_value(self, other_person_id):
        if other_person_id == self.id: return 0
        return self.acquaintance.get(other_person_id, 0)

    def add_link(self, other_person_id, value):
        if other_person_id != self.id:
             self.acquaintance[other_person_id] = value

    def remove_link(self, other_person_id):
        self.acquaintance.pop(other_person_id, None)

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
        return self.tags.pop(tag_id, None) is not None

    def get_acquaintance_ids_and_values(self):
        return list(self.acquaintance.items())

    def get_neighbor_ids(self):
        return set(self.acquaintance.keys())

    def __eq__(self, other):
        if not isinstance(other, PersonSimulator): return NotImplemented
        return self.id == other.id

    def __hash__(self): return hash(self.id)
    def __str__(self): return f"Person(id={self.id}, name='{self.name}', age={self.age})"


class NetworkSimulator:
    def __init__(self):
        self.persons = {} # map person_id -> PersonSimulator
        self.accounts = {} # map account_id -> OfficialAccountSimulator
        self.articles = set() # Global set of all existing article_ids
        self.article_contributors = {} # map article_id -> contributor_person_id

        # Extended exception counts
        self.exception_counts = {
            # HW8/9
            "anf": {"total": 0, "ids": defaultdict(int)}, "epi": {"total": 0, "ids": defaultdict(int)},
            "er": {"total": 0, "ids": defaultdict(int)}, "eti": {"total": 0, "ids": defaultdict(int)},
            "pinf": {"total": 0, "ids": defaultdict(int)}, "rnf": {"total": 0, "ids": defaultdict(int)},
            "tinf": {"total": 0, "ids": defaultdict(int)}, "pnf": {"total": 0, "ids": defaultdict(int)},
            # HW10
            "eoai": {"total": 0, "ids": defaultdict(int)}, "oainf": {"total": 0, "ids": defaultdict(int)},
            "doapd": {"total": 0, "ids": defaultdict(int)}, "eai": {"total": 0, "ids": defaultdict(int)},
            "ainf": {"total": 0, "ids": defaultdict(int)}, "cpd": {"total": 0, "ids": defaultdict(int)},
            "dapd": {"total": 0, "ids": defaultdict(int)},
        }
        # Static counts for exceptions where total count != sum of id counts
        self.er_static_count = 0
        self.pnf_static_count = 0
        self.cpd_static_count = 0
        self.dapd_static_count = 0
        self.doapd_static_count = 0
        # RNF still needs special handling for total count (/2)

        # Optimization: Store triple sum count incrementally
        self.triple_sum_count = 0

    def _record_exception(self, exc_type, id1, id2=None):
        # Increment static counts first if applicable
        if exc_type == "er": self.er_static_count += 1
        elif exc_type == "pnf": self.pnf_static_count += 1
        elif exc_type == "cpd": self.cpd_static_count += 1
        elif exc_type == "dapd": self.dapd_static_count += 1
        elif exc_type == "doapd": self.doapd_static_count += 1

        # Increment total count (special case for RNF handled in format)
        if exc_type != "rnf":
            self.exception_counts[exc_type]["total"] += 1

        # Increment ID counts
        fmt_id1, fmt_id2 = id1, id2
        # Ensure consistent ordering for paired exceptions before recording counts
        if exc_type in ("er", "rnf", "pnf", "cpd", "dapd", "doapd") and id2 is not None and id1 > id2:
             fmt_id1, fmt_id2 = id2, id1

        self.exception_counts[exc_type]["ids"][fmt_id1] += 1
        if id2 is not None:
            # Handle cases where id1 == id2 for paired exceptions - JML implies count only once for the ID
            if fmt_id1 != fmt_id2:
                 self.exception_counts[exc_type]["ids"][fmt_id2] += 1
            # Special RNF handling: JML records both IDs even if they are identical,
            # and its total count is different. Let's adjust here.
            if exc_type == "rnf":
                 # RNF increments total by 2 effectively (1 per ID)
                 self.exception_counts[exc_type]["total"] += 2
                 # If ids were same, the second ID count needs adding explicitly
                 if fmt_id1 == fmt_id2:
                      self.exception_counts[exc_type]["ids"][fmt_id2] += 1


    def _format_exception(self, exc_type, id1, id2=None):
        fmt_id1, fmt_id2 = id1, id2
        # Order IDs for formatting paired exceptions consistently
        if exc_type in ("er", "rnf", "pnf", "cpd", "dapd", "doapd") and id2 is not None and id1 > id2:
             fmt_id1, fmt_id2 = id2, id1

        # Get counts based on the potentially reordered IDs
        id1_count = self.exception_counts[exc_type]["ids"].get(fmt_id1, 0)
        id2_count = self.exception_counts[exc_type]["ids"].get(fmt_id2, 0) if id2 is not None else 0
        total_count = self.exception_counts[exc_type]["total"]

        # Format based on type
        if exc_type == "anf": return f"anf-{total_count}, {fmt_id1}-{id1_count}"
        elif exc_type == "epi": return f"epi-{total_count}, {id1}-{id1_count}" # Use original id1 for epi
        elif exc_type == "er": return f"er-{self.er_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "eti": return f"eti-{total_count}, {id1}-{id1_count}" # Use original id1 for eti
        elif exc_type == "pinf": return f"pinf-{total_count}, {id1}-{id1_count}" # Use original id1 for pinf
        elif exc_type == "rnf":
            total_print_count = total_count // 2 # RNF specific total count logic
            return f"rnf-{total_print_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "tinf": return f"tinf-{total_count}, {id1}-{id1_count}" # Use original id1 for tinf
        elif exc_type == "pnf": return f"pnf-{self.pnf_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        # HW10 exceptions
        elif exc_type == "eoai": return f"eoai-{total_count}, {id1}-{id1_count}" # Use original id1
        elif exc_type == "oainf": return f"oainf-{total_count}, {id1}-{id1_count}"# Use original id1
        elif exc_type == "doapd": return f"doapd-{self.doapd_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "eai": return f"eai-{total_count}, {id1}-{id1_count}" # Use original id1
        elif exc_type == "ainf": return f"ainf-{total_count}, {id1}-{id1_count}" # Use original id1
        elif exc_type == "cpd": return f"cpd-{self.cpd_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "dapd": return f"dapd-{self.dapd_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        else: return "CHECKER_ERROR: Unknown exception type"

    # --- Existing NetworkSimulator methods ---
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
        if not self.contains_person(id1): self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
        if not self.contains_person(id2): self._record_exception("pinf", id2); return self._format_exception("pinf", id2)
        person1 = self.get_person(id1); person2 = self.get_person(id2)
        if person1.is_linked(id2):
            self._record_exception("er", id1, id2); return self._format_exception("er", id1, id2)
        else:
            if id1 != id2:
                neighbors1 = person1.get_neighbor_ids(); neighbors2 = person2.get_neighbor_ids()
                common_neighbors = neighbors1.intersection(neighbors2)
                self.triple_sum_count += len(common_neighbors)
                person1.add_link(id2, value); person2.add_link(id1, value)
            return "Ok" # Adding relation to self is allowed, but no effect on links/triples

    def modify_relation(self, id1, id2, value):
        if not self.contains_person(id1): self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
        if not self.contains_person(id2): self._record_exception("pinf", id2); return self._format_exception("pinf", id2)
        if id1 == id2: self._record_exception("epi", id1); return self._format_exception("epi", id1)
        person1 = self.get_person(id1); person2 = self.get_person(id2)
        if not person1.is_linked(id2):
             self._record_exception("rnf", id1, id2); return self._format_exception("rnf", id1, id2)
        else:
            old_value = person1.query_value(id2); new_value = old_value + value
            if new_value > 0:
                person1.add_link(id2, new_value); person2.add_link(id1, new_value)
            else: # Remove relation
                neighbors1 = person1.get_neighbor_ids(); neighbors2 = person2.get_neighbor_ids()
                common_neighbors = neighbors1.intersection(neighbors2)
                self.triple_sum_count -= len(common_neighbors)
                person1.remove_link(id2); person2.remove_link(id1)
                # Remove from tags
                for tag in list(person1.tags.values()): # Iterate over copy if modifying
                    tag.del_person(id2)
                for tag in list(person2.tags.values()):
                    tag.del_person(id1)
            return "Ok"

    def query_value(self, id1, id2):
        if not self.contains_person(id1): self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
        if not self.contains_person(id2): self._record_exception("pinf", id2); return self._format_exception("pinf", id2)
        person1 = self.get_person(id1)
        if id1 != id2 and not person1.is_linked(id2):
            self._record_exception("rnf", id1, id2); return self._format_exception("rnf", id1, id2)
        return str(person1.query_value(id2))

    def is_circle(self, id1, id2):
         if not self.contains_person(id1): self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
         if not self.contains_person(id2): self._record_exception("pinf", id2); return self._format_exception("pinf", id2)
         if id1 == id2: return "true" # JML implies circle check passes if id1==id2 and exists
         # BFS Implementation
         queue = deque([id1]); visited = {id1}
         while queue:
             current_id = queue.popleft()
             # No need to check for target here in is_circle, just reachability
             current_person = self.get_person(current_id)
             if current_person:
                 for neighbor_id in current_person.acquaintance.keys():
                     if neighbor_id == id2: return "true" # Found target
                     if neighbor_id not in visited:
                         visited.add(neighbor_id); queue.append(neighbor_id)
         return "false" # Target not reached

    def query_triple_sum(self):
        return str(self.triple_sum_count)

    def add_tag(self, person_id, tag_id):
        if not self.contains_person(person_id): self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        if person.contains_tag(tag_id):
             self._record_exception("eti", tag_id); return self._format_exception("eti", tag_id)
        else:
            new_tag = TagSimulator(tag_id); person.add_tag(new_tag)
            return "Ok"

    def add_person_to_tag(self, person_id1, person_id2, tag_id):
        if not self.contains_person(person_id1): self._record_exception("pinf", person_id1); return self._format_exception("pinf", person_id1)
        if not self.contains_person(person_id2): self._record_exception("pinf", person_id2); return self._format_exception("pinf", person_id2)
        if person_id1 == person_id2: self._record_exception("epi", person_id1); return self._format_exception("epi", person_id1)
        person1 = self.get_person(person_id1); person2 = self.get_person(person_id2)
        if not person2.is_linked(person_id1): self._record_exception("rnf", person_id1, person_id2); return self._format_exception("rnf", person_id1, person_id2)
        if not person2.contains_tag(tag_id): self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
        tag = person2.get_tag(tag_id)
        if tag.has_person(person_id1): self._record_exception("epi", person_id1); return self._format_exception("epi", person_id1)
        # Size check before adding
        if tag.get_size() < 1000: # JML <= 999 for adding
             tag.add_person(person_id1)
        # JML implies no output/error if size >= 1000
        return "Ok"

    def query_tag_value_sum(self, person_id, tag_id):
        # This calculation can be slow O(TagSize^2) if not optimized
        # Let's implement according to JML directly first
        if not self.contains_person(person_id): self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        if not person.contains_tag(tag_id): self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
        tag = person.get_tag(tag_id)
        person_ids_in_tag = tag.get_person_ids() # O(TagSize)
        value_sum = 0
        # O(TagSize^2 * O(queryValue)) -> O(TagSize^2) with dicts
        for i in range(len(person_ids_in_tag)):
            p1_id = person_ids_in_tag[i]
            p1 = self.get_person(p1_id)
            if not p1: continue # Should not happen in valid state
            for j in range(len(person_ids_in_tag)): # JML includes i==j check implicit in queryValue
                p2_id = person_ids_in_tag[j]
                # queryValue handles p1 == p2 and !isLinked cases returning 0
                value = p1.query_value(p2_id)
                value_sum += value
        return str(value_sum)

    def query_tag_age_var(self, person_id, tag_id):
        if not self.contains_person(person_id): self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        if not person.contains_tag(tag_id): self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
        tag = person.get_tag(tag_id)
        person_ids_in_tag = tag.get_person_ids() # O(TagSize)
        ages = []
        for pid in person_ids_in_tag: # O(TagSize)
            p = self.get_person(pid) # O(1)
            if p: ages.append(p.age)
        age_var = calculate_age_var(ages) # O(TagSize)
        return str(age_var)

    def del_person_from_tag(self, person_id1, person_id2, tag_id):
        if not self.contains_person(person_id1): self._record_exception("pinf", person_id1); return self._format_exception("pinf", person_id1)
        if not self.contains_person(person_id2): self._record_exception("pinf", person_id2); return self._format_exception("pinf", person_id2)
        person2 = self.get_person(person_id2)
        if not person2.contains_tag(tag_id): self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
        tag = person2.get_tag(tag_id)
        if not tag.has_person(person_id1): # JML requires hasPerson -> PINF exception
            self._record_exception("pinf", person_id1); return self._format_exception("pinf", person_id1)
        tag.del_person(person_id1)
        return "Ok"

    def del_tag(self, person_id, tag_id):
        if not self.contains_person(person_id): self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        if not person.contains_tag(tag_id): self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
        person.del_tag(tag_id)
        return "Ok"

    def query_best_acquaintance(self, person_id):
        if not self.contains_person(person_id): self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        acquaintances = person.get_acquaintance_ids_and_values()
        if not acquaintances: self._record_exception("anf", person_id); return self._format_exception("anf", person_id)
        # Find max value, then min ID with that max value
        max_value = float('-inf')
        # Correct logic according to JML: find max value first
        for _, value in acquaintances: max_value = max(max_value, value)
        best_id = float('inf')
        for acq_id, value in acquaintances:
             if value == max_value: best_id = min(best_id, acq_id)
        # JML guarantees existence if acquaintances is not empty
        return str(int(best_id))

    def query_couple_sum(self):
        # O(N*degree) - Iterate through all persons and check their best acquaintance
        count = 0
        person_ids = list(self.persons.keys()) # O(N)
        for i in range(len(person_ids)):
            id1 = person_ids[i]
            person1 = self.get_person(id1)
            if not person1 or not person1.acquaintance: continue # Skip if no acquaintances

            # Simulate queryBestAcquaintance for id1
            acquaintances1 = person1.get_acquaintance_ids_and_values()
            if not acquaintances1: continue # Should be caught by above check, but safe
            max_value1 = max(v for _, v in acquaintances1)
            best_id1 = min(aid for aid, v in acquaintances1 if v == max_value1)

            # Check only pairs where id1 < best_id1 to avoid double counting
            if id1 < best_id1:
                id2 = best_id1
                if not self.contains_person(id2): continue # Best acquaintance doesn't exist? Skip.
                person2 = self.get_person(id2)
                if not person2 or not person2.acquaintance: continue # Skip if best acq has no acquaintances

                # Simulate queryBestAcquaintance for id2
                acquaintances2 = person2.get_acquaintance_ids_and_values()
                if not acquaintances2: continue
                max_value2 = max(v for _, v in acquaintances2)
                best_id2 = min(aid for aid, v in acquaintances2 if v == max_value2)

                # Check if they point to each other
                if best_id2 == id1:
                    count += 1
        return str(count)

    def query_shortest_path(self, id1, id2):
        # O(N + E) using BFS
        if not self.contains_person(id1): self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
        if not self.contains_person(id2): self._record_exception("pinf", id2); return self._format_exception("pinf", id2)
        if id1 == id2: return "0" # JML requires 0 for same id

        # BFS to find shortest path length (number of edges)
        queue = deque([(id1, 0)]) # (person_id, distance)
        visited = {id1}
        while queue:
            current_id, distance = queue.popleft()
            if current_id == id2:
                return str(distance) # Found shortest path

            current_person = self.get_person(current_id)
            if current_person:
                for neighbor_id in current_person.acquaintance.keys():
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        queue.append((neighbor_id, distance + 1))

        # If queue empties and id2 not found
        self._record_exception("pnf", id1, id2); return self._format_exception("pnf", id1, id2)

    # --- HW10 Methods ---

    def contains_account(self, account_id):
        return account_id in self.accounts

    def get_account(self, account_id):
        return self.accounts.get(account_id)

    def contains_article(self, article_id):
        return article_id in self.articles # Check global article set

    def create_official_account(self, person_id, account_id, name):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        if self.contains_account(account_id):
            self._record_exception("eoai", account_id); return self._format_exception("eoai", account_id)

        # Create account
        new_account = OfficialAccountSimulator(account_id, person_id, name)
        self.accounts[account_id] = new_account

        # Add owner as follower with 0 contribution (as per JML)
        new_account.add_follower(person_id)
        # Note: JML doesn't explicitly state owner gets 0 contribution, but the ensures clause implies it:
        # ensures (\exists int i; ... followers[i].getId() == personId && contributions[i] == 0);
        # Since addFollower sets it to 0, this holds.

        return "Ok"

    def delete_official_account(self, person_id, account_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        if not self.contains_account(account_id):
            self._record_exception("oainf", account_id); return self._format_exception("oainf", account_id)

        account = self.get_account(account_id)
        if account.owner_id != person_id:
            self._record_exception("doapd", person_id, account_id); return self._format_exception("doapd", person_id, account_id)

        # Delete the account
        # JML 'assignable accounts' means only the accounts list/map changes.
        # It does NOT specify removing articles from global list or received lists.
        # Strict interpretation: just remove the account object.
        del self.accounts[account_id]

        return "Ok"

    def contribute_article(self, person_id, account_id, article_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        if not self.contains_account(account_id):
            self._record_exception("oainf", account_id); return self._format_exception("oainf", account_id)
        if self.contains_article(article_id): # Check global article existence
            self._record_exception("eai", article_id); return self._format_exception("eai", article_id)

        account = self.get_account(account_id)
        person = self.get_person(person_id)

        if not account.contains_follower(person_id):
            self._record_exception("cpd", person_id, article_id); return self._format_exception("cpd", person_id, article_id) # Note: JML uses articleId for id2 here

        # Add article globally
        self.articles.add(article_id)
        self.article_contributors[article_id] = person_id

        # Add article to account and update contribution
        account.add_article(person_id, article_id) # Handles adding to account.articles and incrementing contribution

        # Add article to received list of ALL current followers
        # This can be slow if many followers O(num_followers)
        current_follower_ids = list(account.followers.keys()) # Get a snapshot
        for follower_id in current_follower_ids:
            follower_person = self.get_person(follower_id)
            if follower_person:
                follower_person.add_received_article(article_id) # Add to front (deque)
            else:
                 print(f"CHECKER WARNING: Follower {follower_id} not found when distributing article {article_id}", file=sys.stderr)

        return "Ok"

    def delete_article(self, person_id, account_id, article_id):
         if not self.contains_person(person_id):
             self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
         if not self.contains_account(account_id):
             self._record_exception("oainf", account_id); return self._format_exception("oainf", account_id)

         account = self.get_account(account_id)

         if not account.contains_article(article_id): # Check if article exists IN THIS ACCOUNT
             self._record_exception("ainf", article_id); return self._format_exception("ainf", article_id)
         if account.owner_id != person_id:
             self._record_exception("dapd", person_id, article_id); return self._format_exception("dapd", person_id, article_id) # Note: JML uses articleId for id2

         # Find original contributor BEFORE removing from account
         original_contributor_id = self.article_contributors.get(article_id)
         if original_contributor_id is None:
              print(f"CHECKER WARNING: Article {article_id} contributor mapping missing during deletion.", file=sys.stderr)
              # Decide how to proceed. Maybe skip contribution decrement?
              # Let's assume the contributor exists for valid states.

         # Remove article from account and decrement contribution
         account.remove_article(article_id, original_contributor_id)

         # Remove article from global records
         self.articles.discard(article_id)
         self.article_contributors.pop(article_id, None)

         # Remove article from ALL current followers' received lists
         # Potentially slow: O(num_followers * len(received_articles)) in worst case list removal
         # O(num_followers * len(received_articles)) with deque recreation
         current_follower_ids = list(account.followers.keys()) # Snapshot
         for follower_id in current_follower_ids:
             follower_person = self.get_person(follower_id)
             if follower_person:
                 follower_person.remove_received_article(article_id)

         return "Ok"

    def follow_official_account(self, person_id, account_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        if not self.contains_account(account_id):
            self._record_exception("oainf", account_id); return self._format_exception("oainf", account_id)

        account = self.get_account(account_id)
        person = self.get_person(person_id) # Not strictly needed by logic, but good practice

        if account.contains_follower(person_id):
            # JML uses EqualPersonIdException here
            self._record_exception("epi", person_id); return self._format_exception("epi", person_id)

        # Add follower
        account.add_follower(person_id) # Sets contribution to 0

        return "Ok"

    def query_best_contributor(self, account_id):
        if not self.contains_account(account_id):
            self._record_exception("oainf", account_id); return self._format_exception("oainf", account_id)

        account = self.get_account(account_id)
        best_contributor_id = account.get_best_contributor()
        return str(best_contributor_id)

    def query_received_articles(self, person_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)

        person = self.get_person(person_id)
        articles_list = person.query_received_articles_list() # Gets first 5

        if not articles_list:
            return "None"
        else:
            return " ".join(map(str, articles_list)) # Space separated


# --- Main Checker Logic ---

def run_checker(stdin_path, stdout_path):
    network = NetworkSimulator()
    result_status = "Accepted"
    error_details = []

    try:
        with open(stdin_path, 'r', encoding='utf-8') as f_in:
            input_lines = [line.strip() for line in f_in if line.strip()]
    except FileNotFoundError: result_status = "Rejected"; error_details.append({"reason": f"Checker Error: Input file not found: {stdin_path}"}); print(json.dumps({"result": result_status, "errors": error_details}, indent=4)); sys.exit(0)
    except Exception as e: result_status = "Rejected"; error_details.append({"reason": f"Checker Error: Failed to read input file {stdin_path}: {e}"}); print(json.dumps({"result": result_status, "errors": error_details}, indent=4)); sys.exit(0)

    try:
        with open(stdout_path, 'r', encoding='utf-8') as f_out:
            output_lines = [line.strip() for line in f_out if line.strip()]
    except FileNotFoundError: result_status = "Rejected"; error_details.append({"reason": f"Checker Error: Output file not found: {stdout_path}"}); print(json.dumps({"result": result_status, "errors": error_details}, indent=4)); sys.exit(0)
    except Exception as e: result_status = "Rejected"; error_details.append({"reason": f"Checker Error: Failed to read output file {stdout_path}: {e}"}); print(json.dumps({"result": result_status, "errors": error_details}, indent=4)); sys.exit(0)

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

        # --- Handle load_network specially ---
        # (load_network logic remains the same as it relies on add_person/add_relation)
        if cmd in ("ln", "load_network", "lnl", "load_network_local"):
             load_expected_output = "Ok"; load_actual_output = None
             if output_idx >= len(output_lines): result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": load_expected_output, "actual": None, "reason": f"Missing output for {cmd}"}); break
             load_actual_output = output_lines[output_idx]; output_idx += 1
             if len(parts) < 2: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output, "reason": f"Malformed {cmd} command"}); break
             n_str = parts[1]; n = parse_int(n_str)
             if n is None or n < 0: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output, "reason": f"Invalid count '{n_str}' in {cmd}"}); break

             source_lines = []; source_idx_offset = 0; load_file_error = False
             load_lines_needed = 0
             if n > 0: # Calculate lines needed for relations (triangular matrix part)
                 load_lines_needed = 3 + n # ids, names, ages, plus n relation lines

             if cmd in ("lnl", "load_network_local"):
                  if len(parts) < 3: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output, "reason": f"Missing filename for {cmd}"}); break
                  filename = parts[2]
                  try:
                       with open(filename, 'r', encoding='utf-8') as f_load: source_lines = [line.strip() for line in f_load if line.strip()]
                       # Check if enough lines exist in the file for n > 0
                       if n > 0 and len(source_lines) < load_lines_needed: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output, "reason": f"File {filename} insufficient data (expected {load_lines_needed} lines, got {len(source_lines)})"}); break
                  except FileNotFoundError: load_file_error = True; load_expected_output = "File not found"
                  except Exception as e: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Error reading load file {filename}: {e}"}); break
             else: # ln
                  # Check if enough lines remain in stdin for n > 0
                  if n > 0 and input_idx + load_lines_needed -1 > len(input_lines): # -1 because cmd_line already read
                      result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Insufficient lines in stdin for {cmd} {n} (expected {load_lines_needed})"}); break
                  if n > 0:
                     source_lines = input_lines; source_idx_offset = input_idx; input_idx += load_lines_needed

             if load_actual_output != load_expected_output: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": load_expected_output, "actual": load_actual_output, "reason": "Output mismatch for load command"}); break
             if load_file_error: continue # Skip simulation if file not found (already matched output)
             if n == 0: continue # Skip simulation if n=0 (already matched output)

             # Simulate load for n > 0
             try:
                  ids_line = source_lines[source_idx_offset].split(); names_line = source_lines[source_idx_offset + 1].split(); ages_line = source_lines[source_idx_offset + 2].split()
                  if not (len(ids_line) == n and len(names_line) == n and len(ages_line) == n): raise ValueError("Mismatched counts in header lines")
                  ids = [parse_int(id_s) for id_s in ids_line]; names = names_line; ages = [parse_int(age_s) for age_s in ages_line]
                  if None in ids or None in ages: raise ValueError("Parse error IDs/Ages")
                  for i in range(n):
                        sim_res = network.add_person(ids[i], names[i], ages[i]) # Simulate adding person
                        if sim_res != "Ok": raise ValueError(f"Load Error: Failed adding person {ids[i]}: {sim_res}")

                  current_data_line_idx = source_idx_offset + 3
                  # Relation matrix reading (as per spec: row i has i values for relations with 0..i-1)
                  for i in range(n): # Process relation line for person ids[i]
                        if current_data_line_idx >= len(source_lines): raise ValueError(f"Missing relation line {i}")
                        value_line = source_lines[current_data_line_idx].split()
                        # Correction: Line i should have i values (connecting to 0..i-1)
                        if len(value_line) != i: raise ValueError(f"Incorrect num values on relation line {i} (expected {i}, got {len(value_line)})")
                        current_data_line_idx += 1
                        for j in range(i): # Relates ids[i] with ids[j]
                            value = parse_int(value_line[j])
                            if value is None: raise ValueError(f"Invalid value on relation line {i}, column {j}")
                            # Spec implies adding only if value != 0, but JML addRelation doesn't state this.
                            # However, the input format description often implies non-zero means add.
                            # Let's stick to adding if value != 0 as per common interpretation of this format.
                            if value != 0:
                                sim_res = network.add_relation(ids[i], ids[j], value) # Simulate adding relation
                                if sim_res != "Ok": raise ValueError(f"Load Error: Failed adding relation {ids[i]}-{ids[j]}: {sim_res}")
             except Exception as e:
                  result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Checker error during load simulation: {type(e).__name__} {e}"}); break
             continue # Move to next command

        # --- Handle regular commands ---
        actual_output = None
        if output_idx >= len(output_lines): result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": "???", "actual": None, "reason": "Missing output"}); break
        actual_output = output_lines[output_idx]; output_idx += 1

        # Simulate command using NetworkSimulator methods
        try:
            # --- HW8/9 Command dispatching ---
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
            elif cmd in ("qtvs", "query_tag_value_sum") and len(parts) == 3:
                 p_id, t_id = parse_int(parts[1]), parse_int(parts[2])
                 if p_id is None or t_id is None: raise ValueError("Bad arguments")
                 expected_output = network.query_tag_value_sum(p_id, t_id)
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
            elif cmd in ("qcs", "query_couple_sum") and len(parts) == 1:
                expected_output = network.query_couple_sum()
            elif cmd in ("qsp", "query_shortest_path") and len(parts) == 3:
                id1, id2 = parse_int(parts[1]), parse_int(parts[2])
                if id1 is None or id2 is None: raise ValueError("Bad arguments")
                expected_output = network.query_shortest_path(id1, id2)

            # --- HW10 Command dispatching ---
            elif cmd in ("coa", "create_official_account") and len(parts) == 4:
                p_id, acc_id, name_str = parse_int(parts[1]), parse_int(parts[2]), parts[3]
                if p_id is None or acc_id is None: raise ValueError("Bad arguments")
                expected_output = network.create_official_account(p_id, acc_id, name_str)
            elif cmd in ("doa", "delete_official_account") and len(parts) == 3:
                p_id, acc_id = parse_int(parts[1]), parse_int(parts[2])
                if p_id is None or acc_id is None: raise ValueError("Bad arguments")
                expected_output = network.delete_official_account(p_id, acc_id)
            elif cmd in ("ca", "contribute_article") and len(parts) == 4:
                p_id, acc_id, art_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                if p_id is None or acc_id is None or art_id is None: raise ValueError("Bad arguments")
                expected_output = network.contribute_article(p_id, acc_id, art_id)
            elif cmd in ("da", "delete_article") and len(parts) == 4:
                p_id, acc_id, art_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                if p_id is None or acc_id is None or art_id is None: raise ValueError("Bad arguments")
                expected_output = network.delete_article(p_id, acc_id, art_id)
            elif cmd in ("foa", "follow_official_account") and len(parts) == 3:
                p_id, acc_id = parse_int(parts[1]), parse_int(parts[2])
                if p_id is None or acc_id is None: raise ValueError("Bad arguments")
                expected_output = network.follow_official_account(p_id, acc_id)
            elif cmd in ("qbc", "query_best_contributor") and len(parts) == 2:
                acc_id = parse_int(parts[1])
                if acc_id is None: raise ValueError("Bad arguments")
                expected_output = network.query_best_contributor(acc_id)
            elif cmd in ("qra", "query_received_articles") and len(parts) == 2:
                p_id = parse_int(parts[1])
                if p_id is None: raise ValueError("Bad arguments")
                expected_output = network.query_received_articles(p_id)

            # --- Unknown Command ---
            else:
                 raise ValueError(f"Unknown or malformed command: '{cmd_line}'")

        except ValueError as e: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Checker Error: Invalid args/cmd: {e}"}); break
        except Exception as e: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Checker Error: Simulation Error: {type(e).__name__} {e}"}); break

        # Compare expected vs actual
        # Special handling for qra space-separated output vs possible single "None"
        if cmd in ("qra", "query_received_articles"):
             # Normalize whitespace for comparison
             norm_expected = " ".join(expected_output.split())
             norm_actual = " ".join(actual_output.split())
             if norm_actual != norm_expected:
                 result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": norm_expected, "actual": norm_actual, "reason": "Output mismatch"}); break
        elif actual_output != expected_output:
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