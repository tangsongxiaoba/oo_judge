import pandas as pd
import numpy as np
import re

def parse_table(table_text):
    """解析表格格式文本，提取jar包性能指标"""
    lines = table_text.strip().split('\n')
    
    # 提取表头
    header_line = lines[0]
    headers = re.findall(r'\b(\w+(?:\(\w+\))?)\s*', header_line)
    headers = [h.strip() for h in headers if h.strip()]
    
    # 跳过表头和分隔线
    data_rows = []
    for line in lines[2:]:  # 跳过表头和第一条分隔线
        if line.startswith('----'):  # 跳过分隔线
            continue
        
        # 提取每行的数据
        row_data = line.split('|') if '|' in line else re.findall(r'(\S+\.\S+|\S+)\s+', line)
        row_data = [item.strip() for item in row_data if item.strip()]
        
        if len(row_data) >= 8:  # 确保有足够的数据列
            jar_info = {
                'JAR': row_data[0],
                'Status': row_data[1],
                'Score': float(row_data[2]),
                'T_final': float(row_data[3]),
                'WT': float(row_data[4]),
                'W': float(row_data[5]),
                'CPU(s)': float(row_data[6]),
                'Wall(s)': float(row_data[7])
            }
            data_rows.append(jar_info)
    
    return data_rows

def calculate_scores(data):
    """计算所有jar包的得分"""
    # 提取性能指标
    T_run = [item['T_final'] for item in data]
    WT = [item['WT'] for item in data]
    W = [item['W'] for item in data]
    
    # 计算平均值、最大值、最小值
    T_run_avg = np.mean(T_run)
    T_run_max = np.max(T_run)
    T_run_min = np.min(T_run)
    
    WT_avg = np.mean(WT)
    WT_max = np.max(WT)
    WT_min = np.min(WT)
    
    W_avg = np.mean(W)
    W_max = np.max(W)
    W_min = np.min(W)
    
    # 设置 p 值
    p = 0.10
    
    # 计算 base_min 和 base_max
    T_run_base_min = p * T_run_avg + (1 - p) * T_run_min
    T_run_base_max = p * T_run_avg + (1 - p) * T_run_max
    
    WT_base_min = p * WT_avg + (1 - p) * WT_min
    WT_base_max = p * WT_avg + (1 - p) * WT_max
    
    W_base_min = p * W_avg + (1 - p) * W_min
    W_base_max = p * W_avg + (1 - p) * W_max
    
    # 计算每个jar包的得分
    calculated_scores = []
    for i in range(len(data)):
        # 对于T_run，越小越好，需要反转评分
        r_T_run = 1 - ((T_run[i] - T_run_base_min) / (T_run_base_max - T_run_base_min))
        r_T_run = min(max(r_T_run, 0), 1)
        
        # 对于WT，越大越好
        r_WT = 1 - ((WT[i] - WT_base_min) / (WT_base_max - WT_base_min))
        r_WT = min(max(r_WT, 0), 1)
        
        # 对于W，越小越好，需要反转评分
        r_W = 1 - ((W[i] - W_base_min) / (W_base_max - W_base_min))
        r_W = min(max(r_W, 0), 1)
        
        # 计算最终得分
        score = 15 * (0.3 * r_T_run + 0.3 * r_WT + 0.4 * r_W)
        calculated_scores.append(score)
    
    return calculated_scores

import sys

input_lines = sys.stdin.readlines()

# 示例输入文本
input_text = ''.join(input_lines)

# 解析表格
jar_data = parse_table(input_text)
print("解析后的数据：")
for jar in jar_data:
    print(jar)

# 计算得分
scores = calculate_scores(jar_data)

# 显示结果
print("\n重新计算后的得分：")
for i, jar in enumerate(jar_data):
    print(f"{jar['JAR']}: {scores[i]:.3f} (原始得分: {jar['Score']})")
