# -*- coding: utf-8 -*-
import re
import json
import sys
import argparse # Added for command-line arguments
from decimal import Decimal, getcontext, ROUND_HALF_UP

# Set Decimal precision
getcontext().prec = 10 # Adjust precision as needed for calculations

# --- Constants ---
# CORRECTED Floor Mapping based on hw6.md (B4-B1, F1-F7 = 11 floors)
PASSENGER_MIN = 1
PASSENGER_MAX = 200 # HW7 mutual test limit is 70 total instructions, but input check uses original range
FLOOR_MAP = {
    "B4": -3, "B3": -2, "B2": -1, "B1": 0,
    "F1": 1, "F2": 2, "F3": 3, "F4": 4, "F5": 5, "F6": 6, "F7": 7
}
INT_TO_FLOOR_MAP = {v: k for k, v in FLOOR_MAP.items()}
ALL_FLOORS_INT = set(FLOOR_MAP.values()) # HW7: Used for initial allowed floors
NUM_ELEVATORS = 6
DEFAULT_CAPACITY = 6
DEFAULT_MOVE_SPEED = Decimal("0.4")
DOUBLE_CAR_SPEED = Decimal("0.2") # HW7 New Constant
DOOR_OPEN_CLOSE_TIME = Decimal("0.4")
SCHE_DOOR_STOP_TIME = Decimal("1.0")
SCHE_COMPLETE_TIME_LIMIT = Decimal("6.0")
UPDATE_COMPLETE_TIME_LIMIT = Decimal("6.0") # HW7 New Constant
UPDATE_RESET_TIME = Decimal("1.0") # HW7 New Constant
# HW7 MODIFIED Time Gaps based on user request and hw7.md clarification
INTER_SPECIAL_REQUEST_GAP = Decimal("8.0") # Min gap between a SCHE input and an UPDATE input *for the same elevator*
SAME_ELEVATOR_SCHE_GAP = Decimal("6.0") # Min gap between two SCHE inputs *for the same elevator*
VALID_SCHE_SPEEDS = {Decimal("0.2"), Decimal("0.3"), Decimal("0.4"), Decimal("0.5")}
VALID_SCHE_TARGET_FLOORS_STR = {"B2", "B1", "F1", "F2", "F3", "F4", "F5"}
VALID_UPDATE_TARGET_FLOORS_STR = {"B2", "B1", "F1", "F2", "F3", "F4", "F5"} # HW7 New Constant
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
        self.last_sche_end_time = Decimal("-inf")
        self.sche_input_details = None

        # RECEIVE state
        self.active_receives = {} # pid -> receive_timestamp

        # --- HW7 UPDATE State ---
        self.is_disabled = False # If true, this elevator (original A) no longer exists functionally
        self.in_pending_update = False # True between UPDATE-ACCEPT and UPDATE-BEGIN/END
        self.in_active_update = False # True between UPDATE-BEGIN and UPDATE-END
        self.update_partner_id = None # ID of the other elevator in the UPDATE
        self.update_role = None # 'A' or 'B' during the UPDATE process coordination
        self.update_accept_time = None
        self.update_begin_time = None
        self.last_update_end_time = Decimal("-inf")
        self.update_input_details = None # Store the dict of the currently processed input UPDATE request

        # --- HW7 Double-Car State ---
        self.is_double_car = False # True if this elevator is part of a double-car system post-UPDATE
        self.double_car_partner_id = None # ID of the other car in the same shaft
        self.double_car_role = None # 'A' (upper) or 'B' (lower) in the double-car pair
        self.double_car_transfer_floor = None # The target floor from the UPDATE command
        self.allowed_floors = ALL_FLOORS_INT.copy() # Initially all floors are allowed
        # Flag to allow first move away from T+/-1 INITIAL position without RECEIVE
        self.just_updated = False


    def get_current_floor_str(self):
        return INT_TO_FLOOR_MAP.get(self.current_floor_int, "Invalid")

# --- Checker Logic ---
class ElevatorChecker:
    # Added tmax parameter
    def __init__(self, tmax):
        self.tmax = tmax # Store the maximum allowed timestamp
        self.errors = []
        self.last_timestamp = Decimal("-1.0")
        self.elevators = {i: ElevatorState(i) for i in range(1, NUM_ELEVATORS + 1)}
        self.passengers = {} # pid -> PassengerState
        self.input_passenger_requests = {} # pid -> details_dict
        self.input_schedule_requests = {} # eid -> list of details_dicts
        self.input_update_requests = {} # b_eid -> list of details_dicts (key is B's ID)

        # Global track of active receives {pid: elevator_id} - used ONLY for exclusivity check
        self.global_active_receives = {}

        # Track SCHE-ACCEPT details before SCHE-BEGIN
        self.pending_sche = {} # eid -> (accept_time, target_floor_int, temp_speed, arrive_count, input_request_details)

        # HW7 Track UPDATE-ACCEPT details before UPDATE-BEGIN
        # Key is tuple (a_eid, b_eid)
        self.pending_update = {} # (a_eid, b_eid) -> (accept_time, target_floor_int, a_arrive_count, b_arrive_count, input_details)

        # HW7 Track last special operation input times *per elevator* for gap checks
        # Stores the timestamp of the *input line* for that elevator's last special op
        self.last_sche_input_time_per_elevator = {} # eid -> timestamp
        self.last_update_input_time_per_elevator = {} # eid -> timestamp

        # Performance Counters
        self.arrive_count = 0
        self.open_count = 0
        self.close_count = 0

    def add_error(self, timestamp, message, is_input_error=False):
        prefix = "[INPUT ERROR]" if is_input_error else f"[{float(timestamp):.4f}]"
        self.errors.append(f"{prefix} {message}")

    def parse_input_lines(self, input_lines):
        last_input_time = Decimal("-1.0")
        passenger_ids = set()
        update_participation = {} # eid -> count (Check at the end)

        for i, line in enumerate(input_lines):
            line = line.strip()
            if not line: continue

            match_req = re.match(r"\[\s*(\d+\.\d+)\s*\](\d+)-PRI-(\d+)-FROM-([BF]\d+)-TO-([BF]\d+)", line)
            match_sche = re.match(r"\[\s*(\d+\.\d+)\s*\]SCHE-(\d+)-([\d\.]+)-([BF]\d+)", line)
            match_update = re.match(r"\[\s*(\d+\.\d+)\s*\]UPDATE-(\d+)-(\d+)-([BF]\d+)", line) # HW7 New Regex

            current_input_timestamp_str = "N/A" # For error reporting if timestamp fails parse

            try:
                if match_req:
                    t_str, pid_str, pri_str, from_str, to_str = match_req.groups()
                    current_input_timestamp_str = t_str
                    timestamp = Decimal(t_str)
                    pid = int(pid_str)
                    priority = int(pri_str)
                    if from_str not in FLOOR_MAP or to_str not in FLOOR_MAP: raise KeyError(f"Invalid floor name '{from_str}' or '{to_str}'")
                    from_floor_int = FLOOR_MAP[from_str]
                    to_floor_int = FLOOR_MAP[to_str]

                    if timestamp < last_input_time - EPSILON: self.add_error(timestamp, f"Line {i+1}: Input timestamp non-decreasing violation (prev={last_input_time:.4f}, curr={timestamp:.4f}).", is_input_error=True)
                    last_input_time = max(last_input_time, timestamp) # Track max timestamp seen
                    if pid <= 0: self.add_error(timestamp, f"Line {i+1}: Invalid Passenger ID {pid}. Must be positive.", is_input_error=True)
                    if pid in passenger_ids: self.add_error(timestamp, f"Line {i+1}: Duplicate Passenger ID {pid} in input.", is_input_error=True)
                    passenger_ids.add(pid)
                    if not (1 <= priority <= 100): self.add_error(timestamp, f"Line {i+1}: Invalid Priority {priority} for PID {pid}. Must be 1-100.", is_input_error=True)
                    if from_floor_int == to_floor_int: self.add_error(timestamp, f"Line {i+1}: Start and destination floors are the same ({from_str}) for PID {pid}.", is_input_error=True)

                    details = {'time': timestamp, 'priority': priority, 'from': from_floor_int, 'to': to_floor_int}
                    self.input_passenger_requests[pid] = details
                    self.passengers[pid] = PassengerState(pid, timestamp, from_floor_int, to_floor_int, priority)

                elif match_sche:
                    t_str, eid_str, speed_str, floor_str = match_sche.groups()
                    current_input_timestamp_str = t_str
                    timestamp = Decimal(t_str)
                    eid = int(eid_str)
                    speed = Decimal(speed_str)
                    if floor_str not in FLOOR_MAP: raise KeyError(f"Invalid floor name '{floor_str}'")
                    target_floor_int = FLOOR_MAP[floor_str]

                    if timestamp < last_input_time - EPSILON: self.add_error(timestamp, f"Line {i+1}: Input timestamp non-decreasing violation (prev={last_input_time:.4f}, curr={timestamp:.4f}).", is_input_error=True)
                    last_input_time = max(last_input_time, timestamp) # Track max timestamp seen
                    if not (1 <= eid <= NUM_ELEVATORS): self.add_error(timestamp, f"Line {i+1}: Invalid Elevator ID {eid}. Must be 1-{NUM_ELEVATORS}.", is_input_error=True)
                    if speed not in VALID_SCHE_SPEEDS: self.add_error(timestamp, f"Line {i+1}: Invalid SCHE speed {speed} for EID {eid}. Valid: {VALID_SCHE_SPEEDS}.", is_input_error=True)
                    if floor_str not in VALID_SCHE_TARGET_FLOORS_STR:
                        self.add_error(timestamp, f"Line {i+1}: Invalid SCHE target floor {floor_str} for EID {eid}. Valid: {VALID_SCHE_TARGET_FLOORS_STR}", is_input_error=True)

                    # --- HW7 Modified Time Gap Check for SCHE ---
                    # 1. Check against last SCHE for *this specific elevator*
                    last_sche_for_this_eid = self.last_sche_input_time_per_elevator.get(eid, Decimal("-inf"))
                    if timestamp < last_sche_for_this_eid + SAME_ELEVATOR_SCHE_GAP - EPSILON:
                         self.add_error(timestamp, f"Line {i+1}: Input SCHE request for EID {eid} at {timestamp:.4f} is less than {SAME_ELEVATOR_SCHE_GAP}s after the previous SCHE input for the *same elevator* at {last_sche_for_this_eid:.4f}.", is_input_error=True)
                    # 2. Check against last UPDATE involving *this specific elevator*
                    last_update_for_this_eid = self.last_update_input_time_per_elevator.get(eid, Decimal("-inf"))
                    if timestamp < last_update_for_this_eid + INTER_SPECIAL_REQUEST_GAP - EPSILON:
                         self.add_error(timestamp, f"Line {i+1}: Input SCHE request for EID {eid} at {timestamp:.4f} is less than {INTER_SPECIAL_REQUEST_GAP}s after the last UPDATE input involving the *same elevator* at {last_update_for_this_eid:.4f}.", is_input_error=True)

                    # Update last SCHE time *for this elevator*
                    self.last_sche_input_time_per_elevator[eid] = timestamp

                    # Check participation (Elevator cannot be scheduled if already part of an update)
                    # Note: This check relies on update_participation being built incrementally *before* this line.
                    if eid in update_participation and update_participation[eid] > 0:
                         self.add_error(timestamp, f"Line {i+1}: Input Error: Elevator {eid} cannot receive a SCHE request because it is involved in an UPDATE request elsewhere in the input.", is_input_error=True)


                    details = {'time': timestamp, 'eid': eid, 'speed': speed, 'target': target_floor_int, 'floor_str': floor_str}
                    self.input_schedule_requests.setdefault(eid, []).append(details)
                    self.input_schedule_requests[eid].sort(key=lambda x: x['time'])


                elif match_update: # HW7 Handle UPDATE input
                    t_str, a_eid_str, b_eid_str, floor_str = match_update.groups()
                    current_input_timestamp_str = t_str
                    timestamp = Decimal(t_str)
                    a_eid = int(a_eid_str)
                    b_eid = int(b_eid_str)
                    if floor_str not in FLOOR_MAP: raise KeyError(f"Invalid floor name '{floor_str}'")
                    target_floor_int = FLOOR_MAP[floor_str]

                    if timestamp < last_input_time - EPSILON: self.add_error(timestamp, f"Line {i+1}: Input timestamp non-decreasing violation (prev={last_input_time:.4f}, curr={timestamp:.4f}).", is_input_error=True)
                    last_input_time = max(last_input_time, timestamp) # Track max timestamp seen
                    if not (1 <= a_eid <= NUM_ELEVATORS): self.add_error(timestamp, f"Line {i+1}: Invalid Elevator A ID {a_eid} in UPDATE. Must be 1-{NUM_ELEVATORS}.", is_input_error=True)
                    if not (1 <= b_eid <= NUM_ELEVATORS): self.add_error(timestamp, f"Line {i+1}: Invalid Elevator B ID {b_eid} in UPDATE. Must be 1-{NUM_ELEVATORS}.", is_input_error=True)
                    if a_eid == b_eid: self.add_error(timestamp, f"Line {i+1}: Elevator IDs A and B must be different in UPDATE request ({a_eid}).", is_input_error=True)
                    if floor_str not in VALID_UPDATE_TARGET_FLOORS_STR:
                        self.add_error(timestamp, f"Line {i+1}: Invalid UPDATE target floor {floor_str}. Valid: {VALID_UPDATE_TARGET_FLOORS_STR}", is_input_error=True)

                    # --- HW7 Modified Time Gap Check for UPDATE ---
                    # Check *each* involved elevator against its *own* last SCHE and UPDATE
                    for eid_check, role in [(a_eid, 'A'), (b_eid, 'B')]:
                        # 1. Check against last SCHE for *this specific elevator*
                        last_sche_for_this_eid = self.last_sche_input_time_per_elevator.get(eid_check, Decimal("-inf"))
                        if timestamp < last_sche_for_this_eid + INTER_SPECIAL_REQUEST_GAP - EPSILON:
                             self.add_error(timestamp, f"Line {i+1}: Input UPDATE request ({role}={eid_check}) at {timestamp:.4f} is less than {INTER_SPECIAL_REQUEST_GAP}s after the last SCHE input involving the *same elevator* at {last_sche_for_this_eid:.4f}.", is_input_error=True)
                        # 2. Check against last UPDATE involving *this specific elevator*
                        last_update_for_this_eid = self.last_update_input_time_per_elevator.get(eid_check, Decimal("-inf"))
                        if timestamp < last_update_for_this_eid + INTER_SPECIAL_REQUEST_GAP - EPSILON:
                             # Note: The update_participation check done later is the primary guard against multiple UPDATEs for the same elevator.
                             # This time check acts as a secondary guard for the 8s interval if an invalid input attempts it.
                             self.add_error(timestamp, f"Line {i+1}: Input UPDATE request ({role}={eid_check}) at {timestamp:.4f} is less than {INTER_SPECIAL_REQUEST_GAP}s after the previous UPDATE input involving the *same elevator* at {last_update_for_this_eid:.4f}.", is_input_error=True)

                        # Check participation (Elevator cannot be updated if already scheduled/updated)
                        # Note: This check relies on previous entries in `update_participation` and `last_sche_input_time_per_elevator`.
                        if eid_check in update_participation and update_participation[eid_check] > 0:
                             self.add_error(timestamp, f"Line {i+1}: Input Error: Elevator {eid_check} ({role}) cannot participate in this UPDATE because it is involved in another UPDATE request elsewhere in the input.", is_input_error=True)
                        if eid_check in self.last_sche_input_time_per_elevator and timestamp < self.last_sche_input_time_per_elevator[eid_check] + INTER_SPECIAL_REQUEST_GAP - EPSILON:
                             # This duplicates the check above, but confirms the logic flow
                             pass # Error already added by time gap check

                    # Update last UPDATE time *for both elevators*
                    self.last_update_input_time_per_elevator[a_eid] = timestamp
                    self.last_update_input_time_per_elevator[b_eid] = timestamp

                    # Increment participation count *after* checks for *this* line
                    for eid_upd in [a_eid, b_eid]:
                         update_participation[eid_upd] = update_participation.get(eid_upd, 0) + 1

                    details = {'time': timestamp, 'a_eid': a_eid, 'b_eid': b_eid, 'target': target_floor_int, 'floor_str': floor_str}
                    # Store under B's ID, as shaft B persists
                    self.input_update_requests.setdefault(b_eid, []).append(details)
                    self.input_update_requests[b_eid].sort(key=lambda x: x['time'])

                else:
                    if line: self.add_error(Decimal("0"), f"Line {i+1}: Unrecognized input format: {line}", is_input_error=True)

            except (ValueError, KeyError, IndexError) as e:
                # Use the timestamp string captured at the start of the block
                ts_dec_for_error = Decimal(current_input_timestamp_str) if current_input_timestamp_str != "N/A" else Decimal("0.0")
                self.add_error(ts_dec_for_error, f"Line {i+1}: Malformed input line or value error: {line} -> {e}", is_input_error=True)
            except Exception as e: # Catch potential Decimal conversion errors too
                ts_dec_for_error = Decimal("0.0")
                try: # Try to get timestamp from line again for error context
                    match_time = re.match(r"\[\s*(\d+\.\d+)\s*\]", line)
                    if match_time: ts_dec_for_error = Decimal(match_time.group(1))
                except: pass # Ignore secondary errors
                self.add_error(ts_dec_for_error, f"Line {i+1}: Unexpected error parsing line: {line} -> {type(e).__name__}: {e}", is_input_error=True)


        num_pass_req = len(self.input_passenger_requests)
        # HW7: Total number of *instructions* (pass + sche + update) <= 70 for mututal test, not checked here
        # Check original passenger range, allow 0 if special requests exist
        if not (PASSENGER_MIN <= num_pass_req <= PASSENGER_MAX):
             if num_pass_req == 0 and (self.input_schedule_requests or self.input_update_requests):
                 pass # Allow 0 passengers if there are special requests
             else:
                self.add_error(Decimal("0"), f"Input Error: Number of passenger requests ({num_pass_req}) is not within the valid range [{PASSENGER_MIN}, {PASSENGER_MAX}] (unless special requests exist).", is_input_error=True)

        # Input Check: Ensure an elevator isn't involved in multiple UPDATEs (final check after parsing all lines)
        for eid, count in update_participation.items():
             if count > 1:
                 self.add_error(Decimal("0"), f"Input Error: Elevator {eid} is involved in more than one UPDATE request ({count} times) in the input.", is_input_error=True)

    def get_elevator(self, eid, timestamp, operation_tag="Operation"):
        if not (1 <= eid <= NUM_ELEVATORS):
            self.add_error(timestamp, f"{operation_tag}: Invalid Elevator ID {eid}.")
            return None
        elevator = self.elevators[eid]
        # Allow access even if disabled for UPDATE-END handling, check disabled status within handlers where needed.
        return elevator

    def get_passenger(self, pid, timestamp):
        if pid not in self.passengers:
            self.add_error(timestamp, f"Reference to unknown passenger ID {pid} (not found in input).")
            return None
        return self.passengers[pid]

    # --- Action Handlers ---
    # ... (handle_arrive, handle_open, handle_close, handle_in, _handle_out, handle_out_s, handle_out_f, handle_receive) ...
    # These handlers remain largely the same, their internal logic depends on the state set by input parsing and other actions.
    # The core changes were in input validation (`parse_input_lines`).
    # Double-check no handler implicitly relies on the old global gap logic. They seem okay.

    def handle_arrive(self, timestamp, args):
        if len(args) != 2: return self.add_error(timestamp, f"ARRIVE: Invalid arguments {args}")
        floor_str, eid_str = args
        try:
            eid = int(eid_str)
            elevator = self.get_elevator(eid, timestamp, f"ARRIVE-{floor_str}-{eid}")
            if elevator is None: return
            # Check disabled status here, as disabled elevators cannot ARRIVE
            if elevator.is_disabled:
                self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Elevator {eid} is disabled.")
                return

            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            target_floor_int = FLOOR_MAP[floor_str] # This is the destination floor of THIS arrive event

            # --- State Checks ---
            if elevator.door_open: self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Cannot move with doors open.")
            if elevator.in_active_update: self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Cannot move during active UPDATE (between UPDATE-BEGIN and UPDATE-END).")

            # --- HW7: Double-Car Range Check ---
            if elevator.is_double_car and target_floor_int not in elevator.allowed_floors:
                 role = elevator.double_car_role
                 allowed_range_str = f"{INT_TO_FLOOR_MAP.get(min(elevator.allowed_floors))} to {INT_TO_FLOOR_MAP.get(max(elevator.allowed_floors))}"
                 self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Double-Car ({role}) moved outside allowed range ({allowed_range_str}). Target: {floor_str}")

            # --- Move Distance and Direction ---
            departure_floor_int = elevator.current_floor_int # Floor BEFORE this ARRIVE
            floor_diff_abs = abs(target_floor_int - departure_floor_int)
            if floor_diff_abs != 1:
                 self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Invalid move distance. From {elevator.get_current_floor_str()} ({departure_floor_int}) to {floor_str} ({target_floor_int}). Must be 1 floor apart numerically.")

            # --- Move Duration Check ---
            current_move_speed = elevator.move_speed # Handles default, SCHE, and double-car speed
            expected_move_time = current_move_speed
            start_time_for_duration_check = max(elevator.last_close_time, elevator.last_arrive_time) # Start time is end of last close OR end of last arrive (if just moved)
            # Exception: If just updated, the "last close" might be from before the update. Use last_update_end_time.
            if elevator.just_updated and elevator.last_update_end_time > start_time_for_duration_check :
                start_time_for_duration_check = elevator.last_update_end_time

            time_since_start = timestamp - start_time_for_duration_check
            if time_since_start < expected_move_time - EPSILON:
                 self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Move too fast. Speed: {current_move_speed:.1f}s/f. Expected >= {expected_move_time:.4f}, Actual: {time_since_start:.4f} (Since start at {start_time_for_duration_check:.4f})")

            # --- HW7: Double-Car Collision Check ---
            if elevator.is_double_car:
                partner_eid = elevator.double_car_partner_id
                partner = self.elevators.get(partner_eid)
                if partner and not partner.is_disabled: # Partner should exist and not be disabled
                     partner_floor_int = partner.current_floor_int
                     # Check 1: Cannot arrive at the same floor partner currently occupies
                     if target_floor_int == partner_floor_int:
                         self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Double-Car Collision! Arriving at same floor ({floor_str}) as partner {partner_eid}.")
                     # Check 2: A must always be >= B's floor. Check based on who is arriving.
                     if elevator.double_car_role == 'A': # A is arriving at target_floor_int
                         if target_floor_int < partner_floor_int:
                             self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Double-Car Collision! Elevator A ({eid} at {floor_str}) arrived below partner B ({partner_eid} at {INT_TO_FLOOR_MAP.get(partner_floor_int)}).")
                     elif elevator.double_car_role == 'B': # B is arriving at target_floor_int
                         # Partner A is partner_floor_int
                         if partner_floor_int < target_floor_int:
                             self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Double-Car Collision! Partner A ({partner_eid} at {INT_TO_FLOOR_MAP.get(partner_floor_int)}) is below arriving elevator B ({eid} at {floor_str}).")
                elif partner and partner.is_disabled:
                     # If partner is disabled (original A), this elevator (B) can move freely within its range
                     pass # No collision check needed
                else:
                     # This should ideally not happen if UPDATE logic is correct
                     self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Internal Error! Double-Car partner {partner_eid} not found or partner state inconsistent.")


            # --- Illegal Move Justification Check ---
            is_justified_move = False
            justification_reason = []

            if elevator.sche_active:
                is_justified_move = True
                justification_reason.append("SCHE_ACTIVE")
            if elevator.passengers:
                is_justified_move = True
                justification_reason.append(f"PASSENGERS({len(elevator.passengers)})")
            if elevator.active_receives:
                 # Check if there are receives for passengers *outside* the elevator
                 if any(pid in self.passengers and self.passengers[pid].location != eid for pid in elevator.active_receives):
                     is_justified_move = True
                     justification_reason.append(f"ACTIVE_RECEIVES({len(elevator.active_receives)})")

            was_just_updated_flag = False # Track if we use this flag
            if not is_justified_move and elevator.is_double_car and elevator.just_updated:
                expected_initial_floor = None
                transfer_floor = elevator.double_car_transfer_floor
                if elevator.double_car_role == 'A': expected_initial_floor = transfer_floor + 1
                elif elevator.double_car_role == 'B': expected_initial_floor = transfer_floor - 1

                if departure_floor_int == expected_initial_floor:
                    was_just_updated_flag = True # Note that the flag was set and used
                    is_justified_move = True
                    justification_reason.append(f"DC_INITIAL_MOVE(Role:{elevator.double_car_role}, From:{INT_TO_FLOOR_MAP.get(departure_floor_int)})")


            if not is_justified_move and elevator.is_double_car:
                if departure_floor_int == elevator.double_car_transfer_floor:
                    correct_direction_move = False
                    if elevator.double_car_role == 'A' and target_floor_int == departure_floor_int + 1: correct_direction_move = True
                    elif elevator.double_car_role == 'B' and target_floor_int == departure_floor_int - 1: correct_direction_move = True

                    if correct_direction_move and floor_diff_abs == 1:
                         is_justified_move = True
                         justification_reason.append(f"DC_MOVE_FROM_TF(Role:{elevator.double_car_role}, TF:{INT_TO_FLOOR_MAP.get(departure_floor_int)})")

            if not is_justified_move:
                 status_str = justification_reason if justification_reason else ["empty", "no receives", "not SCHE"]
                 if elevator.is_double_car:
                      role = elevator.double_car_role
                      tf_str = INT_TO_FLOOR_MAP.get(elevator.double_car_transfer_floor, "Inv")
                      status_str.append(f"DC(Role:{role}, TF:{tf_str}, JustUpdated:{elevator.just_updated})")
                 self.add_error(timestamp, f"ARRIVE-{floor_str}-{eid}: Illegal move. Elevator is not justified to move ({', '.join(status_str)}). From: {INT_TO_FLOOR_MAP.get(departure_floor_int, 'Inv')}, To: {floor_str}")


            # --- Update state ---
            elevator.current_floor_int = target_floor_int # Update current floor AFTER all checks
            elevator.last_action_time = timestamp
            elevator.last_arrive_time = timestamp
            self.arrive_count += 1

            if was_just_updated_flag:
                 elevator.just_updated = False

            # Track SCHE arrives (if pending)
            if eid in self.pending_sche:
                 accept_time, sche_target_floor, temp_speed, arrive_count, input_details = self.pending_sche[eid]
                 self.pending_sche[eid] = (accept_time, sche_target_floor, temp_speed, arrive_count + 1, input_details)

            # Track UPDATE arrives (if pending)
            update_key_found = None
            for key, val in self.pending_update.items():
                a_eid_pending, b_eid_pending = key
                if eid == a_eid_pending or eid == b_eid_pending:
                     update_key_found = key
                     break
            if update_key_found:
                 accept_time, target_floor, a_arr_count, b_arr_count, input_details = self.pending_update[update_key_found]
                 a_eid_pending, b_eid_pending = update_key_found
                 if eid == a_eid_pending: a_arr_count += 1
                 if eid == b_eid_pending: b_arr_count += 1
                 self.pending_update[update_key_found] = (accept_time, target_floor, a_arr_count, b_arr_count, input_details)


        except (ValueError, KeyError, IndexError) as e:
             self.add_error(timestamp, f"ARRIVE: Invalid argument or state error: {e} in '{floor_str}-{eid_str}'")

    def handle_open(self, timestamp, args):
        if len(args) != 2: return self.add_error(timestamp, f"OPEN: Invalid arguments {args}")
        floor_str, eid_str = args
        try:
            eid = int(eid_str)
            elevator = self.get_elevator(eid, timestamp, f"OPEN-{floor_str}-{eid}")
            if elevator is None: return
            if elevator.is_disabled: # Disabled cannot open
                self.add_error(timestamp, f"OPEN-{floor_str}-{eid}: Elevator {eid} is disabled.")
                return

            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            current_floor_int = FLOOR_MAP[floor_str]

            if elevator.current_floor_int != current_floor_int: self.add_error(timestamp, f"OPEN-{floor_str}-{eid}: Elevator not at this floor. Currently at {elevator.get_current_floor_str()}.")
            if elevator.door_open: self.add_error(timestamp, f"OPEN-{floor_str}-{eid}: Doors already open.")
            if elevator.in_active_update: self.add_error(timestamp, f"OPEN-{floor_str}-{eid}: Cannot open doors during active UPDATE (between UPDATE-BEGIN and UPDATE-END).")

            can_open_after = max(elevator.last_arrive_time, elevator.last_close_time)
            if elevator.just_updated and elevator.last_update_end_time > can_open_after:
                 can_open_after = elevator.last_update_end_time

            if timestamp < can_open_after - EPSILON :
                 self.add_error(timestamp, f"OPEN-{floor_str}-{eid}: Cannot open before arrival/close/update completed (Last relevant action at {can_open_after:.4f}).")

            if elevator.sche_active and elevator.current_floor_int != elevator.sche_target_floor_int:
                 self.add_error(timestamp, f"OPEN-{floor_str}-{eid}: Cannot open doors during SCHE movement before reaching target {INT_TO_FLOOR_MAP.get(elevator.sche_target_floor_int)}.")

            if elevator.is_double_car and current_floor_int not in elevator.allowed_floors:
                 role = elevator.double_car_role
                 allowed_range_str = f"{INT_TO_FLOOR_MAP.get(min(elevator.allowed_floors))} to {INT_TO_FLOOR_MAP.get(max(elevator.allowed_floors))}"
                 self.add_error(timestamp, f"OPEN-{floor_str}-{eid}: Double-Car ({role}) opened outside allowed range ({allowed_range_str}). Floor: {floor_str}")


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
            elevator = self.get_elevator(eid, timestamp, f"CLOSE-{floor_str}-{eid}")
            if elevator is None: return
            if elevator.is_disabled: # Disabled cannot close
                self.add_error(timestamp, f"CLOSE-{floor_str}-{eid}: Elevator {eid} is disabled.")
                return

            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            current_floor_int = FLOOR_MAP[floor_str]

            if elevator.current_floor_int != current_floor_int: self.add_error(timestamp, f"CLOSE-{floor_str}-{eid}: Elevator not at this floor. Currently at {elevator.get_current_floor_str()}.")
            if not elevator.door_open: self.add_error(timestamp, f"CLOSE-{floor_str}-{eid}: Doors already closed.")
            if elevator.in_active_update: self.add_error(timestamp, f"CLOSE-{floor_str}-{eid}: Cannot close doors during active UPDATE (between UPDATE-BEGIN and UPDATE-END).")


            is_sche_stop_condition = elevator.sche_active and elevator.current_floor_int == elevator.sche_target_floor_int
            required_open_time = SCHE_DOOR_STOP_TIME if is_sche_stop_condition else DOOR_OPEN_CLOSE_TIME
            time_since_open = timestamp - elevator.last_open_time
            if time_since_open < required_open_time - EPSILON:
                 self.add_error(timestamp, f"CLOSE-{floor_str}-{eid}: Doors closed too fast. Required >= {required_open_time:.4f}s, Actual: {time_since_open:.4f}s (Since OPEN at {elevator.last_open_time:.4f}) {'[SCHE Target Stop]' if is_sche_stop_condition else ''}")

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
            passenger = self.get_passenger(pid, timestamp)
            if passenger is None: return
            elevator = self.get_elevator(eid, timestamp, f"IN-{pid}-{floor_str}-{eid}")
            if elevator is None: return
            if elevator.is_disabled: # Disabled cannot have passengers IN
                self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Elevator {eid} is disabled.")
                return

            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            current_floor_int = FLOOR_MAP[floor_str]

            if not elevator.door_open: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Cannot enter, doors closed.")
            if elevator.current_floor_int != current_floor_int: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Elevator not at this floor. Currently at {elevator.get_current_floor_str()}.")
            if elevator.in_active_update: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Cannot enter during active UPDATE (between UPDATE-BEGIN and UPDATE-END).")
            if elevator.sche_active:
                self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Cannot enter elevator {eid} while it is under SCHE control (between SCHE-BEGIN and SCHE-END).")

            if passenger.location == eid: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger already inside this elevator.")
            elif isinstance(passenger.location, int): self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger inside another elevator ({passenger.location}).")
            elif passenger.location != floor_str:
                 logical_location_str = passenger.location
                 if logical_location_str != floor_str:
                     self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger's logical location ({logical_location_str}) does not match elevator floor ({floor_str}).")


            if len(elevator.passengers) >= elevator.capacity: self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Elevator full (Capacity: {elevator.capacity}).")

            if passenger.received_by != eid:
                 self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Passenger was not actively RECEIVE'd by this elevator {eid}. Passenger state received_by: {passenger.received_by}. Global state: {self.global_active_receives.get(pid)}")
            elif pid not in elevator.active_receives:
                 self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Elevator {eid} does not have an active RECEIVE record for passenger {pid}, although passenger state might indicate it.")


            if elevator.is_double_car and current_floor_int not in elevator.allowed_floors:
                 role = elevator.double_car_role
                 allowed_range_str = f"{INT_TO_FLOOR_MAP.get(min(elevator.allowed_floors))} to {INT_TO_FLOOR_MAP.get(max(elevator.allowed_floors))}"
                 self.add_error(timestamp, f"IN-{pid}-{floor_str}-{eid}: Double-Car ({role}) passenger entered outside allowed range ({allowed_range_str}). Floor: {floor_str}")


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
            passenger = self.get_passenger(pid, timestamp)
            if passenger is None: return
            elevator = self.get_elevator(eid, timestamp, f"{out_type}-{pid}-{floor_str}-{eid}")
            if elevator is None: return
            if elevator.is_disabled:
                self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Elevator {eid} is disabled.")
                return

            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            current_floor_int = FLOOR_MAP[floor_str]

            if not elevator.door_open: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Cannot exit, doors closed.")
            if elevator.current_floor_int != current_floor_int: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Elevator not at this floor. Currently at {elevator.get_current_floor_str()}.")
            if elevator.in_active_update: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Cannot exit during active UPDATE (between UPDATE-BEGIN and UPDATE-END).")
            if passenger.location != eid: self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Passenger not inside this elevator {eid}. Current location: {passenger.location}")

            if elevator.sche_active and elevator.current_floor_int != elevator.sche_target_floor_int:
                 self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Cannot exit during SCHE movement before reaching target {INT_TO_FLOOR_MAP.get(elevator.sche_target_floor_int)}")

            if elevator.is_double_car and current_floor_int not in elevator.allowed_floors:
                 role = elevator.double_car_role
                 allowed_range_str = f"{INT_TO_FLOOR_MAP.get(min(elevator.allowed_floors))} to {INT_TO_FLOOR_MAP.get(max(elevator.allowed_floors))}"
                 self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Double-Car ({role}) passenger exited outside allowed range ({allowed_range_str}). Floor: {floor_str}")


            if success: # OUT-S
                if passenger.dest_floor_int != current_floor_int:
                     self.add_error(timestamp, f"OUT-S-{pid}-{floor_str}-{eid}: Exited successfully at {floor_str}, but input destination was {INT_TO_FLOOR_MAP.get(passenger.dest_floor_int, 'Unknown')}")
                if passenger.completion_time is None: passenger.completion_time = timestamp
                passenger.is_request_active = False
            else: # OUT-F
                if passenger.dest_floor_int == current_floor_int:
                     self.add_error(timestamp, f"OUT-F-{pid}-{floor_str}-{eid}: Exited with failure (OUT-F), but current floor {floor_str} matches input destination.")
                passenger.start_floor_int = current_floor_int
                passenger.location = floor_str
                passenger.is_request_active = True

            if pid in elevator.passengers:
                elevator.passengers.remove(pid)
            else:
                self.add_error(timestamp, f"{out_type}-{pid}-{floor_str}-{eid}: Passenger {pid} was not in elevator {eid}'s set, inconsistency.")

            passenger.location = floor_str
            passenger.last_action_time = timestamp

            if passenger.received_by == eid:
                passenger.received_by = None
            if pid in elevator.active_receives:
                del elevator.active_receives[pid]
            if pid in self.global_active_receives and self.global_active_receives[pid] == eid:
                del self.global_active_receives[pid]


        except (ValueError, KeyError, IndexError) as e:
             self.add_error(timestamp, f"{out_type}: Invalid argument or state error: {e} in '{pid_str}-{floor_str}-{eid_str}'")


    def handle_receive(self, timestamp, args):
        if len(args) != 2: return self.add_error(timestamp, f"RECEIVE: Invalid arguments {args}")
        pid_str, eid_str = args
        try:
            pid = int(pid_str)
            eid = int(eid_str)
            passenger = self.get_passenger(pid, timestamp)
            if passenger is None: return
            elevator = self.get_elevator(eid, timestamp, f"RECEIVE-{pid}-{eid}")
            if elevator is None: return
            if elevator.is_disabled: # Disabled cannot RECEIVE
                self.add_error(timestamp, f"RECEIVE-{pid}-{eid}: Elevator {eid} is disabled.")
                return

            if isinstance(passenger.location, int):
                self.add_error(timestamp, f"RECEIVE-{pid}-{eid}: Cannot RECEIVE passenger {pid} already inside elevator {passenger.location}.")
                return

            if pid in self.global_active_receives and self.global_active_receives[pid] != eid:
                self.add_error(timestamp, f"RECEIVE-{pid}-{eid}: Passenger {pid} already actively received by elevator {self.global_active_receives[pid]}.")
                return

            if elevator.sche_active:
                self.add_error(timestamp, f"RECEIVE-{pid}-{eid}: Cannot output RECEIVE for elevator {eid} during its active SCHE (SCHE-BEGIN to SCHE-END).")
                return
            if elevator.in_active_update:
                self.add_error(timestamp, f"RECEIVE-{pid}-{eid}: Cannot output RECEIVE for elevator {eid} during its active UPDATE (UPDATE-BEGIN to UPDATE-END).")
                return

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
            elevator = self.get_elevator(eid, timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}")
            if elevator is None: return
            if elevator.is_disabled:
                self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Elevator {eid} is disabled.")
                return

            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            target_floor_int = FLOOR_MAP[floor_str]

            # HW7 Constraint: Cannot SCHE if involved in UPDATE or is a double-car
            if elevator.is_double_car or elevator.in_pending_update or elevator.in_active_update:
                 self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Elevator {eid} cannot accept SCHE as it is involved in/result of an UPDATE.")
                 return
            if elevator.sche_active or eid in self.pending_sche:
                 self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Elevator {eid} is already involved in a SCHE process.")
                 return

            # Find corresponding *unprocessed* input request (check processed_accept_time flag)
            pending_input_requests = [req for req in self.input_schedule_requests.get(eid, []) if req.get('processed_accept_time') is None]
            if not pending_input_requests:
                self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Elevator {eid} received SCHE-ACCEPT, but no corresponding unprocessed SCHE requests found in input.")
                return

            current_input_request = pending_input_requests[0]
            req_time = current_input_request['time']
            expected_speed = current_input_request['speed']
            expected_target_floor = current_input_request['target']
            expected_floor_str = current_input_request['floor_str']

            if speed != expected_speed: self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Accepted speed {speed} does not match input SCHE request speed {expected_speed} (from input line at {req_time:.4f}).")
            if target_floor_int != expected_target_floor: self.add_error(timestamp, f"SCHE-ACCEPT-{eid}-{speed_str}-{floor_str}: Accepted target floor {floor_str} ({target_floor_int}) does not match input SCHE request target {expected_floor_str} ({expected_target_floor}) (from input line at {req_time:.4f}).")

            self.pending_sche[eid] = (timestamp, target_floor_int, speed, 0, current_input_request)
            elevator.sche_accept_time = timestamp
            current_input_request['processed_accept_time'] = timestamp # Mark input as processed

        except (ValueError, KeyError, IndexError) as e:
            self.add_error(timestamp, f"SCHE-ACCEPT: Invalid argument or state error: {e} in '{'-'.join(args)}'")

    def handle_sche_begin(self, timestamp, args):
        if len(args) != 1: return self.add_error(timestamp, f"SCHE-BEGIN: Invalid arguments {args}")
        eid_str = args[0]
        try:
            eid = int(eid_str)
            elevator = self.get_elevator(eid, timestamp, f"SCHE-BEGIN-{eid}")
            if elevator is None: return
            if elevator.is_disabled:
                 self.add_error(timestamp, f"SCHE-BEGIN-{eid}: Elevator {eid} is disabled.") ; return

            if eid not in self.pending_sche:
                 self.add_error(timestamp, f"SCHE-BEGIN-{eid}: SCHE-ACCEPT was not received or already processed for the current SCHE cycle.") ; return

            accept_time, target_floor_int, temp_speed, arrive_count, input_request_details = self.pending_sche[eid]

            if elevator.door_open: self.add_error(timestamp, f"SCHE-BEGIN-{eid}: Cannot begin SCHE with doors open.")
            if arrive_count > 2: self.add_error(timestamp, f"SCHE-BEGIN-{eid}: Began after {arrive_count} ARRIVEs since SCHE-ACCEPT (Max 2 allowed).")

            elevator.sche_active = True
            elevator.sche_target_floor_int = target_floor_int
            elevator.sche_temp_speed = temp_speed
            elevator.move_speed = temp_speed
            elevator.sche_begin_time = timestamp
            elevator.sche_input_details = input_request_details

            # Cancel EXTERNAL receives
            pids_to_cancel_receive = list(elevator.active_receives.keys())
            for pid in pids_to_cancel_receive:
                 passenger = self.passengers.get(pid)
                 if passenger and passenger.location != eid: # Only cancel if OUTSIDE
                     if passenger.received_by == eid: passenger.received_by = None
                     if pid in self.global_active_receives and self.global_active_receives[pid] == eid:
                         del self.global_active_receives[pid]
                     del elevator.active_receives[pid]
                 elif not passenger:
                     self.add_error(timestamp, f"SCHE-BEGIN-{eid}: Internal inconsistency - Passenger {pid} in active_receives but no state found.")
                     if pid in elevator.active_receives: del elevator.active_receives[pid] # Clean up


            del self.pending_sche[eid]

        except (ValueError, KeyError, IndexError) as e:
             self.add_error(timestamp, f"SCHE-BEGIN: Invalid argument or state error: {e} in '{'-'.join(args)}'")


    def handle_sche_end(self, timestamp, args):
        if len(args) != 1: return self.add_error(timestamp, f"SCHE-END: Invalid arguments {args}")
        eid_str = args[0]
        try:
            eid = int(eid_str)
            elevator = self.get_elevator(eid, timestamp, f"SCHE-END-{eid}")
            if elevator is None: return
            if elevator.is_disabled:
                 self.add_error(timestamp, f"SCHE-END-{eid}: Elevator {eid} is disabled.") ; return

            if not elevator.sche_active: self.add_error(timestamp, f"SCHE-END-{eid}: Elevator was not in an active SCHE state.") ; return
            if elevator.door_open: self.add_error(timestamp, f"SCHE-END-{eid}: Doors must be closed before ending SCHE (Output CLOSE first).")
            if elevator.passengers: self.add_error(timestamp, f"SCHE-END-{eid}: Elevator must be empty to end SCHE. Contains: {elevator.passengers}")
            if elevator.current_floor_int != elevator.sche_target_floor_int: self.add_error(timestamp, f"SCHE-END-{eid}: Elevator ended SCHE but is not at target floor {INT_TO_FLOOR_MAP.get(elevator.sche_target_floor_int)}. Current: {elevator.get_current_floor_str()}")

            if elevator.current_floor_int == elevator.sche_target_floor_int:
                 if elevator.last_open_time >= elevator.sche_begin_time and elevator.last_open_time > elevator.last_close_time:
                      required_close_time = elevator.last_open_time + SCHE_DOOR_STOP_TIME
                      if elevator.last_close_time < required_close_time - EPSILON:
                           self.add_error(timestamp, f"SCHE-END-{eid}: The CLOSE action at the target floor (at {elevator.last_close_time:.4f}) occurred before the required {SCHE_DOOR_STOP_TIME}s stop time after opening at {elevator.last_open_time:.4f} (Required close time >= {required_close_time:.4f}).")
                      if timestamp < elevator.last_close_time - EPSILON:
                          self.add_error(timestamp, f"SCHE-END-{eid}: Cannot end SCHE before CLOSE finishes at target floor. SCHE-END at {timestamp:.4f}, last CLOSE at {elevator.last_close_time:.4f}.")
                 elif timestamp < elevator.last_close_time - EPSILON:
                      self.add_error(timestamp, f"SCHE-END-{eid}: Cannot end SCHE before last CLOSE action finishes. SCHE-END at {timestamp:.4f}, last CLOSE at {elevator.last_close_time:.4f}.")

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
                 completed_input_details['processed_end_time'] = timestamp
            else:
                 self.add_error(timestamp, f"SCHE-END-{eid}: Internal error - No stored input request details found for the completed SCHE cycle.")


        except (ValueError, KeyError, IndexError) as e:
            self.add_error(timestamp, f"SCHE-END: Invalid argument or state error: {e} in '{'-'.join(args)}'")

    # --- HW7 UPDATE Handlers ---

    def handle_update_accept(self, timestamp, args):
        if len(args) != 3: return self.add_error(timestamp, f"UPDATE-ACCEPT: Invalid arguments {args}")
        a_eid_str, b_eid_str, floor_str = args
        try:
            a_eid = int(a_eid_str)
            b_eid = int(b_eid_str)
            tag = f"UPDATE-ACCEPT-{a_eid}-{b_eid}-{floor_str}"
            ele_a = self.get_elevator(a_eid, timestamp, tag)
            ele_b = self.get_elevator(b_eid, timestamp, tag)
            if ele_a is None or ele_b is None: return
            if a_eid == b_eid: raise ValueError("A and B elevator IDs must be different")

            if floor_str not in FLOOR_MAP: raise KeyError("Invalid Floor")
            target_floor_int = FLOOR_MAP[floor_str]

            # Find corresponding unprocessed input request (keyed by B's id, matching A's id, check flag)
            pending_input_requests = [
                req for req in self.input_update_requests.get(b_eid, [])
                if req.get('processed_accept_time') is None and req['a_eid'] == a_eid
            ]
            if not pending_input_requests:
                self.add_error(timestamp, f"{tag}: Received UPDATE-ACCEPT, but no corresponding unprocessed UPDATE request found in input for pair A={a_eid}, B={b_eid}.")
                return

            current_input_request = pending_input_requests[0]
            req_time = current_input_request['time']
            expected_target_floor = current_input_request['target']
            expected_floor_str = current_input_request['floor_str']

            if target_floor_int != expected_target_floor:
                self.add_error(timestamp, f"{tag}: Accepted target floor {floor_str} ({target_floor_int}) does not match input request target {expected_floor_str} ({expected_target_floor}) (from input line at {req_time:.4f}).")

            errors_found = False
            for eid_check, ele_check in [(a_eid, ele_a), (b_eid, ele_b)]:
                 if ele_check.is_disabled:
                     self.add_error(timestamp, f"{tag}: Elevator {eid_check} is disabled, cannot participate in UPDATE.") ; errors_found = True
                 if ele_check.is_double_car:
                     self.add_error(timestamp, f"{tag}: Elevator {eid_check} is already a double-car, cannot participate in UPDATE.") ; errors_found = True
                 if ele_check.in_pending_update or ele_check.in_active_update:
                     self.add_error(timestamp, f"{tag}: Elevator {eid_check} is already involved in another UPDATE process.") ; errors_found = True
                 if ele_check.sche_active or eid_check in self.pending_sche:
                     self.add_error(timestamp, f"{tag}: Elevator {eid_check} is involved in a SCHE process, cannot participate in UPDATE.") ; errors_found = True
            if errors_found: return

            update_key = (a_eid, b_eid)
            if update_key in self.pending_update:
                 self.add_error(timestamp, f"{tag}: Duplicate UPDATE-ACCEPT for pair ({a_eid}, {b_eid}) before UPDATE-BEGIN/END.") ; return

            self.pending_update[update_key] = (timestamp, target_floor_int, 0, 0, current_input_request)

            ele_a.in_pending_update = True
            ele_a.update_accept_time = timestamp
            ele_a.update_input_details = current_input_request
            ele_a.update_role = 'A'
            ele_a.update_partner_id = b_eid
            ele_b.in_pending_update = True
            ele_b.update_accept_time = timestamp
            ele_b.update_input_details = current_input_request
            ele_b.update_role = 'B'
            ele_b.update_partner_id = a_eid

            current_input_request['processed_accept_time'] = timestamp

        except (ValueError, KeyError, IndexError) as e:
            self.add_error(timestamp, f"UPDATE-ACCEPT: Invalid argument or state error: {e} in '{'-'.join(args)}'")


    def handle_update_begin(self, timestamp, args):
         if len(args) != 2: return self.add_error(timestamp, f"UPDATE-BEGIN: Invalid arguments {args}")
         a_eid_str, b_eid_str = args
         try:
             a_eid = int(a_eid_str)
             b_eid = int(b_eid_str)
             tag = f"UPDATE-BEGIN-{a_eid}-{b_eid}"
             ele_a = self.get_elevator(a_eid, timestamp, tag)
             ele_b = self.get_elevator(b_eid, timestamp, tag)
             if ele_a is None or ele_b is None: return
             if ele_a.is_disabled or ele_b.is_disabled:
                 self.add_error(timestamp, f"{tag}: One or both elevators ({a_eid if ele_a.is_disabled else ''}{' and ' if ele_a.is_disabled and ele_b.is_disabled else ''}{b_eid if ele_b.is_disabled else ''}) are disabled.") ; return
             if a_eid == b_eid: raise ValueError("A and B elevator IDs must be different")

             update_key = (a_eid, b_eid)
             if update_key not in self.pending_update:
                 self.add_error(timestamp, f"{tag}: UPDATE-ACCEPT was not received or already processed for this pair ({a_eid}, {b_eid}).") ; return

             accept_time, target_floor_int, a_arrive_count, b_arrive_count, input_details = self.pending_update[update_key]

             if a_arrive_count > 2: self.add_error(timestamp, f"{tag}: Elevator A ({a_eid}) made {a_arrive_count} ARRIVEs since UPDATE-ACCEPT (Max 2 allowed).")
             if b_arrive_count > 2: self.add_error(timestamp, f"{tag}: Elevator B ({b_eid}) made {b_arrive_count} ARRIVEs since UPDATE-ACCEPT (Max 2 allowed).")

             errors_found = False
             for eid_check, ele_check in [(a_eid, ele_a), (b_eid, ele_b)]:
                 if ele_check.door_open:
                     self.add_error(timestamp, f"{tag}: Elevator {eid_check} doors must be closed to begin UPDATE.") ; errors_found = True
                 if ele_check.passengers:
                     self.add_error(timestamp, f"{tag}: Elevator {eid_check} must be empty to begin UPDATE. Contains: {ele_check.passengers}") ; errors_found = True
             if errors_found: return

             ele_a.in_pending_update = False
             ele_a.in_active_update = True
             ele_a.update_begin_time = timestamp
             ele_b.in_pending_update = False
             ele_b.in_active_update = True
             ele_b.update_begin_time = timestamp

             # Cancel EXTERNAL receives
             for eid_cancel, ele_cancel in [(a_eid, ele_a), (b_eid, ele_b)]:
                 pids_to_cancel = list(ele_cancel.active_receives.keys())
                 for pid in pids_to_cancel:
                     passenger = self.passengers.get(pid)
                     if passenger and passenger.location != eid_cancel: # Only cancel if OUTSIDE
                          if passenger.received_by == eid_cancel: passenger.received_by = None
                          if pid in self.global_active_receives and self.global_active_receives[pid] == eid_cancel:
                              del self.global_active_receives[pid]
                          del ele_cancel.active_receives[pid]
                     elif passenger and passenger.location == eid_cancel:
                         self.add_error(timestamp, f"{tag}: Internal inconsistency - Elevator {eid_cancel} has passenger {pid} inside but should be empty for UPDATE-BEGIN.")
                         if pid in ele_cancel.active_receives: del ele_cancel.active_receives[pid]
                     elif not passenger:
                          self.add_error(timestamp, f"{tag}: Potential internal inconsistency - Passenger {pid} in active_receives for {eid_cancel} but no state found.")
                          if pid in ele_cancel.active_receives: del ele_cancel.active_receives[pid]


             del self.pending_update[update_key]

         except (ValueError, KeyError, IndexError) as e:
             self.add_error(timestamp, f"UPDATE-BEGIN: Invalid argument or state error: {e} in '{'-'.join(args)}'")

    def handle_update_end(self, timestamp, args):
        if len(args) != 2: return self.add_error(timestamp, f"UPDATE-END: Invalid arguments {args}")
        a_eid_str, b_eid_str = args
        try:
            a_eid = int(a_eid_str)
            b_eid = int(b_eid_str)
            tag = f"UPDATE-END-{a_eid}-{b_eid}"
            if not (1 <= a_eid <= NUM_ELEVATORS): raise ValueError(f"Invalid Elevator A ID {a_eid}")
            if not (1 <= b_eid <= NUM_ELEVATORS): raise ValueError(f"Invalid Elevator B ID {b_eid}")
            ele_a = self.elevators[a_eid]
            ele_b = self.elevators[b_eid]
            if a_eid == b_eid: raise ValueError("A and B elevator IDs must be different")

            a_was_active = ele_a.in_active_update and ele_a.update_partner_id == b_eid
            b_was_active = ele_b.in_active_update and ele_b.update_partner_id == a_eid

            if not a_was_active:
                 self.add_error(timestamp, f"{tag}: Elevator A ({a_eid}) was not in the expected active UPDATE state with partner B ({b_eid}). Current state: active={ele_a.in_active_update}, partner={ele_a.update_partner_id}")
            if not b_was_active:
                 self.add_error(timestamp, f"{tag}: Elevator B ({b_eid}) was not in the expected active UPDATE state with partner A ({a_eid}). Current state: active={ele_b.in_active_update}, partner={ele_b.update_partner_id}")

            if not a_was_active and not b_was_active:
                 self.add_error(timestamp, f"{tag}: Neither elevator A ({a_eid}) nor B ({b_eid}) were in an active UPDATE state together.")
                 return

            update_begin_time = Decimal("-inf")
            if a_was_active and ele_a.update_begin_time is not None: update_begin_time = max(update_begin_time, ele_a.update_begin_time)
            if b_was_active and ele_b.update_begin_time is not None: update_begin_time = max(update_begin_time, ele_b.update_begin_time)

            if update_begin_time == Decimal("-inf"):
                 self.add_error(timestamp, f"{tag}: Internal error - UPDATE-BEGIN time not recorded for active elevator(s).")
            else:
                time_since_begin = timestamp - update_begin_time
                if time_since_begin < UPDATE_RESET_TIME - EPSILON:
                     self.add_error(timestamp, f"{tag}: UPDATE completed too fast. Required >= {UPDATE_RESET_TIME:.4f}s, Actual: {time_since_begin:.4f}s (Since BEGIN at {update_begin_time:.4f})")

            update_accept_time = None
            completed_input_details = None
            # Retrieve details consistently, prefer B's if both were active (as UPDATE is keyed by B)
            if b_was_active and ele_b.update_input_details is not None:
                completed_input_details = ele_b.update_input_details
                update_accept_time = ele_b.update_accept_time
            elif a_was_active and ele_a.update_input_details is not None:
                completed_input_details = ele_a.update_input_details
                update_accept_time = ele_a.update_accept_time

            if update_accept_time is None:
                 self.add_error(timestamp, f"{tag}: Internal error - UPDATE-ACCEPT time not recorded for active elevator(s).")
            elif completed_input_details is None:
                 self.add_error(timestamp, f"{tag}: Internal error - Stored input UPDATE details not found for T_complete check.")
            else:
                t_complete = timestamp - update_accept_time
                if t_complete > UPDATE_COMPLETE_TIME_LIMIT + EPSILON:
                    self.add_error(timestamp, f"{tag}: UPDATE completion time T_complete ({t_complete:.4f}s) exceeds limit ({UPDATE_COMPLETE_TIME_LIMIT}s). ACCEPT was at {update_accept_time:.4f}")

            target_floor_int = completed_input_details.get('target') if completed_input_details else None
            if target_floor_int is None:
                 self.add_error(timestamp, f"{tag}: Internal error or preceding error prevented getting target floor. Cannot complete state transition.")
                 # Reset flags anyway? Best effort cleanup.
                 ele_a.in_active_update = False; ele_a.in_pending_update = False; ele_a.update_partner_id = None; ele_a.update_role = None; ele_a.update_input_details = None; ele_a.update_accept_time = None; ele_a.update_begin_time = None
                 ele_b.in_active_update = False; ele_b.in_pending_update = False; ele_b.update_partner_id = None; ele_b.update_role = None; ele_b.update_input_details = None; ele_b.update_accept_time = None; ele_b.update_begin_time = None
                 return


            # --- Transition to Double-Car State ---
            # 1. Disable original A elevator shaft
            ele_a_original_state = ele_a
            ele_a_original_state.is_disabled = True
            ele_a_original_state.passengers.clear()
            ele_a_original_state.active_receives.clear()
            ele_a_original_state.is_double_car = False
            ele_a_original_state.double_car_partner_id = None
            ele_a_original_state.double_car_role = None
            pids_to_clear_global = [pid for pid, rec_eid in self.global_active_receives.items() if rec_eid == a_eid]
            for pid in pids_to_clear_global:
                 del self.global_active_receives[pid]
                 if pid in self.passengers: self.passengers[pid].received_by = None


            # 2. Configure NEW 'A' car (Upper car in Shaft B, uses object with ID a_eid)
            ele_a_new = ele_a
            ele_a_new.is_disabled = False
            ele_a_new.is_double_car = True
            ele_a_new.double_car_partner_id = b_eid
            ele_a_new.double_car_role = 'A'
            ele_a_new.double_car_transfer_floor = target_floor_int
            ele_a_new.allowed_floors = {f for f in ALL_FLOORS_INT if f >= target_floor_int}
            ele_a_new.move_speed = DOUBLE_CAR_SPEED
            ele_a_new.capacity = DEFAULT_CAPACITY
            ele_a_new.current_floor_int = target_floor_int + 1
            ele_a_new.just_updated = True
            ele_a_new.door_open = False
            ele_a_new.last_action_time = timestamp
            ele_a_new.last_update_end_time = timestamp
            # Reset other state flags
            ele_a_new.last_arrive_time = Decimal("-1.0"); ele_a_new.last_open_time = Decimal("-1.0"); ele_a_new.last_close_time = timestamp;
            ele_a_new.passengers.clear()
            ele_a_new.active_receives.clear()
            ele_a_new.sche_active = False; ele_a_new.sche_target_floor_int = None; ele_a_new.sche_temp_speed = None; ele_a_new.sche_accept_time = None; ele_a_new.sche_begin_time = None; ele_a_new.last_sche_end_time = Decimal("-inf"); ele_a_new.sche_input_details = None
            ele_a_new.in_active_update = False; ele_a_new.in_pending_update = False; ele_a_new.update_begin_time = None; ele_a_new.update_accept_time = None; ele_a_new.update_input_details = None; ele_a_new.update_role = None; ele_a_new.update_partner_id = None


            # 3. Configure 'B' elevator (Lower car in Shaft B)
            ele_b.is_double_car = True
            ele_b.double_car_partner_id = a_eid
            ele_b.double_car_role = 'B'
            ele_b.double_car_transfer_floor = target_floor_int
            ele_b.allowed_floors = {f for f in ALL_FLOORS_INT if f <= target_floor_int}
            ele_b.move_speed = DOUBLE_CAR_SPEED
            ele_b.capacity = DEFAULT_CAPACITY
            ele_b.current_floor_int = target_floor_int - 1
            ele_b.just_updated = True
            ele_b.door_open = False
            ele_b.last_action_time = timestamp
            ele_b.last_update_end_time = timestamp
            # Reset other state flags
            ele_b.last_arrive_time = Decimal("-1.0"); ele_b.last_open_time = Decimal("-1.0"); ele_b.last_close_time = timestamp;
            ele_b.passengers.clear()
            ele_b.active_receives.clear()
            ele_b.sche_active = False; ele_b.sche_target_floor_int = None; ele_b.sche_temp_speed = None; ele_b.sche_accept_time = None; ele_b.sche_begin_time = None; ele_b.last_sche_end_time = Decimal("-inf"); ele_b.sche_input_details = None
            ele_b.in_active_update = False; ele_b.in_pending_update = False; ele_b.update_begin_time = None; ele_b.update_accept_time = None; ele_b.update_input_details = None; ele_b.update_role = None; ele_b.update_partner_id = None

            # Mark input request as fully processed
            if completed_input_details:
                 completed_input_details['processed_end_time'] = timestamp
            else:
                 pass # Error already logged


        except (ValueError, KeyError, IndexError) as e:
            self.add_error(timestamp, f"UPDATE-END: Invalid argument or state error: {e} in '{'-'.join(args)}'")

    # --- Final Checks ---
    def perform_final_checks(self, final_timestamp):
        # NOTE: The check for final_timestamp > self.tmax is now done *after* calling this method.
        # This method focuses only on simulation state validity.
        all_passengers_completed = True
        for pid, p_state in self.passengers.items():
            if p_state.is_request_active:
                 all_passengers_completed = False
                 start_floor_str = INT_TO_FLOOR_MAP.get(p_state.start_floor_int, '?')
                 dest_floor_str = INT_TO_FLOOR_MAP.get(p_state.dest_floor_int, '?')
                 location_str = f"Elevator {p_state.location}" if isinstance(p_state.location, int) else p_state.location
                 self.add_error(final_timestamp, f"FINAL CHECK: Input passenger request {pid} (From: {start_floor_str}, To: {dest_floor_str}, Priority: {p_state.priority}) was not completed successfully (OUT-S). Final location: {location_str}")
            elif p_state.completion_time is None and p_state.request_time is not None: # Check completion time only if it was an input request
                 pass # Ignore missing completion time if request is marked inactive.

        active_elevator_ids = set()
        all_elevators_valid_state = True
        double_car_pairs_checked = set() # To avoid double-checking pairs

        for eid, e_state in self.elevators.items():
            elevator_failed_check = False
            # --- Checks for Disabled Elevators ---
            if e_state.is_disabled:
                if e_state.passengers:
                     self.add_error(final_timestamp, f"FINAL CHECK: Disabled Elevator {eid} still contains passengers: {e_state.passengers}"); elevator_failed_check = True
                if e_state.active_receives:
                     self.add_error(final_timestamp, f"FINAL CHECK: Disabled Elevator {eid} still has active receives: {e_state.active_receives}"); elevator_failed_check = True
                if e_state.door_open:
                     self.add_error(final_timestamp, f"FINAL CHECK: Disabled Elevator {eid}'s doors are open."); elevator_failed_check = True
                if e_state.sche_active or e_state.in_pending_update or e_state.in_active_update:
                     self.add_error(final_timestamp, f"FINAL CHECK: Disabled Elevator {eid} is stuck in SCHE/UPDATE state."); elevator_failed_check = True
                if e_state.is_double_car: # A disabled elevator cannot be part of an active double car pair
                    self.add_error(final_timestamp, f"FINAL CHECK: Internal Inconsistency - Disabled Elevator {eid} is marked as double_car."); elevator_failed_check = True

                if elevator_failed_check: all_elevators_valid_state = False
                continue # Skip active checks for disabled elevators

            # --- Checks for Active Elevators ---
            active_elevator_ids.add(eid)
            if e_state.door_open:
                 self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid}'s doors are open."); elevator_failed_check = True
            if e_state.passengers:
                 self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid} still contains passengers: {e_state.passengers}"); elevator_failed_check = True
            if e_state.sche_active:
                 self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid} is still in SCHE mode (missing SCHE-END)."); elevator_failed_check = True
            if e_state.in_pending_update:
                 self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid} is stuck in pending UPDATE state (missing UPDATE-BEGIN/END)."); elevator_failed_check = True
            if e_state.in_active_update:
                 self.add_error(final_timestamp, f"FINAL CHECK: Elevator {eid} is stuck in active UPDATE state (missing UPDATE-END)."); elevator_failed_check = True

            # --- Check double-car consistency (only if not already checked via partner) ---
            if e_state.is_double_car and eid not in double_car_pairs_checked:
                 partner_id = e_state.double_car_partner_id
                 partner_state = None
                 partner_role = 'A' if e_state.double_car_role == 'B' else 'B' # Expected partner role

                 if partner_id is None or partner_id not in self.elevators:
                      self.add_error(final_timestamp, f"FINAL CHECK: Double-Car Elevator {eid} (Role: {e_state.double_car_role}) has invalid partner ID {partner_id}.") ; elevator_failed_check = True
                 else:
                      partner_state = self.elevators[partner_id]
                      if partner_state.is_disabled:
                           self.add_error(final_timestamp, f"FINAL CHECK: Double-Car Elevator {eid} (Role: {e_state.double_car_role}) has a disabled partner ({partner_id}).") ; elevator_failed_check = True
                      elif not partner_state.is_double_car or partner_state.double_car_partner_id != eid or partner_state.double_car_role != partner_role:
                           self.add_error(final_timestamp, f"FINAL CHECK: Double-Car inconsistency between Elevator {eid} (Role: {e_state.double_car_role}) and partner {partner_id} (IsDC:{partner_state.is_double_car}, Partner:{partner_state.double_car_partner_id}, Role:{partner_state.double_car_role}).") ; elevator_failed_check = True
                      else:
                           upper_car = e_state if e_state.double_car_role == 'A' else partner_state
                           lower_car = e_state if e_state.double_car_role == 'B' else partner_state
                           if upper_car.current_floor_int < lower_car.current_floor_int:
                               self.add_error(final_timestamp, f"FINAL CHECK: Double-Car position violation. Upper Car {upper_car.id} ({upper_car.get_current_floor_str()}) is below Lower Car {lower_car.id} ({lower_car.get_current_floor_str()}).") ; elevator_failed_check = True

                      double_car_pairs_checked.add(eid)
                      double_car_pairs_checked.add(partner_id)


            if elevator_failed_check: all_elevators_valid_state = False


        # --- Check for unprocessed input requests ---
        unprocessed_sche_count = 0
        for eid, requests in self.input_schedule_requests.items():
             for req in requests:
                 # Check if SCHE-END was processed for this request
                 if req.get('processed_end_time') is None:
                     # Only flag if the elevator still exists and is *not* disabled.
                     # If it was disabled by an UPDATE, it's okay that its SCHE wasn't processed.
                     if eid in active_elevator_ids: # active_elevator_ids contains only non-disabled elevators
                          unprocessed_sche_count += 1
                          details = f"(EID: {req['eid']}, Time: {req['time']:.4f}, Speed: {req['speed']}, Target: {req['floor_str']})"
                          self.add_error(final_timestamp, f"FINAL CHECK: Unprocessed input SCHE request for active elevator: {details}")


        unprocessed_update_count = 0
        for b_eid, requests in self.input_update_requests.items():
             for req in requests:
                 # Check if UPDATE-END was processed for this request
                 if req.get('processed_end_time') is None:
                     unprocessed_update_count += 1
                     details = f"(A_EID: {req['a_eid']}, B_EID: {req['b_eid']}, Time: {req['time']:.4f}, Target: {req['floor_str']})"
                     self.add_error(final_timestamp, f"FINAL CHECK: Unprocessed input UPDATE request: {details}")

        # --- Check global receives point to active elevators ---
        for pid, eid in list(self.global_active_receives.items()):
             elevator_state = self.elevators.get(eid)
             if not elevator_state or elevator_state.is_disabled:
                 passenger = self.passengers.get(pid)
                 if passenger and passenger.is_request_active:
                    self.add_error(final_timestamp, f"FINAL CHECK: Passenger {pid} has global active receive for inactive/disabled elevator {eid}, but request is still active.")
                    all_elevators_valid_state = False
                 else:
                     # Clean up stale receive, don't fail check
                     del self.global_active_receives[pid]


        # Return a tuple indicating overall validity
        return (all_passengers_completed and
                unprocessed_sche_count == 0 and
                unprocessed_update_count == 0 and
                all_elevators_valid_state)


    # --- Utility ---
    def parse_line(self, line):
        match = re.match(r"\[\s*(\d+\.\d+)\s*\](.*)", line)
        if not match: return None, None, None
        timestamp_str, data = match.groups()
        timestamp = Decimal(timestamp_str)
        parts = data.strip().split('-')
        if not parts: return timestamp, "INVALID_FORMAT", []

        action = parts[0]
        args = parts[1:]

        # Handle multi-part actions first
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
        elif action == "UPDATE" and len(parts) >= 2:
            sub_action = parts[1]
            if sub_action in ("ACCEPT", "BEGIN", "END"):
                action = f"UPDATE-{sub_action}"
                args = parts[2:]
            else:
                 action = "INVALID_UPDATE_SUBACTION"
        # Keep base actions simple
        elif action not in ("ARRIVE", "OPEN", "CLOSE", "IN", "RECEIVE"):
             action = "UNKNOWN_ACTION"

        return timestamp, action, args

    # --- Performance Calculation ---
    def calculate_performance(self):
        t_final_calc = min(self.last_timestamp, self.tmax) if self.last_timestamp >= 0 else Decimal("0.0")

        energy_w = (self.open_count * W_OPEN) + (self.close_count * W_CLOSE) + (self.arrive_count * W_ARRIVE)
        total_weighted_time = Decimal(0)
        total_weight = Decimal(0)
        num_completed_passengers = 0
        for pid, p_state in self.passengers.items():
            if pid in self.input_passenger_requests:
                 if p_state.completion_time is not None and p_state.request_time is not None and not p_state.is_request_active and p_state.completion_time <= self.tmax:
                     t_i = p_state.completion_time - p_state.request_time
                     if t_i < 0: t_i = Decimal(0)
                     w_i = Decimal(p_state.priority)
                     total_weighted_time += t_i * w_i
                     total_weight += w_i
                     num_completed_passengers += 1
                 elif p_state.completion_time is not None and p_state.completion_time > self.tmax:
                     pass

        weighted_time_wt = Decimal("NaN")
        if num_completed_passengers == 0 and not self.input_passenger_requests:
            weighted_time_wt = Decimal("0")
        elif total_weight > 0:
            weighted_time_wt = total_weighted_time / total_weight

        t_final_float = float(t_final_calc.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        energy_w_float = float(energy_w.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        weighted_time_wt_float = float('nan') if weighted_time_wt.is_nan() else float(weighted_time_wt.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

        return {
            "T_final": t_final_float,
            "W_energy": energy_w_float,
            "WT_weighted_time": weighted_time_wt_float,
            "RawCounts": {
                "ARRIVE": self.arrive_count,
                "OPEN": self.open_count,
                "CLOSE": self.close_count,
                "PassengersCompleted": num_completed_passengers,
                "PassengersInput": len(self.input_passenger_requests)
            }
        }

    # --- Main Check Function ---
    def check(self, input_lines, output_lines):
        # 1. Parse Input
        self.parse_input_lines(input_lines)
        if any("[INPUT ERROR]" in err for err in self.errors):
            # Remove duplicates before returning input errors
            unique_errors = []
            seen_errors = set()
            for error in self.errors:
                if error not in seen_errors:
                    unique_errors.append(error)
                    seen_errors.add(error)
            self.errors = unique_errors
            return json.dumps({"result": "Fail", "errors": self.errors}, indent=2)

        # 2. Process Output lines
        max_time_exceeded_flag = False
        for i, line in enumerate(output_lines):
            line = line.strip()
            if not line: continue

            timestamp, action, args = self.parse_line(line)

            if timestamp is None:
                self.add_error(Decimal("0.0"), f"Line {i+1}: Malformed output line format: {line}")
                continue
            if action in ("INVALID_FORMAT", "UNKNOWN_ACTION", "INVALID_SCHE_SUBACTION", "INVALID_UPDATE_SUBACTION"):
                self.add_error(timestamp, f"Line {i+1}: Invalid action '{action}' or format in output: {line}")
                continue

            if timestamp > self.tmax + EPSILON: # Allow small epsilon for float precision
                self.add_error(timestamp, f"Output timestamp {timestamp:.4f} exceeds the maximum allowed time T_max ({self.tmax:.4f}).")
                max_time_exceeded_flag = True
                # Keep processing lines for format/other errors, but flag the final result

            # Use max to handle out-of-order lines correctly for the non-decreasing check
            current_last_timestamp = self.last_timestamp
            self.last_timestamp = max(self.last_timestamp, timestamp)

            # Check non-decreasing only if the current timestamp isn't over the limit
            # (avoids spurious errors if tmax is exceeded and output stops abruptly)
            if not max_time_exceeded_flag and timestamp < current_last_timestamp - EPSILON:
                 self.add_error(timestamp, f"Timestamp non-decreasing violation. Current: {timestamp:.4f}, Previous: {current_last_timestamp:.4f}")


            # Process the action handler, even if tmax exceeded, to catch basic format/arg errors
            try:
                handler_name = f"handle_{action.replace('-', '_').lower()}"
                handler = getattr(self, handler_name, None)
                if handler:
                    handler(timestamp, args)
                else:
                    self.add_error(timestamp, f"Internal Error: No handler found for recognized action '{action}'.")
            except Exception as e:
                 self.add_error(timestamp, f"Internal checker error processing line {i+1}: '{line}' (Action: '{action}', Args: {args}) -> {type(e).__name__}: {e}")
                 import traceback
                 tb = traceback.format_exc().splitlines()
                 self.errors.append(f"Traceback (last 5 lines): {' | '.join(tb[-5:])}")


        # --- Final Correctness Checks ---
        all_requests_done_and_valid_state = self.perform_final_checks(self.last_timestamp)

        # --- Final TMAX Check ---
        # The check now relies on the max_time_exceeded_flag set during line processing
        final_time_ok = not max_time_exceeded_flag

        # --- Result ---
        if not self.errors and all_requests_done_and_valid_state and final_time_ok:
            performance_metrics = self.calculate_performance()
            return json.dumps({
                "result": "Success",
                "performance": performance_metrics
            }, indent=2)
        else:
            if all_requests_done_and_valid_state is False and not any("FINAL CHECK:" in err for err in self.errors):
                 self.add_error(self.last_timestamp, "FINAL CHECK SUMMARY: Not all requests completed or final system state invalid (check previous errors for details).")
            if not final_time_ok and not max_time_exceeded_flag:
                 # This case should ideally not happen if flag logic is correct
                 self.add_error(self.last_timestamp, "FINAL CHECK SUMMARY: Time limit check failed unexpectedly.")


            # Remove duplicate errors before outputting
            unique_errors = []
            seen_errors = set()
            for error in self.errors:
                if error not in seen_errors:
                    unique_errors.append(error)
                    seen_errors.add(error)
            self.errors = unique_errors
            return json.dumps({"result": "Fail", "errors": self.errors}, indent=2)


# --- Main Execution ---
if __name__ == "__main__":
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(description="Elevator System Checker (HW7 - Modified Input Gaps)")
    parser.add_argument("input_file", help="Path to the input file")
    parser.add_argument("output_file", help="Path to the student's output file")
    parser.add_argument("--tmax", default='120.0',
                        help="Maximum allowed final timestamp (default: 120.0s)")

    args = parser.parse_args()

    # Validate and convert tmax
    try:
        tmax_decimal = Decimal(args.tmax)
        if tmax_decimal < 0:
            raise ValueError("T_max cannot be negative.")
    except (ValueError, TypeError):
        print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Invalid value provided for --tmax: '{args.tmax}'. Must be a non-negative number."]}, indent=2))
        sys.exit(1)

    # --- File Reading ---
    input_lines = []
    output_lines = []

    try:
        with open(args.input_file, 'r', encoding='utf-8') as f: input_lines = f.readlines()
    except FileNotFoundError: print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Input file not found: {args.input_file}"]}, indent=2)); sys.exit(1)
    except Exception as e: print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Error reading input file: {e}"]}, indent=2)); sys.exit(1)

    try:
        with open(args.output_file, 'r', encoding='utf-8') as f: output_lines = f.readlines()
    except FileNotFoundError: print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Output file not found: {args.output_file}"]}, indent=2)); sys.exit(1)
    except Exception as e: print(json.dumps({"result": "Fail", "errors": [f"[PRE-CHECK] Error reading output file: {e}"]}, indent=2)); sys.exit(1)

    # --- Run Checker ---
    checker = ElevatorChecker(tmax=tmax_decimal)
    result_json = checker.check(input_lines, output_lines)
    print(result_json)