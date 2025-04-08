#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shutil
import re
import sys
import yaml # <-- 导入 PyYAML 库

# --- 全局常量 ---
CONFIG_FILE = "config.yml"

# --- 函数：加载配置 ---
def load_config(config_path):
    """Loads configuration from a YAML file."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) # 使用 safe_load 更安全
            # 基本的验证 (可以根据需要添加更详细的检查)
            if not config:
                raise ValueError("配置文件为空或格式错误。")
            if 'logs_dir' not in config or \
               'hacker' not in config or 'waiting_dir' not in config['hacker'] or \
               'update' not in config or 'log_prefix' not in config['update'] or \
               'log_suffix' not in config['update'] or \
               'target_line_prefix' not in config['update']:
                raise KeyError("配置文件缺少必要的键。请检查 config.yml 结构。")
            return config
    except FileNotFoundError:
        print(f"错误：配置文件 '{config_path}' 未找到。")
        sys.exit(1) # 退出脚本
    except yaml.YAMLError as e:
        print(f"错误：解析配置文件 '{config_path}' 时出错: {e}")
        sys.exit(1)
    except (KeyError, ValueError) as e:
        print(f"错误：配置文件 '{config_path}' 内容无效: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"错误：加载配置文件时发生意外错误: {e}")
        sys.exit(1)

# --- 主逻辑 ---
def process_logs(config):
    """
    处理 logs 目录下的 error 日志文件。
    使用从 config 字典中获取的配置。
    """
    # --- 从配置中获取参数 ---
    logs_dir = config['logs_dir']
    hack_waiting_dir = config['hacker']['waiting_dir']
    log_prefix = config['update']['log_prefix']
    log_suffix = config['update']['log_suffix']
    target_line_prefix = config['update']['target_line_prefix']

    # 动态构建正则表达式
    try:
        path_extract_pattern = re.compile(
            r"^\s*" + re.escape(target_line_prefix) + r"\s*(.*?)\s*$"
        )
    except re.error as e:
        print(f"错误：根据配置文件中的 target_line_prefix '{target_line_prefix}' 构建正则表达式失败: {e}")
        sys.exit(1)

    print(f"开始扫描目录: {logs_dir}")
    print(f"目标目录: {hack_waiting_dir}")
    print(f"日志文件筛选: {log_prefix}*{log_suffix}")
    print(f"查找行前缀: '{target_line_prefix}'")

    # 1. 确保目标目录存在
    try:
        os.makedirs(hack_waiting_dir, exist_ok=True)
        print(f"确保目标目录存在: {hack_waiting_dir}")
    except OSError as e:
        print(f"错误：无法创建目标目录 {hack_waiting_dir}: {e}")
        return # 如果无法创建目录，则无法继续

    processed_count = 0
    deleted_count = 0
    error_count = 0

    # 2. 遍历 logs 目录
    if not os.path.isdir(logs_dir):
        print(f"错误：日志目录 '{logs_dir}' (来自配置) 不存在或不是一个目录。")
        return

    for filename in os.listdir(logs_dir):
        # 3. 检查文件名是否符合前缀和后缀
        if filename.startswith(log_prefix) and filename.endswith(log_suffix):
            log_file_path = os.path.join(logs_dir, filename)

            if not os.path.isfile(log_file_path):
                continue

            print(f"\n正在处理日志文件: {log_file_path}")
            input_data_path = None
            found_line = False

            # 4. 打开并逐行读取日志文件
            try:
                with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f: # 添加 errors='ignore' 以防编码问题
                    for line_num, line in enumerate(f, 1):
                        match = path_extract_pattern.match(line)
                        if match:
                            # 5. 提取文件路径
                            input_data_path = match.group(1).strip()
                            print(f"  在第 {line_num} 行找到目标行，提取路径: {input_data_path}")
                            found_line = True
                            break
            except FileNotFoundError:
                print(f"  错误：尝试读取时日志文件 {log_file_path} 消失了？")
                error_count += 1
                continue
            except Exception as e:
                print(f"  错误：读取日志文件 {log_file_path} 时发生错误: {e}")
                error_count += 1
                continue

            # 6. 如果找到了路径，则处理文件
            if found_line and input_data_path:
                # 7. 检查提取到的输入文件是否存在
                if os.path.isfile(input_data_path):
                    try:
                        # 8. 构建目标文件路径并修改后缀
                        base_name = os.path.basename(input_data_path)
                        name_without_ext, _ = os.path.splitext(base_name)
                        dest_filename = name_without_ext + ".in"
                        dest_path = os.path.join(hack_waiting_dir, dest_filename)

                        # 9. 复制文件
                        shutil.copy2(input_data_path, dest_path)
                        print(f"  成功复制文件 '{input_data_path}' 到 '{dest_path}'")
                        processed_count += 1

                        # 10. 删除原始的 log 文件
                        try:
                            os.remove(log_file_path)
                            print(f"  成功删除日志文件: {log_file_path}")
                            deleted_count += 1
                        except OSError as e:
                            print(f"  警告：复制成功，但删除日志文件 {log_file_path} 失败: {e}")
                            error_count += 1

                    except Exception as e:
                        print(f"  错误：处理文件 {input_data_path} (来自 {log_file_path}) 时发生错误: {e}")
                        error_count += 1
                else:
                    print(f"  警告：日志文件中指定的输入文件不存在: '{input_data_path}'。跳过复制和删除日志。")
                    error_count += 1
            elif found_line and not input_data_path:
                 print(f"  警告：在日志 {log_file_path} 中找到了匹配行，但未能提取有效路径。")
                 error_count += 1
            else:
                print(f"  未在日志文件 {log_file_path} 中找到以 '{target_line_prefix}' 开头的行。该日志文件不会被删除。")

    print(f"\n--- 处理完成 ---")
    print(f"成功复制并重命名文件数: {processed_count}")
    print(f"成功删除日志文件数: {deleted_count}")
    print(f"处理过程中遇到警告/错误数: {error_count}")

if __name__ == "__main__":
    # 加载配置
    config = load_config(CONFIG_FILE)
    # 运行主逻辑，传入配置
    process_logs(config)