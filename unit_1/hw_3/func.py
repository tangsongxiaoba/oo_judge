import sympy as sp
import random
import pprint
from typing import Any, Dict, List, Optional, Union
from functools import partial

# 中心化配置
_CONFIG: Dict[str, Any] = {
    # complex expr
    # terms:
    "max_terms": 4,               # 表达式中的最大项数
    "spcial_term_cnt": [1],       # 表达式特殊项数
    "special_term_cnt_prob": 0.5, # 生成特殊项数的概率
    # for each term:
    # coef:
    "coef_range": (-3, 3),                    # 系数值范围
    "special_coef": [0, 1, -1],  # 特殊系数值
    "special_coef_prob": 0.5,                 # 选择特殊系数的概率
    # var_exp:
    "exp_range": (0, 3),                 # 指数值范围
    "special_exponent": [0, 1, 0, 1, 1, 0, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 4], # 特殊指数值
    "special_exponent_prob": 0.3,        # 选择特殊指数的概率
    # expr_factor/diff_factor:
    "max_expr_terms": 2,
    "special_expr_cnt": [0, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 1, 0, 1, 0],
    "special_expr_prob": 0.6,
    # for each expr_factor/diff_factor:
    "expr_coef_range": (-2, 2),
    "special_expr_coef": [0, -1, 1, 1, 1, 2],
    "special_expr_coef_prob": 0.75,
    "expr_offset_range": (-2, 2),
    "special_expr_offset": [0, -1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 2],
    "special_expr_offset_prob": 0.75,
    "expr_power_range": (1, 2),
    "special_expr_power": [1, 1, 1, 0],
    "special_expr_power_prob": 0.75,
    # trig:
    "max_trig_terms": 2,       # 最大trig项数量
    "spcial_trig_cnt": [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2], # 表达式特殊trig项数
    "special_trig_prob": 0.65,  # 生成特殊trig项数的概率
    # for each trig:
    "trig_coef_range": (-3, 3),                    # 三角函数内系数范围
    "special_trig_coef": [0, 1, -1, -1, -1, 2],    # 特殊三角函数系数
    "special_trig_coef_prob": 0.6,                 # 选择特殊三角函数系数的概率
    "trig_offset_range": (-3, 3),                  # 三角函数内偏移量范围
    "special_trig_offset": [0, 1, -1, -1, -1, -2], # 特殊三角函数偏移量
    "special_trig_offset_prob": 0.5,               # 选择特殊三角函数偏移量的概率
    "trig_power_range": (0, 4),                    # 三角函数的指数范围
    "special_trig_power": [0, 0, 2, 2],            # 特殊三角函数指数
    "special_trig_power_prob": 0.5,                # 选择特殊三角函数指数的概率
    # after terms:
    "add_constant_prob": 0.7,                      # 添加常数项的概率
    "const_range": (-5, 5),                        # 常数范围
    "special_const": [0, 1, -1, 666, -114514],     # 特殊常数
    "special_const_prob": 0.3,       # 选择特殊常数的概率
    
    "max_n": 3,                      # 递推式最大n值
    "special_n": [0, 1, 0, 1, 1, 0, 0, 2, 2, 1, 0, 1, 1, 0, 1, 2, 2, 1, 1, 1],          # 特殊n值
    "special_n_prob": 0.9,           # 选择特殊n值的概率
    
    "max_depth": 0,                  # 嵌套调用最大深度
    "skip_nesting_prob": 0.3,        # 跳过嵌套的概率
    "special_expr_prob": 0.3,        # 选择特殊表达式的概率
    "special_simple_expr": [0, 1, -1, 2, -2],  # 特殊简单表达式
    "simple_params_prob": 0.75,       # 使用简单参数的概率
    
    # 参数互换
    "swap_probablity": 0.5,

    # 自定义函数属性
    "max_func_terms": 2,
    "special_func_cnt": [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 1, 1, 1, 2],
    "special_func_prob": 0.8,
    "max_para_terms": 2,
    "special_para_cnt": [1, 1, 2, 1, 1,1, 1,1,1,1,1,1,1,1,1,1,1, 1, 2, 1, 2, 1, 1, 2, 1],
    "special_para_prob": 0.8,
    "max_func_use_terms": 1,
    "special_func_use_cnt": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "special_func_use_prob": 0.95,
}

def _custom_random(min_val: int, 
                   max_val: int, 
                   special_values: Optional[List[Any]] = None, 
                   special_weight: float = 0.3) -> int:
    """
    生成一个随机整数，但对特殊值有更高的概率

    参数:
    - min_val: 整数，范围下限
    - max_val: 整数，范围上限
    - special_values: 可选的特殊值列表 (例如 [0, 1, -1])
    - special_weight: 选择特殊值的概率

    返回:
    - 随机生成的整数
    """
    if special_values and random.random() < special_weight:
        return random.choice(special_values)
    ret = 0
    if max_val < min_val:
        ret = min_val
    else:
        ret = random.randint(min_val, max_val)
    if ret == 0:
        return random.choice(special_values)
    return ret

def _generate_expression(variable: List[sp.Expr], max_depth: int = 1, complexity: float = 1.0, exception=[]) -> sp.Expr:
    """
    生成一个复杂符号表达式
    标准项形式: Σ(a * variable^b * Π(sin(expr_i)^c_i) * Π(cos(expr_i)^d_i))
    
    参数:
    - variable: sympy表达式（通常为符号变量 x 或 y）
    - max_depth: 嵌套深度
    - complexity: 复杂度

    返回:
    - 生成的复杂表达式 (sp.Expr)
    """

    # 决定项的数量
    num_terms: int = _custom_random(
        0, 
        max(1, int(_CONFIG["max_terms"] * complexity)), 
        _CONFIG["spcial_term_cnt"], 
        _CONFIG["special_term_cnt_prob"]
    )

    terms: List[sp.Expr] = []
    
    extreme_factor = 0.0

    adj_cmpl = complexity

    for _ in range(max(1, num_terms)):
        adj_cmpl = max(0.1, adj_cmpl * (1.0 - extreme_factor))

        # 系数 - 增加特殊值的概率
        a: int = _custom_random(
            int(_CONFIG["coef_range"][0] * adj_cmpl), 
            int(_CONFIG["coef_range"][1] * adj_cmpl), 
            _CONFIG["special_coef"], 
            _CONFIG["special_coef_prob"]
        )
        
        # 指数 - 增加特殊值的概率
        b: int = _custom_random(
            _CONFIG["exp_range"][0], 
            int(_CONFIG["exp_range"][1] * adj_cmpl), 
            _CONFIG["special_exponent"], 
            _CONFIG["special_exponent_prob"]
        )

        if abs(b) > _CONFIG["exp_range"][1] * 0.7:
            extreme_factor += 0.1
        elif abs(b) < _CONFIG["exp_range"][1] * 0.3:
            extreme_factor -= 0.1
        
        # 总trig项的数量
        num_trig_factors: int = _custom_random(
            0, 
            max(1, int(_CONFIG["max_trig_terms"] * adj_cmpl)), 
            _CONFIG["spcial_trig_cnt"], 
            _CONFIG["special_trig_prob"]
        )

        # 总expr项数量
        num_expr_factors: int = _custom_random(
            0,
            max(1, int(_CONFIG["max_expr_terms"] * adj_cmpl)),
            _CONFIG["special_expr_cnt"],
            _CONFIG["special_expr_prob"]
        )

        num_sin_factors: int = random.randint(0, num_trig_factors)
        num_cos_factors: int = num_trig_factors - num_sin_factors
        sin_factors: List[sp.Expr] = []
        cos_factors: List[sp.Expr] = []
        expr_factors: List[sp.Expr] = []

        cur_max_depth = max(0, int(max_depth * adj_cmpl))

        for _ in range(num_expr_factors):
            power: int = _custom_random(
                _CONFIG["expr_power_range"][0], 
                int(_CONFIG["expr_power_range"][1] * adj_cmpl), 
                _CONFIG["special_expr_power"], 
                _CONFIG["special_expr_power_prob"]
            )

            if power > _CONFIG["expr_power_range"][1] * 0.7:
                extreme_factor += 0.1  # 增加极端因子
            elif power < _CONFIG["expr_power_range"][1] * 0.3:
                extreme_factor -= 0.1

            # 同时生成求导因子
            if (cur_max_depth <= 0):
                coef: int = _custom_random(
                        int(_CONFIG["expr_coef_range"][0] * adj_cmpl),
                        int(_CONFIG["expr_coef_range"][1] * adj_cmpl), 
                        _CONFIG["special_expr_coef"], 
                        _CONFIG["special_expr_coef_prob"]
                    )
                offset: int = _custom_random(
                    int(_CONFIG["expr_offset_range"][0] * adj_cmpl), 
                    int(_CONFIG["expr_offset_range"][1] * adj_cmpl), 
                    _CONFIG["special_expr_offset"], 
                    _CONFIG["special_expr_offset_prob"]
                )  
                expr_expr: sp.Expr = (coef * random.choice(variable) + offset) ** power       
            else:
                nxt_cmpl = adj_cmpl * 1.1
                expr_expr: sp.Expr = (_generate_expression(variable, max_depth-1, nxt_cmpl)) ** power
            
            expr_factors.append(expr_expr)
        
        for _ in range(num_sin_factors):
            power: int = _custom_random(
                _CONFIG["trig_power_range"][0], 
                int(_CONFIG["trig_power_range"][1] * adj_cmpl), 
                _CONFIG["special_trig_power"], 
                _CONFIG["special_trig_power_prob"]
            )

            if power > _CONFIG["trig_power_range"][1] * 0.7:
                extreme_factor += 0.1  # 增加极端因子
            elif power < _CONFIG["trig_power_range"][1] * 0.3:
                extreme_factor -= 0.1

            if (cur_max_depth <= 0):
                coef: int = _custom_random(
                    int(_CONFIG["trig_coef_range"][0] * adj_cmpl),
                    int(_CONFIG["trig_coef_range"][1] * adj_cmpl), 
                    _CONFIG["special_trig_coef"], 
                    _CONFIG["special_trig_coef_prob"]
                )
                offset: int = _custom_random(
                    int(_CONFIG["trig_offset_range"][0] * adj_cmpl), 
                    int(_CONFIG["trig_offset_range"][1] * adj_cmpl), 
                    _CONFIG["special_trig_offset"], 
                    _CONFIG["special_trig_offset_prob"]
                )
                sin_expr: sp.Expr = sp.sin(coef * random.choice(variable) + offset) ** power        
            else:
                nxt_cmpl = adj_cmpl * 0.8
                sin_expr: sp.Expr = sp.sin(_generate_expression(variable, max_depth-1, nxt_cmpl)) ** power
            sin_factors.append(sin_expr)

        for _ in range(num_cos_factors):
            power: int = _custom_random(
                _CONFIG["trig_power_range"][0], 
                int(_CONFIG["trig_power_range"][1] * adj_cmpl), 
                _CONFIG["special_trig_power"], 
                _CONFIG["special_trig_power_prob"]
            )

            if power > _CONFIG["trig_power_range"][1] * 0.7:
                extreme_factor += 0.1  # 增加极端因子
            elif power < _CONFIG["trig_power_range"][1] * 0.3:
                extreme_factor -= 0.1

            if (cur_max_depth <= 0):
                coef: int = _custom_random(
                    int(_CONFIG["trig_coef_range"][0] * adj_cmpl), 
                    int(_CONFIG["trig_coef_range"][1] * adj_cmpl), 
                    _CONFIG["special_trig_coef"], 
                    _CONFIG["special_trig_coef_prob"]
                )
                offset: int = _custom_random(
                    int(_CONFIG["trig_offset_range"][0] * adj_cmpl), 
                    int(_CONFIG["trig_offset_range"][1] * adj_cmpl), 
                    _CONFIG["special_trig_offset"], 
                    _CONFIG["special_trig_offset_prob"]
                )

                cos_expr: sp.Expr = sp.cos(coef * random.choice(variable) + offset) ** power        
            else:
                nxt_cmpl = adj_cmpl * 0.8
                cos_expr: sp.Expr = sp.cos(_generate_expression(variable, max_depth-1, nxt_cmpl)) ** power
            cos_factors.append(cos_expr)
        global ret
        func_factors = []
        if ret and len(exception) != 2:
            func_num: int = _custom_random(
                0,
                max(1, _CONFIG["max_func_use_terms"]),
                _CONFIG["special_func_use_cnt"],
                _CONFIG["special_func_prob"]
            )
            for _ in range(func_num):
                can_get = [key for key in ret.keys() if ret[key]["true_func"] not in exception]
                func = random.choice(can_get)
                nxt_cmpl = adj_cmpl * 0.6
                if ret[func]["para_num"] == 1:
                    func_factors.append(ret[func]["true_func"](_generate_expression(variable, max_depth -1, nxt_cmpl, exception)))
                else:
                    func_factors.append(ret[func]["true_func"](_generate_expression(variable, max_depth - 1, nxt_cmpl, exception), _generate_expression(variable, max_depth - 1, nxt_cmpl, exception)))

        term: sp.Expr = a * (random.choice(variable) ** b)
        for factor in sin_factors:
            term *= factor
        for factor in cos_factors:
            term *= factor
        for factor in expr_factors:
            term *= factor
        for factor in func_factors:
            term *= factor
        terms.append(term)
    
    expression: sp.Expr = 0
    for term in terms:
        expression += term
    
    if (random.random() < _CONFIG["add_constant_prob"]):
        const_num: int = _custom_random(
            _CONFIG["const_range"][0],
            _CONFIG["const_range"][1],
            _CONFIG["special_const"],
            _CONFIG["special_const_prob"]
        )
        expression += const_num
        
    return expression

class RecursiveCall:
    def __init__(self, n: int, x_expr: Union[sp.Expr, 'RecursiveCall', Any], y_expr: Union[sp.Expr, 'RecursiveCall', Any]) -> None:
        """
        初始化递归调用的符号表示

        参数:
        - n: 递归深度或阶数
        - x_expr: x方向的表达式
        - y_expr: y方向的表达式
        """
        self.n: int = n
        self.x_expr: Union[sp.Expr, RecursiveCall, Any] = x_expr
        self.y_expr: Union[sp.Expr, RecursiveCall, Any] = y_expr
    
    def __str__(self) -> str:
        return f"f{{{self.n}}}(({self.x_expr}), ({self.y_expr}))"
    
    def __repr__(self) -> str:
        return self.__str__()

def _generate_nested_call(n: int, max_depth: int = 2) -> Union[RecursiveCall, sp.Expr]:
    """
    生成嵌套递推函数调用，返回 RecursiveCall 对象或简单表达式

    参数:
    - n: 当前的递归阶数
    - max_depth: 嵌套调用的最大深度

    返回:
    - RecursiveCall 对象或一个 sympy 表达式
    """
    if max_depth == 0 or random.random() > _CONFIG["skip_nesting_prob"]:
        # 一定概率直接返回x或特殊表达式
        if random.random() < _CONFIG["special_expr_prob"]:
            special_exprs: List[Union[sp.Expr, int]] = [_x] + _CONFIG["special_simple_expr"]
            return random.choice(special_exprs)
        else:
            return _generate_expression([_x], 0, 0.3)
    
    nested_n: int = _custom_random(
        0, 
        max(n - 1, 1), 
        _CONFIG["special_n"], 
        _CONFIG["special_n_prob"]
    )
    
    # 增加简单参数的概率
    if random.random() < _CONFIG["simple_params_prob"]:
        # 一定概率使用特殊简单参数
        special_params: List[Union[sp.Expr, int]] = [_x] + _CONFIG["special_simple_expr"]
        x_nested: Union[sp.Expr, int] = random.choice(special_params)
        y_nested: Union[sp.Expr, int] = random.choice(special_params)
    else:
        # 正常生成嵌套调用
        x_nested = _generate_nested_call(nested_n, max_depth - 1)
        y_nested = _generate_nested_call(nested_n, max_depth - 1)
    
    return RecursiveCall(nested_n, x_nested, y_nested)

def _recursive_function(n: int, x_expr: sp.Expr, y_expr: sp.Expr) -> sp.Expr:
    """
    实现递推关系计算：
    f_n(x, y) = a * f_{n-1}(g(x, y), h(x, y)) + b * f_{n-2}(g'(x, y), h'(x, y)) + i(x, y)

    参数:
    - n: 递推的阶数
    - x_expr: x方向的表达式 (sp.Expr)
    - y_expr: y方向的表达式 (sp.Expr)

    返回:
    - 计算得到的表达式 (sp.Expr)
    """
    orig_dict = {_x: x_expr, _y: y_expr}
    if n == 0:
        return f0.subs(orig_dict)
    elif n == 1:
        return f1.subs(orig_dict)
    else:
        # 递归调用
        f_n_minus_1 = _recursive_function(
            n - 1,
            g.subs(orig_dict),
            h.subs(orig_dict)
        )
        f_n_minus_2 = _recursive_function(
            n - 2,
            w.subs(orig_dict),
            v.subs(orig_dict)
        )
        return a * f_n_minus_1 + b * f_n_minus_2 + i.subs(orig_dict)

def _evaluate_symbolic(expr: Union[RecursiveCall, sp.Expr]) -> sp.Expr:
    """
    进行符号计算，保持表达式形式

    参数:
    - expr: 可能为 RecursiveCall 对象或 sympy 表达式

    返回:
    - 计算后的 sympy 表达式
    """
    if isinstance(expr, RecursiveCall):
        x_result: sp.Expr = _evaluate_symbolic(expr.x_expr)
        y_result: sp.Expr = _evaluate_symbolic(expr.y_expr)
        return _recursive_function(expr.n, x_result, y_result)
    else:
        return expr

def _add_extra_parentheses(expr):
    """
    在所有sin()和cos()函数调用内部添加额外的括号
    例如: sin(x+y) -> sin((x+y))，sin(cos(x)) -> sin((cos((x))))
    """
    i = 0
    result = ""
    global ret
    while i < len(expr):
        # 检查是否有sin或cos函数调用
        if i + 3 < len(expr) and expr[i:i+3] == "sin" and expr[i+3] == "(":
            result += "sin("
            # 找到对应的右括号
            open_paren_pos = i + 3
            extra, closing_paren_pos = _find_matching_paren(expr, open_paren_pos)
            
            # 递归处理括号内的内容
            inner_content = _add_extra_parentheses(expr[open_paren_pos+1:closing_paren_pos])
            result += "(" + inner_content + "))"
            
            i = closing_paren_pos + 1
        elif i + 3 < len(expr) and expr[i:i+3] == "cos" and expr[i+3] == "(":
            result += "cos("
            # 找到对应的右括号
            open_paren_pos = i + 3
            extra, closing_paren_pos = _find_matching_paren(expr, open_paren_pos)
            
            # 递归处理括号内的内容
            inner_content = _add_extra_parentheses(expr[open_paren_pos+1:closing_paren_pos])
            result += "(" + inner_content + "))"
            
            i = closing_paren_pos + 1
        elif i + 1 < len(expr) and (expr[i] == "g" or expr[i] == "h") and expr[i+1] == '(':
            result += f"({expr[i]}("
            open_paren_pos = i + 1
            if ret[expr[i]]["para_num"] == 1:
                extra, closing_paren_pos = _find_matching_paren(expr, open_paren_pos)
                
                # 递归处理括号内的内容
                inner_content = _add_extra_parentheses(expr[open_paren_pos+1:closing_paren_pos])
                result += "(" + inner_content + ")))"
            else :
                extra, closing_paren_pos = _find_matching_paren(expr, open_paren_pos, True)
                # 递归处理括号内的内容
                inner_content = _add_extra_parentheses(expr[open_paren_pos+1:closing_paren_pos])
                result += "(" + inner_content + "),"
                
                open_paren_pos = closing_paren_pos
                extra, closing_paren_pos = _find_matching_paren(expr, open_paren_pos, False)
                inner_content = _add_extra_parentheses(expr[open_paren_pos+1:closing_paren_pos])
                result += "(" + inner_content + ")))"
            
            i = closing_paren_pos + 1
        else:
            result += expr[i]
            i += 1
    
    return result

def _find_matching_paren(expr, open_pos, comma=False):
    """
    找到与open_pos位置的左括号匹配的右括号
    返回括号内的内容和右括号的位置
    """
    # assert expr[open_pos] == "("
    if expr[open_pos] == "(" or expr[open_pos] == ",":
        pass
    else:
        raise Exception
    stack = 1  # 已经有一个左括号
    i = open_pos + 1
    not_find = True
    while i < len(expr) and stack > 0:
        if expr[i] == "(":
            stack += 1
        elif expr[i] == ")":
            stack -= 1
        elif comma and expr[i] == ',':
            if stack == 1:
                stack -= 1
                i += 1
                break
        i += 1
    
    if stack != 0:
        raise ValueError("括号不匹配")
    
    closing_pos = i - 1
    return expr[open_pos+1:closing_pos], closing_pos

def generate_function_problem():
    global _x, _y
    global _g, _h
    global func_locals
    func_locals = {}
    func_num: int = _custom_random(
        0,
        max(1, _CONFIG["max_func_terms"]),
        _CONFIG["special_func_cnt"],
        _CONFIG["special_func_prob"]
    )
    func_names = [
        {"func_name": "g", "true_func": _g},
        {"func_name": "h", "true_func": _h}
    ]
    random.shuffle(func_names)
    global ret
    ret = {}
    for i in range(func_num):
        func_name = func_names[i]["func_name"]
        ret[func_name] = {}
        ret[func_name]["true_func"] = func_names[i]["true_func"]
        paras = [_x, _y]
        para_num: int = _custom_random(
            1,
            max(1, _CONFIG["max_para_terms"]),
            _CONFIG["special_para_cnt"],
            _CONFIG["special_para_prob"]
        )
        generate_paras = []
        if para_num == 2:
            random.shuffle(paras)
            generate_paras = paras
            ret[func_name]["paras"] = ["x", "y"] if generate_paras[0] == _x else ["y", "x"]
            ret[func_name]["para_num"] = 2
        else:
            generate_paras.append(random.choice(paras))
            ret[func_name]["paras"] = ["x"] if generate_paras[0] == _x else ["y"]
            ret[func_name]["para_num"] = 1
        abort = []
        if i == 0:
            abort = [_g, _h]
        else:
            abort = [_g] if func_name == "g" else [_h]
        expr = _generate_expression(generate_paras, 0.3, exception=abort)
        ret[func_name]["expr"] = expr
        expr_str = f"{expr}"
        if func_locals and expr.has(_g if func_name == "h" else _h):
            expr = sp.sympify(expr_str, locals=func_locals)

        def create_func(expr, u, v=None):
            if v is None:
                return partial(lambda a: expr.subs({u: a}))
            return partial(lambda a, b: expr.subs({u: a, v: b}))

        # 赋值时创建独立作用域
        if ret[func_name]["para_num"] == 1:
            u = generate_paras[0]
            ret[func_name]["func"] = create_func(expr, u)
        else:
            u = generate_paras[0]
            v = generate_paras[1]
            ret[func_name]["func"] = create_func(expr, u, v)

        func_locals[func_name] = ret[func_name]["func"]
def generate_recursive_problem() -> Optional[Dict[str, Any]]:
    """
    主函数，用于生成和求解递推式问题

    返回:
    - 一个包含递推式定义、调用和计算结果的字典，若计算失败则返回 None
    """
    global _g, _h
    _g = sp.Function("g")
    _h = sp.Function("h")
    
    # 定义递推关系中的函数，使用全局变量
    global g, h, w, v, i, f0, f1, a, b

    global _x, _y
    _x, _y = sp.symbols('x y')
    generate_function_problem()
    # pprint.pprint(ret)
    global func_locals
    # f{n}(x, y) = a * f{n-1}(g(x, y), h(x, y)) + b * f{n-2}(w(x, y), v(x, y)) + i(x, y)

    g = _generate_expression([_x, _y], 1, 0.5)
    h = _generate_expression([_x, _y], 1, 0.5)
    w = _generate_expression([_x, _y], 1, 0.5)
    v = _generate_expression([_x, _y], 1, 0.5)
    i = _generate_expression([_x, _y], 1, 0.5)

    # 定义初始条件
    f0 = _generate_expression([_x, _y], 1, 0.85)
    f1 = _generate_expression([_x, _y], 1, 0.85)

    a = _custom_random(
        _CONFIG["coef_range"][0], 
        _CONFIG["coef_range"][1], 
        _CONFIG["special_coef"], 
        _CONFIG["special_coef_prob"]
    )
        
    b = _custom_random(
        _CONFIG["coef_range"][0], 
        _CONFIG["coef_range"][1], 
        _CONFIG["special_coef"], 
        _CONFIG["special_coef_prob"]
    )

    # 随机选择 n，增加特殊值的概率
    n: int = _custom_random(
        0, 
        _CONFIG["max_n"], 
        _CONFIG["special_n"], 
        _CONFIG["special_n_prob"]
    )
    
    max_depth: int = _custom_random(
        0, 
        _CONFIG["max_depth"], 
        [0], 
        _CONFIG["special_trig_prob"]
    )

    # 生成嵌套表达式
    args = []
    x_expr = _generate_nested_call(n, max_depth=max_depth)
    y_expr = _generate_nested_call(n, max_depth=max_depth)
    if random.randint(0, 1) == 0:
        args.append(f"dx({x_expr})")
        x_expr = sp.diff(sp.sympify(f"{x_expr}", locals=func_locals))
    else:
        args.append(f"({x_expr})")
    if random.randint(0, 1) == 0:
        args.append(f"dx({y_expr})")
        y_expr = sp.diff(sp.sympify(f"{y_expr}", locals=func_locals))
    else:
        args.append(f"({y_expr})")

    final_call = RecursiveCall(n, x_expr, y_expr)
    try:
        symbolic_result = _evaluate_symbolic(final_call)
        # print(f"Original:{symbolic_result}")
        symbolic_result = sp.sympify(str(symbolic_result), locals=func_locals)
        final_call_str = str(final_call)

        f0_def = "f{0}(x,y) = " + str(f0)
        f1_def = "f{1}(x,y) = " + str(f1)
        fn_def = f"f{{n}}(x,y) = {a} * f{{n-1}}(({g}), ({h})) + {b} * f{{n-2}}(({w}), ({v})) + {i}"
            
        f0_def = _add_extra_parentheses(f0_def).replace("**", "^")
        f1_def = _add_extra_parentheses(f1_def).replace("**", "^")
        fn_def = _add_extra_parentheses(fn_def).replace("**", "^")
        args = [_add_extra_parentheses(arg).replace("**", "^") for arg in args]
        ret_dict = {
            "definition": {
                "f0": f0_def, 
                "f1": f1_def,
                "fn": fn_def
            },
            "call": final_call_str,
            "actual_call": final_call_str[:4],
            "args": args,
            "result": symbolic_result
        }
        ret_dict["self_func"] = []
        for key in ret.keys():
            func_body = _add_extra_parentheses(str(ret[key]["expr"])).replace("**", "^")
            func_str = f"{key}({','.join(ret[key]['paras'])})={func_body}"
            ret_dict["self_func"].append(func_str) 
        return ret_dict
    except Exception as e:
        print(f"符号计算出错: {e}")
        print("嵌套层次可能太深，导致计算太复杂。尝试减少max_depth参数或减少表达式复杂度。")
        return None

def update_config(new_config: Dict[str, Any]) -> None:
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

if __name__ == "__main__":
    while True:
        res = generate_recursive_problem()
        def_str = [res["definition"]["f0"], res["definition"]["f1"], res["definition"]["fn"]]
        random.shuffle(def_str)
        func_str = "\n".join(res["self_func"])
        if func_str != "":
            func_str = func_str + "\n"
        que_str = f"{len(res['self_func'])}\n" + f"{func_str}" + "1\n" + def_str[0] + '\n' + def_str[1] + '\n' + def_str[2] + '\n' + f"{res['actual_call']}({res['args'][0]},{res['args'][1]})"
        ans_str = res['result']
        pprint.pprint(res)
        print(que_str)
        pass