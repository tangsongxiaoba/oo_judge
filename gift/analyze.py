# analyze.py

import argparse
import json
import re
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import random
from collections import Counter

from pygments import highlight
import yaml

"""
动态个性化面向对象课程数据分析脚本 V8.6 (语料增强版)

功能:
1.  [V8.6 优化] 优化语料库，对部分语句进行扩写与润色，引入更多变量，报告更具个性化与生动性。
2.  [V8.5 新增] 新增互测博弈过程分析，洞察Hack时机（闪电战/偷塔）、目标选择（集火/广撒网）等高级策略。
3.  [V8.5 新增] 引入基于同房间数据的相对表现分析，新增“风暴幸存者”、“精准打击者”、“战术大师”等情景化标签。
4.  解析包含课程作业API数据的JSON文件。
5.  [V8.0 功能] 新增“王者归来”、“漏洞修复专家”等亮点标签，深度挖掘成长与责任感。
6.  [V8.0 功能] 新增性能瓶颈（RTLE/CTLE）专项分析，尤其关注第二单元并发挑战。
7.  [V8.0 功能] 全面启用并优化语料库，生成关于稳定性、攻防风格的深度文字分析，报告更具洞察力。
8.  [V7.0 功能] 引入学生画像系统 (防御者/攻击者/改进者/DDL战神)，生成高度个性化报告。
9.  [V7.0 功能] 深度挖掘Bug修复数据，分析Bug修复率、攻防得分比，评估开发者责任感。
10. [V7.0 功能] 详细解析第四单元UML模型检查点，提供针对性反馈。
11. [V7.0 功能] 整合核心图表为2x2的“综合表现仪表盘”，信息更集中。
12. 深度分析攻防策略演化、提交行为与代码质量的关联。
13. 引入基于房间等级的加权防御分，更科学地评估鲁棒性。
14. 使用大型语料库，生成每次都不同的、充满洞察与个性的分析报告。
15. 生成多维度、信息丰富的可视化图表。

如何使用:
1.  将你的JSON数据文件（如 result1.txt 或本例中的 tmp.json）与此脚本放在同一目录。
2.  创建一个名为 `config.yml` 的文件，并在其中写入你的学号，格式如下:
    stu_id: 23371265
3.  确保已安装所需库: pip install pandas matplotlib numpy pyyaml
4.  运行脚本: python3 analyze.py
"""

# --- 1. 配置区 ---
CONFIG = {
    "FILE_PATH": "tmp.json",
    "YAML_CONFIG_PATH": "config.yml",
    "USER_INFO": {
        "real_name": None,
        "name": None,
        "student_id": None,
        "email": None
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


# --- 2. 语料库 (Corpus) V8.6 优化版 ---
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
        "PERFECT": [ # [V8.6 扩写]
            "  - UML模型解析: 完美通过所有检查点，展现了你对类图、状态图和顺序图的深刻理解。",
            "  - UML模型解析: 你的UML解析器表现堪称完美，精确无误地解读了所有模型，所有检查点均顺利通过。",
        ],
        "IMPERFECT": [ # [V8.6 扩写]
            "  - UML模型解析: 在以下检查点遇到挑战：{issues}。这通常是模型间关联的难点，也是深入理解UML的绝佳机会。",
            "  - UML模型解析: 在解析中，以下部分需要关注：{issues}。这些复杂的交互点正是UML学习的核心，攻克它们意味着更大的进步。",
        ]
    }
    HIGHLIGHTS_INTRO = [ # [V8.6 扩写]
        "基于你的学期数据，我们为你提炼了以下几个闪亮的个人标签：",
        "数据不会说谎，它们为你描绘了一幅独特的开发者画像。以下是为你专属定制的亮点标签：",
        "在海量的代码与提交记录中，我们捕捉到了你独有的闪光点。请看你的高光时刻集锦：",
    ]
    HIGHLIGHTS_TAGS = {
        # --- 高分/卓越型 ---
        "TOP_SCORER": "  - 🏆 学霸本色: 你的强测平均分高达{avg_score:.2f}，位列顶尖水平，展现了强大的硬实力。",
        "ROCK_SOLID": "  - 💎 稳如磐石: 整个学期，你的强测最低分仍高达 {min_score:.2f}，且几乎未在互测中失守。代码质量稳定得令人惊叹！",
        "DEFENSE_MASTER": "  - 🛡️ 防御大师: 你的代码在超过75%的互测中保持零失误，堪称固若金汤。",
        "HACK_ARTIST": "  - ⚔️ 机会主义黑客: 在「{hw_name}」中，你敏锐地抓住机会，发起了{count}次成功Hack，一战成名。",
        "JML_MASTER": "  - 📜 JML大师: 在第三单元，你完美地驾驭了JML规格，所有相关作业均取得近乎满分的成绩，展现了对形式化设计的深刻理解。",
        "UML_EXPERT": "  - 🗺️ UML专家: 在第四单元，你精确地解析了所有UML模型，所有检查点均完美通过，展现了对复杂模型无与伦比的洞察力。",
        
        # --- 效率/方法型 ---
        "EFFICIENCY_ACE": "  - ⚡ 效率奇才: 在「{hw_name}」等多次任务中，你以极少的提交次数一次通过，展现了卓越的开发效率。",
        "FAST_STARTER": "  - 🚀 开局冲刺手: 在「{hw_name}」等多次作业中，你都在早期就完成了首次提交，展现了极强的学习主动性和规划能力。",
        "DEADLINE_COMEBACK": "  - ⏰ DDL逆袭者: 在「{hw_name}」等任务中，你数次在最终时刻力挽狂澜，提交的代码依然取得了优良成绩，展现了非凡的抗压能力。",

        # --- 成长/态度型 (普适性更强) ---
        "COMEBACK_KING": "  - 📈 王者归来: 从学期初的{u1_score:.1f}分到学期末的{u4_score:.1f}分，你的平均分实现了显著提升，展现了惊人的学习能力和后劲。", # [V8.6 优化] 增加具体分数
        "REFACTOR_VIRTUOSO": "  - 🏗️ 架构迭代大师: 在「{unit_name}」中，你通过果断的迭代，实现了从「{hw_name_before}」到「{hw_name_after}」的飞跃，展现了卓越的架构演进能力。",
        "BUG_FIXER_PRO": "  - 🔧 漏洞修复专家: 对于学期中被发现的所有Bug，你都成功修复，体现了极致的开发者责任感。",
        "PERFORMANCE_CHALLENGER": "  - 💨 并发挑战者: 你在第二单元虽然遇到了性能挑战，但最终成功克服，展现了强大的调试和优化能力。",
        "THE_PERSEVERER": "  - 🌱 坚韧不拔: 即使在「{low_score_hw}」遇到挫折，你依然坚持不懈，并在「{rebound_hw}」中取得了显著进步，这份毅力比分数更宝贵！",
        "DILIGENT_EXPLORER": "  - 🧗 勤奋的探索者: 本学期你累计提交了 {total_submissions} 次代码。每一次提交都是一次宝贵的探索，记录了你攀登技术高峰的足迹。",
        "ACTIVE_COLLABORATOR": "  - 🤝 积极的协作者: 在「{hw_name}」的互测中，你发起了 {hack_attempts} 次测试，积极参与到社区协作中。发现他人bug与修复自身bug同样是学习的重要一环。",
        
        # --- V8.5 新增：博弈/情景化标签 ---
        "PRECISION_STRIKER": "  - 🎯 精准打击者: 在「{hw_name}」中，你的Hack成功率高达{rate:.0f}%，展现了你构造高效测试用例的非凡能力。",
        "TACTICAL_MASTER": "  - ♟️ 战术大师: 你在「{hw_name}」的互测中展现了清晰的战术思路，集中火力成功攻破了{target_count}名同学的防线。",
        "STORM_SURVIVOR": "  - 🌊 风暴幸存者: 在「{hw_name}」这场被Hack总数高达{room_total_hacked}次的“腥风血雨”中，你仅被攻破{self_hacked}次，展现了超凡的生存能力。"
    }
    HIGHLIGHTS_CATEGORIES = {
        # ... (no changes needed here)
        "TOP_SCORER": "卓越表现", "ROCK_SOLID": "卓越表现", "DEFENSE_MASTER": "卓越表现", "JML_MASTER": "卓越表现", "UML_EXPERT": "卓越表现", "STORM_SURVIVOR": "卓越表现",
        "EFFICIENCY_ACE": "高效策略", "FAST_STARTER": "高效策略", "DEADLINE_COMEBACK": "高效策略",
        "COMEBACK_KING": "成长态度", "REFACTOR_VIRTUOSO": "成长态度", "BUG_FIXER_PRO": "成长态度", "PERFORMANCE_CHALLENGER": "成长态度", "THE_PERSEVERER": "成长态度", "DILIGENT_EXPLORER": "成长态度", "ACTIVE_COLLABORATOR": "成长态度",
        "HACK_ARTIST": "博弈高手", "PRECISION_STRIKER": "博弈高手", "TACTICAL_MASTER": "博弈高手",
    }
    DDL_ANALYSIS = [
        "数据显示，当你的「DDL指数」较高时，代码出现问题的风险似乎有所增加。这提示我们，对于复杂任务，预留更充足的测试时间可能效果更佳",
        "你的DDL指数与代码质量之间未发现明显关联，这表明即使在时间压力下，你依然能保持高水平的编码质量，令人钦佩",
        "DDL压力测试曲线揭示：当截止钟声临近时，你的代码如同压缩弹簧，反而迸发出更强的稳定性",
        "在时间压力与代码质量的平衡木上，你的表现堪比专业体操选手，总能找到完美的落地姿态",
        "系统监测到独特的DDL响应模式：时间压力不仅未削弱你的代码质量，反而激发更严谨的边界检查",
        "DDL指数分析报告显示：你的时间管理智慧让编码节奏始终处于黄金效率区间",
        "当DDL警报响起时，你的代码如同精密机械表，在时间压力下仍保持零误差运行"
    ]
    DEFENSE_SCORE_ANALYSIS = [
        "考虑到你长期在高强度的A/B房战斗，我们为你计算了加权防御分。你的最终得分是 {score:.2f} (满分100)，这比原始数据更能体现你代码的超凡鲁棒性",
        "你的加权防御分为 {score:.2f}，表现出色。这证明你的代码不仅逻辑正确，更能经受住来自同行的严苛考验",
        "经过战场压力校准，你的真实防御力指数锁定在 {score:.2f} 分，位列同期学员防御榜TOP 5%",
        "在 {score:.2f} 的加权防御分背后，是异常处理矩阵经受住300+次暴力测试的硬核证明",
        "{score:.2f} 分的防御堡垒评级意味着：你的每个catch块都如同防爆门，能吸收90%以上的异常冲击波",
        "系统授予「钻石防御认证」：基于 {score:.2f} 分的加权评估，你的代码在压力测试中实现零崩溃记录",
        "这份 {score:.2f} 分的防御成绩单，宣告你的异常处理机制已达到工业级防护标准"
    ]
    STRONG_TEST_HIGH_SCORE = [
        "强测成绩是代码质量的硬通货，你的表现堪称典范，几乎每次都稳稳拿下",
        "在强测的考验中，你的代码展现出了教科书级别的稳定性与正确性",
        "纵观整个学期，你的强测分数曲线如同一条平稳上升的航线，精准而有力",
        "你的提交记录犹如精密的瑞士钟表，在强测压力下始终保持完美节律",
        "每次强测都是你技术实力的公开展示，而你的代码总能在聚光灯下闪耀夺目",
        "强测成绩单如同你的技术护照，每一页都盖着「卓越性能」的签证印章",
        "当强测风暴来袭时，你的程序如同定海神针，在性能漩涡中岿然不动"
    ]
    STRONG_TEST_IMPERFECTION = [
        "那些非满分的作业，如同寻宝图上的标记，指引着你找到了知识的薄弱点，并最终征服了它们",
        "每一次小小的失分，都像是磨刀石，让你的编程技艺变得更加锋利",
        "值得注意的是，你在{hw_names}上遇到了挑战，这些经历是成长的最佳催化剂",
        "强测中的小缺口恰似技术拼图的留白，激励你探索更完整的知识版图",
        "在{hw_names}的强测战场上，那些未得的分数化作导航星，引领你突破认知边界",
        "强测的试金石不仅检验代码，更在{hw_names}处雕琢出你思维的新棱角",
        "强测曲线上的微小波动，在{hw_names}处激起最绚烂的成长涟漪"
    ]
    PERFORMANCE_ISSUE = [
        "特别是在处理 {hw_names} 时遇到的性能问题（{issue_types}），是你从「能用」到「好用」的进阶之战",
        "RTLE/CTLE 是每个优秀程序员都会遇到的拦路虎，你成功驯服了它，这标志着你对算法复杂度的理解迈上了新台阶",
        "在 {hw_names} 的性能迷宫中，{issue_types} 如同米诺陶洛斯，而你用时间复杂度分析之剑斩开了最优路径",
        "当 {issue_types} 在 {hw_names} 中投下阴影，你的优化方案如破晓之光，将执行耗时压缩至理论极限",
        "那些在 {hw_names} 中搏斗的 {issue_types} 巨兽，最终成为你算法精进之路的垫脚石",
        "性能调优的艺术在于：将 {issue_types} 的挑战转化为 {hw_names} 中最优雅的时间复杂度曲线",
        "如同程序员版的普罗米修斯，你从 {issue_types} 的火焰中盗取了性能优化的神圣火种，照亮了 {hw_names} 的黑暗角落"
    ]
    CONSISTENCY_STABLE = [
        "你的强测成绩方差仅为 {variance:.2f}，表现出惊人的稳定性。如同一位经验丰富的老兵，总能精确命中目标，这背后是扎实的基本功和严谨的编程习惯",
        "数据展示了你稳健的一面：成绩波动极小（方差{variance:.2f}）。这种持续高质量的输出能力，是大型软件工程中极为宝贵的品质",
        "{variance:.2f}的成绩方差如同心电图上的完美直线，证明你的代码心脏始终以恒定节律泵出优质逻辑",
        "在技术波动风暴中，你的成绩曲线如定海神针，{variance:.2f}的方差值创造了工程稳定性的新标杆",
        "系统检测到超稳定编码模式：{variance:.2f}的方差系数意味着你的每次提交都是精度达纳米级的工业艺术品",
        "{variance:.2f}的方差数据背后，是异常处理机制与算法实现的双重零抖动保障体系",
        "你的成绩轨迹如同镭射校准线，{variance:.2f}的微小波动区间彰显大师级质量控制能力"
    ]
    CONSISTENCY_VOLATILE = [
        "你的成绩曲线充满了动态与激情（方差{variance:.2f}），时而登顶，时而面临挑战。这说明你勇于探索不同的方法，每一次的波谷都是为了下一次的跃升积蓄力量",
        "方差 {variance:.2f} 的数据显示，你的学习之路并非一帆风顺，但这恰恰证明了你的坚韧。从 {worst_hw} 的低谷到 {best_hw} 的高峰，你完成了漂亮的逆袭",
        "{variance:.2f}的波动指数揭示：在{worst_hw}的淬火与{best_hw}的锻造间，你已掌握技术进化的呼吸韵律",
        "从{worst_hw}到{best_hw}的征途上，{variance:.2f}的方差记录了你突破舒适区的每个勇敢脚印",
        "你的成绩图谱如硅谷创业曲线：{worst_hw}的低谷积蓄创新势能，{best_hw}的峰值释放技术突破，整体方差{variance:.2f}正是成长加速度的证明",
        "在{variance:.2f}的波动幅度中，我们看到{worst_hw}的反思如何催化{best_hw}的质变，这是最动人的学习进化论",
        "系统记录到成长型波动模式：{worst_hw}处的调试深蹲只为{best_hw}处的性能腾跃，{variance:.2f}的方差正是你技术弹性的度量衡"
    ]
    MUTUAL_TEST_DEFENSIVE = [
        "你的代码仿佛一座坚固的堡垒，在互测的炮火中屹立不倒，被Hack次数极少。这说明你对边界条件和异常处理有着深刻的理解，防御记录堪称传奇",
        "在互测环节，你的程序表现出了惊人的鲁棒性，让无数「黑客」无功而返。能守住自己的阵地，本身就是一种强大的实力",
        "如同数字城墙的守护者，你的异常处理机制在{count}次围攻中始终保持零缺口防御记录",
        "当边界值风暴来袭时，你的代码如同诺曼底要塞，在{hw_names}战场创下连续{hacked}小时未被攻破的传奇",
        "系统授予「磐石认证」：基于{count}次高强度攻击测试，你的防御矩阵展现出军事级稳定性",
        "你的catch块如同魔法护盾，在互测战场上反弹了98%的异常流攻击",
        "在{hw_names}的攻防沙盘上，你的核心模块始终是黑客无法逾越的叹息之墙"
    ]
    MUTUAL_TEST_OFFENSIVE = [
        "你是一位敏锐的「赏金猎人」，在「{hw_name_most_hacks}」中一战成名，单次作业贡献了 {hacks_in_best_hw} 次成功Hack，占总数({total_hacks})的相当一部分。",
        "黑客大师勋章授予依据：在整个学期中，你的测试用例如手术刀般，成功攻破了 {total_unique_targets} 位同学的防御体系，展现了广泛的打击面。",
        "系统检测到高能攻击模式：你的整体Hack成功率高达 {overall_hack_rate:.1f}%，证明你的测试用例构造得极为精准高效，弹无虚发。",
        "逆向工程日志显示：在「{hw_name_most_hacks}」任务中，你似乎找到了关键的突破口，成功发起了 {hacks_in_best_hw} 次攻击，堪称该作业的‘克星’。",
        "你的漏洞雷达扫描范围极广，学期内共定位了 {total_hacks} 个bug。尤其是在「{hw_name_most_hacks}」，展现了你洞察他人代码逻辑漏洞的犀利眼光。"
    ]
    MUTUAL_TEST_BALANCED = [
        "攻防两端，你都游刃有余。既能像骑士一样发起冲锋（成功Hack {total_hacks} 次），又能像守护者一样稳固城池（被Hack {total_hacked} 次）。这种均衡的能力让你在互测的江湖中立于不败之地。",
        "双修宗师能力矩阵：进攻端斩获 {total_hacks} 个关键漏洞，防守端亦表现稳健，仅被攻破 {total_hacked} 次，展现了全面的技术实力。",
        "系统检测到完美攻防韵律：在整个学期中，你捕获了 {total_hacks} 个bug，同时自身的防线也经受住了考验，被Hack次数控制在 {total_hacked} 次。",
        "太极大师认证：以OO课程为道场，化解了大部分攻击的同时，也发动了 {total_hacks} 次精准反击，攻守平衡，节奏稳健。"
    ]
    MUTUAL_TEST_BATTLE_HARDENED = [
        "你的代码堪称「身经百战」，在总计{total_hacked_attempts}次密集攻击下，仅被成功攻破{total_hacked}次，被成功Hack率仅为{rate:.1f}%。这种在高强度测试下的沉稳表现，是卓越防御能力的最佳证明",
        "面对{total_hacked_attempts}次的轮番测试，你的程序展现出了强大的韧性，仅有{total_hacked}次被突破。这表明你的代码不仅功能正确，更具备在复杂测试环境下的生存能力",
        "数字战场生存报告：历经{total_hacked_attempts}次饱和攻击，你的防御矩阵仅出现{total_hacked}次裂隙，{rate:.1f}%的失守率创下战场生存新纪录",
        "在{total_hacked_attempts}次黑客集团冲锋后，你的核心堡垒仍保持{total_hacked}次以内的有限损伤，{rate:.1f}%的突破率宣告你已晋升为「代码防御宗师」",
        "压力熔炉测试结论：当异常洪流以{total_hacked_attempts}次/秒频率冲击时，你的异常处理链仅断裂{total_hacked}次，{rate:.1f}%的崩溃率达成军工级稳定性标准",
        "战场遗迹分析：在{total_hacked_attempts}个攻击弹坑中，仅{total_hacked}个突破防线，{rate:.1f}%的防御成功率如同现代马其诺防线般坚不可摧",
        "生存能力认证：基于{total_hacked_attempts}次攻击样本，你的代码在{total_hacked}次危机中展现进化能力，将漏洞率压缩至{rate:.1f}%的绝对安全阈值"
    ]
    MUTUAL_TEST_RELATIVE_PERFORMANCE = [
        "值得一提的是，你在互测中长期处于高强度的A房（A房率{a_room_rate:.0f}%），并常年在远低于房间平均被Hack次数的水平上保持稳定，防御能力经受住了最严苛的考验",
        "数据显示，你的A房率高达{a_room_rate:.0f}%。在高水平的竞争环境中，你的代码依然表现稳健，这含金量十足",
        "精英竞技场报告：{a_room_rate:.0f}%的A房出勤率，配合低于均值{count}个数量级的漏洞率，铸就钻石段位防御力",
        "在顶级{a_room_rate:.0f}%A房生存率背后，是你在{hw_names}战场淬炼出的反黑客特种作战能力",
        "系统授予「巅峰挑战者」称号：基于{a_room_rate:.0f}%的A房参与度，你的防御评分超越同房{count}%选手",
        "当{a_room_rate:.0f}%的代码精英汇聚A房，你的异常处理矩阵仍能保持99.9%的拦截成功率",
        "这份{a_room_rate:.0f}%的A房通行证，见证你在{term}赛季的{hw_names}中通过地狱级防御试炼"
    ]
    BUG_FIX_INSIGHT = [ # [V8.6 扩写]
        "Bug修复阶段的分数是你辛勤付出的最好证明，每一分都凝聚着你的汗水与智慧。",
        "这部分得分，是你作为一名负责任的开发者的勋章。它证明你不仅能发现问题，更能漂亮地解决问题，完成软件开发的闭环。",
        "修复得分不仅是数字，更是你追求代码卓越、对用户负责的直接体现。",
        "在攻防世界里，修复漏洞与发现漏洞同等重要。你在这方面的投入，构建了你作为可靠开发者的声誉。",
    ]
    UNIT_ANALYSIS = [ # [V8.6 扩写]
        "在 **{unit_name}**，你的平均强测分高达 **{avg_score:.2f}**，展现了你对 {unit_paradigm} 的深刻理解。",
        "回顾 **{unit_name}**，你在互测中成功Hack {hacks} 次，同时代码被攻破 {hacked} 次，攻防战绩斐然，显然你已掌握了 {unit_paradigm} 的核心要领。",
        "**{unit_name}** 对你来说似乎是一个挑战与机遇并存的篇章。虽然遇到了一些困难，但你最终还是攻克了它，这种解决复杂问题的经历远比一帆风顺更加宝贵。",
        "深入 **{unit_name}** 单元，你的代码在面对 {unit_paradigm} 的复杂场景时，展现了 {avg_score:.2f} 分的强劲实力，尤其在互测中取得 {hacks} 次成功Hack，表现亮眼。",
    ]
    GROWTH_ANALYSIS = [ # [V8.6 扩写]
        "从学期初到学期末，你的进步显而易见。后期作业的平均分（{later_avg:.2f}）明显高于前期（{early_avg:.2f}），这是一条陡峭而坚实的上升曲线。",
        "你的学习轨迹展现了强大的后劲。数据显示，随着课程深入，你的表现愈发稳健，后期平均分达到了 {later_avg:.2f}，证明你已将OO思想内化于心。",
        "你的成长曲线令人印象深刻。从学期初的 {early_avg:.2f} 分到后期的 {later_avg:.2f} 分，这不仅仅是分数的增长，更是对面向对象思想理解深度的跃迁。",
    ]
    SUBMISSION_ANALYSIS_INTRO = [ # [V8.6 扩写]
        "你的提交习惯，是代码之外的另一面镜子，反映了你的工作节奏与策略。",
        "让我们看看你的时间管理艺术：每一次commit和submit，都藏着你的开发故事。",
        "代码的诞生过程同样精彩。你的提交时间轴，如同一部纪录片，揭示了你独特的工作心流。",
        "每一次 `git push` 都不是终点，而是新的起点。让我们通过提交数据，一窥你的开发哲学。",
    ]
    SUBMISSION_MOST = [ # [V8.6 扩写]
        "在「{hw_name}」上，你投入了最多的精力，提交了 {count} 次。毫无疑问，这是你精雕细琢的作品。",
        "「{hw_name}」以 {count} 次提交荣登榜首，可见你在这项作业上付出了巨大的努力，不断迭代优化。",
        "在「{hw_name}」上，你倾注了最多的心血，高达 {count} 次的提交记录了你从构思到完美的每一步迭代。",
    ]
    SUBMISSION_LEAST = [ # [V8.6 扩写]
        "而在「{hw_name}」上，你仅用了 {count} 次提交就搞定，展现了惊人的效率和自信！",
        "「{hw_name}」的提交次数最少（{count}次），或许是你思路清晰、一气呵成的典范之作。",
        "对于「{hw_name}」，你展现了‘快准狠’的风格，仅用 {count} 次提交便大功告成，这背后是对需求的精准把握和强大的自信。",
    ]
    HW_ANALYSIS_INTRO = [ # [V8.6 扩写]
        "接下来，让我们深入每一次作业的细节，复盘得失，洞见成长。",
        "每一份作业都是一个独特的关卡，下面是你通关每一关的详细战报。",
        "现在，让我们戴上显微镜，逐一剖析每次作业的战斗记录，从中汲取经验，为未来铺路。",
        "历史是最好的老师。下面，我们将回放你在每次作业中的表现，重温那些挑战与突破的瞬间。",
    ]
    HACK_STRATEGY_INTRO = [ # [V8.6 扩写]
        "你的互测攻击模式，揭示了你作为一名“白帽黑客”的独特风格与战术偏好。",
        "在互测的博弈场上，你不是一个简单的测试者。你的攻击模式，揭示了你的战术思想与独特洞察力。",
        "每一次成功的Hack都是一次精彩的推理。让我们分析你的攻击数据，看看这位“赏金猎人”的作案手法。",
    ]
    HACK_TIMING_ANALYSIS = {
        "EARLY_BIRD": "你是一位典型的“闪电战”选手，习惯在互测开始后的“黄金一小时”内迅速发起攻势，抢占先机。",
        "DEADLINE_SNIPER": "你更像一位“狙击手”，倾向于在互测临近结束时出手，此刻往往能发现一些他人忽略的漏洞。",
        "CONSISTENT_PRESSURE": "你的攻击分布在整个互测周期，通过持续的压力测试寻找对手的薄弱环节，策略稳健而有效。"
    }
    HACK_TARGETING_ANALYSIS = {
        "FOCUSED_FIRE": "你的攻击策略倾向于“集中火力”，一旦发现某个对手的潜在弱点，便会进行深入和持续的测试。",
        "WIDE_NET": "你倾向于“广撒网”，对房间内的多位同学进行试探性攻击，以此来最大化发现漏洞的概率。"
    }
    STYLE_EARLY_BIRD = [
    "⚡ 闪电启动：任务发布24小时内立即行动", "🕊️ 晨型人格：清晨工作效率提升200%", "⏳ 时间魔法师：提前完成创造缓冲空间",
    "🧠 深度思考者：用省下时间优化全局策略", "📚 知识囤积癖：常备3个替代方案应对变数", "🌅 曙光效应：在他人起步时已完成迭代",
    "🎯 精准预判：擅长识别任务关键路径"
    ]
    STYLE_WELL_PACED = [
    "🧘 禅式节奏：每日稳定推进5%进度", "📊 模块大师：将任务分解为标准化单元", "⚖️ 平衡艺术家：工作/休息严格按52分钟循环",
    "🛡️ 抗压金钟罩：突发状况下仍保持原速", "📈 复利思维：日积月累产生质变飞跃", "🧩 拼图策略：系统性构建知识网络",
    "☕ 咖啡哲学：懂得何时暂停萃取灵感"
    ]
    STYLE_DDL_FIGHTER = [
    "🚀 肾上腺素模式：倒计时72小时激活超频状态", "🌙 夜行生物：月光下工作效率飙升", "🎭 极限表演家：压力越大表现越惊艳",
    "💥 压缩魔法：将月工作量凝练为三日精华", "🆘 危机经济学：擅长用20%精力达成80%效果", "🔥 凤凰涅槃：每次冲刺后需3天恢复期",
    "🎲 冒险赌徒：享受刀尖跳舞的刺激感"
    ]
    STYLE_UNKNOWN = [
    "🕰️ 时空扭曲者：提交记录显示昨日完成明日任务", "🔮 先知体质：提前提交未发布的任务", "🪐 虫洞穿梭：同一时间出现在多个任务线",
    "🧪 实验室白鼠：行为数据突破系统认知边界", "📜 历史编纂官：修改已归档任务的完成时间", "🌀 因果律破坏者：提交导致任务需求反向变更",
    "👽 外星逻辑：用第四维度理解三维时间轴"
    ]
    OVERALL_CONCLUSION = [
    "🪐 你的OO征程宛如星际拓荒：在类与对象的陨石带中导航，于多态的星云里绘制轨迹，最终在继承的引力场完成华丽入轨",
    "🌱 从幼苗到巨树：根系深扎封装土壤，枝叶伸展多态光能，当设计模式的年轮闭合时，整片森林都在回响你的生长节律",
    "⚒️ 代码熔炉记事：\n"
    "   - 以调试为锤 锻出异常处理的精钢骨架\n"
    "   - 用需求作砧 敲击出接口契约的凛冽锋刃\n"
    "   - 在持续集成的淬火池中 铸成可扩展性的不朽剑纹",
    "📜 这本由commit日志编纂的史诗中：\n"
    "   ‘重构风暴’章节见证你破茧的阵痛\n"
    "   ‘模式觉醒’卷轴记载架构的顿悟\n"
    "   而最动人的诗篇 永远藏在那些debug到天明的注脚里",
    "🎻 当期末终章奏响：\n"
    "   你交出的不仅是可执行文件\n"
    "   更是用抽象思维编织的交响乐\n"
    "   每个方法都是跃动的音符\n"
    "   每个对象都在共鸣箱里找到自己的音程",
    "🌌 请珍藏这份架构师成长星图：\n"
    "   那些看似迷路的异常分支\n"
    "   实则是通往技术深度的虫洞坐标\n"
    "   此刻的毕业证书只是序曲封面\n"
    "   真正的工程传奇正在编译中..."
    ]


def find_and_update_user_info(student_id, raw_data, config):
    """
    根据学生ID在原始JSON数据中查找姓名和邮箱，并更新CONFIG。
    """
    user_name = None
    user_email = None

    for item in raw_data:
        body_data = item.get("body", {}).get("data", {})
        if not body_data: continue
        if 'mutual_test/room/self' in item.get('url', ''):
            for member in body_data.get('members', []):
                if member.get('student_id') == student_id:
                    user_name = member.get('real_name')
                    break
        if user_name: break

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

    if not user_email:
        user_email = f"{student_id}@buaa.edu.cn"
        print(f"警告：未在数据中找到邮箱，已自动生成: {user_email}")

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
        # V8.5 新增：解析互测时间
        elif 'mutual_test' in item['url'] and 'room' not in item['url'] and 'data_config' not in item['url'] and 'start_time' in body_data:
            homework_data[hw_id].update({
                'mutual_test_start_time': body_data.get('start_time'),
                'mutual_test_end_time': body_data.get('end_time'),
            })
        elif 'ultimate_test/submit' in item['url'] and is_target_user(body_data.get('user', {}), config):
            homework_data[hw_id]['strong_test_score'] = body_data.get('score')
            results = body_data.get('results', [])
            issue_counter = Counter(p['message'] for p in results if p.get('message') != 'ACCEPTED')
            homework_data[hw_id]['strong_test_issues'] = dict(issue_counter) if issue_counter else {}
            if 'uml_results' in body_data and body_data['uml_results']:
                homework_data[hw_id]['uml_detailed_results'] = body_data['uml_results']
        elif 'mutual_test/room/self' in item['url']:
            all_members = body_data.get('members', [])
            all_events = body_data.get('events', [])
            # V8.5 新增：计算房间整体数据
            room_hacked_counts = [int(m.get('hacked', {}).get('success', 0)) for m in all_members]
            if room_hacked_counts:
                homework_data[hw_id]['room_total_hacked'] = sum(room_hacked_counts)
                homework_data[hw_id]['room_avg_hacked'] = np.mean(room_hacked_counts)

            for member in all_members:
                if is_target_user(member, config):
                    # V8.5 新增：解析个人博弈数据
                    my_hack_events = [
                        {'time': e['submitted_at'], 'target': e['hacked']['student_id']}
                        for e in all_events if is_target_user(e.get('hack', {}), config)
                    ]
                    successful_targets = sum(1 for m in all_members if int(m.get('hacked', {}).get('your_success', 0)) > 0)

                    homework_data[hw_id].update({
                        'alias_name': member.get('alias_name_string'),
                        'hack_success': int(member.get('hack', {}).get('success', 0)),
                        'hack_total_attempts': int(member.get('hack', {}).get('total', 0)),
                        'hacked_success': int(member.get('hacked', {}).get('success', 0)),
                        'hacked_total_attempts': int(member.get('hacked', {}).get('total', 0)),
                        'room_level': body_data.get('mutual_test', {}).get('level', 'N/A').upper(),
                        'mutual_test_events': my_hack_events,
                        'successful_hack_targets': successful_targets
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
    dt_cols = ['public_test_start_time', 'public_test_end_time', 'public_test_last_submit',
               'mutual_test_start_time', 'mutual_test_end_time']
    for col in dt_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')

    durations = (df['public_test_end_time'] - df['public_test_start_time']).dt.total_seconds()
    offsets = (df['public_test_last_submit'] - df['public_test_start_time']).dt.total_seconds()
    df['ddl_index'] = (offsets / durations).fillna(0.5).clip(0, 1)

    df['offense_defense_ratio'] = (df['hack_success'].fillna(0) + 1) / (df['hacked_success'].fillna(0) + 1)

    df['strong_test_deduction_count'] = df['strong_test_issues'].apply(
        lambda x: sum(x.values()) if isinstance(x, dict) else 0)

    room_weights = {'A': 10, 'B': 8, 'C': 5}
    df['weighted_defense_deduction'] = df.apply(
        lambda row: row['hacked_success'] * room_weights.get(row.get('room_level'), 3), axis=1)

    df['bug_fix_details'] = df['bug_fix_details'].apply(lambda x: x if isinstance(x, dict) else {})
    df['mutual_test_events'] = df['mutual_test_events'].apply(lambda x: x if isinstance(x, list) else [])
    df['hacked_total_attempts'] = df['hacked_total_attempts'].fillna(0).astype(int)

    df['bug_fix_details'] = df['bug_fix_details'].fillna(value={})
    df['bug_fix_hacked_count'] = df['bug_fix_details'].apply(lambda x: x.get('hacked_count', 0))
    df['bug_fix_unfixed_count'] = df['bug_fix_details'].apply(lambda x: x.get('unfixed_count', 0))
    df['bug_fix_hack_score'] = df['bug_fix_details'].apply(lambda x: x.get('hack_score', 0))
    df['bug_fix_hacked_score'] = df['bug_fix_details'].apply(lambda x: x.get('hacked_score', 0))
    
    with np.errstate(divide='ignore', invalid='ignore'):
        df['bug_fix_rate'] = ((df['bug_fix_hacked_count'] - df['bug_fix_unfixed_count']) / df['bug_fix_hacked_count']) * 100
        df['hack_success_rate'] = (df['hack_success'] / df['hack_total_attempts']) * 100

    df['bug_fix_rate'] = df['bug_fix_rate'].fillna(np.nan)
    df['hack_success_rate'] = df['hack_success_rate'].fillna(np.nan)

    df['hack_fix_score_ratio'] = (df['bug_fix_hack_score'] + 0.1) / (df['bug_fix_hacked_score'] + 0.1)

    return df


# --- 5. 可视化模块 ---
def create_visualizations(df, user_name, config):
    """主函数，调用所有可视化生成函数"""
    print("\n正在生成可视化图表，请稍候...")
    create_performance_dashboard(df, user_name)
    create_unit_radar_chart(df, user_name, config)
    print("所有分析报告与图表已生成完毕！")

def create_performance_dashboard(df, user_name):
    """生成2x2的综合表现仪表盘"""
    fig, axes = plt.subplots(2, 2, figsize=(20, 14))
    fig.suptitle(f'{user_name} - OO课程综合表现仪表盘 (V8.6)', fontsize=24, weight='bold')

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
        ax2_twin.set_ylabel('被成功Hack次数', color=color2, fontsize=12)
        ax2_twin.scatter(analysis_df['ddl_index'], analysis_df['hacked_success'],
                         marker='x', alpha=0.6, color=color2, label='被成功Hack次数')
        ax2_twin.tick_params(axis='y', labelcolor=color2)
        ax2.set_title('提交时间与代码质量关联', fontsize=16)
    
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
        max_hacked = np.nanmax(stats_array[:, 2])
        if max_hacked > 0: stats_array[:, 2] = max_hacked - stats_array[:, 2] 
        else: stats_array[:, 2] = 1 
        
        with np.errstate(divide='ignore', invalid='ignore'):
            max_vals = np.nanmax(stats_array, axis=0)
            max_vals[max_vals == 0] = 1 
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

# --- 6. 动态报告生成器 V8.6 ---
def analyze_submission_style(hw_row):
    start, end, last_submit = hw_row.get('public_test_start_time'), hw_row.get('public_test_end_time'), hw_row.get('public_test_last_submit')
    if pd.isna(start) or pd.isna(end) or pd.isna(last_submit): return random.choice(ReportCorpus.STYLE_UNKNOWN)
    total_duration = end - start
    if total_duration.total_seconds() <= 0: return random.choice(ReportCorpus.STYLE_UNKNOWN)
    ratio = (last_submit - start).total_seconds() / total_duration.total_seconds()
    if ratio <= 0.2: return random.choice(ReportCorpus.STYLE_EARLY_BIRD)
    elif ratio >= 0.8: return random.choice(ReportCorpus.STYLE_DDL_FIGHTER)
    else: return random.choice(ReportCorpus.STYLE_WELL_PACED)

def generate_highlights(df):
    """[V8.6-Refined] 生成最多5个多样化的个人亮点标签，优先覆盖不同类别，并使用随机选择代替评分。"""
    if df.empty:
        return []
    
    all_possible_highlights = []

    def add_highlight(key, text):
        all_possible_highlights.append((key, text))

    strong_scores = df['strong_test_score'].dropna()
    mutual_df = df[df.get('has_mutual_test', pd.Series(True))].dropna(subset=['hack_success', 'hacked_success'])
    submit_times_df = df.dropna(subset=['public_test_used_times'])
    
    # === 普适型标签 (成长态度) ===
    if not submit_times_df.empty:
        total_submissions = int(submit_times_df['public_test_used_times'].sum())
        if total_submissions > 30: 
            add_highlight("DILIGENT_EXPLORER", ReportCorpus.HIGHLIGHTS_TAGS["DILIGENT_EXPLORER"].format(total_submissions=total_submissions))
    if len(strong_scores) > 1:
        for i in range(len(df) - 1):
            hw1, hw2 = df.iloc[i], df.iloc[i+1]
            s1, s2 = hw1.get('strong_test_score'), hw2.get('strong_test_score')
            if pd.notna(s1) and pd.notna(s2) and s1 < 80 and s2 - s1 > 15:
                add_highlight("THE_PERSEVERER", ReportCorpus.HIGHLIGHTS_TAGS["THE_PERSEVERER"].format(low_score_hw=hw1['name'], rebound_hw=hw2['name']))
                break
    if not mutual_df.empty:
        active_row = mutual_df.loc[mutual_df['hack_total_attempts'].idxmax(skipna=True)] if 'hack_total_attempts' in mutual_df.columns and not mutual_df['hack_total_attempts'].empty else None
        if active_row is not None and active_row['hack_total_attempts'] > 10:
             add_highlight("ACTIVE_COLLABORATOR", ReportCorpus.HIGHLIGHTS_TAGS["ACTIVE_COLLABORATOR"].format(hw_name=active_row['name'], hack_attempts=int(active_row['hack_total_attempts'])))
    bugfix_df = df.dropna(subset=['bug_fix_hacked_count'])
    if not bugfix_df.empty and bugfix_df['bug_fix_hacked_count'].sum() > 0 and bugfix_df['bug_fix_unfixed_count'].sum() == 0:
        add_highlight("BUG_FIXER_PRO", ReportCorpus.HIGHLIGHTS_TAGS["BUG_FIXER_PRO"])
    unit2_df = df[df['unit'].str.contains("第二单元", na=False)]
    if not unit2_df.empty:
        has_perf_issues = any("TIME" in str(s) for s in unit2_df['strong_test_issues'].dropna())
        if has_perf_issues and unit2_df['strong_test_score'].mean() > 95:
             add_highlight("PERFORMANCE_CHALLENGER", ReportCorpus.HIGHLIGHTS_TAGS["PERFORMANCE_CHALLENGER"])

    # === 效率与方法型 (高效策略) ===
    ddl_comeback_df = df[(df['ddl_index'] > 0.9) & (df['strong_test_score'] > 85)]
    if len(ddl_comeback_df) >= 2:
        add_highlight("DEADLINE_COMEBACK", ReportCorpus.HIGHLIGHTS_TAGS["DEADLINE_COMEBACK"].format(hw_name=ddl_comeback_df.iloc[0]['name']))
    if not submit_times_df.empty:
        min_submit_row = submit_times_df.loc[submit_times_df['public_test_used_times'].idxmin()]
        if min_submit_row['public_test_used_times'] <= 2:
            add_highlight("EFFICIENCY_ACE", ReportCorpus.HIGHLIGHTS_TAGS["EFFICIENCY_ACE"].format(hw_name=min_submit_row['name']))
    early_submitters = df[df['ddl_index'] < 0.1]
    if len(early_submitters) >= 3:
        add_highlight("FAST_STARTER", ReportCorpus.HIGHLIGHTS_TAGS["FAST_STARTER"].format(hw_name=early_submitters.iloc[0]['name']))

    # === 高分与卓越型 (卓越表现) ===
    if not strong_scores.empty and not mutual_df.empty and strong_scores.min() > 95 and mutual_df['hacked_success'].sum() <= 1:
        add_highlight("ROCK_SOLID", ReportCorpus.HIGHLIGHTS_TAGS["ROCK_SOLID"].format(min_score=strong_scores.min()))
    if not mutual_df.empty and (mutual_df['hacked_success'] == 0).mean() >= 0.75:
        add_highlight("DEFENSE_MASTER", ReportCorpus.HIGHLIGHTS_TAGS["DEFENSE_MASTER"])
    if not strong_scores.empty and strong_scores.mean() > 98.5:
        add_highlight("TOP_SCORER", ReportCorpus.HIGHLIGHTS_TAGS["TOP_SCORER"].format(avg_score=strong_scores.mean()))
    
    # === 博弈/情景化标签 (博弈高手 & 卓越表现) ===
    if not mutual_df.empty and not mutual_df['hack_success'].empty:
        max_hack_row = mutual_df.loc[mutual_df['hack_success'].idxmax()]
        if max_hack_row['hack_success'] >= 10:
            add_highlight("HACK_ARTIST", ReportCorpus.HIGHLIGHTS_TAGS["HACK_ARTIST"].format(hw_name=max_hack_row['name'], count=int(max_hack_row['hack_success'])))
    for _, hw in df.iterrows():
        if pd.notna(hw.get('hack_success_rate')) and hw.get('hack_total_attempts', 0) > 3 and hw['hack_success_rate'] > 20:
            add_highlight("PRECISION_STRIKER", ReportCorpus.HIGHLIGHTS_TAGS["PRECISION_STRIKER"].format(hw_name=hw['name'], rate=hw['hack_success_rate']))
        if hw.get('hack_success', 0) > 4 and hw.get('successful_hack_targets', 100) <= 2:
            add_highlight("TACTICAL_MASTER", ReportCorpus.HIGHLIGHTS_TAGS["TACTICAL_MASTER"].format(hw_name=hw['name'], target_count=int(hw['successful_hack_targets'])))
        if hw.get('room_total_hacked', 0) > 20 and hw.get('hacked_success', 100) <= 1:
            add_highlight("STORM_SURVIVOR", ReportCorpus.HIGHLIGHTS_TAGS["STORM_SURVIVOR"].format(hw_name=hw['name'], room_total_hacked=int(hw['room_total_hacked']), self_hacked=int(hw['hacked_success'])))

    # === 单元专精与成长型 (卓越表现 & 成长态度) ===
    unit3_df = df[df['unit'].str.contains("第三单元", na=False)]
    if not unit3_df.empty and unit3_df['strong_test_score'].mean() > 99 and unit3_df['hacked_success'].sum() == 0:
        add_highlight("JML_MASTER", ReportCorpus.HIGHLIGHTS_TAGS["JML_MASTER"])
    unit4_df = df[df['unit'].str.contains("第四单元", na=False)]
    if not unit4_df.empty and unit4_df['strong_test_score'].mean() == 100:
        is_perfect = all(all(r['message'] == 'ACCEPTED' for r in row.get('uml_detailed_results', [])) for _, row in unit4_df.iterrows() if row.get('uml_detailed_results'))
        if is_perfect:
            add_highlight("UML_EXPERT", ReportCorpus.HIGHLIGHTS_TAGS["UML_EXPERT"])
    for unit_name in df['unit'].unique():
        unit_df = df[df['unit'] == unit_name].sort_values('hw_num')
        if len(unit_df) > 1:
            scores = unit_df['strong_test_score'].dropna()
            if len(scores) > 1 and scores.iloc[-1] - scores.iloc[0] > 10 and scores.iloc[-1] > 95:
                add_highlight("REFACTOR_VIRTUOSO", ReportCorpus.HIGHLIGHTS_TAGS["REFACTOR_VIRTUOSO"].format(unit_name=re.sub(r'：.*', '', unit_name), hw_name_before=unit_df.iloc[0]['name'], hw_name_after=unit_df.iloc[-1]['name']))
                break
    unit_scores = df.groupby('unit')['strong_test_score'].mean()
    u1_key, u4_key = "第一单元：表达式求导", "第四单元：UML解析"
    if u1_key in unit_scores and u4_key in unit_scores:
        u1_score, u4_score = unit_scores[u1_key], unit_scores[u4_key]
        if pd.notna(u1_score) and pd.notna(u4_score) and u4_score > u1_score + 2:
            add_highlight("COMEBACK_KING", ReportCorpus.HIGHLIGHTS_TAGS["COMEBACK_KING"].format(u1_score=u1_score, u4_score=u4_score))

    if not all_possible_highlights:
        return []

    highlights_by_category = {}
    for key, text in all_possible_highlights:
        category = ReportCorpus.HIGHLIGHTS_CATEGORIES.get(key, "其他")
        if category not in highlights_by_category:
            highlights_by_category[category] = []
        highlights_by_category[category].append(text)

    final_highlights = []
    available_categories = list(highlights_by_category.keys())
    random.shuffle(available_categories)

    if len(available_categories) >= 5:
        chosen_categories = random.sample(available_categories, 5)
        for category in chosen_categories:
            final_highlights.append(random.choice(highlights_by_category[category]))
    else:
        leftover_highlights = []
        for category in available_categories:
            category_highlights = highlights_by_category[category]
            random.shuffle(category_highlights)
            final_highlights.append(category_highlights.pop(0))
            leftover_highlights.extend(category_highlights)
        
        needed = 5 - len(final_highlights)
        if needed > 0 and leftover_highlights:
            random.shuffle(leftover_highlights)
            final_highlights.extend(leftover_highlights[:needed])

    random.shuffle(final_highlights)
    return final_highlights[:5]

def identify_student_persona(df):
    if df.empty: return "BALANCED"
    mutual_df = df[df.get('has_mutual_test', pd.Series(False))]
    if df['ddl_index'].dropna().mean() > 0.8: return "SPRINTER"
    if not mutual_df.empty and mutual_df['hack_success'].sum() > 25: return "HUNTER"
    if (not mutual_df.empty and mutual_df['hacked_success'].sum() <= 3) and df['strong_test_score'].var() < 10: return "FORTRESS"
    if df['public_test_used_times'].dropna().mean() > 6: return "GRINDER"
    return "BALANCED"

def format_uml_analysis(hw_row):
    uml_results = hw_row.get('uml_detailed_results', [])
    if not uml_results: return ""
    failed_checks = [r['name'] for r in uml_results if r['message'] != 'ACCEPTED']
    if not failed_checks: return random.choice(ReportCorpus.UML_ANALYSIS["PERFECT"])
    else: return random.choice(ReportCorpus.UML_ANALYSIS["IMPERFECT"]).format(issues=', '.join(failed_checks))

def _analyze_overall_performance(df):
    """[V8.6] 辅助函数，生成宏观表现的文字分析，加入相对表现和防御韧性分析"""
    analysis_texts = []
    
    strong_scores = df['strong_test_score'].dropna()
    if not strong_scores.empty:
        avg_score, var_score = strong_scores.mean(), strong_scores.var()
        analysis_texts.append(f"强测表现: 平均分 {avg_score:.2f} | 稳定性 (方差) {var_score:.2f}")
        if avg_score > 98: analysis_texts.append(random.choice(ReportCorpus.STRONG_TEST_HIGH_SCORE))
        else:
            imperfect_hws = df[df['strong_test_score'] < 100]['name'].tolist()
            if imperfect_hws: analysis_texts.append(random.choice(ReportCorpus.STRONG_TEST_IMPERFECTION).format(hw_names=', '.join(imperfect_hws[:2])))
        if var_score < 15: analysis_texts.append(random.choice(ReportCorpus.CONSISTENCY_STABLE).format(variance=var_score))
        else:
            best_hw = df.loc[df['strong_test_score'].idxmax()]['name'] if pd.notna(df['strong_test_score'].max()) else '某次作业'
            worst_hw = df.loc[df['strong_test_score'].idxmin()]['name'] if pd.notna(df['strong_test_score'].min()) else '另一次作业'
            analysis_texts.append(random.choice(ReportCorpus.CONSISTENCY_VOLATILE).format(variance=var_score, best_hw=best_hw, worst_hw=worst_hw))

    mutual_df = df[df.get('has_mutual_test', pd.Series(False))].dropna(subset=['hack_success', 'hacked_success', 'hacked_total_attempts'])
    if not mutual_df.empty:
        total_hacks = mutual_df['hack_success'].sum()
        total_hacked = mutual_df['hacked_success'].sum()
        total_hacked_attempts = mutual_df['hacked_total_attempts'].sum()
        
        analysis_texts.append(f"\n互测战绩: 成功Hack {int(total_hacks)} 次 | 被成功Hack {int(total_hacked)} 次 (总计被攻击 {int(total_hacked_attempts)} 次)")

        profile_found = False
        
        # [V8.6 修复] Offensive profile check with accurate data
        if total_hacks > total_hacked * 2 and total_hacks >= 10:
            hw_with_most_hacks = mutual_df.loc[mutual_df['hack_success'].idxmax()]
            total_unique_targets = mutual_df['successful_hack_targets'].sum()
            total_hack_attempts = mutual_df['hack_total_attempts'].sum()
            overall_hack_rate = (total_hacks / total_hack_attempts) * 100 if total_hack_attempts > 0 else 0

            offensive_format_vars = {
                'hw_name_most_hacks': hw_with_most_hacks['name'],
                'hacks_in_best_hw': int(hw_with_most_hacks['hack_success']),
                'total_hacks': int(total_hacks),
                'total_unique_targets': int(total_unique_targets),
                'overall_hack_rate': overall_hack_rate
            }
            analysis_texts.append(random.choice(ReportCorpus.MUTUAL_TEST_OFFENSIVE).format(**offensive_format_vars))
            profile_found = True
        
        # Defensive profile check (low successful hacks)
        if total_hacked <= 3:
            analysis_texts.append(random.choice(ReportCorpus.MUTUAL_TEST_DEFENSIVE).format(count=int(total_hacked_attempts), hw_names="各次", hacked="多"))
            profile_found = True
        
        # Battle-Hardened profile check (high attempts, low success rate)
        if total_hacked_attempts > 20: 
            hacked_rate = (total_hacked / total_hacked_attempts) * 100 if total_hacked_attempts > 0 else 0
            if hacked_rate < 15:
                analysis_texts.append(random.choice(ReportCorpus.MUTUAL_TEST_BATTLE_HARDENED).format(
                    total_hacked_attempts=int(total_hacked_attempts),
                    total_hacked=int(total_hacked),
                    rate=hacked_rate
                ))
                profile_found = True
        
        if not profile_found:
            # [V8.6 修复] Balanced profile check with accurate data
            balanced_format_vars = {
                'total_hacks': int(total_hacks),
                'total_hacked': int(total_hacked)
            }
            analysis_texts.append(random.choice(ReportCorpus.MUTUAL_TEST_BALANCED).format(**balanced_format_vars))

        # V8.5 新增：相对表现分析
        room_df = df.dropna(subset=['room_level'])
        if not room_df.empty:
            a_room_rate = (room_df['room_level'] == 'A').mean() * 100
            if a_room_rate > 60:
                # This format string is general enough and doesn't need specific fixes
                analysis_texts.append(random.choice(ReportCorpus.MUTUAL_TEST_RELATIVE_PERFORMANCE).format(a_room_rate=a_room_rate, count=0, hw_names="多次", term="本"))

        total_weighted_deduction = mutual_df['weighted_defense_deduction'].sum()
        max_possible_deduction = mutual_df.shape[0] * 10 
        defense_score = 100 - (total_weighted_deduction / (max_possible_deduction * 10) * 100) if max_possible_deduction > 0 else 100
        analysis_texts.append(random.choice(ReportCorpus.DEFENSE_SCORE_ANALYSIS).format(score=max(0, defense_score)))

    unit2_df = df[df['unit'].str.contains("第二单元", na=False)]
    if not unit2_df.empty:
        perf_issues = {}
        for _, row in unit2_df.iterrows():
            for issue, count in row.get('strong_test_issues', {}).items():
                if "TIME_LIMIT_EXCEED" in issue:
                    perf_issues.setdefault(issue, []).append(row['name'])
        if perf_issues:
            issue_types = ", ".join(perf_issues.keys())
            hw_names = ", ".join(list(set(sum(perf_issues.values(), []))))
            analysis_texts.append("\n" + random.choice(ReportCorpus.PERFORMANCE_ISSUE).format(hw_names=hw_names, issue_types=issue_types))
            
    return analysis_texts

def _analyze_hack_strategy(df):
    """[V8.5 新增] 分析互测博弈策略"""
    texts = []
    mutual_df = df.dropna(subset=['mutual_test_start_time', 'mutual_test_end_time', 'mutual_test_events'])
    mutual_df = mutual_df[mutual_df['mutual_test_events'].apply(len) > 0]
    if mutual_df.empty:
        return []

    early_hacks, late_hacks, total_hacks = 0, 0, 0
    total_attempts, total_unique_targets = 0, 0

    for _, hw in mutual_df.iterrows():
        duration = (hw['mutual_test_end_time'] - hw['mutual_test_start_time']).total_seconds()
        if duration <= 0: continue
        events = hw['mutual_test_events']
        total_hacks += len(events)
        total_attempts += len(events)
        total_unique_targets += len(set(e['target'] for e in events))

        for event in events:
            hack_time = pd.to_datetime(event['time'])
            ratio = (hack_time - hw['mutual_test_start_time']).total_seconds() / duration
            if ratio < 0.1: early_hacks += 1
            if ratio > 0.9: late_hacks += 1

    if total_hacks == 0: return []
    
    if early_hacks / total_hacks > 0.5:
        texts.append(ReportCorpus.HACK_TIMING_ANALYSIS["EARLY_BIRD"])
    elif late_hacks / total_hacks > 0.5:
        texts.append(ReportCorpus.HACK_TIMING_ANALYSIS["DEADLINE_SNIPER"])
    else:
        texts.append(ReportCorpus.HACK_TIMING_ANALYSIS["CONSISTENT_PRESSURE"])

    concentration_ratio = total_attempts / total_unique_targets if total_unique_targets > 0 else 0
    if concentration_ratio > 2.5:
        texts.append(ReportCorpus.HACK_TARGETING_ANALYSIS["FOCUSED_FIRE"])
    else:
        texts.append(ReportCorpus.HACK_TARGETING_ANALYSIS["WIDE_NET"])
    
    return texts

def generate_dynamic_report(df, user_name, config):
    print("\n" + "="*80)
    print(f" {user_name} - OO课程动态学习轨迹报告 V8.6 ".center(80, "="))
    print("="*80)
    
    if df.empty:
        print("\n未找到该学生的有效作业数据，请检查配置文件。")
        return

    persona = identify_student_persona(df)
    print("\n" + ReportCorpus.PERSONA_ANALYSIS[persona].format(user_name=user_name))

    highlights = generate_highlights(df)
    if highlights:
        print("\n" + "--- 1. 个人亮点标签 ---".center(70))
        print(random.choice(ReportCorpus.HIGHLIGHTS_INTRO))
        for tag in highlights:
            print(tag)

    print("\n" + "--- 2. 宏观学期表现与深度洞察 ---".center(70))
    for text in _analyze_overall_performance(df):
        print(text)
    
    print("\n" + "--- 3. 开发者责任感与调试能力 (Bug修复) ---".center(70))
    bugfix_df = df.dropna(subset=['bug_fix_hacked_count'])
    total_bugs = bugfix_df['bug_fix_hacked_count'].sum()
    if total_bugs > 0:
        fixed_bugs = total_bugs - bugfix_df['bug_fix_unfixed_count'].sum()
        fix_rate = (fixed_bugs / total_bugs) * 100
        print(ReportCorpus.BUG_FIX_ANALYSIS["HIGH_FIX_RATE" if fix_rate > 80 else "LOW_FIX_RATE"].format(total_bugs=int(total_bugs), fixed_bugs=int(fixed_bugs), rate=fix_rate))
            
        total_hack_score, total_hacked_score = bugfix_df['bug_fix_hack_score'].sum(), bugfix_df['bug_fix_hacked_score'].sum()
        if total_hack_score + total_hacked_score > 0:
            ratio = (total_hack_score + 0.1) / (total_hacked_score + 0.1)
            if ratio > 1.5: print(ReportCorpus.BUG_FIX_ANALYSIS["HACK_FOCUSED"].format(hack_score=total_hack_score, hacked_score=total_hacked_score, ratio=ratio))
            elif ratio < 0.7: print(ReportCorpus.BUG_FIX_ANALYSIS["FIX_FOCUSED"].format(hack_score=total_hack_score, hacked_score=total_hacked_score, ratio=ratio))
        print(random.choice(ReportCorpus.BUG_FIX_INSIGHT))
    else:
        print(ReportCorpus.BUG_FIX_ANALYSIS["NO_BUGS_TO_FIX"])

    print("\n" + "--- 4. 单元深度与成长轨迹 ---".center(70))
    unit_paradigms = {"第一单元": "递归下降", "第二单元": "多线程", "第三单元": "JML规格", "第四单元": "UML解析"}
    for unit_name_full, hw_nums in config["UNIT_MAP"].items():
        unit_df = df[df['unit'] == unit_name_full]
        unit_name_short = re.sub(r'：.*', '', unit_name_full)
        if not unit_df.empty and pd.notna(unit_df['strong_test_score'].mean()):
            print(random.choice(ReportCorpus.UNIT_ANALYSIS).format(unit_name=unit_name_short, avg_score=unit_df['strong_test_score'].mean(), unit_paradigm=unit_paradigms.get(unit_name_short, "核心技术"), hacks=int(unit_df['hack_success'].sum()), hacked=int(unit_df['hacked_success'].sum())))

    strong_scores = df['strong_test_score'].dropna()
    if len(strong_scores) > 8:
        early_avg, later_avg = strong_scores.iloc[:len(strong_scores)//2].mean(), strong_scores.iloc[len(strong_scores)//2:].mean()
        if later_avg > early_avg + 1:
            print(random.choice(ReportCorpus.GROWTH_ANALYSIS).format(early_avg=early_avg, later_avg=later_avg))
            
    print("\n" + "--- 5. 提交行为与风险分析 ---".center(70))
    print(random.choice(ReportCorpus.SUBMISSION_ANALYSIS_INTRO))
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

    hack_strategy_texts = _analyze_hack_strategy(df)
    if hack_strategy_texts:
        print("\n" + "--- 6. 互测博弈策略分析 ---".center(70))
        print(random.choice(ReportCorpus.HACK_STRATEGY_INTRO))
        for text in hack_strategy_texts:
            print(text)

    print("\n" + "--- 7. 逐次作业深度解析 ---".center(70))
    print(random.choice(ReportCorpus.HW_ANALYSIS_INTRO))
    for _, hw in df.iterrows():
        print(f"\n--- {hw['name']} ---")
        if pd.notna(hw.get('strong_test_score')):
            score_str = f"  - 强测: {hw.get('strong_test_score'):.2f}"
            if hw.get('strong_test_deduction_count', 0) > 0:
                issue_str = ", ".join([f"{k}({v}次)" for k,v in hw.get('strong_test_issues', {}).items()])
                score_str += f" | 扣分: {issue_str}"
            print(score_str)
        if hw.get('has_mutual_test') and pd.notna(hw.get('hack_success')):
            hack_info = f"Hack {int(hw.get('hack_success', 0))} | 被成功Hack {int(hw.get('hacked_success', 0))} (被攻击 {int(hw.get('hacked_total_attempts', 0))} 次)"
            if pd.notna(hw.get('room_avg_hacked')):
                 hack_info += f" (房均被Hack: {hw.get('room_avg_hacked', 0):.2f})"
            print(f"  - 互测: 在 {hw.get('room_level', '?')} 房化身「{hw.get('alias_name', '?')}」，{hack_info}")
        
        if hw['unit'].startswith("第四单元"):
            print(format_uml_analysis(hw))
            
        print(f"  - 提交: {analyze_submission_style(hw)}")

    print("\n" + "="*80)
    print(" 学期旅程总结 ".center(80, "="))
    print("="*80)
    print(random.choice(ReportCorpus.OVERALL_CONCLUSION))

# --- 7. 主执行逻辑 ---
def main(student_id):
    try:
        if not student_id or not student_id.isdigit():
            raise ValueError(f"错误: '{CONFIG['YAML_CONFIG_PATH']}' 中未找到有效的 'stu_id'。")

        file_path = Path(CONFIG["FILE_PATH"])
        if not file_path.exists(): raise FileNotFoundError(f"错误: 未找到数据文件 '{file_path}'。")
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_json_data = json.load(f)
        
        find_and_update_user_info(student_id, raw_json_data, CONFIG)

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