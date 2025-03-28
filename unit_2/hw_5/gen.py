import random
import argparse
import sys
import time
import math

# --- Constants based on the problem description ---
FLOORS = ['B4', 'B3', 'B2', 'B1', 'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7']
FLOOR_MAP = {name: i for i, name in enumerate(FLOORS)}
NUM_FLOORS = len(FLOORS)
NUM_ELEVATORS = 6
MIN_PRIORITY = 1
MAX_PRIORITY = 100
MID_PRIORITY = (MIN_PRIORITY + MAX_PRIORITY) // 2 # ~50

# --- Default Generation Parameters ---
DEFAULT_NUM_REQUESTS = 20
DEFAULT_MAX_TIME = 50.0
DEFAULT_MIN_INTERVAL = 0.0
DEFAULT_MAX_INTERVAL = 1.4
DEFAULT_START_TIME = 1.0
DEFAULT_PRIORITY_MIDDLE_RANGE = 20 # Default range for 'middle' bias (e.g., 40-60)

# --- Hu Ce (Mutual Testing) Specific Constraints ---
HUCE_MAX_REQUESTS = 70
HUCE_MAX_TIME = 50.0
HUCE_START_TIME = 1.0
HUCE_MAX_REQUESTS_PER_ELEVATOR = 30

def get_timestamp_from_string(request_str):
    """Extracts the float timestamp from a request string."""
    try:
        return float(request_str[1:request_str.find(']')])
    except ValueError:
        return -1.0

def generate_request(passenger_id, current_time, elevator_id, floors,
                     extreme_floor_ratio=0.0,
                     priority_bias='none', priority_bias_ratio=0.0,
                     priority_middle_range=DEFAULT_PRIORITY_MIDDLE_RANGE): # Added middle range
    """Generates a single, valid passenger request string with updated priority options."""

    # --- Priority Generation ---
    priority = -1
    apply_bias = random.random() < priority_bias_ratio

    if apply_bias and priority_bias != 'none':
        if priority_bias == 'extremes':
            # Choose either MIN or MAX priority
            priority = random.choice([MIN_PRIORITY, MAX_PRIORITY])
        elif priority_bias == 'middle':
            # Calculate bounds for the middle range
            half_range = priority_middle_range // 2
            lower_bound = max(MIN_PRIORITY, MID_PRIORITY - half_range)
            upper_bound = min(MAX_PRIORITY, MID_PRIORITY + half_range)
            # Ensure lower isn't greater than upper if range is too large
            if lower_bound > upper_bound:
                 lower_bound = upper_bound = MID_PRIORITY
            # Generate within the calculated middle range
            priority = random.randint(lower_bound, upper_bound)
        # else: # Should not happen if validation is correct
            # priority = random.randint(MIN_PRIORITY, MAX_PRIORITY) # Fallback
    else:
        # Default: Uniform random priority (also applies if bias='none' or bias roll fails)
        priority = random.randint(MIN_PRIORITY, MAX_PRIORITY)

    # --- Floor Generation ---
    start_floor, end_floor = None, None
    if random.random() < extreme_floor_ratio:
        if random.choice([True, False]):
            start_floor, end_floor = floors[0], floors[-1] # B4 -> F7
        else:
            start_floor, end_floor = floors[-1], floors[0] # F7 -> B4
    else:
        while True:
            start_floor = random.choice(floors)
            end_floor = random.choice(floors)
            if start_floor != end_floor:
                break

    return (
        f"[{current_time:.1f}]{passenger_id}-PRI-{priority}"
        f"-FROM-{start_floor}-TO-{end_floor}-BY-{elevator_id}"
    )

def generate_data(num_requests, max_time, min_interval, max_interval, start_time,
                  huce_mode=False, seed=None,
                  force_start_requests=0, force_end_requests=0,
                  burst_size=0, burst_time=None,
                  extreme_floor_ratio=0.0,
                  focus_elevator=None, focus_ratio=0.0,
                  priority_bias='none', priority_bias_ratio=0.0,
                  priority_middle_range=DEFAULT_PRIORITY_MIDDLE_RANGE # Pass down
                  ):
    """Generates a list of elevator request strings with boundary condition focus."""

    # (Seed and basic HuCe/Param validation remains the same as before)
    if seed is not None:
        print(f"INFO: Using random seed: {seed}", file=sys.stderr)
        random.seed(seed)
    else:
        current_seed = int(time.time() * 1000)
        print(f"INFO: Using generated random seed: {current_seed}", file=sys.stderr)
        random.seed(current_seed)

    # --- Parameter Validation & Adjustment ---
    if huce_mode:
        original_num_requests = num_requests
        num_requests = min(num_requests, HUCE_MAX_REQUESTS)
        if original_num_requests > num_requests:
             print(f"WARNING: Requested {original_num_requests} requests, but Hu Ce mode limits to {HUCE_MAX_REQUESTS}. Generating {HUCE_MAX_REQUESTS}.", file=sys.stderr)
        max_time = min(max_time, HUCE_MAX_TIME)
        start_time = max(start_time, HUCE_START_TIME)
        print(f"INFO: Running in Hu Ce mode. Max requests: {num_requests}, Max time: {max_time:.1f}, Start time >= {start_time:.1f}, Max/Elevator: {HUCE_MAX_REQUESTS_PER_ELEVATOR}", file=sys.stderr)
    else:
         if not (1 <= num_requests <= 100):
              print(f"ERROR: Number of requests ({num_requests}) must be between 1 and 100.", file=sys.stderr)
              return None

    # (Validation for force_requests, burst, extreme_floor, focus_elevator remain the same)
    if force_start_requests < 0 or force_end_requests < 0 or burst_size < 0:
        print("ERROR: Forced request counts/burst size cannot be negative.", file=sys.stderr)
        return None
    if force_start_requests + force_end_requests + burst_size > num_requests:
        print(f"ERROR: Sum of forced/burst requests ({force_start_requests + force_end_requests + burst_size}) exceeds total requests ({num_requests}).", file=sys.stderr)
        return None
    # (...) other validations

    if priority_bias not in ['none', 'extremes', 'middle']:
        print(f"WARNING: Invalid priority bias '{priority_bias}'. Valid options: none, extremes, middle. Defaulting to 'none'.", file=sys.stderr)
        priority_bias = 'none'
    if not (0.0 <= priority_bias_ratio <= 1.0):
         print(f"WARNING: Priority bias ratio ({priority_bias_ratio}) outside [0, 1]. Clamping.", file=sys.stderr)
         priority_bias_ratio = max(0.0, min(1.0, priority_bias_ratio))
    if priority_middle_range <= 0:
        print(f"WARNING: Priority middle range ({priority_middle_range}) must be positive. Using default {DEFAULT_PRIORITY_MIDDLE_RANGE}.", file=sys.stderr)
        priority_middle_range = DEFAULT_PRIORITY_MIDDLE_RANGE

    # --- Priority Info ---
    if priority_bias == 'none':
        print(f"INFO: Priority generation: Uniform random ({MIN_PRIORITY}-{MAX_PRIORITY}).", file=sys.stderr)
    elif priority_bias == 'extremes':
        print(f"INFO: Priority generation: Biased towards extremes ({MIN_PRIORITY} or {MAX_PRIORITY}) with probability {priority_bias_ratio:.2f}.", file=sys.stderr)
    elif priority_bias == 'middle':
        half_range = priority_middle_range // 2
        lower_bound = max(MIN_PRIORITY, MID_PRIORITY - half_range)
        upper_bound = min(MAX_PRIORITY, MID_PRIORITY + half_range)
        print(f"INFO: Priority generation: Biased towards middle range (~{lower_bound}-{upper_bound}) with probability {priority_bias_ratio:.2f}.", file=sys.stderr)


    # --- Generation Logic ---
    # (The core generation loop structure, assign_elevator helper,
    # handling of forced requests, bursts, middle requests, sorting, etc.
    # remains the same as in the previous enhanced version)
    # ...
    requests = []
    last_passenger_id = 0
    elevator_request_counts = {i: 0 for i in range(1, NUM_ELEVATORS + 1)}

    def assign_elevator():
        # (Same assign_elevator logic as before)
        nonlocal elevator_request_counts
        if focus_elevator is not None and random.random() < focus_ratio:
            can_assign_focused = True
            if huce_mode and elevator_request_counts[focus_elevator] >= HUCE_MAX_REQUESTS_PER_ELEVATOR:
                can_assign_focused = False
            if can_assign_focused:
                 elevator_request_counts[focus_elevator] += 1
                 return focus_elevator

        if huce_mode:
            eligible_elevators = [
                e_id for e_id in range(1, NUM_ELEVATORS + 1)
                if elevator_request_counts[e_id] < HUCE_MAX_REQUESTS_PER_ELEVATOR
            ]
            if not eligible_elevators:
                print(f"WARNING: Cannot assign more requests due to Hu Ce elevator limits. Returning None.", file=sys.stderr)
                return None
            chosen_elevator_id = random.choice(eligible_elevators)
            elevator_request_counts[chosen_elevator_id] += 1
            return chosen_elevator_id
        else:
             chosen_elevator_id = random.randint(1, NUM_ELEVATORS)
             elevator_request_counts[chosen_elevator_id] += 1
             return chosen_elevator_id

    # --- 1. Generate Forced Start Requests ---
    if force_start_requests > 0:
        # (...) same logic
        print(f"INFO: Generating {force_start_requests} requests exactly at start_time {start_time:.1f}", file=sys.stderr)
        for _ in range(force_start_requests):
             last_passenger_id += 1
             elevator_id = assign_elevator()
             if elevator_id is None: return None
             req_str = generate_request( # Pass arguments including new priority ones
                 passenger_id=last_passenger_id, current_time=start_time, elevator_id=elevator_id, floors=FLOORS,
                 extreme_floor_ratio=extreme_floor_ratio, priority_bias=priority_bias,
                 priority_bias_ratio=priority_bias_ratio, priority_middle_range=priority_middle_range
             )
             requests.append(req_str)

    # --- 2. Generate Middle Requests (including potential burst) ---
    num_middle_requests = num_requests - force_start_requests - force_end_requests
    burst_added = False
    current_time = start_time
    burst_insert_index = -1
    # (burst index calculation remains the same)
    if burst_size > 0 and num_middle_requests > 0:
        time_span = max_time - start_time
        if time_span > 0:
             burst_ratio = (burst_time - start_time) / time_span
             burst_insert_index = math.ceil(burst_ratio * (num_middle_requests - burst_size))
             burst_insert_index = max(0, min(burst_insert_index, num_middle_requests - burst_size))
        else:
            burst_insert_index = 0
        print(f"INFO: Planning burst of size {burst_size} at time {burst_time:.1f}, insert index ~{burst_insert_index}", file=sys.stderr)

    if num_middle_requests > 0:
        print(f"INFO: Generating {num_middle_requests} middle requests between ({start_time:.1f}, {max_time:.1f})", file=sys.stderr)

    middle_req_generated_count = 0
    for i in range(num_middle_requests): # Loop potentially more times than needed if burst happens
        if middle_req_generated_count >= num_middle_requests: # Check if we already generated enough
            break

        is_burst_req = False
        if burst_size > 0 and not burst_added and middle_req_generated_count == burst_insert_index:
            # (...) Same burst generation logic
            print(f"INFO: Inserting burst of {burst_size} requests now.", file=sys.stderr)
            burst_actual_time = max(current_time, min(burst_time, max_time))
            for _ in range(burst_size):
                if middle_req_generated_count >= num_middle_requests: break # Don't exceed total
                last_passenger_id += 1
                elevator_id = assign_elevator()
                if elevator_id is None: return None
                req_str = generate_request( # Pass arguments
                    passenger_id=last_passenger_id, current_time=burst_actual_time, elevator_id=elevator_id, floors=FLOORS,
                    extreme_floor_ratio=extreme_floor_ratio, priority_bias=priority_bias,
                    priority_bias_ratio=priority_bias_ratio, priority_middle_range=priority_middle_range
                )
                requests.append(req_str)
                middle_req_generated_count += 1 # Increment count here
            current_time = burst_actual_time
            burst_added = True
            is_burst_req = True # Indicate these were burst requests for loop logic (though count check is primary)
            if middle_req_generated_count >= num_middle_requests:
                 break # Stop if burst filled remaining slots

        # --- Generate Regular Middle Request ---
        if not is_burst_req and middle_req_generated_count < num_middle_requests:
            # (...) Same time increment and clamping logic
            if middle_req_generated_count > 0 or force_start_requests > 0:
                 interval = random.uniform(min_interval, max_interval)
                 current_time += interval
            current_time = max(start_time, min(current_time, max_time))

            last_passenger_id += 1
            elevator_id = assign_elevator()
            if elevator_id is None: return None
            req_str = generate_request( # Pass arguments
                passenger_id=last_passenger_id, current_time=current_time, elevator_id=elevator_id, floors=FLOORS,
                extreme_floor_ratio=extreme_floor_ratio, priority_bias=priority_bias,
                priority_bias_ratio=priority_bias_ratio, priority_middle_range=priority_middle_range
            )
            requests.append(req_str)
            middle_req_generated_count += 1

            if current_time >= max_time and middle_req_generated_count < num_middle_requests:
                 print(f"INFO: Reached max_time ({max_time:.1f}) during middle request generation.", file=sys.stderr)
                 break


    # --- 3. Generate Forced End Requests ---
    if force_end_requests > 0:
        # (...) Same logic
        print(f"INFO: Generating {force_end_requests} requests exactly at max_time {max_time:.1f}", file=sys.stderr)
        actual_end_time = max(current_time, max_time) # Ensure end time is not before last middle req
        actual_end_time = min(actual_end_time, max_time) # Clamp to max_time

        for _ in range(force_end_requests):
            last_passenger_id += 1
            elevator_id = assign_elevator()
            if elevator_id is None: return None
            req_str = generate_request( # Pass arguments
                passenger_id=last_passenger_id, current_time=actual_end_time, elevator_id=elevator_id, floors=FLOORS,
                extreme_floor_ratio=extreme_floor_ratio, priority_bias=priority_bias,
                priority_bias_ratio=priority_bias_ratio, priority_middle_range=priority_middle_range
            )
            requests.append(req_str)

    # --- 4. Final Sort and Validation ---
    requests.sort(key=get_timestamp_from_string)

    # (Final count check and elevator load summary remain the same)
    if len(requests) != num_requests:
         print(f"WARNING: Expected {num_requests} requests, but generated {len(requests)}. This might happen if HuCe limits were hit.", file=sys.stderr)

    print("\nINFO: Final Elevator Request Counts:", file=sys.stderr)
    for eid, count in sorted(elevator_request_counts.items()):
        if count > 0:
            print(f"  Elevator {eid}: {count} requests", file=sys.stderr)
            if huce_mode and count > HUCE_MAX_REQUESTS_PER_ELEVATOR:
                 print(f"    ERROR: Exceeded HuCe limit for Elevator {eid}!", file=sys.stderr) # Should not happen

    return requests


def main():
    parser = argparse.ArgumentParser(description="Generate Elevator Test Data with Boundary Focus")

    # --- Core Parameters ---
    # (num-requests, max-time, start-time, min/max-interval, output-file, seed, hce remain same)
    parser.add_argument(
        "-n", "--num-requests", type=int, default=DEFAULT_NUM_REQUESTS,
        help=f"Number of passenger requests (default: {DEFAULT_NUM_REQUESTS}). Non-HuCe: 1-100. HuCe: 1-{HUCE_MAX_REQUESTS}."
    )
    parser.add_argument(
        "-t", "--max-time", type=float, default=DEFAULT_MAX_TIME,
        help=f"Maximum timestamp for the last request (default: {DEFAULT_MAX_TIME:.1f}s). HuCe clamps at {HUCE_MAX_TIME:.1f}s."
    )
    parser.add_argument(
        "--start-time", type=float, default=DEFAULT_START_TIME,
        help=f"Earliest timestamp for the first request (default: {DEFAULT_START_TIME:.1f}s). HuCe enforces >= {HUCE_START_TIME:.1f}s."
    )
    parser.add_argument(
        "--min-interval", type=float, default=DEFAULT_MIN_INTERVAL,
        help=f"Minimum time interval between consecutive requests (default: {DEFAULT_MIN_INTERVAL:.1f}s)"
    )
    parser.add_argument(
        "--max-interval", type=float, default=DEFAULT_MAX_INTERVAL,
        help=f"Maximum time interval between consecutive requests (default: {DEFAULT_MAX_INTERVAL:.1f}s)"
    )
    parser.add_argument(
        "-o", "--output-file", type=str, default=None,
        help="File to write the generated data to (default: stdout)"
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducibility"
    )
    parser.add_argument(
        "--hce", action='store_true',
        help=f"Apply Hu Ce constraints: max {HUCE_MAX_REQUESTS} reqs, <= {HUCE_MAX_TIME:.1f}s, >= {HUCE_START_TIME:.1f}s, max {HUCE_MAX_REQUESTS_PER_ELEVATOR} reqs/elevator."
    )

    # --- Boundary Condition Parameters ---
    # (force-start/end, burst, extreme-floor, focus-elevator remain same)
    parser.add_argument(
        "--force-start-requests", type=int, default=0,
        help="Generate N requests exactly at start-time (default: 0)."
    )
    parser.add_argument(
        "--force-end-requests", type=int, default=0,
        help="Generate N requests exactly at max-time (default: 0)."
    )
    parser.add_argument(
        "--burst-size", type=int, default=0,
        help="Generate a burst of N requests at the same time (0 interval) (default: 0)."
    )
    parser.add_argument(
        "--burst-time", type=float, default=None,
        help="Approximate timestamp for the burst (defaults to mid-point between start/max-time if burst-size > 0 and this is not set)."
    )
    parser.add_argument(
        "--extreme-floor-ratio", type=float, default=0.0,
        help="Probability (0.0 to 1.0) of generating B4<->F7 requests (default: 0.0)."
    )
    parser.add_argument(
        "--focus-elevator", type=int, default=None,
        help=f"Elevator ID (1-{NUM_ELEVATORS}) to receive a higher proportion of requests."
    )
    parser.add_argument(
        "--focus-ratio", type=float, default=0.7,
        help="Probability (0.0 to 1.0) of assigning to focus-elevator (if set) (default: 0.7)."
    )
    parser.add_argument(
        "--priority-bias", choices=['none', 'extremes', 'middle'], default='none',
        help="Bias request priority: 'none' (uniform), 'extremes' (1 or 100), 'middle' (around 50) (default: none)."
    )
    parser.add_argument(
        "--priority-bias-ratio", type=float, default=0.5,
        help="Probability (0.0 to 1.0) of applying the priority bias (if not 'none') (default: 0.5)."
    )
    parser.add_argument(
        "--priority-middle-range", type=int, default=DEFAULT_PRIORITY_MIDDLE_RANGE,
        help=f"Approximate range width for 'middle' priority bias (e.g., 20 targets ~40-60) (default: {DEFAULT_PRIORITY_MIDDLE_RANGE})."
    )

    args = parser.parse_args()

    # --- Argument Validation (Basic) ---
    if args.num_requests <= 0:
         print("WARNING: Number of requests should ideally be positive.", file=sys.stderr)
    if args.max_time < args.start_time:
        print("ERROR: Max time cannot be less than start time.", file=sys.stderr)
        sys.exit(1)
    if args.burst_size > 0 and args.burst_time is None:
        # Calculate midpoint time, ensuring float division
        default_burst_time = (args.start_time + args.max_time) / 2.0
        # Clamp the default burst time within the valid range just in case
        default_burst_time = max(args.start_time, min(default_burst_time, args.max_time))
        args.burst_time = default_burst_time
        print(f"INFO: --burst-size > 0 and --burst-time not specified. Defaulting burst time to midpoint: {args.burst_time:.1f}", file=sys.stderr)

    # --- Generate Data ---
    generated_requests = generate_data(
        num_requests=args.num_requests,
        max_time=args.max_time,
        min_interval=args.min_interval,
        max_interval=args.max_interval,
        start_time=args.start_time,
        huce_mode=args.hce,
        seed=args.seed,
        force_start_requests=args.force_start_requests,
        force_end_requests=args.force_end_requests,
        burst_size=args.burst_size,
        burst_time=args.burst_time,
        extreme_floor_ratio=args.extreme_floor_ratio,
        focus_elevator=args.focus_elevator,
        focus_ratio=args.focus_ratio,
        priority_bias=args.priority_bias,
        priority_bias_ratio=args.priority_bias_ratio,
        priority_middle_range=args.priority_middle_range
    )

    if generated_requests is None:
        print("ERROR: Data generation failed due to validation errors.", file=sys.stderr)
        sys.exit(1)

    # --- Output ---
    output_content = "\n".join(generated_requests)
    if args.output_file:
        try:
            with open(args.output_file, 'w') as f:
                f.write(output_content)
                if generated_requests: f.write("\n")
            print(f"\nSuccessfully generated {len(generated_requests)} requests to {args.output_file}", file=sys.stderr)
        except IOError as e:
            print(f"ERROR: Could not write to file {args.output_file}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(output_content)

if __name__ == "__main__":
    main()