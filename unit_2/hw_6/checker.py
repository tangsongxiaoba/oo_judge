# -*- coding: utf-8 -*-
import re
import json
import sys
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
        # self.expected_sche_details = None # REMOVED: Use input_schedule_requests instead
        self.last_sche_end_time = Decimal("-inf") # NEW: Track last SCHE end time, initialize to negative infinity
        self.sche_input_details = None # NEW: Store the dict of the currently processed input SCHE request
        # RECEIVE state - CHANGED to dictionary
        self.active_receives = {} # pid -> receive_timestamp

    def get_current_floor_str(self):
        return INT_TO_FLOOR_MAP.get(self.current_floor_int, "Invalid")

# --- Checker Logic ---
class ElevatorChecker:
    def __init__(self):
        self.errors = []
        self.last_timestamp = Decimal("-1.0")
        self.elevators = {i: ElevatorState(i) for i in range(1, NUM_ELEVATORS + 1)}
        self.passengers = {} # pid -> PassengerState (populated from input)
        self.input_passenger_requests = {} # pid -> details_dict
        # MODIFIED: Store a list of SCHE requests per elevator
        self.input_schedule_requests = {} # eid -> list of details_dicts

        # Global track of active receives {pid: elevator_id} - used ONLY for exclusivity check
        self.global_active_receives = {}
        # Track SCHE-ACCEPT details before SCHE-BEGIN
        # MODIFIED: Also store the original input request details being processed
        self.pending_sche = {} # eid -> (accept_time, target_floor_int, temp_speed, arrive_count, input_request_details)

        # --- Performance Counters ---
        self.arrive_count = 0
        self.open_count = 0
        self.close_count = 0

    def add_error(self, timestamp, message, is_input_error=False):
        prefix = "[INPUT ERROR]" if is_input_error else f"[{float(timestamp):.4f}]"
        self.errors.append(f"{prefix} {message}")

    def parse_input_lines(self, input_lines):
        last_input_time = Decimal("-1.0")
        passenger_ids = set()

        for i, line in enumerate(input_lines):
            line = line.strip()
            if not line: continue

            match_req = re.match(r"\[\s*(\d+\.\d+)\s*\](\d+)-PRI-(\d+)-FROM-([BF]\d+)-TO-([BF]\d+)", line)
            match_sche = re.match(r"\[\s*(\d+\.\d+)\s*\]SCHE-(\d+)-([\d\.]+)-([BF]\d+)", line)

            if match_req:
                t_str, pid_str, pri_str, from_str, to_str = match_req.groups()
                try:
                    timestamp = Decimal(t_str)
                    pid = int(pid_str)
                    priority = int(pri_str)
                    if from_str not in FLOOR_MAP or to_str not in FLOOR_MAP: raise KeyError(f"Invalid floor name '{from_str}' or '{to_str}'")
                    from_floor_int = FLOOR_MAP[from_str]
                    to_floor_int = FLOOR_MAP[to_str]

                    if timestamp < last_input_time: self.add_error(timestamp, f"Line {i+1}: Input timestamp non-decreasing violation.", is_input_error=True)
                    last_input_time = timestamp
                    if pid <= 0: self.add_error(timestamp, f"Line {i+1}: Invalid Passenger ID {pid}. Must be positive.", is_input_error=True)
                    if pid in passenger_ids: self.add_error(timestamp, f"Line {i+1}: Duplicate Passenger ID {pid} in input.", is_input_error=True)
                    passenger_ids.add(pid)
                    if not (1 <= priority <= 100): self.add_error(timestamp, f"Line {i+1}: Invalid Priority {priority} for PID {pid}. Must be 1-100.", is_input_error=True)
                    if from_floor_int == to_floor_int: self.add_error(timestamp, f"Line {i+1}: Start and destination floors are the same ({from_str}) for PID {pid}.", is_input_error=True)

                    details = {'time': timestamp, 'priority': priority, 'from': from_floor_int, 'to': to_floor_int}
                    self.input_passenger_requests[pid] = details
                    self.passengers[pid] = PassengerState(pid, timestamp, from_floor_int, to_floor_int, priority)

                except (ValueError, KeyError, IndexError) as e:
                    self.add_error(Decimal(t_str) if t_str else Decimal("0"), f"Line {i+1}: Malformed passenger request: {line} -> {e}", is_input_error=True)

            elif match_sche:
                t_str, eid_str, speed_str, floor_str = match_sche.groups()
                try:
                    timestamp = Decimal(t_str)
                    eid = int(eid_str)
                    speed = Decimal(speed_str)
                    if floor_str not in FLOOR_MAP: raise KeyError(f"Invalid floor name '{floor_str}'")
                    target_floor_int = FLOOR_MAP[floor_str]

                    if timestamp < last_input_time: self.add_error(timestamp, f"Line {i+1}: Input timestamp non-decreasing violation.", is_input_error=True)
                    last_input_time = timestamp
                    if not (1 <= eid <= NUM_ELEVATORS): self.add_error(timestamp, f"Line {i+1}: Invalid Elevator ID {eid}. Must be 1-{NUM_ELEVATORS}.", is_input_error=True)
                    if speed not in VALID_SCHE_SPEEDS: self.add_error(timestamp, f"Line {i+1}: Invalid SCHE speed {speed} for EID {eid}. Valid: {VALID_SCHE_SPEEDS}.", is_input_error=True)
                    valid_sche_targets_str = {"B2", "B1", "F1", "F2", "F3", "F4", "F5"}
                    if floor_str not in valid_sche_targets_str:
                        self.add_error(timestamp, f"Line {i+1}: Invalid SCHE target floor {floor_str} for EID {eid}. Valid: {valid_sche_targets_str}", is_input_error=True)

                    # --- MODIFIED: Store SCHE request in a list for the elevator ---
                    details = {'time': timestamp, 'speed': speed, 'target': target_floor_int, 'floor_str': floor_str} # Store floor_str for potential error messages
                    # Initialize the list if this is the first SCHE for this elevator
                    self.input_schedule_requests.setdefault(eid, []).append(details)
                    # Sort the list by time just in case input is not strictly ordered per elevator (though overall time must increase)
                    # This assumes we process SCHE requests for a given elevator in their input time order.
                    self.input_schedule_requests[eid].sort(key=lambda x: x['time'])

                    # REMOVED: Single SCHE request check
                    # if eid in self.input_schedule_requests: self.add_error(timestamp, f"Line {i+1}: Multiple SCHE requests for Elevator {eid} in input (violates H/W constraint).", is_input_error=True)
                    # self.input_schedule_requests[eid] = {'time': timestamp, 'speed': speed, 'target': target_floor_int}
                    # self.elevators[eid].expected_sche_details = (timestamp, speed, target_floor_int)

                except (ValueError, KeyError, IndexError) as e:
                    self.add_error(Decimal(t_str) if t_str else Decimal("0"), f"Line {i+1}: Malformed schedule request: {line} -> {e}", is_input_error=True)
            else:
                if line: self.add_error(Decimal("0"), f"Line {i+1}: Unrecognized input format: {line}", is_input_error=True)

        num_pass_req = len(self.input_passenger_requests)
        if not (1 <= num_pass_req <= 100): self.add_error(Decimal("0"), f"Input Error: Number of passenger requests ({num_pass_req}) is not within the valid range [1, 100].", is_input_error=True)


    def get_passenger(self, pid, timestamp):
        if pid not in self.passengers:
            self.add_error(timestamp, f"Reference to unknown passenger ID {pid} (not found in input).")
            return None
        return self.passengers[pid]

    # --- Action Handlers ---

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
            # CORRECTED: Allow ARRIVE at exactly last_close_time + move_speed
            # The actual check is based on duration below, this check is less precise
            # if timestamp <= elevator.last_close_time: self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Cannot start moving at the same time as or before the last close action finished (Last CLOSE at {elevator.last_close_time:.4f}).")

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
            # Move can start *after* the previous ARRIVE or *after* the doors finish closing
            start_time_for_duration_check = max(elevator.last_close_time, elevator.last_arrive_time)
            time_since_start = timestamp - start_time_for_duration_check
            if time_since_start < expected_move_time - EPSILON: self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Move too fast. Expected >= {expected_move_time:.4f}, Actual: {time_since_start:.4f} (Since start at {start_time_for_duration_check:.4f})")


            # --- Check Move Start Time vs RECEIVE Time (If elevator is empty and not SCHE) ---
            if not elevator.sche_active and not elevator.passengers:
                min_receive_time = None
                if elevator.active_receives:
                    relevant_receive_times = [
                        receive_ts for pid, receive_ts in elevator.active_receives.items()
                        if pid in self.passengers and self.passengers[pid].location != eid # Passenger is outside this elevator
                    ]
                    if relevant_receive_times:
                        min_receive_time = min(relevant_receive_times)

                if min_receive_time is not None:
                    # Calculate when this move *must* have started
                    # Note: This is an approximation, the actual start depends on last_close/last_arrive
                    earliest_possible_start_of_this_move = timestamp - current_move_speed
                    # If the move started *before* the receive that justifies it, it's an error
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
            # Can open immediately after arriving or after closing (if already open)
            can_open_after = max(elevator.last_arrive_time, elevator.last_close_time)
            # Add tiny epsilon for safety if timestamp is exactly the same as arrival/close
            if timestamp < can_open_after - EPSILON :
                 self.add_error(timestamp, f"OPEN-{floor_str}-{eid}: Cannot open before arrival/close completed (Last relevant action at {can_open_after:.4f}).")

            # SCHE constraint: Cannot open during SCHE movement except at target floor
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

            # Time since open check: Use SCHE_DOOR_STOP_TIME if SCHE ended at this floor, else default
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
            passenger = self.get_passenger(pid, timestamp)
            if passenger is None: return
            elevator = self.elevators[eid]
            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            current_floor_int = FLOOR_MAP[floor_str]

            if not elevator.door_open: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Cannot enter, doors closed.")
            if elevator.current_floor_int != current_floor_int: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Elevator not at this floor. Currently at {elevator.get_current_floor_str()}.")
            if passenger.location == eid: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger already inside this elevator.")
            elif isinstance(passenger.location, int): self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger inside another elevator ({passenger.location}).")
            # Check if passenger is waiting at the correct floor (their location should be the floor string)
            elif passenger.location != floor_str:
                 # Allow IN if they just arrived via OUT-F/OUT-S, but verify floor match.
                 # The critical check is whether they were *supposed* to be at this floor.
                 # Check if the *current* floor matches the passenger's *start* floor IF they haven't been picked up yet.
                 is_first_pickup = passenger.received_by == eid # Check if receive is active for *this* elevator
                 if is_first_pickup and passenger.start_floor_int != current_floor_int:
                      self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger's start floor ({INT_TO_FLOOR_MAP.get(passenger.start_floor_int)}) does not match current floor ({floor_str}).")
                 # If not first pickup (e.g., after OUT-F), their location should match the floor string.
                 # This case (`passenger.location != floor_str`) implies they are not at the correct floor to enter.
                 elif not is_first_pickup:
                     self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger location ({passenger.location}) does not match elevator floor ({floor_str}).")

            if len(elevator.passengers) >= elevator.capacity: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Elevator full (Capacity: {elevator.capacity}).")
            # Check if received by *this* elevator specifically
            if passenger.received_by != eid: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger was not actively RECEIVE'd by this elevator {eid}. Currently received by: {passenger.received_by}")
            # Cannot enter during active SCHE movement phase
            if elevator.sche_active: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Cannot enter elevator during active SCHE (between SCHE-BEGIN and SCHE-END).")

            # Update state
            elevator.passengers.add(pid)
            passenger.location = eid # Location is now the elevator ID
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
            passenger = self.get_passenger(pid, timestamp)
            if passenger is None: return
            elevator = self.elevators[eid]
            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            current_floor_int = FLOOR_MAP[floor_str]

            if not elevator.door_open: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Cannot exit, doors closed.")
            if elevator.current_floor_int != current_floor_int: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Elevator not at this floor. Currently at {elevator.get_current_floor_str()}.")
            if passenger.location != eid: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Passenger not inside this elevator {eid}. Current location: {passenger.location}")
            # SCHE constraint: Cannot exit during SCHE except at target floor
            if elevator.sche_active and elevator.current_floor_int != elevator.sche_target_floor_int: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Cannot exit during SCHE except at the target floor {INT_TO_FLOOR_MAP.get(elevator.sche_target_floor_int)}")

            # Validate against input destination
            if success: # OUT-S
                if passenger.dest_floor_int != current_floor_int:
                     self.add_error(timestamp, f"OUT-S-{pid}-{floor_str}-{eid}: Exited successfully at {floor_str}, but input destination was {INT_TO_FLOOR_MAP.get(passenger.dest_floor_int, 'Unknown')}")
                else: # Correct destination
                     if passenger.completion_time is None: passenger.completion_time = timestamp
                     passenger.is_request_active = False # Mark as completed
            else: # OUT-F
                if passenger.dest_floor_int == current_floor_int: self.add_error(timestamp, f"OUT-F-{pid}-{floor_str}-{eid}: Exited with failure (OUT-F), but current floor {floor_str} matches input destination.")
                 # Passenger remains active, request is not fulfilled yet
                passenger.start_floor_int = current_floor_int # New start floor is the current floor
                passenger.is_request_active = True # 


            # --- Update State ---
            if pid in elevator.passengers: elevator.passengers.remove(pid)
            else: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Passenger {pid} was not in elevator {eid}'s set, inconsistency.")
            passenger.location = floor_str # Passenger is now on the floor (string representation)
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
            passenger = self.get_passenger(pid, timestamp)
            if passenger is None: return

            # Cannot RECEIVE passenger already inside *any* elevator
            if isinstance(passenger.location, int): self.add_error(timestamp, f"RECEIVE-{pid}-{eid}: Cannot RECEIVE passenger already inside elevator {passenger.location}.")
            # Check if passenger is already exclusively received by another elevator
            if pid in self.global_active_receives and self.global_active_receives[pid] != eid: self.add_error(timestamp, f"RECEIVE-{pid}-{eid}: Passenger {pid} already actively received by elevator {self.global_active_receives[pid]}.")
            # Cannot issue RECEIVE if the elevator is currently in active SCHE mode
            if elevator.sche_active: self.add_error(timestamp, f"RECEIVE-{pid}-{eid}: Cannot output RECEIVE for elevator {eid} during its active SCHE.")

            # Update State
            passenger.received_by = eid
            elevator.active_receives[pid] = timestamp # Store PID and timestamp for this elevator
            self.global_active_receives[pid] = eid # Update global tracking

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
            target_floor_int = FLOOR_MAP[floor_str] # Accepted target floor

            # --- MODIFIED: Find the next unprocessed SCHE request from input ---
            pending_input_requests = self.input_schedule_requests.get(eid, [])
            if not pending_input_requests:
                self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Elevator {eid} received SCHE-ACCEPT, but no corresponding SCHE requests found or remaining in input.")
                return

            # Assume requests are processed in order; take the first one
            current_input_request = pending_input_requests[0]
            req_time = current_input_request['time']
            expected_speed = current_input_request['speed']
            expected_target_floor = current_input_request['target']
            expected_floor_str = current_input_request['floor_str'] # For error messages

            # --- NEW: Check time gap since last SCHE ended ---
            if req_time < elevator.last_sche_end_time + SCHE_REQUEST_MIN_GAP - EPSILON:
                self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Input SCHE request time {req_time:.4f} is less than {SCHE_REQUEST_MIN_GAP}s after previous SCHE ended at {elevator.last_sche_end_time:.4f}.")
                # Continue validation below, but this is an error.

            # --- Validate accepted parameters against the input request ---
            if speed != expected_speed: self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Accepted speed {speed} does not match input SCHE request speed {expected_speed} (from input line at {req_time:.4f}).")
            if target_floor_int != expected_target_floor: self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Accepted target floor {floor_str} ({target_floor_int}) does not match input SCHE request target {expected_floor_str} ({expected_target_floor}) (from input line at {req_time:.4f}).")

            # Store details needed for SCHE-BEGIN, including the input request details
            self.pending_sche[eid] = (timestamp, target_floor_int, speed, 0, current_input_request)
            elevator.sche_accept_time = timestamp # Record accept time for T_complete check later

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

            # Unpack including the input request details
            accept_time, target_floor_int, temp_speed, arrive_count, input_request_details = self.pending_sche[eid]

            if elevator.door_open: self.add_error(timestamp, f"SCHE-BEGIN-{eid}: Cannot begin SCHE with doors open.")
            if arrive_count > 2: self.add_error(timestamp, f"SCHE-BEGIN-{eid}: Began after {arrive_count} ARRIVEs since SCHE-ACCEPT (Max 2 allowed).")

            # Activate SCHE state in the elevator
            elevator.sche_active = True
            elevator.sche_target_floor_int = target_floor_int
            elevator.sche_temp_speed = temp_speed
            elevator.move_speed = temp_speed # Set elevator speed to temp SCHE speed
            elevator.sche_begin_time = timestamp
            # NEW: Store which input request this SCHE corresponds to
            elevator.sche_input_details = input_request_details

            # Cancel relevant RECEIVEs (passengers waiting outside this elevator)
            pids_to_cancel_receive = list(elevator.active_receives.keys())
            for pid in pids_to_cancel_receive:
                 passenger = self.passengers.get(pid)
                 # Only cancel if passenger exists and is OUTSIDE this elevator
                 if passenger and passenger.location != eid:
                     if passenger.received_by == eid: passenger.received_by = None
                     if pid in self.global_active_receives and self.global_active_receives[pid] == eid:
                         del self.global_active_receives[pid]
                     # Remove from this elevator's active_receives dict
                     del elevator.active_receives[pid]
                 elif not passenger:
                     self.add_error(timestamp, f"SCHE-BEGIN-{eid}: Internal inconsistency - Passenger {pid} in active_receives but no state found.")
                     if pid in elevator.active_receives: del elevator.active_receives[pid] # Clean up defensively

            # Remove from pending state as SCHE is now active
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

            # Check T_complete (Time from ACCEPT to END)
            if elevator.sche_accept_time is None: self.add_error(timestamp, f"SCHE-END-{eid}: Cannot check T_complete, SCHE-ACCEPT time not recorded (internal error).")
            else:
                t_complete = timestamp - elevator.sche_accept_time
                if t_complete > SCHE_COMPLETE_TIME_LIMIT + EPSILON: self.add_error(timestamp, f"SCHE-END-{eid}: SCHE completion time T_complete ({t_complete:.4f}s) exceeds limit ({SCHE_COMPLETE_TIME_LIMIT}s). ACCEPT was at {elevator.sche_accept_time:.4f}")

            # --- Retrieve the details of the input request that was just completed ---
            completed_input_details = elevator.sche_input_details

            # --- Reset SCHE state in the elevator ---
            elevator.sche_active = False
            elevator.move_speed = DEFAULT_MOVE_SPEED # Restore default speed
            elevator.sche_target_floor_int = None
            elevator.sche_temp_speed = None
            elevator.sche_accept_time = None
            elevator.sche_begin_time = None
            elevator.sche_input_details = None # Clear the stored input details
            elevator.last_action_time = timestamp
            # --- NEW: Record the end time for the gap check ---
            elevator.last_sche_end_time = timestamp

            # --- MODIFIED: Remove the completed request from the input list ---
            if completed_input_details:
                request_list = self.input_schedule_requests.get(eid)
                if request_list:
                    try:
                        # Remove the specific dictionary instance
                        request_list.remove(completed_input_details)
                    except ValueError:
                        # This indicates an internal inconsistency
                        self.add_error(timestamp, f"SCHE-END-{eid}: Internal error - Could not find the completed SCHE request details in the input list to remove it.")
                else:
                     self.add_error(timestamp, f"SCHE-END-{eid}: Internal error - No input request list found for elevator {eid} while trying to remove completed request.")
            else:
                # This suggests SCHE-END occurred without SCHE-BEGIN properly storing details
                 self.add_error(timestamp, f"SCHE-END-{eid}: Internal error - No stored input request details found for the completed SCHE cycle.")


        except (ValueError, KeyError, IndexError) as e:
            self.add_error(timestamp, f"SCHE-END: Invalid argument or state error: {e} in '{'-'.join(args)}'")


    # --- Final Checks ---
    def perform_final_checks(self, final_timestamp):
        all_passengers_completed = True
        for pid, p_state in self.passengers.items():
            if p_state.is_request_active:
                 all_passengers_completed = False
                 self.add_error(final_timestamp, f"FINAL CHECK: Input passenger request {pid} (From: {INT_TO_FLOOR_MAP.get(p_state.start_floor_int, '?')}, To: {INT_TO_FLOOR_MAP.get(p_state.dest_floor_int, '?')}) was not completed successfully.")
            elif p_state.completion_time is None:
                 # This case should only happen if is_request_active is False but OUT-S was missed/invalid
                 self.add_error(final_timestamp, f"FINAL CHECK: Passenger {pid} marked inactive, but completion time not recorded (likely internal error or missed/invalid OUT-S).")

        for eid, e_state in self.elevators.items():
            if e_state.door_open: self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid}'s doors are open.")
            if e_state.passengers: self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid} still contains passengers: {e_state.passengers}")
            if e_state.sche_active: self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid} is still in SCHE mode (missing SCHE-END).")
            # MODIFIED: Check if any input SCHE requests remain unprocessed
            remaining_sche_requests = self.input_schedule_requests.get(eid, [])
            if remaining_sche_requests:
                 # Format remaining requests for clarity
                 remaining_details = [f"(Time: {req['time']}, Speed: {req['speed']}, Target: {req['floor_str']})" for req in remaining_sche_requests]
                 self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid} has unprocessed input SCHE requests: {', '.join(remaining_details)}")

        return all_passengers_completed


    # --- Utility ---
    def parse_line(self, line):
        # Keep this function as is, it correctly parses actions including SCHE sub-actions
        match = re.match(r"\[\s*(\d+\.\d+)\s*\](.*)", line)
        if not match: return None, None, None
        timestamp_str, data = match.groups()
        timestamp = Decimal(timestamp_str)
        parts = data.strip().split('-')
        if not parts: return timestamp, "INVALID_FORMAT", []
        action = parts[0]
        args = parts[1:]
        if action == "OUT" and len(parts) >= 2 and parts[1] in ('S', 'F'):
            action = f"OUT-{parts[1]}"
            args = parts[2:]
        elif action == "SCHE" and len(parts) >= 2:
            sub_action = parts[1]
            # Explicitly list valid sub-actions
            if sub_action in ("ACCEPT", "BEGIN", "END"):
                action = f"SCHE-{sub_action}"
                args = parts[2:]
            else:
                 action = "INVALID_SCHE_SUBACTION" # Mark invalid SCHE sub-action
        # Explicitly list known valid top-level actions
        elif action not in ("ARRIVE", "OPEN", "CLOSE", "IN", "RECEIVE"):
             action = "UNKNOWN_ACTION" # Mark other unknown actions

        return timestamp, action, args

    # --- Performance Calculation ---
    def calculate_performance(self):
        # This function remains the same
        t_final = self.last_timestamp
        energy_w = (self.open_count * W_OPEN) + (self.close_count * W_CLOSE) + (self.arrive_count * W_ARRIVE)
        total_weighted_time = Decimal(0)
        total_weight = Decimal(0)
        for pid, p_state in self.passengers.items():
            if p_state.completion_time is not None and p_state.request_time is not None:
                t_i = p_state.completion_time - p_state.request_time
                if t_i < 0: t_i = Decimal(0) # Should not happen with timestamp checks
                w_i = Decimal(p_state.priority)
                total_weighted_time += t_i * w_i
                total_weight += w_i

        weighted_time_wt = Decimal("NaN")
        if total_weight > 0:
            weighted_time_wt = total_weighted_time / total_weight

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
        # 1. Parse Input (uses the modified parse_input_lines)
        self.parse_input_lines(input_lines)
        if any("[INPUT ERROR]" in err for err in self.errors):
            return json.dumps({"result": "Fail", "errors": self.errors}, indent=2)

        # 2. Process Output lines
        for i, line in enumerate(output_lines):
            line = line.strip()
            if not line: continue

            timestamp, action, args = self.parse_line(line)

            if timestamp is None:
                self.add_error(Decimal("0.0"), f"Line {i+1}: Malformed output line format: {line}")
                continue
            if action in ("INVALID_FORMAT", "UNKNOWN_ACTION", "INVALID_SCHE_SUBACTION"):
                self.add_error(timestamp, f"Line {i+1}: Invalid action '{action}' or format in output: {line}")
                continue

            # Timestamp check remains the same
            if timestamp < self.last_timestamp - EPSILON:
                 self.add_error(timestamp, f"Timestamp non-decreasing violation. Current: {timestamp:.4f}, Previous: {self.last_timestamp:.4f}")
            self.last_timestamp = max(self.last_timestamp, timestamp) # Use max for safety

            # Dynamically call the correct handler
            try:
                # Construct handler method name (e.g., "handle_sche_accept")
                handler_name = f"handle_{action.replace('-', '_').lower()}"
                handler = getattr(self, handler_name, None)
                if handler:
                    handler(timestamp, args)
                else:
                    # This should now be caught by parse_line returning UNKNOWN_ACTION etc.
                    self.add_error(timestamp, f"Internal Error: No handler found for action '{action}' identified by parse_line.")
            except Exception as e:
                 # Catch unexpected errors during handler execution
                 self.add_error(timestamp, f"Internal checker error processing action '{action}' with args {args} on line {i+1}: {e}\nLine content: {line}")
                 import traceback
                 self.errors.append(f"Traceback: {traceback.format_exc()}")

        # --- Final Correctness Checks (uses modified perform_final_checks) ---
        all_requests_done = self.perform_final_checks(self.last_timestamp)

        # --- Result ---
        if not self.errors:
            # Only calculate performance if all passenger requests were completed
            if not all_requests_done:
                 # Final checks should have added specific errors. Add a summary error if needed.
                 if not any("FINAL CHECK: Input passenger request" in err for err in self.errors):
                     self.add_error(self.last_timestamp, "Final Check Summary: Not all passenger requests were completed successfully, performance metrics omitted.")
                 return json.dumps({"result": "Fail", "errors": self.errors}, indent=2)

            # If successful and no errors, calculate performance
            performance_metrics = self.calculate_performance()
            return json.dumps({
                "result": "Success",
                "performance": performance_metrics
            }, indent=2)
        else:
            # If any errors occurred (input, output processing, or final checks)
            return json.dumps({"result": "Fail", "errors": self.errors}, indent=2)


# --- Main Execution ---
if __name__ == "__main__":
    # Keep the main execution block as is
    if len(sys.argv) != 3:
        print("Usage: python checker.py <input_file> <output_file>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]
    input_lines = []
    output_lines = []

    try:
        with open(input_file, 'r', encoding='utf-8') as f: input_lines = f.readlines()
    except FileNotFoundError: print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Input file not found: {input_file}"]}, indent=2)); sys.exit(1)
    except Exception as e: print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Error reading input file: {e}"]}, indent=2)); sys.exit(1)

    try:
        with open(output_file, 'r', encoding='utf-8') as f: output_lines = f.readlines()
    except FileNotFoundError: print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Output file not found: {output_file}"]}, indent=2)); sys.exit(1)
    except Exception as e: print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Error reading output file: {e}"]}, indent=2)); sys.exit(1)


    checker = ElevatorChecker()
    result_json = checker.check(input_lines, output_lines)
    print(result_json)