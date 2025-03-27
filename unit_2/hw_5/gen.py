import random
import argparse
import sys
import time

# --- Constants based on the problem description ---
FLOORS = ['B4', 'B3', 'B2', 'B1', 'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7']
NUM_FLOORS = len(FLOORS)
NUM_ELEVATORS = 6
MIN_PRIORITY = 1
MAX_PRIORITY = 100

# --- Default Generation Parameters ---
DEFAULT_NUM_REQUESTS = 20
DEFAULT_MAX_TIME = 50.0  # Default max time for the last request
DEFAULT_MIN_INTERVAL = 0.0 # Min time between consecutive requests
DEFAULT_MAX_INTERVAL = 2.0 # Max time between consecutive requests
DEFAULT_START_TIME = 1.0  # Default earliest time for the first request

# --- Hu Ce (Mutual Testing) Specific Constraints ---
HUCE_MAX_REQUESTS = 70
HUCE_MAX_TIME = 50.0
HUCE_START_TIME = 1.0
HUCE_MAX_REQUESTS_PER_ELEVATOR = 30

def generate_request(passenger_id, current_time, elevator_id, floors):
    """Generates a single, valid passenger request string."""
    priority = random.randint(MIN_PRIORITY, MAX_PRIORITY)
    
    while True:
        start_floor = random.choice(floors)
        end_floor = random.choice(floors)
        if start_floor != end_floor:
            break
            
    # Format: [时间戳]乘客ID-PRI-优先级指数-FROM-起点层-TO-终点层-BY-指定的电梯ID
    return (
        f"[{current_time:.1f}]{passenger_id}-PRI-{priority}"
        f"-FROM-{start_floor}-TO-{end_floor}-BY-{elevator_id}"
    )

def generate_data(num_requests, max_time, min_interval, max_interval, start_time, huce_mode=False, seed=None):
    """Generates a list of elevator request strings."""
    
    if seed is not None:
        random.seed(seed)
    else:
        # Use current time for a different seed each run if none provided
        random.seed(int(time.time() * 1000)) 

    # Apply Hu Ce constraints if needed
    if huce_mode:
        num_requests = min(num_requests, HUCE_MAX_REQUESTS)
        max_time = min(max_time, HUCE_MAX_TIME)
        start_time = max(start_time, HUCE_START_TIME)
        print(f"INFO: Running in Hu Ce mode. Max requests: {num_requests}, Max time: {max_time:.1f}, Start time >= {start_time:.1f}", file=sys.stderr)

    requests = []
    current_time = start_time
    last_passenger_id = 0 # Start passenger IDs from 1
    elevator_request_counts = {i: 0 for i in range(1, NUM_ELEVATORS + 1)}
    available_elevators = list(range(1, NUM_ELEVATORS + 1))

    for i in range(num_requests):
        # Add time interval for subsequent requests
        if i > 0:
            interval = random.uniform(min_interval, max_interval)
            current_time += interval
        
        # Ensure time doesn't exceed max_time (clamp if necessary)
        current_time = min(current_time, max_time)
        
        # Clamp start time
        current_time = max(current_time, start_time)

        # --- Elevator Assignment ---
        chosen_elevator_id = -1
        if huce_mode:
            # Filter elevators that haven't reached the limit
            eligible_elevators = [
                e_id for e_id in available_elevators 
                if elevator_request_counts[e_id] < HUCE_MAX_REQUESTS_PER_ELEVATOR
            ]
            if not eligible_elevators:
                print(f"WARNING: Cannot assign more requests due to Hu Ce elevator limits. Generated {i} requests.", file=sys.stderr)
                break # Stop generation if no elevator can take more requests
            
            chosen_elevator_id = random.choice(eligible_elevators)
            elevator_request_counts[chosen_elevator_id] += 1
            # Optional: Remove elevator from available list if it reaches the limit
            # if elevator_request_counts[chosen_elevator_id] >= HUCE_MAX_REQUESTS_PER_ELEVATOR:
            #    available_elevators.remove(chosen_elevator_id) # Less efficient but clear
        else:
            # Random assignment if not in Hu Ce mode
             chosen_elevator_id = random.randint(1, NUM_ELEVATORS)
             # We don't strictly need to track counts if not in huce_mode for generation
             # but it might be useful for analysis later if desired.
             elevator_request_counts[chosen_elevator_id] += 1


        # --- Generate Request ---
        last_passenger_id += 1
        request_str = generate_request(
            passenger_id=last_passenger_id,
            current_time=current_time,
            elevator_id=chosen_elevator_id,
            floors=FLOORS
        )
        requests.append(request_str)

        # Stop if max_time is reached precisely (unlikely with floats, but possible)
        if current_time >= max_time and i < num_requests - 1:
             print(f"INFO: Reached max_time ({max_time:.1f}) after {i+1} requests.", file=sys.stderr)
             break


    if huce_mode:
         print("\nINFO: Hu Ce Elevator Request Counts:", file=sys.stderr)
         for eid, count in elevator_request_counts.items():
             if count > 0:
                 print(f"  Elevator {eid}: {count} requests", file=sys.stderr)


    return requests

def main():
    parser = argparse.ArgumentParser(description="Generate Elevator Test Data")
    parser.add_argument(
        "-n", "--num-requests", type=int, default=DEFAULT_NUM_REQUESTS,
        help=f"Number of passenger requests to generate (default: {DEFAULT_NUM_REQUESTS})"
    )
    parser.add_argument(
        "-t", "--max-time", type=float, default=DEFAULT_MAX_TIME,
        help=f"Maximum timestamp for the last request (default: {DEFAULT_MAX_TIME:.1f}s)"
    )
    parser.add_argument(
        "--start-time", type=float, default=DEFAULT_START_TIME,
        help=f"Earliest timestamp for the first request (default: {DEFAULT_START_TIME:.1f}s)"
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
        help=f"Apply Hu Ce (Mutual Testing) constraints: max {HUCE_MAX_REQUESTS} reqs, "
             f"last req <= {HUCE_MAX_TIME:.1f}s, first req >= {HUCE_START_TIME:.1f}s, "
             f"max {HUCE_MAX_REQUESTS_PER_ELEVATOR} reqs/elevator."
    )

    args = parser.parse_args()

    # Validate arguments
    if args.num_requests <= 0:
        print("ERROR: Number of requests must be positive.", file=sys.stderr)
        sys.exit(1)
    if args.max_time < args.start_time:
        print("ERROR: Max time cannot be less than start time.", file=sys.stderr)
        sys.exit(1)
    if args.min_interval < 0 or args.max_interval < 0:
         print("ERROR: Time intervals cannot be negative.", file=sys.stderr)
         sys.exit(1)
    if args.min_interval > args.max_interval:
        print("ERROR: Min interval cannot be greater than max interval.", file=sys.stderr)
        sys.exit(1)
    if args.hce and args.num_requests > HUCE_MAX_REQUESTS:
         print(f"WARNING: Requested {args.num_requests} requests, but Hu Ce mode limits to {HUCE_MAX_REQUESTS}. Generating {HUCE_MAX_REQUESTS}.", file=sys.stderr)
         args.num_requests = HUCE_MAX_REQUESTS


    generated_requests = generate_data(
        num_requests=args.num_requests,
        max_time=args.max_time,
        min_interval=args.min_interval,
        max_interval=args.max_interval,
        start_time=args.start_time,
        huce_mode=args.hce,
        seed=args.seed
    )

    output_content = "\n".join(generated_requests)

    if args.output_file:
        try:
            with open(args.output_file, 'w') as f:
                f.write(output_content)
                # Add a newline at the end if requests were generated
                if generated_requests:
                    f.write("\n") 
            print(f"Successfully generated {len(generated_requests)} requests to {args.output_file}", file=sys.stderr)
        except IOError as e:
            print(f"ERROR: Could not write to file {args.output_file}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Print to stdout
        print(output_content)

if __name__ == "__main__":
    main()