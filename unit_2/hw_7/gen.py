# --- START OF FILE gen.py ---

# --- START OF MODIFIED gen.py (HW7 - Granular Timing V3 - SCHE Control & Bursts + UPDATE->SCHE Ban + Independent Random ID Seed) ---
import random
import argparse
import sys
import time
import math
import re # Import regex module for easier ID replacement
from collections import defaultdict

# --- Constants based on the problem description ---
ALL_FLOORS = ['B4', 'B3', 'B2', 'B1', 'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7']
FLOOR_MAP = {name: i for i, name in enumerate(ALL_FLOORS)}
NUM_FLOORS = len(ALL_FLOORS)
NUM_ELEVATORS = 6
ALL_ELEVATOR_IDS = list(range(1, NUM_ELEVATORS + 1))
MIN_PRIORITY = 1
MAX_PRIORITY = 100
MID_PRIORITY = (MIN_PRIORITY + MAX_PRIORITY) // 2
SCHE_TARGET_FLOORS = ['B2', 'B1', 'F1', 'F2', 'F3', 'F4', 'F5']
SCHE_SPEEDS = [0.2, 0.3, 0.4, 0.5]
UPDATE_TARGET_FLOORS = ['B2', 'B1', 'F1', 'F2', 'F3', 'F4', 'F5'] # Same as SCHE for target
MAX_RANDOM_PASSENGER_ID = 2_000_000

# --- Timing & Interval Constants ---
UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL = 8
SCHE_SAME_ELEVATOR_MIN_INTERVAL = 8

# --- Default Generation Parameters ---
DEFAULT_NUM_PASSENGERS = 15
DEFAULT_NUM_SCHE = 3
DEFAULT_NUM_UPDATE = 1
DEFAULT_MAX_TIME = 50.0
DEFAULT_MIN_INTERVAL_PASS = 0.0
DEFAULT_MAX_INTERVAL_PASS = 1.4
DEFAULT_START_TIME = 1.0
DEFAULT_PRIORITY_MIDDLE_RANGE = 20
DEFAULT_UPDATE_TIME_LIMIT_RATIO = 0.6
DEFAULT_SCHE_ELEVATORS = ",".join(map(str, ALL_ELEVATOR_IDS))
DEFAULT_ALLOW_SCHE_UPDATE_OVERLAP = True
DEFAULT_USE_RANDOM_ID = False

# --- Hu Ce (Mutual Testing) Specific Constraints ---
HUCE_MAX_DIRECTIVES = 70
HUCE_MAX_TIME = 50.0
HUCE_MIN_START_TIME = 1.0

# --- Helper Functions (Unchanged) ---
def get_timestamp_from_string(request_str):
    try:
        end_bracket_index = request_str.find(']')
        if end_bracket_index == -1: return -1.0
        timestamp_str = request_str[1:end_bracket_index]
        return float(timestamp_str)
    except (ValueError, IndexError):
        return -1.0

def floor_name_to_index(floor_name):
    return FLOOR_MAP.get(floor_name, -1)

def index_to_floor_name(index):
    if 0 <= index < len(ALL_FLOORS):
        return ALL_FLOORS[index]
    return None

# --- Request Generation Functions (Unchanged internally) ---
# generate_passenger_request still expects sequential ID during main run
def generate_passenger_request(passenger_id, current_time, floors,
                               extreme_floor_ratio=0.0,
                               priority_bias='none', priority_bias_ratio=0.0,
                               priority_middle_range=DEFAULT_PRIORITY_MIDDLE_RANGE):
    priority = -1; apply_bias = random.random() < priority_bias_ratio
    if apply_bias and priority_bias != 'none':
        if priority_bias == 'extremes': priority = random.choice([MIN_PRIORITY, MAX_PRIORITY])
        elif priority_bias == 'middle':
            half_range = priority_middle_range // 2; lower_bound = max(MIN_PRIORITY, MID_PRIORITY - half_range); upper_bound = min(MAX_PRIORITY, MID_PRIORITY + half_range)
            if lower_bound > upper_bound: lower_bound = upper_bound = MID_PRIORITY
            priority = random.randint(lower_bound, upper_bound)
    if priority == -1: priority = random.randint(MIN_PRIORITY, MAX_PRIORITY)
    start_floor, end_floor = None, None
    if random.random() < extreme_floor_ratio:
        extreme_floors = [floors[0], floors[-1]]; start_floor = random.choice(extreme_floors); end_floor = extreme_floors[1] if start_floor == extreme_floors[0] else extreme_floors[0]
    else:
        while True:
            start_floor = random.choice(floors); end_floor = random.choice(floors);
            if start_floor != end_floor:
                break
    formatted_time = round(current_time, 1)
    return f"[{formatted_time:.1f}]{passenger_id}-PRI-{priority}-FROM-{start_floor}-TO-{end_floor}"

def generate_sche_request(current_time, elevator_id, target_floors, speeds):
    speed = random.choice(speeds); target_floor = random.choice(target_floors); formatted_time = round(current_time, 1)
    return f"[{formatted_time:.1f}]SCHE-{elevator_id}-{speed}-{target_floor}"

def generate_update_request(current_time, elevator_id_a, elevator_id_b, target_floor):
    formatted_time = round(current_time, 1)
    return f"[{formatted_time:.1f}]UPDATE-{elevator_id_a}-{elevator_id_b}-{target_floor}"

# --- Helper for Timestamp Generation (Unchanged) ---
def _generate_target_timestamps(num_events, start_time, max_time,
                               burst_size=0, burst_time=None,
                               min_interval=0.0, max_interval=1.0):
    # (Function unchanged)
    timestamps = []
    if num_events <= 0: return timestamps
    current_time = start_time
    absolute_max_time = max_time
    time_span = absolute_max_time - start_time
    if time_span < 0: time_span = 0
    actual_burst_time = -1.0
    burst_insert_index = -1
    num_regular_events = num_events
    if burst_size > 0 and num_events >= burst_size:
        num_regular_events = num_events - burst_size
        if burst_time is not None: actual_burst_time = max(start_time, min(burst_time, absolute_max_time))
        elif time_span > 1e-9: actual_burst_time = start_time + time_span / 2.0
        else: actual_burst_time = start_time
        burst_ratio = (actual_burst_time - start_time) / time_span if time_span > 1e-9 else 0.0
        burst_insert_index = math.ceil(burst_ratio * num_regular_events)
        burst_insert_index = max(0, min(burst_insert_index, num_regular_events))
    elif burst_size > 0:
        print(f"INFO: Burst size ({burst_size}) > num events ({num_events}). Treating all as burst.", file=sys.stderr)
        burst_size = num_events; num_regular_events = 0
        actual_burst_time = burst_time if burst_time is not None else start_time + time_span / 2.0
        actual_burst_time = max(start_time, min(actual_burst_time, absolute_max_time))
        burst_insert_index = 0
    generated_regular_count = 0; burst_added = False
    avg_interval = time_span / num_events if num_events > 1 else 0.0
    max_interval = max(max_interval, avg_interval * 1.5)
    min_interval = min(min_interval, avg_interval * 0.5)
    for i in range(num_events):
        is_burst_event_this_iter = False
        if burst_size > 0 and not burst_added and generated_regular_count == burst_insert_index:
            burst_gen_time = max(current_time, min(actual_burst_time, absolute_max_time))
            for _ in range(burst_size): timestamps.append(burst_gen_time)
            current_time = burst_gen_time; burst_added = True; is_burst_event_this_iter = True
        if generated_regular_count < num_regular_events:
            if i > 0 or is_burst_event_this_iter:
                 interval = random.uniform(min_interval, max_interval)
                 current_time += interval
            request_time = max(start_time, min(current_time, absolute_max_time))
            timestamps.append(request_time)
            generated_regular_count += 1; current_time = request_time
            if current_time >= absolute_max_time: break
        elif burst_added and generated_regular_count >= num_regular_events: break
    while len(timestamps) < num_events:
        last_time = timestamps[-1] if timestamps else start_time
        next_time = min(absolute_max_time, last_time + random.uniform(min_interval, max_interval))
        timestamps.append(next_time)
    return sorted(timestamps[:num_events])


# --- Main Data Generation Logic ---
def generate_data(num_passengers, num_sche, num_update, max_time,
                  min_interval_pass, max_interval_pass, start_time,
                  sche_target_elevators=ALL_ELEVATOR_IDS,
                  allow_sche_update_overlap=DEFAULT_ALLOW_SCHE_UPDATE_OVERLAP,
                  sche_burst_size=0, sche_burst_time=None,
                  update_burst_size=0, update_burst_time=None,
                  huce_mode=False, seed=None,
                  force_start_passengers=0, force_end_passengers=0,
                  pass_burst_size=0, pass_burst_time=None,
                  extreme_floor_ratio=0.0,
                  priority_bias='none', priority_bias_ratio=0.0,
                  priority_middle_range=DEFAULT_PRIORITY_MIDDLE_RANGE,
                  update_time_limit_ratio=DEFAULT_UPDATE_TIME_LIMIT_RATIO,
                  use_random_ids=DEFAULT_USE_RANDOM_ID,
                  # --- New parameter for the independent ID seed ---
                  random_id_seed=None
                  ):
    """
    Generates interleaved elevator directives. Main generation uses 'seed'.
    If use_random_ids is True, passenger IDs are replaced post-processing
    using the 'random_id_seed' (or current time if None).
    CORE RULE: An elevator involved in UPDATE can *never* be used in SCHE afterwards.
    """

    # --- Seeding for Main Generation ---
    # This controls timestamps, priorities, SCHE/UPDATE choices etc.
    if seed is not None: print(f"INFO: Using MAIN random seed: {seed}", file=sys.stderr); random.seed(seed)
    else: current_seed = int(time.time() * 1000); print(f"INFO: Using generated MAIN random seed: {current_seed}", file=sys.stderr); random.seed(current_seed)

    # State Trackers
    last_sche_time_per_elevator = defaultdict(lambda: -float('inf'))
    last_update_time_per_elevator = defaultdict(lambda: -float('inf'))
    updated_elevators = set()
    sche_assigned_elevators_count = defaultdict(int)
    last_passenger_id = 0 # Always used internally first

    # Pre-generation Validation & Info (minor updates)
    if num_passengers < 0 or num_sche < 0 or num_update < 0: print("CRITICAL ERROR: Counts cannot be negative.", file=sys.stderr); return None
    if num_passengers == 0 and num_sche == 0 and num_update == 0: print("CRITICAL ERROR: Must request at least one directive.", file=sys.stderr); return None
    print(f"INFO: Passenger ID Mode during generation: Always Sequential (1, 2, ...)", file=sys.stderr)
    if use_random_ids:
        id_seed_info = f"provided seed {random_id_seed}" if random_id_seed is not None else "current timestamp (default)"
        print(f"INFO: Random IDs will be applied via post-processing using: {id_seed_info}.", file=sys.stderr)
    # ... (rest of pre-generation info unchanged) ...
    print(f"INFO: Eligible elevators for SCHE (initially): {sorted(sche_target_elevators)}", file=sys.stderr)
    print(f"INFO: Hard Rule: Elevators in UPDATE are permanently banned from future SCHE.", file=sys.stderr)
    print(f"INFO: Allow SCHE -> UPDATE overlap (if not HCE): {allow_sche_update_overlap}", file=sys.stderr)
    if huce_mode:
        print(f"--- Hu Ce Mode Activated ---", file=sys.stderr)
        if start_time < HUCE_MIN_START_TIME: print(f"WARNING (HuCe): start_time {start_time:.1f} adjusted to {HUCE_MIN_START_TIME:.1f}.", file=sys.stderr); start_time = HUCE_MIN_START_TIME
        if max_time > HUCE_MAX_TIME: print(f"WARNING (HuCe): max_time {max_time:.1f} adjusted to {HUCE_MAX_TIME:.1f}.", file=sys.stderr); max_time = HUCE_MAX_TIME
        if allow_sche_update_overlap:
             print("INFO (HuCe): HuCe mode implicitly disallows SCHE/UPDATE overlap. Setting allow_sche_update_overlap=False.", file=sys.stderr)
        allow_sche_update_overlap = False
        if len(sche_target_elevators) < num_sche:
             print(f"WARNING (HuCe): Requested SCHE ({num_sche}) > eligible elevators ({len(sche_target_elevators)}). Adjusting SCHE count to {len(sche_target_elevators)}.", file=sys.stderr)
             num_sche = len(sche_target_elevators)
        print(f"INFO (HuCe): Generating {num_passengers+num_sche+num_update} directives (P:{num_passengers}, S:{num_sche}, U:{num_update}). Time: [{start_time:.1f}, {max_time:.1f}].", file=sys.stderr)
        print(f"INFO (HuCe): Constraints: Max 1 SCHE/eligible elevator, Max 1 UPDATE involvement/elevator, No SCHE/UPDATE overlap (enforced).", file=sys.stderr)
        print(f"-----------------------------", file=sys.stderr)

    absolute_max_time = max_time
    total_duration = absolute_max_time - start_time
    if total_duration < 0: total_duration = 0
    effective_ratio = max(0.0, min(1.0, update_time_limit_ratio))
    update_max_time = start_time + total_duration * effective_ratio
    update_max_time = max(start_time, update_max_time)
    if effective_ratio < 1.0: print(f"INFO: Attempting to place UPDATEs before target time limit: {update_max_time:.1f}", file=sys.stderr)

    # --- Helper Function for getting next *SEQUENTIAL* passenger ID ---
    def get_next_sequential_passenger_id():
        nonlocal last_passenger_id
        last_passenger_id += 1
        return last_passenger_id

    # --- 1. Generate Passenger Requests (Uses MAIN seed via global random) ---
    # (Code unchanged from previous version - uses sequential IDs)
    passenger_requests = []
    current_time_pass = start_time
    if num_passengers > 0:
        if force_start_passengers > 0:
            for _ in range(force_start_passengers):
                current_passenger_id = get_next_sequential_passenger_id()
                req_str = generate_passenger_request(current_passenger_id, start_time, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range)
                passenger_requests.append(req_str)
            current_time_pass = start_time
        num_middle_passengers = num_passengers - force_start_passengers - force_end_passengers
        burst_added = False; actual_burst_time_pass = -1.0; burst_insert_index_pass = -1
        if pass_burst_size > 0 and num_middle_passengers >= pass_burst_size:
            time_span_middle = absolute_max_time - current_time_pass; time_span_middle = max(0.1, time_span_middle)
            if pass_burst_time is not None: actual_burst_time_pass = max(current_time_pass, min(pass_burst_time, absolute_max_time))
            else: actual_burst_time_pass = current_time_pass + time_span_middle / 2.0
            actual_burst_time_pass = max(current_time_pass, min(actual_burst_time_pass, absolute_max_time))
            burst_ratio_pass = (actual_burst_time_pass - current_time_pass) / time_span_middle if time_span_middle > 1e-9 else 0.0; relevant_middle_count_pass = max(0, num_middle_passengers - pass_burst_size)
            burst_insert_index_pass = math.ceil(burst_ratio_pass * relevant_middle_count_pass); burst_insert_index_pass = max(0, min(burst_insert_index_pass, relevant_middle_count_pass))
        elif pass_burst_size > 0: print(f"INFO: Not enough 'middle' passengers ({num_middle_passengers}) for burst {pass_burst_size}. Ignored.", file=sys.stderr); pass_burst_size = 0
        middle_req_generated_count = 0
        if num_middle_passengers > 0 or pass_burst_size > 0:
             regular_middle_target = num_middle_passengers; total_middle_iterations = num_middle_passengers + pass_burst_size
             for i in range(total_middle_iterations):
                 is_burst_req_generated_this_iteration = False
                 if pass_burst_size > 0 and not burst_added and middle_req_generated_count == burst_insert_index_pass:
                     burst_gen_time = max(current_time_pass, min(actual_burst_time_pass, absolute_max_time))
                     for _ in range(pass_burst_size):
                         current_passenger_id = get_next_sequential_passenger_id()
                         req_str = generate_passenger_request(current_passenger_id, burst_gen_time, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range)
                         passenger_requests.append(req_str)
                     current_time_pass = burst_gen_time; burst_added = True; is_burst_req_generated_this_iteration = True
                 if middle_req_generated_count < regular_middle_target:
                     if middle_req_generated_count > 0 or force_start_passengers > 0 or is_burst_req_generated_this_iteration:
                         interval = random.uniform(min_interval_pass, max_interval_pass); current_time_pass += interval
                     request_time_pass = max(start_time, min(current_time_pass, absolute_max_time))
                     current_passenger_id = get_next_sequential_passenger_id()
                     req_str = generate_passenger_request(current_passenger_id, request_time_pass, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range)
                     passenger_requests.append(req_str)
                     middle_req_generated_count += 1; current_time_pass = request_time_pass
                     if current_time_pass >= absolute_max_time: break
                 elif burst_added and middle_req_generated_count >= regular_middle_target: break
        if force_end_passengers > 0:
            actual_end_time = max(current_time_pass, absolute_max_time); actual_end_time = min(actual_end_time, absolute_max_time)
            for _ in range(force_end_passengers):
                current_passenger_id = get_next_sequential_passenger_id()
                req_str = generate_passenger_request(current_passenger_id, actual_end_time, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range)
                passenger_requests.append(req_str)

    # --- 2. Generate Target Timestamps for SCHE/UPDATE (Uses MAIN seed via global random) ---
    # (Code unchanged)
    sche_target_timestamps = _generate_target_timestamps(num_sche, start_time, absolute_max_time, sche_burst_size, sche_burst_time, 0.1, 2.0)
    update_target_timestamps = _generate_target_timestamps(num_update, start_time, update_max_time, update_burst_size, update_burst_time, 0.1, 2.0)

    # --- 3. Combine Targets and Place SCHE/UPDATE (Uses MAIN seed via global random) ---
    # (Code unchanged)
    all_target_events = [(ts, 'SCHE') for ts in sche_target_timestamps] + [(ts, 'UPDATE') for ts in update_target_timestamps]
    all_target_events.sort(key=lambda x: x[0])
    generated_sche_requests = []; generated_update_requests = []
    sche_placed_count = 0; update_placed_count = 0
    for target_time, event_type in all_target_events:
        placement_time = -1.0; best_effort_time = target_time
        if event_type == 'SCHE' and sche_placed_count < num_sche:
            # ... (SCHE placement logic unchanged, uses global random.*) ...
            found_sche = False
            current_sche_candidates = [eid for eid in sche_target_elevators if eid not in updated_elevators]
            random.shuffle(current_sche_candidates)
            min_valid_time_for_any = float('inf'); best_elevator_for_min_time = -1
            for elevator_id in current_sche_candidates:
                 if huce_mode and sche_assigned_elevators_count[elevator_id] >= 1: continue
                 earliest_possible = best_effort_time
                 earliest_possible = max(earliest_possible, last_sche_time_per_elevator[elevator_id] + SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                 earliest_possible = max(earliest_possible, last_update_time_per_elevator[elevator_id] + UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                 if earliest_possible < min_valid_time_for_any and earliest_possible <= absolute_max_time + 1e-9:
                     min_valid_time_for_any = earliest_possible; best_elevator_for_min_time = elevator_id
            if best_elevator_for_min_time != -1:
                possible_placements = []
                for elevator_id in current_sche_candidates:
                    if huce_mode and sche_assigned_elevators_count[elevator_id] >= 1: continue
                    earliest_possible = best_effort_time
                    earliest_possible = max(earliest_possible, last_sche_time_per_elevator[elevator_id] + SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                    earliest_possible = max(earliest_possible, last_update_time_per_elevator[elevator_id] + UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                    if abs(earliest_possible - min_valid_time_for_any) < 1e-9 and earliest_possible <= absolute_max_time + 1e-9:
                         possible_placements.append((earliest_possible, elevator_id))
                if possible_placements:
                     placement_time, assigned_elevator_id = random.choice(possible_placements)
                     final_event_time = round(placement_time, 1)
                     req_str = generate_sche_request(final_event_time, assigned_elevator_id, SCHE_TARGET_FLOORS, SCHE_SPEEDS)
                     generated_sche_requests.append(req_str)
                     last_sche_time_per_elevator[assigned_elevator_id] = placement_time
                     sche_assigned_elevators_count[assigned_elevator_id] += 1
                     sche_placed_count += 1; found_sche = True
        elif event_type == 'UPDATE' and update_placed_count < num_update:
            # ... (UPDATE placement logic unchanged, uses global random.*) ...
             found_update = False
             available_for_update = [eid for eid in ALL_ELEVATOR_IDS if eid not in updated_elevators]
             if not allow_sche_update_overlap: available_for_update = [eid for eid in available_for_update if sche_assigned_elevators_count[eid] == 0]
             if len(available_for_update) >= 2:
                 min_valid_time_for_any = float('inf'); best_pair_for_min_time = None
                 potential_pairs = [];
                 if len(available_for_update) >=2:
                     for i in range(len(available_for_update)):
                         for j in range(i + 1, len(available_for_update)): potential_pairs.append(tuple(sorted((available_for_update[i], available_for_update[j]))))
                     random.shuffle(potential_pairs)
                 for e_a, e_b in potential_pairs:
                      earliest_possible = best_effort_time
                      earliest_possible = max(earliest_possible, last_sche_time_per_elevator[e_a] + UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                      earliest_possible = max(earliest_possible, last_sche_time_per_elevator[e_b] + UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                      if earliest_possible < min_valid_time_for_any and earliest_possible <= update_max_time + 1e-9 and earliest_possible <= absolute_max_time + 1e-9:
                            min_valid_time_for_any = earliest_possible; best_pair_for_min_time = (e_a, e_b)
                 if best_pair_for_min_time is not None:
                     possible_placements = []
                     for e_a, e_b in potential_pairs:
                         earliest_possible = best_effort_time
                         earliest_possible = max(earliest_possible, last_sche_time_per_elevator[e_a] + UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                         earliest_possible = max(earliest_possible, last_sche_time_per_elevator[e_b] + UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                         if abs(earliest_possible - min_valid_time_for_any) < 1e-9 and earliest_possible <= update_max_time + 1e-9 and earliest_possible <= absolute_max_time + 1e-9:
                              possible_placements.append((earliest_possible, e_a, e_b))
                     if possible_placements:
                         placement_time, assigned_e_a, assigned_e_b = random.choice(possible_placements)
                         final_event_time = round(placement_time, 1); target_floor = random.choice(UPDATE_TARGET_FLOORS)
                         req_str = generate_update_request(final_event_time, assigned_e_a, assigned_e_b, target_floor)
                         generated_update_requests.append(req_str)
                         last_update_time_per_elevator[assigned_e_a] = placement_time; last_update_time_per_elevator[assigned_e_b] = placement_time
                         updated_elevators.add(assigned_e_a); updated_elevators.add(assigned_e_b)
                         update_placed_count += 1; found_update = True
    if sche_placed_count < num_sche: print(f"INFO: Successfully generated {sche_placed_count} SCHE requests (target was {num_sche}). Constraints may limit placement.", file=sys.stderr)
    if update_placed_count < num_update: print(f"INFO: Successfully generated {update_placed_count} UPDATE requests (target was {num_update}). Constraints may limit placement.", file=sys.stderr)


    # --- 4. Combine and Sort (Using sequential IDs generated by MAIN seed) ---
    # (Code unchanged)
    all_directives_sequential = passenger_requests + generated_sche_requests + generated_update_requests
    directives_with_indices = []
    for i, req in enumerate(all_directives_sequential):
         ts = get_timestamp_from_string(req)
         type_sort_key = 0 if "-PRI-" in req else (1 if "SCHE-" in req else 2)
         directives_with_indices.append((ts, type_sort_key, i, req))
    directives_with_indices.sort()
    sorted_directives_sequential = [item[3] for item in directives_with_indices]

    # --- 5. Post-Processing: Replace IDs if requested using INDEPENDENT seed ---
    final_directives = []
    if use_random_ids:
        print("INFO: Applying random IDs post-processing...", file=sys.stderr)

        # --- CRITICAL: Re-seed the GLOBAL random generator with the ID seed ---
        # This temporarily overrides the main seed state for ID generation ONLY.
        # All subsequent random.* calls *within this block* will use this ID seed.
        # If random_id_seed is None, it uses the value determined in main() (timestamp).
        random.seed(random_id_seed)
        id_seed_info = f"seed {random_id_seed}" if random_id_seed is not None else "current timestamp"
        print(f"INFO: Seeding RNG for random IDs with: {id_seed_info}", file=sys.stderr)

        used_random_ids = set()
        passenger_count = 0
        processed_directives = []
        passenger_regex = re.compile(r"^(\[\s*\d+\.\d+\s*\])(\d+)(-PRI-.*)$") # Slightly adjusted regex

        for req_str in sorted_directives_sequential:
            match = passenger_regex.match(req_str)
            if match:
                passenger_count += 1
                timestamp_part = match.group(1)
                # sequential_id_str = match.group(2) # We don't actually need the old ID value
                rest_of_request = match.group(3)

                # Generate a unique random ID using the ID-specific RNG state
                new_id = -1; attempts = 0; max_attempts = num_passengers * 10 + 1000
                while attempts < max_attempts:
                    potential_id = random.randint(1, MAX_RANDOM_PASSENGER_ID)
                    if potential_id not in used_random_ids:
                        new_id = potential_id
                        used_random_ids.add(new_id)
                        break
                    attempts += 1
                if new_id == -1:
                    print(f"CRITICAL ERROR: Failed to generate unique random ID for passenger request after {max_attempts} attempts.", file=sys.stderr)
                    seq_id_match = re.search(r"\](\d+)-PRI-", req_str)
                    fallback_id = seq_id_match.group(1) if seq_id_match else f"ERRORID{passenger_count}"
                    processed_directives.append(f"{timestamp_part}{fallback_id}{rest_of_request}")
                else:
                    new_req_str = f"{timestamp_part}{new_id}{rest_of_request}"
                    processed_directives.append(new_req_str)
            else:
                processed_directives.append(req_str) # Keep non-passenger requests
        final_directives = processed_directives
        print(f"INFO: Replaced IDs for {passenger_count} passenger requests using ID-specific seed.", file=sys.stderr)
        if len(used_random_ids) != passenger_count and passenger_count > 0:
             print(f"WARNING: Number of unique random IDs ({len(used_random_ids)}) does not match passenger count ({passenger_count}).", file=sys.stderr)

        # --- Optional: Restore main seed state if needed later ---
        # If there were more generation steps *after* this block that needed
        # to depend on the original main seed, we would restore it:
        # print(f"INFO: Restoring main RNG state (seed={seed})", file=sys.stderr)
        # random.seed(seed) # Or use random.setstate(saved_state) if state was saved
        # In this script, it's the last step, so restoration isn't strictly necessary.

    else:
        final_directives = sorted_directives_sequential


    # --- 6. Final Summary (minor updates) ---
    final_passenger_count = sum(1 for req in final_directives if "-PRI-" in req)
    final_sche_count = sum(1 for req in final_directives if "SCHE-" in req)
    final_update_count = sum(1 for req in final_directives if "UPDATE-" in req)
    print(f"\n--- Generation Summary ---", file=sys.stderr)
    print(f"Total Directives Generated: {len(final_directives)}", file=sys.stderr)
    print(f"  Passenger Requests: {final_passenger_count} (Target: {num_passengers})", file=sys.stderr)
    print(f"  SCHE Requests:      {final_sche_count} (Target: {num_sche})", file=sys.stderr)
    print(f"  UPDATE Requests:    {final_update_count} (Target: {num_update})", file=sys.stderr)
    id_mode_str = "Random Unique Positive Integers (Post-Processed)" if use_random_ids else "Sequential (1, 2, ...)"
    id_seed_info = f"(ID Seed: {'Timestamp' if random_id_seed is None else random_id_seed})" if use_random_ids else ""
    print(f"  Passenger ID Mode (Final Output): {id_mode_str} {id_seed_info}", file=sys.stderr)
    updated_str = str(sorted(list(updated_elevators))) if updated_elevators else "None"
    print(f"  Elevators Used in UPDATE (Banned from future SCHE): {updated_str}", file=sys.stderr)
    sche_counts_str = ", ".join(f"E{k}:{v}" for k, v in sorted(sche_assigned_elevators_count.items()) if v > 0) if any(sche_assigned_elevators_count.values()) else "None"
    print(f"  SCHE Counts per Elevator: {sche_counts_str}", file=sys.stderr)
    print(f"  Initially Eligible for SCHE: {sorted(sche_target_elevators)}", file=sys.stderr)
    print(f"  Hard Rule: UPDATE -> No Future SCHE = Enforced", file=sys.stderr)
    print(f"  Allow SCHE -> UPDATE Overlap (Non-HCE): {allow_sche_update_overlap}", file=sys.stderr)
    print(f"--------------------------", file=sys.stderr)

    return final_directives


# --- Main Function (Argument Parsing & Calling generate_data) ---
def main():
    parser = argparse.ArgumentParser(
        description="Generate Elevator Test Data (HW7: V3 + SCHE/UPDATE Control + Independent Random ID Seed)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # Core Parameters
    parser.add_argument("-np", "--num-passengers", type=int, default=DEFAULT_NUM_PASSENGERS, help="Target number of passenger requests.")
    parser.add_argument("-ns", "--num-sche", type=int, default=DEFAULT_NUM_SCHE, help="Target number of SCHE requests.")
    parser.add_argument("-nu", "--num-update", type=int, default=DEFAULT_NUM_UPDATE, help="Target number of UPDATE requests.")
    parser.add_argument("-t", "--max-time", type=float, default=DEFAULT_MAX_TIME, help="Maximum timestamp for any request.")
    parser.add_argument("--start-time", type=float, default=DEFAULT_START_TIME, help="Earliest timestamp for any request.")
    parser.add_argument("-o", "--output-file", type=str, default=None, help="Output file (default: stdout).")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for main generation reproducibility (timestamps, priorities, SCHE/UPDATE etc.).")

    # Hu Ce Mode
    parser.add_argument("--hce", action='store_true', help=f"Apply stricter Hu Ce constraints: Total <= {HUCE_MAX_DIRECTIVES}, Time [{HUCE_MIN_START_TIME:.1f}, {HUCE_MAX_TIME:.1f}], etc.")

    # Passenger Control
    pgroup = parser.add_argument_group('Passenger Request Control')
    pgroup.add_argument("--random-id", action='store_true', default=DEFAULT_USE_RANDOM_ID, help="Replace sequential passenger IDs with random unique positive integers post-generation.")
    # --- New argument for the ID seed ---
    pgroup.add_argument("--random-id-seed", type=int, default=None, help="Specific random seed for generating passenger IDs when --random-id is used. If omitted, uses current timestamp, making IDs non-repeatable across runs even with the same main --seed.")
    pgroup.add_argument("--min-interval-pass", type=float, default=DEFAULT_MIN_INTERVAL_PASS)
    pgroup.add_argument("--max-interval-pass", type=float, default=DEFAULT_MAX_INTERVAL_PASS)
    pgroup.add_argument("--force-start-passengers", type=int, default=0)
    pgroup.add_argument("--force-end-passengers", type=int, default=0)
    pgroup.add_argument("--pass-burst-size", type=int, default=0)
    pgroup.add_argument("--pass-burst-time", type=float, default=None)
    pgroup.add_argument("--extreme-floor-ratio", type=float, default=0.0)
    # Passenger Priority Control
    prigroup = parser.add_argument_group('Passenger Priority Control')
    prigroup.add_argument("--priority-bias", choices=['none', 'extremes', 'middle'], default='none')
    prigroup.add_argument("--priority-bias-ratio", type=float, default=0.5)
    prigroup.add_argument("--priority-middle-range", type=int, default=DEFAULT_PRIORITY_MIDDLE_RANGE)

    # SCHE/UPDATE Control
    sche_group = parser.add_argument_group('SCHE/UPDATE Control')
    sche_group.add_argument("--sche-target-elevators", type=str, default=DEFAULT_SCHE_ELEVATORS)
    sche_group.add_argument("--disallow-sche-update-overlap", action='store_true')
    sche_group.add_argument("--sche-burst-size", type=int, default=0)
    sche_group.add_argument("--sche-burst-time", type=float, default=None)
    sche_group.add_argument("--update-burst-size", type=int, default=0)
    sche_group.add_argument("--update-burst-time", type=float, default=None)
    sche_group.add_argument("--update-time-limit-ratio", type=float, default=DEFAULT_UPDATE_TIME_LIMIT_RATIO)

    args = parser.parse_args()

    # --- Argument Validation & Processing ---
    # (Most validation unchanged)
    adjusted_np = args.num_passengers; adjusted_ns = args.num_sche; adjusted_nu = args.num_update
    adjusted_start_time = args.start_time; adjusted_max_time = args.max_time
    if adjusted_np < 0 or adjusted_ns < 0 or adjusted_nu < 0: print("ERROR: Counts cannot be negative.", file=sys.stderr); sys.exit(1)

    eligible_sche_elevators = [] # ... (sche target elevator processing unchanged) ...
    if args.sche_target_elevators.lower() == 'all': eligible_sche_elevators = list(ALL_ELEVATOR_IDS)
    else:
        try:
            ids = [int(x.strip()) for x in args.sche_target_elevators.split(',') if x.strip()]
            valid_ids = [i for i in ids if i in ALL_ELEVATOR_IDS]
            if len(valid_ids) != len(ids): print(f"WARNING: Invalid elevator IDs found in --sche-target-elevators. Using only valid ones: {sorted(valid_ids)}", file=sys.stderr)
            if not valid_ids: print(f"ERROR: No valid elevator IDs provided. Defaulting to 'all'.", file=sys.stderr); eligible_sche_elevators = list(ALL_ELEVATOR_IDS)
            else: eligible_sche_elevators = sorted(list(set(valid_ids)))
        except ValueError: print(f"ERROR: Invalid format for --sche-target-elevators. Defaulting to 'all'.", file=sys.stderr); eligible_sche_elevators = list(ALL_ELEVATOR_IDS)

    allow_sche_then_update_overlap = DEFAULT_ALLOW_SCHE_UPDATE_OVERLAP
    if args.disallow_sche_update_overlap: allow_sche_then_update_overlap = False
    if args.hce:
        if allow_sche_then_update_overlap and not args.disallow_sche_update_overlap: print("INFO (HuCe): HuCe mode implicitly disallows SCHE->UPDATE overlap.", file=sys.stderr)
        allow_sche_then_update_overlap = False
        # ... (HCE adjustments unchanged) ...
        print("--- Applying Hu Ce Constraints (V3 + UPDATE->SCHE Ban) ---", file=sys.stderr)
        if adjusted_start_time < HUCE_MIN_START_TIME: print(f"  Adjusting start_time: {adjusted_start_time:.1f} -> {HUCE_MIN_START_TIME:.1f}", file=sys.stderr); adjusted_start_time = HUCE_MIN_START_TIME
        if adjusted_max_time > HUCE_MAX_TIME: print(f"  Adjusting max_time: {adjusted_max_time:.1f} -> {HUCE_MAX_TIME:.1f}", file=sys.stderr); adjusted_max_time = HUCE_MAX_TIME
        if adjusted_max_time < adjusted_start_time: print(f"ERROR (HuCe): Invalid time range.", file=sys.stderr); sys.exit(1)
        max_possible_updates = NUM_ELEVATORS // 2
        if adjusted_nu > max_possible_updates: print(f"  Adjusting num_update: {adjusted_nu} -> {max_possible_updates}", file=sys.stderr); adjusted_nu = max_possible_updates
        max_possible_sche = len(eligible_sche_elevators)
        if adjusted_ns > max_possible_sche: print(f"  Adjusting num_sche: {adjusted_ns} -> {max_possible_sche}", file=sys.stderr); adjusted_ns = max_possible_sche
        total_reqs = adjusted_np + adjusted_ns + adjusted_nu
        if total_reqs == 0: print("ERROR (HuCe): Total directives cannot be 0.", file=sys.stderr); sys.exit(1)
        elif total_reqs > HUCE_MAX_DIRECTIVES:
            print(f"  Total requested directives ({total_reqs}) exceeds HuCe limit ({HUCE_MAX_DIRECTIVES}).", file=sys.stderr); excess = total_reqs - HUCE_MAX_DIRECTIVES
            reduce_p=min(adjusted_np,excess); adjusted_np-=reduce_p; excess-=reduce_p
            if excess>0: reduce_s=min(adjusted_ns,excess); adjusted_ns-=reduce_s; excess-=reduce_s
            if excess>0: reduce_u=min(adjusted_nu,excess); adjusted_nu-=reduce_u; excess-=reduce_u
            print(f"  Adjusting counts -> P:{adjusted_np}, S:{adjusted_ns}, U:{adjusted_nu}", file=sys.stderr)
        if adjusted_np > 0:
            total_special = args.force_start_passengers + args.force_end_passengers + args.pass_burst_size
            if total_special > adjusted_np: print(f"ERROR (HuCe): Sum of forced/burst passengers ({total_special}) exceeds adjusted P ({adjusted_np}).", file=sys.stderr); sys.exit(1)
        elif args.force_start_passengers>0 or args.force_end_passengers>0 or args.pass_burst_size>0: print(f"  INFO (HuCe): Forced/burst P ignored as adjusted P is 0.", file=sys.stderr); args.force_start_passengers=0; args.force_end_passengers=0; args.pass_burst_size=0
        print("---------------------------------------", file=sys.stderr)

    if not (0.0 <= args.update_time_limit_ratio <= 1.0): print(f"WARNING: --update-time-limit-ratio invalid. Clamping to 1.0.", file=sys.stderr); args.update_time_limit_ratio = 1.0

    # --- Determine the seed for random IDs ---
    actual_random_id_seed = None
    if args.random_id:
        if args.random_id_seed is not None:
            actual_random_id_seed = args.random_id_seed
            # print(f"DEBUG: Using provided random_id_seed: {actual_random_id_seed}", file=sys.stderr)
        else:
            # Use current time if no specific seed is given for IDs
            actual_random_id_seed = int(time.time() * 1000 + random.randint(0, 999)) # Add small random to reduce timestamp collision chance
            # print(f"DEBUG: Using time-based random_id_seed: {actual_random_id_seed}", file=sys.stderr)

    # Burst Time Defaulting/Clamping (Unchanged)
    def adjust_burst_time(burst_time, type_name, start_t, max_t):
        adj_burst_time = burst_time
        if adj_burst_time is None: adj_burst_time = (start_t + max_t) / 2.0; print(f"INFO: Defaulting {type_name} burst time to midpoint: {adj_burst_time:.1f}", file=sys.stderr)
        original_burst_time = adj_burst_time; adj_burst_time = max(start_t, min(adj_burst_time, max_t))
        if abs(adj_burst_time - original_burst_time) > 1e-9 : print(f"INFO: Adjusted {type_name} burst time from {original_burst_time:.1f} to {adj_burst_time:.1f}.", file=sys.stderr)
        return adj_burst_time
    adjusted_pass_burst_time = args.pass_burst_time
    if args.pass_burst_size > 0 and adjusted_np > 0: adjusted_pass_burst_time = adjust_burst_time(args.pass_burst_time, "Passenger", adjusted_start_time, adjusted_max_time)
    adjusted_sche_burst_time = args.sche_burst_time
    if args.sche_burst_size > 0 and adjusted_ns > 0: adjusted_sche_burst_time = adjust_burst_time(args.sche_burst_time, "SCHE", adjusted_start_time, adjusted_max_time)
    adjusted_update_burst_time = args.update_burst_time
    update_burst_max_time = adjusted_start_time + (adjusted_max_time - adjusted_start_time) * args.update_time_limit_ratio
    update_burst_max_time = max(adjusted_start_time, update_burst_max_time)
    if args.update_burst_size > 0 and adjusted_nu > 0: adjusted_update_burst_time = adjust_burst_time(args.update_burst_time, "UPDATE", adjusted_start_time, update_burst_max_time)

    # Generate Data - Pass the determined ID seed
    generated_directives = generate_data(
        num_passengers=adjusted_np, num_sche=adjusted_ns, num_update=adjusted_nu,
        max_time=adjusted_max_time,
        min_interval_pass=args.min_interval_pass, max_interval_pass=args.max_interval_pass,
        start_time=adjusted_start_time,
        sche_target_elevators=eligible_sche_elevators,
        allow_sche_update_overlap=allow_sche_then_update_overlap,
        sche_burst_size=args.sche_burst_size, sche_burst_time=adjusted_sche_burst_time,
        update_burst_size=args.update_burst_size, update_burst_time=adjusted_update_burst_time,
        huce_mode=args.hce,
        seed=args.seed, # Main seed
        force_start_passengers=args.force_start_passengers, force_end_passengers=args.force_end_passengers,
        pass_burst_size=args.pass_burst_size, pass_burst_time=adjusted_pass_burst_time,
        extreme_floor_ratio=args.extreme_floor_ratio,
        priority_bias=args.priority_bias, priority_bias_ratio=args.priority_bias_ratio,
        priority_middle_range=args.priority_middle_range,
        update_time_limit_ratio=args.update_time_limit_ratio,
        use_random_ids=args.random_id,
        random_id_seed=actual_random_id_seed # Pass the specific seed for IDs
    )
    if generated_directives is None: print("ERROR: Data generation failed.", file=sys.stderr); sys.exit(1)

    # Output (Unchanged)
    output_content = "\n".join(generated_directives)
    if args.output_file:
        try:
            with open(args.output_file, 'w') as f: f.write(output_content); f.write("\n")
            print(f"\nSuccessfully generated {len(generated_directives)} directives to {args.output_file}", file=sys.stderr)
        except IOError as e: print(f"ERROR: Could not write to file {args.output_file}: {e}", file=sys.stderr); sys.exit(1)
    else:
        if output_content: print(output_content)

# --- Script Entry Point ---
if __name__ == "__main__":
    main()

# --- Example Presets (Illustrative - Note independent seeds) ---
"""
GEN_PRESET_COMMANDS = [
    # ID: BASE_SEQ_S1
    "gen.py -np 10 -ns 2 -nu 1 -t 20.0 --seed 1", # Main Seed 1 -> Seq IDs
    # ID: BASE_RAND_ID_TIME_S1
    "gen.py -np 10 -ns 2 -nu 1 -t 20.0 --seed 1 --random-id", # Main Seed 1 -> Time-based IDs (will differ each run)
    # ID: BASE_RAND_ID_SEED_S1_RS100
    "gen.py -np 10 -ns 2 -nu 1 -t 20.0 --seed 1 --random-id --random-id-seed 100", # Main Seed 1 -> ID Seed 100 (reproducible IDs)
    # ID: BASE_RAND_ID_SEED_S1_RS200
    "gen.py -np 10 -ns 2 -nu 1 -t 20.0 --seed 1 --random-id --random-id-seed 200", # Main Seed 1 -> ID Seed 200 (reproducible, different from RS100)
    # ID: BASE_RAND_ID_SEED_S2_RS100
    "gen.py -np 10 -ns 2 -nu 1 -t 20.0 --seed 2 --random-id --random-id-seed 100", # Main Seed 2 -> ID Seed 100 (structure differs from S1, IDs match S1_RS100)
]
"""
# --- END OF MODIFIED gen.py (HW7 - Granular Timing V3 + UPDATE->SCHE Ban + Independent Random ID Seed) ---
# --- END OF FILE gen.py ---