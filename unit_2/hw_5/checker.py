import re
import argparse
import sys
from collections import defaultdict, deque
import math

# --- Constants ---
FLOOR_MAP = {
    'B4': 0, 'B3': 1, 'B2': 2, 'B1': 3,
    'F1': 4, 'F2': 5, 'F3': 6, 'F4': 7, 'F5': 8, 'F6': 9, 'F7': 10
}
INDEX_TO_FLOOR = {v: k for k, v in FLOOR_MAP.items()}
NUM_FLOORS = len(FLOOR_MAP)
NUM_ELEVATORS = 6
ELEVATOR_IDS = set(range(1, NUM_ELEVATORS + 1))

CAPACITY = 6
MOVE_TIME_PER_FLOOR = 0.4
DOOR_OPEN_CLOSE_TIME = 0.4  # Minimum time between OPEN and CLOSE

POWER_ARRIVE = 0.4
POWER_OPEN = 0.1
POWER_CLOSE = 0.1

EPSILON = 1e-6 # Tolerance for float comparisons

# --- Data Structures ---
passengers = {} # passenger_id -> {info}
elevators = {}  # elevator_id -> {state}

# --- Helper Functions ---
def floor_to_index(floor_str):
    """Converts floor string ('F1', 'B2') to integer index."""
    return FLOOR_MAP.get(floor_str)

def index_to_floor(floor_idx):
    """Converts integer index back to floor string."""
    return INDEX_TO_FLOOR.get(floor_idx)

def parse_time(time_str):
    """Extracts float time from [timestamp] format."""
    match = re.match(r"\[\s*(\d+\.\d+)\s*\]", time_str)
    if match:
        return float(match.group(1))
    return None

def print_error(line_num, timestamp, message):
    """Prints an error message and sets the error flag."""
    global correctness_ok
    correctness_ok = False
    print(f"ERROR (Line {line_num}, Time {timestamp:.4f}): {message}", file=sys.stderr)

# --- Main Logic ---
def check_output(request_file, output_file, t_max=float('inf')):
    """
    Checks the elevator output file for correctness and calculates performance.

    Args:
        request_file (str): Path to the input request file.
        output_file (str): Path to the elevator simulation output file.
        t_max (float): Maximum allowed T_final (relevant for HuCe/specific tests).
    """
    global correctness_ok, passengers, elevators
    correctness_ok = True
    passengers = {}
    elevators = {}

    total_requests = 0
    finished_passengers = set()
    max_output_timestamp = 0.0

    # Performance counters
    n_arrive = 0
    n_open = 0
    n_close = 0

    # 1. Read Requests
    try:
        with open(request_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Format: [时间戳]乘客ID-PRI-优先级指数-FROM-起点层-TO-终点层-BY-指定的电梯ID
                match = re.match(
                    r"\[\s*(\d+\.\d+)\s*\]"              # Timestamp
                    r"(\d+)-PRI-(\d+)"                   # ID, Priority
                    r"-FROM-([BF]\d+)-TO-([BF]\d+)"     # Floors
                    r"-BY-(\d+)",                        # Elevator ID
                    line
                )
                if not match:
                    print(f"FATAL: Invalid request format in {request_file}: {line}", file=sys.stderr)
                    return False, None, None, None # Indicate fatal error

                req_time, p_id_str, pri_str, from_f, to_f, elev_id_str = match.groups()
                p_id = int(p_id_str)
                elev_id = int(elev_id_str)
                if p_id in passengers:
                     print(f"FATAL: Duplicate passenger ID {p_id} in {request_file}", file=sys.stderr)
                     return False, None, None, None
                if elev_id not in ELEVATOR_IDS:
                     print(f"FATAL: Invalid elevator ID {elev_id} for passenger {p_id} in {request_file}", file=sys.stderr)
                     return False, None, None, None
                if floor_to_index(from_f) is None or floor_to_index(to_f) is None:
                    print(f"FATAL: Invalid floor in request for passenger {p_id} in {request_file}", file=sys.stderr)
                    return False, None, None, None
                if from_f == to_f:
                     print(f"FATAL: Start and end floor are the same for passenger {p_id} in {request_file}", file=sys.stderr)
                     return False, None, None, None


                passengers[p_id] = {
                    'id': p_id,
                    'priority': int(pri_str),
                    'start_floor': from_f,
                    'end_floor': to_f,
                    'assigned_elevator': elev_id,
                    'request_time': float(req_time),
                    'location': 'OUTSIDE', # OUTSIDE, INSIDE_ELEVATOR_X, ARRIVED
                    'current_floor': from_f, # Track current location when OUTSIDE
                    'exit_time': None
                }
                total_requests += 1
    except FileNotFoundError:
        print(f"FATAL: Request file not found: {request_file}", file=sys.stderr)
        return False, None, None, None
    except Exception as e:
        print(f"FATAL: Error reading request file {request_file}: {e}", file=sys.stderr)
        return False, None, None, None

    if not 1 <= total_requests <= 100:
         if total_requests == 0:
             # Handle the edge case of no requests gracefully if needed
             print("INFO: No requests found in the input file.", file=sys.stderr)
             # If output is also empty, it might be considered correct depending on rules
             # For now, assume output should also be empty.
         else:
             # This check might be more relevant for the generator, but good to have
             print(f"WARNING: Number of requests ({total_requests}) is outside the typical range [1, 100].", file=sys.stderr)
             # Proceed with checking anyway


    # 2. Initialize Elevators
    for i in range(1, NUM_ELEVATORS + 1):
        elevators[i] = {
            'id': i,
            'current_floor_idx': floor_to_index('F1'),
            'door_state': 'CLOSED', # CLOSED, OPEN
            'passengers': set(), # Set of passenger_ids inside
            'last_action_time': 0.0, # Timestamp of last completed action (ARRIVE, CLOSE, OPEN)
            'last_move_finish_time': 0.0, # Time the last ARRIVE occurred
            'last_open_start_time': None, # Time the current OPEN sequence started
        }

    # 3. Read and Process Output
    output_lines = []
    try:
        with open(output_file, 'r') as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                timestamp = parse_time(line)
                if timestamp is None:
                    print(f"ERROR (Line {i+1}): Malformed timestamp or line format: {line}", file=sys.stderr)
                    correctness_ok = False
                    # Skip this line or halt? Let's try skipping.
                    continue
                output_lines.append({'line_num': i + 1, 'timestamp': timestamp, 'raw': line})
    except FileNotFoundError:
        print(f"FATAL: Output file not found: {output_file}", file=sys.stderr)
        return False, None, None, None
    except Exception as e:
        print(f"FATAL: Error reading output file {output_file}: {e}", file=sys.stderr)
        return False, None, None, None

    # Sort by timestamp primarily, use original line number as tie-breaker (stable sort)
    output_lines.sort(key=lambda x: (x['timestamp'], x['line_num']))

    last_timestamp = -1.0 # Allow 0.0 timestamp

    for item in output_lines:
        line_num = item['line_num']
        timestamp = item['timestamp']
        line = item['raw']

        # --- Timestamp Check ---
        if timestamp < last_timestamp - EPSILON:
            print_error(line_num, timestamp, f"Timestamp non-monotonically decreasing (previous: {last_timestamp:.4f})")
            # Continue checking other things if possible, but mark as incorrect
        last_timestamp = timestamp
        max_output_timestamp = max(max_output_timestamp, timestamp)

        # --- Parse Event ---
        # Using more flexible regex to catch variations in spacing
        match_arrive = re.match(r"\[\s*(\d+\.\d+)\s*\]ARRIVE-([BF]\d+)-(\d+)", line)
        match_open = re.match(r"\[\s*(\d+\.\d+)\s*\]OPEN-([BF]\d+)-(\d+)", line)
        match_close = re.match(r"\[\s*(\d+\.\d+)\s*\]CLOSE-([BF]\d+)-(\d+)", line)
        match_in = re.match(r"\[\s*(\d+\.\d+)\s*\]IN-(\d+)-([BF]\d+)-(\d+)", line)
        match_out = re.match(r"\[\s*(\d+\.\d+)\s*\]OUT-(\d+)-([BF]\d+)-(\d+)", line)

        current_elevator = None
        current_passenger = None

        # --- Event Specific Checks ---
        if match_arrive:
            _, floor_str, elev_id_str = match_arrive.groups()
            elev_id = int(elev_id_str)
            floor_idx = floor_to_index(floor_str)

            if elev_id not in elevators:
                print_error(line_num, timestamp, f"ARRIVE: Invalid elevator ID {elev_id}")
                continue
            if floor_idx is None:
                print_error(line_num, timestamp, f"ARRIVE: Invalid floor {floor_str}")
                continue

            e_state = elevators[elev_id]
            if e_state['door_state'] != 'CLOSED':
                print_error(line_num, timestamp, f"ARRIVE: Elevator {elev_id} door is not CLOSED")

            # Movement time check (compare against the time doors finished closing)
            # Assume movement starts *after* CLOSE finishes
            time_since_last_action = timestamp - e_state['last_action_time']
            floors_moved = abs(floor_idx - e_state['current_floor_idx'])

            # Need to be careful: elevator might open/close without moving
            if floors_moved > 0:
                 min_expected_time = MOVE_TIME_PER_FLOOR * floors_moved
                 # Allow for slight inaccuracies
                 if time_since_last_action < min_expected_time - EPSILON:
                     print_error(line_num, timestamp,
                                 f"ARRIVE: Elevator {elev_id} moved {floors_moved} floors "
                                 f"(from {index_to_floor(e_state['current_floor_idx'])} to {floor_str}) "
                                 f"too fast ({time_since_last_action:.4f}s, expected >= {min_expected_time:.4f}s)")

            # Update state AFTER checks
            e_state['current_floor_idx'] = floor_idx
            e_state['last_action_time'] = timestamp
            e_state['last_move_finish_time'] = timestamp # Record when movement stopped
            n_arrive += 1

        elif match_open:
            _, floor_str, elev_id_str = match_open.groups()
            elev_id = int(elev_id_str)
            floor_idx = floor_to_index(floor_str)

            if elev_id not in elevators:
                print_error(line_num, timestamp, f"OPEN: Invalid elevator ID {elev_id}")
                continue
            if floor_idx is None:
                print_error(line_num, timestamp, f"OPEN: Invalid floor {floor_str}")
                continue

            e_state = elevators[elev_id]
            if e_state['current_floor_idx'] != floor_idx:
                print_error(line_num, timestamp, f"OPEN: Elevator {elev_id} is at floor {index_to_floor(e_state['current_floor_idx'])}, not {floor_str}")
            if e_state['door_state'] != 'CLOSED':
                 # This might happen if CLOSE wasn't output?
                print_error(line_num, timestamp, f"OPEN: Elevator {elev_id} door is already OPEN or in transition")

            # Check if elevator was supposed to be moving
            # It should only open after arriving or if it was already stationary
            time_since_last_move = timestamp - e_state['last_move_finish_time']
            if time_since_last_move < -EPSILON: # Should be >= 0
                 print_error(line_num, timestamp, f"OPEN: Elevator {elev_id} opened before finishing previous move?")

            # Update state AFTER checks
            e_state['door_state'] = 'OPEN'
            e_state['last_action_time'] = timestamp
            e_state['last_open_start_time'] = timestamp # Record when this open started
            n_open += 1

        elif match_close:
            _, floor_str, elev_id_str = match_close.groups()
            elev_id = int(elev_id_str)
            floor_idx = floor_to_index(floor_str)

            if elev_id not in elevators:
                print_error(line_num, timestamp, f"CLOSE: Invalid elevator ID {elev_id}")
                continue
            if floor_idx is None:
                print_error(line_num, timestamp, f"CLOSE: Invalid floor {floor_str}")
                continue

            e_state = elevators[elev_id]
            if e_state['current_floor_idx'] != floor_idx:
                print_error(line_num, timestamp, f"CLOSE: Elevator {elev_id} is at floor {index_to_floor(e_state['current_floor_idx'])}, not {floor_str}")
            if e_state['door_state'] != 'OPEN':
                print_error(line_num, timestamp, f"CLOSE: Elevator {elev_id} door is not OPEN")

            # Door duration check
            if e_state['last_open_start_time'] is None:
                 print_error(line_num, timestamp, f"CLOSE: Elevator {elev_id} closed door, but no corresponding OPEN time recorded")
            else:
                door_open_duration = timestamp - e_state['last_open_start_time']
                if door_open_duration < DOOR_OPEN_CLOSE_TIME - EPSILON:
                    print_error(line_num, timestamp,
                                f"CLOSE: Elevator {elev_id} door was open for only {door_open_duration:.4f}s "
                                f"(expected >= {DOOR_OPEN_CLOSE_TIME:.4f}s)")

            # Update state AFTER checks
            e_state['door_state'] = 'CLOSED'
            e_state['last_action_time'] = timestamp
            e_state['last_open_start_time'] = None # Reset open time
            n_close += 1

        elif match_in:
            _, p_id_str, floor_str, elev_id_str = match_in.groups()
            p_id = int(p_id_str)
            elev_id = int(elev_id_str)
            floor_idx = floor_to_index(floor_str)

            if elev_id not in elevators:
                print_error(line_num, timestamp, f"IN: Invalid elevator ID {elev_id}")
                continue
            if p_id not in passengers:
                print_error(line_num, timestamp, f"IN: Invalid passenger ID {p_id} (not in requests)")
                continue
            if floor_idx is None:
                print_error(line_num, timestamp, f"IN: Invalid floor {floor_str}")
                continue

            e_state = elevators[elev_id]
            p_state = passengers[p_id]

            if e_state['door_state'] != 'OPEN':
                print_error(line_num, timestamp, f"IN: Elevator {elev_id} door is not OPEN for passenger {p_id}")
            if e_state['current_floor_idx'] != floor_idx:
                print_error(line_num, timestamp, f"IN: Elevator {elev_id} is at floor {index_to_floor(e_state['current_floor_idx'])}, not {floor_str} for passenger {p_id}")
            if p_state['location'] != 'OUTSIDE':
                 print_error(line_num, timestamp, f"IN: Passenger {p_id} is not OUTSIDE (current: {p_state['location']})")
            # Check if passenger is at the correct floor to enter
            if p_state['current_floor'] != floor_str:
                 print_error(line_num, timestamp, f"IN: Passenger {p_id} is trying to enter at {floor_str}, but should be at {p_state['current_floor']}")

            # --- HW5 Specific Constraint ---
            if p_state['assigned_elevator'] != elev_id:
                 print_error(line_num, timestamp, f"IN: Passenger {p_id} tried to enter elevator {elev_id}, but was assigned to {p_state['assigned_elevator']}")
            # --- Capacity Constraint ---
            if len(e_state['passengers']) >= CAPACITY:
                 print_error(line_num, timestamp, f"IN: Elevator {elev_id} is full (capacity {CAPACITY}) when passenger {p_id} tried to enter")

            # Update state AFTER checks (only if checks passed for this event)
            if correctness_ok and p_id not in e_state['passengers']: # Prevent double entry if error occurs mid-check
                e_state['passengers'].add(p_id)
                p_state['location'] = f'INSIDE_ELEVATOR_{elev_id}'
                p_state['current_floor'] = None # No longer relevant when inside


        elif match_out:
            _, p_id_str, floor_str, elev_id_str = match_out.groups()
            p_id = int(p_id_str)
            elev_id = int(elev_id_str)
            floor_idx = floor_to_index(floor_str)

            if elev_id not in elevators:
                print_error(line_num, timestamp, f"OUT: Invalid elevator ID {elev_id}")
                continue
            if p_id not in passengers:
                print_error(line_num, timestamp, f"OUT: Invalid passenger ID {p_id} (not in requests)")
                continue
            if floor_idx is None:
                print_error(line_num, timestamp, f"OUT: Invalid floor {floor_str}")
                continue

            e_state = elevators[elev_id]
            p_state = passengers[p_id]

            if e_state['door_state'] != 'OPEN':
                print_error(line_num, timestamp, f"OUT: Elevator {elev_id} door is not OPEN for passenger {p_id}")
            if e_state['current_floor_idx'] != floor_idx:
                 print_error(line_num, timestamp, f"OUT: Elevator {elev_id} is at floor {index_to_floor(e_state['current_floor_idx'])}, not {floor_str} for passenger {p_id}")
            if p_state['location'] != f'INSIDE_ELEVATOR_{elev_id}':
                 print_error(line_num, timestamp, f"OUT: Passenger {p_id} is not inside elevator {elev_id} (current: {p_state['location']})")
            if p_id not in e_state['passengers']:
                 # This might be redundant with the location check above, but good sanity check
                 print_error(line_num, timestamp, f"OUT: Passenger {p_id} not found in elevator {elev_id}'s passenger list")

            # Update state AFTER checks
            if correctness_ok and p_id in e_state['passengers']: # Prevent double removal
                e_state['passengers'].remove(p_id)
                p_state['location'] = 'OUTSIDE'
                p_state['current_floor'] = floor_str # Track where they exited

                # Check if destination reached
                if floor_str == p_state['end_floor']:
                    p_state['location'] = 'ARRIVED'
                    p_state['exit_time'] = timestamp
                    finished_passengers.add(p_id)

        elif line: # If line is not empty but didn't match any pattern
            print_error(line_num, timestamp, f"Unrecognized output format: {line}")

        # If any error occurred in this line's checks, stop processing?
        # For detailed debugging, it might be better to continue and report all errors.
        # If performance matters, stopping early might be desired. Let's continue.


    # 4. Final State Checks (after processing all output)
    if not correctness_ok:
        print("\nCORRECTNESS CHECK FAILED (See errors above). Performance metrics not calculated reliably.", file=sys.stderr)
        return False, None, None, None

    # Check all passengers arrived
    if len(finished_passengers) != total_requests:
        missed_passengers = set(passengers.keys()) - finished_passengers
        print_error('FINAL', max_output_timestamp,
                    f"Not all passengers reached destination. Missing: {missed_passengers} "
                    f"({len(finished_passengers)} finished / {total_requests} total)")

    # Check no passengers stuck inside
    for p_id, p_state in passengers.items():
        if p_state['location'].startswith('INSIDE_ELEVATOR'):
            print_error('FINAL', max_output_timestamp, f"Passenger {p_id} is stuck inside elevator {p_state['location'].split('_')[-1]}")
        elif p_state['location'] == 'OUTSIDE' and p_id not in finished_passengers:
             # This case should be covered by the "missed passengers" check, but double-check logic
             if p_state['exit_time'] is None: # Ensure they never reached the destination
                 print_error('FINAL', max_output_timestamp, f"Passenger {p_id} finished outside but not at destination {p_state['end_floor']} (Current: {p_state['current_floor']})")


    # Check all elevator doors closed
    for elev_id, e_state in elevators.items():
        if e_state['door_state'] != 'CLOSED':
             print_error('FINAL', max_output_timestamp, f"Elevator {elev_id} door finished in state {e_state['door_state']}")

    # Check T_max constraint (using T_final)
    if max_output_timestamp > t_max + EPSILON:
        print_error('FINAL', max_output_timestamp, f"Final timestamp {max_output_timestamp:.4f} exceeds T_max ({t_max:.4f})")


    # Check if any errors were found during final checks
    if not correctness_ok:
        print("\nCORRECTNESS CHECK FAILED (See final state errors above). Performance metrics not calculated reliably.", file=sys.stderr)
        return False, None, None, None

    # 5. Calculate Performance Metrics (only if all checks passed)
    print("\nCORRECTNESS CHECK PASSED.", file=sys.stderr)

    t_final = max_output_timestamp

    # Calculate WT
    total_weighted_time = 0.0
    total_weight = 0.0
    calculation_error = False
    for p_id, p_state in passengers.items():
        if p_state['exit_time'] is None:
            # This should have been caught by correctness checks, but safeguard
            print(f"PERFORMANCE ERROR: Passenger {p_id} has no exit_time!", file=sys.stderr)
            calculation_error = True
            break
        completion_time = p_state['exit_time'] - p_state['request_time']
        if completion_time < -EPSILON:
             # Should not happen if timestamps are monotonic
             print(f"PERFORMANCE WARNING: Passenger {p_id} has negative completion time ({completion_time:.4f})!", file=sys.stderr)
             # Continue calculation, but flag potential issue

        total_weighted_time += completion_time * p_state['priority']
        total_weight += p_state['priority']

    wt = (total_weighted_time / total_weight) if total_weight > 0 else 0.0
    if calculation_error:
        wt = None # Indicate WT could not be calculated

    # Calculate W (Power)
    power_w = (POWER_OPEN * n_open) + (POWER_CLOSE * n_close) + (POWER_ARRIVE * n_arrive)

    return True, t_final, wt, power_w


# --- Argument Parsing and Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check Elevator Output Correctness and Calculate Performance Metrics")
    parser.add_argument("request_file", help="Path to the original passenger request file (.txt)")
    parser.add_argument("output_file", help="Path to the elevator simulation output file (.txt)")
    parser.add_argument(
        "--tmax", type=float, default=float('inf'),
        help="Optional: Maximum allowed final timestamp (T_max) for correctness check (e.g., 120.0 for HuCe)"
    )

    args = parser.parse_args()

    is_correct, t_final, wt, power = check_output(args.request_file, args.output_file, args.tmax)

    print("\n--- Results ---")
    if is_correct:
        print("Verdict: CORRECT")
        print(f" T_final (Max Output Timestamp): {t_final:.4f}")
        if wt is not None:
            print(f" WT (Weighted Avg Completion Time): {wt:.4f}")
        else:
             print(f" WT (Weighted Avg Completion Time): FAILED TO CALCULATE")
        print(f" W (Power Consumption): {power:.4f}")
        if wt is not None:
            print(f"Weighted Total Score(the less the better): {(t_final * 3 + wt * 3 + power * 4):.4f}")
        print("-" * 15)
        # print("Note: Final performance score 's' requires statistics across all submissions and is not calculated here.")
    else:
        # Specific error messages were printed to stderr during the check
        print("Verdict: INCORRECT")
        print("-" * 15)