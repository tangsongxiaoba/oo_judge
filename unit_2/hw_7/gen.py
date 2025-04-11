# --- START OF MODIFIED gen.py (HW7 - Granular Timing Rules) ---
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
MIN_PRIORITY = 1
MAX_PRIORITY = 100
MID_PRIORITY = (MIN_PRIORITY + MAX_PRIORITY) // 2
SCHE_TARGET_FLOORS = ['B2', 'B1', 'F1', 'F2', 'F3', 'F4', 'F5']
SCHE_SPEEDS = [0.2, 0.3, 0.4, 0.5]
UPDATE_TARGET_FLOORS = ['B2', 'B1', 'F1', 'F2', 'F3', 'F4', 'F5'] # Same as SCHE for target

# --- Timing & Interval Constants ---
UPDATE_SCHE_MIN_INTERVAL = 12.5  # Min interval between an UPDATE and a SCHE (any order)
SCHE_SAME_ELEVATOR_MIN_INTERVAL = 10 # Min interval between SCHE requests for the SAME elevator
# Intervals of 0s (simultaneous allowed) for:
# - SCHE vs SCHE (different elevators)
# - UPDATE vs UPDATE (different elevators - automatically true due to 1-UPDATE rule)

# --- Default Generation Parameters ---
DEFAULT_NUM_PASSENGERS = 15
DEFAULT_NUM_SCHE = 3
DEFAULT_NUM_UPDATE = 1
DEFAULT_MAX_TIME = 50.0
DEFAULT_MIN_INTERVAL = 0.0 # Min interval between *passenger* requests
DEFAULT_MAX_INTERVAL = 1.4 # Max interval between *passenger* requests
DEFAULT_START_TIME = 1.0
DEFAULT_PRIORITY_MIDDLE_RANGE = 20
DEFAULT_UPDATE_TIME_LIMIT_RATIO = 0.6 # Default target ratio for UPDATE placement

# --- Hu Ce (Mutual Testing) Specific Constraints ---
HUCE_MAX_DIRECTIVES = 70
HUCE_MAX_TIME = 50.0
HUCE_MIN_START_TIME = 1.0
# HUCE_MAX_SCHE_PER_ELEVATOR = 1 # Enforced inside generation logic if huce_mode=True
# HUCE_MAX_UPDATE_PER_ELEVATOR = 1 # Enforced inherently by updated_elevators set

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


# --- Main Data Generation Logic ---
def generate_data(num_passengers, num_sche, num_update, max_time, min_interval_pass, max_interval_pass, start_time,
                  huce_mode=False, seed=None,
                  force_start_passengers=0, force_end_passengers=0,
                  burst_size=0, burst_time=None,
                  extreme_floor_ratio=0.0,
                  priority_bias='none', priority_bias_ratio=0.0,
                  priority_middle_range=DEFAULT_PRIORITY_MIDDLE_RANGE,
                  update_time_limit_ratio=DEFAULT_UPDATE_TIME_LIMIT_RATIO
                  ):
    """Generates interleaved elevator directives with granular timing constraints."""

    # Seeding
    if seed is not None: print(f"INFO: Using random seed: {seed}", file=sys.stderr); random.seed(seed)
    else: current_seed = int(time.time() * 1000); print(f"INFO: Using generated random seed: {current_seed}", file=sys.stderr); random.seed(current_seed)

    passenger_requests = []
    sche_requests = []
    update_requests = []
    last_passenger_id = 0
    current_time_pass = start_time

    # State Trackers
    last_sche_time_per_elevator = defaultdict(lambda: -float('inf')) # Tracks last SCHE time per elevator
    last_update_time_per_elevator = defaultdict(lambda: -float('inf')) # Tracks last UPDATE time involving this elevator
    last_sche_time_global = -float('inf') # Tracks the time of the most recent SCHE event globally
    last_update_time_global = -float('inf') # Tracks the time of the most recent UPDATE event globally
    updated_elevators = set() # Elevators that have been part of an UPDATE
    sche_assigned_elevators_count = defaultdict(int) # Tracks how many SCHE assigned per elevator (for HuCe mostly)


    # Pre-generation Validation & Info
    # (Validation logic mostly unchanged, adjusted HuCe info)
    if num_passengers < 0 or num_sche < 0 or num_update < 0: print("CRITICAL ERROR: Counts cannot be negative.", file=sys.stderr); return None
    if num_passengers == 0 and num_sche == 0 and num_update == 0: print("CRITICAL ERROR: Must request at least one directive.", file=sys.stderr); return None
    if huce_mode:
        print(f"--- Hu Ce Mode Activated ---", file=sys.stderr)
        if start_time < HUCE_MIN_START_TIME: print(f"WARNING (HuCe): start_time {start_time:.1f} adjusted to {HUCE_MIN_START_TIME:.1f}.", file=sys.stderr); start_time = HUCE_MIN_START_TIME
        if max_time > HUCE_MAX_TIME: print(f"WARNING (HuCe): max_time {max_time:.1f} adjusted to {HUCE_MAX_TIME:.1f}.", file=sys.stderr); max_time = HUCE_MAX_TIME
        total_reqs = num_passengers + num_sche + num_update
        # HuCe enforces max 1 UPDATE per elevator (implicit in updated_elevators)
        # HuCe enforces max 1 SCHE per elevator (will be checked during generation)
        if not (1 <= total_reqs <= HUCE_MAX_DIRECTIVES): print(f"CRITICAL ERROR (HuCe): Total directives ({total_reqs}) not in [1, {HUCE_MAX_DIRECTIVES}].", file=sys.stderr); return None
        print(f"INFO (HuCe): Generating {total_reqs} directives (P:{num_passengers}, S:{num_sche}, U:{num_update}). Time: [{start_time:.1f}, {max_time:.1f}].", file=sys.stderr)
        print(f"INFO (HuCe): Limits: Max 1 SCHE/elevator, Max 1 UPDATE involvement/elevator.", file=sys.stderr)
        print(f"-----------------------------", file=sys.stderr)
    # ... (Other validation unchanged) ...

    # Calculate Effective Time Limit for UPDATEs
    absolute_max_time = max_time
    total_duration = absolute_max_time - start_time
    if total_duration < 0: total_duration = 0
    effective_ratio = max(0.0, min(1.0, update_time_limit_ratio))
    update_max_time = start_time + total_duration * effective_ratio
    update_max_time = max(start_time, update_max_time)
    if effective_ratio < 1.0: print(f"INFO: Attempting to place UPDATEs before target time limit: {update_max_time:.1f}", file=sys.stderr)


    # --- 1. Generate Passenger Requests ---
    # (Passenger generation logic UNCHANGED)
    # ... (Identical to previous versions) ...
    if num_passengers > 0:
        # 1a. Forced Start
        if force_start_passengers > 0:
            for _ in range(force_start_passengers): last_passenger_id += 1; req_str = generate_passenger_request(last_passenger_id, start_time, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range); passenger_requests.append(req_str)
            current_time_pass = start_time
        # 1b. Middle Passengers (including burst)
        num_middle_passengers = num_passengers - force_start_passengers - force_end_passengers
        burst_added = False; actual_burst_time = -1.0; burst_insert_index = -1
        if burst_size > 0 and num_middle_passengers >= burst_size:
            time_span_middle = absolute_max_time - current_time_pass; time_span_middle = max(0.1, time_span_middle)
            if burst_time is not None: actual_burst_time = max(current_time_pass, min(burst_time, absolute_max_time))
            else: actual_burst_time = current_time_pass + time_span_middle / 2.0
            actual_burst_time = max(current_time_pass, min(actual_burst_time, absolute_max_time))
            burst_ratio = (actual_burst_time - current_time_pass) / time_span_middle if time_span_middle > 1e-9 else 0.0; relevant_middle_count = max(0, num_middle_passengers - burst_size)
            burst_insert_index = math.ceil(burst_ratio * relevant_middle_count); burst_insert_index = max(0, min(burst_insert_index, relevant_middle_count))
        elif burst_size > 0: print(f"INFO: Not enough 'middle' passengers ({num_middle_passengers}) for burst {burst_size}. Ignored.", file=sys.stderr); burst_size = 0
        middle_req_generated_count = 0
        if num_middle_passengers > 0:
            regular_middle_target = num_middle_passengers # Keep track of non-burst middle requests needed
            for i in range(num_middle_passengers + burst_size): # Loop enough times for all middle+burst
                is_burst_req_generated_this_iteration = False
                # Place burst at the calculated index relative to *regular* middle passengers
                if burst_size > 0 and not burst_added and middle_req_generated_count == burst_insert_index:
                    burst_gen_time = max(current_time_pass, min(actual_burst_time, absolute_max_time))
                    for _ in range(burst_size): last_passenger_id += 1; req_str = generate_passenger_request(last_passenger_id, burst_gen_time, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range); passenger_requests.append(req_str)
                    current_time_pass = burst_gen_time; burst_added = True; is_burst_req_generated_this_iteration = True
                # Generate Regular Middle Request if needed
                if middle_req_generated_count < regular_middle_target:
                    if middle_req_generated_count > 0 or force_start_passengers > 0 or is_burst_req_generated_this_iteration: # Advance time after first or after burst
                        interval = random.uniform(min_interval_pass, max_interval_pass); current_time_pass += interval
                    request_time_pass = max(start_time, min(current_time_pass, absolute_max_time))
                    last_passenger_id += 1; req_str = generate_passenger_request(last_passenger_id, request_time_pass, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range); passenger_requests.append(req_str)
                    middle_req_generated_count += 1; current_time_pass = request_time_pass
                    if current_time_pass >= absolute_max_time: break # Stop if max time reached
                elif burst_added and middle_req_generated_count >= regular_middle_target:
                    break # Stop if all regular middle passengers are generated and burst is done
        # 1c. Forced End
        if force_end_passengers > 0:
            actual_end_time = max(current_time_pass, absolute_max_time); actual_end_time = min(actual_end_time, absolute_max_time)
            for _ in range(force_end_passengers): last_passenger_id += 1; req_str = generate_passenger_request(last_passenger_id, actual_end_time, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range); passenger_requests.append(req_str)
            current_time_pass = actual_end_time


    # --- 2. Interleaved SCHE/UPDATE Generation with Granular Timing ---
    sche_generated_count = 0
    update_generated_count = 0
    all_elevator_ids = list(range(1, NUM_ELEVATORS + 1))
    max_iterations_combined = (num_sche + num_update) * NUM_ELEVATORS * 2 + 100 # Generous safety break
    current_iteration = 0

    while (sche_generated_count < num_sche or update_generated_count < num_update) and current_iteration < max_iterations_combined:
        current_iteration += 1

        min_next_sche_time = float('inf')
        min_next_update_time = float('inf')
        eligible_sche_candidates = [] # Store tuples of (time, elevator_id)
        eligible_update_candidates = [] # Store tuples of (time, elevator_a, elevator_b)

        # --- Calculate Earliest Possible Time for NEXT SCHE ---
        if sche_generated_count < num_sche:
            potential_sche_elevators = []
            for eid in all_elevator_ids:
                 # Check HuCe limit first
                 if huce_mode and sche_assigned_elevators_count[eid] >= 1:
                     continue
                 # Check if elevator was already part of an UPDATE
                 if eid in updated_elevators:
                     continue
                 potential_sche_elevators.append(eid)

            if potential_sche_elevators:
                min_time_for_any_sche = float('inf')
                for elevator_id in potential_sche_elevators:
                    # Calculate earliest time based on constraints for *this* elevator
                    earliest_time = start_time # Base constraint
                    # Constraint 1: >= 6.0s after last SCHE for *this* elevator
                    earliest_time = max(earliest_time, last_sche_time_per_elevator[elevator_id] + SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                    # Constraint 2: >= 12.5s after last UPDATE involving *this* elevator
                    earliest_time = max(earliest_time, last_update_time_per_elevator[elevator_id] + UPDATE_SCHE_MIN_INTERVAL)
                    # Constraint 3: >= 12.5s after the *global* last UPDATE
                    earliest_time = max(earliest_time, last_update_time_global + UPDATE_SCHE_MIN_INTERVAL)
                    # Constraint 4: SCHE vs SCHE for *different* elevators can be simultaneous (no constraint needed here based on last_sche_time_global)

                    # Ensure time does not exceed max_time
                    if earliest_time <= absolute_max_time + 1e-9:
                         min_time_for_any_sche = min(min_time_for_any_sche, earliest_time)

                min_next_sche_time = min_time_for_any_sche

                # Now find all elevators eligible AT that specific minimum time
                if min_next_sche_time != float('inf'):
                    for elevator_id in potential_sche_elevators:
                        sche_possible_time = start_time
                        sche_possible_time = max(sche_possible_time, last_sche_time_per_elevator[elevator_id] + SCHE_SAME_ELEVATOR_MIN_INTERVAL)
                        sche_possible_time = max(sche_possible_time, last_update_time_per_elevator[elevator_id] + UPDATE_SCHE_MIN_INTERVAL)
                        sche_possible_time = max(sche_possible_time, last_update_time_global + UPDATE_SCHE_MIN_INTERVAL)

                        # Check if this elevator can run AT the calculated global minimum sche time
                        if abs(sche_possible_time - min_next_sche_time) < 1e-9:
                             eligible_sche_candidates.append((min_next_sche_time, elevator_id))


        # --- Calculate Earliest Possible Time for NEXT UPDATE ---
        if update_generated_count < num_update:
            potential_update_pairs = []
            available_for_update = [eid for eid in all_elevator_ids if eid not in updated_elevators]

            if len(available_for_update) >= 2:
                 min_time_for_any_update = float('inf')
                 for idx_a in range(len(available_for_update)):
                     for idx_b in range(idx_a + 1, len(available_for_update)):
                         e_a = available_for_update[idx_a]
                         e_b = available_for_update[idx_b]

                         # Calculate earliest time based on constraints for *this* pair
                         earliest_time = start_time # Base constraint
                         # Constraint 1: >= 12.5s after last SCHE for elevator A
                         earliest_time = max(earliest_time, last_sche_time_per_elevator[e_a] + UPDATE_SCHE_MIN_INTERVAL)
                         # Constraint 2: >= 12.5s after last SCHE for elevator B
                         earliest_time = max(earliest_time, last_sche_time_per_elevator[e_b] + UPDATE_SCHE_MIN_INTERVAL)
                         # Constraint 3: >= 12.5s after the *global* last SCHE
                         earliest_time = max(earliest_time, last_sche_time_global + UPDATE_SCHE_MIN_INTERVAL)
                         # Constraint 4: UPDATE vs UPDATE can be simultaneous (no constraint needed based on last_update_time_global or per-elevator UPDATE times, handled by updated_elevators set)

                         # Check against UPDATE time limit ratio AND absolute max time
                         if earliest_time <= update_max_time + 1e-9 and earliest_time <= absolute_max_time + 1e-9:
                              min_time_for_any_update = min(min_time_for_any_update, earliest_time)

                 min_next_update_time = min_time_for_any_update

                 # Now find all pairs eligible AT that specific minimum time
                 if min_next_update_time != float('inf'):
                     for idx_a in range(len(available_for_update)):
                         for idx_b in range(idx_a + 1, len(available_for_update)):
                            e_a = available_for_update[idx_a]
                            e_b = available_for_update[idx_b]

                            update_possible_time = start_time
                            update_possible_time = max(update_possible_time, last_sche_time_per_elevator[e_a] + UPDATE_SCHE_MIN_INTERVAL)
                            update_possible_time = max(update_possible_time, last_sche_time_per_elevator[e_b] + UPDATE_SCHE_MIN_INTERVAL)
                            update_possible_time = max(update_possible_time, last_sche_time_global + UPDATE_SCHE_MIN_INTERVAL)

                            # Check if this pair can run AT the calculated global minimum update time
                            if abs(update_possible_time - min_next_update_time) < 1e-9:
                                eligible_update_candidates.append((min_next_update_time, e_a, e_b))


        # --- Decide which action to take (if any) ---
        actual_placement_time = min(min_next_sche_time, min_next_update_time)

        if actual_placement_time == float('inf'):
            # print("DEBUG: No further SCHE or UPDATE can be scheduled.", file=sys.stderr)
            break # Cannot schedule anything more

        # Filter candidates to only those matching the actual_placement_time
        possible_sche_actions = [c for c in eligible_sche_candidates if abs(c[0] - actual_placement_time) < 1e-9]
        possible_update_actions = [c for c in eligible_update_candidates if abs(c[0] - actual_placement_time) < 1e-9]

        can_place_sche = bool(possible_sche_actions) and sche_generated_count < num_sche
        can_place_update = bool(possible_update_actions) and update_generated_count < num_update

        decision = 'none'
        # Prioritize based on which event type determined the actual_placement_time,
        # or randomly if both were possible at the same minimum time.
        time_determined_by_sche = abs(actual_placement_time - min_next_sche_time) < 1e-9
        time_determined_by_update = abs(actual_placement_time - min_next_update_time) < 1e-9

        if can_place_sche and can_place_update:
            if time_determined_by_sche and time_determined_by_update : # Both possible at the exact same time
                rem_s = num_sche - sche_generated_count; rem_u = num_update - update_generated_count
                if random.uniform(0, rem_s + rem_u) < rem_s: decision = 'sche'
                else: decision = 'update'
            elif time_determined_by_sche: decision = 'sche'
            elif time_determined_by_update: decision = 'update'
            else: # Should not happen if logic is correct, fallback
                rem_s = num_sche - sche_generated_count; rem_u = num_update - update_generated_count
                if random.uniform(0, rem_s + rem_u) < rem_s: decision = 'sche'
                else: decision = 'update'
        elif can_place_sche: decision = 'sche'
        elif can_place_update: decision = 'update'
        else: decision = 'none' # Neither possible at this time


        # --- Execute chosen action ---
        if decision == 'sche':
            # Select one SCHE action randomly from the eligible ones at this time
            selected_time, assigned_elevator_id = random.choice(possible_sche_actions)
            final_event_time = round(selected_time, 1) # Round time for output
            req_str = generate_sche_request(final_event_time, assigned_elevator_id, SCHE_TARGET_FLOORS, SCHE_SPEEDS)
            sche_requests.append(req_str)

            # Update ALL relevant state trackers
            last_sche_time_per_elevator[assigned_elevator_id] = selected_time # Use precise time for constraints
            last_sche_time_global = max(last_sche_time_global, selected_time)
            sche_assigned_elevators_count[assigned_elevator_id] += 1
            sche_generated_count += 1
            # print(f"DEBUG: Placed SCHE for E{assigned_elevator_id} at {selected_time:.3f} (Rounded: {final_event_time:.1f})", file=sys.stderr)

        elif decision == 'update':
            # Select one UPDATE action randomly from the eligible ones at this time
            selected_time, e_a, e_b = random.choice(possible_update_actions)
            final_event_time = round(selected_time, 1) # Round time for output
            target_floor = random.choice(UPDATE_TARGET_FLOORS)
            req_str = generate_update_request(final_event_time, e_a, e_b, target_floor)
            update_requests.append(req_str)

            # Update ALL relevant state trackers
            last_update_time_per_elevator[e_a] = selected_time # Use precise time for constraints
            last_update_time_per_elevator[e_b] = selected_time
            last_update_time_global = max(last_update_time_global, selected_time)
            updated_elevators.add(e_a)
            updated_elevators.add(e_b)
            update_generated_count += 1
            # print(f"DEBUG: Placed UPDATE for E{e_a},E{e_b} at {selected_time:.3f} (Rounded: {final_event_time:.1f})", file=sys.stderr)

        elif decision == 'none':
             # This case should ideally not be reached if calculation of min times is correct
             # print(f"DEBUG: No action possible at time {actual_placement_time:.3f}. This might indicate an issue.", file=sys.stderr)
             # As a fallback, break to avoid infinite loop
             break

        # No explicit time advancement needed here, the next iteration will recalculate
        # the minimum possible times based on the updated state trackers.

    # End of combined SCHE/UPDATE loop

    # Report if quotas weren't met
    if sche_generated_count < num_sche: print(f"INFO: Successfully generated {sche_generated_count} SCHE requests (target was {num_sche}).", file=sys.stderr)
    if update_generated_count < num_update: print(f"INFO: Successfully generated {update_generated_count} UPDATE requests (target was {num_update}).", file=sys.stderr)


    # --- 4. Combine and Sort ---
    all_directives = passenger_requests + sche_requests + update_requests
    # Sort primarily by timestamp, use original index as tie-breaker if needed (though unlikely with float times)
    # Adding original index helps maintain relative order of simultaneous events if precision causes issues
    directives_with_indices = list(enumerate(all_directives))
    directives_with_indices.sort(key=lambda item: (get_timestamp_from_string(item[1]), item[0]))
    all_directives = [item[1] for item in directives_with_indices]


    # --- 5. Final Summary ---
    final_passenger_count = sum(1 for req in all_directives if "-PRI-" in req)
    final_sche_count = sum(1 for req in all_directives if "SCHE-" in req)
    final_update_count = sum(1 for req in all_directives if "UPDATE-" in req)
    print(f"\n--- Generation Summary ---", file=sys.stderr)
    print(f"Total Directives Generated: {len(all_directives)}", file=sys.stderr)
    print(f"  Passenger Requests: {final_passenger_count}", file=sys.stderr)
    print(f"  SCHE Requests:      {final_sche_count}", file=sys.stderr)
    print(f"  UPDATE Requests:    {final_update_count}", file=sys.stderr)
    updated_str = str(sorted(list(updated_elevators))) if updated_elevators else "None"
    print(f"  Elevators Used in UPDATE: {updated_str}", file=sys.stderr)
    sche_counts_str = ", ".join(f"E{k}:{v}" for k, v in sorted(sche_assigned_elevators_count.items()) if v > 0) if any(sche_assigned_elevators_count.values()) else "None"
    print(f"  SCHE Counts per Elevator: {sche_counts_str}", file=sys.stderr)
    print(f"--------------------------", file=sys.stderr)

    return all_directives


# --- Main Function (Argument Parsing & Calling generate_data) ---
def main():
    # (main function largely UNCHANGED, HuCe help text updated slightly)
    parser = argparse.ArgumentParser(
        description="Generate Elevator Test Data (HW7: Passengers + Interleaved SCHE/UPDATE + Granular Timing Rules)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # Core Parameters
    parser.add_argument("-np", "--num-passengers", type=int, default=DEFAULT_NUM_PASSENGERS, help="Target number of passenger requests.")
    parser.add_argument("-ns", "--num-sche", type=int, default=DEFAULT_NUM_SCHE, help="Target number of SCHE requests.")
    parser.add_argument("-nu", "--num-update", type=int, default=DEFAULT_NUM_UPDATE, help="Target number of UPDATE requests.")
    parser.add_argument("-t", "--max-time", type=float, default=DEFAULT_MAX_TIME, help="Maximum timestamp for any request.")
    parser.add_argument("--start-time", type=float, default=DEFAULT_START_TIME, help="Earliest timestamp for any request.")
    parser.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL, help="Minimum time interval between consecutive PASSENGER requests (approx).")
    parser.add_argument("--max-interval", type=float, default=DEFAULT_MAX_INTERVAL, help="Maximum time interval between consecutive PASSENGER requests (approx).")
    parser.add_argument("-o", "--output-file", type=str, default=None, help="Output file (default: stdout).")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")
    # Hu Ce Mode
    parser.add_argument("--hce", action='store_true', help=f"Apply stricter Hu Ce constraints: Total <= {HUCE_MAX_DIRECTIVES}, Time [{HUCE_MIN_START_TIME:.1f}, {HUCE_MAX_TIME:.1f}], Max 1 SCHE/elevator, Max 1 UPDATE involvement/elevator.")
    # Passenger Special Cases
    pgroup = parser.add_argument_group('Passenger Request Special Cases')
    pgroup.add_argument("--force-start-passengers", type=int, default=0, help="Generate N passengers exactly at start-time.")
    pgroup.add_argument("--force-end-passengers", type=int, default=0, help="Generate N passengers exactly at max-time.")
    pgroup.add_argument("--burst-size", type=int, default=0, help="Generate a burst of N passengers at approx. burst-time.")
    pgroup.add_argument("--burst-time", type=float, default=None, help="Approx timestamp for passenger burst (defaults to midpoint if burst-size > 0).")
    pgroup.add_argument("--extreme-floor-ratio", type=float, default=0.0, help=f"Probability (0.0-1.0) of {ALL_FLOORS[0]}<->{ALL_FLOORS[-1]} passenger requests.")
    # Passenger Priority Control
    prigroup = parser.add_argument_group('Passenger Priority Control')
    prigroup.add_argument("--priority-bias", choices=['none', 'extremes', 'middle'], default='none', help="Bias priority generation.")
    prigroup.add_argument("--priority-bias-ratio", type=float, default=0.5, help="Probability (0.0-1.0) of applying the bias.")
    prigroup.add_argument("--priority-middle-range", type=int, default=DEFAULT_PRIORITY_MIDDLE_RANGE, help="Range width for 'middle' bias (e.g., 20 -> ~40-60).")
    # HW7 Timing Control
    timing_group = parser.add_argument_group('HW7 Timing Control')
    timing_group.add_argument("--update-time-limit-ratio", type=float, default=DEFAULT_UPDATE_TIME_LIMIT_RATIO, help="Attempt to place UPDATE requests before this fraction of the total duration (start_time + (max_time-start_time)*ratio). Value between 0.0 and 1.0.")

    args = parser.parse_args()

    # Argument Validation & HuCe Enforcement
    adjusted_np = args.num_passengers; adjusted_ns = args.num_sche; adjusted_nu = args.num_update
    adjusted_start_time = args.start_time; adjusted_max_time = args.max_time
    if adjusted_np < 0 or adjusted_ns < 0 or adjusted_nu < 0: print("ERROR: Counts cannot be negative.", file=sys.stderr); sys.exit(1)
    if args.hce:
        print("--- Applying Hu Ce Constraints ---", file=sys.stderr)
        if adjusted_start_time < HUCE_MIN_START_TIME: print(f"  Adjusting start_time: {adjusted_start_time:.1f} -> {HUCE_MIN_START_TIME:.1f}", file=sys.stderr); adjusted_start_time = HUCE_MIN_START_TIME
        if adjusted_max_time > HUCE_MAX_TIME: print(f"  Adjusting max_time: {adjusted_max_time:.1f} -> {HUCE_MAX_TIME:.1f}", file=sys.stderr); adjusted_max_time = HUCE_MAX_TIME
        if adjusted_max_time < adjusted_start_time: print(f"ERROR (HuCe): Invalid time range.", file=sys.stderr); sys.exit(1)
        max_possible_updates = NUM_ELEVATORS // 2
        if adjusted_nu > max_possible_updates: print(f"  Adjusting num_update: {adjusted_nu} -> {max_possible_updates} (max 1 UPDATE per elevator)", file=sys.stderr); adjusted_nu = max_possible_updates
        # For SCHE, the generator now handles the 1-per-elevator limit directly in HuCe mode
        # We only adjust if the *requested* number exceeds the *total* number of elevators
        if adjusted_ns > NUM_ELEVATORS: print(f"  Adjusting num_sche: {adjusted_ns} -> {NUM_ELEVATORS} (max 1 SCHE per elevator)", file=sys.stderr); adjusted_ns = NUM_ELEVATORS
        total_reqs = adjusted_np + adjusted_ns + adjusted_nu
        if total_reqs == 0: print("ERROR (HuCe): Total directives cannot be 0.", file=sys.stderr); sys.exit(1)
        elif total_reqs > HUCE_MAX_DIRECTIVES:
            print(f"  Total requested directives ({total_reqs}) exceeds HuCe limit ({HUCE_MAX_DIRECTIVES}).", file=sys.stderr); excess = total_reqs - HUCE_MAX_DIRECTIVES
            reduce_np = min(adjusted_np, excess); adjusted_np -= reduce_np; excess -= reduce_np
            if excess > 0: reduce_ns = min(adjusted_ns, excess); adjusted_ns -= reduce_ns; excess -= reduce_ns
            if excess > 0: reduce_nu = min(adjusted_nu, excess); adjusted_nu -= reduce_nu; excess -= reduce_nu
            print(f"  Adjusting counts -> P:{adjusted_np}, S:{adjusted_ns}, U:{adjusted_nu}", file=sys.stderr)
        # (Passenger special case validation unchanged)
        if adjusted_np > 0:
            total_special = args.force_start_passengers + args.force_end_passengers + args.burst_size
            if total_special > adjusted_np: print(f"ERROR (HuCe): Sum of forced/burst passengers ({total_special}) exceeds adjusted P ({adjusted_np}).", file=sys.stderr); sys.exit(1)
        elif args.force_start_passengers > 0 or args.force_end_passengers > 0 or args.burst_size > 0:
             print(f"  INFO (HuCe): Forced/burst P options ignored as adjusted P is 0.", file=sys.stderr); args.force_start_passengers = 0; args.force_end_passengers = 0; args.burst_size = 0
        print("---------------------------------", file=sys.stderr)

    if not (0.0 <= args.update_time_limit_ratio <= 1.0): print(f"WARNING: --update-time-limit-ratio invalid. Clamping to 1.0.", file=sys.stderr); args.update_time_limit_ratio = 1.0

    # Burst Time Defaulting/Clamping
    adjusted_burst_time = args.burst_time
    if args.burst_size > 0 and adjusted_np > 0:
        if adjusted_burst_time is None: adjusted_burst_time = (adjusted_start_time + adjusted_max_time) / 2.0; print(f"INFO: Defaulting burst time to midpoint: {adjusted_burst_time:.1f}", file=sys.stderr)
        original_burst_time = adjusted_burst_time; adjusted_burst_time = max(adjusted_start_time, min(adjusted_burst_time, adjusted_max_time))
        if abs(adjusted_burst_time - original_burst_time) > 1e-9 : print(f"INFO: Adjusted burst time from {original_burst_time:.1f} to {adjusted_burst_time:.1f}.", file=sys.stderr)

    # Generate Data
    generated_directives = generate_data(
        num_passengers=adjusted_np, num_sche=adjusted_ns, num_update=adjusted_nu, max_time=adjusted_max_time, min_interval_pass=args.min_interval, max_interval_pass=args.max_interval, start_time=adjusted_start_time,
        huce_mode=args.hce, seed=args.seed, force_start_passengers=args.force_start_passengers, force_end_passengers=args.force_end_passengers, burst_size=args.burst_size, burst_time=adjusted_burst_time,
        extreme_floor_ratio=args.extreme_floor_ratio, priority_bias=args.priority_bias, priority_bias_ratio=args.priority_bias_ratio, priority_middle_range=args.priority_middle_range,
        update_time_limit_ratio=args.update_time_limit_ratio
    )
    if generated_directives is None: print("ERROR: Data generation failed.", file=sys.stderr); sys.exit(1)

    # Output
    output_content = "\n".join(generated_directives)
    if args.output_file:
        try:
            with open(args.output_file, 'w') as f:
                f.write(output_content)
                if generated_directives: f.write("\n") # Add trailing newline if not empty
            print(f"\nSuccessfully generated {len(generated_directives)} directives to {args.output_file}", file=sys.stderr)
        except IOError as e: print(f"ERROR: Could not write to file {args.output_file}: {e}", file=sys.stderr); sys.exit(1)
    else:
        if output_content: print(output_content)

# --- Script Entry Point ---
if __name__ == "__main__":
    main()

# --- Example Presets (Illustrative) ---
"""
GEN_PRESET_COMMANDS = [
    # ID: HCE_INTERLEAVED_SIMPLE
    "gen.py --hce -np 20 -ns 3 -nu 2 -t 45.0 --update-time-limit-ratio 0.8", # Total 25
    # ID: PUB_INTERLEAVED_MODERATE
    "gen.py -np 40 -ns 8 -nu 3 -t 90.0 --update-time-limit-ratio 0.7", # Total 51
    # ID: PUB_SIMULTANEOUS_SCHE (Test 0s SCHE-SCHE diff elev)
    "gen.py -np 5 -ns 8 -nu 0 -t 60.0 --seed 123", # Expect some SCHEs at same time for different elevators
    # ID: PUB_SIMULTANEOUS_MIXED (Test 0s SCHE-SCHE/UPDATE-UPDATE, 12.5s SCHE-UPDATE)
    "gen.py -np 10 -ns 6 -nu 3 -t 70.0 --seed 456", # Expect some simultaneous, check 12.5s cross-type gap
    # ID: HCE_UPDATE_ONLY_EARLY
    "gen.py --hce -np 5 -ns 0 -nu 3 -t 40.0", # Should place UPDATEs early, potentially simultaneously
    # ID: HCE_SCHE_ONLY
    "gen.py --hce -np 5 -ns 6 -nu 0 -t 50.0", # Max 1 SCHE/elevator, potentially simultaneous if allowed by time/rules
    # ID: PUB_SCHE_MULTI_SAME_ELEVATOR (Test 6s constraint)
    "gen.py -np 10 -ns 10 -nu 0 -t 100.0", # Should show SCHE for same elevator >= 6s apart
    # ID: PUB_INTERLEAVED_STRESS
    "gen.py -np 50 -ns 15 -nu 3 -t 150.0 --update-time-limit-ratio 0.75", # Total 68 (mix of intervals)
    # ID: HCE_MAX_ALL_INTERLEAVED
    "gen.py --hce -np 61 -ns 3 -nu 3 -t 48.0 --update-time-limit-ratio 0.9", # Total 70 - tight scheduling
]
"""
# --- END OF MODIFIED gen.py (HW7 - Granular Timing Rules) ---