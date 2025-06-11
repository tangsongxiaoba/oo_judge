# analyze.py

import argparse
import json
import os
import re
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import random
from collections import Counter

import yaml

"""
动态个性化面向对象课程数据分析脚本 V7.0 (旗舰增强版)

功能:
1.  解析包含课程作业API数据的JSON文件。
2.  [V7.0 新增] 引入学生画像系统 (防御者/攻击者/改进者/DDL战神)，生成高度个性化报告。
3.  [V7.0 新增] 深度挖掘Bug修复数据，分析Bug修复率、攻防得分比，评估开发者责任感。
4.  [V7.0 新增] 详细解析第四单元UML模型检查点，提供针对性反馈。
5.  [V7.0 新增] 整合核心图表为2x2的“综合表现仪表盘”，信息更集中。
6.  深度分析攻防策略演化、提交行为与代码质量的关联。
7.  引入基于房间等级的加权防御分，更科学地评估鲁棒性。
8.  智能生成个人亮点标签，一键洞悉个人特质。
9.  分析提交行为：包括提交次数、提交时间，判断“DDL Fighter”等风格。
10. 生成逐次作业的微观深度报告，包含每次的强测扣分、互测细节。
11. 使用大型语料库，生成每次都不同的、充满洞察与个性的分析报告。
12. 生成多维度、信息丰富的可视化图表。

如何使用:
1.  将你的JSON数据文件（如 result1.txt）与此脚本放在同一目录。
2.  修改下面的 `CONFIG` 字典，特别是 `USER_INFO` 和 `UNIT_MAP`。
3.  确保已安装所需库: pip install pandas matplotlib numpy
4.  运行脚本: python3 analyze.py
"""

# --- 1. 配置区 ---
CONFIG = {
    "FILE_PATH": "tmp.json",
    "USER_INFO": {
        "real_name": None,  # 将被自动填充
        "name": None,       # 将被自动填充
        "student_id": None, # 将从YAML文件读取
        "email": None       # 将被自动填充
    },
    "HOMEWORK_NUM_MAP": {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8,
        '九': 9, '十': 10, '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15
    },
    "UNIT_MAP": {
        "第一单元：表达式求导": list(range(1, 5)),
        "第二单元：多线程电梯": list(range(5, 9)),
        "第三单元：JML规格化设计": list(range(9, 13)),
        "第四单元：UML解析": list(range(13, 16)),
    },
    "FONT_FAMILY": ['WenQuanYi Zen Hei', 'SimHei', 'Microsoft YaHei', 'sans-serif']
}
# --- Matplotlib 设置 ---
plt.rcParams['font.sans-serif'] = CONFIG["FONT_FAMILY"]
plt.rcParams['axes.unicode_minus'] = False


# --- 2. 语料库 (Corpus) V7.0 ---
class ReportCorpus:
    PERSONA_ANALYSIS = {
        "FORTRESS": "你好，{user_name}！欢迎查阅你的OO学习纪实。数据显示，你如同一位‘稳健防御者’，代码质量坚如磐石，在风浪中始终保持着卓越的稳定性。让我们一同回顾这段构筑代码堡垒的旅程。",
        "HUNTER": "你好，{user_name}！这份报告将带你重温OO课程中的高光时刻。你的数据画像显示出一位‘敏锐攻击者’的特质，总能洞察他人代码的微妙之处。让我们看看这位‘猎人’的辉煌战绩。",
        "GRINDER": "欢迎查阅你的OO学习纪实，{user_name}。数据显示，你是一位典型的‘迭代改进者’，通过不懈的努力和反复打磨，实现了技术的持续跃迁。汗水浇灌的花朵，格外鲜艳。",
        "SPRINTER": "你好，{user_name}！欢迎来到你的OO时间胶囊。数据显示，你是一位出色的‘DDL战神’，擅长在压力之下爆发出惊人的效率和创造力。让我们一同回顾那些在deadline前完成的华丽冲刺。",
        "BALANCED": "你好，{user_name}！这份报告将带你穿越时空，回顾你在OO课程中的一段非凡旅程。数据显示你是一位攻防均衡、稳扎稳打的‘全能型选手’。让我们一起揭开数据的面纱，看看汗水与代码交织出的成长画卷。"
    }
    BUG_FIX_ANALYSIS = {
        "HIGH_FIX_RATE": "在Bug修复阶段，你的表现堪称典范。对于被发现的 {total_bugs} 个bug，你成功修复了 {fixed_bugs} 个，修复率高达 {rate:.1f}%。这体现了你作为开发者的责任心与强大的调试纠错能力。",
        "LOW_FIX_RATE": "在Bug修复阶段，数据显示你在被发现的 {total_bugs} 个bug中修复了 {fixed_bugs} 个（修复率 {rate:.1f}%）。那些未修复的bug是宝贵的学习机会，它们提醒我们，修复bug与编写新功能同等重要。",
        "HACK_FOCUSED": "从修复得分来看，你的进攻得分（{hack_score:.2f}）远高于修复失分（{hacked_score:.2f}），得分比为 {ratio:.2f}。这表明你更倾向于通过主动出击寻找他人bug来获取分数，是一位策略清晰的‘攻击型’选手。",
        "FIX_FOCUSED": "从修复得分来看，你通过修复自身bug挽回的分数（{hacked_score:.2f}）占了主导地位（得分比 {ratio:.2f}）。这表明你非常专注于巩固自身代码的质量，是一位沉稳的‘防御型’选手。",
        "NO_BUGS_TO_FIX": "在整个学期的Bug修复环节，你的代码未曾被发现任何可修复的bug，这是一个了不起的成就！"
    }
    UML_ANALYSIS = {
        "PERFECT": "  - UML模型解析: 完美通过所有检查点，展现了你对类图、状态图和顺序图的深刻理解。",
        "IMPERFECT": "  - UML模型解析: 在以下检查点遇到挑战：{issues}。这通常是模型间关联的难点，也是深入理解UML的绝佳机会。"
    }
    # (其他语料库与 V6.0 相同，此处为简洁省略)
    INTRODUCTION = [
        "你好，{user_name}！这份报告将带你穿越时空，回顾你在OO课程中的一段非凡旅程。让我们一起揭开数据的面纱，看看汗水与代码交织出的成长画卷。",
        "欢迎查阅你的OO学习纪实，{user_name}。数据是冰冷的，但它所记录的每一次思考、每一次调试、每一次突破，都充满了温度。",
    ]
    HIGHLIGHTS_INTRO = ["基于你的学期数据，我们为你提炼了以下几个闪亮的个人标签："]
    HIGHLIGHTS_TAGS = {
        "DEFENSE_MASTER": "  - 防御大师: 你的代码在超过75%的互测中保持零失误，堪称固若金汤。",
        "EFFICIENCY_ACE": "  - 效率奇才: 在「{hw_name}」等多次任务中，你以极少的提交次数一次通过，展现了卓越的开发效率。",
        "PERFORMANCE_CHALLENGER": "  - 并发挑战者: 你在第二单元直面了多线程的挑战并成功克服，这是你技术能力的一次重要跃迁。",
        "TOP_SCORER": "  - 学霸本色: 你的强测平均分高达{avg_score:.2f}，位列顶尖水平，展现了强大的硬实力。",
        "HACK_ARTIST": "  - 机会主义黑客: 在「{hw_name}」中，你敏锐地抓住机会，发起了{count}次成功Hack，一战成名。"
    }
    DDL_ANALYSIS = [
        "数据显示，当你的‘DDL指数’较高时，代码出现问题的风险似乎有所增加。这提示我们，对于复杂任务，预留更充足的测试时间可能效果更佳。",
        "你的DDL指数与代码质量之间未发现明显关联，这表明即使在时间压力下，你依然能保持高水平的编码质量，令人钦佩！",
    ]
    DEFENSE_SCORE_ANALYSIS = [
        "考虑到你长期在高强度的A/B房战斗，我们为你计算了加权防御分。你的最终得分是 {score:.2f} (满分100)，这比原始数据更能体现你代码的超凡鲁棒性！",
        "你的加权防御分为 {score:.2f}，表现出色。这证明你的代码不仅逻辑正确，更能经受住来自同行的严苛考验。"
    ]
    # (其他语料库与 V5.0 相同，此处为简洁省略)
    STRONG_TEST_HIGH_SCORE = [
        "强测成绩是代码质量的硬通货，你的表现堪称典范，几乎每次都稳稳拿下。",
        "在强测的考验中，你的代码展现出了教科书级别的稳定性与正确性。",
        "纵观整个学期，你的强测分数曲线如同一条平稳上升的航线，精准而有力。",
        "面对严苛的强测，你交出了一份近乎完美的答卷，实力可见一斑。",
    ]
    STRONG_TEST_IMPERFECTION = [
        "那些非满分的作业，如同寻宝图上的标记，指引着你找到了知识的薄弱点，并最终征服了它们。",
        "每一次小小的失分，都像是磨刀石，让你的编程技艺变得更加锋利。",
        "值得注意的是，你在 {hw_names} 上遇到了挑战，这些经历是成长的最佳催化剂。",
        "这些扣分点 ({issues}) 提醒我们，魔鬼藏在细节中，而你显然已经学会了如何与魔鬼共舞。",
    ]
    PERFORMANCE_ISSUE = [
        "特别是在处理 {hw_names} 时遇到的性能问题（{issue_types}），是你从‘能用’到‘好用’的进阶之战。",
        "RTLE/CTLE 是每个优秀程序员都会遇到的拦路虎，你成功驯服了它，这标志着你对算法复杂度的理解迈上了新台阶。",
    ]
    CONSISTENCY_STABLE = [
        "你的强测成绩方差仅为 {variance:.2f}，表现出惊人的稳定性。如同一位经验丰富的老兵，总能精确命中目标，这背后是扎实的基本功和严谨的编程习惯。",
        "数据展示了你稳健的一面：成绩波动极小（方差{variance:.2f}）。这种持续高质量的输出能力，是大型软件工程中极为宝贵的品质。",
    ]
    CONSISTENCY_VOLATILE = [
        "你的成绩曲线充满了动态与激情（方差{variance:.2f}），时而登顶，时而面临挑战。这说明你勇于探索不同的方法，每一次的波谷都是为了下一次的跃升积蓄力量。",
        "方差 {variance:.2f} 的数据显示，你的学习之路并非一帆风顺，但这恰恰证明了你的坚韧。从 {worst_hw} 的低谷到 {best_hw} 的高峰，你完成了漂亮的逆袭。",
    ]
    MUTUAL_TEST_DEFENSIVE = [
        "你的代码仿佛一座坚固的堡垒，在互测的炮火中屹立不倒，被Hack次数极少。这说明你对边界条件和异常处理有着深刻的理解，防御记录堪称传奇。",
        "在互测环节，你的程序表现出了惊人的鲁棒性，让无数“黑客”无功而返。能守住自己的阵地，本身就是一种强大的实力。",
    ]
    MUTUAL_TEST_OFFENSIVE = [
        "你不仅是位优秀的工程师，更是一位敏锐的“赏金猎人”，在 {hw_names} 中大放异彩，成功定位了 {count} 个bug。你的Hack记录显示了洞察他人代码逻辑漏洞的犀利眼光。",
    ]
    MUTUAL_TEST_BALANCED = [
        "攻防两端，你都游刃有余。既能像骑士一样发起冲锋，又能像守护者一样稳固城池。这种均衡的能力让你在互测的江湖中立于不败之地。",
    ]
    BUG_FIX_INSIGHT = [
        "Bug修复阶段的分数是你辛勤付出的最好证明，每一分都凝聚着你的汗水与智慧。",
        "这部分得分，是你作为一名负责任的开发者的勋章。它证明你不仅能发现问题，更能漂亮地解决问题，完成软件开发的闭环。",
    ]
    UNIT_ANALYSIS = [
        "在 **{unit_name}**，你的平均强测分高达 **{avg_score:.2f}**，展现了你对 {unit_paradigm} 的深刻理解。",
        "回顾 **{unit_name}**，你在互测中成功Hack {hacks} 次，同时代码被攻破 {hacked} 次，攻防战绩斐然，显然你已掌握了 {unit_paradigm} 的核心要领。",
        "**{unit_name}** 对你来说似乎是一个挑战与机遇并存的篇章。虽然遇到了一些困难，但你最终还是攻克了它，这种解决复杂问题的经历远比一帆风顺更加宝贵。",
    ]
    GROWTH_ANALYSIS = [
        "从学期初到学期末，你的进步显而易见。后期作业的平均分（{later_avg:.2f}）明显高于前期（{early_avg:.2f}），这是一条陡峭而坚实的上升曲线。",
        "你的学习轨迹展现了强大的后劲。数据显示，随着课程深入，你的表现愈发稳健，后期平均分达到了 {later_avg:.2f}，证明你已将OO思想内化于心。",
    ]
    SUBMISSION_ANALYSIS_INTRO = [
        "你的提交习惯，是代码之外的另一面镜子，反映了你的工作节奏与策略。",
        "让我们看看你的时间管理艺术：每一次commit和submit，都藏着你的开发故事。",
    ]
    SUBMISSION_MOST = [
        "在「{hw_name}」上，你投入了最多的精力，提交了 {count} 次。毫无疑问，这是你精雕细琢的作品。",
        "「{hw_name}」以 {count} 次提交荣登榜首，可见你在这项作业上付出了巨大的努力，不断迭代优化。",
    ]
    SUBMISSION_LEAST = [
        "而在「{hw_name}」上，你仅用了 {count} 次提交就搞定，展现了惊人的效率和自信！",
        "「{hw_name}」的提交次数最少（{count}次），或许是你思路清晰、一气呵成的典范之作。",
    ]
    HW_ANALYSIS_INTRO = [
        "接下来，让我们深入每一次作业的细节，复盘得失，洞见成长。",
        "每一份作业都是一个独特的关卡，下面是你通关每一关的详细战报。",
    ]
    STYLE_EARLY_BIRD = ["闪电突击型 (Early Bird) - 任务发布后迅速完成，留出充足时间思考人生。"]
    STYLE_WELL_PACED = ["从容不迫型 (Well-Paced) - 稳扎稳打，节奏尽在掌握。"]
    STYLE_DDL_FIGHTER = ["冲刺型选手 (DDL Fighter) - 压力是第一生产力，在截止线前完成华丽冲刺！"]
    STYLE_UNKNOWN = ["时间旅行者 (Time Traveler) - 你的提交时间充满了谜团。"]
    OVERALL_CONCLUSION = [
        "回顾整个学期，你的OO之旅如同一部精彩的成长史诗，充满了挑战、突破与收获。",
        "从最初的基础构建到最终的复杂系统解析，你的技能树被逐一点亮，最终汇成了一片璀璨的星空。",
        "这份数据档案记录了你从一名OO新手到准工程师的蜕变，每一点进步都值得被铭记。",
        "你的学习轨迹并非一帆风顺，但正是那些波折塑造了你解决复杂问题的能力，这比一味的满分更加珍贵。",
    ]
def find_and_update_user_info(student_id, raw_data, config):
    """
    根据学生ID在原始JSON数据中查找姓名和邮箱，并更新CONFIG。
    """
    user_name = None
    user_email = None

    # 优先从互测房间信息中通过 student_id 找到 real_name
    for item in raw_data:
        body_data = item.get("body", {}).get("data", {})
        if not body_data: continue
        if 'mutual_test/room/self' in item.get('url', ''):
            for member in body_data.get('members', []):
                if member.get('student_id') == student_id:
                    user_name = member.get('real_name')
                    break
        if user_name:
            break

    # 再根据找到的姓名，从强测提交记录中找到最可靠的邮箱
    if user_name:
        for item in raw_data:
            body_data = item.get("body", {}).get("data", {})
            if not body_data: continue
            if 'ultimate_test/submit' in item.get('url', ''):
                user_obj = body_data.get('user', {})
                if user_obj.get('name') == user_name:
                    user_email = user_obj.get('email')
                    break
    
    if not user_name:
        raise ValueError(f"错误：在数据文件 {config['FILE_PATH']} 中未找到学号为 {student_id} 的学生信息。")

    # 如果没找到邮箱，则根据学号规则生成一个
    if not user_email:
        user_email = f"{student_id}@buaa.edu.cn"
        print(f"警告：未在数据中找到邮箱，已自动生成: {user_email}")

    # 更新全局配置
    config["USER_INFO"].update({
        "student_id": student_id,
        "real_name": user_name,
        "name": user_name,
        "email": user_email
    })
    print(f"成功识别用户: {user_name} ({student_id})")
    return True

# --- 3. 数据解析与处理 ---
def get_hw_number(hw_name, config):
    match = re.search(r'第(.*)次作业', hw_name or '')
    return config["HOMEWORK_NUM_MAP"].get(match.group(1), 99) if match else 99

def get_unit_from_hw_num(hw_num, config):
    for unit_name, hw_nums in config["UNIT_MAP"].items():
        if hw_num in hw_nums:
            return unit_name
    return "其他"

def is_target_user(data_dict, config):
    if not isinstance(data_dict, dict): return False
    return any(data_dict.get(k) == v for k, v in config["USER_INFO"].items())

def parse_course_data(raw_data, config):
    homework_data = {}
    for item in raw_data:
        match = re.search(r'/homework/(\d+)', item.get('url', ''))
        if not match: continue
        hw_id = match.group(1)
        if hw_id not in homework_data: homework_data[hw_id] = {'id': hw_id}
        body_data = item.get("body", {}).get("data", {})
        if not body_data: continue
        if 'homework' in body_data: homework_data[hw_id].update(body_data['homework'])
        if 'public_test' in item['url'] and 'public_test' in body_data:
            pt_data = body_data['public_test']
            homework_data[hw_id].update({
                'public_test_used_times': pt_data.get('used_times'),
                'public_test_start_time': pt_data.get('start_time'),
                'public_test_end_time': pt_data.get('end_time'),
                'public_test_last_submit': pt_data.get('last_submit'),
            })
        if 'ultimate_test/submit' in item['url'] and is_target_user(body_data.get('user', {}), config):
            homework_data[hw_id]['strong_test_score'] = body_data.get('score')
            results = body_data.get('results', [])
            issue_counter = Counter(p['message'] for p in results if p.get('message') != 'ACCEPTED')
            homework_data[hw_id]['strong_test_issues'] = dict(issue_counter) if issue_counter else {}
            if 'uml_results' in body_data and body_data['uml_results']:
                homework_data[hw_id]['uml_detailed_results'] = body_data['uml_results']
        elif 'mutual_test/room/self' in item['url']:
            for member in body_data.get('members', []):
                if is_target_user(member, config):
                    homework_data[hw_id].update({
                        'alias_name': member.get('alias_name_string'),
                        'hack_success': int(member.get('hack', {}).get('success', 0)),
                        'hacked_success': int(member.get('hacked', {}).get('success', 0)),
                        'room_level': body_data.get('mutual_test', {}).get('level', 'N/A').upper()
                    })
                    break
        elif 'bug_fix' in item['url'] and 'personal' in body_data:
            personal = body_data['personal']
            hacked_info = personal.get('hacked', {})
            hack_info = personal.get('hack', {})
            homework_data[hw_id]['bug_fix_details'] = {
                'hack_score': hack_info.get('score', 0),
                'hacked_score': hacked_info.get('score', 0),
                'hacked_count': hacked_info.get('count', 0),
                'unfixed_count': hacked_info.get('unfixed', 0)
            }
    processed_homeworks = []
    for hw_id, data in homework_data.items():
        if 'name' in data:
            hw_num = get_hw_number(data['name'], config)
            data['hw_num'] = hw_num
            data['unit'] = get_unit_from_hw_num(hw_num, config)
            processed_homeworks.append(data)
    return sorted(processed_homeworks, key=lambda x: x['hw_num'])

# --- 4. 数据预处理与计算 ---
def preprocess_and_calculate_metrics(df):
    """对DataFrame进行预处理，计算所有需要的衍生指标"""
    # 时间转换
    for col in ['public_test_start_time', 'public_test_end_time', 'public_test_last_submit']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')

    # 计算DDL指数
    durations = (df['public_test_end_time'] - df['public_test_start_time']).dt.total_seconds()
    offsets = (df['public_test_last_submit'] - df['public_test_start_time']).dt.total_seconds()
    df['ddl_index'] = (offsets / durations).fillna(0.5).clip(0, 1)

    # 计算攻防指数
    df['offense_defense_ratio'] = (df['hack_success'].fillna(0) + 1) / (df['hacked_success'].fillna(0) + 1)

    # 强测扣分总数
    df['strong_test_deduction_count'] = df['strong_test_issues'].apply(
        lambda x: sum(x.values()) if isinstance(x, dict) else 0)

    # 加权防御分
    room_weights = {'A': 10, 'B': 8, 'C': 5}
    df['weighted_defense_deduction'] = df.apply(
        lambda row: row['hacked_success'] * room_weights.get(row.get('room_level'), 3), axis=1)

    df['bug_fix_details'] = df['bug_fix_details'].apply(lambda x: x if isinstance(x, dict) else {})

    # Bug修复相关指标
    df['bug_fix_details'] = df['bug_fix_details'].fillna(value={})
    df['bug_fix_hacked_count'] = df['bug_fix_details'].apply(lambda x: x.get('hacked_count', 0))
    df['bug_fix_unfixed_count'] = df['bug_fix_details'].apply(lambda x: x.get('unfixed_count', 0))
    df['bug_fix_hack_score'] = df['bug_fix_details'].apply(lambda x: x.get('hack_score', 0))
    df['bug_fix_hacked_score'] = df['bug_fix_details'].apply(lambda x: x.get('hacked_score', 0))
    
    # Bug修复率
    with np.errstate(divide='ignore', invalid='ignore'):
        df['bug_fix_rate'] = ((df['bug_fix_hacked_count'] - df['bug_fix_unfixed_count']) / df['bug_fix_hacked_count']) * 100
    df['bug_fix_rate'] = df['bug_fix_rate'].fillna(np.nan) # Keep NaN for 0/0 cases

    # Hack/Fix得分比
    df['hack_fix_score_ratio'] = (df['bug_fix_hack_score'] + 0.1) / (df['bug_fix_hacked_score'] + 0.1)

    return df


# --- 5. 可视化模块 V7.0 ---
def create_visualizations(df, user_name, config):
    """主函数，调用所有可视化生成函数"""
    print("\n正在生成可视化图表，请稍候...")
    create_performance_dashboard(df, user_name)
    create_unit_radar_chart(df, user_name, config)
    print("所有分析报告与图表已生成完毕！")

def create_performance_dashboard(df, user_name):
    """[V7.0 新增] 生成2x2的综合表现仪表盘"""
    fig, axes = plt.subplots(2, 2, figsize=(20, 14))
    fig.suptitle(f'{user_name} - OO课程综合表现仪表盘 (V7.0)', fontsize=24, weight='bold')

    # --- 图1: 强测成绩趋势 ---
    ax1 = axes[0, 0]
    df_strong = df.dropna(subset=['strong_test_score'])
    if not df_strong.empty:
        ax1.plot(df_strong['name'], df_strong['strong_test_score'], marker='o', linestyle='-', color='b', label='强测分数')
        ax1.axhline(y=100, color='r', linestyle='--', label='满分线 (100)', alpha=0.7)
        ax1.set_title('学期强测成绩变化趋势', fontsize=16)
        ax1.set_xlabel('作业', fontsize=12)
        ax1.set_ylabel('分数', fontsize=12)
        ax1.tick_params(axis='x', rotation=45, labelsize=9)
        ax1.grid(True, which='both', linestyle='--', linewidth=0.5)
        ax1.legend()
        ax1.set_ylim(bottom=min(80, df_strong['strong_test_score'].min() - 5 if not df_strong.empty else 80), top=105)

    # --- 图2: DDL指数与代码质量关联 ---
    ax2 = axes[0, 1]
    analysis_df = df.dropna(subset=['ddl_index', 'strong_test_deduction_count', 'hacked_success'])
    if not analysis_df.empty:
        color1 = 'tab:red'
        ax2.set_xlabel('DDL 指数 (越接近1，越晚提交)', fontsize=12)
        ax2.set_ylabel('强测扣分点数量', color=color1, fontsize=12)
        ax2.scatter(analysis_df['ddl_index'], analysis_df['strong_test_deduction_count'],
                    alpha=0.6, color=color1, label='强测扣分点')
        ax2.tick_params(axis='y', labelcolor=color1)
        
        ax2_twin = ax2.twinx()
        color2 = 'tab:blue'
        ax2_twin.set_ylabel('被Hack次数', color=color2, fontsize=12)
        ax2_twin.scatter(analysis_df['ddl_index'], analysis_df['hacked_success'],
                         marker='x', alpha=0.6, color=color2, label='被Hack次数')
        ax2_twin.tick_params(axis='y', labelcolor=color2)
        ax2.set_title('提交时间与代码质量关联', fontsize=16)
    
    # --- 图3: 互测攻防策略演化 ---
    ax3 = axes[1, 0]
    mutual_df = df[df.get('has_mutual_test', pd.Series(False))].dropna(subset=['offense_defense_ratio'])
    if not mutual_df.empty:
        ax3.plot(mutual_df['name'], mutual_df['offense_defense_ratio'], marker='^', linestyle=':', color='purple', label='攻防指数')
        ax3.axhline(y=1, color='grey', linestyle='--', label='攻防平衡线 (指数=1)')
        ax3.set_yscale('log')
        ax3.set_title('互测攻防策略演化 (对数坐标)', fontsize=16)
        ax3.set_xlabel('作业', fontsize=12)
        ax3.set_ylabel('攻防指数 (Hack+1)/(Hacked+1)', fontsize=12)
        ax3.tick_params(axis='x', rotation=45, labelsize=9)
        ax3.grid(True, which='both', linestyle='--', linewidth=0.5)
        ax3.legend()

    # --- 图4: Bug修复率分析 ---
    ax4 = axes[1, 1]
    bugfix_df = df.dropna(subset=['bug_fix_rate'])
    if not bugfix_df.empty:
        bars = ax4.bar(bugfix_df['name'], bugfix_df['bug_fix_rate'], color='teal', alpha=0.8)
        ax4.axhline(y=100, color='green', linestyle='--', label='100%修复', alpha=0.7)
        ax4.set_title('Bug修复率', fontsize=16)
        ax4.set_xlabel('作业', fontsize=12)
        ax4.set_ylabel('修复率 (%)', fontsize=12)
        ax4.set_ylim(0, 110)
        ax4.tick_params(axis='x', rotation=45, labelsize=9)
        ax4.grid(axis='y', linestyle='--', linewidth=0.5)
        ax4.legend()
        for bar in bars:
            yval = bar.get_height()
            if yval > 0:
                ax4.text(bar.get_x() + bar.get_width()/2.0, yval, f'{yval:.0f}%', va='bottom', ha='center')
    else:
        ax4.text(0.5, 0.5, '未发现可供分析的Bug修复数据', ha='center', va='center', fontsize=14, color='gray')

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.show()

def create_unit_radar_chart(df, user_name, config):
    """[V7.0 保持独立] 生成各单元能力雷达图"""
    unit_stats = {}
    for unit_name in config["UNIT_MAP"].keys():
        unit_df = df[df['unit'] == unit_name]
        if not unit_df.empty:
            unit_stats[unit_name] = {
                '强测表现': unit_df['strong_test_score'].mean(skipna=True),
                '进攻能力': unit_df['hack_success'].sum(skipna=True),
                '防守能力': unit_df['hacked_success'].sum(skipna=True)
            }
    valid_units = {k: v for k, v in unit_stats.items() if pd.notna(v.get('强测表现'))}
    if len(valid_units) >= 3:
        labels = list(next(iter(valid_units.values())).keys())
        stats_list = [list(d.values()) for d in valid_units.values()]
        stats_array = np.array(stats_list)
        # Normalize: '防守能力' is inverted (lower is better)
        max_hacked = np.nanmax(stats_array[:, 2])
        if max_hacked > 0: stats_array[:, 2] = max_hacked - stats_array[:, 2] 
        else: stats_array[:, 2] = 1 # Avoid all zeros if no one was ever hacked
        
        # Normalize all stats
        with np.errstate(divide='ignore', invalid='ignore'):
            max_vals = np.nanmax(stats_array, axis=0)
            max_vals[max_vals == 0] = 1 # Avoid division by zero
            normalized_stats = stats_array / max_vals
        
        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        angles += angles[:1]
        
        fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True))
        for i, (unit_name, data) in enumerate(valid_units.items()):
            values = normalized_stats[i].tolist()
            values += values[:1]
            ax.plot(angles, values, 'o-', linewidth=2, label=re.sub(r'：.*', '', unit_name))
            ax.fill(angles, values, alpha=0.25)
        
        ax.set_thetagrids(np.degrees(angles[:-1]), labels)
        ax.set_title(f'{user_name} - 各单元能力雷达图', size=20, color='blue', y=1.1)
        ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1))
        plt.show()

# --- 6. 动态报告生成器 V7.0 ---
def analyze_submission_style(hw_row):
    start, end, last_submit = hw_row.get('public_test_start_time'), hw_row.get('public_test_end_time'), hw_row.get('public_test_last_submit')
    if pd.isna(start) or pd.isna(end) or pd.isna(last_submit): return ReportCorpus.STYLE_UNKNOWN[0]
    total_duration = end - start
    if total_duration.total_seconds() <= 0: return ReportCorpus.STYLE_UNKNOWN[0]
    ratio = (last_submit - start).total_seconds() / total_duration.total_seconds()
    if ratio <= 0.2: return random.choice(ReportCorpus.STYLE_EARLY_BIRD)
    elif ratio >= 0.8: return random.choice(ReportCorpus.STYLE_DDL_FIGHTER)
    else: return random.choice(ReportCorpus.STYLE_WELL_PACED)

def generate_highlights(df):
    highlights = []
    # 防御大师
    mutual_df = df[df.get('has_mutual_test', pd.Series(False))].dropna(subset=['hacked_success'])
    if not mutual_df.empty and (mutual_df['hacked_success'] == 0).mean() >= 0.75:
        highlights.append(ReportCorpus.HIGHLIGHTS_TAGS["DEFENSE_MASTER"])
    # 效率奇才
    submit_times_df = df.dropna(subset=['public_test_used_times'])
    if not submit_times_df.empty:
        min_submit_row = submit_times_df.loc[submit_times_df['public_test_used_times'].idxmin()]
        if min_submit_row['public_test_used_times'] <= 2:
             highlights.append(ReportCorpus.HIGHLIGHTS_TAGS["EFFICIENCY_ACE"].format(hw_name=min_submit_row['name']))
    # 并发挑战者
    unit2_df = df[df['unit'].str.contains("第二单元", na=False)]
    if not unit2_df.empty and unit2_df['strong_test_score'].mean() > 95:
        if any("TIME" in str(s) for s in unit2_df['strong_test_issues']):
            highlights.append(ReportCorpus.HIGHLIGHTS_TAGS["PERFORMANCE_CHALLENGER"])
    # 学霸本色
    strong_scores = df['strong_test_score'].dropna()
    if not strong_scores.empty and strong_scores.mean() > 98:
        highlights.append(ReportCorpus.HIGHLIGHTS_TAGS["TOP_SCORER"].format(avg_score=strong_scores.mean()))
    # 机会主义黑客
    if not mutual_df.empty:
        max_hack_row = mutual_df.loc[mutual_df['hack_success'].idxmax()]
        if max_hack_row['hack_success'] >= 10:
            highlights.append(ReportCorpus.HIGHLIGHTS_TAGS["HACK_ARTIST"].format(hw_name=max_hack_row['name'], count=int(max_hack_row['hack_success'])))
    
    return highlights[:3]

def identify_student_persona(df):
    """[V7.0 新增] 根据数据特征识别学生画像"""
    if df.empty: return "BALANCED"
    
    mutual_df = df[df.get('has_mutual_test', pd.Series(False))]
    # DDL战神: 平均提交时间非常靠后
    if df['ddl_index'].dropna().mean() > 0.8:
        return "SPRINTER"
    # 敏锐攻击者: 总hack数很多
    if not mutual_df.empty and mutual_df['hack_success'].sum() > 25:
        return "HUNTER"
    # 稳健防御者: 被hack数极少且强测稳定
    if (not mutual_df.empty and mutual_df['hacked_success'].sum() <= 3) and df['strong_test_score'].var() < 10:
        return "FORTRESS"
    # 迭代改进者: 提交次数很多
    if df['public_test_used_times'].dropna().mean() > 6:
        return "GRINDER"
        
    return "BALANCED"

def format_uml_analysis(hw_row):
    """[V7.0 新增] 格式化UML分析结果"""
    uml_results = hw_row.get('uml_detailed_results', [])
    if not uml_results: return ""
    
    failed_checks = [r['name'] for r in uml_results if r['message'] != 'ACCEPTED']
    
    if not failed_checks:
        return ReportCorpus.UML_ANALYSIS["PERFECT"]
    else:
        return ReportCorpus.UML_ANALYSIS["IMPERFECT"].format(issues=', '.join(failed_checks))

def generate_dynamic_report(df, user_name, config):
    print("\n" + "="*80)
    print(f" {user_name} - OO课程动态学习轨迹报告 V7.0 ".center(80, "="))
    print("="*80)
    
    if df.empty:
        print("\n未找到该学生的有效作业数据，请检查配置文件。")
        return

    # --- 0. 个性化开场白 ---
    persona = identify_student_persona(df)
    print("\n" + ReportCorpus.PERSONA_ANALYSIS[persona].format(user_name=user_name))

    # --- 1. 个人亮点标签 ---
    highlights = generate_highlights(df)
    if highlights:
        print("\n" + "--- 1. 个人亮点标签 ---".center(70))
        print(random.choice(ReportCorpus.HIGHLIGHTS_INTRO))
        for tag in highlights:
            print(tag)

    # --- 2. 宏观学期表现与深度洞察 ---
    print("\n" + "--- 2. 宏观学期表现与深度洞察 ---".center(70))
    strong_scores = df['strong_test_score'].dropna()
    if not strong_scores.empty:
        avg_score, var_score = strong_scores.mean(), strong_scores.var()
        print(f"强测表现: 平均分 {avg_score:.2f} | 稳定性 (方差) {var_score:.2f}")
    
    mutual_df = df[df.get('has_mutual_test', pd.Series(False))].dropna(subset=['hack_success', 'hacked_success'])
    if not mutual_df.empty:
        total_hacks, total_hacked = mutual_df['hack_success'].sum(), mutual_df['hacked_success'].sum()
        print(f"互测战绩: 成功Hack {int(total_hacks)} 次 | 被Hack {int(total_hacked)} 次")
        
        total_weighted_deduction = mutual_df['weighted_defense_deduction'].sum()
        max_possible_deduction = mutual_df.shape[0] * 10 # 假设每个互测作业的防御分满分是10
        defense_score = 100 - (total_weighted_deduction / (max_possible_deduction * 10) * 100) if max_possible_deduction > 0 else 100
        print(random.choice(ReportCorpus.DEFENSE_SCORE_ANALYSIS).format(score=max(0, defense_score)))
    
    # --- 3. 开发者责任感与调试能力 (Bug修复) ---
    print("\n" + "--- 3. 开发者责任感与调试能力 (Bug修复) ---".center(70))
    bugfix_df = df.dropna(subset=['bug_fix_hacked_count'])
    total_bugs = bugfix_df['bug_fix_hacked_count'].sum()
    if total_bugs > 0:
        unfixed_bugs = bugfix_df['bug_fix_unfixed_count'].sum()
        fixed_bugs = total_bugs - unfixed_bugs
        fix_rate = (fixed_bugs / total_bugs) * 100 if total_bugs > 0 else 100
        
        if fix_rate > 80:
            print(ReportCorpus.BUG_FIX_ANALYSIS["HIGH_FIX_RATE"].format(total_bugs=int(total_bugs), fixed_bugs=int(fixed_bugs), rate=fix_rate))
        else:
            print(ReportCorpus.BUG_FIX_ANALYSIS["LOW_FIX_RATE"].format(total_bugs=int(total_bugs), fixed_bugs=int(fixed_bugs), rate=fix_rate))
            
        total_hack_score = bugfix_df['bug_fix_hack_score'].sum()
        total_hacked_score = bugfix_df['bug_fix_hacked_score'].sum()
        if total_hack_score + total_hacked_score > 0:
            ratio = (total_hack_score + 0.1) / (total_hacked_score + 0.1)
            if ratio > 1.5:
                 print(ReportCorpus.BUG_FIX_ANALYSIS["HACK_FOCUSED"].format(hack_score=total_hack_score, hacked_score=total_hacked_score, ratio=ratio))
            elif ratio < 0.7:
                 print(ReportCorpus.BUG_FIX_ANALYSIS["FIX_FOCUSED"].format(hack_score=total_hack_score, hacked_score=total_hacked_score, ratio=ratio))
    else:
        print(ReportCorpus.BUG_FIX_ANALYSIS["NO_BUGS_TO_FIX"])

    # --- 4. 单元深度与成长轨迹 ---
    print("\n" + "--- 4. 单元深度与成长轨迹 ---".center(70))
    unit_paradigms = {"第一单元": "递归下降", "第二单元": "多线程", "第三单元": "JML规格", "第四单元": "UML解析"}
    for unit_name_full in config["UNIT_MAP"].keys():
        unit_df = df[df['unit'] == unit_name_full]
        unit_name_short = re.sub(r'：.*', '', unit_name_full)
        if not unit_df.empty and pd.notna(unit_df['strong_test_score'].mean()):
            print(f"  - {unit_name_short}: 强测均分 {unit_df['strong_test_score'].mean():.2f}, "
                  f"Hack/Hacked: {int(unit_df['hack_success'].sum())}/{int(unit_df['hacked_success'].sum())}")
    if len(strong_scores) > 8:
        early_avg, later_avg = strong_scores.iloc[:len(strong_scores)//2].mean(), strong_scores.iloc[len(strong_scores)//2:].mean()
        if later_avg > early_avg:
            print(random.choice(ReportCorpus.GROWTH_ANALYSIS).format(early_avg=early_avg, later_avg=later_avg))
            
    # --- 5. 提交行为与风险分析 ---
    print("\n" + "--- 5. 提交行为与风险分析 ---".center(70))
    submit_times_df = df.dropna(subset=['public_test_used_times'])
    if not submit_times_df.empty:
        total_submissions = submit_times_df['public_test_used_times'].sum()
        print(f"本学期你共提交 {int(total_submissions)} 次代码。")
        most_submitted, least_submitted = submit_times_df.loc[submit_times_df['public_test_used_times'].idxmax()], submit_times_df.loc[submit_times_df['public_test_used_times'].idxmin()]
        print(random.choice(ReportCorpus.SUBMISSION_MOST).format(hw_name=most_submitted['name'], count=int(most_submitted['public_test_used_times'])))
        print(random.choice(ReportCorpus.SUBMISSION_LEAST).format(hw_name=least_submitted['name'], count=int(least_submitted['public_test_used_times'])))
    
    ddl_risk_df = df[(df['ddl_index'] > 0.9) & ((df['strong_test_deduction_count'] > 0) | (df['hacked_success'] > 0))]
    if len(ddl_risk_df) > len(df) * 0.1:
        print(random.choice(ReportCorpus.DDL_ANALYSIS))

    # --- 6. 逐次作业深度解析 ---
    print("\n" + "--- 6. 逐次作业深度解析 ---".center(70))
    for _, hw in df.iterrows():
        print(f"\n--- {hw['name']} ---")
        if pd.notna(hw.get('strong_test_score')):
            score_str = f"  - 强测: {hw.get('strong_test_score'):.2f}"
            if hw.get('strong_test_deduction_count', 0) > 0:
                issue_str = ", ".join([f"{k}({v}次)" for k,v in hw.get('strong_test_issues', {}).items()])
                score_str += f" | 扣分: {issue_str}"
            print(score_str)
        if hw.get('has_mutual_test') and pd.notna(hw.get('hack_success')):
            print(f"  - 互测: 在 {hw.get('room_level', '?')} 房化身「{hw.get('alias_name', '?')}」，Hack {int(hw.get('hack_success'))} | Hacked {int(hw.get('hacked_success'))}")
        
        # [V7.0 新增] UML 详细分析
        if hw['unit'].startswith("第四单元"):
            print(format_uml_analysis(hw))
            
        print(f"  - 提交: {analyze_submission_style(hw)}")

    # --- 7. 总结 ---
    print("\n" + "="*80)
    print(" 学期旅程总结 ".center(80, "="))
    print("="*80)
    print(random.choice(ReportCorpus.OVERALL_CONCLUSION))

# --- 7. 主执行逻辑 ---
def main(student_id):
    try:
        if not student_id or not student_id.isdigit():
            raise ValueError(f"错误: '{CONFIG['YAML_CONFIG_PATH']}' 中未找到有效的 'stu_id'。")

        # 2. 加载原始 JSON 数据
        file_path = Path(CONFIG["FILE_PATH"])
        if not file_path.exists(): raise FileNotFoundError(f"错误: 未找到数据文件 '{file_path}'。")
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_json_data = json.load(f)
        
        # 3. 自动查找用户信息并更新CONFIG
        find_and_update_user_info(student_id, raw_json_data, CONFIG)

        # 4. 执行原有的数据解析和分析流程
        # 注意：parse_course_data现在需要传入原始数据，避免重复读取文件
        raw_df = pd.DataFrame(parse_course_data(raw_json_data, CONFIG))
        df = preprocess_and_calculate_metrics(raw_df)
        
        user_display_name = CONFIG["USER_INFO"].get("real_name")

        generate_dynamic_report(df, user_display_name, CONFIG)
        create_visualizations(df, user_display_name, CONFIG)

    except (FileNotFoundError, ValueError) as e:
        print(e)
    except Exception as e:
        print(f"\n处理数据时发生未知错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="通过 Playwright 自动捕获北航OO课程网站的API数据。")
    
    # 添加必要的命令行参数：学号和密码
    parser.add_argument("student_id", help="用于登录的学号 (例如: 23371265)")    
    # 解析命令行传入的参数
    args = parser.parse_args()
    
    # 运行主异步函数，并将解析到的参数传递进去
    main(args.student_id)