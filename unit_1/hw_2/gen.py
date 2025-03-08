# hw_2/gen.py
import random
from sympy import symbols, expand
import sympy
import importlib

current_package = __name__.rsplit('.', 1)[0] if '.' in __name__ else ''
func = importlib.import_module(f"{current_package}.func" if current_package else "func")

class TestGenerator:
    # Configuration settings as class variable
    _CONFIG = {
        'integer': {
            'min': 0,
            'max': 20,
            'allow_negative_prob': 0.8,
            'add_plus_sign_prob': 0.8,
        },
        'exponent': {
            'min': 0,
            'max': 3,
        },
        'space': {
            'prob': 0.7,
            'max_spaces': 3,
        },
        'expression': {
            'max_depth': 2,
            'term_count': {'min': 2, 'max': 4},
        },
        'factor': {
            'choice_weights': [1, 1, 3],  # variable, constant, expression weights
        },
        'variable_factor': {
            'power_prob': 0.5,
            'trig_functions': ['sin', 'cos'],
        },
        'term': {
            'multi_factor_prob': 0.7,
            'max_factors': 5,
            'sign_prob': 0.5,
        }
    }
    
    @staticmethod
    def genData():
        """公开方法，返回generate_test_case的结果"""

        def _add_extra_parentheses(expr):
            """
            在所有sin()和cos()函数调用内部添加额外的括号
            例如: sin(x+y) -> sin((x+y))，sin(cos(x)) -> sin((cos((x))))
            """
            i = 0
            result = ""
            
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
                else:
                    result += expr[i]
                    i += 1
            
            return result
        
        def _find_matching_paren(expr, open_pos):
            """
            找到与open_pos位置的左括号匹配的右括号
            返回括号内的内容和右括号的位置
            """
            assert expr[open_pos] == "("
            
            stack = 1  # 已经有一个左括号
            i = open_pos + 1
            
            while i < len(expr) and stack > 0:
                if expr[i] == "(":
                    stack += 1
                elif expr[i] == ")":
                    stack -= 1
                i += 1
            
            if stack != 0:
                raise ValueError("括号不匹配")
            
            closing_pos = i - 1
            return expr[open_pos+1:closing_pos], closing_pos

        if random.random() < 0.5:
            exp_str = TestGenerator.__generate_test_case()
            que_str = "0\n" + exp_str
            ans_str = TestGenerator._parse_expression_with_sympy(exp_str)
            return que_str, ans_str
        res = func.generate_recursive_problem()
        que_str = ("1\n"
        + _add_extra_parentheses(str(res['definition']['f0'])).replace("**", "^") + '\n' 
        + _add_extra_parentheses(str(res['definition']['f1'])).replace("**", "^") + '\n' 
        + _add_extra_parentheses(str(res['definition']['fn'])).replace("**", "^") + '\n' 
        + _add_extra_parentheses(str(res['call'])).replace("**", "^"))
        ans_str = res['result']
        return que_str, ans_str

    @staticmethod
    def __generate_integer(allow_negative=True):
        """生成带符号整数"""
        value = random.randint(TestGenerator._CONFIG['integer']['min'], 
                              TestGenerator._CONFIG['integer']['max'])
        if allow_negative and random.random() < TestGenerator._CONFIG['integer']['allow_negative_prob']:
            return f"-{value}"
        elif random.random() < TestGenerator._CONFIG['integer']['add_plus_sign_prob']:
            return f"+{value}"
        else:
            return str(value)

    @staticmethod
    def __generate_exponent():
        """生成非负指数，不超过8"""
        return str(random.randint(TestGenerator._CONFIG['exponent']['min'], 
                                 TestGenerator._CONFIG['exponent']['max']))

    @staticmethod
    def __generate_space():
        """随机生成空白字符"""
        if random.random() < TestGenerator._CONFIG['space']['prob']:
            spaces = random.randint(0, TestGenerator._CONFIG['space']['max_spaces'])
            return ' ' * spaces
        return ''

    @staticmethod
    def __generate_variable_factor(depth=0, max_depth=None):
        """生成变量因子"""
        if max_depth is None:
            max_depth = TestGenerator._CONFIG['expression']['max_depth']
            
        if depth > max_depth:
            return 'x'
        
        choice = random.randint(1, 2)
        
        if choice == 1:  # 幂函数
            if random.random() < TestGenerator._CONFIG['variable_factor']['power_prob']:
                return f"x{TestGenerator.__generate_space()}^{TestGenerator.__generate_space()}{TestGenerator.__generate_exponent()}"
            else:
                return "x"
        else:  # 三角函数
            trig = random.choice(TestGenerator._CONFIG['variable_factor']['trig_functions'])
            inner = TestGenerator.__generate_factor(depth + 1, max_depth)
            if random.random() < TestGenerator._CONFIG['variable_factor']['power_prob']:
                return f"{trig}{TestGenerator.__generate_space()}({TestGenerator.__generate_space()}{inner}{TestGenerator.__generate_space()}){TestGenerator.__generate_space()}^{TestGenerator.__generate_space()}{TestGenerator.__generate_exponent()}"
            else:
                return f"{trig}{TestGenerator.__generate_space()}({TestGenerator.__generate_space()}{inner}{TestGenerator.__generate_space()})"

    @staticmethod
    def __generate_constant_factor():
        """生成常数因子"""
        return TestGenerator.__generate_integer()

    @staticmethod
    def __generate_expression_factor(depth=0, max_depth=None):
        """生成表达式因子"""
        if max_depth is None:
            max_depth = TestGenerator._CONFIG['expression']['max_depth']
            
        if depth > max_depth:
            return f"({TestGenerator.__generate_space()}x{TestGenerator.__generate_space()})"
        
        expr = TestGenerator.__generate_expression(depth + 1, max_depth)
        if random.random() < TestGenerator._CONFIG['variable_factor']['power_prob']:
            return f"({TestGenerator.__generate_space()}{expr}{TestGenerator.__generate_space()}){TestGenerator.__generate_space()}^{TestGenerator.__generate_space()}{TestGenerator.__generate_exponent()}"
        else:
            return f"({TestGenerator.__generate_space()}{expr}{TestGenerator.__generate_space()})"

    @staticmethod
    def __generate_factor(depth=0, max_depth=None):
        """生成因子"""
        if max_depth is None:
            max_depth = TestGenerator._CONFIG['expression']['max_depth']
            
        if depth > max_depth:
            choice = random.randint(1, 2)
            if choice == 1:
                return TestGenerator.__generate_constant_factor()
            else:
                return TestGenerator.__generate_variable_factor(depth, max_depth)
        
        weights = TestGenerator._CONFIG['factor']['choice_weights']
        choice = random.choices([1, 2, 3], weights=weights, k=1)[0]
        
        if choice == 1:
            return TestGenerator.__generate_variable_factor(depth, max_depth)
        elif choice == 2:
            return TestGenerator.__generate_constant_factor()
        else:
            return TestGenerator.__generate_expression_factor(depth, max_depth)

    @staticmethod
    def __generate_term(depth=0, max_depth=None):
        """生成项"""
        if max_depth is None:
            max_depth = TestGenerator._CONFIG['expression']['max_depth']
            
        if depth > max_depth:
            return f"{TestGenerator.__generate_factor(depth, max_depth)}"
        
        factor = TestGenerator.__generate_factor(depth, max_depth)
        if random.random() < TestGenerator._CONFIG['term']['sign_prob']:
            sign = random.choice(['+', '-'])
            return f"{sign}{TestGenerator.__generate_space()}{factor}"
        
        # 随机决定是否生成多因子项
        if random.random() < TestGenerator._CONFIG['term']['multi_factor_prob'] and depth < max_depth - 1:
            num_factors = random.randint(1, TestGenerator._CONFIG['term']['max_factors'])
            term = factor
            for _ in range(num_factors):
                term += f"{TestGenerator.__generate_space()}*{TestGenerator.__generate_space()}{TestGenerator.__generate_factor(depth + 1, max_depth)}"
            return term
        else:
            return factor

    @staticmethod
    def __generate_expression(depth=0, max_depth=None):
        """生成表达式"""
        if max_depth is None:
            max_depth = TestGenerator._CONFIG['expression']['max_depth']
            
        if depth > max_depth:
            return TestGenerator.__generate_term(depth, max_depth)
        
        num_terms = random.randint(TestGenerator._CONFIG['expression']['term_count']['min'], 
                                  TestGenerator._CONFIG['expression']['term_count']['max'])
        first_term = TestGenerator.__generate_term(depth, max_depth)
        if random.random() < TestGenerator._CONFIG['term']['sign_prob']:
            sign = random.choice(['+', '-'])
            expr = f"{sign}{TestGenerator.__generate_space()}{first_term}"
        else:
            expr = first_term
        
        for _ in range(num_terms - 1):
            op = random.choice(['+', '-'])
            expr += f"{TestGenerator.__generate_space()}{op}{TestGenerator.__generate_space()}{TestGenerator.__generate_term(depth + 1, max_depth)}"
        
        return expr

    @staticmethod
    def __generate_test_case():
        """生成完整测试用例"""
        # 生成待展开的表达式
        expression = TestGenerator.__generate_expression(0, TestGenerator._CONFIG['expression']['max_depth'])
        
        return expression
    
    @staticmethod
    def _parse_expression_with_sympy(expr_str):
        """使用sympy解析表达式并展开"""
        # print(expr_str)
        expr_str = expr_str.replace('^', '**')
        
        x = symbols('x')

        math_funcs = {
            "sin": sympy.sin,
            "cos": sympy.cos,
            "x": x,
            "sympy": sympy
        }
        
        try:
            expr = eval(expr_str, {"x": x, "__builtins__": {}}, math_funcs)
            expanded_expr = expand(expr)
            return expanded_expr
        except Exception as e:
            print(f"Sympy解析错误: {e}")
            return None

# 使用示例
if __name__ == "__main__":
    for _ in range(1000):
        t = TestGenerator.genData()
        if(str(t[0]).startswith(("0", "1")) == False):
            print("wrong format")
            print("que: " + str(t[0]))
            print("ans: " + str(t[1]))
        