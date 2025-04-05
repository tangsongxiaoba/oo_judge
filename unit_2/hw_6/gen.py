# --- START OF UPDATED gen.py (with FULL HuCe constraints) ---
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
SCHE_MIN_INTERVAL_SAME_ELEVATOR = 12

# --- Default Generation Parameters ---
DEFAULT_NUM_PASSENGERS = 15
DEFAULT_NUM_SCHE = 5
DEFAULT_MAX_TIME = 50.0 # Default already matches HuCe max
DEFAULT_MIN_INTERVAL = 0.0
DEFAULT_MAX_INTERVAL = 1.4
DEFAULT_START_TIME = 1.0 # Default already matches HuCe min
DEFAULT_PRIORITY_MIDDLE_RANGE = 20

# --- Hu Ce (Mutual Testing) Specific Constraints ---
HUCE_MAX_DIRECTIVES = 70
HUCE_MAX_TIME = 50.0
HUCE_MIN_START_TIME = 1.0 # Renamed for clarity
HUCE_MAX_SCHE_PER_ELEVATOR = 1

def get_timestamp_from_string(request_str):
    """Extracts the float timestamp from a request string."""
    try:
        end_bracket_index = request_str.find(']')
        if end_bracket_index == -1: return -1.0
        timestamp_str = request_str[1:end_bracket_index]
        return float(timestamp_str)
    except (ValueError, IndexError):
        return -1.0

def generate_passenger_request(passenger_id, current_time, floors,
                               extreme_floor_ratio=0.0,
                               priority_bias='none', priority_bias_ratio=0.0,
                               priority_middle_range=DEFAULT_PRIORITY_MIDDLE_RANGE):
    """Generates a single, valid passenger request string."""
    priority = -1
    apply_bias = random.random() < priority_bias_ratio
    if apply_bias and priority_bias != 'none':
        if priority_bias == 'extremes':
            priority = random.choice([MIN_PRIORITY, MAX_PRIORITY])
        elif priority_bias == 'middle':
            half_range = priority_middle_range // 2
            lower_bound = max(MIN_PRIORITY, MID_PRIORITY - half_range)
            upper_bound = min(MAX_PRIORITY, MID_PRIORITY + half_range)
            if lower_bound > upper_bound: lower_bound = upper_bound = MID_PRIORITY
            priority = random.randint(lower_bound, upper_bound)
    if priority == -1: # Default if no bias applied or range was invalid
        priority = random.randint(MIN_PRIORITY, MAX_PRIORITY)

    start_floor, end_floor = None, None
    if random.random() < extreme_floor_ratio:
        extreme_floors = [floors[0], floors[-1]]
        start_floor = random.choice(extreme_floors)
        end_floor = extreme_floors[1] if start_floor == extreme_floors[0] else extreme_floors[0]
    else:
        while True:
            start_floor = random.choice(floors)
            end_floor = random.choice(floors)
            if start_floor != end_floor: break

    formatted_time = round(current_time, 1)
    return (
        f"[{formatted_time:.1f}]{passenger_id}-PRI-{priority}"
        f"-FROM-{start_floor}-TO-{end_floor}"
    )

def generate_sche_request(current_time, elevator_id, target_floors, speeds):
    """Generates a single Temporary Scheduling (SCHE) request string."""
    speed = random.choice(speeds)
    target_floor = random.choice(target_floors)
    formatted_time = round(current_time, 1)
    return f"[{formatted_time:.1f}]SCHE-{elevator_id}-{speed}-{target_floor}"


def generate_data(num_passengers, num_sche, max_time, min_interval, max_interval, start_time,
                  huce_mode=False, seed=None,
                  force_start_passengers=0, force_end_passengers=0,
                  burst_size=0, burst_time=None,
                  extreme_floor_ratio=0.0,
                  priority_bias='none', priority_bias_ratio=0.0,
                  priority_middle_range=DEFAULT_PRIORITY_MIDDLE_RANGE
                  ):
    """Generates a list of elevator directives with constraints."""

    # Seeding (moved earlier for clarity)
    if seed is not None:
        print(f"INFO: Using random seed: {seed}", file=sys.stderr)
        random.seed(seed)
    else:
        current_seed = int(time.time() * 1000)
        print(f"INFO: Using generated random seed: {current_seed}", file=sys.stderr)
        random.seed(current_seed)

    requests = []
    last_passenger_id = 0
    last_sche_time_per_elevator = defaultdict(lambda: -float('inf'))
    sche_assigned_elevators_huce = set() # Only used in HuCe mode

    # --- Pre-generation Validation & Info (Moved from main for internal consistency) ---
    # Basic non-negative check
    if num_passengers < 0 or num_sche < 0:
         print("CRITICAL ERROR: Number of passengers and SCHE requests cannot be negative.", file=sys.stderr)
         return None # Cannot proceed
    # At least one directive
    if num_passengers == 0 and num_sche == 0:
        print("CRITICAL ERROR: Must request at least one passenger or SCHE directive.", file=sys.stderr)
        return None # Cannot proceed

    # Specific HuCe checks (only if huce_mode is True)
    if huce_mode:
        print(f"--- Hu Ce Mode Activated ---", file=sys.stderr)
        # Check Max SCHE per elevator (already implicitly handled later, but good to state)
        if num_sche > NUM_ELEVATORS:
             print(f"INFO (HuCe): Requested {num_sche} SCHE, but max 1 per elevator allowed. Will generate at most {NUM_ELEVATORS}.", file=sys.stderr)
             # Note: Actual generation logic caps this later

        # Check time constraints
        if start_time < HUCE_MIN_START_TIME:
            print(f"INFO (HuCe): Requested start_time {start_time:.1f} < {HUCE_MIN_START_TIME:.1f}. Adjusting start_time to {HUCE_MIN_START_TIME:.1f}.", file=sys.stderr)
            start_time = HUCE_MIN_START_TIME
        if max_time > HUCE_MAX_TIME:
             print(f"INFO (HuCe): Requested max_time {max_time:.1f} > {HUCE_MAX_TIME:.1f}. Adjusting max_time to {HUCE_MAX_TIME:.1f}.", file=sys.stderr)
             max_time = HUCE_MAX_TIME

        # Check total directives (already pre-adjusted in main, this is a confirmation)
        total_reqs = num_passengers + num_sche
        if not (1 <= total_reqs <= HUCE_MAX_DIRECTIVES):
             # This case should theoretically not be reached if main() adjusted correctly
             print(f"CRITICAL ERROR (HuCe): Total directives ({total_reqs}) not in range [1, {HUCE_MAX_DIRECTIVES}] after adjustment. Aborting.", file=sys.stderr)
             return None
        print(f"INFO (HuCe): Generating {total_reqs} total directives (Passengers: {num_passengers}, SCHE: {num_sche}).", file=sys.stderr)
        print(f"INFO (HuCe): Time range: [{start_time:.1f}, {max_time:.1f}]. Max SCHE/Elevator: {HUCE_MAX_SCHE_PER_ELEVATOR}.", file=sys.stderr)
        print(f"-----------------------------", file=sys.stderr)

    else: # Non-HuCe mode warnings
         if not (1 <= num_passengers <= 100) and num_passengers != 0 :
              print(f"WARNING (Non-HuCe): Num passengers ({num_passengers}) outside typical range [1, 100].", file=sys.stderr)
         # Max SCHE for non-HuCe is 20 according to public test limits
         if num_sche > 20:
              print(f"WARNING (Non-HuCe): Num SCHE ({num_sche}) exceeds public test limit (<= 20).", file=sys.stderr)


    # --- Parameter Validation (Continued: Burst, Force, Priority) ---
    if force_start_passengers < 0 or force_end_passengers < 0 or burst_size < 0:
        print("ERROR: Forced passenger counts/burst size cannot be negative.", file=sys.stderr)
        return None
    # Adjusted validation: check against potentially reduced num_passengers
    if num_passengers > 0:
        total_special_passengers = force_start_passengers + force_end_passengers + burst_size
        if total_special_passengers > num_passengers:
            print(f"ERROR: Sum of forced/burst passengers ({total_special_passengers}) exceeds total available passengers ({num_passengers}). Reduce counts.", file=sys.stderr)
            return None
    elif burst_size > 0 or force_start_passengers > 0 or force_end_passengers > 0:
        # If num_passengers became 0 due to HuCe adjustment
         print(f"INFO: Burst/Force passenger options ignored as num_passengers is 0.", file=sys.stderr)
         force_start_passengers = force_end_passengers = burst_size = 0 # Reset them


    if priority_bias not in ['none', 'extremes', 'middle']:
        print(f"WARNING: Invalid priority bias '{priority_bias}'. Defaulting to 'none'.", file=sys.stderr)
        priority_bias = 'none'
    if not (0.0 <= priority_bias_ratio <= 1.0):
         print(f"WARNING: Priority bias ratio ({priority_bias_ratio}) outside [0, 1]. Clamping.", file=sys.stderr)
         priority_bias_ratio = max(0.0, min(1.0, priority_bias_ratio))
    if priority_middle_range <= 0:
        print(f"WARNING: Priority middle range ({priority_middle_range}) must be positive. Using default {DEFAULT_PRIORITY_MIDDLE_RANGE}.", file=sys.stderr)
        priority_middle_range = DEFAULT_PRIORITY_MIDDLE_RANGE

    # --- Priority Info ---
    # (Keep this logging as is)
    if priority_bias != 'none':
        # ... (logging code unchanged) ...
        pass
    else:
        print(f"INFO: Priority generation: Uniform random ({MIN_PRIORITY}-{MAX_PRIORITY}).", file=sys.stderr)


    # === Generation Logic ===
    # (Passenger and SCHE generation logic remains the same as the previous version
    #  which correctly handles the 6s interval and HuCe 1-SCHE-per-elevator limit)
    # ... (Sections 1a, 1b, 1c for passenger generation unchanged) ...
    # ... (Section 2 for SCHE generation unchanged - it correctly uses
    #      last_sche_time_per_elevator and sche_assigned_elevators_huce) ...

    # --- 1. Generate Passenger Requests ---
    passenger_requests = []
    current_time_pass = start_time
    if num_passengers > 0:
        # 1a. Forced Start
        if force_start_passengers > 0:
            for _ in range(force_start_passengers):
                 last_passenger_id += 1
                 req_str = generate_passenger_request(last_passenger_id, start_time, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range)
                 passenger_requests.append(req_str)
            current_time_pass = start_time

        # 1b. Middle Passengers (including burst)
        num_middle_passengers = num_passengers - force_start_passengers - force_end_passengers
        burst_added = False
        actual_burst_time = -1.0
        burst_insert_index = -1
        if burst_size > 0 and num_middle_passengers >= burst_size: # Ensure enough middle passengers for burst
            time_span = max_time - start_time
            actual_burst_time = max(start_time, min(burst_time if burst_time is not None else (start_time + max_time) / 2.0, max_time))
            if time_span > 0:
                burst_ratio = (actual_burst_time - start_time) / time_span
                relevant_middle_count = max(0, num_middle_passengers - burst_size)
                burst_insert_index = math.ceil(burst_ratio * relevant_middle_count)
                burst_insert_index = max(0, min(burst_insert_index, relevant_middle_count))
            else:
                burst_insert_index = 0
        elif burst_size > 0:
             print(f"INFO: Not enough 'middle' passengers ({num_middle_passengers}) to create distinct burst of size {burst_size}. Burst ignored.", file=sys.stderr)
             burst_size = 0 # Effectively disable burst

        middle_req_generated_count = 0
        if num_middle_passengers > 0:
            max_iterations = num_middle_passengers
            for i in range(max_iterations):
                is_burst_req = False
                # Insert burst if conditions met
                if burst_size > 0 and not burst_added and middle_req_generated_count == burst_insert_index:
                    burst_gen_time = max(current_time_pass, min(actual_burst_time, max_time))
                    for _ in range(burst_size):
                        last_passenger_id += 1
                        req_str = generate_passenger_request(last_passenger_id, burst_gen_time, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range)
                        passenger_requests.append(req_str)
                        middle_req_generated_count += 1
                    current_time_pass = burst_gen_time
                    burst_added = True
                    is_burst_req = True # Flag that these were burst reqs

                # Generate Regular Middle Request if not part of the just-added burst and quota not met
                if middle_req_generated_count < num_middle_passengers and not is_burst_req:
                    # Increment time logic (only after first or if burst was added)
                    if middle_req_generated_count > 0 or force_start_passengers > 0 or burst_added:
                        interval = random.uniform(min_interval, max_interval)
                        current_time_pass += interval
                    current_time_pass = max(start_time, min(current_time_pass, max_time))

                    last_passenger_id += 1
                    req_str = generate_passenger_request(last_passenger_id, current_time_pass, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range)
                    passenger_requests.append(req_str)
                    middle_req_generated_count += 1

                    if current_time_pass >= max_time and middle_req_generated_count < num_middle_passengers:
                         break # Stop if max time reached

        # 1c. Forced End
        if force_end_passengers > 0:
            actual_end_time = max(current_time_pass, max_time)
            actual_end_time = min(actual_end_time, max_time)
            for _ in range(force_end_passengers):
                 last_passenger_id += 1
                 req_str = generate_passenger_request(last_passenger_id, actual_end_time, ALL_FLOORS, extreme_floor_ratio, priority_bias, priority_bias_ratio, priority_middle_range)
                 passenger_requests.append(req_str)

    # --- 2. Generate SCHE Requests ---
    sche_requests = []
    if num_sche > 0:
        sche_generated_count = 0
        current_time_sche = start_time
        all_elevator_ids = list(range(1, NUM_ELEVATORS + 1))

        for i in range(num_sche): # Loop for the *target* number of SCHE requests
            candidate_time_sche = current_time_sche # Start checking from current time
            if i > 0: # Add interval after the first attempt
                interval = random.uniform(min_interval, max_interval)
                candidate_time_sche += interval
            candidate_time_sche = max(start_time, min(candidate_time_sche, max_time)) # Clamp candidate

            found_elevator_for_this_req = False
            loop_count = 0 # Safety break
            max_loops = NUM_ELEVATORS * 5 + 10 # Heuristic limit

            while candidate_time_sche <= max_time and loop_count < max_loops:
                loop_count+=1
                eligible_elevators = []
                potential_ids = []
                if huce_mode:
                    potential_ids = [eid for eid in all_elevator_ids if eid not in sche_assigned_elevators_huce]
                    random.shuffle(potential_ids)
                    for elevator_id in potential_ids:
                        min_next_time = last_sche_time_per_elevator[elevator_id] + SCHE_MIN_INTERVAL_SAME_ELEVATOR
                        if candidate_time_sche >= min_next_time:
                            eligible_elevators.append(elevator_id)
                            break # HuCe: take first valid
                else:
                    potential_ids = list(all_elevator_ids)
                    random.shuffle(potential_ids)
                    for elevator_id in potential_ids:
                         min_next_time = last_sche_time_per_elevator[elevator_id] + SCHE_MIN_INTERVAL_SAME_ELEVATOR
                         if candidate_time_sche >= min_next_time:
                              eligible_elevators.append(elevator_id)
                    # Collect all eligible in non-HuCe

                if eligible_elevators:
                    assigned_elevator_id = -1
                    if huce_mode:
                        assigned_elevator_id = eligible_elevators[0]
                        sche_assigned_elevators_huce.add(assigned_elevator_id)
                    else:
                        assigned_elevator_id = random.choice(eligible_elevators)

                    final_sche_time = candidate_time_sche # Use the time that worked
                    req_str = generate_sche_request(final_sche_time, assigned_elevator_id, SCHE_TARGET_FLOORS, SCHE_SPEEDS)
                    sche_requests.append(req_str)
                    last_sche_time_per_elevator[assigned_elevator_id] = final_sche_time
                    sche_generated_count += 1
                    found_elevator_for_this_req = True
                    current_time_sche = final_sche_time # Update time for next interval calc
                    break # Success for this SCHE request (i)

                else: # No eligible elevator at candidate_time_sche
                    min_possible_next_time = float('inf')
                    ids_to_consider = []
                    if huce_mode:
                         ids_to_consider = [eid for eid in all_elevator_ids if eid not in sche_assigned_elevators_huce]
                    else:
                         ids_to_consider = all_elevator_ids

                    if not ids_to_consider: break # No elevators left (HuCe)

                    for elevator_id in ids_to_consider:
                         min_possible_next_time = min(min_possible_next_time, last_sche_time_per_elevator[elevator_id] + SCHE_MIN_INTERVAL_SAME_ELEVATOR)

                    # Advance candidate time
                    new_time_sche = max(candidate_time_sche + 0.01, min_possible_next_time, start_time)

                    if new_time_sche > max_time: break # Cannot schedule within time limits
                    candidate_time_sche = new_time_sche # Retry with the new advanced time
                    # Loop continues

            # End of while loop for finding a slot
            if not found_elevator_for_this_req:
                 # print(f"INFO: Could not generate SCHE request {i+1} due to time/elevator constraints.", file=sys.stderr)
                 break # Stop trying to generate further SCHE requests

        if sche_generated_count < num_sche:
            print(f"INFO: Successfully generated {sche_generated_count} SCHE requests (target was {num_sche}).", file=sys.stderr)


    # --- 3. Combine and Sort ---
    # REMOVED: HuCe truncation here - it's done pre-generation in main()
    all_directives = passenger_requests + sche_requests
    all_directives.sort(key=get_timestamp_from_string)

    # --- 4. Final Summary ---
    final_passenger_count = sum(1 for req in all_directives if "-PRI-" in req)
    final_sche_count = sum(1 for req in all_directives if "SCHE-" in req)
    print(f"\n--- Generation Summary ---", file=sys.stderr)
    print(f"Total Directives Generated: {len(all_directives)}", file=sys.stderr)
    print(f"  Passenger Requests: {final_passenger_count}", file=sys.stderr)
    print(f"  SCHE Requests:      {final_sche_count}", file=sys.stderr)
    if huce_mode and sche_assigned_elevators_huce:
        print(f"  Elevators Assigned SCHE (HuCe): {sorted(list(sche_assigned_elevators_huce))}", file=sys.stderr)
    print(f"--------------------------", file=sys.stderr)

    return all_directives


def main():
    parser = argparse.ArgumentParser(
        description="Generate Elevator Test Data (HW6: Passengers + SCHE)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter # Show defaults in help
    )

    # --- Core Parameters ---
    parser.add_argument("-np", "--num-passengers", type=int, default=DEFAULT_NUM_PASSENGERS, help="Target number of passenger requests.")
    parser.add_argument("-ns", "--num-sche", type=int, default=DEFAULT_NUM_SCHE, help="Target number of SCHE requests.")
    parser.add_argument("-t", "--max-time", type=float, default=DEFAULT_MAX_TIME, help="Maximum timestamp for any request.")
    parser.add_argument("--start-time", type=float, default=DEFAULT_START_TIME, help="Earliest timestamp for any request.")
    parser.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL, help="Minimum time interval between consecutive requests (approx).")
    parser.add_argument("--max-interval", type=float, default=DEFAULT_MAX_INTERVAL, help="Maximum time interval between consecutive requests (approx).")
    parser.add_argument("-o", "--output-file", type=str, default=None, help="Output file (default: stdout).")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")

    # --- Hu Ce Mode ---
    parser.add_argument("--hce", action='store_true', help=f"Apply stricter Hu Ce constraints: Total <= {HUCE_MAX_DIRECTIVES}, Time [{HUCE_MIN_START_TIME:.1f}, {HUCE_MAX_TIME:.1f}], Max {HUCE_MAX_SCHE_PER_ELEVATOR} SCHE/elevator.")

    # --- Boundary/Special Cases ---
    pgroup = parser.add_argument_group('Passenger Request Special Cases')
    pgroup.add_argument("--force-start-passengers", type=int, default=0, help="Generate N passengers exactly at start-time.")
    pgroup.add_argument("--force-end-passengers", type=int, default=0, help="Generate N passengers exactly at max-time.")
    pgroup.add_argument("--burst-size", type=int, default=0, help="Generate a burst of N passengers at approx. burst-time.")
    pgroup.add_argument("--burst-time", type=float, default=None, help="Approx timestamp for passenger burst (defaults to midpoint if burst-size > 0).")
    pgroup.add_argument("--extreme-floor-ratio", type=float, default=0.0, help=f"Probability (0.0-1.0) of B4<->F7 passenger requests.")

    # --- Priority Control ---
    prigroup = parser.add_argument_group('Passenger Priority Control')
    prigroup.add_argument("--priority-bias", choices=['none', 'extremes', 'middle'], default='none', help="Bias priority generation.")
    prigroup.add_argument("--priority-bias-ratio", type=float, default=0.5, help="Probability (0.0-1.0) of applying the bias.")
    prigroup.add_argument("--priority-middle-range", type=int, default=DEFAULT_PRIORITY_MIDDLE_RANGE, help="Range width for 'middle' bias (e.g., 20 -> ~40-60).")

    args = parser.parse_args()

    # --- Argument Validation & HuCe Enforcement ---
    adjusted_np = args.num_passengers
    adjusted_ns = args.num_sche
    adjusted_start_time = args.start_time
    adjusted_max_time = args.max_time

    if adjusted_np < 0 or adjusted_ns < 0:
         print("ERROR: Number of passengers and SCHE requests cannot be negative.", file=sys.stderr)
         sys.exit(1)

    if args.hce:
        print("--- Applying Hu Ce Constraints ---", file=sys.stderr)
        # 1. Time clamping
        if adjusted_start_time < HUCE_MIN_START_TIME:
            print(f"  Adjusting start_time: {adjusted_start_time:.1f} -> {HUCE_MIN_START_TIME:.1f}", file=sys.stderr)
            adjusted_start_time = HUCE_MIN_START_TIME
        if adjusted_max_time > HUCE_MAX_TIME:
             print(f"  Adjusting max_time: {adjusted_max_time:.1f} -> {HUCE_MAX_TIME:.1f}", file=sys.stderr)
             adjusted_max_time = HUCE_MAX_TIME
        if adjusted_max_time < adjusted_start_time:
             print(f"ERROR (HuCe): Adjusted max_time ({adjusted_max_time:.1f}) is less than adjusted start_time ({adjusted_start_time:.1f}). Invalid range.", file=sys.stderr)
             sys.exit(1)

        # 2. Max SCHE per elevator (implicit cap, but let's cap target ns)
        if adjusted_ns > NUM_ELEVATORS:
            print(f"  Adjusting num_sche: {adjusted_ns} -> {NUM_ELEVATORS} (HuCe max 1 per elevator)", file=sys.stderr)
            adjusted_ns = NUM_ELEVATORS

        # 3. Total directives constraint [1, 70]
        total_reqs = adjusted_np + adjusted_ns
        if total_reqs == 0:
            print("ERROR (HuCe): Total number of directives cannot be 0.", file=sys.stderr)
            sys.exit(1)
        elif total_reqs > HUCE_MAX_DIRECTIVES:
            print(f"  Total requested directives ({total_reqs}) exceeds HuCe limit ({HUCE_MAX_DIRECTIVES}).", file=sys.stderr)
            excess = total_reqs - HUCE_MAX_DIRECTIVES
            # Strategy: Reduce passengers first, then SCHE if necessary
            reduce_np = min(adjusted_np, excess)
            adjusted_np -= reduce_np
            excess -= reduce_np

            if excess > 0: # Still need to reduce SCHE
                 reduce_ns = min(adjusted_ns, excess)
                 adjusted_ns -= reduce_ns
                 excess -= reduce_ns # Should be 0 now

            print(f"  Adjusting counts -> num_passengers: {adjusted_np}, num_sche: {adjusted_ns}", file=sys.stderr)

        # Re-check forced/burst counts against adjusted passenger count
        if adjusted_np > 0:
            total_special = args.force_start_passengers + args.force_end_passengers + args.burst_size
            if total_special > adjusted_np:
                 print(f"ERROR (HuCe): Sum of forced/burst passengers ({total_special}) exceeds *adjusted* num_passengers ({adjusted_np}). Reduce force/burst counts or increase total initial np.", file=sys.stderr)
                 sys.exit(1)
        elif args.force_start_passengers > 0 or args.force_end_passengers > 0 or args.burst_size > 0:
             print(f"  INFO (HuCe): Forced/burst passenger options ignored as adjusted num_passengers is 0.", file=sys.stderr)
             # Reset args values directly for generate_data consistency if needed
             args.force_start_passengers = 0
             args.force_end_passengers = 0
             args.burst_size = 0
        print("---------------------------------", file=sys.stderr)


    # --- Burst Time Defaulting/Clamping (After potential HuCe time adjustments) ---
    adjusted_burst_time = args.burst_time
    if args.burst_size > 0 and adjusted_np > 0: # Only if burst is requested and possible
        if adjusted_burst_time is None:
            adjusted_burst_time = (adjusted_start_time + adjusted_max_time) / 2.0
            print(f"INFO: Defaulting burst time to midpoint: {adjusted_burst_time:.1f}", file=sys.stderr)
        # Clamp burst time to the *final* adjusted time range
        original_burst_time = adjusted_burst_time
        adjusted_burst_time = max(adjusted_start_time, min(adjusted_burst_time, adjusted_max_time))
        if abs(adjusted_burst_time - original_burst_time) > 0.01 : # Check if clamped
             print(f"INFO: Adjusted burst time from {original_burst_time:.1f} to {adjusted_burst_time:.1f} to fit range [{adjusted_start_time:.1f}, {adjusted_max_time:.1f}]", file=sys.stderr)

    # --- Generate Data ---
    generated_directives = generate_data(
        num_passengers=adjusted_np, # Use adjusted values
        num_sche=adjusted_ns,
        max_time=adjusted_max_time,
        min_interval=args.min_interval,
        max_interval=args.max_interval,
        start_time=adjusted_start_time,
        huce_mode=args.hce, # Pass the flag
        seed=args.seed,
        force_start_passengers=args.force_start_passengers,
        force_end_passengers=args.force_end_passengers,
        burst_size=args.burst_size,
        burst_time=adjusted_burst_time, # Pass potentially adjusted burst time
        extreme_floor_ratio=args.extreme_floor_ratio,
        priority_bias=args.priority_bias,
        priority_bias_ratio=args.priority_bias_ratio,
        priority_middle_range=args.priority_middle_range
    )

    if generated_directives is None:
        print("ERROR: Data generation failed. See previous messages.", file=sys.stderr)
        sys.exit(1)

    # --- Output ---
    output_content = "\n".join(generated_directives)
    if args.output_file:
        try:
            with open(args.output_file, 'w') as f:
                f.write(output_content)
                if generated_directives: f.write("\n")
            # Final success message moved outside generate_data
            print(f"\nSuccessfully generated {len(generated_directives)} directives to {args.output_file}", file=sys.stderr)
        except IOError as e:
            print(f"ERROR: Could not write to file {args.output_file}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        if output_content:
            print(output_content)

if __name__ == "__main__":
    main()
# --- END OF UPDATED gen.py ---