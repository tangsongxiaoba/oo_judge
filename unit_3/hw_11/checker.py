# -*- coding: utf-8 -*-
import sys
import math
from collections import deque, defaultdict
import json
import abc # For abstract base class

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

# --- Forward Declarations for Type Hinting ---
class PersonSimulator: pass
class TagSimulator: pass

# --- Simulator Classes ---

class TagSimulator:
    def __init__(self, tag_id):
        self.id = tag_id
        self.persons = set() # Set of person_ids

    def add_person(self, person_id):
        self.persons.add(person_id)

    def has_person(self, person_id): # Takes person_id
        return person_id in self.persons

    def has_person_obj(self, person_obj: PersonSimulator): # Takes PersonSimulator object
        return person_obj.id in self.persons

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
        self.followers = {}
        self.articles = set()

    def add_follower(self, person_id):
        if person_id not in self.followers:
             self.followers[person_id] = 0

    def contains_follower(self, person_id): # Takes person_id
        return person_id in self.followers
    
    def contains_follower_obj(self, person_obj: PersonSimulator): # Takes PersonSimulator object
        return person_obj.id in self.followers

    def add_article(self, person_id, article_id):
        if person_id in self.followers:
            self.articles.add(article_id)
            self.followers[person_id] = self.followers.get(person_id, 0) + 1
        else:
             print(f"CHECKER WARNING: OfficialAccountSimulator.add_article called for non-follower {person_id} on account {self.id}", file=sys.stderr)


    def contains_article(self, article_id):
        return article_id in self.articles

    def remove_article(self, article_id, original_contributor_id):
        self.articles.discard(article_id)
        if original_contributor_id in self.followers:
            if self.followers[original_contributor_id] > 0:
                 self.followers[original_contributor_id] -= 1
            else:
                 print(f"CHECKER WARNING: OfficialAccountSimulator.remove_article: Original contributor {original_contributor_id}'s contribution was already non-positive in account {self.id}.", file=sys.stderr)
        else:
             print(f"CHECKER WARNING: OfficialAccountSimulator.remove_article: Original contributor {original_contributor_id} not found in current followers of account {self.id} during contribution decrement.", file=sys.stderr)


    def get_best_contributor(self):
        if not self.followers:
             return 0

        max_contribution = -1
        for contribution in self.followers.values():
            max_contribution = max(max_contribution, contribution)
        
        if max_contribution == -1 and self.followers: # All contributions are 0 or less, find min ID with 0
            min_id_at_zero = float('inf')
            found_zero = False
            for pid, contrib in self.followers.items():
                if contrib == 0:
                    min_id_at_zero = min(min_id_at_zero, pid)
                    found_zero = True
            if found_zero:
                return min_id_at_zero
            else: # No followers or all negative contributions (error state or empty)
                return 0 # Or smallest ID if any follower exists? JML implies 0 if no one with max.
                        # If all are 0, then smallest ID with 0. If all negative, then 0 is correct.


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
        self.acquaintance = {} 
        self.tags = {} # maps tag_id -> TagSimulator object
        self.received_articles = deque()
        self.socialValue = 0
        self.money = 0
        self.messages = deque() # Stores MessageSimulator objects

    def add_received_article(self, article_id):
        self.received_articles.appendleft(article_id)

    def remove_received_article(self, article_id):
        new_deque = deque(a_id for a_id in self.received_articles if a_id != article_id)
        self.received_articles = new_deque

    def get_received_articles_list(self):
        return list(self.received_articles)

    def query_received_articles_list(self):
         count = min(len(self.received_articles), 5)
         return [self.received_articles[i] for i in range(count)]

    def add_message_to_receiver(self, message): # message is MessageSimulator object
        self.messages.appendleft(message)

    def get_messages_list(self):
        return list(self.messages)

    def query_received_messages_list(self):
        count = min(len(self.messages), 5)
        return [self.messages[i] for i in range(count)]

    def addSocialValue(self, num):
        self.socialValue += num

    def getSocialValue(self):
        return self.socialValue

    def addMoney(self, num):
        self.money += num

    def getMoney(self):
        return self.money

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

    def contains_tag(self, tag_id): # Takes tag_id
        return tag_id in self.tags

    def get_tag(self, tag_id): # Takes tag_id, returns TagSimulator object
        return self.tags.get(tag_id)

    def add_tag(self, tag: TagSimulator): # Takes TagSimulator object
        if not self.contains_tag(tag.id):
            self.tags[tag.id] = tag
            return True
        return False

    def del_tag(self, tag_id): # Takes tag_id
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


# --- Message Classes ---

class MessageSimulator(abc.ABC):
    def __init__(self, msg_id: int, # This param is for subclasses to pass specific value (money, emoji_id, article_id, or social_value)
                 person1_obj: PersonSimulator,
                 person2_obj: PersonSimulator = None, tag_obj: TagSimulator = None):
        self.id = msg_id
        self.person1 = person1_obj # Store PersonSimulator object

        self.person2 = None        # For type 0, store PersonSimulator object
        self.tag = None            # For type 1, store TagSimulator object
        self.type = -1

        if person2_obj is not None and tag_obj is not None:
            raise ValueError("Message cannot be both person-to-person and person-to-tag")

        if person2_obj is not None: # Type 0
            self.type = 0
            self.person2 = person2_obj
            if not isinstance(self.person1, PersonSimulator) or not isinstance(self.person2, PersonSimulator):
                 print(f"CHECKER WARNING: Message type 0 created with non-PersonSimulator objects. P1: {type(self.person1)}, P2: {type(self.person2)} for msg {self.id}", file=sys.stderr)
        elif tag_obj is not None: # Type 1
            self.type = 1
            self.tag = tag_obj
            if not isinstance(self.person1, PersonSimulator) or not isinstance(self.tag, TagSimulator):
                 print(f"CHECKER WARNING: Message type 1 created with non-PersonSimulator or non-TagSimulator. P1: {type(self.person1)}, Tag: {type(self.tag)} for msg {self.id}", file=sys.stderr)
        else:
            # This means neither person2_obj nor tag_obj was provided
            raise ValueError(f"Message (id={self.id}) must have either person2_obj or tag_obj")
        
        # Subclasses are responsible for setting/calculating actual socialValue based on JML.

    def get_id(self): return self.id
    
    @abc.abstractmethod
    def get_social_value(self): pass

    def get_type(self): return self.type
    
    def get_person1(self) -> PersonSimulator: return self.person1
    def get_person1_id(self) -> int: return self.person1.id if self.person1 else None # Should always exist

    def get_person2(self) -> PersonSimulator:
        if self.type == 0: return self.person2
        return None 
    
    def get_person2_id(self) -> int:
        if self.type == 0 and self.person2: return self.person2.id
        return None

    def get_tag(self) -> TagSimulator:
        if self.type == 1: return self.tag
        return None

    def get_tag_id(self) -> int:
        if self.type == 1 and self.tag: return self.tag.id
        return None

    def __eq__(self, other):
        if not isinstance(other, MessageSimulator): return NotImplemented
        return self.id == other.id
    def __hash__(self): return hash(self.id)

    @abc.abstractmethod
    def get_output_prefix(self): pass
    @abc.abstractmethod
    def get_output_value(self): pass

class StandardMessageSimulator(MessageSimulator):
    def __init__(self, msg_id: int, social_value: int, person1_obj: PersonSimulator, 
                 person2_obj: PersonSimulator = None, tag_obj: TagSimulator = None):
        super().__init__(msg_id, person1_obj, person2_obj, tag_obj) # Pass person1_obj directly
        self._social_value = social_value # Store the direct social value

    def get_social_value(self): return self._social_value
    def get_output_prefix(self): return "Ordinary message"
    def get_output_value(self): return self.id

class EmojiMessageSimulator(MessageSimulator):
    def __init__(self, msg_id: int, emoji_id: int, person1_obj: PersonSimulator, 
                 person2_obj: PersonSimulator = None, tag_obj: TagSimulator = None):
        super().__init__(msg_id, person1_obj, person2_obj, tag_obj)
        self.emojiId = emoji_id

    def get_social_value(self): return self.emojiId # JML: socialValue == emojiId
    def get_emoji_id(self): return self.emojiId
    def get_output_prefix(self): return "Emoji"
    def get_output_value(self): return self.emojiId

class RedEnvelopeMessageSimulator(MessageSimulator):
    def __init__(self, msg_id: int, money: int, person1_obj: PersonSimulator, 
                 person2_obj: PersonSimulator = None, tag_obj: TagSimulator = None):
        super().__init__(msg_id, person1_obj, person2_obj, tag_obj)
        self.money = money

    def get_social_value(self): return self.money * 5 # JML: socialValue == money * 5
    def get_money(self): return self.money
    def get_output_prefix(self): return "RedEnvelope"
    def get_output_value(self): return self.money

class ForwardMessageSimulator(MessageSimulator):
    def __init__(self, msg_id: int, article_id: int, person1_obj: PersonSimulator, 
                 person2_obj: PersonSimulator = None, tag_obj: TagSimulator = None):
        super().__init__(msg_id, person1_obj, person2_obj, tag_obj)
        self.articleId = article_id

    def get_social_value(self): return abs(self.articleId) % 200 # JML: socialValue == abs(articleId) % 200
    def get_article_id(self): return self.articleId
    def get_output_prefix(self): return "Forward"
    def get_output_value(self): return self.articleId


class NetworkSimulator:
    def __init__(self):
        self.persons = {} 
        self.accounts = {} 
        self.articles = set() 
        self.article_contributors = {}
        self.messages = {} # message_id -> MessageSimulator object
        self.emoji_map = {}

        self.error_counters = {
            "anf":   {"count": 0, "id_counts": defaultdict(int)}, 
            "ainf":  {"count": 0, "id_counts": defaultdict(int)}, 
            "cpd":   {"count": 0, "id_counts": defaultdict(int)}, 
            "dapd":  {"count": 0, "id_counts": defaultdict(int)}, 
            "doapd": {"count": 0, "id_counts": defaultdict(int)},
            "eai":   {"count": 0, "id_counts": defaultdict(int)}, 
            "eei":   {"count": 0, "id_counts": defaultdict(int)}, 
            "emi":   {"count": 0, "id_counts": defaultdict(int)}, 
            "eoai":  {"count": 0, "id_counts": defaultdict(int)},
            "epi":   {"count": 0, "id_counts": defaultdict(int)}, 
            "er":    {"count": 0, "id_counts": defaultdict(int)}, 
            "eti":   {"count": 0, "id_counts": defaultdict(int)}, 
            "einf":  {"count": 0, "id_counts": defaultdict(int)},
            "minf":  {"count": 0, "id_counts": defaultdict(int)},
            "oainf": {"count": 0, "id_counts": defaultdict(int)},
            "pnf":   {"count": 0, "id_counts": defaultdict(int)}, 
            "pinf":  {"count": 0, "id_counts": defaultdict(int)}, 
            "rnf":   {"count": 0, "id_counts": defaultdict(int)}, 
            "tinf":  {"count": 0, "id_counts": defaultdict(int)}, 
        }
        self.er_static_count = 0
        self.pnf_static_count = 0
        self.cpd_static_count = 0
        self.dapd_static_count = 0
        self.doapd_static_count = 0
        self.rnf_total_triggers = 0 
        self.triple_sum_count = 0

    def _record_exception(self, exc_type, id1, id2=None):
        counter = self.error_counters[exc_type]
        if exc_type == "er": self.er_static_count += 1
        elif exc_type == "pnf": self.pnf_static_count += 1
        elif exc_type == "cpd": self.cpd_static_count += 1
        elif exc_type == "dapd": self.dapd_static_count += 1
        elif exc_type == "doapd": self.doapd_static_count += 1
        elif exc_type == "rnf": self.rnf_total_triggers += 1
        counter["count"] += 1
        fmt_id1, fmt_id2 = id1, id2
        if exc_type in ("er", "rnf", "pnf", "cpd", "dapd", "doapd") and id2 is not None and id1 > id2:
             fmt_id1, fmt_id2 = id2, id1
        counter["id_counts"][fmt_id1] += 1
        if id2 is not None and fmt_id1 != fmt_id2:
            counter["id_counts"][fmt_id2] += 1

    def _format_exception(self, exc_type, id1, id2=None):
        counter = self.error_counters[exc_type]
        total_count = counter["count"]
        fmt_id1, fmt_id2 = id1, id2
        if exc_type in ("er", "rnf", "pnf", "cpd", "dapd", "doapd") and id2 is not None and id1 > id2:
             fmt_id1, fmt_id2 = id2, id1
        id1_count = counter["id_counts"].get(fmt_id1, 0)
        id2_count = counter["id_counts"].get(fmt_id2, 0) if id2 is not None else 0

        if exc_type == "anf": return f"anf-{total_count}, {fmt_id1}-{id1_count}"
        elif exc_type == "ainf": return f"ainf-{total_count}, {id1}-{id1_count}"
        elif exc_type == "cpd": return f"cpd-{self.cpd_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "dapd": return f"dapd-{self.dapd_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "doapd": return f"doapd-{self.doapd_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "eai": return f"eai-{total_count}, {id1}-{id1_count}"
        elif exc_type == "eei": return f"eei-{total_count}, {id1}-{id1_count}"
        elif exc_type == "emi": return f"emi-{total_count}, {id1}-{id1_count}"
        elif exc_type == "eoai": return f"eoai-{total_count}, {id1}-{id1_count}"
        elif exc_type == "epi": return f"epi-{total_count}, {id1}-{id1_count}"
        elif exc_type == "er": return f"er-{self.er_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "eti": return f"eti-{total_count}, {id1}-{id1_count}"
        elif exc_type == "einf": return f"einf-{total_count}, {id1}-{id1_count}"
        elif exc_type == "minf": return f"minf-{total_count}, {id1}-{id1_count}"
        elif exc_type == "oainf": return f"oainf-{total_count}, {id1}-{id1_count}"
        elif exc_type == "pnf": return f"pnf-{self.pnf_static_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "pinf": return f"pinf-{total_count}, {id1}-{id1_count}"
        elif exc_type == "rnf":
             rnf_print_count = self.rnf_total_triggers 
             return f"rnf-{rnf_print_count}, {fmt_id1}-{id1_count}, {fmt_id2}-{id2_count}"
        elif exc_type == "tinf": return f"tinf-{total_count}, {id1}-{id1_count}"
        else: return "CHECKER_ERROR: Unknown exception type"

    def contains_person(self, person_id):
        return person_id in self.persons
    def get_person(self, person_id) -> PersonSimulator: # Returns PersonSimulator object
        return self.persons.get(person_id)

    def add_person(self, person_id, name, age): # Corresponds to addPerson(PersonInterface person)
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
            person1.add_link(id2, value)
            if id1 != id2: 
                person2.add_link(id1, value)
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
                neighbors1 = person1.get_neighbor_ids(); neighbors2 = person2.get_neighbor_ids()
                common_neighbors = (neighbors1 - {id2}).intersection(neighbors2 - {id1})
                self.triple_sum_count -= len(common_neighbors)
                person1.remove_link(id2); person2.remove_link(id1)
                for tag in list(person1.tags.values()): # Iterate over copy if modifying
                    if tag.has_person(id2): tag.del_person(id2)
                for tag in list(person2.tags.values()): # Iterate over copy
                    if tag.has_person(id1): tag.del_person(id1)
            return "Ok"

    def query_value(self, id1, id2):
        if not self.contains_person(id1): self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
        if not self.contains_person(id2): self._record_exception("pinf", id2); return self._format_exception("pinf", id2)
        person1 = self.get_person(id1)
        if id1 != id2 and not person1.is_linked(id2): # JML check before queryValue
            self._record_exception("rnf", id1, id2); return self._format_exception("rnf", id1, id2)
        return str(person1.query_value(id2))

    def is_circle(self, id1, id2):
         if not self.contains_person(id1): self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
         if not self.contains_person(id2): self._record_exception("pinf", id2); return self._format_exception("pinf", id2)
         if id1 == id2: return "true" 
         queue = deque([id1]); visited = {id1}
         while queue:
             current_id = queue.popleft()
             current_person = self.get_person(current_id)
             if not current_person: continue
             for neighbor_id in current_person.acquaintance.keys():
                 if neighbor_id == id2: return "true"
                 if neighbor_id not in visited:
                     if self.contains_person(neighbor_id):
                         visited.add(neighbor_id); queue.append(neighbor_id)
         return "false"

    def query_triple_sum(self):
        return str(self.triple_sum_count)

    def add_tag(self, person_id, tag_id): # Corresponds to addTag(int personId, TagInterface tag)
        if not self.contains_person(person_id): self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        if person.contains_tag(tag_id): # Check if tag with this ID already exists for this person
             self._record_exception("eti", tag_id); return self._format_exception("eti", tag_id)
        else:
            new_tag = TagSimulator(tag_id) # Create new tag object
            person.add_tag(new_tag) # Add the TagSimulator object to person
            return "Ok"

    def add_person_to_tag(self, person_id1, person_id2, tag_id):
        if not self.contains_person(person_id1): self._record_exception("pinf", person_id1); return self._format_exception("pinf", person_id1)
        if not self.contains_person(person_id2): self._record_exception("pinf", person_id2); return self._format_exception("pinf", person_id2)
        if person_id1 == person_id2: self._record_exception("epi", person_id1); return self._format_exception("epi", person_id1)
        person1 = self.get_person(person_id1); person2 = self.get_person(person_id2)
        if not person2.is_linked(person_id1):
            self._record_exception("rnf", person_id1, person_id2); return self._format_exception("rnf", person_id1, person_id2)
        if not person2.contains_tag(tag_id):
            self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
        tag = person2.get_tag(tag_id) # Get TagSimulator object
        if tag.has_person(person_id1): # Check if person1_id is already in the tag
            self._record_exception("epi", person_id1); return self._format_exception("epi", person_id1)
        if tag.get_size() < 1000:
             tag.add_person(person_id1) # Add person1_id to tag
        return "Ok"

    def query_tag_value_sum(self, person_id, tag_id):
        if not self.contains_person(person_id): self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        if not person.contains_tag(tag_id): self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
        tag = person.get_tag(tag_id)
        person_ids_in_tag = tag.get_person_ids()
        value_sum = 0
        for i in range(len(person_ids_in_tag)):
            p1_id_in_tag = person_ids_in_tag[i]
            p1_in_tag = self.get_person(p1_id_in_tag)
            if not p1_in_tag: continue
            for j in range(len(person_ids_in_tag)):
                p2_id_in_tag = person_ids_in_tag[j]
                value_sum += p1_in_tag.query_value(p2_id_in_tag)
        return str(value_sum)

    def query_tag_age_var(self, person_id, tag_id):
        if not self.contains_person(person_id): self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        if not person.contains_tag(tag_id): self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
        tag = person.get_tag(tag_id)
        person_ids_in_tag = tag.get_person_ids()
        ages = []
        for pid_in_tag in person_ids_in_tag:
            p_obj = self.get_person(pid_in_tag)
            if p_obj: ages.append(p_obj.age)
        return str(calculate_age_var(ages))

    def del_person_from_tag(self, person_id1, person_id2, tag_id):
        if not self.contains_person(person_id1): self._record_exception("pinf", person_id1); return self._format_exception("pinf", person_id1)
        if not self.contains_person(person_id2): self._record_exception("pinf", person_id2); return self._format_exception("pinf", person_id2)
        person2 = self.get_person(person_id2)
        if not person2.contains_tag(tag_id):
            self._record_exception("tinf", tag_id); return self._format_exception("tinf", tag_id)
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
        if not acquaintances:
            self._record_exception("anf", person_id); return self._format_exception("anf", person_id)
        max_val = -float('inf')
        for _, val in acquaintances: max_val = max(max_val, val)
        best_id = float('inf')
        for acq_id, val in acquaintances:
             if val == max_val: best_id = min(best_id, acq_id)
        return str(int(best_id)) if best_id != float('inf') else "CHECKER_ERROR_QBA"


    def query_couple_sum(self):
        count = 0
        person_ids = list(self.persons.keys())
        best_acquaintances_map = {}
        for pid in person_ids:
            person = self.get_person(pid)
            if not person: continue
            acquaintances = person.get_acquaintance_ids_and_values()
            if not acquaintances: best_acquaintances_map[pid] = None; continue
            max_val = -float('inf')
            for _, val_acq in acquaintances: max_val = max(max_val, val_acq)
            current_best_id = float('inf')
            has_max_val_acq = False
            for acq_id, val_acq in acquaintances:
                if val_acq == max_val: current_best_id = min(current_best_id, acq_id); has_max_val_acq = True
            best_acquaintances_map[pid] = int(current_best_id) if has_max_val_acq else None
        
        processed_pairs = set()
        for id1_val in person_ids:
            qba_id1 = best_acquaintances_map.get(id1_val)
            if qba_id1 is None: continue
            id2_val = qba_id1
            if id2_val not in best_acquaintances_map: continue
            qba_id2 = best_acquaintances_map.get(id2_val)
            if qba_id2 is None: continue
            pair = tuple(sorted((id1_val, id2_val)))
            if qba_id2 == id1_val and id1_val != id2_val and pair not in processed_pairs : # Ensure not self-couple and distinct pair
                 count += 1
                 processed_pairs.add(pair)
        return str(count)

    def query_shortest_path(self, id1, id2):
        if not self.contains_person(id1): self._record_exception("pinf", id1); return self._format_exception("pinf", id1)
        if not self.contains_person(id2): self._record_exception("pinf", id2); return self._format_exception("pinf", id2)
        if id1 == id2: return "0"
        queue = deque([(id1, 0)]); visited = {id1}
        while queue:
            current_id, distance = queue.popleft()
            if current_id == id2: return str(distance)
            current_person = self.get_person(current_id)
            if current_person:
                for neighbor_id in current_person.acquaintance.keys():
                    if neighbor_id not in visited and self.contains_person(neighbor_id):
                        visited.add(neighbor_id); queue.append((neighbor_id, distance + 1))
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
        person_obj = self.get_person(person_id) # Need Person object for containsFollower_obj
        if not account.contains_follower_obj(person_obj): # JML uses getPerson(personId)
            self._record_exception("cpd", person_id, article_id); return self._format_exception("cpd", person_id, article_id)
        
        self.articles.add(article_id)
        self.article_contributors[article_id] = person_id
        account.add_article(person_id, article_id)
        current_follower_ids = list(account.followers.keys())
        for follower_id in current_follower_ids:
            follower_person = self.get_person(follower_id)
            if follower_person: follower_person.add_received_article(article_id)
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
              print(f"CHECKER CRITICAL WARNING: Article {article_id} in account {account_id} but no global contributor. State inconsistent.", file=sys.stderr)
              original_contributor_id = -1 
         account.remove_article(article_id, original_contributor_id)
         current_follower_ids = list(account.followers.keys())
         for follower_id in current_follower_ids:
             follower_person = self.get_person(follower_id)
             if follower_person: follower_person.remove_received_article(article_id)
         return "Ok"

    def follow_official_account(self, person_id, account_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        if not self.contains_account(account_id):
            self._record_exception("oainf", account_id); return self._format_exception("oainf", account_id)
        account = self.get_account(account_id)
        person_obj = self.get_person(person_id) # Need Person object for containsFollower_obj
        if account.contains_follower_obj(person_obj): # JML uses getPerson(personId)
            self._record_exception("epi", person_id); return self._format_exception("epi", person_id)
        account.add_follower(person_id)
        return "Ok"

    def query_best_contributor(self, account_id):
        if not self.contains_account(account_id):
            self._record_exception("oainf", account_id); return self._format_exception("oainf", account_id)
        account = self.get_account(account_id)
        return str(account.get_best_contributor())

    def query_received_articles(self, person_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        articles_list = person.query_received_articles_list()
        return "None" if not articles_list else " ".join(map(str, articles_list))

    def containsMessage(self, msg_id): return msg_id in self.messages
    def getMessage(self, msg_id) -> MessageSimulator: return self.messages.get(msg_id)
    def containsEmojiId(self, emoji_id): return emoji_id in self.emoji_map

    def addMessage(self, message: MessageSimulator): # message is a fully formed MessageSimulator object
        msg_id = message.get_id()
        if self.containsMessage(msg_id):
            self._record_exception("emi", msg_id); return self._format_exception("emi", msg_id)

        person1_obj = message.get_person1() # This is a PersonSimulator object
        if not person1_obj: # Should be prevented by run_checker's simulation of Runner
            print(f"CHECKER CRITICAL: Network.addMessage received message {msg_id} with person1=None.", file=sys.stderr)
            # This is an internal error state. JML assumes person1 is non_null.
            # For robustness, could throw an error or return an internal error string.
            # However, following JML, this path shouldn't be reachable if run_checker is correct.
            # To avoid NonePointers if it does happen:
            return "CHECKER_ERROR: Message had null person1"


        if isinstance(message, EmojiMessageSimulator):
            emoji_id = message.get_emoji_id()
            if not self.containsEmojiId(emoji_id):
                self._record_exception("einf", emoji_id); return self._format_exception("einf", emoji_id)

        if isinstance(message, ForwardMessageSimulator):
             article_id = message.get_article_id()
             # JML: message.getPerson1().getReceivedArticles.contains(...)
             # person1_obj is message.getPerson1()
             if not self.contains_article(article_id): # Global check
                  self._record_exception("ainf", article_id); return self._format_exception("ainf", article_id)
             # Ensure person1_obj is not None before accessing its list
             if not person1_obj.get_received_articles_list().__contains__(article_id):
                 self._record_exception("ainf", article_id); return self._format_exception("ainf", article_id)

        if message.get_type() == 0:
            person2_obj = message.get_person2() # This is a PersonSimulator object
            if not person2_obj: # Should be prevented by run_checker
                print(f"CHECKER CRITICAL: Network.addMessage received type 0 message {msg_id} with person2=None.", file=sys.stderr)
                return "CHECKER_ERROR: Message had null person2 for type 0"

            if person1_obj.id == person2_obj.id: # JML: !message.getPerson1().equals(message.getPerson2())
                self._record_exception("epi", person1_obj.id); return self._format_exception("epi", person1_obj.id)
        
        self.messages[msg_id] = message
        return "Ok"

    def sendMessage(self, msg_id: int):
        if not self.containsMessage(msg_id):
            self._record_exception("minf", msg_id); return self._format_exception("minf", msg_id)

        message = self.getMessage(msg_id) # MessageSimulator object
        sender_obj = message.get_person1() # PersonSimulator object from the message

        # This check should ideally be redundant if message construction is always valid
        if not sender_obj: 
            print(f"CHECKER CRITICAL: sendMessage for msg_id {msg_id} found message with no sender.", file=sys.stderr)
            # This indicates an internal inconsistency.
            self._record_exception("minf", msg_id) # Or a custom checker error.
            return self._format_exception("minf", msg_id)


        social_value_change = message.get_social_value()

        if message.get_type() == 0: # Person-to-person
            receiver_obj = message.get_person2() # PersonSimulator object from the message
            if not receiver_obj:
                print(f"CHECKER CRITICAL: sendMessage for type 0 msg_id {msg_id} found message with no receiver.", file=sys.stderr)
                self._record_exception("minf", msg_id)
                return self._format_exception("minf", msg_id)

            if not sender_obj.is_linked(receiver_obj.id):
                self._record_exception("rnf", sender_obj.id, receiver_obj.id)
                return self._format_exception("rnf", sender_obj.id, receiver_obj.id)

            sender_obj.addSocialValue(social_value_change)
            receiver_obj.addSocialValue(social_value_change)

            if isinstance(message, RedEnvelopeMessageSimulator):
                money = message.get_money()
                sender_obj.addMoney(-money); receiver_obj.addMoney(money)
            if isinstance(message, ForwardMessageSimulator):
                receiver_obj.add_received_article(message.get_article_id())
            if isinstance(message, EmojiMessageSimulator):
                emoji_id = message.get_emoji_id()
                if self.containsEmojiId(emoji_id): self.emoji_map[emoji_id] += 1
            
            receiver_obj.add_message_to_receiver(message)

        elif message.get_type() == 1: # Person-to-tag
            tag_obj_in_message = message.get_tag() # TagSimulator object stored in the message
            if not tag_obj_in_message:
                print(f"CHECKER CRITICAL: sendMessage for type 1 msg_id {msg_id} found message with no tag.", file=sys.stderr)
                self._record_exception("minf", msg_id)
                return self._format_exception("minf", msg_id)

            # JML: !sender_obj.containsTag(message.getTag().getId()) -> TINF
            if not sender_obj.contains_tag(tag_obj_in_message.id):
                self._record_exception("tinf", tag_obj_in_message.id)
                return self._format_exception("tinf", tag_obj_in_message.id)

            sender_obj.addSocialValue(social_value_change)
            
            # Use members of the tag_obj_in_message
            tag_members_ids = tag_obj_in_message.get_person_ids()
            num_members = tag_obj_in_message.get_size() # Use size of the tag stored in message

            money_per_member = 0
            if isinstance(message, RedEnvelopeMessageSimulator) and num_members > 0:
                total_money = message.get_money()
                money_per_member = total_money // num_members
                sender_obj.addMoney(-(money_per_member * num_members)) # Use actual num_members for deduction

            for member_id in tag_members_ids:
                member_sim_obj = self.get_person(member_id)
                if member_sim_obj:
                    member_sim_obj.addSocialValue(social_value_change)
                    if isinstance(message, RedEnvelopeMessageSimulator) and num_members > 0:
                         member_sim_obj.addMoney(money_per_member)
                    if isinstance(message, ForwardMessageSimulator):
                         member_sim_obj.add_received_article(message.get_article_id())
                    member_sim_obj.add_message_to_receiver(message)

            if isinstance(message, EmojiMessageSimulator):
                 emoji_id = message.get_emoji_id()
                 if self.containsEmojiId(emoji_id): self.emoji_map[emoji_id] += 1
        
        del self.messages[msg_id]
        return "Ok"

    def querySocialValue(self, person_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        return str(self.get_person(person_id).getSocialValue())

    def queryReceivedMessages(self, person_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        person = self.get_person(person_id)
        messages_list = person.query_received_messages_list()
        if not messages_list: return "None"
        output_parts = [f"{msg.get_output_prefix()}: {msg.get_output_value()}" for msg in messages_list]
        return "; ".join(output_parts)

    def storeEmojiId(self, emoji_id):
        if self.containsEmojiId(emoji_id):
            self._record_exception("eei", emoji_id); return self._format_exception("eei", emoji_id)
        self.emoji_map[emoji_id] = 0
        return "Ok"

    def queryMoney(self, person_id):
        if not self.contains_person(person_id):
            self._record_exception("pinf", person_id); return self._format_exception("pinf", person_id)
        return str(self.get_person(person_id).getMoney())

    def queryPopularity(self, emoji_id):
        if not self.containsEmojiId(emoji_id):
            self._record_exception("einf", emoji_id); return self._format_exception("einf", emoji_id)
        return str(self.emoji_map.get(emoji_id, 0))

    def deleteColdEmoji(self, limit):
        deleted_emoji_ids = {eid for eid, heat in self.emoji_map.items() if heat < limit}
        self.emoji_map = {eid: heat for eid, heat in self.emoji_map.items() if heat >= limit}
        
        messages_to_delete = [
            msg_id for msg_id, message in self.messages.items()
            if isinstance(message, EmojiMessageSimulator) and message.get_emoji_id() in deleted_emoji_ids
        ]
        for msg_id in messages_to_delete: del self.messages[msg_id]
        return str(len(self.emoji_map))

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
        cmd_line = input_lines[input_idx]; input_idx += 1
        parts = cmd_line.split();
        if not parts: continue
        cmd = parts[0]
        expected_output = "Checker_Error: Command not implemented or invalid args"

        # --- Load Network Handling (Simplified for brevity, assume it's correct) ---
        if cmd in ("ln", "load_network", "lnl", "load_network_local"):
            # ... (load network logic as before, it doesn't involve new message classes)
            # For brevity, I'm omitting the full load_network block here but it should be retained from the original.
            # It correctly calls network.add_person and network.add_relation.
             load_expected_output_str = "Ok"; load_actual_output_str = None
             if output_idx >= len(output_lines): result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": load_expected_output_str, "actual": None, "reason": f"Missing output for {cmd}"}); break
             load_actual_output_str = output_lines[output_idx]; output_idx += 1
             if len(parts) < 2: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output_str, "reason": f"Malformed {cmd} command"}); break
             n_str = parts[1]; n = parse_int(n_str)
             if n is None or n < 0: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output_str, "reason": f"Invalid count '{n_str}' in {cmd}"}); break
             num_data_lines_for_load = 0
             if n > 0: num_data_lines_for_load = 3 + (n - 1)
             source_lines_for_sim = []; source_idx_offset_for_sim = 0; load_file_error_flag = False
             if cmd in ("lnl", "load_network_local"):
                  if len(parts) < 3: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output_str, "reason": f"Missing filename for {cmd}"}); break
                  filename = parts[2]
                  try:
                       with open(filename, 'r', encoding='utf-8') as f_load: source_lines_for_sim = [line.strip() for line in f_load if line.strip()]
                       if n > 0 and len(source_lines_for_sim) < num_data_lines_for_load: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": None, "actual": load_actual_output_str, "reason": f"File {filename} insufficient data"}); break
                  except FileNotFoundError: load_file_error_flag = True; load_expected_output_str = "File not found"
                  except Exception as e: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Error reading load file {filename}: {e}"}); break
             else:
                  if n > 0:
                      if (input_idx + num_data_lines_for_load > len(input_lines)): result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Insufficient lines in stdin for {cmd} {n}"}); break
                      source_lines_for_sim = input_lines; source_idx_offset_for_sim = input_idx; input_idx += num_data_lines_for_load
             if load_actual_output_str != load_expected_output_str: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": load_expected_output_str, "actual": load_actual_output_str, "reason": "Output mismatch for load command"}); break
             if load_file_error_flag or n == 0: continue
             try:
                  ids_line = source_lines_for_sim[source_idx_offset_for_sim].split(); names_line = source_lines_for_sim[source_idx_offset_for_sim + 1].split(); ages_line = source_lines_for_sim[source_idx_offset_for_sim + 2].split()
                  if not (len(ids_line) == n and len(names_line) == n and len(ages_line) == n): raise ValueError("Mismatched counts in header lines for load")
                  ids = [parse_int(id_s) for id_s in ids_line]; names = names_line; ages = [parse_int(age_s) for age_s in ages_line]
                  if None in ids or None in ages: raise ValueError("Parse error IDs/Ages for load")
                  for i in range(n):
                        sim_res = network.add_person(ids[i], names[i], ages[i])
                        if sim_res != "Ok": raise ValueError(f"Load Error: Failed adding person {ids[i]}: {sim_res}")
                  current_data_line_idx_in_source = source_idx_offset_for_sim + 3
                  for line_k_idx in range(n - 1):
                        if current_data_line_idx_in_source >= len(source_lines_for_sim): raise ValueError(f"Missing relation data: line block index {line_k_idx}")
                        value_str_list = source_lines_for_sim[current_data_line_idx_in_source].split(); current_data_line_idx_in_source += 1
                        expected_num_values = line_k_idx + 1
                        if len(value_str_list) != expected_num_values: raise ValueError(f"Incorrect number of values on relation line block {line_k_idx}")
                        person1_actual_id = ids[line_k_idx + 1]
                        for val_idx_on_line in range(expected_num_values):
                            person2_actual_id = ids[val_idx_on_line]; value = parse_int(value_str_list[val_idx_on_line])
                            if value is None: raise ValueError(f"Invalid value on relation line block {line_k_idx}, value index {val_idx_on_line}")
                            if value != 0:
                                sim_res = network.add_relation(person1_actual_id, person2_actual_id, value)
                                if sim_res != "Ok": raise ValueError(f"Load Error: Failed adding relation {person1_actual_id}-{person2_actual_id}: {sim_res}")
             except Exception as e: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Checker error during load simulation: {type(e).__name__} {e}"}); break
             continue


        actual_output = None
        if output_idx >= len(output_lines): result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": "???", "actual": None, "reason": "Missing output"}); break
        actual_output = output_lines[output_idx]; output_idx += 1

        try:
            if cmd in ("ap", "add_person") and len(parts) >= 4:
                id_val, name, age = parse_int(parts[1]), parts[2], parse_int(parts[3])
                if id_val is None or age is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                expected_output = network.add_person(id_val, name, age)
            elif cmd in ("ar", "add_relation") and len(parts) >= 4:
                id1, id2, val = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                if id1 is None or id2 is None or val is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                expected_output = network.add_relation(id1, id2, val)
            elif cmd in ("mr", "modify_relation") and len(parts) >= 4:
                 id1, id2, m_val = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                 if id1 is None or id2 is None or m_val is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                 expected_output = network.modify_relation(id1, id2, m_val)
            elif cmd in ("qv", "query_value") and len(parts) >= 3:
                id1, id2 = parse_int(parts[1]), parse_int(parts[2])
                if id1 is None or id2 is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                expected_output = network.query_value(id1, id2)
            elif cmd in ("qci", "query_circle") and len(parts) >= 3:
                id1, id2 = parse_int(parts[1]), parse_int(parts[2])
                if id1 is None or id2 is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                expected_output = network.is_circle(id1, id2)
            elif cmd in ("qts", "query_triple_sum") and len(parts) >= 1:
                expected_output = network.query_triple_sum()
            elif cmd in ("at", "add_tag") and len(parts) >= 3:
                 p_id, t_id = parse_int(parts[1]), parse_int(parts[2])
                 if p_id is None or t_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                 expected_output = network.add_tag(p_id, t_id)
            elif cmd in ("att", "add_to_tag") and len(parts) >= 4:
                 id1, id2, t_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                 if id1 is None or id2 is None or t_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                 expected_output = network.add_person_to_tag(id1, id2, t_id)
            elif cmd in ("qtvs", "query_tag_value_sum") and len(parts) >= 3:
                 p_id, t_id = parse_int(parts[1]), parse_int(parts[2])
                 if p_id is None or t_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                 expected_output = network.query_tag_value_sum(p_id, t_id)
            elif cmd in ("qtav", "query_tag_age_var") and len(parts) >= 3:
                 p_id, t_id = parse_int(parts[1]), parse_int(parts[2])
                 if p_id is None or t_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                 expected_output = network.query_tag_age_var(p_id, t_id)
            elif cmd in ("dft", "del_from_tag") and len(parts) >= 4:
                 id1, id2, t_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                 if id1 is None or id2 is None or t_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                 expected_output = network.del_person_from_tag(id1, id2, t_id)
            elif cmd in ("dt", "del_tag") and len(parts) >= 3:
                 p_id, t_id = parse_int(parts[1]), parse_int(parts[2])
                 if p_id is None or t_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                 expected_output = network.del_tag(p_id, t_id)
            elif cmd in ("qba", "query_best_acquaintance") and len(parts) >= 2:
                id_val = parse_int(parts[1])
                if id_val is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:2]}")
                expected_output = network.query_best_acquaintance(id_val)
            elif cmd in ("qcs", "query_couple_sum") and len(parts) >= 1:
                expected_output = network.query_couple_sum()
            elif cmd in ("qsp", "query_shortest_path") and len(parts) >= 3:
                id1, id2 = parse_int(parts[1]), parse_int(parts[2])
                if id1 is None or id2 is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                expected_output = network.query_shortest_path(id1, id2)
            elif cmd in ("coa", "create_official_account") and len(parts) >= 4:
                p_id, acc_id, name_str = parse_int(parts[1]), parse_int(parts[2]), parts[3]
                if p_id is None or acc_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                expected_output = network.create_official_account(p_id, acc_id, name_str)
            elif cmd in ("doa", "delete_official_account") and len(parts) >= 3:
                p_id, acc_id = parse_int(parts[1]), parse_int(parts[2])
                if p_id is None or acc_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                expected_output = network.delete_official_account(p_id, acc_id)
            elif cmd in ("ca", "contribute_article") and len(parts) >= 4: # Name (parts[4]) ignored
                p_id, acc_id, art_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                if p_id is None or acc_id is None or art_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                expected_output = network.contribute_article(p_id, acc_id, art_id)
            elif cmd in ("da", "delete_article") and len(parts) >= 4:
                p_id, acc_id, art_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
                if p_id is None or acc_id is None or art_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:4]}")
                expected_output = network.delete_article(p_id, acc_id, art_id)
            elif cmd in ("foa", "follow_official_account") and len(parts) >= 3:
                p_id, acc_id = parse_int(parts[1]), parse_int(parts[2])
                if p_id is None or acc_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:3]}")
                expected_output = network.follow_official_account(p_id, acc_id)
            elif cmd in ("qbc", "query_best_contributor") and len(parts) >= 2:
                acc_id = parse_int(parts[1])
                if acc_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:2]}")
                expected_output = network.query_best_contributor(acc_id)
            elif cmd in ("qra", "query_received_articles") and len(parts) >= 2:
                p_id = parse_int(parts[1])
                if p_id is None: raise ValueError(f"Bad arguments for {cmd}: {parts[1:2]}")
                expected_output = network.query_received_articles(p_id)
            
            # --- HW11 Commands ---
            # Refactored add message commands to mimic Runner.java pre-checks
            elif cmd in ("am", "add_message") or \
                 cmd in ("aem", "add_emoji_message") or \
                 cmd in ("arem", "add_red_envelope_message") or \
                 cmd in ("afm", "add_forward_message"):
                
                if cmd == "am" and len(parts) >= 6: # msg_id, social_val, type, p1_id, p2_id|tag_id
                    msg_id_val, val1, type_val, p1_id_val, target_id_val = (parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3]), parse_int(parts[4]), parse_int(parts[5]))
                    if None in [msg_id_val, val1, type_val, p1_id_val, target_id_val]: raise ValueError(f"Bad arguments for {cmd}")
                    msg_constructor = StandardMessageSimulator
                elif cmd == "aem" and len(parts) >= 6: # msg_id, emoji_id, type, p1_id, p2_id|tag_id
                    msg_id_val, val1, type_val, p1_id_val, target_id_val = (parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3]), parse_int(parts[4]), parse_int(parts[5]))
                    if None in [msg_id_val, val1, type_val, p1_id_val, target_id_val]: raise ValueError(f"Bad arguments for {cmd}")
                    msg_constructor = EmojiMessageSimulator
                elif cmd == "arem" and len(parts) >= 6: # msg_id, money, type, p1_id, p2_id|tag_id
                    msg_id_val, val1, type_val, p1_id_val, target_id_val = (parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3]), parse_int(parts[4]), parse_int(parts[5]))
                    if None in [msg_id_val, val1, type_val, p1_id_val, target_id_val]: raise ValueError(f"Bad arguments for {cmd}")
                    msg_constructor = RedEnvelopeMessageSimulator
                elif cmd == "afm" and len(parts) >= 6: # msg_id, article_id, type, p1_id, p2_id|tag_id
                    msg_id_val, val1, type_val, p1_id_val, target_id_val = (parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3]), parse_int(parts[4]), parse_int(parts[5]))
                    if None in [msg_id_val, val1, type_val, p1_id_val, target_id_val]: raise ValueError(f"Bad arguments for {cmd}")
                    msg_constructor = ForwardMessageSimulator
                else:
                    raise ValueError(f"Malformed add_message variant: {cmd_line}")

                p1_obj = network.get_person(p1_id_val)
                if not p1_obj:
                    expected_output = "The person with this number does not exist"
                else:
                    message_to_add = None
                    if type_val == 0: # Person-to-person
                        p2_obj = network.get_person(target_id_val)
                        if not p2_obj:
                            expected_output = "The person with this number does not exist"
                        else:
                            message_to_add = msg_constructor(msg_id_val, val1, p1_obj, person2_obj=p2_obj)
                    elif type_val == 1: # Person-to-tag
                        tag_obj_for_msg = p1_obj.get_tag(target_id_val) # target_id_val is tag_id
                        if not tag_obj_for_msg:
                            expected_output = "Tag does not exist"
                        else:
                            message_to_add = msg_constructor(msg_id_val, val1, p1_obj, tag_obj=tag_obj_for_msg)
                    else:
                        raise ValueError(f"Invalid type {type_val} for {cmd}")
                    
                    if message_to_add: # If construction was successful (no pre-check failed)
                        expected_output = network.addMessage(message_to_add)
                    # If expected_output is still the default error, it means a pre-check failed and was set.

            elif cmd in ("sm", "send_message") and len(parts) >= 2:
                 msg_id = parse_int(parts[1])
                 if msg_id is None: raise ValueError(f"Bad arguments for {cmd}")
                 expected_output = network.sendMessage(msg_id)
            elif cmd in ("qsv", "query_social_value") and len(parts) >= 2:
                 p_id = parse_int(parts[1])
                 if p_id is None: raise ValueError(f"Bad arguments for {cmd}")
                 expected_output = network.querySocialValue(p_id)
            elif cmd in ("qrm", "query_received_messages") and len(parts) >= 2:
                 p_id = parse_int(parts[1])
                 if p_id is None: raise ValueError(f"Bad arguments for {cmd}")
                 expected_output = network.queryReceivedMessages(p_id)
            elif cmd in ("sei", "store_emoji_id") and len(parts) >= 2:
                 emoji_id = parse_int(parts[1])
                 if emoji_id is None: raise ValueError(f"Bad arguments for {cmd}")
                 expected_output = network.storeEmojiId(emoji_id)
            elif cmd in ("qp", "query_popularity") and len(parts) >= 2:
                 emoji_id = parse_int(parts[1])
                 if emoji_id is None: raise ValueError(f"Bad arguments for {cmd}")
                 expected_output = network.queryPopularity(emoji_id)
            elif cmd in ("dce", "delete_cold_emoji") and len(parts) >= 2:
                 limit = parse_int(parts[1])
                 if limit is None: raise ValueError(f"Bad arguments for {cmd}")
                 expected_output = network.deleteColdEmoji(limit)
            elif cmd in ("qm", "query_money") and len(parts) >= 2:
                 p_id = parse_int(parts[1])
                 if p_id is None: raise ValueError(f"Bad arguments for {cmd}")
                 expected_output = network.queryMoney(p_id)
            else:
                 raise ValueError(f"Unknown or malformed command: '{cmd_line}'")

        except ValueError as e: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Checker Error: Invalid args/cmd processing: {e}"}); break
        except Exception as e: result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "reason": f"Checker Error: Simulation Error: {type(e).__name__} {e}"}); import traceback; traceback.print_exc(); break


        if cmd in ("qra", "query_received_articles", "qrm", "query_received_messages"):
             norm_expected = " ".join(expected_output.split()) if expected_output else ""
             norm_actual = " ".join(actual_output.split()) if actual_output else ""
             # For qrm, ";" might make simple space join problematic. Let's do direct compare.
             if cmd == "qrm":
                 if actual_output != expected_output:
                     result_status = "Rejected"; error_details.append({"command_number": command_num, "command": cmd_line, "expected": expected_output, "actual": actual_output, "reason": "Output mismatch"}); break
             elif norm_actual != norm_expected : # For qra
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