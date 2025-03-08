# hw_1/gen.py
import re
import random

import sympy
from sympy import symbols, expand

class TestGenerator:
    # 全局配置
    _CONFIG = {
        "max_depth": 2,           # 最大嵌套深度
        "max_terms": 4,           # 表达式中最大项数
        "max_factors": 3,         # 项中最大因子数
        "max_whitespace": 2,      # 最大空白字符数
        "max_integer": 666,       # 最大整数值
        "max_exponent": 8,        # 最大指数值
        "leading_zero_prob": 0.3, # 前导零概率
    }

    @staticmethod
    def _generate_whitespace():
        """生成随机空白字符串"""
        whitespace_chars = [' ', '\t']
        length = random.randint(0, TestGenerator._CONFIG["max_whitespace"])
        return ''.join(random.choice(whitespace_chars) for _ in range(length))

    @staticmethod
    def _generate_integer(allow_sign=True, allow_zero=True, min_val=None, max_val=None):
        """生成带符号整数"""
        if min_val is None:
            min_val = -TestGenerator._CONFIG["max_integer"]
        if max_val is None:
            max_val = TestGenerator._CONFIG["max_integer"]
            
        # 决定是否生成前导零
        has_leading_zero = random.random() < TestGenerator._CONFIG["leading_zero_prob"]
        
        # 生成数值
        if allow_zero:
            value = random.randint(min_val, max_val)
        else:
            # 确保非零
            if min_val == 0:
                value = random.randint(1, max_val)
            elif max_val == 0:
                value = random.randint(min_val, -1)
            else:
                value = random.randint(min_val, max_val)
                if value == 0:
                    value = 1
        
        # 生成符号
        sign = ""
        if allow_sign and value > 0 and random.choice([True, False]):
            sign = "+"
        elif value < 0:
            sign = "-"
            value = abs(value)
        
        # 生成数字字符串
        if has_leading_zero and value > 0:
            # 添加前导零
            num_leading_zeros = random.randint(1, 2)
            value_str = '0' * num_leading_zeros + str(value)
        else:
            value_str = str(value)
        
        return sign + value_str

    @staticmethod
    def _generate_exponent():
        """生成指数部分"""
        # 决定是否生成指数
        if random.choice([True, False]):
            # 生成非负指数（最大为配置值）
            exponent_val = random.randint(0, TestGenerator._CONFIG["max_exponent"])
            # 决定是否包含+号
            sign = "+" if random.choice([True, False]) and exponent_val > 0 else ""
            # 决定是否有前导零
            if exponent_val > 0 and random.random() < TestGenerator._CONFIG["leading_zero_prob"]:
                exponent_str = '0' + str(exponent_val)
            else:
                exponent_str = str(exponent_val)
            
            return TestGenerator._generate_whitespace() + "^" + TestGenerator._generate_whitespace() + sign + exponent_str
        return ""

    @staticmethod
    def _generate_power_function():
        """生成幂函数（变量因子）"""
        return "x" + TestGenerator._generate_exponent()

    @staticmethod
    def _generate_constant_factor():
        """生成常数因子"""
        return TestGenerator._generate_integer()

    @staticmethod
    def _generate_factor(depth=0):
        """生成因子（变量因子、常数因子或表达式因子）"""
        # 根据当前深度调整生成不同类型因子的权重
        if depth >= TestGenerator._CONFIG["max_depth"]:
            # 到达最大深度时，不再生成表达式因子
            factor_type = random.choice(["variable", "constant"])
        else:
            # 深度越大，生成表达式因子的概率越低
            weights = [4, 3, max(0, 3 - depth)]  # 随着深度增加，表达式因子权重递减
            factor_type = random.choices(["variable", "constant", "expression"], weights=weights, k=1)[0]
        
        if factor_type == "variable":
            return TestGenerator._generate_power_function()
        elif factor_type == "constant":
            return TestGenerator._generate_constant_factor()
        else:  # expression
            # 递归生成表达式，深度+1
            expr = "(" + TestGenerator._generate_whitespace() + TestGenerator._generate_expression(depth + 1) + TestGenerator._generate_whitespace() + ")" + TestGenerator._generate_exponent()
            return expr

    @staticmethod
    def _generate_term(depth=0):
        """生成项"""
        # 决定是否在第一个因子前添加符号
        sign = random.choice(["", "+", "-"]) if random.choice([True, False]) else ""
        
        # 生成第一个因子
        term = sign + TestGenerator._generate_whitespace() + TestGenerator._generate_factor(depth)
        
        # 决定多余因子数量，随深度减少
        max_extra_factors = max(0, TestGenerator._CONFIG["max_factors"] - depth)
        num_extra_factors = random.randint(0, max_extra_factors)
        
        for _ in range(num_extra_factors):
            term += TestGenerator._generate_whitespace() + "*" + TestGenerator._generate_whitespace() + TestGenerator._generate_factor(depth)
        
        return term

    @staticmethod
    def _parse_expression_with_sympy(expr_str):
        """使用sympy解析表达式并展开"""
        expr_str = expr_str.replace('^', '**')
        expr_str = re.sub(r'([+-]?)0+([1-9][0-9]*)', r'\1\2', expr_str)

        x = symbols('x')
        
        try:
            expr = eval(expr_str, {"x": x, "__builtins__": {}}, {"sympy": sympy})
            expanded_expr = expand(expr)
            return expanded_expr
        except Exception as e:
            print(f"Sympy解析错误: {e}")
            return None

    @staticmethod
    def _generate_expression(depth=0):
        """生成表达式"""
        # 决定是否在第一项前添加符号
        sign = random.choice(["+", "-"]) if random.choice([True, False]) else ""
        
        # 生成第一项
        expression = sign + TestGenerator._generate_whitespace() + TestGenerator._generate_term(depth)
        
        # 决定项的数量，随深度减少
        max_terms = max(1, TestGenerator._CONFIG["max_terms"] - depth * 2)
        num_terms = random.randint(1, max_terms)
        
        for _ in range(num_terms):
            # 随机选择加号或减号
            operator = random.choice(["+", "-"])
            expression += TestGenerator._generate_whitespace() + operator + TestGenerator._generate_whitespace() + TestGenerator._generate_term(depth)

        return expression

    @staticmethod
    def genData():
        expr = TestGenerator._generate_expression()
        ans = TestGenerator._parse_expression_with_sympy(expr)
        return expr, ans


if __name__ == "__main__":
    print(TestGenerator.genData())