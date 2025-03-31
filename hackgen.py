import time
import random
import os
import sys
import subprocess
import re

DEFAULT_GEN_MAX_TIME = 50.0 # Default generator -t value if not specified in preset

# --- Generator Argument Presets ---
# List of command strings for gen.py
GEN_PRESET_COMMANDS = [
    # === Baseline ===
    # "gen.py -n 25 -t 50.0",
    # === Load & Density ===
    # "gen.py -n 70 -t 40.0 --min-interval 0.0 --max-interval 0.5 --hce",
    # "gen.py -n 98 -t 70.0 --min-interval 0.1 --max-interval 0.8",
    # "gen.py -n 8 -t 100.0 --min-interval 10.0 --max-interval 15.0",
    # "gen.py -n 75 -t 150.0 --min-interval 0.5 --max-interval 2.5",
    # # "gen.py -n 1 -t 10.0",
    # "gen.py -n 2 -t 10.0 --min-interval 0.1 --max-interval 0.5",
    # # "gen.py -n 1 -t 10.0 --hce",
    # "gen.py -n 2 -t 10.0 --hce --min-interval 0.2 --max-interval 0.8",
    # === Timing & Bursts ===
    "gen.py -n 30 --start-time 1.0 --max-time 10.0 --force-start-requests 30", # Uses --max-time
    "gen.py -n 20 --start-time 1.0 --max-time 30.0 --force-end-requests 20", # Uses --max-time
    "gen.py -n 15 --start-time 5.0 --max-time 5.0",                             # Uses --max-time
    "gen.py -n 45 --start-time 10.0 --max-time 10.1 --burst-size 45 --burst-time 10.0", # Uses --max-time
    "gen.py -n 60 -t 49.9 --burst-size 30",
    # "gen.py -n 90 -t 80.0 --start-time 2.0 --force-start-requests 25 --burst-size 30 --burst-time 41.0 --force-end-requests 25",
    "gen.py -n 65 -t 40.0 --hce --force-start-requests 20 --burst-size 25 --burst-time 8.0",
    "gen.py -n 40 -t 49.5 --hce --burst-size 20 --burst-time 48.0",
    # "gen.py -n 20 -t 100.0 --min-interval 8.0 --max-interval 12.0 --burst-size 8 --burst-time 50.0",
    "gen.py -n 30 -t 30.0 --min-interval 0.5 --max-interval 0.5",
    # === Priority ===
    # "gen.py -n 60 -t 30.0 --priority-bias extremes --priority-bias-ratio 0.9",
    # "gen.py -n 55 -t 40.0 --priority-bias middle --priority-bias-ratio 0.9 --priority-middle-range 10",
    # "gen.py -n 50 -t 40.0 --priority-bias middle --priority-bias-ratio 0.8 --priority-middle-range 2",
    # "gen.py -n 15 -t 120.0 --min-interval 5.0 --max-interval 10.0 --priority-bias extremes --priority-bias-ratio 0.9",
    # "gen.py -n 40 -t 30.0 --priority-bias extremes --priority-bias-ratio 1.0",
    # === Elevator Focus ===
    "gen.py -n 40 -t 30.0 --focus-elevator 1 --focus-ratio 1.0 --hce", # Added -t
    "gen.py -n 70 -t 48.0 --hce --focus-elevator 2 --focus-ratio 0.8",
    "gen.py -n 80 -t 49.0 --focus-elevator 4 --focus-ratio 0.9",
    "gen.py -n 40 -t 30.0 --focus-elevator 5 --focus-ratio 0.0",
    # === Floor Patterns ===
    "gen.py -n 50 -t 49.0 --extreme-floor-ratio 0.8",
    # === Complex Combinations ===
    "gen.py -n 65 -t 45.0 --start-time 1.0 --force-start-requests 5 --force-end-requests 5 --burst-size 15 --burst-time 20.0 --focus-elevator 3 --focus-ratio 0.5 --priority-bias extremes --priority-bias-ratio 0.3 --hce",
    "gen.py -n 60 -t 20.0 --hce --min-interval 0.0 --max-interval 0.2 --priority-bias extremes --priority-bias-ratio 0.4",
    "gen.py -n 55 -t 45.0 --hce --extreme-floor-ratio 0.6 --priority-bias middle --priority-bias-ratio 0.7 --priority-middle-range 15",
    "gen.py -n 50 -t 45.0 --hce --extreme-floor-ratio 0.7 --priority-bias extremes --priority-bias-ratio 0.6",
    "gen.py -n 60 -t 49.0 --extreme-floor-ratio 0.7 --priority-bias extremes --priority-bias-ratio 0.7",
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
                command, capture_output=True, text=True, timeout=15, check=True, encoding='utf-8', errors='replace', cwd=os.path.join("unit_2", "hw_5")
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
    for data in datas:
        ret.append(f"[{data[0]}]{data[1]}\n")
    return "".join(ret)


if __name__ == "__main__":
    ret = genData()
    print(ret)