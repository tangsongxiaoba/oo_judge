import sympy as sp
import random

# 定义符号变量
x, y = sp.symbols('x y')

# 中心化配置
_CONFIG = {
    # 值范围配置
    "coef_range": (-3, 3),           # 系数值范围
    "exponent_range": (0, 2),        # 指数值范围
    "trig_coef_range": (-3, 3),       # 三角函数内系数范围
    "trig_offset_range": (-3, 3),    # 三角函数内偏移量范围
    "trig_power_range": (0, 2),      # 三角函数的指数范围
    "const_range": (-5, 5),          # 常数范围
    
    # 项数量配置
    "max_terms": 4,                  # 表达式中的最大项数
    "max_sin_terms": 1,              # 最大sin项数量
    "max_cos_terms": 1,              # 最大cos项数量
    "max_n": 3,                      # 递推式最大n值
    "max_depth": 1,                  # 嵌套调用最大深度
    
    # 特殊值配置
    "special_coef": [0, 1, -1],      # 特殊系数值
    "special_exponent": [0, 1],      # 特殊指数值
    "special_trig_coef": [1],        # 特殊三角函数系数
    "special_trig_offset": [0],      # 特殊三角函数偏移量
    "special_trig_power": [1],       # 特殊三角函数指数
    "special_const": [0, 1, -1],     # 特殊常数
    "special_n": [0, 1, 2],          # 特殊n值
    "special_simple_expr": [0, 1, -1, 2, -2],  # 特殊简单表达式
    
    # 概率配置
    "special_coef_prob": 0.3,        # 选择特殊系数的概率
    "special_exponent_prob": 0.3,    # 选择特殊指数的概率
    "special_trig_coef_prob": 0.3,   # 选择特殊三角函数系数的概率
    "special_trig_offset_prob": 0.3, # 选择特殊三角函数偏移量的概率
    "special_trig_power_prob": 0.3,  # 选择特殊三角函数指数的概率
    "special_const_prob": 0.3,       # 选择特殊常数的概率
    "special_n_prob": 0.3,           # 选择特殊n值的概率
    "special_expr_prob": 0.3,        # 选择特殊表达式的概率
    "simple_vs_complex_prob": 0.5,   # 选择简单表达式vs复杂表达式的概率
    "add_constant_prob": 0.3,        # 添加常数项的概率
    "simple_params_prob": 0.3,       # 使用简单参数的概率
    "single_term_prob": 0.7,         # 生成单项的概率
    "single_factor_prob": 0.8,       # 生成单因子的概率
    "skip_nesting_prob": 0.7,        # 跳过嵌套的概率
}

# 辅助函数，生成带权重的随机整数
def weighted_random_int(min_val, max_val, special_values=None, special_weight=0.3):
    """
    生成一个随机整数，但对特殊值有更高的概率
    
    参数:
    - min_val, max_val: 整数范围
    - special_values: 特殊值列表，如[0, 1, -1]等
    - special_weight: 选择特殊值的概率
    """
    if special_values and random.random() < special_weight:
        return random.choice(special_values)
    return random.randint(min_val, max_val)

# 改进的复杂函数生成器
def generate_complex_expression(variable):
    """生成一个符合标准项形式的复杂符号表达式
    标准项形式: Σ(a * variable^b * Π(sin(expr_i)^c_i) * Π(cos(expr_i)^d_i))
    """
    # 决定项的数量
    num_terms = weighted_random_int(
        1, 
        _CONFIG["max_terms"], 
        [1], 
        _CONFIG["single_term_prob"]
    )
    terms = []
    
    for _ in range(num_terms):
        # 系数 - 增加特殊值的概率
        a = weighted_random_int(
            _CONFIG["coef_range"][0], 
            _CONFIG["coef_range"][1], 
            _CONFIG["special_coef"], 
            _CONFIG["special_coef_prob"]
        )
        if a == 0:  # 避免系数为0
            a = weighted_random_int(1, _CONFIG["coef_range"][1], [1], 0.7)
            
        # 指数 - 增加特殊值的概率
        b = weighted_random_int(
            _CONFIG["exponent_range"][0], 
            _CONFIG["exponent_range"][1], 
            _CONFIG["special_exponent"], 
            _CONFIG["special_exponent_prob"]
        )
        
        # sin项的数量
        num_sin_terms = weighted_random_int(
            0, 
            _CONFIG["max_sin_terms"], 
            [0, 1], 
            _CONFIG["single_factor_prob"]
        )
        sin_factors = []
        
        for _ in range(num_sin_terms):
            # 系数、偏移量和指数
            coef = weighted_random_int(
                _CONFIG["trig_coef_range"][0], 
                _CONFIG["trig_coef_range"][1], 
                _CONFIG["special_trig_coef"], 
                _CONFIG["special_trig_coef_prob"]
            )
            offset = weighted_random_int(
                _CONFIG["trig_offset_range"][0], 
                _CONFIG["trig_offset_range"][1], 
                _CONFIG["special_trig_offset"], 
                _CONFIG["special_trig_offset_prob"]
            )
            power = weighted_random_int(
                _CONFIG["trig_power_range"][0], 
                _CONFIG["trig_power_range"][1], 
                _CONFIG["special_trig_power"], 
                _CONFIG["special_trig_power_prob"]
            )
            sin_expr = sp.sin(coef * variable + offset) ** power
            sin_factors.append(sin_expr)
        
        # cos项的数量
        num_cos_terms = weighted_random_int(
            0, 
            _CONFIG["max_cos_terms"], 
            [0, 1], 
            _CONFIG["single_factor_prob"]
        )
        cos_factors = []
        
        for _ in range(num_cos_terms):
            # 系数、偏移量和指数
            coef = weighted_random_int(
                _CONFIG["trig_coef_range"][0], 
                _CONFIG["trig_coef_range"][1], 
                _CONFIG["special_trig_coef"], 
                _CONFIG["special_trig_coef_prob"]
            )
            offset = weighted_random_int(
                _CONFIG["trig_offset_range"][0], 
                _CONFIG["trig_offset_range"][1], 
                _CONFIG["special_trig_offset"], 
                _CONFIG["special_trig_offset_prob"]
            )
            power = weighted_random_int(
                _CONFIG["trig_power_range"][0], 
                _CONFIG["trig_power_range"][1], 
                _CONFIG["special_trig_power"], 
                _CONFIG["special_trig_power_prob"]
            )
            cos_expr = sp.cos(coef * variable + offset) ** power
            cos_factors.append(cos_expr)
        
        # 构建完整项
        term = a * (variable ** b)
        
        # 乘以所有sin因子
        for factor in sin_factors:
            term *= factor
            
        # 乘以所有cos因子
        for factor in cos_factors:
            term *= factor
            
        terms.append(term)
    
    # 合并所有项
    expression = 0
    for term in terms:
        expression += term
        
    return expression

# 定义递推函数的符号表示类
class RecursiveCall:
    def __init__(self, n, x_expr, y_expr):
        self.n = n
        self.x_expr = x_expr
        self.y_expr = y_expr
    
    def __str__(self):
        return f"f{{{self.n}}}(({self.x_expr}), ({self.y_expr}))"
    
    def __repr__(self):
        return self.__str__()

# 改进的X表达式生成器
def generate_x_expression(complexity=1):
    """生成关于x的表达式，complexity控制复杂度"""
    if complexity <= 0 or random.random() < _CONFIG["simple_vs_complex_prob"]:
        # 简单表达式 - 增加特殊值和边界值
        options = [
            x,                        # 单独变量x 
            weighted_random_int(1, _CONFIG["coef_range"][1], [1, 2], _CONFIG["special_coef_prob"]) * x,
            x**weighted_random_int(1, _CONFIG["exponent_range"][1], [1, 2], _CONFIG["special_exponent_prob"]),
            x + weighted_random_int(_CONFIG["const_range"][0], _CONFIG["const_range"][1], 
                                   _CONFIG["special_const"], _CONFIG["special_const_prob"]),
            weighted_random_int(_CONFIG["const_range"][0], _CONFIG["const_range"][1], 
                              _CONFIG["special_const"], _CONFIG["special_const_prob"])  # 纯常数
        ]
        return random.choice(options)
    else:
        # 复杂表达式 - 移除复杂的分数和指数，遵循标准项形式
        expr_options = [
            x ** weighted_random_int(
                _CONFIG["exponent_range"][0], 
                _CONFIG["exponent_range"][1], 
                _CONFIG["special_exponent"], 
                _CONFIG["special_exponent_prob"]
            ),
            weighted_random_int(
                1, 
                _CONFIG["coef_range"][1], 
                [1], 
                _CONFIG["special_coef_prob"]
            ) * x,
            sp.sin(
                weighted_random_int(
                    _CONFIG["trig_coef_range"][0], 
                    _CONFIG["trig_coef_range"][1], 
                    _CONFIG["special_trig_coef"], 
                    _CONFIG["special_trig_coef_prob"]
                ) * x + 
                weighted_random_int(
                    _CONFIG["trig_offset_range"][0], 
                    _CONFIG["trig_offset_range"][1], 
                    _CONFIG["special_trig_offset"], 
                    _CONFIG["special_trig_offset_prob"]
                )
            ),
            sp.cos(
                weighted_random_int(
                    _CONFIG["trig_coef_range"][0], 
                    _CONFIG["trig_coef_range"][1], 
                    _CONFIG["special_trig_coef"], 
                    _CONFIG["special_trig_coef_prob"]
                ) * x + 
                weighted_random_int(
                    _CONFIG["trig_offset_range"][0], 
                    _CONFIG["trig_offset_range"][1], 
                    _CONFIG["special_trig_offset"], 
                    _CONFIG["special_trig_offset_prob"]
                )
            )
        ]
        
        # 随机选择1-2个表达式相乘
        num_factors = weighted_random_int(
            1, 
            2, 
            [1], 
            _CONFIG["single_factor_prob"]
        )
        result = 1
        for _ in range(num_factors):
            factor = random.choice(expr_options)
            result *= factor
            
        # 加上一个常数的概率
        if random.random() < _CONFIG["add_constant_prob"]:
            result += weighted_random_int(
                _CONFIG["const_range"][0], 
                _CONFIG["const_range"][1], 
                _CONFIG["special_const"], 
                _CONFIG["special_const_prob"]
            )
            
        return result

# 嵌套函数调用生成器
def generate_nested_call(n, max_depth=2):
    """
    生成嵌套递推函数调用，返回RecursiveCall对象
    """
    # 增加直接返回基础表达式的概率
    if max_depth == 0 or random.random() > _CONFIG["skip_nesting_prob"]:
        # 一定概率直接返回x或特殊表达式
        if random.random() < _CONFIG["special_expr_prob"]:
            special_exprs = [x] + _CONFIG["special_simple_expr"]
            return random.choice(special_exprs)
        else:
            return generate_x_expression()
    
    # 嵌套递推函数调用
    # 增加边界情况n=0和n=1的概率
    nested_n = weighted_random_int(
        0, 
        max(n - 1, 1), 
        _CONFIG["special_n"], 
        _CONFIG["special_n_prob"]
    )
    
    # 增加简单参数的概率
    if random.random() < _CONFIG["simple_params_prob"]:
        # 一定概率使用特殊简单参数
        special_params = [x] + _CONFIG["special_simple_expr"]
        x_nested = random.choice(special_params)
        y_nested = random.choice(special_params)
    else:
        # 正常生成嵌套调用
        x_nested = generate_nested_call(nested_n, max_depth - 1)
        y_nested = generate_nested_call(nested_n, max_depth - 1)
    
    return RecursiveCall(nested_n, x_nested, y_nested)

# 定义递推函数实际计算
# 定义递推函数实际计算
def recursive_function(n, x_expr, y_expr):
    """
    实现递推关系计算：
    f_n(x, y) = a * f_{n-1}(g(x, y), h(x, y)) + b * f_{n-2}(g'(x, y), h'(x, y)) + i(x, y)
    """
    if n == 0:
        return f0.subs({x: x_expr, y: y_expr})
    elif n == 1:
        return f1.subs({x: x_expr, y: y_expr})
    else:
        # 递归调用
        f_n_minus_1 = recursive_function(
            n - 1,
            g.subs({x: x_expr, y: y_expr}),
            h.subs({x: x_expr, y: y_expr}),
        )
        f_n_minus_2 = recursive_function(
            n - 2,
            g_prime.subs({x: x_expr, y: y_expr}),
            h_prime.subs({x: x_expr, y: y_expr}),
        )
        return a * f_n_minus_1 + b * f_n_minus_2 + i.subs({x: x_expr})

# 符号计算函数
def evaluate_symbolic(expr):
    """进行符号计算，保持表达式形式"""
    if isinstance(expr, RecursiveCall):
        x_result = evaluate_symbolic(expr.x_expr)
        y_result = evaluate_symbolic(expr.y_expr)
        return recursive_function(expr.n, x_result, y_result)
    else:
        return expr

# 主函数，用于生成和求解递推式问题
def generate_recursive_problem():
    # 定义递推关系中的函数
    global g, h, g_prime, h_prime, i, f0, f1, a, b
    
    g = generate_complex_expression(x)
    h = generate_complex_expression(y)
    g_prime = generate_complex_expression(x)
    h_prime = generate_complex_expression(y)
    i = generate_complex_expression(x)

    # 定义初始条件
    f0 = generate_complex_expression(x) + generate_complex_expression(y)
    f1 = generate_complex_expression(x) * generate_complex_expression(y)

    # 随机生成系数，增加特殊值的概率
    a = weighted_random_int(
        _CONFIG["coef_range"][0], 
        _CONFIG["coef_range"][1], 
        _CONFIG["special_coef"], 
        _CONFIG["special_coef_prob"]
    )
    if a == 0:  # 避免系数为0
        a = weighted_random_int(1, _CONFIG["coef_range"][1], [1], 0.7)
        
    b = weighted_random_int(
        _CONFIG["coef_range"][0], 
        _CONFIG["coef_range"][1], 
        _CONFIG["special_coef"], 
        _CONFIG["special_coef_prob"]
    )
    if b == 0:  # 避免系数为0
        b = weighted_random_int(1, _CONFIG["coef_range"][1], [1], 0.7)

    # 打印递推函数定义
    # print("递推函数定义：")
    # print(f"f{{0}}(x,y) = {f0}")
    # print(f"f{{1}}(x,y) = {f1}")
    # print(f"f{{n}}(x,y) = {a} * f(n-1)({g}, {h}) + {b} * f(n-2)({g_prime}, {h_prime}) + {i}")

    # 随机选择n，增加特殊值的概率
    n = weighted_random_int(
        2, 
        _CONFIG["max_n"], 
        _CONFIG["special_n"], 
        _CONFIG["special_n_prob"]
    )
    
    # max_depth = weighted_random_int(
    #     1, 
    #     _CONFIG["max_depth"], 
    #     [0], 
    #     _CONFIG["single_factor_prob"]
    # )

    max_depth = 0

    # 生成嵌套表达式
    x_expr = generate_nested_call(n, max_depth=max_depth)
    y_expr = generate_nested_call(n, max_depth=max_depth)

    # print("\n生成的嵌套表达式：")
    # print(f"x_expr = {x_expr}")
    # print(f"y_expr = {y_expr}")

    # 创建最终调用
    final_call = RecursiveCall(n, x_expr, y_expr)
    # print(f"\n最终递推函数调用：")
    # print(final_call)

    # 符号计算
    # print("\n尝试符号计算结果:")
    try:
        symbolic_result = evaluate_symbolic(final_call)
        # 尝试简化结果
        # simplified_result = sp.simplify(symbolic_result)
        # print(f"符号结果 = {symbolic_result}")
        return {
            "definition": {
                "f0": "f{0}(x,y) = " + str(f0),
                "f1": "f{1}(x,y) = " + str(f1),
                "fn": f"f{{n}}(x,y) = {a} * f{{n-1}}(({g}), ({h})) + {b} * f{{n-2}}(({g_prime}), ({h_prime})) + {i}"
            },
            "call": final_call,
            "result": symbolic_result
        }
    except Exception as e:
        print(f"符号计算出错: {e}")
        print("嵌套层次可能太深，导致计算太复杂。尝试减少max_depth参数或减少表达式复杂度。")
        return None

# 允许调整配置参数的函数
def update_config(new_config):
    """
    更新配置参数
    
    参数:
    - new_config: 包含需要更新的配置项的字典
    """
    global _CONFIG
    for key, value in new_config.items():
        if key in _CONFIG:
            _CONFIG[key] = value
        else:
            print(f"警告: 配置项 '{key}' 不存在，将被忽略")

# 如果直接运行这个脚本
if __name__ == "__main__":
    # 可选: 在这里调整配置参数
    # 例如，如果想要更简单的表达式:
    # update_config({
    #     "max_terms": 1,
    #     "max_sin_terms": 1,
    #     "max_cos_terms": 1,
    #     "max_depth": 1,
    #     "simple_vs_complex_prob": 0.7
    # })
    
    # 生成问题
    problem = generate_recursive_problem()
    
    # 如果需要，可以进一步处理 problem 字典
