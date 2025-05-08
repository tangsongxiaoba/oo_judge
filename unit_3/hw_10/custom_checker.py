# -*- coding: utf-8 -*-
import sys
import json
import subprocess
import os

def normalize_output(content):
    """
    Normalizes output by splitting into lines, stripping whitespace from each line,
    and removing empty lines.
    """
    if content is None:
        return []
    lines = content.splitlines()
    normalized_lines = [line.strip() for line in lines]
    # Filter out lines that become empty after stripping,
    # unless the original content was just a single empty line or only whitespace.
    if not any(line.strip() for line in lines) and lines:
        return [""] if content.strip() == "" and len(lines) == 1 else []
    return [line for line in normalized_lines if line]


def run_comparison_checker(stdin_path, user_stdout_path, std_jar_path_arg):
    result_status = "Accepted"
    error_details = []

    # --- 1. Check if std.jar (passed as argument) exists ---
    if not os.path.exists(std_jar_path_arg):
        result_status = "Rejected"
        error_details.append({
            "reason": f"Checker Configuration Error: Standard solution JAR '{std_jar_path_arg}' not found.",
            "stdin_file": stdin_path,
            "user_stdout_file": user_stdout_path,
            "std_jar_path": std_jar_path_arg
        })
        print(json.dumps({"result": result_status, "errors": error_details}, indent=4, ensure_ascii=False))
        return

    # --- 2. Run std.jar to get true_stdout ---
    true_stdout_content = None
    std_jar_error_output = None
    try:
        with open(stdin_path, 'r', encoding='utf-8') as f_in:
            # Execute std.jar
            process = subprocess.run(
                ['java', '-jar', std_jar_path_arg],
                stdin=f_in,
                capture_output=True,
                text=True,
                encoding='utf-8',
                check=False
            )
            
            if process.returncode != 0:
                result_status = "Rejected"
                std_jar_error_output = process.stderr.strip() if process.stderr else "N/A"
                error_details.append({
                    "reason": f"Standard Solution Error: '{std_jar_path_arg}' exited with code {process.returncode}.",
                    "stdin_file": stdin_path,
                    "user_stdout_file": user_stdout_path,
                    "std_jar_path": std_jar_path_arg,
                    "std_jar_stderr": std_jar_error_output
                })
            else:
                true_stdout_content = process.stdout

    except FileNotFoundError: # This would be for stdin_path if it's somehow removed after initial check
        result_status = "Rejected"
        error_details.append({
            "reason": f"Checker Error: Input file for standard solution not found: {stdin_path}",
            "stdin_file": stdin_path,
            "user_stdout_file": user_stdout_path,
            "std_jar_path": std_jar_path_arg
        })
    except subprocess.CalledProcessError as e: # Should be caught by check=False, but good to have
        result_status = "Rejected"
        error_details.append({
            "reason": f"Checker Error: Failed to run '{std_jar_path_arg}'. Error: {e}",
            "stdin_file": stdin_path,
            "user_stdout_file": user_stdout_path,
            "std_jar_path": std_jar_path_arg,
            "std_jar_stderr": e.stderr.strip() if e.stderr else "N/A"
        })
    except Exception as e:
        result_status = "Rejected"
        error_details.append({
            "reason": f"Checker Error: An unexpected error occurred while running '{std_jar_path_arg}': {type(e).__name__} - {e}",
            "stdin_file": stdin_path,
            "user_stdout_file": user_stdout_path,
            "std_jar_path": std_jar_path_arg
        })

    if result_status == "Rejected":
        print(json.dumps({"result": result_status, "errors": error_details}, indent=4, ensure_ascii=False))
        return

    # --- 3. Read user's stdout ---
    user_stdout_content = None
    try:
        with open(user_stdout_path, 'r', encoding='utf-8') as f_out:
            user_stdout_content = f_out.read()
    except FileNotFoundError:
        result_status = "Rejected"
        error_details.append({
            "reason": f"User Output Error: User output file not found: {user_stdout_path}",
            "stdin_file": stdin_path,
            "user_stdout_file": user_stdout_path,
            "std_jar_path": std_jar_path_arg
        })
    except Exception as e:
        result_status = "Rejected"
        error_details.append({
            "reason": f"User Output Error: Failed to read user output file {user_stdout_path}: {e}",
            "stdin_file": stdin_path,
            "user_stdout_file": user_stdout_path,
            "std_jar_path": std_jar_path_arg
        })

    if result_status == "Rejected":
        print(json.dumps({"result": result_status, "errors": error_details}, indent=4, ensure_ascii=False))
        return

    # --- 4. Compare true_stdout and user_stdout ---
    normalized_true_lines = normalize_output(true_stdout_content)
    normalized_user_lines = normalize_output(user_stdout_content)

    if normalized_true_lines != normalized_user_lines:
        result_status = "Rejected"
        
        diff_reason = "Output content mismatch."
        max_len = max(len(normalized_true_lines), len(normalized_user_lines))
        mismatch_found = False
        for i in range(max_len):
            true_line = normalized_true_lines[i] if i < len(normalized_true_lines) else "<End of True Output>"
            user_line = normalized_user_lines[i] if i < len(normalized_user_lines) else "<End of User Output>"
            if true_line != user_line:
                error_details.append({
                    "reason": "Output content mismatch.",
                    "stdin_file": stdin_path,
                    "user_stdout_file": user_stdout_path,
                    "std_jar_path": std_jar_path_arg,
                    "mismatch_detail": {
                        "line_number": i + 1,
                        "expected_line": true_line,
                        "actual_line": user_line
                    }
                })
                mismatch_found = True
                break
        if not mismatch_found: # Should not happen if lines are different, but as a fallback
             error_details.append({
                "reason": "Output content mismatch (general, lengths might differ or content type).",
                "stdin_file": stdin_path,
                "user_stdout_file": user_stdout_path,
                "std_jar_path": std_jar_path_arg,
             })


    # --- 5. Print final result ---
    final_result = {"result": result_status, "errors": error_details}
    print(json.dumps(final_result, indent=4, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 4: # Changed from 3 to 4
        print(json.dumps({
            "result": "Rejected",
            "errors": [{
                "reason": "Checker Usage Error: Incorrect number of arguments. "
                          "Usage: python comparison_checker.py <stdin_file> <user_stdout_file> <std_jar_file>"
            }]
        }, indent=4, ensure_ascii=False))
        sys.exit(1)

    stdin_file_arg = sys.argv[1]
    user_stdout_file_arg = sys.argv[2]
    std_jar_file_arg = sys.argv[3] # New argument

    run_comparison_checker(stdin_file_arg, user_stdout_file_arg, std_jar_file_arg)