# -*- coding: utf-8 -*-
import re
import json
import sys
import argparse # Import argparse for command-line argument parsing
from decimal import Decimal, getcontext, ROUND_HALF_UP

# Set Decimal precision
getcontext().prec = 10 # Adjust precision as needed for calculations

# --- Constants ---
# CORRECTED Floor Mapping based on hw6.md (B4-B1, F1-F7 = 11 floors)
FLOOR_MAP = {
    "B4": -3, "B3": -2, "B2": -1, "B1": 0,
    "F1": 1, "F2": 2, "F3": 3, "F4": 4, "F5": 5, "F6": 6, "F7": 7
}
INT_TO_FLOOR_MAP = {v: k for k, v in FLOOR_MAP.items()}
VALID_FLOORS_INT = set(FLOOR_MAP.values())
NUM_ELEVATORS = 6
DEFAULT_CAPACITY = 6
DEFAULT_MOVE_SPEED = Decimal("0.4")
DOOR_OPEN_CLOSE_TIME = Decimal("0.4")
SCHE_DOOR_STOP_TIME = Decimal("1.0")
SCHE_COMPLETE_TIME_LIMIT = Decimal("6.0")
SCHE_REQUEST_MIN_GAP = Decimal("6.0") # New constant for the gap
VALID_SCHE_SPEEDS = {Decimal("0.2"), Decimal("0.3"), Decimal("0.4"), Decimal("0.5")}
EPSILON = Decimal("0.0001") # For float comparisons

# Default Maximum Timestamp
DEFAULT_TMAX = Decimal("120.0") # NEW: Default max timestamp limit

# Performance Constants
W_ARRIVE = Decimal("0.4")
W_OPEN = Decimal("0.1")
W_CLOSE = Decimal("0.1")


# --- State Classes ---
class PassengerState:
    def __init__(self, pid, request_time, start_floor_int, dest_floor_int, priority):
        self.id = pid
        self.request_time = request_time
        self.start_floor_int = start_floor_int
        self.dest_floor_int = dest_floor_int
        self.priority = priority # Store for performance checks

        self.location = INT_TO_FLOOR_MAP.get(start_floor_int,"Unknown") # Initial location is start floor (string)
        self.is_request_active = True
        self.received_by = None # elevator_id or None
        self.last_action_time = request_time
        self.completion_time = None # Timestamp of successful OUT-S

class ElevatorState:
    def __init__(self, eid):
        self.id = eid
        self.current_floor_int = FLOOR_MAP["F1"] # Start at F1
        self.door_open = False
        self.passengers = set() # Set of passenger IDs inside
        self.capacity = DEFAULT_CAPACITY
        self.move_speed = DEFAULT_MOVE_SPEED
        self.last_action_time = Decimal("0.0")
        self.last_arrive_time = Decimal("-1.0")
        self.last_open_time = Decimal("-1.0")
        self.last_close_time = Decimal("0.0") # Initial state is closed
        # SCHE state
        self.sche_active = False
        self.sche_target_floor_int = None
        self.sche_temp_speed = None
        self.sche_accept_time = None
        self.sche_begin_time = None
        self.last_sche_end_time = Decimal("-inf") # NEW: Track last SCHE end time, initialize to negative infinity
        self.sche_input_details = None # NEW: Store the dict of the currently processed input SCHE request
        # RECEIVE state - CHANGED to dictionary
        self.active_receives = {} # pid -> receive_timestamp

    def get_current_floor_str(self):
        return INT_TO_FLOOR_MAP.get(self.current_floor_int, "Invalid")

# --- Checker Logic ---
class ElevatorChecker:
    # MODIFIED: Add tmax parameter to constructor
    def __init__(self, tmax=DEFAULT_TMAX):
        self.errors = []
        self.last_timestamp = Decimal("-1.0")
        self.elevators = {i: ElevatorState(i) for i in range(1, NUM_ELEVATORS + 1)}
        self.passengers = {} # pid -> PassengerState (populated from input)
        self.input_passenger_requests = {} # pid -> details_dict
        self.input_schedule_requests = {} # eid -> list of details_dicts
        self.global_active_receives = {}
        self.pending_sche = {} # eid -> (accept_time, target_floor_int, temp_speed, arrive_count, input_request_details)
        self.arrive_count = 0
        self.open_count = 0
        self.close_count = 0
        self.tmax = tmax # Store the maximum allowed timestamp

    def add_error(self, timestamp, message, is_input_error=False):
        # If timestamp is None or invalid, use 0.0 for prefix formatting
        try:
            ts_float = float(timestamp)
        except (TypeError, ValueError):
            ts_float = 0.0
        prefix = "[INPUT ERROR]" if is_input_error else f"[{ts_float:.4f}]"
        self.errors.append(f"{prefix} {message}")


    def parse_input_lines(self, input_lines):
        last_input_time = Decimal("-1.0")
        passenger_ids = set()

        for i, line in enumerate(input_lines):
            line = line.strip()
            if not line: continue

            # Try to extract timestamp first for tmax check
            t_str = None
            t_match = re.match(r"\[\s*(\d+\.\d+)\s*\]", line)
            if t_match:
                t_str = t_match.group(1)
                try:
                    timestamp = Decimal(t_str)
                    # --- NEW: Check against tmax for input timestamp ---
                    if timestamp > self.tmax:
                        self.add_error(timestamp, f"Line {i+1}: Input timestamp {timestamp:.4f} exceeds maximum allowed time {self.tmax:.4f}.", is_input_error=True)
                        # Continue parsing the line for other potential input errors, but Tmax violation is noted
                except ValueError:
                    self.add_error(Decimal("0"), f"Line {i+1}: Malformed timestamp in input: {t_str}", is_input_error=True)
                    continue # Skip further processing of this line if timestamp is malformed

            else: # If timestamp cannot be extracted, report error and skip
                self.add_error(Decimal("0"), f"Line {i+1}: Cannot extract timestamp from input line: {line}", is_input_error=True)
                continue

            # Proceed with parsing based on request type
            match_req = re.match(r"\[\s*(\d+\.\d+)\s*\](\d+)-PRI-(\d+)-FROM-([BF]\d+)-TO-([BF]\d+)", line)
            match_sche = re.match(r"\[\s*(\d+\.\d+)\s*\]SCHE-(\d+)-([\d\.]+)-([BF]\d+)", line)

            if match_req:
                # We already parsed and checked timestamp above
                _, pid_str, pri_str, from_str, to_str = match_req.groups()
                try:
                    pid = int(pid_str)
                    priority = int(pri_str)
                    if from_str not in FLOOR_MAP or to_str not in FLOOR_MAP: raise KeyError(f"Invalid floor name '{from_str}' or '{to_str}'")
                    from_floor_int = FLOOR_MAP[from_str]
                    to_floor_int = FLOOR_MAP[to_str]

                    # Timestamp monotonicity check (only if timestamp is valid)
                    if timestamp <= self.tmax and timestamp < last_input_time:
                         self.add_error(timestamp, f"Line {i+1}: Input timestamp non-decreasing violation.", is_input_error=True)
                    # Only update last_input_time if current timestamp is valid w.r.t tmax
                    if timestamp <= self.tmax:
                        last_input_time = timestamp

                    if pid <= 0: self.add_error(timestamp, f"Line {i+1}: Invalid Passenger ID {pid}. Must be positive.", is_input_error=True)
                    if pid in passenger_ids: self.add_error(timestamp, f"Line {i+1}: Duplicate Passenger ID {pid} in input.", is_input_error=True)
                    passenger_ids.add(pid)
                    if not (1 <= priority <= 100): self.add_error(timestamp, f"Line {i+1}: Invalid Priority {priority} for PID {pid}. Must be 1-100.", is_input_error=True)
                    if from_floor_int == to_floor_int: self.add_error(timestamp, f"Line {i+1}: Start and destination floors are the same ({from_str}) for PID {pid}.", is_input_error=True)

                    details = {'time': timestamp, 'priority': priority, 'from': from_floor_int, 'to': to_floor_int}
                    self.input_passenger_requests[pid] = details
                    # Only create passenger state if timestamp is valid
                    if timestamp <= self.tmax:
                        self.passengers[pid] = PassengerState(pid, timestamp, from_floor_int, to_floor_int, priority)
                    else:
                        # Mark as invalid request due to time limit, but store details for potential final checks
                        details['invalid_time'] = True


                except (ValueError, KeyError, IndexError) as e:
                    self.add_error(timestamp, f"Line {i+1}: Malformed passenger request: {line} -> {e}", is_input_error=True)

            elif match_sche:
                # We already parsed and checked timestamp above
                _, eid_str, speed_str, floor_str = match_sche.groups()
                try:
                    eid = int(eid_str)
                    speed = Decimal(speed_str)
                    if floor_str not in FLOOR_MAP: raise KeyError(f"Invalid floor name '{floor_str}'")
                    target_floor_int = FLOOR_MAP[floor_str]

                    # Timestamp monotonicity check (only if timestamp is valid)
                    if timestamp <= self.tmax and timestamp < last_input_time:
                         self.add_error(timestamp, f"Line {i+1}: Input timestamp non-decreasing violation.", is_input_error=True)
                    # Only update last_input_time if current timestamp is valid w.r.t tmax
                    if timestamp <= self.tmax:
                        last_input_time = timestamp

                    if not (1 <= eid <= NUM_ELEVATORS): self.add_error(timestamp, f"Line {i+1}: Invalid Elevator ID {eid}. Must be 1-{NUM_ELEVATORS}.", is_input_error=True)
                    if speed not in VALID_SCHE_SPEEDS: self.add_error(timestamp, f"Line {i+1}: Invalid SCHE speed {speed} for EID {eid}. Valid: {VALID_SCHE_SPEEDS}.", is_input_error=True)
                    valid_sche_targets_str = {"B2", "B1", "F1", "F2", "F3", "F4", "F5"}
                    if floor_str not in valid_sche_targets_str:
                        self.add_error(timestamp, f"Line {i+1}: Invalid SCHE target floor {floor_str} for EID {eid}. Valid: {valid_sche_targets_str}", is_input_error=True)

                    # Store SCHE request only if timestamp is valid
                    if timestamp <= self.tmax:
                        details = {'time': timestamp, 'speed': speed, 'target': target_floor_int, 'floor_str': floor_str}
                        self.input_schedule_requests.setdefault(eid, []).append(details)
                        self.input_schedule_requests[eid].sort(key=lambda x: x['time'])
                    # else: Ignore SCHE requests beyond tmax

                except (ValueError, KeyError, IndexError) as e:
                    self.add_error(timestamp, f"Line {i+1}: Malformed schedule request: {line} -> {e}", is_input_error=True)
            else:
                 # This case should ideally not be reached if timestamp extraction worked
                 # but handle unrecognized format after timestamp check
                 if line: self.add_error(timestamp if timestamp is not None else Decimal("0"), f"Line {i+1}: Unrecognized input format: {line}", is_input_error=True)

        # --- Adjusted Check for Number of *Valid* Passenger Requests ---
        num_valid_pass_req = sum(1 for pid, details in self.input_passenger_requests.items() if 'invalid_time' not in details)
        if not (1 <= num_valid_pass_req <= 100):
            # Report error if the *count* of requests *within* tmax is outside the range
            self.add_error(Decimal("0"), f"Input Error: Number of valid passenger requests (timestamp <= {self.tmax:.4f}) is {num_valid_pass_req}, which is not within the valid range [1, 100].", is_input_error=True)


    def get_passenger(self, pid, timestamp):
        # Check if passenger exists *at all* (even if their request time was > tmax)
        if pid not in self.input_passenger_requests:
            self.add_error(timestamp, f"Reference to unknown passenger ID {pid} (not found in input).")
            return None
        # Check if passenger state was created (meaning request time <= tmax)
        if pid not in self.passengers:
             # This means the passenger's request existed but was beyond tmax
             req_time = self.input_passenger_requests[pid].get('time', 'Unknown')
             self.add_error(timestamp, f"Reference to passenger ID {pid} whose request time ({req_time}) exceeded tmax ({self.tmax:.4f}). No actions should be performed for this passenger.")
             return None
        return self.passengers[pid]

    # --- Action Handlers (No changes needed inside these unless they reference input times directly) ---
    # ... (handle_arrive, handle_open, handle_close, handle_in, _handle_out, handle_receive, handle_sche_accept, handle_sche_begin, handle_sche_end) ...
    # Keep the existing action handlers exactly as they were in the previous version.
    # The timestamp check for the *output* line itself happens in the main `check` loop.
    # The input parsing already filters requests based on tmax.

    def handle_arrive(self, timestamp, args):
        # CORRECTED: Argument check message
        if len(args) != 2: return self.add_error(timestamp, f"ARRIVE: Invalid arguments {args}")
        floor_str, eid_str = args
        try:
            eid = int(eid_str)
            if not (1 <= eid <= NUM_ELEVATORS): raise ValueError("Invalid Elevator ID")
            elevator = self.elevators[eid]
            # Use corrected floor map for validation
            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            target_floor_int = FLOOR_MAP[floor_str]

            # --- Basic Validation ---
            if elevator.door_open: self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Cannot move with doors open.")

            floor_diff = abs(target_floor_int - elevator.current_floor_int)
            # Handle B1 <-> F1 crossing (distance 1)
            if (elevator.current_floor_int == 0 and target_floor_int == 1) or \
               (elevator.current_floor_int == 1 and target_floor_int == 0):
                floor_diff = 1
            # Handle B2 <-> B1 crossing (distance 1)
            elif (elevator.current_floor_int == -1 and target_floor_int == 0) or \
                 (elevator.current_floor_int == 0 and target_floor_int == -1):
                 floor_diff = 1

            if floor_diff != 1: self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Invalid move distance. From {elevator.get_current_floor_str()} ({elevator.current_floor_int}) to {floor_str} ({target_floor_int}). Must be 1 floor apart.")

            # --- Move Duration Check ---
            current_move_speed = elevator.move_speed # Use current speed (could be default or SCHE speed)
            expected_move_time = current_move_speed
            start_time_for_duration_check = max(elevator.last_close_time, elevator.last_arrive_time)
            time_since_start = timestamp - start_time_for_duration_check
            if time_since_start < expected_move_time - EPSILON: self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Move too fast. Expected >= {expected_move_time:.4f}, Actual: {time_since_start:.4f} (Since start at {start_time_for_duration_check:.4f})")

            # --- Check Move Start Time vs RECEIVE Time (If elevator is empty and not SCHE) ---
            if not elevator.sche_active and not elevator.passengers:
                min_receive_time = None
                if elevator.active_receives:
                    relevant_receive_times = [
                        receive_ts for pid, receive_ts in elevator.active_receives.items()
                        # Check if passenger exists *and* is outside this elevator
                        if pid in self.passengers and self.passengers[pid].location != eid
                    ]
                    if relevant_receive_times:
                        min_receive_time = min(relevant_receive_times)

                if min_receive_time is not None:
                    earliest_possible_start_of_this_move = timestamp - current_move_speed
                    if earliest_possible_start_of_this_move < min_receive_time - EPSILON:
                        self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Move potentially started at ~{earliest_possible_start_of_this_move:.4f} (ARRIVE {timestamp:.4f} - Speed {current_move_speed:.1f}) before the earliest relevant justifying RECEIVE at {min_receive_time:.4f}.")

            # --- Illegal Move Check (if empty, no receives, no SCHE) ---
            if not elevator.sche_active and not elevator.passengers and not elevator.active_receives:
                 self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Illegal move. Elevator is empty, has no active receives, and is not under SCHE.")

            # --- Update state AND Increment counter ---
            elevator.current_floor_int = target_floor_int
            elevator.last_action_time = timestamp
            elevator.last_arrive_time = timestamp
            self.arrive_count += 1

            # Track SCHE arrives (if SCHE-ACCEPT has occurred but SCHE-BEGIN hasn't yet)
            if eid in self.pending_sche:
                 accept_time, sche_target_floor, temp_speed, arrive_count, input_details = self.pending_sche[eid]
                 self.pending_sche[eid] = (accept_time, sche_target_floor, temp_speed, arrive_count + 1, input_details)

        except (ValueError, KeyError, IndexError) as e:
             self.add_error(timestamp, f"ARRIVE: Invalid argument or state error: {e} in '{floor_str}-{eid_str}'")

    def handle_open(self, timestamp, args):
        if len(args) != 2: return self.add_error(timestamp, f"OPEN: Invalid arguments {args}")
        floor_str, eid_str = args
        try:
            eid = int(eid_str)
            if not (1 <= eid <= NUM_ELEVATORS): raise ValueError("Invalid Elevator ID")
            elevator = self.elevators[eid]
            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            current_floor_int = FLOOR_MAP[floor_str]

            if elevator.current_floor_int != current_floor_int: self.add_error(timestamp, f"OPEN-{floor_str}-{eid}: Elevator not at this floor. Currently at {elevator.get_current_floor_str()}.")
            if elevator.door_open: self.add_error(timestamp, f"OPEN-{floor_str}-{eid}: Doors already open.")
            can_open_after = max(elevator.last_arrive_time, elevator.last_close_time)
            if timestamp < can_open_after - EPSILON :
                 self.add_error(timestamp, f"OPEN-{floor_str}-{eid}: Cannot open before arrival/close completed (Last relevant action at {can_open_after:.4f}).")

            if elevator.sche_active and elevator.current_floor_int != elevator.sche_target_floor_int: self.add_error(timestamp, f"OPEN-{floor_str}-{eid}: Cannot open doors during SCHE movement before reaching target {INT_TO_FLOOR_MAP.get(elevator.sche_target_floor_int)}.")

            elevator.door_open = True
            elevator.last_action_time = timestamp
            elevator.last_open_time = timestamp
            self.open_count += 1

        except (ValueError, KeyError, IndexError) as e:
             self.add_error(timestamp, f"OPEN: Invalid argument or state error: {e} in '{floor_str}-{eid_str}'")


    def handle_close(self, timestamp, args):
        if len(args) != 2: return self.add_error(timestamp, f"CLOSE: Invalid arguments {args}")
        floor_str, eid_str = args
        try:
            eid = int(eid_str)
            if not (1 <= eid <= NUM_ELEVATORS): raise ValueError("Invalid Elevator ID")
            elevator = self.elevators[eid]
            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            current_floor_int = FLOOR_MAP[floor_str]

            if elevator.current_floor_int != current_floor_int: self.add_error(timestamp, f"CLOSE-{floor_str}-{eid}: Elevator not at this floor. Currently at {elevator.get_current_floor_str()}.")
            if not elevator.door_open: self.add_error(timestamp, f"CLOSE-{floor_str}-{eid}: Doors already closed.")

            is_sche_stop = elevator.sche_active and elevator.current_floor_int == elevator.sche_target_floor_int
            required_open_time = SCHE_DOOR_STOP_TIME if is_sche_stop else DOOR_OPEN_CLOSE_TIME
            time_since_open = timestamp - elevator.last_open_time
            if time_since_open < required_open_time - EPSILON: self.add_error(timestamp, f"CLOSE-{floor_str}-{eid}: Doors closed too fast. Required >= {required_open_time:.4f}s, Actual: {time_since_open:.4f}s (Since OPEN at {elevator.last_open_time:.4f}) {'[SCHE Stop]' if is_sche_stop else ''}")

            elevator.door_open = False
            elevator.last_action_time = timestamp
            elevator.last_close_time = timestamp
            self.close_count += 1

        except (ValueError, KeyError, IndexError) as e:
             self.add_error(timestamp, f"CLOSE: Invalid argument or state error: {e} in '{floor_str}-{eid_str}'")

    def handle_in(self, timestamp, args):
        if len(args) != 3: return self.add_error(timestamp, f"IN: Invalid arguments {args}")
        pid_str, floor_str, eid_str = args
        try:
            pid = int(pid_str)
            eid = int(eid_str)
            if not (1 <= eid <= NUM_ELEVATORS): raise ValueError("Invalid Elevator ID")
            # Use the modified get_passenger which checks for tmax validity
            passenger = self.get_passenger(pid, timestamp)
            if passenger is None: return # Error already added by get_passenger
            elevator = self.elevators[eid]
            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            current_floor_int = FLOOR_MAP[floor_str]

            if not elevator.door_open: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Cannot enter, doors closed.")
            if elevator.current_floor_int != current_floor_int: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Elevator not at this floor. Currently at {elevator.get_current_floor_str()}.")
            if passenger.location == eid: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger already inside this elevator.")
            elif isinstance(passenger.location, int): self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger inside another elevator ({passenger.location}).")
            elif passenger.location != floor_str:
                 is_first_pickup = passenger.received_by == eid
                 if is_first_pickup and passenger.start_floor_int != current_floor_int:
                      self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger's start floor ({INT_TO_FLOOR_MAP.get(passenger.start_floor_int)}) does not match current floor ({floor_str}).")
                 elif not is_first_pickup:
                     self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger location ({passenger.location}) does not match elevator floor ({floor_str}).")

            if len(elevator.passengers) >= elevator.capacity: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Elevator full (Capacity: {elevator.capacity}).")
            if passenger.received_by != eid: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger was not actively RECEIVE'd by this elevator {eid}. Currently received by: {passenger.received_by}")
            if elevator.sche_active: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Cannot enter elevator during active SCHE (between SCHE-BEGIN and SCHE-END).")

            # Update state
            elevator.passengers.add(pid)
            passenger.location = eid
            passenger.last_action_time = timestamp
        except (ValueError, KeyError, IndexError) as e:
             self.add_error(timestamp, f"IN: Invalid argument or state error: {e} in '{pid_str}-{floor_str}-{eid_str}'")


    def handle_out_s(self, timestamp, args):
        self._handle_out(timestamp, args, success=True)

    def handle_out_f(self, timestamp, args):
        self._handle_out(timestamp, args, success=False)

    def _handle_out(self, timestamp, args, success):
        out_type = "OUT-S" if success else "OUT-F"
        if len(args) != 3: return self.add_error(timestamp, f"{out_type}: Invalid arguments {args}")
        pid_str, floor_str, eid_str = args
        try:
            pid = int(pid_str)
            eid = int(eid_str)
            if not (1 <= eid <= NUM_ELEVATORS): raise ValueError("Invalid Elevator ID")
            # Use the modified get_passenger which checks for tmax validity
            passenger = self.get_passenger(pid, timestamp)
            if passenger is None: return # Error already added by get_passenger
            elevator = self.elevators[eid]
            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            current_floor_int = FLOOR_MAP[floor_str]

            if not elevator.door_open: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Cannot exit, doors closed.")
            if elevator.current_floor_int != current_floor_int: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Elevator not at this floor. Currently at {elevator.get_current_floor_str()}.")
            if passenger.location != eid: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Passenger not inside this elevator {eid}. Current location: {passenger.location}")
            if elevator.sche_active and elevator.current_floor_int != elevator.sche_target_floor_int: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Cannot exit during SCHE except at the target floor {INT_TO_FLOOR_MAP.get(elevator.sche_target_floor_int)}")

            if success: # OUT-S
                if passenger.dest_floor_int != current_floor_int:
                     self.add_error(timestamp, f"OUT-S-{pid}-{floor_str}-{eid}: Exited successfully at {floor_str}, but input destination was {INT_TO_FLOOR_MAP.get(passenger.dest_floor_int, 'Unknown')}")
                else:
                     if passenger.completion_time is None: passenger.completion_time = timestamp
                     passenger.is_request_active = False # Mark as completed
            else: # OUT-F
                if passenger.dest_floor_int == current_floor_int: self.add_error(timestamp, f"OUT-F-{pid}-{floor_str}-{eid}: Exited with failure (OUT-F), but current floor {floor_str} matches input destination.")
                passenger.start_floor_int = current_floor_int
                passenger.is_request_active = True

            # --- Update State ---
            if pid in elevator.passengers: elevator.passengers.remove(pid)
            else: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Passenger {pid} was not in elevator {eid}'s set, inconsistency.")
            passenger.location = floor_str
            passenger.last_action_time = timestamp

            # --- Cancel RECEIVE state for this passenger (on this elevator) ---
            if passenger.received_by == eid:
                passenger.received_by = None
                if pid in self.global_active_receives and self.global_active_receives[pid] == eid:
                    del self.global_active_receives[pid]
                if pid in elevator.active_receives:
                    del elevator.active_receives[pid]

        except (ValueError, KeyError, IndexError) as e:
             self.add_error(timestamp, f"{out_type}: Invalid argument or state error: {e} in '{pid_str}-{floor_str}-{eid_str}'")


    def handle_receive(self, timestamp, args):
        if len(args) != 2: return self.add_error(timestamp, f"RECEIVE: Invalid arguments {args}")
        pid_str, eid_str = args
        try:
            pid = int(pid_str)
            eid = int(eid_str)
            if not (1 <= eid <= NUM_ELEVATORS): raise ValueError("Invalid Elevator ID")
            elevator = self.elevators[eid]
            # Use the modified get_passenger which checks for tmax validity
            passenger = self.get_passenger(pid, timestamp)
            if passenger is None: return # Error already added by get_passenger

            if isinstance(passenger.location, int): self.add_error(timestamp, f"RECEIVE-{pid}-{eid}: Cannot RECEIVE passenger already inside elevator {passenger.location}.")
            if pid in self.global_active_receives and self.global_active_receives[pid] != eid: self.add_error(timestamp, f"RECEIVE-{pid}-{eid}: Passenger {pid} already actively received by elevator {self.global_active_receives[pid]}.")
            if elevator.sche_active: self.add_error(timestamp, f"RECEIVE-{pid}-{eid}: Cannot output RECEIVE for elevator {eid} during its active SCHE.")

            # Update State
            passenger.received_by = eid
            elevator.active_receives[pid] = timestamp
            self.global_active_receives[pid] = eid

        except (ValueError, KeyError, IndexError) as e:
             self.add_error(timestamp, f"RECEIVE: Invalid argument: {e} in '{'-'.join(args)}'")


    def handle_sche_accept(self, timestamp, args):
        if len(args) != 3: return self.add_error(timestamp, f"SCHE-ACCEPT: Invalid arguments {args}")
        eid_str, speed_str, floor_str = args
        try:
            eid = int(eid_str)
            speed = Decimal(speed_str)
            if not (1 <= eid <= NUM_ELEVATORS): raise ValueError("Invalid Elevator ID")
            elevator = self.elevators[eid]
            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            target_floor_int = FLOOR_MAP[floor_str]

            # Input SCHE requests > tmax were already filtered out during input parsing
            pending_input_requests = self.input_schedule_requests.get(eid, [])
            if not pending_input_requests:
                self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Elevator {eid} received SCHE-ACCEPT, but no corresponding SCHE requests found or remaining in input (within tmax <= {self.tmax:.4f}).")
                return

            current_input_request = pending_input_requests[0]
            req_time = current_input_request['time']
            expected_speed = current_input_request['speed']
            expected_target_floor = current_input_request['target']
            expected_floor_str = current_input_request['floor_str']

            # We know req_time <= tmax because it was filtered during input parsing
            if req_time < elevator.last_sche_end_time + SCHE_REQUEST_MIN_GAP - EPSILON:
                self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Input SCHE request time {req_time:.4f} is less than {SCHE_REQUEST_MIN_GAP}s after previous SCHE ended at {elevator.last_sche_end_time:.4f}.")

            if speed != expected_speed: self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Accepted speed {speed} does not match input SCHE request speed {expected_speed} (from input line at {req_time:.4f}).")
            if target_floor_int != expected_target_floor: self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Accepted target floor {floor_str} ({target_floor_int}) does not match input SCHE request target {expected_floor_str} ({expected_target_floor}) (from input line at {req_time:.4f}).")

            self.pending_sche[eid] = (timestamp, target_floor_int, speed, 0, current_input_request)
            elevator.sche_accept_time = timestamp

        except (ValueError, KeyError, IndexError) as e:
            self.add_error(timestamp, f"SCHE-ACCEPT: Invalid argument or state error: {e} in '{'-'.join(args)}'")

    def handle_sche_begin(self, timestamp, args):
        if len(args) != 1: return self.add_error(timestamp, f"SCHE-BEGIN: Invalid arguments {args}")
        eid_str = args[0]
        try:
            eid = int(eid_str)
            if not (1 <= eid <= NUM_ELEVATORS): raise ValueError("Invalid Elevator ID")
            elevator = self.elevators[eid]

            if eid not in self.pending_sche: self.add_error(timestamp, f"SCHE-BEGIN-{eid}: SCHE-ACCEPT was not received or already processed for the current SCHE cycle.") ; return

            accept_time, target_floor_int, temp_speed, arrive_count, input_request_details = self.pending_sche[eid]

            if elevator.door_open: self.add_error(timestamp, f"SCHE-BEGIN-{eid}: Cannot begin SCHE with doors open.")
            if arrive_count > 2: self.add_error(timestamp, f"SCHE-BEGIN-{eid}: Began after {arrive_count} ARRIVEs since SCHE-ACCEPT (Max 2 allowed).")

            elevator.sche_active = True
            elevator.sche_target_floor_int = target_floor_int
            elevator.sche_temp_speed = temp_speed
            elevator.move_speed = temp_speed
            elevator.sche_begin_time = timestamp
            elevator.sche_input_details = input_request_details

            # Cancel relevant RECEIVEs
            pids_to_cancel_receive = list(elevator.active_receives.keys())
            for pid in pids_to_cancel_receive:
                 # Use get_passenger to ensure passenger is valid (req_time <= tmax)
                 passenger = self.get_passenger(pid, timestamp)
                 if passenger and passenger.location != eid: # Passenger exists and is outside
                     if passenger.received_by == eid: passenger.received_by = None
                     if pid in self.global_active_receives and self.global_active_receives[pid] == eid:
                         del self.global_active_receives[pid]
                     del elevator.active_receives[pid]
                 elif not passenger: # get_passenger failed (likely > tmax or not in input)
                      # If they were somehow in active_receives, remove them defensively
                     if pid in elevator.active_receives:
                         self.add_error(timestamp, f"SCHE-BEGIN-{eid}: Internal inconsistency - Passenger {pid} in active_receives but no valid state found (possibly request time > tmax). Removing.")
                         del elevator.active_receives[pid]
                         # Also clear from global if needed
                         if pid in self.global_active_receives and self.global_active_receives[pid] == eid:
                             del self.global_active_receives[pid]

            del self.pending_sche[eid]

        except (ValueError, KeyError, IndexError) as e:
             self.add_error(timestamp, f"SCHE-BEGIN: Invalid argument or state error: {e} in '{'-'.join(args)}'")


    def handle_sche_end(self, timestamp, args):
        if len(args) != 1: return self.add_error(timestamp, f"SCHE-END: Invalid arguments {args}")
        eid_str = args[0]
        try:
            eid = int(eid_str)
            if not (1 <= eid <= NUM_ELEVATORS): raise ValueError("Invalid Elevator ID")
            elevator = self.elevators[eid]

            if not elevator.sche_active: self.add_error(timestamp, f"SCHE-END-{eid}: Elevator was not in an active SCHE state.") ; return
            if elevator.door_open: self.add_error(timestamp, f"SCHE-END-{eid}: Doors must be closed before ending SCHE.")
            if elevator.current_floor_int != elevator.sche_target_floor_int: self.add_error(timestamp, f"SCHE-END-{eid}: Elevator ended SCHE but is not at target floor {INT_TO_FLOOR_MAP.get(elevator.sche_target_floor_int)}. Current: {elevator.get_current_floor_str()}")
            if elevator.passengers: self.add_error(timestamp, f"SCHE-END-{eid}: Elevator must be empty to end SCHE. Contains: {elevator.passengers}")

            if elevator.sche_accept_time is None: self.add_error(timestamp, f"SCHE-END-{eid}: Cannot check T_complete, SCHE-ACCEPT time not recorded (internal error).")
            else:
                t_complete = timestamp - elevator.sche_accept_time
                if t_complete > SCHE_COMPLETE_TIME_LIMIT + EPSILON: self.add_error(timestamp, f"SCHE-END-{eid}: SCHE completion time T_complete ({t_complete:.4f}s) exceeds limit ({SCHE_COMPLETE_TIME_LIMIT}s). ACCEPT was at {elevator.sche_accept_time:.4f}")

            completed_input_details = elevator.sche_input_details

            elevator.sche_active = False
            elevator.move_speed = DEFAULT_MOVE_SPEED
            elevator.sche_target_floor_int = None
            elevator.sche_temp_speed = None
            elevator.sche_accept_time = None
            elevator.sche_begin_time = None
            elevator.sche_input_details = None
            elevator.last_action_time = timestamp
            elevator.last_sche_end_time = timestamp

            if completed_input_details:
                request_list = self.input_schedule_requests.get(eid)
                if request_list:
                    try:
                        request_list.remove(completed_input_details)
                    except ValueError:
                        self.add_error(timestamp, f"SCHE-END-{eid}: Internal error - Could not find the completed SCHE request details in the input list to remove it.")
                else:
                     self.add_error(timestamp, f"SCHE-END-{eid}: Internal error - No input request list found for elevator {eid} while trying to remove completed request.")
            else:
                 self.add_error(timestamp, f"SCHE-END-{eid}: Internal error - No stored input request details found for the completed SCHE cycle.")


        except (ValueError, KeyError, IndexError) as e:
            self.add_error(timestamp, f"SCHE-END: Invalid argument or state error: {e} in '{'-'.join(args)}'")

    # --- Final Checks ---
    def perform_final_checks(self, final_timestamp):
        # Only check passengers whose request time was <= tmax
        all_passengers_completed = True
        for pid, p_state in self.passengers.items(): # self.passengers only contains those with valid request times
            if p_state.is_request_active:
                 all_passengers_completed = False
                 req_time = p_state.request_time # Already checked <= tmax to be in self.passengers
                 self.add_error(final_timestamp, f"FINAL CHECK: Input passenger request {pid} (ReqTime: {req_time:.4f}, From: {INT_TO_FLOOR_MAP.get(p_state.start_floor_int, '?')}, To: {INT_TO_FLOOR_MAP.get(p_state.dest_floor_int, '?')}) was not completed successfully.")
            elif p_state.completion_time is None:
                 self.add_error(final_timestamp, f"FINAL CHECK: Passenger {pid} marked inactive, but completion time not recorded (likely internal error or missed/invalid OUT-S).")

        # Also check if any requests were defined in input but ignored due to tmax
        for pid, details in self.input_passenger_requests.items():
            if 'invalid_time' in details:
                self.add_error(final_timestamp, f"FINAL CHECK: Input passenger request {pid} (ReqTime: {details['time']:.4f}) was ignored because its timestamp exceeded tmax ({self.tmax:.4f}).")
                # If requests > tmax exist, the overall run can't be 'Success' in terms of fulfilling all input lines,
                # but the checker logic might pass if *valid* requests were handled.
                # We'll let the presence of this error contribute to a "Fail" result.
                all_passengers_completed = False # Consider this a failure condition

        # Check elevators (same as before)
        for eid, e_state in self.elevators.items():
            if e_state.door_open: self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid}'s doors are open.")
            if e_state.passengers: self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid} still contains passengers: {e_state.passengers}")
            if e_state.sche_active: self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid} is still in SCHE mode (missing SCHE-END).")
            # Check remaining *valid* SCHE requests (req_time <= tmax)
            remaining_sche_requests = self.input_schedule_requests.get(eid, [])
            if remaining_sche_requests:
                 remaining_details = [f"(Time: {req['time']}, Speed: {req['speed']}, Target: {req['floor_str']})" for req in remaining_sche_requests]
                 self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid} has unprocessed input SCHE requests (within tmax): {', '.join(remaining_details)}")
                 all_passengers_completed = False # Unprocessed SCHE is also a failure

        return all_passengers_completed

    # --- Utility ---
    def parse_line(self, line):
        # Keep this function as is
        match = re.match(r"\[\s*(\d+\.\d+)\s*\](.*)", line)
        if not match: return None, None, None
        timestamp_str, data = match.groups()
        timestamp = Decimal(timestamp_str) # Conversion happens here
        parts = data.strip().split('-')
        if not parts: return timestamp, "INVALID_FORMAT", []
        action = parts[0]
        args = parts[1:]
        if action == "OUT" and len(parts) >= 2 and parts[1] in ('S', 'F'):
            action = f"OUT-{parts[1]}"
            args = parts[2:]
        elif action == "SCHE" and len(parts) >= 2:
            sub_action = parts[1]
            if sub_action in ("ACCEPT", "BEGIN", "END"):
                action = f"SCHE-{sub_action}"
                args = parts[2:]
            else:
                 action = "INVALID_SCHE_SUBACTION"
        elif action not in ("ARRIVE", "OPEN", "CLOSE", "IN", "RECEIVE"):
             action = "UNKNOWN_ACTION"

        return timestamp, action, args

    # --- Performance Calculation ---
    def calculate_performance(self):
        # Calculates performance based only on passengers whose request time was <= tmax
        # and who were successfully completed.
        t_final = self.last_timestamp
        energy_w = (self.open_count * W_OPEN) + (self.close_count * W_CLOSE) + (self.arrive_count * W_ARRIVE)
        total_weighted_time = Decimal(0)
        total_weight = Decimal(0)

        # Iterate through passengers state (only contains valid time requests)
        for pid, p_state in self.passengers.items():
            if p_state.completion_time is not None: # Check if completed
                 # request_time is guaranteed to be <= tmax here
                t_i = p_state.completion_time - p_state.request_time
                if t_i < 0: t_i = Decimal(0)
                w_i = Decimal(p_state.priority)
                total_weighted_time += t_i * w_i
                total_weight += w_i

        weighted_time_wt = Decimal("NaN")
        if total_weight > 0:
            weighted_time_wt = total_weighted_time / total_weight

        # Ensure final timestamp used for calculation doesn't exceed tmax
        # Note: self.last_timestamp could be > tmax if the *last* line violated it.
        # Performance should ideally reflect activity *up to* tmax? Or up to the last *valid* timestamp?
        # Let's use min(self.last_timestamp, self.tmax) if we want to cap performance calculation time.
        # However, the current definition uses the last observed timestamp. We'll stick to that for now.
        # T_final definition might need clarification if timestamps can exceed tmax.
        # For now, use self.last_timestamp as calculated.

        t_final_float = float(t_final.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        energy_w_float = float(energy_w.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        weighted_time_wt_float = float('nan') if weighted_time_wt.is_nan() else float(weighted_time_wt.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

        return {
            "T_final": t_final_float,
            "W_energy": energy_w_float,
            "WT_weighted_time": weighted_time_wt_float,
            "RawCounts": {
                "ARRIVE": self.arrive_count,
                "OPEN": self.open_count,
                "CLOSE": self.close_count
            }
        }


    # --- Main Check Function ---
    def check(self, input_lines, output_lines):
        # 1. Parse Input (uses the modified parse_input_lines which checks input tmax)
        self.parse_input_lines(input_lines)
        # Check for input errors *after* parsing all input
        if any("[INPUT ERROR]" in err for err in self.errors):
            return json.dumps({"result": "Fail", "errors": self.errors}, indent=2)

        # 2. Process Output lines
        output_processing_errors = False # Flag if errors occur *during* output processing
        for i, line in enumerate(output_lines):
            line = line.strip()
            if not line: continue

            timestamp, action, args = self.parse_line(line)

            if timestamp is None:
                self.add_error(Decimal("0.0"), f"Line {i+1}: Malformed output line format: {line}")
                output_processing_errors = True
                continue # Skip processing this line

            # --- NEW: Check output timestamp against tmax ---
            if timestamp > self.tmax:
                self.add_error(timestamp, f"Line {i+1}: Output timestamp {timestamp:.4f} exceeds maximum allowed time {self.tmax:.4f}.")
                # We might want to stop processing further lines after a Tmax violation in output,
                # or just record the error and continue checking the rest for other errors.
                # Let's record and continue for now.
                output_processing_errors = True
                # We still update last_timestamp to check monotonicity, but the line itself is invalid.
                self.last_timestamp = max(self.last_timestamp, timestamp)
                continue # Skip handling the action for this line


            if action in ("INVALID_FORMAT", "UNKNOWN_ACTION", "INVALID_SCHE_SUBACTION"):
                self.add_error(timestamp, f"Line {i+1}: Invalid action '{action}' or format in output: {line}")
                output_processing_errors = True
                self.last_timestamp = max(self.last_timestamp, timestamp) # Still update timestamp
                continue # Skip handling the action


            # Timestamp monotonicity check (only compare against previous *valid* timestamps)
            # Note: self.last_timestamp might have been updated by a line > tmax.
            # The check should be if the current valid timestamp is less than the last *valid* one.
            # This is implicitly handled by checking if timestamp < self.last_timestamp. If the previous
            # one was invalid (>tmax), this check might pass spuriously, but the previous line
            # would have already generated an error.
            if timestamp < self.last_timestamp - EPSILON:
                 self.add_error(timestamp, f"Timestamp non-decreasing violation. Current: {timestamp:.4f}, Previous: {self.last_timestamp:.4f}")
                 output_processing_errors = True
            self.last_timestamp = max(self.last_timestamp, timestamp) # Update with current valid timestamp

            # Dynamically call the correct handler
            try:
                handler_name = f"handle_{action.replace('-', '_').lower()}"
                handler = getattr(self, handler_name, None)
                if handler:
                    handler(timestamp, args)
                else:
                    self.add_error(timestamp, f"Internal Error: No handler found for action '{action}'.")
                    output_processing_errors = True # Treat as processing error
            except Exception as e:
                 self.add_error(timestamp, f"Internal checker error processing action '{action}' with args {args} on line {i+1}: {e}\nLine content: {line}")
                 import traceback
                 self.errors.append(f"Traceback: {traceback.format_exc()}")
                 output_processing_errors = True # Treat as processing error

        # --- Final Correctness Checks ---
        # Perform final checks regardless of output processing errors to catch things like incomplete requests
        all_requests_done = self.perform_final_checks(self.last_timestamp)

        # --- Result ---
        # Fail if there were *any* errors (input, output processing, final checks)
        if self.errors:
            return json.dumps({"result": "Fail", "errors": self.errors}, indent=2)
        else:
            # Success only if NO errors AND all valid requests completed
            performance_metrics = self.calculate_performance()
            return json.dumps({
                "result": "Success",
                "performance": performance_metrics
            }, indent=2)


# --- Main Execution ---
if __name__ == "__main__":
    # --- MODIFIED: Use argparse ---
    parser = argparse.ArgumentParser(description="Checks elevator simulation output against input and rules.")
    parser.add_argument("input_file", help="Path to the input request file.")
    parser.add_argument("output_file", help="Path to the simulation output file.")
    parser.add_argument("--tmax", type=Decimal, default=DEFAULT_TMAX,
                        help=f"Maximum allowed timestamp (default: {DEFAULT_TMAX})")

    args = parser.parse_args()

    input_lines = []
    output_lines = []

    # Validate tmax value provided
    if args.tmax <= 0:
        print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] --tmax value ({args.tmax}) must be positive."]}, indent=2))
        sys.exit(1)


    try:
        with open(args.input_file, 'r', encoding='utf-8') as f: input_lines = f.readlines()
    except FileNotFoundError: print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Input file not found: {args.input_file}"]}, indent=2)); sys.exit(1)
    except Exception as e: print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Error reading input file: {e}"]}, indent=2)); sys.exit(1)

    try:
        with open(args.output_file, 'r', encoding='utf-8') as f: output_lines = f.readlines()
    except FileNotFoundError: print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Output file not found: {args.output_file}"]}, indent=2)); sys.exit(1)
    except Exception as e: print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Error reading output file: {e}"]}, indent=2)); sys.exit(1)

    # Create checker instance with the specified tmax
    checker = ElevatorChecker(tmax=args.tmax)
    result_json = checker.check(input_lines, output_lines)
    print(result_json)