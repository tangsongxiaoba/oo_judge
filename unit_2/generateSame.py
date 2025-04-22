import random
import re
import argparse
import sys

def generate_unique_random_id(existing_ids, min_val=10000, max_val=999999):
    """
    Generates a unique random integer ID within the specified range
    that hasn't been used before in this run.
    """
    while True:
        # Generate a candidate ID
        new_id = random.randint(min_val, max_val)
        # Check if it's already been generated for another passenger
        if new_id not in existing_ids:
            existing_ids.add(new_id)
            return new_id

def process_elevator_input(input_filename, output_filename):
    """
    Reads the input file, randomizes passenger IDs in request lines,
    and writes the result to the output file.
    """
    # Regular expression to match passenger request lines
    # It captures:
    # group(1): The timestamp part (e.g., [5.0])
    # group(2): The original passenger ID part (before -PRI-)
    # group(3): The rest of the line starting from -PRI-
    passenger_request_regex = re.compile(r'^(\[.*?\])(.*?)(-PRI-.*)$')

    # Keep track of generated IDs to ensure uniqueness
    generated_ids = set()
    # Optional: Map original IDs to new IDs if needed later (not used here)
    # id_map = {}

    print(f"Processing input file: {input_filename}")
    print(f"Writing output to: {output_filename}")

    try:
        with open(input_filename, 'r', encoding='utf-8') as infile, \
             open(output_filename, 'w', encoding='utf-8') as outfile:

            line_count = 0
            replaced_count = 0
            for line in infile:
                line_count += 1
                original_line = line.strip() # Remove leading/trailing whitespace

                if not original_line:
                    outfile.write('\n') # Preserve empty lines
                    continue

                match = passenger_request_regex.match(original_line)

                if match:
                    # This looks like a passenger request line
                    timestamp_part = match.group(1)
                    original_id_str = match.group(2)
                    rest_of_line = match.group(3) # Includes the leading -PRI-

                    # Generate a new unique random ID
                    new_id = generate_unique_random_id(generated_ids)
                    # id_map[original_id_str] = new_id # Store mapping if needed

                    # Construct the modified line
                    modified_line = f"{timestamp_part}{new_id}{rest_of_line}"
                    outfile.write(modified_line + '\n')
                    replaced_count += 1
                    # print(f"  Line {line_count}: Replaced ID '{original_id_str}' with '{new_id}'") # Verbose output
                else:
                    # Not a passenger request line, write it unchanged
                    outfile.write(original_line + '\n')

        print(f"\nProcessing complete.")
        print(f"Total lines read: {line_count}")
        print(f"Passenger request IDs replaced: {replaced_count}")

    except FileNotFoundError:
        print(f"Error: Input file '{input_filename}' not found.", file=sys.stderr)
        sys.exit(1)
    except IOError as e:
        print(f"Error reading or writing file: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Randomize passenger IDs in elevator simulation input files."
    )
    parser.add_argument(
        "input_file",
        help="Path to the input file (e.g., stdin18.txt)"
    )
    parser.add_argument(
        "output_file",
        help="Path to the output file where the modified content will be saved."
    )

    args = parser.parse_args()

    process_elevator_input(args.input_file, args.output_file)