import random
import time
from playwright.sync_api import sync_playwright
import playwright
import os
import subprocess
import re
import sys
import shutil
import playwright.sync_api
import json
import yaml
import concurrent.futures
from datetime import datetime, timedelta

PASSED = []
REJECTED = []
THISSTDIN = None

GEN_PRESET_COMMANDS = [
    "gen.py -np 20 -ns 5 -t 50.0 --hce",
    "gen.py -np 65 -ns 5 -t 50.0 --min-interval 0.0 --max-interval 0.5 --hce",
    "gen.py -np 64 -ns 6 -t 50.0 --min-interval 0.0 --max-interval 0.3 --hce",
    "gen.py -np 6 -ns 2 -t 50.0 --min-interval 10.0 --max-interval 15.0 --hce",
    "gen.py -np 2 -ns 0 -t 50.0 --min-interval 0.1 --max-interval 0.5 --hce",
    "gen.py -np 0 -ns 1 -t 50.0 --hce",
    "gen.py -np 0 -ns 6 -t 50.0 --hce",
    "gen.py -np 30 -ns 2 -t 50.0 --start-time 1.0 --force-start-passengers 30 --hce",
    "gen.py -np 20 -ns 1 -t 50.0 --start-time 1.0 --force-end-passengers 20 --hce",
    "gen.py -np 15 -ns 1 -t 50.0 --start-time 5.0 --max-time 5.0 --hce",
    "gen.py -np 45 -ns 3 -t 50.0 --start-time 10.0 --burst-size 45 --burst-time 10.0 --hce",
    "gen.py -np 55 -ns 5 -t 50.0 --burst-size 30 --burst-time 25.0 --hce",
    "gen.py -np 60 -ns 5 -t 50.0 --force-start-passengers 5 --force-end-passengers 5 --burst-size 15 --burst-time 20.0 --hce",
    "gen.py -np 55 -ns 5 -t 50.0 --priority-bias extremes --priority-bias-ratio 0.9 --hce",
    "gen.py -np 50 -ns 5 -t 50.0 --priority-bias middle --priority-bias-ratio 0.9 --priority-middle-range 10 --hce",
    "gen.py -np 48 -ns 2 -t 50.0 --priority-bias middle --priority-bias-ratio 0.8 --priority-middle-range 2 --hce",
    "gen.py -np 45 -ns 5 -t 50.0 --extreme-floor-ratio 0.8 --hce",
    "gen.py -np 1 -ns 6 -t 50.0 --min-interval 7.0 --max-interval 9.0 --hce",
    "gen.py -np 10 -ns 6 -t 50.0 --min-interval 0.1 --max-interval 1.5 --hce",
    "gen.py -np 10 -ns 5 -t 50.0 --start-time 40.0 --hce",
    "gen.py -np 50 -ns 6 -t 50.0 --priority-bias extremes --priority-bias-ratio 0.7 --hce",
    "gen.py -np 40 -ns 6 -t 50.0 --extreme-floor-ratio 0.6 --hce",
    "gen.py -np 20 -ns 6 -t 50.0 --start-time 10.0 --burst-size 15 --burst-time 15.0 --hce",
    "gen.py -np 50 -ns 5 -t 50.0 --extreme-floor-ratio 0.6 --priority-bias middle --priority-bias-ratio 0.7 --priority-middle-range 15 --hce",
    "gen.py -np 54 -ns 6 -t 50.0 --extreme-floor-ratio 1.0 --priority-bias extremes --priority-bias-ratio 1.0 --hce",
    "gen.py -np 40 -ns 6 -t 50.0 --force-start-passengers 5 --burst-size 10 --burst-time 25.0 --priority-bias extremes --priority-bias-ratio 0.5 --extreme-floor-ratio 0.5 --hce",
    "gen.py -np 30 -ns 6 -t 50.0 --start-time 15.0 --max-time 15.1 --force-start-passengers 30 --hce",
    "gen.py -np 64 -ns 6 -t 50.0 --start-time 40.0 --max-time 40.2 --force-start-passengers 64 --hce",
    "gen.py -np 40 -ns 6 -t 50.0 --start-time 1.0 --force-start-passengers 40 --min-interval 5.0 --max-interval 7.0 --hce",
    "gen.py -np 34 -ns 6 -t 50.0 --start-time 1.0 --burst-size 30 --burst-time 25.0 --hce",
    "gen.py -np 1 -ns 6 -t 50.0 --start-time 1.0 --max-time 40.0 --min-interval 0.1 --max-interval 1.0 --hce",
]

def run_std_jar(std_jar_path, stdin_path, timeout_seconds=300):
    print(f"INFO: Running standard JAR '{os.path.basename(std_jar_path)}' with input '{os.path.basename(stdin_path)}'...")
    try:
        with open(stdin_path, "r", encoding="utf-8") as stdin_file:
            java_proc = subprocess.run(
                ["java", "-jar", os.path.abspath(std_jar_path)],
                stdin=stdin_file,
                capture_output=True,
                text=True,
                encoding='utf-8',
                check=False, # Don't raise exception on non-zero exit
                timeout=timeout_seconds
            )

        if java_proc.returncode != 0:
            print(f"ERROR: Standard JAR process failed for input '{os.path.basename(stdin_path)}'. Return code: {java_proc.returncode}")
            if java_proc.stderr:
                print(f"Java stderr:\n---\n{java_proc.stderr.strip()}\n---")
            return None # Indicate failure

        print(f"INFO: Standard JAR ran successfully for '{os.path.basename(stdin_path)}'.")
        return java_proc.stdout # Return the captured stdout

    except subprocess.TimeoutExpired:
        print(f"ERROR: Standard JAR process timed out ({timeout_seconds}s) for input '{os.path.basename(stdin_path)}'.")
        return None
    except FileNotFoundError:
        print(f"ERROR: 'java' command not found or Standard JAR '{std_jar_path}' not found.")
        # This is a critical setup error, maybe raise it? For now, return None.
        return None
    except Exception as e:
        print(f"ERROR: An unexpected error occurred while running the Standard JAR for '{os.path.basename(stdin_path)}': {e}")
        import traceback
        print(traceback.format_exc())
        return None

def move_file_pair(base_name, source_dir, dest_dir):
    """将指定基名的 .in 和 .out 文件从源目录移动到目标目录"""
    os.makedirs(dest_dir, exist_ok=True) # 确保目标目录存在
    moved_in = False
    moved_out = False
    for suffix in [".in", ".out"]:
        source_path = os.path.join(source_dir, f"{base_name}{suffix}")
        dest_path = os.path.join(dest_dir, f"{base_name}{suffix}")
        if os.path.exists(source_path):
            try:
                shutil.move(source_path, dest_path)
                print(f"INFO: Moved {source_path} to {dest_path}")
                if suffix == ".in": moved_in = True
                if suffix == ".out": moved_out = True
            except Exception as e:
                print(f"ERROR: Failed to move {source_path} to {dest_path}: {e}")
        else:
            print(f"WARNING: Source file {source_path} not found for moving.")
    return moved_in and moved_out

def load_config(config_path="config.yml"):
    if not os.path.exists(config_path):
        print(f"CRITICAL ERROR: Configuration file '{config_path}' not found.")
        print("Please create config.yml in the same directory as hack.py with your settings.")
        sys.exit(1)
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"CRITICAL ERROR: Error parsing configuration file '{config_path}': {e}")
        sys.exit(1)
    except Exception as e:
        print(f"CRITICAL ERROR: Error reading configuration file '{config_path}': {e}")
        sys.exit(1)

    # 基本验证 (可以根据需要添加更多检查)
    required_keys = ['hw', 'stu_id', 'stu_pwd', 'jar_base_dir', 'hacker']
    if not all([(key in config) for key in required_keys]):
        print(f"CRITICAL ERROR: Config file '{config_path}' is missing one or more required top-level keys: {required_keys}")
        sys.exit(1)

    required_hacker_keys = ['std_jar_name', 'checker_name', 'generator_name', 'hack_dir', 'num_generate', 'debug', 'courseid']
    if not isinstance(config['hacker'], dict) or not all(key in config['hacker'] for key in required_hacker_keys):
        print(f"CRITICAL ERROR: Config file '{config_path}' is missing one or more required keys under 'hacker': {required_hacker_keys}")
        sys.exit(1)

    if not config.get('stu_id') or not config.get('stu_pwd'):
        print("CRITICAL ERROR: 'stu_id' or 'stu_pwd' is not set in the config file.")
        sys.exit(1)

    print(f"INFO: Configuration loaded successfully from '{config_path}'.")
    return config

def calculate_paths(config):
    """根据配置计算所需的文件路径"""
    hw = config['hw']
    unit_no = (hw - 1) // 4 + 1 # 计算单元号 (假设 hw 5,6,7,8 对应 unit 2)

    # 作业相关路径
    unit_hw_dir = os.path.join(f"unit_{unit_no}", f"hw_{hw}")
    checker_path = os.path.join(unit_hw_dir, config['hacker']['checker_name'])
    generator_path = os.path.join(unit_hw_dir, config['hacker']['generator_name'])

    # 标准 JAR 路径
    std_jar_path = os.path.join(config['jar_base_dir'], config['hacker']['std_jar_name'])

    # Hack 目录
    hack_dir = config['hacker']['hack_dir']

    # 检查关键文件是否存在
    if not os.path.exists(checker_path):
        print(f"CRITICAL ERROR: Checker script not found at calculated path: {checker_path}")
        sys.exit(1)
    if not os.path.exists(generator_path):
        print(f"CRITICAL ERROR: Generator script not found at calculated path: {generator_path}")
        sys.exit(1)
    if not os.path.exists(std_jar_path):
        print(f"CRITICAL ERROR: Standard JAR not found at calculated path: {std_jar_path}")
        sys.exit(1)
    
    print(f"INFO: Using Checker: {checker_path}")
    print(f"INFO: Using Generator: {generator_path}")
    print(f"INFO: Using Std JAR: {std_jar_path}")
    print(f"INFO: Using Hack Dir: {hack_dir}")

    return checker_path, generator_path, std_jar_path, hack_dir

def login(page, usr, pwd):
    print(f"INFO: Attempting login for user: {usr}")
    page.goto("http://oo.buaa.edu.cn")
    page.locator(".topmost a").click()
    page.wait_for_selector("iframe#loginIframe", timeout=10000)
    iframe = page.frame_locator("iframe#loginIframe")
    time.sleep(1)
    iframe.locator("div.content-con-box:nth-of-type(1) div.item:nth-of-type(1) input").fill(usr)
    time.sleep(1)
    iframe.locator("div.content-con-box:nth-of-type(1) div.item:nth-of-type(3) input").fill(pwd)
    time.sleep(1)
    iframe.locator("div.content-con-box:nth-of-type(1) div.item:nth-of-type(7) input").click()
    time.sleep(1)
    print("INFO: Login form submitted.") # 添加日志

def remove(list1: list, list2):
    items_to_remove = set(list2) # 使用集合提高查找效率
    list1[:] = [item for item in list1 if item not in items_to_remove]

def _generate_single_missing_out(std_jar_path, stdin_path, stdout_path, hack_rejected_dir):
    """
    Worker function for parallel generation. Runs std_jar for a single stdin,
    writes stdout, or moves stdin to rejected on failure.

    Returns:
        tuple: (stdin_path, success_boolean)
    """
    base_name = os.path.basename(stdin_path).replace(".in", "")
    print(f"INFO [Parallel Worker]: Checking/Generating for {base_name}.in")
    generated_stdout_content = run_std_jar(std_jar_path, stdin_path) # 使用已有的函数

    if generated_stdout_content is None:
        # JAR 运行失败或超时
        print(f"ERROR [Parallel Worker]: Failed to generate stdout for '{base_name}.in'. Moving to rejected.")
        # 移动 .in 文件到 rejected
        in_dst = os.path.join(hack_rejected_dir, f"{base_name}.in")
        os.makedirs(hack_rejected_dir, exist_ok=True)
        if os.path.exists(stdin_path):
            try:
                shutil.move(stdin_path, in_dst)
                print(f"INFO [Parallel Worker]: Moved '{base_name}.in' to rejected.")
                # 注意：这里不直接修改全局 REJECTED 列表，依赖文件移动
            except Exception as e:
                print(f"ERROR [Parallel Worker]: Failed to move '{base_name}.in' to '{in_dst}': {e}")
        return stdin_path, False # Indicate failure
    else:
        # JAR 运行成功，尝试写入 .out 文件
        try:
            with open(stdout_path, "w", encoding="utf-8") as f_out:
                f_out.write(generated_stdout_content)
            print(f"INFO [Parallel Worker]: Successfully generated '{base_name}.out'.")
            return stdin_path, True # Indicate success
        except IOError as e:
            print(f"ERROR [Parallel Worker]: Failed to write generated stdout to '{os.path.basename(stdout_path)}': {e}. Leaving '{base_name}.in' as is (will likely be rejected later).")
            # 如果写入失败，暂时不移动，让 choose_existed_one 稍后处理（它会发现无法读取/验证）
            # 或者，也可以选择在这里移动到 rejected
            # in_dst = os.path.join(hack_rejected_dir, f"{base_name}.in")
            # os.makedirs(hack_rejected_dir, exist_ok=True)
            # if os.path.exists(stdin_path):
            #     try: shutil.move(stdin_path, in_dst)
            #     except Exception: pass
            return stdin_path, False # Indicate failure due to write error


# 新增：并行生成所有缺失的 .out 文件
def generate_missing_out_files_parallel(hack_waiting_dir, hack_rejected_dir, std_jar_path):
    """
    Finds all .in files in waiting dir without a corresponding .out file
    and attempts to generate the .out files in parallel using std_jar.
    Moves failed .in files to rejected dir.
    """
    print("\n--- Checking for and generating missing .out files in parallel ---")
    try:
        all_files = os.listdir(hack_waiting_dir)
        in_files = {f for f in all_files if f.endswith(".in")}
        out_files = {f for f in all_files if f.endswith(".out")}
    except FileNotFoundError:
        print(f"INFO: Waiting directory '{hack_waiting_dir}' not found or empty. Skipping generation.")
        return

    missing_pairs = []
    for stdin_name in in_files:
        base_name = stdin_name.replace(".in", "")
        stdout_name = f"{base_name}.out"
        if stdout_name not in out_files:
            stdin_path = os.path.join(hack_waiting_dir, stdin_name)
            stdout_path = os.path.join(hack_waiting_dir, stdout_name)
            missing_pairs.append((stdin_path, stdout_path))

    if not missing_pairs:
        print("INFO: No missing .out files found in waiting directory.")
        return

    print(f"INFO: Found {len(missing_pairs)} .in files missing corresponding .out files. Starting parallel generation...")
    os.makedirs(hack_rejected_dir, exist_ok=True) # Ensure rejected dir exists

    successful_generations = 0
    failed_generations = 0
    # 使用与 generate_random_ones 类似的并行逻辑
    # 限制 worker 数量，防止过多进程拖慢系统
    max_workers = min(len(missing_pairs), os.cpu_count() or 4) # 保守一点，或者用 os.cpu_count()
    print(f"INFO: Using up to {max_workers} worker processes for parallel generation.")

    futures = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        for stdin_path, stdout_path in missing_pairs:
            future = executor.submit(
                _generate_single_missing_out, # 调用新的工作者函数
                std_jar_path,
                stdin_path,
                stdout_path,
                hack_rejected_dir
            )
            futures.append(future)

        print(f"INFO: Submitted {len(futures)} generation tasks. Waiting for completion...")
        for future in concurrent.futures.as_completed(futures):
            try:
                _, success = future.result() # 获取工作函数返回的元组
                if success:
                    successful_generations += 1
                else:
                    failed_generations += 1
            except Exception as e:
                # 这个异常通常是 worker 进程内部未捕获的严重错误
                print(f"ERROR: A parallel generation task failed with an unexpected exception: {e}")
                failed_generations += 1
                import traceback
                print(traceback.format_exc())

    print(f"--- Parallel generation finished ---")
    print(f"Successfully generated: {successful_generations}")
    print(f"Failed/Moved to rejected: {failed_generations}")

def choose_existed_one(hack_waiting_dir, hack_rejected_dir, checker_path, std_jar_path):
    global REJECTED, PASSED, THISSTDIN
    try:
        all_in_files = [f for f in os.listdir(hack_waiting_dir) if f.endswith(".in")]
    except FileNotFoundError:
        print(f"WARNING: Waiting directory '{hack_waiting_dir}' not found.")
        return None, None
       
    available_bases = [f.replace(".in", "") for f in all_in_files if f.replace(".in", "") not in REJECTED and f.replace(".in", "") not in PASSED]
    if not available_bases:
        print("INFO: No available & valid data pairs found in the waiting directory (after parallel generation attempt).")
        return None, None
    random.shuffle(available_bases)

    for base_name in available_bases: # 尝试所有可用的
        stdin_name = f"{base_name}.in"
        stdout_name = f"{base_name}.out"

        stdin_path = os.path.join(hack_waiting_dir, stdin_name)
        stdout_path = os.path.join(hack_waiting_dir, stdout_name)

        if not os.path.exists(stdout_path):
            print(f"INFO: Stdout file '{stdout_name}' not found for '{stdin_name}'. Attempting to generate it using std_jar...")

            generated_stdout_content = run_std_jar(std_jar_path, stdin_path) # run_std_jar 已包含超时处理

            if generated_stdout_content is None:
                # run_std_jar 失败 (超时、Java 错误等)
                print(f"ERROR: Failed to generate stdout for '{stdin_name}' using std_jar. Moving '{stdin_name}' to rejected.")
                REJECTED.append(base_name)
                # 只移动 .in 文件
                in_src = os.path.join(hack_waiting_dir, stdin_name)
                in_dst = os.path.join(hack_rejected_dir, stdin_name) # 直接用 .in 文件名
                os.makedirs(hack_rejected_dir, exist_ok=True)
                if os.path.exists(in_src):
                    try:
                        shutil.move(in_src, in_dst)
                    except Exception as e:
                        print(f"ERROR: Failed to move '{in_src}' to rejected after generation failure: {e}")
                continue # 尝试下一个 base_name

            else:
                # run_std_jar 成功，尝试写入 .out 文件
                try:
                    with open(stdout_path, "w", encoding="utf-8") as f_out:
                        f_out.write(generated_stdout_content)
                    print(f"INFO: Successfully generated and saved '{stdout_name}'. Proceeding with checker validation.")
                    # 文件已生成，让代码自然流到下面的 checker 验证部分
                    # *** 不要 continue ***
                except IOError as e:
                    print(f"ERROR: Failed to write generated stdout to '{stdout_path}': {e}. Moving '{stdin_name}' to rejected.")
                    REJECTED.append(base_name)
                    # 只移动 .in 文件
                    in_src = os.path.join(hack_waiting_dir, stdin_name)
                    in_dst = os.path.join(hack_rejected_dir, stdin_name)
                    os.makedirs(hack_rejected_dir, exist_ok=True)
                    if os.path.exists(in_src):
                        try:
                            shutil.move(in_src, in_dst)
                        except Exception as move_e:
                            print(f"ERROR: Failed to move '{in_src}' to rejected after write failure: {move_e}")
                    # 清理可能创建的不完整 .out 文件 (可选，但最好加上)
                    if os.path.exists(stdout_path):
                        try: os.remove(stdout_path)
                        except OSError as remove_e: print(f"WARNING: Could not remove partially written file '{stdout_path}': {remove_e}")
                    continue # 尝试下一个 base_name
        
        isPass = False # 默认检查不通过
        checker_errors = []

        if not os.path.exists(stdout_path):
            print(f"INTERNAL ERROR: stdout file '{stdout_path}' should exist at this point but doesn't. Skipping {base_name}.")
            REJECTED.append(base_name)
            # 尝试移动 .in 文件
            in_src = os.path.join(hack_waiting_dir, stdin_name)
            in_dst = os.path.join(hack_rejected_dir, stdin_name)
            os.makedirs(hack_rejected_dir, exist_ok=True)
            if os.path.exists(in_src):
                try: shutil.move(in_src, in_dst)
                except Exception as e: print(f"ERROR: Failed to move '{in_src}' to rejected after internal error: {e}")
            continue

        print(f"INFO: Checking data pair: {base_name}.in / .out from waiting dir.")
        try:
            # 运行 checker.py 脚本 (传入 waiting 目录中的文件路径)
            checker_process = subprocess.run(
                ["python", checker_path, stdin_path, stdout_path], # <--- 新用法: 使用 "python" 和 checker_path
                capture_output=True,
                text=True,         # 获取文本输出
                encoding='utf-8',  # 指定编码
                check=False        # 不要对非零退出码抛出异常，我们自己检查输出
            )

            checker_output_str = checker_process.stdout.strip()
            checker_stderr_str = checker_process.stderr.strip()

            if checker_stderr_str:
                print(f"WARNING: Checker script for {base_name} produced stderr output:")
                print(checker_stderr_str)

            if not checker_output_str:
                print(f"ERROR: Checker script for {base_name} produced no stdout output.")
                checker_errors.append("Checker produced no stdout.")
            else:
                # *** 修改点：使用 json.loads 解析 checker 输出 ***
                try:
                    checker_data = json.loads(checker_output_str)
                    if isinstance(checker_data, dict):
                        # 检查 "result" 字段是否为 "Success"
                        if checker_data.get("result") == "Success":
                            isPass = True
                            print(f"INFO: Checker validation PASSED for {base_name}.")
                        else:
                            # 如果不是 Success，记录 checker 提供的错误信息
                            checker_errors = checker_data.get("errors", ["Checker result was not 'Success', but no specific errors provided."])
                            print(f"INFO: Checker validation FAILED for {base_name}.")
                    else:
                        print(f"ERROR: Checker output for {base_name} is not a valid JSON object (dict). Output: {checker_output_str}")
                        checker_errors.append("Checker output was not a JSON object.")

                except json.JSONDecodeError:
                    print(f"ERROR: Failed to parse checker output for {base_name} as JSON.")
                    print(f"Raw checker output:\n---\n{checker_output_str}\n---")
                    checker_errors.append("Failed to parse checker output as JSON.")
                except Exception as e: # 捕获其他可能的解析错误
                    print(f"ERROR: Unexpected error parsing checker JSON for {base_name}: {e}")
                    checker_errors.append(f"Unexpected JSON parsing error: {e}")

        except FileNotFoundError:
            print(f"CRITICAL ERROR: Cannot find Python interpreter 'python' or Checker script '{checker_path}'.")
            # 这是一个严重问题，可能需要停止脚本
            raise # 重新抛出异常，让脚本停止
        except Exception as e:
            print(f"ERROR: An unexpected error occurred while running the checker for {base_name}: {e}")
            checker_errors.append(f"Unexpected error during checker execution: {e}")
    
        if not isPass:
            print(f"ERROR: Data pair {base_name} failed validation. Moving to rejected.")
            if checker_errors:
                print("Checker Errors/Reasons:")
                for err in checker_errors:
                    print(f"  - {err}")
            REJECTED.append(base_name)
            move_file_pair(base_name, hack_waiting_dir, hack_rejected_dir)
        else:
            # 如果检查通过，读取文件内容
            try:
                with open(stdin_path, "r", encoding="utf-8") as f_in:
                    stdin_content = f_in.read()
                with open(stdout_path, "r", encoding="utf-8") as f_out:
                    stdout_content = f_out.read()

                THISSTDIN = base_name # 记录当前成功选中的文件名
                print(f"INFO: Successfully selected and validated data pair: {THISSTDIN} from waiting dir.")
                return stdin_content, stdout_content
            except Exception as e:
                print(f"ERROR: Failed to read content of validated files for {base_name}: {e}. Moving to rejected.")
                REJECTED.append(base_name) # 即使通过了检查，如果读不了文件也算拒绝
    print("INFO: No valid and readable data pair found in the current waiting list.")
    return None, None

def generate_single_pair(generator_path, std_jar_path, hack_waiting_dir, command_str, index, formatted_time):
    final_filename_base = f"{formatted_time}_{index}"
    # 使用唯一的临时 stdin 文件名，防止并行冲突
    temp_stdin_filename = f"temp_stdin_{formatted_time}_{index}.txt"
    temp_stdin_path = os.path.join(hack_waiting_dir, temp_stdin_filename) # <--- 修改路径
    final_stdin_path = os.path.join(hack_waiting_dir, f"{final_filename_base}.in") # <--- 修改路径
    stdout_path = os.path.join(hack_waiting_dir, f"{final_filename_base}.out") 

    print(f"INFO [Worker {index}]: Starting generation for {final_filename_base} into '{hack_waiting_dir}' using '{command_str}'")

    try:
        # 1. 运行 gen.py
        command_parts = command_str.split()
        gen_args = command_parts[1:] if command_parts[0] == 'gen.py' else command_parts

        gen_process = subprocess.run(
            ["python", generator_path] + gen_args,
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=False
        )

        if gen_process.returncode != 0:
            print(f"ERROR [Worker {index}]: gen.py failed for command '{command_str}'. Return code: {gen_process.returncode}")
            print(f"gen.py stderr:\n---\n{gen_process.stderr.strip()}\n---")
            return None # 表示失败

        stdin_content = gen_process.stdout
        if not stdin_content.strip():
            print(f"WARNING [Worker {index}]: gen.py for command '{command_str}' produced empty output. Skipping.")
            return None # 表示失败

        # 写入临时 stdin 文件 (确保 java 能读到)
        try:
            with open(temp_stdin_path, "w", encoding="utf-8") as file:
                file.write(stdin_content)
        except IOError as e:
            print(f"ERROR [Worker {index}]: Failed to write temporary stdin file {temp_stdin_path}: {e}")
            return None

        # 2. 运行 Java STD_JAR
        # print(f"DEBUG [Worker {index}]: Running STD_JAR process...") # Debugging print
        try:
            # 使用临时文件作为 stdin 重定向的来源
            with open(temp_stdin_path, "r", encoding="utf-8") as stdin_file:
                 java_proc = subprocess.run(
                    ["java", "-jar", os.path.abspath(std_jar_path)],
                    stdin=stdin_file,          # 从临时文件读取输入
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    check=False,
                    timeout=300 # 添加超时，防止标程卡死 (60秒, 可调整)
                )

            if java_proc.returncode != 0:
                print(f"ERROR [Worker {index}]: Java STD_JAR process failed for {final_filename_base}. Return code: {java_proc.returncode}")
                if java_proc.stderr:
                    print(f"Java stderr:\n---\n{java_proc.stderr.strip()}\n---")
                # 清理临时文件
                if os.path.exists(temp_stdin_path): os.remove(temp_stdin_path)
                return None # 表示失败

            # 3. 写入 Java 输出到 stdout 文件
            try:
                with open(stdout_path, "w", encoding="utf-8") as stdout_file:
                    stdout_file.write(java_proc.stdout)
            except IOError as e:
                print(f"ERROR [Worker {index}]: Failed to write stdout file {stdout_path}: {e}")
                if os.path.exists(temp_stdin_path): os.remove(temp_stdin_path)
                return None

            # 4. 重命名临时 stdin 文件为最终文件
            shutil.move(temp_stdin_path, final_stdin_path)
            print(f"INFO [Worker {index}]: Successfully generated pair in waiting dir: {final_filename_base}.in / .out")
            return final_filename_base # 返回成功的文件基名

        except subprocess.TimeoutExpired:
            print(f"ERROR [Worker {index}]: Java STD_JAR process timed out for {final_filename_base}.")
            if os.path.exists(temp_stdin_path): os.remove(temp_stdin_path)
            return None
        except FileNotFoundError:
            print(f"ERROR [Worker {index}]: 'java' command not found or STD_JAR '{std_jar_path}' not found.")
            if os.path.exists(temp_stdin_path): os.remove(temp_stdin_path)
            # 这是一个严重错误，但只影响当前 worker
            return None
        except Exception as e:
            print(f"ERROR [Worker {index}]: An unexpected error occurred while running the Java process for {final_filename_base}: {e}")
            if os.path.exists(temp_stdin_path): os.remove(temp_stdin_path)
            import traceback
            print(traceback.format_exc())
            return None # 表示失败

    except FileNotFoundError as e:
        print(f"ERROR [Worker {index}]: File not found during generation: {e}. Check PYTHON path or GENERATOR path.")
        return None
    except Exception as e:
        print(f"ERROR [Worker {index}]: Exception during generation for {final_filename_base}: {e}")
        # 确保清理可能的临时文件
        if os.path.exists(temp_stdin_path):
            try:
                os.remove(temp_stdin_path)
            except OSError as remove_err:
                print(f"WARNING [Worker {index}]: Could not remove temp file {temp_stdin_path} after error: {remove_err}")
        import traceback
        print(traceback.format_exc())
        return None # 表示失败

def generate_random_ones(std_jar_path, generator_path, hack_dir, num_generate):
    hack_waiting_dir = os.path.join(hack_dir, "waiting")

    print(f"INFO: Generating {num_generate} new data points in parallel into '{hack_waiting_dir}'...")
    try:
        # 确保目录存在
        os.makedirs(hack_waiting_dir, exist_ok=True)

        local_time = time.localtime()
        formatted_time = time.strftime("%Y%m%d_%H%M%S", local_time)
        generated_count = 0
        futures = []

        if not GEN_PRESET_COMMANDS:
            print("ERROR: GEN_PRESET_COMMANDS list is empty. Cannot generate data.")
            return # 或者 raise Exception

        max_workers = min(num_generate, os.cpu_count() or 1) # 限制最大worker数量，防止过载
        print(f"INFO: Using up to {max_workers} worker processes for generation.")

        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            # 提交 num_generate 个任务到进程池
            for i in range(num_generate):
                selected_command_str = random.choice(GEN_PRESET_COMMANDS)
                # 提交任务：调用 generate_single_pair 函数
                future = executor.submit(
                    generate_single_pair,
                    generator_path,
                    std_jar_path,
                    hack_waiting_dir,
                    selected_command_str,
                    i, # 传递索引
                    formatted_time # 传递时间戳
                )
                futures.append(future)

            # 等待所有任务完成并收集结果
            print(f"INFO: Submitted {len(futures)} generation tasks. Waiting for completion...")
            # 使用 as_completed 可以按完成顺序处理结果，方便实时反馈
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result() # 获取工作函数的返回值 (文件名或 None)
                    if result is not None:
                        generated_count += 1
                except Exception as e:
                    # 这个异常通常是 worker 进程内部未捕获的严重错误
                    print(f"ERROR: A generation task failed with an unexpected exception: {e}")
                    import traceback
                    print(traceback.format_exc())

        print(f"INFO: Parallel generation complete. Successfully generated {generated_count}/{num_generate} new data pairs into '{hack_waiting_dir}'.")
        if generated_count == 0 and num_generate > 0:
            print("WARNING: Failed to generate any new data pairs.")

    except Exception as e:
        print(f"ERROR: Unexpected error during parallel data generation setup: {e}")
        import traceback
        print(traceback.format_exc())

def select_point(hack_dir, checker_path, std_jar_path):
    hack_waiting_dir = os.path.join(hack_dir, "waiting")
    hack_rejected_dir = os.path.join(hack_dir, "rejected")

    os.makedirs(hack_waiting_dir, exist_ok=True)
    os.makedirs(hack_rejected_dir, exist_ok=True)

    print(f"\n--- Selecting data point from '{hack_waiting_dir}' (Single Attempt) ---")

    stdin_content, stdout_content = choose_existed_one(hack_waiting_dir, hack_rejected_dir, checker_path, std_jar_path)
    if stdin_content is not None and stdout_content is not None:
        print(f"INFO: Successfully selected data pair '{THISSTDIN}' from waiting directory.")
        return stdin_content, stdout_content
    else:
        # choose_existed_one 未能在当前 waiting 目录中找到有效且可用的数据点
        print(f"INFO: No valid and available data pair found in '{hack_waiting_dir}' during this selection attempt.") # <--- 修改日志
        return None, None # 返回 None, None 表示失败

def send_point(page: playwright.sync_api.Page, homework_id: int, target_alias_name: str, stdin_content: str, stdout_content: str, hack_dir: str):
    global PASSED, REJECTED, THISSTDIN

    hack_waiting_dir = os.path.join(hack_dir, "waiting")
    hack_passed_dir = os.path.join(hack_dir, "passed")
    hack_rejected_dir = os.path.join(hack_dir, "rejected")

    print("\n--- Attempting to submit the selected hack via API ---")

    if not THISSTDIN:
        print("CRITICAL ERROR: THISSTDIN is not set before calling send_point. Cannot determine which file to move later.")
        # 最好在这里做个防护，虽然理论上 main 的逻辑保证了这一点
        return False, False

    print(f"INFO: Using selected data pair: {THISSTDIN}. Preparing API submission for target '{target_alias_name}'.")

    api_url = f"http://api.oo.buaa.edu.cn/homework/{homework_id}/mutual_test/room/self/code/{target_alias_name}/submit_data"

    payload = {
        'stdin': stdin_content,
        'stdout': stdout_content
    }
    api_timeout = 15000
    is_cooldown = False
    is_success = False

    try:
        print(f"INFO: Sending POST request to {api_url}")
        response = page.request.post(
            api_url,
            data=payload,
            timeout=api_timeout
        )

        print(f"INFO: API response status: {response.status}")

        if not response.ok:
            print(f"ERROR: API submission failed with HTTP status {response.status}: {response.status_text}")
            try:
                error_body = response.text()
                print(f"Response body: {error_body}")
                try:
                    error_data = json.loads(error_body)
                    api_message = error_data.get("message", "No message in error body.")
                    print(f"API Error Message: {api_message}")
                    if error_data.get("code") == 1617:
                        print("INFO: Cooldown detected via API error response (code 1617).")
                        is_cooldown = True
                except json.JSONDecodeError:
                    print("INFO: Error response body is not valid JSON.")
            except Exception as text_err:
                print(f"ERROR: Could not read response body after HTTP error: {text_err}")
            is_success = False
        else:
            try:
                response_data = response.json()
                print(f"INFO: API Response JSON: {response_data}")

                message = response_data.get("message", "No message provided.")
                print(f"INFO: API Message: {message}")

                if response_data.get("success") is True:
                    print("INFO: API reported SUCCESSFUL submission.")
                    is_success = True
                else:
                    print("INFO: API reported FAILED submission (success: false or missing).")
                    is_success = False
                    if response_data.get("code") == 1617:
                        print("INFO: Cooldown detected via API response (code 1617).")
                        is_cooldown = True

            except json.JSONDecodeError as json_err:
                print(f"ERROR: Failed to parse successful API response as JSON: {json_err}")
                print(f"Raw response body: {response.text()}")
                is_success = False
            except Exception as parse_err:
                print(f"ERROR: Unexpected error processing API JSON response: {parse_err}")
                is_success = False

    except playwright.sync_api.Error as api_err: # Catch Playwright network errors (timeout, connection refused etc.)
        print(f"ERROR: Playwright API request failed: {api_err}")
        is_success = False # Treat request error as failure
    except Exception as e:
        print(f"ERROR: Unexpected exception during API submission call: {e}")
        import traceback
        print(traceback.format_exc())
        is_success = False # Treat unexpected errors as failure

    if THISSTDIN: # Ensure THISSTDIN is set (it should be if select_point succeeded)
        if is_success:
            print(f"INFO: Moving data pair {THISSTDIN} to passed directory.")
            PASSED.append(THISSTDIN)
            move_file_pair(THISSTDIN, hack_waiting_dir, hack_passed_dir)
            print("COMMITTED successfully via API")
        elif is_cooldown:
            # If the *reason* for failure was cooldown, leave the data in waiting
            print(f"INFO: Submission blocked by cooldown (API code 1617). Data pair {THISSTDIN} remains in waiting directory.")
        else:
            # Any other failure reason -> move to rejected
            print(f"INFO: Moving data pair {THISSTDIN} to rejected directory due to API submission failure (HTTP error, success:false, JSON error, etc.).")
            REJECTED.append(THISSTDIN)
            move_file_pair(THISSTDIN, hack_waiting_dir, hack_rejected_dir)
    else:
        print("WARNING: THISSTDIN was not set before file moving logic. This might indicate an issue in select_point.")
    
    return is_cooldown, is_success

def get_course(page: playwright.sync_api.Page, config):
    print("INFO: Navigating to course page using API...")
    
    hw = config['hw']
    course_id = config['hacker']['courseid']
    api_base_url = "http://api.oo.buaa.edu.cn"
    web_base_url = "http://oo.buaa.edu.cn"
    api_url = f"{api_base_url}/course/{course_id}"

    homework_id = None
    homework_name = None # 用于日志记录

    try:
        print(f"INFO: Fetching course data from API: {api_url}")
        # 使用 Playwright 的 page.request 来利用已登录的 session/cookie
        # 不需要导入 requests 库
        api_response = page.request.get(api_url)

        if not api_response.ok:
            print(f"ERROR: API request failed with status {api_response.status}: {api_response.status_text}")
            print(f"Response body: {api_response.text()}") # 打印错误信息
            raise Exception(f"API request failed: {api_response.status}")

        print("INFO: API request successful. Parsing JSON response...")
        try:
            data = api_response.json()
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse JSON response from API: {e}")
            print(f"Raw response: {api_response.text()}")
            raise Exception("JSON parsing error")

        # 验证 JSON 结构并提取 homework ID
        if data.get('success') and 'data' in data and 'homeworks' in data['data']:
            homeworks = data['data']['homeworks']
            hw_index = hw - 1 # 用户要求使用 hw-1 作为索引

            if 0 <= hw_index < len(homeworks):
                target_homework = homeworks[hw_index]
                homework_id = target_homework.get('id')
                homework_name = target_homework.get('name') # 获取名称用于日志
                if homework_id is None:
                    print(f"ERROR: Homework entry at index {hw_index} is missing 'id'. Data: {target_homework}")
                    raise Exception("Homework ID not found in API data")
                print(f"INFO: Found Homework ID: {homework_id} (Name: '{homework_name}') for HW {hw} (index {hw_index}).")
            else:
                print(f"ERROR: Invalid homework index {hw_index} for API data. Found {len(homeworks)} homeworks.")
                print(f"Available homeworks: {homeworks}")
                raise Exception("Homework index out of bounds")
        else:
            print("ERROR: Unexpected API response structure.")
            print(f"API Response Data: {data}")
            raise Exception("Invalid API response structure")

    except playwright.sync_api.Error as e: # 捕获 Playwright 的网络错误
        print(f"CRITICAL ERROR: Playwright network error during API request: {e}")
        raise Exception(f"Playwright API request failed: {e}")
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to get homework ID from API: {e}")
        raise # 重新抛出异常

    if homework_id is not None:
        mutual_url = f"{web_base_url}/assignment/{homework_id}/mutual"
        print(f"INFO: Navigating to mutual testing page: {mutual_url}")
        try:
            page.goto(mutual_url)
            print("INFO: Mutual testing page loaded successfully.")
            return homework_id
        except playwright.sync_api.TimeoutError:
            print(f"WARNING: Timed out waiting for '互测房间' element on {mutual_url}. Page might be slow or structure changed.")
            # 检查当前 URL 是否正确，如果错误则抛出异常
            current_url = page.url
            if str(homework_id) not in current_url or "/mutual" not in current_url:
                 print(f"ERROR: Failed to load the correct mutual testing page. Current URL: {current_url}")
                 raise Exception("Navigation to mutual page failed after timeout")
            else:
                 print("INFO: Current URL seems correct despite timeout waiting for element. Proceeding cautiously.")
        except playwright.sync_api.Error as e: # 捕获 Playwright 导航错误
            print(f"CRITICAL ERROR: Playwright error during navigation to mutual page: {e}")
            raise Exception(f"Playwright navigation failed: {e}")
        except Exception as e:
            print(f"CRITICAL ERROR: Unexpected error during navigation to mutual page: {e}")
            raise # 重新抛出异常
    else:
        # 这个分支理论上不应该执行到，因为前面出错会 raise
        print("CRITICAL ERROR: homework_id is None after API processing. This should not happen.")
        raise Exception("Internal logic error: homework_id is None")

def ready_to_break(page: playwright.sync_api.Page, homework_id: int, hack_limit=3):
    api_url = f"http://api.oo.buaa.edu.cn/homework/{homework_id}/mutual_test/room/self"
    print(f"INFO: Checking hack status via API: {api_url}")

    try:
        api_response = page.request.get(api_url)

        if not api_response.ok:
            print(f"ERROR: API request failed with status {api_response.status}: {api_response.status_text}")
            print(f"Response body: {api_response.text()}")
            return False, None # API 失败，无法判断，不停止

        try:
            data = api_response.json()
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse JSON response from room API: {e}")
            print(f"Raw response: {api_response.text()}")
            return False, None # JSON 解析失败，无法判断，不停止

        # 验证基本结构并获取自身 alias_name 和成员列表
        if (data.get('success') and
                'data' in data and
                'mutual_test' in data['data'] and
                'my_alias_name' in data['data']['mutual_test'] and
                'members' in data['data'] and
                isinstance(data['data']['members'], list)):

            my_alias_name = data['data']['mutual_test']['my_alias_name']
            members = data['data']['members']
            print(f"INFO: My alias name is {my_alias_name}. Checking {len(members)} members.")

            potential_target_alias = None # 存储第一个遇到的非自己成员的 alias_name

            for member in members:
                member_alias = member.get('alias_name')
                if member_alias is None:
                    print(f"WARNING: Member found without alias_name: {member}")
                    continue # 跳过无效成员数据

                # 跳过自己
                if member_alias == my_alias_name:
                    continue

                # 记录第一个遇到的其他人
                if potential_target_alias is None:
                    potential_target_alias = member_alias

                # 检查 hacked.your_success
                hacked_info = member.get('hacked', {})
                your_success_str = hacked_info.get('your_success')

                if your_success_str is not None:
                    try:
                        your_success_count = int(your_success_str)
                        print(f"INFO: Checking member {member_alias}: your_success = {your_success_count}")
                        if your_success_count >= hack_limit:
                            print(f"INFO: Hack limit ({hack_limit}) reached for member {member_alias}. Stopping condition met.")
                            return True, None # 达到停止条件
                    except ValueError:
                        print(f"WARNING: Could not convert 'your_success' ({your_success_str}) to int for member {member_alias}.")
                        # 可以选择将此视为 0 或跳过，这里选择视为未达到限制
                else:
                     print(f"WARNING: 'your_success' key missing in 'hacked' info for member {member_alias}.")

            # 如果循环完成，说明没有人达到 hack_limit
            if potential_target_alias is not None:
                print(f"INFO: Hack limit not reached for any member. Potential target alias: {potential_target_alias}")
                return False, potential_target_alias # 未达到停止条件，返回 false 和一个目标
            else:
                print("INFO: No other members found in the room or all other members had invalid data. Cannot determine target.")
                return False, None # 没有找到其他成员，也算未达到停止条件，但无目标返回

        else:
            print("ERROR: Unexpected API response structure or missing key fields ('success', 'data', 'mutual_test', 'my_alias_name', 'members').")
            print(f"API Response Data: {data}")
            return False, None # 结构错误，无法判断，不停止

    except playwright.sync_api.Error as e:
        print(f"ERROR: Playwright network error during room API request: {e}")
        return False, None # 网络错误，无法判断，不停止
    except Exception as e:
        print(f"ERROR: An unexpected error occurred in ready_to_break: {e}")
        import traceback
        print(traceback.format_exc())
        return False, None # 其他未知错误，无法判断，不停止
    
def sync_lists_and_ensure_waiting_data(hack_dir, std_jar_path, generator_path, num_generate):
    global PASSED, REJECTED # 明确我们要修改全局列表

    hack_waiting_dir = os.path.join(hack_dir, "waiting")
    hack_passed_dir = os.path.join(hack_dir, "passed")
    hack_rejected_dir = os.path.join(hack_dir, "rejected")

    print("\n--- Synchronizing PASSED/REJECTED lists and ensuring data availability ---")

    # 确保目录存在 (虽然 main 里也做了，但这里再确认下无妨)
    os.makedirs(hack_waiting_dir, exist_ok=True)
    os.makedirs(hack_passed_dir, exist_ok=True)
    os.makedirs(hack_rejected_dir, exist_ok=True)

    # 从 passed 目录同步 PASSED 列表
    try:
        passed_files = {f.replace(".in", "") for f in os.listdir(hack_passed_dir) if f.endswith(".in")}
        PASSED[:] = list(passed_files) # 使用切片赋值更新全局列表
        print(f"INFO: Synced PASSED list from directory. Count: {len(PASSED)}")
    except FileNotFoundError:
        print(f"WARNING: Passed directory '{hack_passed_dir}' not found during sync.")
        PASSED[:] = [] # 如果目录不存在，清空列表

    # 从 rejected 目录同步 REJECTED 列表
    try:
        rejected_files = {f.replace(".in", "") for f in os.listdir(hack_rejected_dir) if f.endswith(".in")}
        REJECTED[:] = list(rejected_files) # 使用切片赋值更新全局列表
        print(f"INFO: Synced REJECTED list from directory. Count: {len(REJECTED)}")
    except FileNotFoundError:
        print(f"WARNING: Rejected directory '{hack_rejected_dir}' not found during sync.")
        REJECTED[:] = [] # 如果目录不存在，清空列表

    print("INFO: Attempting to generate any missing .out files in waiting directory...")
    try:
        generate_missing_out_files_parallel(hack_waiting_dir, hack_rejected_dir, std_jar_path)
    except Exception as e:
        print(f"ERROR: Unexpected error during parallel generation of missing .out files: {e}")
        # 即使生成失败，也继续尝试检查和生成新的
        import traceback
        print(traceback.format_exc())

    # 检查 waiting 目录中是否有可用的数据点
    try:
        waiting_files = [f for f in os.listdir(hack_waiting_dir) if f.endswith(".in")]
        available_waiting_bases = {
            f.replace(".in", "") for f in waiting_files
            if f.replace(".in", "") not in PASSED and f.replace(".in", "") not in REJECTED
        }
        num_available = len(available_waiting_bases)
        print(f"INFO: Found {num_available} available data points in '{hack_waiting_dir}' (excluding PASSED/REJECTED).")

        if num_available == 0:
            print(f"INFO: No available data found in '{hack_waiting_dir}'. Generating {num_generate} new data points...")
            try:
                # 调用现有的生成函数
                generate_random_ones(std_jar_path, generator_path, hack_dir, num_generate)
            except Exception as e:
                print(f"ERROR: Failed to generate random data when waiting directory was empty: {e}")
                import traceback
                print(traceback.format_exc())

    except FileNotFoundError:
        print(f"WARNING: Waiting directory '{hack_waiting_dir}' not found. Attempting to generate new data...")
        try:
            generate_random_ones(std_jar_path, generator_path, hack_dir, num_generate)
        except Exception as e:
            print(f"ERROR: Failed to generate random data after waiting directory not found: {e}")
            import traceback
            print(traceback.format_exc())

    print("--- Synchronization and data availability check complete ---")

def handle_cooldown(page: playwright.sync_api.Page, homework_id: int):
    """
    检查API的冷却状态，如果处于冷却中，则计算等待时间并休眠，然后重新加载页面。
    """
    print("\n--- Checking cooldown status via API ---")
    cooldown_api_url = f"http://api.oo.buaa.edu.cn/homework/{homework_id}/mutual_test"
    should_reload = False # 标记是否需要重新加载页面

    try:
        api_response = page.request.get(cooldown_api_url)
        if api_response.ok:
            data = api_response.json()
            if data.get('success') and 'data' in data:
                mutual_data = data['data']
                is_cooling_down = mutual_data.get('cooling_down')
                print(f"INFO: API cooldown status: {is_cooling_down}")

                if is_cooling_down is True:
                    submit_cd = mutual_data.get('submit_cd')
                    last_submit_str = mutual_data.get('last_submit')
                    current_time_str = mutual_data.get('current_time')

                    if submit_cd is not None and last_submit_str and current_time_str:
                        try:
                            time_format = "%Y-%m-%d %H:%M:%S"
                            # 为时区不匹配添加健壮性处理 (假设API时间是本地时间或UTC，但保持一致即可)
                            # 如果需要更精确的时区处理，需要使用 pytz 等库
                            last_submit_dt = datetime.strptime(last_submit_str, time_format)
                            current_time_dt = datetime.strptime(current_time_str, time_format)
                            cooldown_end_time = last_submit_dt + timedelta(seconds=submit_cd)
                            wait_duration = cooldown_end_time - current_time_dt
                            wait_seconds = max(0, wait_duration.total_seconds()) # 确保等待时间不为负

                            if wait_seconds > 0:
                                sleep_time = wait_seconds
                                total_sleep_int = int(sleep_time)
                                print(f"INFO: Currently in cooldown. Last submit: {last_submit_str}, CD: {submit_cd}s. Calculated wait time: {wait_seconds:.2f}s. Sleeping for {total_sleep_int} seconds...")
                                last_msg_len = 0
                                for i in range(total_sleep_int, 0, -1):
                                    progress_message = f"Cooldown remaining: {i:>{len(str(total_sleep_int))}} seconds... "
                                    print(' ' * last_msg_len, end='\r')
                                    print(progress_message, end='\r', flush=True)
                                    last_msg_len = len(progress_message)
                                    time.sleep(1)
                                print(' ' * last_msg_len, end='\r', flush=True)
                                print("INFO: Cooldown finished.")
                                should_reload = True # 等待结束后需要重新加载
                            else:
                                print("INFO: Cooldown period seems to have just ended according to API. Proceeding.")
                                # 即使刚结束，也最好重新加载一下以获取最新状态
                                should_reload = True

                        except (ValueError, TypeError) as time_err:
                            print(f"WARNING: Error parsing time strings or calculating cooldown: {time_err}. API Data: {mutual_data}. Falling back to default long wait (60s).")
                            time.sleep(60) # 出错时默认等待较短时间，避免卡死太久
                            should_reload = True
                    else:
                        print(f"WARNING: Missing required fields (submit_cd, last_submit, current_time) in API response for cooldown calculation. API Data: {mutual_data}. Assuming not in cooldown for now.")
                        # 即使缺少字段，也可能需要重新加载页面以防万一
                        should_reload = True
            else:
                print(f"WARNING: API request for cooldown status succeeded but response format unexpected. Response: {data}")
                should_reload = True # 响应格式不对，也重新加载一下
        else:
            print(f"WARNING: API request for cooldown status failed with status {api_response.status}. Proceeding cautiously.")
            # API失败，可能页面会卡住，尝试重新加载
            should_reload = True

    except playwright.sync_api.Error as req_err:
        print(f"WARNING: Network error fetching cooldown status: {req_err}. Proceeding cautiously.")
        should_reload = True # 网络错误后尝试重新加载
    except json.JSONDecodeError as json_err:
        print(f"WARNING: Error decoding cooldown API JSON response: {json_err}. Proceeding cautiously.")
        should_reload = True # JSON解析错误后尝试重新加载
    except Exception as api_exc:
        print(f"WARNING: Unexpected error during cooldown check: {api_exc}. Proceeding cautiously.")
        import traceback
        print(traceback.format_exc())
        should_reload = True # 未知错误后尝试重新加载

    # 如果需要重新加载页面
    if should_reload:
        try:
            print("INFO: Reloading page after cooldown check/wait...")
            page.reload(wait_until="domcontentloaded") # 等待DOM加载完成
            print("INFO: Page reloaded successfully.")
        except playwright.sync_api.Error as reload_err:
            print(f"ERROR: Failed to reload page after cooldown handling: {reload_err}. Attempting to continue...")
        except Exception as e:
            print(f"ERROR: Unexpected error during page reload after cooldown handling: {e}. Attempting to continue...")

    print("--- Cooldown check finished ---")

def main():
    config = load_config()
    hw = config['hw']
    usr = str(config['stu_id'])
    pwd = config['stu_pwd']
    debug_mode = config['hacker']['debug']
    num_generate = config['hacker']['num_generate']

    checker_path, generator_path, std_jar_path, hack_dir = calculate_paths(config)

    os.makedirs(hack_dir, exist_ok=True)
    os.makedirs(os.path.join(hack_dir, "waiting"), exist_ok=True) # <--- 创建
    os.makedirs(os.path.join(hack_dir, "passed"), exist_ok=True)  # <--- 创建
    os.makedirs(os.path.join(hack_dir, "rejected"), exist_ok=True)# <--- 创建
    print(f"INFO: Ensured hack directories exist: waiting, passed, rejected inside '{hack_dir}'") # <--- 添加日志

    print("--- Starting Playwright ---")
    with sync_playwright() as p:
        browser = None # 初始化为 None
        homework_id = None
        try:
            browser = p.chromium.launch(headless=not debug_mode)
            print(f"INFO: Browser launched (Headless: {not debug_mode}).")
            page = browser.new_page()
            print("INFO: New page created.")

            # --- 登录和导航 ---
            login(page, usr, pwd)
            print("INFO: Login attempt finished.")
            homework_id = get_course(page, config)
            if homework_id is None: # <--- 健壮性检查
                raise Exception("Failed to retrieve homework_id from get_course.")
            print("INFO: Navigation to mutual test page finished.")

            hack_attempts = 0
            while True:
                hack_attempts += 1
                print(f"\n===== Hack Cycle {hack_attempts} =====")

                sync_lists_and_ensure_waiting_data(hack_dir, std_jar_path, generator_path, num_generate)

                handle_cooldown(page, homework_id)

                should_break, target_alias_name = ready_to_break(page, homework_id)
                if should_break:
                    print("INFO: Hack limit reached for at least one person according to API. Exiting loop.")
                    break
                else:
                    if target_alias_name is not None:
                        print(f"INFO: No hack limit reached yet. Proceeding to hack target: {target_alias_name}")
                    else:
                        print("ERROR: Cannot proceed without a target alias name from ready_to_break. Exiting.")
                        sys.exit(-1)

                stdin_content, stdout_content = select_point(hack_dir, checker_path, std_jar_path)

                if stdin_content is None or stdout_content is None:
                    print(f"INFO: Failed to select a valid data point in cycle {hack_attempts}. Skipping submission and proceeding to next cycle.")
                    # 短暂休眠一下，避免在没有数据时快速空转
                    sleep_duration = random.uniform(3, 6)
                    print(f"INFO: Pausing for {sleep_duration:.1f} seconds before next cycle...")
                    time.sleep(sleep_duration)
                    # 重新加载页面可能不是必须的，但如果担心页面状态过时可以加上
                    try:
                        print("INFO: Reloading page before next cycle attempt...")
                        page.reload(wait_until="domcontentloaded")
                        print("INFO: Page reloaded.")
                    except Exception as reload_err:
                         print(f"WARNING: Failed to reload page before next cycle: {reload_err}")
                    continue # 跳到下一个循环开始，sync 会重新运行

                print(f"INFO: Data point '{THISSTDIN}' selected. Attempting submission to target '{target_alias_name}'.")
                submission_was_blocked_by_cooldown, submission_succeeded = send_point(
                    page,                   # playwright 页面对象
                    homework_id,            # 作业 ID
                    target_alias_name,      # 目标 alias
                    stdin_content,          # <--- 传入选择好的 stdin
                    stdout_content,         # <--- 传入选择好的 stdout
                    hack_dir                # <--- 传入 hack 目录路径
                )

                if submission_succeeded:
                    print(f"INFO: Submission successful for cycle {hack_attempts}.")
                    # Successful submission might trigger cooldown, the check at the start
                    # of the *next* loop should handle the wait.
                elif submission_was_blocked_by_cooldown:
                    print(f"INFO: Submission attempt failed due to cooldown detected by API (code 1617) for cycle {hack_attempts}.")
                    print("INFO: Waiting before next cycle due to cooldown detection...")
                else:
                    # Submission failed for reasons other than cooldown
                    current_data_msg = f"(Last attempted: {THISSTDIN})" if THISSTDIN else "(No data selected/available)"
                    print(f"INFO: Submission attempt failed {current_data_msg} for cycle {hack_attempts}.")

                # 打印当前状态
                print(f"--- Status after cycle {hack_attempts} ---")
                print(f"Successfully Submitted (PASSED): {PASSED}")
                print(f"Rejected/Failed (REJECTED): {REJECTED}")
                try:
                    num_waiting = len([f for f in os.listdir(os.path.join(hack_dir, "waiting")) if f.endswith(".in")])
                    num_passed = len([f for f in os.listdir(os.path.join(hack_dir, "passed")) if f.endswith(".in")])
                    num_rejected = len([f for f in os.listdir(os.path.join(hack_dir, "rejected")) if f.endswith(".in")])
                    print(f"Files in directories: waiting={num_waiting}, passed={num_passed}, rejected={num_rejected}")
                except FileNotFoundError:
                    print("WARNING: Could not count files in directories.")

                # 在每次循环后短暂暂停，避免过于频繁的操作
                print("INFO: Preparing for next cycle...")
                # Add a small random delay before reload
                sleep_duration = random.uniform(2, 5)
                print(f"INFO: Pausing for {sleep_duration:.1f} seconds...")
                time.sleep(sleep_duration)
                try:
                    print("INFO: Reloading page...")
                    page.reload(wait_until="domcontentloaded") # Wait for page to be ready
                    print("INFO: Page reloaded.")
                except playwright.sync_api.Error as reload_err:
                    print(f"ERROR: Failed to reload page: {reload_err}. Attempting to continue...")

            print("--- Hack script finished ---")

        except Exception as e:
            print(f"CRITICAL ERROR in main loop or setup: {e}")
            import traceback
            print(traceback.format_exc())
            print("Attempting to close browser...")
        finally:
            if browser:
                browser.close()
                print("INFO: Browser closed.")

if __name__ == "__main__":
    print("INFO: hack.py script started.")
    main()
    print("INFO: hack.py script finished.")
