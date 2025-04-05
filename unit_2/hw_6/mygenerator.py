import time
import random
import os
import sys
import subprocess
import re

DEFAULT_GEN_MAX_TIME = 50.0 # Default generator -t value if not specified in preset

# --- Generator Argument Presets ---
# List of command strings for gen.py
# --- Updated GEN_PRESET_COMMANDS for HW6 ---
GEN_PRESET_COMMANDS = [
    # === Baseline (Mix Passengers & SCHE) ===
    # OK: Moderate P/S, intervals likely okay. Assumes gen.py default interval isn't pathologically small.
    "gen.py -np 20 -ns 5 -t 50.0",

    # === Load & Density (Passengers Dominant) ===
    # OK (--hce): HuCe constraints met. SCHE on different elevators.
    "gen.py -np 65 -ns 5 -t 40.0 --min-interval 0.0 --max-interval 0.5 --hce", # Total 70
    # RISKY (non-hce): -ns 5 with potentially small intervals. Increased min-interval slightly. Requires gen.py fix ideally.
    "gen.py -np 90 -ns 5 -t 70.0 --min-interval 0.5 --max-interval 1.5",
    # OK: Sparse requests, low chance of SCHE collision even without --hce.
    "gen.py -np 6 -ns 2 -t 100.0 --min-interval 10.0 --max-interval 15.0",
    # OK: Moderate density, -ns 5 over long time. Should be okay.
    "gen.py -np 70 -ns 5 -t 150.0 --min-interval 0.5 --max-interval 2.5",
    # OK: Very few P requests.
    "gen.py -np 2 -ns 0 -t 10.0 --min-interval 0.1 --max-interval 0.5",
    # OK (--hce): HuCe constraints met.
    "gen.py -np 1 -ns 1 -t 10.0 --hce --min-interval 0.2 --max-interval 0.8", # Total 2

    # === Timing & Passenger Bursts ===
    # RISKY (non-hce): -ns 2 but all requests in <10s. Low chance but possible SCHE collision.
    "gen.py -np 30 -ns 2 -t 10.0 --start-time 1.0 --force-start-passengers 30",
    # RISKY (non-hce): -ns 1, OK.
    "gen.py -np 20 -ns 1 -t 30.0 --start-time 1.0 --force-end-passengers 20",
    # RISKY (non-hce): -ns 1, OK.
    "gen.py -np 15 -ns 1 -t 5.0 --start-time 5.0 --max-time 5.0",
    # RISKY (non-hce): -ns 3 concentrated in ~0.1s. Higher chance of SCHE collision. Needs gen.py fix ideally.
    "gen.py -np 45 -ns 3 -t 10.1 --start-time 10.0 --burst-size 45 --burst-time 10.0",
    # RISKY (non-hce): -ns 5 spread over 50s. Moderate risk.
    "gen.py -np 55 -ns 5 -t 50.0 --burst-size 30",
    # FIXED (non-hce): Increased min-interval significantly for -ns 10. Still assumes gen.py doesn't pathologically cluster.
    "gen.py -np 80 -ns 10 -t 80.0 --min-interval 2.0 --max-interval 5.0 --start-time 2.0 --force-start-passengers 25 --burst-size 30 --burst-time 41.0 --force-end-passengers 25", # Note: -ns 10 needs care!
    # OK (--hce): HuCe constraints met. Max time adjusted.
    "gen.py -np 60 -ns 5 -t 40.0 --max-time 40.0 --hce --force-start-passengers 20 --burst-size 25 --burst-time 8.0", # Total 65
    # OK (--hce): HuCe constraints met. Max time adjusted.
    "gen.py -np 35 -ns 5 -t 49.5 --max-time 49.5 --hce --burst-size 20 --burst-time 48.0", # Total 40
    # OK (non-hce): Sparse P, -ns 5 over 100s. Low risk.
    "gen.py -np 15 -ns 5 -t 100.0 --min-interval 8.0 --max-interval 12.0 --burst-size 8 --burst-time 50.0",
    # RISKY (non-hce): -ns 2 with fixed 0.5s interval. Possible SCHE collision.
    "gen.py -np 28 -ns 2 -t 30.0 --min-interval 0.5 --max-interval 0.5",

    # === Passenger Priority Focus ===
    # RISKY (non-hce): -ns 5 over 30s. Moderate risk.
    "gen.py -np 55 -ns 5 -t 30.0 --priority-bias extremes --priority-bias-ratio 0.9",
    # RISKY (non-hce): -ns 5 over 40s. Moderate risk.
    "gen.py -np 50 -ns 5 -t 40.0 --priority-bias middle --priority-bias-ratio 0.9 --priority-middle-range 10",
    # RISKY (non-hce): -ns 2 over 40s. Lower risk.
    "gen.py -np 48 -ns 2 -t 40.0 --priority-bias middle --priority-bias-ratio 0.8 --priority-middle-range 2",
    # OK (non-hce): Sparse P, -ns 5 over 120s. Low risk.
    "gen.py -np 10 -ns 5 -t 120.0 --min-interval 5.0 --max-interval 10.0 --priority-bias extremes --priority-bias-ratio 0.9",
    # RISKY (non-hce): -ns 5 over 30s. Moderate risk.
    "gen.py -np 35 -ns 5 -t 30.0 --priority-bias extremes --priority-bias-ratio 1.0",

    # === Passenger Floor Patterns ===
    # RISKY (non-hce): -ns 5 over 60s. Moderate risk.
    "gen.py -np 45 -ns 5 -t 60.0 --extreme-floor-ratio 0.8",

    # === SCHE Focused Tests ===
    # --- SCHE Distribution & Timing ---
    # OK (--hce): SCHE ONLY, spread out on different elevators. HuCe time limit ok.
    "gen.py -np 1 -ns 6 -t 50.0 --max-time 50.0 --min-interval 7.0 --max-interval 9.0 --hce",
    # OK (--hce): P + SCHE clustered early. HuCe rules ok.
    "gen.py -np 10 -ns 6 -t 20.0 --max-time 20.0 --min-interval 0.1 --max-interval 1.5 --hce",
    # OK: SCHE ONLY, very late.
    "gen.py -np 1 -ns 1 -t 50.0 --start-time 49.0",
    # OK: SCHE ONLY, very early.
    "gen.py -np 1 -ns 1 -t 5.0 --start-time 1.0 --max-time 1.1",
    # RISKY (non-hce): -ns 5 late, concentrated in 10s. Moderate risk.
    "gen.py -np 10 -ns 5 -t 50.0 --start-time 40.0",
    # --- SCHE interacting with Passenger Loads ---
    # OK (--hce): SCHE spread out (diff elevators), passenger burst later. HuCe time ok.
    "gen.py -np 30 -ns 5 -t 50.0 --max-time 50.0 --burst-size 20 --burst-time 35.0 --hce", # Total 35
    # OK (--hce): High passenger density + Max SCHE (diff elevators). HuCe time ok.
    "gen.py -np 60 -ns 6 -t 45.0 --max-time 45.0 --min-interval 0.1 --max-interval 0.8 --hce", # Total 66
    # OK (--hce): Extreme priority P + Max SCHE (diff elevators). HuCe time ok.
    "gen.py -np 50 -ns 6 -t 40.0 --max-time 40.0 --priority-bias extremes --priority-bias-ratio 0.7 --hce", # Total 56
    # OK (--hce): Extreme floor P + Max SCHE (diff elevators). HuCe time ok.
    "gen.py -np 40 -ns 6 -t 60.0 --max-time 50.0 --extreme-floor-ratio 0.6 --hce", # Total 46, enforced max_time 50 for HuCe
    # OK (--hce): Early passenger burst + Max SCHE (diff elevators). HuCe time ok.
    "gen.py -np 20 -ns 6 -t 70.0 --max-time 50.0 --start-time 10.0 --burst-size 15 --burst-time 15.0 --hce", # Total 26, enforced max_time 50 for HuCe

    # === Complex Combinations (Revisited for HW6) ===
    # OK (--hce): Mix forces/burst/prio + SCHE (diff elevators). HuCe time ok.
    "gen.py -np 60 -ns 5 -t 45.0 --max-time 45.0 --start-time 1.0 --force-start-passengers 5 --force-end-passengers 5 --burst-size 15 --burst-time 20.0 --priority-bias extremes --priority-bias-ratio 0.3 --hce", # Total 65
    # OK (--hce): Very high density P/S, HuCe limit. SCHE on diff elevators. HuCe time ok.
    "gen.py -np 64 -ns 6 -t 20.0 --max-time 20.0 --hce --min-interval 0.0 --max-interval 0.2 --priority-bias extremes --priority-bias-ratio 0.4", # Total 70
    # OK (--hce): Extreme floor + middle prio P + SCHE (diff elevators). HuCe time ok.
    "gen.py -np 50 -ns 5 -t 45.0 --max-time 45.0 --hce --extreme-floor-ratio 0.6 --priority-bias middle --priority-bias-ratio 0.7 --priority-middle-range 15", # Total 55
    # OK (--hce): Extreme floor/prio P + SCHE (diff elevators). HuCe time ok.
    "gen.py -np 45 -ns 5 -t 45.0 --max-time 45.0 --hce --extreme-floor-ratio 0.7 --priority-bias extremes --priority-bias-ratio 0.6", # Total 50
    # FIXED (non-hce): Replaced -ns 10 with -ns 6 and increased interval. Reduced risk.
    "gen.py -np 50 -ns 6 -t 70.0 --min-interval 1.0 --max-interval 4.0 --extreme-floor-ratio 0.7 --priority-bias extremes --priority-bias-ratio 0.7",

    "gen.py -np 20 -ns 5 -t 50.0",

    # === Load & Density (Passengers Dominant) ===
    # ID: HCE_MAX_LOAD
    # OK (--hce): Maximize passengers under HuCe limit with a few SCHE. High density.
    "gen.py -np 67 -ns 3 -t 40.0 --min-interval 0.0 --max-interval 0.3 --hce", # Total 70
    # ID: PUB_HIGH_LOAD
    # OK (non-hce): High passenger load, moderate SCHE spread out.
    "gen.py -np 90 -ns 8 -t 80.0 --min-interval 0.5 --max-interval 1.0",
    # ID: HCE_SPARSE
    # OK (--hce): Few requests, very spread out.
    "gen.py -np 4 -ns 2 -t 45.0 --min-interval 8.0 --max-interval 12.0 --hce", # Total 6
    # ID: PUB_SPARSE_LONG
    # OK (non-hce): Moderate P/S over very long duration.
    "gen.py -np 30 -ns 10 -t 200.0 --min-interval 3.0 --max-interval 8.0",

    # === Timing & Passenger Bursts ===
    # ID: HCE_FORCE_START_MAX_SCHE
    # OK (--hce): All passengers forced at start, max allowed SCHE spread later.
    "gen.py -np 40 -ns 6 -t 50.0 --start-time 1.0 --force-start-passengers 40 --min-interval 6.0 --max-interval 8.0 --hce", # Total 46
    # ID: HCE_FORCE_END_SCHE
    # OK (--hce): All passengers forced at end, SCHE requests earlier.
    "gen.py -np 30 -ns 5 -t 50.0 --start-time 1.0 --force-end-passengers 30 --max-time 49.9 --hce", # Total 35
    # ID: PUB_BURST_EARLY_HIGH_SCHE
    # OK (non-hce): Early passenger burst, high number of SCHE spread after.
    "gen.py -np 30 -ns 18 -t 100.0 --start-time 5.0 --burst-size 30 --burst-time 5.1 --min-interval 4.0 --max-interval 6.0",
    # ID: PUB_BURST_MID_HIGH_SCHE
    # OK (non-hce): Mid-simulation burst during potential SCHE period (tests interaction). High SCHE count.
    "gen.py -np 40 -ns 15 -t 80.0 --burst-size 35 --burst-time 40.0 --min-interval 1.0 --max-interval 5.0",
    # ID: HCE_BURST_LATE
    # OK (--hce): SCHE spread early, passenger burst very late within HuCe limits.
    "gen.py -np 20 -ns 6 -t 50.0 --start-time 1.0 --burst-size 15 --burst-time 48.0 --hce", # Total 26
    # ID: PUB_MULTI_BURST_SCHE
    # OK (non-hce): Multiple passenger events (force start, burst, force end) interspersed with SCHE. Uses moderate SCHE count.
    "gen.py -np 60 -ns 8 -t 90.0 --force-start-passengers 10 --burst-size 20 --burst-time 45.0 --force-end-passengers 10 --min-interval 1.0 --max-interval 6.0", # P=10+20+10 + 20 middle

    # === Passenger Priority Focus ===
    # ID: HCE_PRIO_EXTREME_MAX_SCHE
    # OK (--hce): High extreme priority passenger load + Max allowed SCHE.
    "gen.py -np 54 -ns 6 -t 40.0 --priority-bias extremes --priority-bias-ratio 0.9 --hce", # Total 60
    # ID: PUB_PRIO_MIDDLE_HIGH_SCHE
    # OK (non-hce): High middle priority passenger load + High SCHE count.
    "gen.py -np 50 -ns 16 -t 100.0 --priority-bias middle --priority-bias-ratio 0.8 --priority-middle-range 10 --min-interval 1.0 --max-interval 5.0",

    # === Passenger Floor Patterns ===
    # ID: HCE_FLOOR_EXTREME_MAX_SCHE
    # OK (--hce): High extreme floor passenger load + Max allowed SCHE.
    "gen.py -np 44 -ns 6 -t 48.0 --extreme-floor-ratio 0.8 --hce", # Total 50
    # ID: PUB_FLOOR_EXTREME_HIGH_SCHE
    # OK (non-hce): High extreme floor passenger load + High SCHE count.
    "gen.py -np 40 -ns 17 -t 120.0 --extreme-floor-ratio 0.7 --min-interval 2.0 --max-interval 6.0",

    # === SCHE Focused Tests ===
    # ID: HCE_SCHE_ONLY_MAX
    # OK (--hce): SCHE ONLY, max allowed (6), spread within HuCe time.
    "gen.py -np 1 -ns 6 -t 50.0 --start-time 1.0 --min-interval 7.0 --max-interval 8.0 --hce",
    # ID: HCE_SCHE_ONLY_CLUSTERED
    # OK (--hce): SCHE ONLY, max allowed (6), forced into shorter time span (intervals enforced by gen.py).
    "gen.py -np 1 -ns 6 -t 40.0 --start-time 1.0 --max-time 40.0 --min-interval 0.1 --max-interval 1.0 --hce",
    # ID: PUB_SCHE_ONLY_MAX
    # OK (non-hce): SCHE ONLY, max public count (20), requires long duration for 6s interval.
    "gen.py -np 1 -ns 20 -t 150.0 --start-time 1.0 --min-interval 6.0 --max-interval 7.0",
    # ID: PUB_SCHE_ONLY_MAX_PRESSURE
    # OK (non-hce): SCHE ONLY, max public count (20), shorter duration tests generator's time advancement.
    "gen.py -np 1 -ns 20 -t 100.0 --start-time 1.0 --min-interval 0.5 --max-interval 3.0", # Generator will push times > 6s apart

    # === Pressure Tests (Bursts during SCHE periods) ===
    # ID: HCE_PRESSURE_BURST_MID_SCHE
    # OK (--hce): Max SCHE spread, large passenger burst occurs mid-way.
    "gen.py -np 40 -ns 6 -t 50.0 --start-time 1.0 --burst-size 35 --burst-time 25.0 --hce", # Total 46
    # ID: PUB_PRESSURE_BURST_HIGH_SCHE
    # OK (non-hce): High SCHE count spread, large passenger burst mid-way.
    "gen.py -np 50 -ns 15 -t 100.0 --start-time 1.0 --min-interval 1.0 --max-interval 5.0 --burst-size 40 --burst-time 50.0",
    # ID: HCE_PRESSURE_DENSE_P_MAX_SCHE
    # OK (--hce): High density passengers throughout + Max SCHE requests.
    "gen.py -np 64 -ns 6 -t 30.0 --max-time 30.0 --min-interval 0.0 --max-interval 0.3 --hce", # Total 70
    # ID: PUB_PRESSURE_DENSE_P_HIGH_SCHE
    # OK (non-hce): High density passengers throughout + High SCHE count.
    "gen.py -np 70 -ns 18 -t 90.0 --min-interval 0.1 --max-interval 0.8",

    # === Minimal Cases ===
    # ID: HCE_MIN_P
    # OK (--hce): Minimal passengers, no SCHE.
    "gen.py -np 1 -ns 0 -t 5.0 --hce",
    # ID: HCE_MIN_SCHE
    # OK (--hce): No passengers, minimal SCHE.
    "gen.py -np 1 -ns 1 -t 5.0 --hce",
    # ID: PUB_MIN_P
    # OK (non-hce): Minimal passengers, no SCHE.
    "gen.py -np 1 -ns 0 -t 5.0",
    # ID: PUB_MIN_SCHE
    # OK (non-hce): No passengers, minimal SCHE.
    "gen.py -np 1 -ns 1 -t 5.0",

    # === Edge Combinations ===
    # ID: HCE_EXTREME_ALL
    # OK (--hce): Combines Prio/Floor extremes, burst, forced, max SCHE under HuCe limits.
    "gen.py -np 50 -ns 6 -t 50.0 --force-start-passengers 5 --force-end-passengers 5 --burst-size 10 --burst-time 25.0 --priority-bias extremes --priority-bias-ratio 0.5 --extreme-floor-ratio 0.5 --hce", # Total 56
    # ID: PUB_EXTREME_ALL_HIGH_SCHE
    # OK (non-hce): Combines Prio/Floor extremes, burst, forced, high SCHE count.
    "gen.py -np 40 -ns 19 -t 140.0 --force-start-passengers 5 --force-end-passengers 5 --burst-size 10 --burst-time 70.0 --priority-bias middle --priority-bias-ratio 0.4 --priority-middle-range 5 --extreme-floor-ratio 0.6 --min-interval 1.0 --max-interval 5.0", # P=5+5+10+20=40
]

def _generate_data(gen_args_list):
        """Calls gen.py with provided args, returns requests, writes output to unique tmp file."""
        # Generate a unique filename for this round's input data
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        rand_id = random.randint(1000, 9999)

        requests_data = None
        gen_stdout = None

        try:
            command = ["python"] + gen_args_list
            gen_proc = subprocess.run(
                command, capture_output=True, text=True, timeout=15, check=True, encoding='utf-8', errors='replace'
            )
            gen_stdout = gen_proc.stdout

            # --- (Request Parsing Logic - unchanged) ---
            raw_requests = gen_stdout.strip().splitlines()
            requests_data = []
            pattern = re.compile(r"\[\s*(\d+\.\d+)\s*\](.*)")
            for line in raw_requests:
                match = pattern.match(line)
                if match:
                    timestamp_req = float(match.group(1)) # Renamed to avoid confusion
                    req_part = match.group(2)
                    requests_data.append((timestamp_req, req_part))
                elif line.strip(): # Ignore empty lines
                    print(f"WARNING: Generator produced invalid line format (ignored): {line}", file=sys.stderr)

            is_n_zero = any(arg == '-n' and gen_args_list[i+1] == '0' for i, arg in enumerate(gen_args_list[:-1]))
            if not raw_requests and not requests_data and is_n_zero:
                 return [] # Still return path even if empty

            if not requests_data and raw_requests:
                 print(f"WARNING: Generator produced output, but no valid request lines were parsed.", file=sys.stderr)
                 return [] # Return path even if parsing failed

            requests_data.sort(key=lambda x: x[0])
            return requests_data
            # --- (End Request Parsing Logic) ---

        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired:
            print("ERROR: Generator script timed out.", file=sys.stderr)
            return None
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Generator script failed with exit code {e.returncode}.", file=sys.stderr)
            print(f"--- Generator Command ---\n{' '.join(command)}", file=sys.stderr)
            print(f"--- Generator Stdout ---\n{e.stdout or '<empty>'}\n--- Generator Stderr ---\n{e.stderr or '<empty>'}", file=sys.stderr)
            # Try to save the failed output anyway
        except Exception as e:
            print(f"ERROR: Failed to generate data: {e}", file=sys.stderr)
            return None

def genData():
    command = random.choice(GEN_PRESET_COMMANDS)
    command = command.split(" ")
    datas = _generate_data(command)
    ret = []
    # print(datas)
    for data in datas:
        ret.append(f"[{data[0]}]{data[1]}\n")
    return "".join(ret)


if __name__ == "__main__":
    ret = genData()
    print(ret)