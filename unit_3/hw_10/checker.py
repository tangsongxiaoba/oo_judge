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
        # JML ensures !containsArticle (in this account), containsFollower(person) before calling
        if person_id in self.followers: # This check ensures the person is a follower
            self.articles.add(article_id) # Add to this account's list of articles
            self.followers[person_id] = self.followers.get(person_id, 0) + 1 # Increment contribution
        else:
             print(f"CHECKER WARNING: OfficialAccountSimulator.add_article called for non-follower {person_id} on account {self.id}", file=sys.stderr)


    def contains_article(self, article_id):
        return article_id in self.articles

    def remove_article(self, article_id, original_contributor_id):
        # JML ensures this account containsArticle before calling
        self.articles.discard(article_id) # Remove from this account's articles
        
        # Decrement contribution of the original_contributor_id IF they are still a follower
        if original_contributor_id in self.followers:
            self.followers[original_contributor_id] -= 1
            # JML doesn't explicitly state contribution can't go below 0, but -1 is the standard interpretation.
        else:
             # This case might occur if the original contributor unfollowed the account
             # before the article was deleted. JML for deleteArticle's ensures clause for contribution
             # implies the person (articleContributors[i]) is still a follower.
             # (\exists int j; ... accounts.get(accountId).followers[j].getId() == articleContributors[i] ... contributions[j] == \old -1)
             # If this warning prints, it might indicate a subtle JML interpretation difference or a complex scenario.
             print(f"CHECKER WARNING: OfficialAccountSimulator.remove_article: Original contributor {original_contributor_id} not found in current followers of account {self.id} during contribution decrement.", file=sys.stderr)


    def get_best_contributor(self):
        if not self.followers:
             return 0 

        max_contribution = -1 
        for contribution in self.followers.values():
            max_contribution = max(max_contribution, contribution)
        
        if max_contribution == -1: # No followers or all contributions somehow negative (should not happen)
            return 0

        best_id = float('inf')
        for person_id, contribution in self.followers.items():
            if contribution == max_contribution:
                best_id = min(best_id, person_id)
        
        return best_id if best_id != float('inf') else 0


class PersonSimulator:
    def __init__(self, person_id, name, age):
        self.id = person_id
        self.name = name
        self.age = age
        self.acquaintance = {} # maps acquaintance_id -> value
        self.tags = {} # maps tag_id -> TagSimulator object
        self.received_articles = deque()

    def add_received_article(self, article_id):
        self.received_articles.appendleft(article_id) 

    def remove_received_article(self, article_id):
        try:
             new_deque = deque(a_id for a_id in self.received_articles if a_id != article_id)
             self.received_articles = new_deque
        except ValueError:
             pass 

    def get_received_articles_list(self):
        return list(self.received_articles)

    def query_received_articles_list(self):
         count = min(len(self.received_articles), 5)
         return [self.received_articles[i] for i in range(count)]

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
        self.persons = {} 
        self.accounts = {} 
        self.articles = set() # Global set of all existing article_ids in the Network
        self.article_contributors = {} # Global map: article_id -> original_contributor_person_id

        self.exception_counts = {
            "anf": {"total": 0, "ids": defaultdict(int)}, "epi": {"total": 0, "ids": defaultdict(int)},
            "er": {"total": 0, "ids": defaultdict(int)}, "eti": {"total": 0, "ids": defaultdict(int)},
            "pinf": {"total": 0, "ids": defaultdict(int)}, "rnf": {"total": 0, "ids": defaultdict(int)},
            "tinf": {"total": 0, "ids": defaultdict(int)}, "pnf": {"total": 0, "ids": defaultdict(int)},
            "eoai": {"total": 0, "ids": defaultdict(int)}, "oainf": {"total": 0, "ids": defaultdict(int)},
            "doapd": {"total": 0, "ids": defaultdict(int)}, "eai": {"total": 0, "ids": defaultdict(int)},
            "ainf": {"total": 0, "ids": defaultdict(int)}, "cpd": {"total": 0, "ids": defaultdict(int)},
            "dapd": {"total": 0, "ids": defaultdict(int)},
        }
        self.er_static_count = 0
        self.pnf_static_count = 0
        self.cpd_static_count = 0
        self.dapd_static_count = 0
        self.doapd_static_count = 0
        self.triple_sum_count = 0

    def _record_exception(self, exc_type, id1, id2=None):
        if exc_type == "er": self.er_static_count += 1
        elif exc_type == "pnf": self.pnf_static_count += 1
        elif exc_type == "cpd": self.cpd_static_count += 1
        elif exc_type == "dapd": self.dapd_static_count += 1
        elif exc_type == "doapd": self.doapd_static_count += 1

        if exc_type != "rnf":
            self.exception_counts[exc_type]["total"] += 1

        fmt_id1, fmt_id2 = id1, id2
        if exc_type in ("er", "rnf", "pnf", "cpd", "dapd", "doapd") and id2 is not None and id1 > id2:
             fmt_id1, fmt_id2 = id2, id1

        self.exception_counts[exc_type]["ids"][fmt_id1] += 1
        if id2 is not None:
            if fmt_id1 != fmt_id2:
                 self.exception_counts[exc_type]["ids"][fmt_id2] += 1
            if exc_type == "rnf":
                 self.exception_counts[exc_type]["total"] += 2 
                 if fmt_id1 == fmt_id2:
                      self.exception_counts[exc_type]["ids"][fmt_id2] += 1


    def _format_exception(self, exc_type, id1, id2=None):
        fmt_id1, fmt_id2 = id1, id2
        if exc_type in ("er", "rnf", "pnf", "cpd", "dapd", "doapd") and id2 is not None and id1 > id2:
             fmt_id1, fmt_id2 = id2, id1

        id1_count = self.exception_counts[exc_type]["ids"].get(fmt_id1, 0)
        id2_count = self.exception_counts[exc_type]["ids"].get(fmt_id2, 0) if id2 is not None else 0
        total_count = self.exception_counts[exc_type]["total"]

        if exc_type == "anf": return f"anf-{total_count}, {fmt_id1}-{id1_count}"
        elif exc_type == "epi": return f"epi-{total_count}, {id1}-{id1_count}" 
        elif exc_type == "er": return f"er-{self.er_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "eti": return f"eti-{total_count}, {id1}-{id1_count}" 
        elif exc_type == "pinf": return f"pinf-{total_count}, {id1}-{id1_count}" 
        elif exc_type == "rnf":
            total_print_count = total_count // 2 
            return f"rnf-{total_print_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "tinf": return f"tinf-{total_count}, {id1}-{id1_count}" 
        elif exc_type == "pnf": return f"pnf-{self.pnf_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "eoai": return f"eoai-{total_count}, {id1}-{id1_count}" 
        elif exc_type == "oainf": return f"oainf-{total_count}, {id1}-{id1_count}"
        elif exc_type == "doapd": return f"doapd-{self.doapd_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "eai": return f"eai-{total_count}, {id1}-{id1_count}" 
        elif exc_type == "ainf": return f"ainf-{total_count}, {id1}-{id1_count}" 
        elif exc_type == "cpd": return f"cpd-{self.cpd_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "dapd": return f"dapd-{self.dapd_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        else: return "CHECKER_ERROR: Unknown exception type"

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
            if id1 != id2: # Only add to triple_sum if distinct persons and new relation
                neighbors1 = person1.get_neighbor_ids(); neighbors2 = person2.get_neighbor_ids()
                common_neighbors = neighbors1.intersection(neighbors2)
                self.triple_sum_count += len(common_neighbors)
            person1.add_link(id2, value); person2.add_link(id1, value) # JML implies add_link handles id1==id2 correctly (no effect on actual links)
            return "Ok"

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
            else: 
                # Before removing link, update triple_sum_count
                neighbors1 = person1.get_neighbor_ids(); neighbors2 = person2.get_neighbor_ids()
                # Common neighbors exclude person1 and person2 themselves if they were part of it.
                # The intersection gives common third parties.
                common_neighbors = (neighbors1 - {id2}).intersection(neighbors2 - {id1}) # More precise calculation of common nodes for triples
                self.triple_sum_count -= len(common_neighbors)

                person1.remove_link(id2); person2.remove_link(id1)
                for tag in list(person1.tags.values()): 
                    if tag.has_person(id2): tag.del_person(id2) # JML implies del if has
                for tag in list(person2.tags.values()):
                    if tag.has_person(id1): tag.del_person(id1)
            return "Ok"

    def query_value(self, id1, id2):
        if not self.contains_person(id1): self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
        if not self.contains_person(id2): self._record_exception("pinf", id2); return self._format_exception("pinf", id2)
        person1 = self.get_person(id1)
        if id1 != id2 and not person1.is_linked(id2): # JML implies queryValue for non-linked distinct persons is an error condition covered by RNF
            self._record_exception("rnf", id1, id2); return self._format_exception("rnf", id1, id2)
        return str(person1.query_value(id2)) # query_value in PersonSimulator handles id1==id2

    def is_circle(self, id1, id2):
         if not self.contains_person(id1): self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
         if not self.contains_person(id2): self._record_exception("pinf", id2); return self._format_exception("pinf", id2)
         if id1 == id2: return "true" 
         
         queue = deque([id1]); visited = {id1}
         while queue:
             current_id = queue.popleft()
             current_person = self.get_person(current_id)
             if current_person: # Should always be true if ID in self.persons
                 for neighbor_id in current_person.acquaintance.keys():
                     if neighbor_id == id2: return "true" 
                     if neighbor_id not in visited:
                         visited.add(neighbor_id); queue.append(neighbor_id)
         return "false"

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
        if person_id1 == person_id2: self._record_exception("epi", person_id1); return self._format_exception("epi", person_id1) # JML indicates epi for id1==id2
        
        person1 = self.get_person(person_id1); person2 = self.get_person(person_id2) # person1 is to be added, person2 owns the tag
        
        if not person2.is_linked(person_id1): self._record_exception("rnf", person_id1, person_id2); return self._format_exception("rnf", person_id1, person_id2)
        if not person2.contains_tag(tag_id): self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
        
        tag = person2.get_tag(tag_id)
        if tag.has_person(person_id1): self._record_exception("epi", person_id1); return self._format_exception("epi", person_id1) # JML indicates epi if person already in tag
        
        if tag.get_size() < 1000: 
             tag.add_person(person_id1)
        return "Ok" # JML implies Ok even if not added due to size limit

    def query_tag_value_sum(self, person_id, tag_id):
        if not self.contains_person(person_id): self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        if not person.contains_tag(tag_id): self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
        
        tag = person.get_tag(tag_id)
        person_ids_in_tag = tag.get_person_ids() 
        value_sum = 0
        for i in range(len(person_ids_in_tag)):
            p1_id = person_ids_in_tag[i]
            p1 = self.get_person(p1_id)
            if not p1: continue 
            for j in range(len(person_ids_in_tag)): 
                p2_id = person_ids_in_tag[j]
                value_sum += p1.query_value(p2_id) 
        return str(value_sum)

    def query_tag_age_var(self, person_id, tag_id):
        if not self.contains_person(person_id): self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        if not person.contains_tag(tag_id): self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
        
        tag = person.get_tag(tag_id)
        person_ids_in_tag = tag.get_person_ids() 
        ages = []
        for pid in person_ids_in_tag: 
            p_obj = self.get_person(pid)
            if p_obj: ages.append(p_obj.age)
        age_var = calculate_age_var(ages) 
        return str(age_var)

    def del_person_from_tag(self, person_id1, person_id2, tag_id):
        if not self.contains_person(person_id1): self._record_exception("pinf", person_id1); return self._format_exception("pinf", person_id1)
        if not self.contains_person(person_id2): self._record_exception("pinf", person_id2); return self._format_exception("pinf", person_id2)
        
        person2 = self.get_person(person_id2)
        if not person2.contains_tag(tag_id): self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
        
        tag = person2.get_tag(tag_id)
        if not tag.has_person(person_id1): 
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
        
        max_val = -float('inf')
        for _, val in acquaintances:
            if val > max_val:
                max_val = val
        
        best_id = float('inf')
        for acq_id, val in acquaintances:
             if val == max_val: 
                 best_id = min(best_id, acq_id)
        return str(int(best_id))

    def query_couple_sum(self):
        count = 0
        person_ids = list(self.persons.keys()) 
        best_acquaintances_map = {}
        for pid in person_ids:
            person = self.get_person(pid)
            if not person or not person.acquaintance:
                best_acquaintances_map[pid] = None
                continue
            
            acquaintances = person.get_acquaintance_ids_and_values()
            if not acquaintances:
                best_acquaintances_map[pid] = None
                continue

            max_val = -float('inf')
            for _, val_acq in acquaintances: max_val = max(max_val, val_acq)
            
            current_best_id = float('inf')
            for acq_id, val_acq in acquaintances:
                if val_acq == max_val: current_best_id = min(current_best_id, acq_id)
            
            best_acquaintances_map[pid] = int(current_best_id) if current_best_id != float('inf') else None

        for i in range(len(person_ids)):
            id1 = person_ids[i]
            qba_id1 = best_acquaintances_map.get(id1)
            if qba_id1 is None: continue

            for j in range(i + 1, len(person_ids)):
                id2 = person_ids[j]
                qba_id2 = best_acquaintances_map.get(id2)
                if qba_id2 is None: continue

                if qba_id1 == id2 and qba_id2 == id1:
                    count += 1
        return str(count)

    def query_shortest_path(self, id1, id2):
        if not self.contains_person(id1): self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
        if not self.contains_person(id2): self._record_exception("pinf", id2); return self._format_exception("pinf", id2)
        if id1 == id2: return "0" 

        queue = deque([(id1, 0)]) 
        visited = {id1}
        while queue:
            current_id, distance = queue.popleft()
            if current_id == id2:
                return str(distance) 

            current_person = self.get_person(current_id)
            if current_person:
                for neighbor_id in current_person.acquaintance.keys():
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        queue.append((neighbor_id, distance + 1))
        
        self._record_exception("pnf", id1, id2); return self._format_exception("pnf", id1, id2)

    def contains_account(self, account_id):
        return account_id in self.accounts

    def get_account(self, account_id):
        return self.accounts.get(account_id)

    def contains_article(self, article_id):
        return article_id in self.articles

    def create_official_account(self, person_id, account_id, name):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        if self.contains_account(account_id):
            self._record_exception("eoai", account_id); return self._format_exception("eoai", account_id)

        new_account = OfficialAccountSimulator(account_id, person_id, name)
        self.accounts[account_id] = new_account
        new_account.add_follower(person_id)
        return "Ok"

    def delete_official_account(self, person_id, account_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        if not self.contains_account(account_id):
            self._record_exception("oainf", account_id); return self._format_exception("oainf", account_id)

        account = self.get_account(account_id)
        if account.owner_id != person_id:
            self._record_exception("doapd", person_id, account_id); return self._format_exception("doapd", person_id, account_id)
        
        del self.accounts[account_id]
        return "Ok"

    def contribute_article(self, person_id, account_id, article_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        if not self.contains_account(account_id):
            self._record_exception("oainf", account_id); return self._format_exception("oainf", account_id)
        
        if self.contains_article(article_id): 
            self._record_exception("eai", article_id); return self._format_exception("eai", article_id)

        account = self.get_account(account_id)
        if not account.contains_follower(person_id):
            self._record_exception("cpd", person_id, article_id); return self._format_exception("cpd", person_id, article_id) 

        self.articles.add(article_id)
        self.article_contributors[article_id] = person_id
        account.add_article(person_id, article_id) 

        current_follower_ids = list(account.followers.keys()) 
        for follower_id in current_follower_ids:
            follower_person = self.get_person(follower_id)
            if follower_person:
                follower_person.add_received_article(article_id) 
            else:
                 print(f"CHECKER WARNING: Follower {follower_id} not found when distributing article {article_id}", file=sys.stderr)
        return "Ok"

    def delete_article(self, person_id, account_id, article_id):
         if not self.contains_person(person_id):
             self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
         if not self.contains_account(account_id):
             self._record_exception("oainf", account_id); return self._format_exception("oainf", account_id)

         account = self.get_account(account_id)
         if not account.contains_article(article_id): 
             self._record_exception("ainf", article_id); return self._format_exception("ainf", article_id)
         
         if account.owner_id != person_id:
             self._record_exception("dapd", person_id, article_id); return self._format_exception("dapd", person_id, article_id)

         original_contributor_id = self.article_contributors.get(article_id)
         if original_contributor_id is None:
              print(f"CHECKER CRITICAL WARNING: Article {article_id} is in account {account_id} but no global contributor record found. State inconsistent.", file=sys.stderr)
         account.remove_article(article_id, original_contributor_id)
         current_follower_ids = list(account.followers.keys()) 
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
        if account.contains_follower(person_id):
            self._record_exception("epi", person_id); return self._format_exception("epi", person_id)

        account.add_follower(person_id)
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
        articles_list = person.query_received_articles_list() 

        if not articles_list:
            return "None"
        else:
            return " ".join(map(str, articles_list))


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
        expected_output = "Checker_Error: Command not implemented" 

        if cmd in ("ln", "load_network", "lnl", "load_network_local"):
             load_expected_output_str = "Ok"; load_actual_output_str = None 
             if output_idx >= len(output_lines): result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": load_expected_output_str, "actual": None, "reason": f"Missing output for {cmd}"}); break
             load_actual_output_str = output_lines[output_idx]; output_idx += 1
             if len(parts) < 2: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output_str, "reason": f"Malformed {cmd} command"}); break
             n_str = parts[1]; n = parse_int(n_str)
             if n is None or n < 0: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output_str, "reason": f"Invalid count '{n_str}' in {cmd}"}); break

             num_data_lines_for_load = 0
             if n > 0:
                 num_relation_lines = n - 1 
                 num_data_lines_for_load = 3 + num_relation_lines 

             source_lines_for_sim = []; source_idx_offset_for_sim = 0; load_file_error_flag = False 
             
             if cmd in ("lnl", "load_network_local"):
                  if len(parts) < 3: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output_str, "reason": f"Missing filename for {cmd}"}); break
                  filename = parts[2]
                  try:
                       with open(filename, 'r', encoding='utf-8') as f_load: source_lines_for_sim = [line.strip() for line in f_load if line.strip()]
                       if n > 0 and len(source_lines_for_sim) < num_data_lines_for_load: 
                           result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output_str, "reason": f"File {filename} insufficient data (expected {num_data_lines_for_load} lines, got {len(source_lines_for_sim)})"}); break
                  except FileNotFoundError: load_file_error_flag = True; load_expected_output_str = "File not found"
                  except Exception as e: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Error reading load file {filename}: {e}"}); break
             else: 
                  if n > 0:
                      if (input_idx + num_data_lines_for_load > len(input_lines)):
                          result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Insufficient lines in stdin for {cmd} {n} (expected {num_data_lines_for_load}, available {len(input_lines) - input_idx})"}); break
                      source_lines_for_sim = input_lines
                      source_idx_offset_for_sim = input_idx
                      input_idx += num_data_lines_for_load 

             if load_actual_output_str != load_expected_output_str: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": load_expected_output_str, "actual": load_actual_output_str, "reason": "Output mismatch for load command"}); break
             if load_file_error_flag: continue 
             if n == 0: continue 

             try:
                  ids_line = source_lines_for_sim[source_idx_offset_for_sim].split()
                  names_line = source_lines_for_sim[source_idx_offset_for_sim + 1].split()
                  ages_line = source_lines_for_sim[source_idx_offset_for_sim + 2].split()
                  
                  if not (len(ids_line) == n and len(names_line) == n and len(ages_line) == n): raise ValueError("Mismatched counts in header lines")
                  ids = [parse_int(id_s) for id_s in ids_line]; names = names_line; ages = [parse_int(age_s) for age_s in ages_line]
                  if None in ids or None in ages: raise ValueError("Parse error IDs/Ages")
                  
                  for i in range(n):
                        sim_res = network.add_person(ids[i], names[i], ages[i]) 
                        if sim_res != "Ok": raise ValueError(f"Load Error: Failed adding person {ids[i]}: {sim_res}")

                  current_data_line_idx_in_source = source_idx_offset_for_sim + 3
                  
                  for line_k_idx in range(n - 1): 
                        if current_data_line_idx_in_source >= len(source_lines_for_sim): 
                            raise ValueError(f"Missing relation data: line block index {line_k_idx}")
                        
                        value_str_list = source_lines_for_sim[current_data_line_idx_in_source].split()
                        current_data_line_idx_in_source += 1

                        expected_num_values = line_k_idx + 1
                        if len(value_str_list) != expected_num_values:
                            raise ValueError(
                                f"Incorrect number of values on relation line block index {line_k_idx} "
                                f"(expected {expected_num_values}, got {len(value_str_list)})"
                            )

                        person1_actual_id = ids[line_k_idx + 1]

                        for val_idx_on_line in range(expected_num_values): 
                            person2_actual_id = ids[val_idx_on_line]
                            
                            value = parse_int(value_str_list[val_idx_on_line])
                            if value is None:
                                raise ValueError(
                                    f"Invalid value on relation line block index {line_k_idx}, "
                                    f"value index {val_idx_on_line}"
                                )
                            
                            if value != 0:
                                sim_res = network.add_relation(person1_actual_id, person2_actual_id, value)
                                if sim_res != "Ok":
                                    raise ValueError(
                                        f"Load Error: Failed adding relation {person1_actual_id}-{person2_actual_id}: {sim_res}"
                                    )
             except Exception as e:
                  result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Checker error during load simulation: {type(e).__name__} {e}"}); break
             continue 
        
        actual_output = None
        if output_idx >= len(output_lines): result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": "???", "actual": None, "reason": "Missing output"}); break
        actual_output = output_lines[output_idx]; output_idx += 1

        try:
            if cmd in ("ap", "add_person") and len(parts) >= 4: # 3 args: id, name, age
                id_val, name, age = parse_int(parts[1]), parts[2], parse_int(parts[3])
                if id_val is None or age is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                expected_output = network.add_person(id_val, name, age)
            elif cmd in ("ar", "add_relation") and len(parts) >= 4: # 3 args: id1, id2, value
                id1, id2, val = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                if id1 is None or id2 is None or val is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                expected_output = network.add_relation(id1, id2, val)
            elif cmd in ("mr", "modify_relation") and len(parts) >= 4: # 3 args: id1, id2, value
                 id1, id2, m_val = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                 if id1 is None or id2 is None or m_val is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                 expected_output = network.modify_relation(id1, id2, m_val)
            elif cmd in ("qv", "query_value") and len(parts) >= 3: # 2 args: id1, id2
                id1, id2 = parse_int(parts[1]), parse_int(parts[2])
                if id1 is None or id2 is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                expected_output = network.query_value(id1, id2)
            elif cmd in ("qci", "query_circle") and len(parts) >= 3: # 2 args: id1, id2
                id1, id2 = parse_int(parts[1]), parse_int(parts[2])
                if id1 is None or id2 is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                expected_output = network.is_circle(id1, id2)
            elif cmd in ("qts", "query_triple_sum") and len(parts) >= 1: # 0 args
                expected_output = network.query_triple_sum()
            elif cmd in ("at", "add_tag") and len(parts) >= 3: # 2 args: person_id, tag_id
                 p_id, t_id = parse_int(parts[1]), parse_int(parts[2])
                 if p_id is None or t_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                 expected_output = network.add_tag(p_id, t_id)
            elif cmd in ("att", "add_to_tag") and len(parts) >= 4: # 3 args: id1, id2, tag_id
                 id1, id2, t_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                 if id1 is None or id2 is None or t_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                 expected_output = network.add_person_to_tag(id1, id2, t_id)
            elif cmd in ("qtvs", "query_tag_value_sum") and len(parts) >= 3: # 2 args: person_id, tag_id
                 p_id, t_id = parse_int(parts[1]), parse_int(parts[2])
                 if p_id is None or t_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                 expected_output = network.query_tag_value_sum(p_id, t_id)
            elif cmd in ("qtav", "query_tag_age_var") and len(parts) >= 3: # 2 args: person_id, tag_id
                 p_id, t_id = parse_int(parts[1]), parse_int(parts[2])
                 if p_id is None or t_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                 expected_output = network.query_tag_age_var(p_id, t_id)
            elif cmd in ("dft", "del_from_tag") and len(parts) >= 4: # 3 args: id1, id2, tag_id
                 id1, id2, t_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                 if id1 is None or id2 is None or t_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                 expected_output = network.del_person_from_tag(id1, id2, t_id)
            elif cmd in ("dt", "del_tag") and len(parts) >= 3: # 2 args: person_id, tag_id
                 p_id, t_id = parse_int(parts[1]), parse_int(parts[2])
                 if p_id is None or t_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                 expected_output = network.del_tag(p_id, t_id)
            elif cmd in ("qba", "query_best_acquaintance") and len(parts) >= 2: # 1 arg: id
                id_val = parse_int(parts[1])
                if id_val is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:2]}")
                expected_output = network.query_best_acquaintance(id_val)
            elif cmd in ("qcs", "query_couple_sum") and len(parts) >= 1: # 0 args
                expected_output = network.query_couple_sum()
            elif cmd in ("qsp", "query_shortest_path") and len(parts) >= 3: # 2 args: id1, id2
                id1, id2 = parse_int(parts[1]), parse_int(parts[2])
                if id1 is None or id2 is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                expected_output = network.query_shortest_path(id1, id2)
            elif cmd in ("coa", "create_official_account") and len(parts) >= 4: # 3 args: p_id, acc_id, name_str
                p_id, acc_id, name_str = parse_int(parts[1]), parse_int(parts[2]), parts[3]
                if p_id is None or acc_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}") # Name is string, no parse check
                expected_output = network.create_official_account(p_id, acc_id, name_str)
            elif cmd in ("doa", "delete_official_account") and len(parts) >= 3: # 2 args: p_id, acc_id
                p_id, acc_id = parse_int(parts[1]), parse_int(parts[2])
                if p_id is None or acc_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                expected_output = network.delete_official_account(p_id, acc_id)
            elif cmd in ("ca", "contribute_article") and len(parts) >= 4: # 3 args: p_id, acc_id, art_id (name ignored)
                p_id, acc_id, art_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                if p_id is None or acc_id is None or art_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                expected_output = network.contribute_article(p_id, acc_id, art_id)
            elif cmd in ("da", "delete_article") and len(parts) >= 4: # 3 args: p_id, acc_id, art_id
                p_id, acc_id, art_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                if p_id is None or acc_id is None or art_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                expected_output = network.delete_article(p_id, acc_id, art_id)
            elif cmd in ("foa", "follow_official_account") and len(parts) >= 3: # 2 args: p_id, acc_id
                p_id, acc_id = parse_int(parts[1]), parse_int(parts[2])
                if p_id is None or acc_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                expected_output = network.follow_official_account(p_id, acc_id)
            elif cmd in ("qbc", "query_best_contributor") and len(parts) >= 2: # 1 arg: acc_id
                acc_id = parse_int(parts[1])
                if acc_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:2]}")
                expected_output = network.query_best_contributor(acc_id)
            elif cmd in ("qra", "query_received_articles") and len(parts) >= 2: # 1 arg: p_id
                p_id = parse_int(parts[1])
                if p_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:2]}")
                expected_output = network.query_received_articles(p_id)
            else:
                 raise ValueError(f"Unknown or malformed command: '{cmd_line}'")

        except ValueError as e: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Checker Error: Invalid args/cmd processing: {e}"}); break
        except Exception as e: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Checker Error: Simulation Error: {type(e).__name__} {e}"}); break

        if cmd in ("qra", "query_received_articles"):
             norm_expected = " ".join(expected_output.split())
             norm_actual = " ".join(actual_output.split())
             if norm_actual != norm_expected:
                 result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": norm_expected, "actual": norm_actual, "reason": "Output mismatch"}); break
        elif actual_output != expected_output:
             result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": expected_output, "actual": actual_output, "reason": "Output mismatch"}); break

    if result_status == "Accepted" and output_idx < len(output_lines):
        result_status = "Rejected"; error_details.append({"command_number": command_num + 1, "reason": "Extra output", "actual": output_lines[output_idx]})

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