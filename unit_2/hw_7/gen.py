# --- START OF FILE gen.py ---

# --- START OF MODIFIED gen.py (HW7 - Granular Timing V3 - SCHE Control & Bursts + UPDATE->SCHE Ban) ---
import random
import argparse
import sys
import time
import math
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

# --- Timing & Interval Constants ---
UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL = 8  # Min interval between UPDATE and SCHE involving the *same* elevator (SCHE must be strictly later)
SCHE_SAME_ELEVATOR_MIN_INTERVAL = 8 # Min interval between SCHE requests for the SAME elevator
# Intervals of 0s (simultaneous allowed) for:
# - SCHE vs SCHE (different elevators)
# - UPDATE vs UPDATE (different elevators - automatically true due to 1-UPDATE rule)
# - SCHE vs UPDATE (different elevators) - RELAXED RULE (but UPDATE->SCHE ban is absolute)

# --- Default Generation Parameters ---
DEFAULT_NUM_PASSENGERS = 15
DEFAULT_NUM_SCHE = 3
DEFAULT_NUM_UPDATE = 1
DEFAULT_MAX_TIME = 50.0
DEFAULT_MIN_INTERVAL_PASS = 0.0 # Min interval between *passenger* requests
DEFAULT_MAX_INTERVAL_PASS = 1.4 # Max interval between *passenger* requests
DEFAULT_START_TIME = 1.0
DEFAULT_PRIORITY_MIDDLE_RANGE = 20
DEFAULT_UPDATE_TIME_LIMIT_RATIO = 0.6 # Default target ratio for UPDATE placement
DEFAULT_SCHE_ELEVATORS = ",".join(map(str, ALL_ELEVATOR_IDS)) # Default: all elevators can be SCHE'd
DEFAULT_ALLOW_SCHE_UPDATE_OVERLAP = True # Default: Allows SCHE then UPDATE, but NOT UPDATE then SCHE.

# --- Hu Ce (Mutual Testing) Specific Constraints ---
HUCE_MAX_DIRECTIVES = 70
HUCE_MAX_TIME = 50.0
HUCE_MIN_START_TIME = 1.0
# HUCE constraints on SCHE/UPDATE counts/overlap are handled by generator logic/args

# --- Helper Functions ---
def get_timestamp_from_string(request_str):
    """Extracts the float timestamp from a request string."""
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

# --- Request Generation Functions ---
def generate_passenger_request(passenger_id, current_time, floors,
                               extreme_floor_ratio=0.0,
                               priority_bias='none', priority_bias_ratio=0.0,
                               priority_middle_range=DEFAULT_PRIORITY_MIDDLE_RANGE):
    # (Function unchanged)
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
    # (Function unchanged)
    speed = random.choice(speeds); target_floor = random.choice(target_floors); formatted_time = round(current_time, 1)
    return f"[{formatted_time:.1f}]SCHE-{elevator_id}-{speed}-{target_floor}"

def generate_update_request(current_time, elevator_id_a, elevator_id_b, target_floor):
    # (Function unchanged)
    formatted_time = round(current_time, 1)
    return f"[{formatted_time:.1f}]UPDATE-{elevator_id_a}-{elevator_id_b}-{target_floor}"

# --- NEW Helper for Timestamp Generation ---
def _generate_target_timestamps(num_events, start_time, max_time,
                               burst_size=0, burst_time=None,
                               min_interval=0.0, max_interval=1.0):
    """Generates a list of target timestamps for events, handling bursts."""
    timestamps = []
    if num_events <= 0:
        return timestamps

    current_time = start_time
    absolute_max_time = max_time
    time_span = absolute_max_time - start_time
    if time_span < 0: time_span = 0

    # Calculate burst parameters if needed
    actual_burst_time = -1.0
    burst_insert_index = -1
    num_regular_events = num_events
    if burst_size > 0 and num_events >= burst_size:
        num_regular_events = num_events - burst_size
        # Determine burst time
        if burst_time is not None:
            actual_burst_time = max(start_time, min(burst_time, absolute_max_time))
        elif time_span > 1e-9:
             actual_burst_time = start_time + time_span / 2.0 # Default burst to midpoint
        else:
             actual_burst_time = start_time # Fallback if timespan is zero

        # Determine insertion point (relative to regular events)
        burst_ratio = (actual_burst_time - start_time) / time_span if time_span > 1e-9 else 0.0
        burst_insert_index = math.ceil(burst_ratio * num_regular_events)
        burst_insert_index = max(0, min(burst_insert_index, num_regular_events)) # Clamp index
    elif burst_size > 0:
        print(f"INFO: Burst size ({burst_size}) > num events ({num_events}). Treating all as burst.", file=sys.stderr)
        burst_size = num_events
        num_regular_events = 0
        actual_burst_time = burst_time if burst_time is not None else start_time + time_span / 2.0
        actual_burst_time = max(start_time, min(actual_burst_time, absolute_max_time))
        burst_insert_index = 0 # All events are burst events at index 0


    # Generate timestamps
    generated_regular_count = 0
    burst_added = False
    # Use average interval for regular events if specific intervals aren't critical,
    # otherwise use random intervals like passenger generation. Let's use random for now.
    avg_interval = time_span / num_events if num_events > 1 else 0.0
    max_interval = max(max_interval, avg_interval * 1.5) # Ensure max interval isn't too small
    min_interval = min(min_interval, avg_interval * 0.5) # Ensure min interval isn't too large

    for i in range(num_events):
        is_burst_event_this_iter = False
        # Check if it's time to insert the burst
        if burst_size > 0 and not burst_added and generated_regular_count == burst_insert_index:
            burst_gen_time = max(current_time, min(actual_burst_time, absolute_max_time))
            for _ in range(burst_size):
                timestamps.append(burst_gen_time)
            current_time = burst_gen_time # Update time after burst
            burst_added = True
            is_burst_event_this_iter = True

        # Generate regular event timestamp if needed
        if generated_regular_count < num_regular_events:
            if i > 0 or is_burst_event_this_iter: # Advance time after first event or after burst
                 interval = random.uniform(min_interval, max_interval)
                 current_time += interval
            request_time = max(start_time, min(current_time, absolute_max_time))
            timestamps.append(request_time)
            generated_regular_count += 1
            current_time = request_time # Update time based on actual placement
            if current_time >= absolute_max_time: break # Stop if max time reached early

        elif burst_added and generated_regular_count >= num_regular_events:
             break # All regular events generated and burst is done

    # Ensure the correct number of timestamps (handle edge cases)
    while len(timestamps) < num_events:
        last_time = timestamps[-1] if timestamps else start_time
        next_time = min(absolute_max_time, last_time + random.uniform(min_interval, max_interval))
        timestamps.append(next_time)

    return sorted(timestamps[:num_events])


# --- Main Data Generation Logic ---
def generate_data(num_passengers, num_sche, num_update, max_time,
                  min_interval_pass, max_interval_pass, start_time,
                  sche_target_elevators=ALL_ELEVATOR_IDS,
                  allow_sche_update_overlap=DEFAULT_ALLOW_SCHE_UPDATE_OVERLAP, # Controls SCHE->UPDATE if False
                  sche_burst_size=0, sche_burst_time=None,
                  update_burst_size=0, update_burst_time=None,
                  huce_mode=False, seed=None,
                  force_start_passengers=0, force_end_passengers=0,
                  pass_burst_size=0, pass_burst_time=None,
                  extreme_floor_ratio=0.0,
                  priority_bias='none', priority_bias_ratio=0.0,
                  priority_middle_range=DEFAULT_PRIORITY_MIDDLE_RANGE,
                  update_time_limit_ratio=DEFAULT_UPDATE_TIME_LIMIT_RATIO
                  ):
    """
    Generates interleaved elevator directives with V3 features.
    CORE RULE: An elevator involved in UPDATE can *never* be used in SCHE afterwards.
    """

    # Seeding
    if seed is not None: print(f"INFO: Using random seed: {seed}", file=sys.stderr); random.seed(seed)
    else: current_seed = int(time.time() * 1000); print(f"INFO: Using generated random seed: {current_seed}", file=sys.stderr); random.seed(current_seed)

    # State Trackers
    last_sche_time_per_elevator = defaultdict(lambda: -float('inf'))
    last_update_time_per_elevator = defaultdict(lambda: -float('inf'))
    updated_elevators = set() # Elevators that have been part of an UPDATE directive
    sche_assigned_elevators_count = defaultdict(int) # Tracks SCHE count per elevator

    # Pre-generation Validation & Info
    if num_passengers < 0 or num_sche < 0 or num_update < 0: print("CRITICAL ERROR: Counts cannot be negative.", file=sys.stderr); return None
    if num_passengers == 0 and num_sche == 0 and num_update == 0: print("CRITICAL ERROR: Must request at least one directive.", file=sys.stderr); return None
    print(f"INFO: Eligible elevators for SCHE (initially): {sorted(sche_target_elevators)}", file=sys.stderr)
    print(f"INFO: Hard Rule: Elevators in UPDATE are permanently banned from future SCHE.", file=sys.stderr)
    print(f"INFO: Allow SCHE -> UPDATE overlap (if not HCE): {allow_sche_update_overlap}", file=sys.stderr)
    if huce_mode:
        print(f"--- Hu Ce Mode Activated ---", file=sys.stderr)
        if start_time < HUCE_MIN_START_TIME: print(f"WARNING (HuCe): start_time {start_time:.1f} adjusted to {HUCE_MIN_START_TIME:.1f}.", file=sys.stderr); start_time = HUCE_MIN_START_TIME
        if max_time > HUCE_MAX_TIME: print(f"WARNING (HuCe): max_time {max_time:.1f} adjusted to {HUCE_MAX_TIME:.1f}.", file=sys.stderr); max_time = HUCE_MAX_TIME
        # HuCe implicitly disallows SCHE/UPDATE overlap (enforced below and by new rule)
        if allow_sche_update_overlap:
             print("INFO (HuCe): HuCe mode implicitly disallows SCHE/UPDATE overlap. Setting allow_sche_update_overlap=False.", file=sys.stderr)
        allow_sche_update_overlap = False # Enforce no overlap in HuCe
        # Other HuCe checks... (unchanged)
        if len(sche_target_elevators) < num_sche:
             print(f"WARNING (HuCe): Requested SCHE ({num_sche}) > eligible elevators ({len(sche_target_elevators)}). Adjusting SCHE count to {len(sche_target_elevators)}.", file=sys.stderr)
             num_sche = len(sche_target_elevators)
        print(f"INFO (HuCe): Generating {num_passengers+num_sche+num_update} directives (P:{num_passengers}, S:{num_sche}, U:{num_update}). Time: [{start_time:.1f}, {max_time:.1f}].", file=sys.stderr)
        print(f"INFO (HuCe): Constraints: Max 1 SCHE/eligible elevator, Max 1 UPDATE involvement/elevator, No SCHE/UPDATE overlap (enforced).", file=sys.stderr)
        print(f"-----------------------------", file=sys.stderr)

    # Calculate Effective Time Limit for UPDATEs
    absolute_max_time = max_time
    total_duration = absolute_max_time - start_time
    if total_duration < 0: total_duration = 0
    effective_ratio = max(0.0, min(1.0, update_time_limit_ratio))
    update_max_time = start_time + total_duration * effective_ratio
    update_max_time = max(start_time, update_max_time)
    if effective_ratio < 1.0: print(f"INFO: Attempting to place UPDATEs before target time limit: {update_max_time:.1f}", file=sys.stderr)


    # --- 1. Generate Passenger Requests (Timestamps Fixed) ---
    passenger_requests = []
    # ... (Passenger generation logic remains exactly the same as before) ...
    # (Snipped for brevity - assumed identical to the provided code)
    last_passenger_id = 0
    current_time_pass = start_time
    if num_passengers > 0:
        if force_start_passengers > 0:
            for _ in range(force_start_passengers): last_passenger_id += 1; req_str = generate_passenger_request(last_passenger_id, start_time, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range); passenger_requests.append(req_str)
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
        if num_middle_passengers > 0:
            regular_middle_target = num_middle_passengers # Keep track of non-burst middle requests needed
            for i in range(num_middle_passengers + pass_burst_size): # Loop enough times for all middle+burst
                is_burst_req_generated_this_iteration = False
                if pass_burst_size > 0 and not burst_added and middle_req_generated_count == burst_insert_index_pass:
                    burst_gen_time = max(current_time_pass, min(actual_burst_time_pass, absolute_max_time))
                    for _ in range(pass_burst_size): last_passenger_id += 1; req_str = generate_passenger_request(last_passenger_id, burst_gen_time, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range); passenger_requests.append(req_str)
                    current_time_pass = burst_gen_time; burst_added = True; is_burst_req_generated_this_iteration = True
                if middle_req_generated_count < regular_middle_target:
                    if middle_req_generated_count > 0 or force_start_passengers > 0 or is_burst_req_generated_this_iteration: # Advance time after first or after burst
                        interval = random.uniform(min_interval_pass, max_interval_pass); current_time_pass += interval
                    request_time_pass = max(start_time, min(current_time_pass, absolute_max_time))
                    last_passenger_id += 1; req_str = generate_passenger_request(last_passenger_id, request_time_pass, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range); passenger_requests.append(req_str)
                    middle_req_generated_count += 1; current_time_pass = request_time_pass
                    if current_time_pass >= absolute_max_time: break # Stop if max time reached
                elif burst_added and middle_req_generated_count >= regular_middle_target:
                    break # Stop if all regular middle passengers are generated and burst is done
        if force_end_passengers > 0:
            actual_end_time = max(current_time_pass, absolute_max_time); actual_end_time = min(actual_end_time, absolute_max_time)
            for _ in range(force_end_passengers): last_passenger_id += 1; req_str = generate_passenger_request(last_passenger_id, actual_end_time, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range); passenger_requests.append(req_str)
            current_time_pass = actual_end_time


    # --- 2. Generate Target Timestamps for SCHE/UPDATE ---
    sche_target_timestamps = _generate_target_timestamps(num_sche, start_time, absolute_max_time, sche_burst_size, sche_burst_time, 0.1, 2.0)
    update_target_timestamps = _generate_target_timestamps(num_update, start_time, update_max_time, update_burst_size, update_burst_time, 0.1, 2.0)

    # --- 3. Combine Targets and Place SCHE/UPDATE respecting constraints ---
    all_target_events = [(ts, 'SCHE') for ts in sche_target_timestamps] + \
                        [(ts, 'UPDATE') for ts in update_target_timestamps]
    all_target_events.sort(key=lambda x: x[0]) # Sort by target time

    generated_sche_requests = []
    generated_update_requests = []
    sche_placed_count = 0
    update_placed_count = 0

    # Process targets one by one, finding the earliest valid placement time
    for target_time, event_type in all_target_events:
        placement_time = -1.0
        best_effort_time = target_time # Start searching from the target time

        if event_type == 'SCHE' and sche_placed_count < num_sche:
            found_sche = False
            # Filter candidates based on the *current* state of updated_elevators
            current_sche_candidates = [eid for eid in sche_target_elevators if eid not in updated_elevators]
            random.shuffle(current_sche_candidates)

            min_valid_time_for_any = float('inf')
            best_elevator_for_min_time = -1

            # Find the absolute earliest time *any* eligible, non-updated elevator can run >= target_time
            for elevator_id in current_sche_candidates: # Use the filtered list
                 # --- CORE RULE CHECK (Implicitly handled by filtering current_sche_candidates) ---
                 # if elevator_id in updated_elevators: continue # This check is now done *before* the loop

                 # HuCe check (Max 1 SCHE per elevator)
                 if huce_mode and sche_assigned_elevators_count[elevator_id] >= 1: continue

                 # Calculate earliest possible time for THIS elevator >= best_effort_time
                 earliest_possible = best_effort_time
                 # Check against last SCHE for THIS elevator
                 earliest_possible = max(earliest_possible, last_sche_time_per_elevator[elevator_id] + SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                 # Check against last UPDATE involving THIS elevator (though it shouldn't happen due to the core rule, this maintains interval logic if needed elsewhere)
                 earliest_possible = max(earliest_possible, last_update_time_per_elevator[elevator_id] + UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL)

                 if earliest_possible < min_valid_time_for_any and earliest_possible <= absolute_max_time + 1e-9:
                     min_valid_time_for_any = earliest_possible
                     best_elevator_for_min_time = elevator_id # Tentative best

            # Now, find ALL elevators that can run exactly at min_valid_time_for_any
            if best_elevator_for_min_time != -1:
                possible_placements = []
                for elevator_id in current_sche_candidates: # Use the filtered list again
                    # --- CORE RULE CHECK (Implicitly handled by filtering) ---
                    # if elevator_id in updated_elevators: continue

                    # HuCe check
                    if huce_mode and sche_assigned_elevators_count[elevator_id] >= 1: continue

                    # Calculate earliest possible time (same logic as above)
                    earliest_possible = best_effort_time
                    earliest_possible = max(earliest_possible, last_sche_time_per_elevator[elevator_id] + SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                    earliest_possible = max(earliest_possible, last_update_time_per_elevator[elevator_id] + UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL)

                    # Check if it matches the absolute minimum found time
                    if abs(earliest_possible - min_valid_time_for_any) < 1e-9 and earliest_possible <= absolute_max_time + 1e-9:
                         possible_placements.append((earliest_possible, elevator_id))

                if possible_placements:
                     # Choose randomly among elevators that can run at the earliest possible time
                     placement_time, assigned_elevator_id = random.choice(possible_placements)
                     final_event_time = round(placement_time, 1)
                     req_str = generate_sche_request(final_event_time, assigned_elevator_id, SCHE_TARGET_FLOORS, SCHE_SPEEDS)
                     generated_sche_requests.append(req_str)
                     last_sche_time_per_elevator[assigned_elevator_id] = placement_time # Use precise time
                     sche_assigned_elevators_count[assigned_elevator_id] += 1
                     sche_placed_count += 1
                     found_sche = True
                     # print(f"DEBUG: Placed SCHE E{assigned_elevator_id} at {placement_time:.3f} (Target: {target_time:.3f})", file=sys.stderr)


        elif event_type == 'UPDATE' and update_placed_count < num_update:
            found_update = False
            # Start with elevators not already updated (1 UPDATE per elevator rule)
            available_for_update = [eid for eid in ALL_ELEVATOR_IDS if eid not in updated_elevators]

            # Apply SCHE->UPDATE overlap constraint if needed (allow_sche_update_overlap=False)
            if not allow_sche_update_overlap:
                 # If overlap is disallowed, remove elevators that have *already* been SCHE'd
                 available_for_update = [eid for eid in available_for_update if sche_assigned_elevators_count[eid] == 0]

            if len(available_for_update) >= 2:
                min_valid_time_for_any = float('inf')
                best_pair_for_min_time = None

                # Find the absolute earliest time *any* eligible pair can run >= target_time
                potential_pairs = []
                for i in range(len(available_for_update)):
                    for j in range(i + 1, len(available_for_update)):
                        potential_pairs.append(tuple(sorted((available_for_update[i], available_for_update[j]))))
                random.shuffle(potential_pairs) # Avoid bias

                for e_a, e_b in potential_pairs:
                     # Calculate earliest possible time for THIS pair >= best_effort_time
                     earliest_possible = best_effort_time
                     # Check against last SCHE for either elevator (relevant for interval separation)
                     earliest_possible = max(earliest_possible, last_sche_time_per_elevator[e_a] + UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                     earliest_possible = max(earliest_possible, last_sche_time_per_elevator[e_b] + UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                     # No need to check against last_update_time, as elevators in `updated_elevators` are already excluded.

                     # Check against update time limit AND max time
                     if earliest_possible < min_valid_time_for_any and \
                        earliest_possible <= update_max_time + 1e-9 and \
                        earliest_possible <= absolute_max_time + 1e-9:
                           min_valid_time_for_any = earliest_possible
                           best_pair_for_min_time = (e_a, e_b) # Tentative best

                # Now, find ALL pairs that can run exactly at min_valid_time_for_any
                if best_pair_for_min_time is not None:
                    possible_placements = []
                    for e_a, e_b in potential_pairs:
                        # Calculate earliest possible time (same logic as above)
                        earliest_possible = best_effort_time
                        earliest_possible = max(earliest_possible, last_sche_time_per_elevator[e_a] + UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                        earliest_possible = max(earliest_possible, last_sche_time_per_elevator[e_b] + UPDATE_SCHE_SAME_ELEVATOR_MIN_INTERVAL)

                        # Check if it matches the minimum time and respects time limits
                        if abs(earliest_possible - min_valid_time_for_any) < 1e-9 and \
                           earliest_possible <= update_max_time + 1e-9 and \
                           earliest_possible <= absolute_max_time + 1e-9:
                             possible_placements.append((earliest_possible, e_a, e_b))

                    if possible_placements:
                        # Choose randomly among pairs that can run at the earliest possible time
                        placement_time, assigned_e_a, assigned_e_b = random.choice(possible_placements)
                        final_event_time = round(placement_time, 1)
                        target_floor = random.choice(UPDATE_TARGET_FLOORS)
                        req_str = generate_update_request(final_event_time, assigned_e_a, assigned_e_b, target_floor)
                        generated_update_requests.append(req_str)
                        last_update_time_per_elevator[assigned_e_a] = placement_time # Use precise time
                        last_update_time_per_elevator[assigned_e_b] = placement_time
                        # Add to the permanent blacklist for SCHE
                        updated_elevators.add(assigned_e_a)
                        updated_elevators.add(assigned_e_b)
                        update_placed_count += 1
                        found_update = True
                        # print(f"DEBUG: Placed UPDATE E{assigned_e_a},E{assigned_e_b} at {placement_time:.3f} (Target: {target_time:.3f})", file=sys.stderr)

    # Report if quotas weren't met
    if sche_placed_count < num_sche: print(f"INFO: Successfully generated {sche_placed_count} SCHE requests (target was {num_sche}). Could not place all due to constraints (incl. UPDATE->SCHE ban).", file=sys.stderr)
    if update_placed_count < num_update: print(f"INFO: Successfully generated {update_placed_count} UPDATE requests (target was {num_update}). Could not place all due to constraints.", file=sys.stderr)


    # --- 4. Combine and Sort ---
    all_directives = passenger_requests + generated_sche_requests + generated_update_requests
    # Sort primarily by timestamp, use original index/type as tie-breaker
    directives_with_indices = []
    for i, req in enumerate(all_directives):
         ts = get_timestamp_from_string(req)
         # Add a secondary sort key to try and keep passengers first at same time if needed
         type_sort_key = 0 if "-PRI-" in req else (1 if "SCHE-" in req else 2)
         directives_with_indices.append((ts, type_sort_key, i, req))

    directives_with_indices.sort() # Sort by timestamp, then type, then original order
    all_directives = [item[3] for item in directives_with_indices]


    # --- 5. Final Summary ---
    final_passenger_count = sum(1 for req in all_directives if "-PRI-" in req)
    final_sche_count = sum(1 for req in all_directives if "SCHE-" in req)
    final_update_count = sum(1 for req in all_directives if "UPDATE-" in req)
    print(f"\n--- Generation Summary ---", file=sys.stderr)
    print(f"Total Directives Generated: {len(all_directives)}", file=sys.stderr)
    print(f"  Passenger Requests: {final_passenger_count} (Target: {num_passengers})", file=sys.stderr)
    print(f"  SCHE Requests:      {final_sche_count} (Target: {num_sche})", file=sys.stderr)
    print(f"  UPDATE Requests:    {final_update_count} (Target: {num_update})", file=sys.stderr)
    updated_str = str(sorted(list(updated_elevators))) if updated_elevators else "None"
    print(f"  Elevators Used in UPDATE (Banned from future SCHE): {updated_str}", file=sys.stderr)
    sche_counts_str = ", ".join(f"E{k}:{v}" for k, v in sorted(sche_assigned_elevators_count.items()) if v > 0) if any(sche_assigned_elevators_count.values()) else "None"
    print(f"  SCHE Counts per Elevator: {sche_counts_str}", file=sys.stderr)
    print(f"  Initially Eligible for SCHE: {sorted(sche_target_elevators)}", file=sys.stderr)
    print(f"  Hard Rule: UPDATE -> No Future SCHE = Enforced", file=sys.stderr)
    print(f"  Allow SCHE -> UPDATE Overlap (Non-HCE): {allow_sche_update_overlap}", file=sys.stderr)
    print(f"--------------------------", file=sys.stderr)

    return all_directives


# --- Main Function (Argument Parsing & Calling generate_data) ---
def main():
    parser = argparse.ArgumentParser(
        description="Generate Elevator Test Data (HW7: V3 + SCHE Control & Bursts + UPDATE->SCHE Ban)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # Core Parameters
    parser.add_argument("-np", "--num-passengers", type=int, default=DEFAULT_NUM_PASSENGERS, help="Target number of passenger requests.")
    parser.add_argument("-ns", "--num-sche", type=int, default=DEFAULT_NUM_SCHE, help="Target number of SCHE requests.")
    parser.add_argument("-nu", "--num-update", type=int, default=DEFAULT_NUM_UPDATE, help="Target number of UPDATE requests.")
    parser.add_argument("-t", "--max-time", type=float, default=DEFAULT_MAX_TIME, help="Maximum timestamp for any request.")
    parser.add_argument("--start-time", type=float, default=DEFAULT_START_TIME, help="Earliest timestamp for any request.")
    parser.add_argument("-o", "--output-file", type=str, default=None, help="Output file (default: stdout).")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")

    # Hu Ce Mode
    parser.add_argument("--hce", action='store_true', help=f"Apply stricter Hu Ce constraints: Total <= {HUCE_MAX_DIRECTIVES}, Time [{HUCE_MIN_START_TIME:.1f}, {HUCE_MAX_TIME:.1f}], Max 1 SCHE/eligible elevator, Max 1 UPDATE involvement/elevator, No SCHE/UPDATE overlap (enforced). UPDATE->SCHE ban applies.")

    # Passenger Control (Unchanged)
    pgroup = parser.add_argument_group('Passenger Request Control')
    pgroup.add_argument("--min-interval-pass", type=float, default=DEFAULT_MIN_INTERVAL_PASS, help="Minimum time interval between consecutive PASSENGER requests (approx).")
    pgroup.add_argument("--max-interval-pass", type=float, default=DEFAULT_MAX_INTERVAL_PASS, help="Maximum time interval between consecutive PASSENGER requests (approx).")
    pgroup.add_argument("--force-start-passengers", type=int, default=0, help="Generate N passengers exactly at start-time.")
    pgroup.add_argument("--force-end-passengers", type=int, default=0, help="Generate N passengers exactly at max-time.")
    pgroup.add_argument("--pass-burst-size", type=int, default=0, help="Generate a burst of N passengers at approx. pass-burst-time.")
    pgroup.add_argument("--pass-burst-time", type=float, default=None, help="Approx timestamp for passenger burst (defaults to midpoint if pass-burst-size > 0).")
    pgroup.add_argument("--extreme-floor-ratio", type=float, default=0.0, help=f"Probability (0.0-1.0) of {ALL_FLOORS[0]}<->{ALL_FLOORS[-1]} passenger requests.")
    # Passenger Priority Control (Unchanged)
    prigroup = parser.add_argument_group('Passenger Priority Control')
    prigroup.add_argument("--priority-bias", choices=['none', 'extremes', 'middle'], default='none', help="Bias priority generation.")
    prigroup.add_argument("--priority-bias-ratio", type=float, default=0.5, help="Probability (0.0-1.0) of applying the bias.")
    prigroup.add_argument("--priority-middle-range", type=int, default=DEFAULT_PRIORITY_MIDDLE_RANGE, help="Range width for 'middle' bias (e.g., 20 -> ~40-60).")

    # SCHE/UPDATE Control
    sche_group = parser.add_argument_group('SCHE/UPDATE Control')
    sche_group.add_argument("--sche-target-elevators", type=str, default=DEFAULT_SCHE_ELEVATORS, help="Comma-separated list of elevator IDs *initially* eligible for SCHE (e.g., '1,3,5'), or 'all'. They become ineligible after UPDATE.")
    # Note: --disallow-sche-update-overlap now only affects SCHE->UPDATE direction if set.
    sche_group.add_argument("--disallow-sche-update-overlap", action='store_true', help="If set, prevent an elevator involved in SCHE from being involved in UPDATE. Default allows SCHE->UPDATE (unless --hce). UPDATE->SCHE is *always* disallowed.")
    sche_group.add_argument("--sche-burst-size", type=int, default=0, help="Generate a burst of N SCHE requests near sche-burst-time.")
    sche_group.add_argument("--sche-burst-time", type=float, default=None, help="Approx target timestamp for SCHE burst.")
    sche_group.add_argument("--update-burst-size", type=int, default=0, help="Generate a burst of N UPDATE requests near update-burst-time.")
    sche_group.add_argument("--update-burst-time", type=float, default=None, help="Approx target timestamp for UPDATE burst.")
    sche_group.add_argument("--update-time-limit-ratio", type=float, default=DEFAULT_UPDATE_TIME_LIMIT_RATIO, help="Attempt to place UPDATE requests before this fraction of the total duration. Value between 0.0 and 1.0.")

    args = parser.parse_args()

    # --- Argument Validation & Processing ---
    adjusted_np = args.num_passengers
    adjusted_ns = args.num_sche
    adjusted_nu = args.num_update
    adjusted_start_time = args.start_time
    adjusted_max_time = args.max_time

    # Validate counts
    if adjusted_np < 0 or adjusted_ns < 0 or adjusted_nu < 0: print("ERROR: Counts cannot be negative.", file=sys.stderr); sys.exit(1)

    # Process --sche-target-elevators (Unchanged)
    eligible_sche_elevators = []
    if args.sche_target_elevators.lower() == 'all':
        eligible_sche_elevators = list(ALL_ELEVATOR_IDS)
    else:
        try:
            ids = [int(x.strip()) for x in args.sche_target_elevators.split(',') if x.strip()]
            valid_ids = [i for i in ids if i in ALL_ELEVATOR_IDS]
            if len(valid_ids) != len(ids):
                 print(f"WARNING: Invalid elevator IDs found in --sche-target-elevators. Using only valid ones: {sorted(valid_ids)}", file=sys.stderr)
            if not valid_ids:
                 print(f"ERROR: No valid elevator IDs provided for --sche-target-elevators. Defaulting to 'all'.", file=sys.stderr)
                 eligible_sche_elevators = list(ALL_ELEVATOR_IDS)
            else:
                 eligible_sche_elevators = sorted(list(set(valid_ids))) # Unique, sorted
        except ValueError:
             print(f"ERROR: Invalid format for --sche-target-elevators. Expected comma-separated integers or 'all'. Defaulting to 'all'.", file=sys.stderr)
             eligible_sche_elevators = list(ALL_ELEVATOR_IDS)

    # Determine SCHE->UPDATE overlap rule
    # UPDATE->SCHE is *always* disallowed now.
    allow_sche_then_update_overlap = DEFAULT_ALLOW_SCHE_UPDATE_OVERLAP
    if args.disallow_sche_update_overlap:
        allow_sche_then_update_overlap = False
    if args.hce: # HuCe mode overrides and disallows SCHE->UPDATE overlap
        if allow_sche_then_update_overlap and not args.disallow_sche_update_overlap:
             print("INFO (HuCe): HuCe mode implicitly disallows SCHE->UPDATE overlap. Overriding default/user setting.", file=sys.stderr)
        allow_sche_then_update_overlap = False

    # HuCe Enforcement (Unchanged logic, but descriptions acknowledge new rule)
    if args.hce:
        print("--- Applying Hu Ce Constraints (V3 + UPDATE->SCHE Ban) ---", file=sys.stderr)
        if adjusted_start_time < HUCE_MIN_START_TIME: print(f"  Adjusting start_time: {adjusted_start_time:.1f} -> {HUCE_MIN_START_TIME:.1f}", file=sys.stderr); adjusted_start_time = HUCE_MIN_START_TIME
        if adjusted_max_time > HUCE_MAX_TIME: print(f"  Adjusting max_time: {adjusted_max_time:.1f} -> {HUCE_MAX_TIME:.1f}", file=sys.stderr); adjusted_max_time = HUCE_MAX_TIME
        if adjusted_max_time < adjusted_start_time: print(f"ERROR (HuCe): Invalid time range.", file=sys.stderr); sys.exit(1)

        max_possible_updates = NUM_ELEVATORS // 2
        if adjusted_nu > max_possible_updates: print(f"  Adjusting num_update: {adjusted_nu} -> {max_possible_updates} (max 1 UPDATE per elevator)", file=sys.stderr); adjusted_nu = max_possible_updates

        # SCHE limit based on *eligible* elevators (and implicitly by UPDATE ban)
        max_possible_sche = len(eligible_sche_elevators)
        if adjusted_ns > max_possible_sche: print(f"  Adjusting num_sche: {adjusted_ns} -> {max_possible_sche} (max 1 SCHE per *initially eligible* elevator)", file=sys.stderr); adjusted_ns = max_possible_sche

        total_reqs = adjusted_np + adjusted_ns + adjusted_nu
        if total_reqs == 0: print("ERROR (HuCe): Total directives cannot be 0.", file=sys.stderr); sys.exit(1)
        elif total_reqs > HUCE_MAX_DIRECTIVES:
            print(f"  Total requested directives ({total_reqs}) exceeds HuCe limit ({HUCE_MAX_DIRECTIVES}).", file=sys.stderr); excess = total_reqs - HUCE_MAX_DIRECTIVES
            reduce_p = min(adjusted_np, excess); adjusted_np -= reduce_p; excess -= reduce_p
            if excess > 0: reduce_s = min(adjusted_ns, excess); adjusted_ns -= reduce_s; excess -= reduce_s
            if excess > 0: reduce_u = min(adjusted_nu, excess); adjusted_nu -= reduce_u; excess -= reduce_u
            print(f"  Adjusting counts -> P:{adjusted_np}, S:{adjusted_ns}, U:{adjusted_nu}", file=sys.stderr)

        # Validate passenger special cases (Unchanged)
        if adjusted_np > 0:
            total_special = args.force_start_passengers + args.force_end_passengers + args.pass_burst_size
            if total_special > adjusted_np: print(f"ERROR (HuCe): Sum of forced/burst passengers ({total_special}) exceeds adjusted P ({adjusted_np}).", file=sys.stderr); sys.exit(1)
        elif args.force_start_passengers > 0 or args.force_end_passengers > 0 or args.pass_burst_size > 0:
             print(f"  INFO (HuCe): Forced/burst P options ignored as adjusted P is 0.", file=sys.stderr); args.force_start_passengers = 0; args.force_end_passengers = 0; args.pass_burst_size = 0
        print("---------------------------------------", file=sys.stderr)

    # Validate other args (Unchanged)
    if not (0.0 <= args.update_time_limit_ratio <= 1.0): print(f"WARNING: --update-time-limit-ratio invalid. Clamping to 1.0.", file=sys.stderr); args.update_time_limit_ratio = 1.0

    # Burst Time Defaulting/Clamping (Unchanged)
    def adjust_burst_time(burst_time, type_name, start_t, max_t):
        adj_burst_time = burst_time
        if adj_burst_time is None:
             adj_burst_time = (start_t + max_t) / 2.0
             print(f"INFO: Defaulting {type_name} burst time to midpoint: {adj_burst_time:.1f}", file=sys.stderr)
        original_burst_time = adj_burst_time
        adj_burst_time = max(start_t, min(adj_burst_time, max_t))
        if abs(adj_burst_time - original_burst_time) > 1e-9 : print(f"INFO: Adjusted {type_name} burst time from {original_burst_time:.1f} to {adj_burst_time:.1f}.", file=sys.stderr)
        return adj_burst_time

    adjusted_pass_burst_time = args.pass_burst_time
    if args.pass_burst_size > 0 and adjusted_np > 0: adjusted_pass_burst_time = adjust_burst_time(args.pass_burst_time, "Passenger", adjusted_start_time, adjusted_max_time)

    adjusted_sche_burst_time = args.sche_burst_time
    if args.sche_burst_size > 0 and adjusted_ns > 0: adjusted_sche_burst_time = adjust_burst_time(args.sche_burst_time, "SCHE", adjusted_start_time, adjusted_max_time)

    adjusted_update_burst_time = args.update_burst_time
    update_burst_max_time = adjusted_start_time + (adjusted_max_time - adjusted_start_time) * args.update_time_limit_ratio
    if args.update_burst_size > 0 and adjusted_nu > 0: adjusted_update_burst_time = adjust_burst_time(args.update_burst_time, "UPDATE", adjusted_start_time, update_burst_max_time)


    # Generate Data
    generated_directives = generate_data(
        num_passengers=adjusted_np, num_sche=adjusted_ns, num_update=adjusted_nu,
        max_time=adjusted_max_time,
        min_interval_pass=args.min_interval_pass, max_interval_pass=args.max_interval_pass,
        start_time=adjusted_start_time,
        sche_target_elevators=eligible_sche_elevators,
        allow_sche_update_overlap=allow_sche_then_update_overlap, # Pass the potentially adjusted flag
        sche_burst_size=args.sche_burst_size, sche_burst_time=adjusted_sche_burst_time,
        update_burst_size=args.update_burst_size, update_burst_time=adjusted_update_burst_time,
        huce_mode=args.hce, seed=args.seed,
        force_start_passengers=args.force_start_passengers, force_end_passengers=args.force_end_passengers,
        pass_burst_size=args.pass_burst_size, pass_burst_time=adjusted_pass_burst_time,
        extreme_floor_ratio=args.extreme_floor_ratio,
        priority_bias=args.priority_bias, priority_bias_ratio=args.priority_bias_ratio,
        priority_middle_range=args.priority_middle_range,
        update_time_limit_ratio=args.update_time_limit_ratio
    )
    if generated_directives is None: print("ERROR: Data generation failed.", file=sys.stderr); sys.exit(1)

    # Output (Unchanged)
    output_content = "\n".join(generated_directives)
    if args.output_file:
        try:
            with open(args.output_file, 'w') as f:
                f.write(output_content)
                if generated_directives: f.write("\n")
            print(f"\nSuccessfully generated {len(generated_directives)} directives to {args.output_file}", file=sys.stderr)
        except IOError as e: print(f"ERROR: Could not write to file {args.output_file}: {e}", file=sys.stderr); sys.exit(1)
    else:
        if output_content: print(output_content)

# --- Script Entry Point ---
if __name__ == "__main__":
    main()

# --- Example Presets (Illustrative - Note UPDATE->SCHE Ban) ---
"""
GEN_PRESET_COMMANDS = [
    # ID: HCE_SIMPLE_V3_BAN
    "gen.py --hce -np 20 -ns 3 -nu 2 -t 45.0 --sche-target-elevators '1,2,3,4'", # HCE + Ban. If UPDATE involves E1/E2, only E3/E4 can get SCHE after.
    # ID: PUB_SCHE_BURST_V3_BAN
    "gen.py -np 10 -ns 12 -nu 1 -t 80.0 --sche-burst-size 6 --sche-burst-time 40.0", # Burst of 6 SCHE. If UPDATE occurs before t=40 and involves E_x, E_x cannot be in the burst.
    # ID: PUB_UPDATE_THEN_SCHE_TEST_BAN
    "gen.py -np 5 -ns 5 -nu 1 -t 30.0 --update-burst-size 1 --update-burst-time 10.0 --sche-burst-size 3 --sche-burst-time 20.0", # UPDATE at t=10, SCHE at t=20. The 2 elevators in UPDATE are banned from SCHE burst.
    # ID: PUB_LIMIT_SCHE_DISALLOW_OVERLAP_V3_BAN
    "gen.py -np 15 -ns 5 -nu 2 -t 70.0 --sche-target-elevators '2,4,6' --disallow-sche-update-overlap", # Only E2,4,6 get SCHE. If E2 gets SCHE, it cannot get UPDATE later. If E4/E6 get UPDATE, they cannot get SCHE later.
]
"""
# --- END OF MODIFIED gen.py (HW7 - Granular Timing V3 + UPDATE->SCHE Ban) ---