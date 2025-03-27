import random
import numpy as np
import sympy as sp
import re

_FROM_FILE = True
# 定义符号变量
x = sp.symbols('x')

# 两个字符串表达式
str_expr1 = ""
str_expr2 = ""
if not _FROM_FILE:
    str_expr1 = input("Enter std ans: ")
    str_expr2 = input("Enter usr ans: ")
else:
    str_expr1 = open("from_std.log", "r", encoding="utf-8").read()
    str_expr2 = open("from_usr.log", "r", encoding="utf-8").read()


str_expr1 = str_expr1.replace(" ", "")
str_expr1 = str_expr1.replace("\t", "")
str_expr1 = re.sub(r'\b0+(\d+)\b', r'\1', str_expr1)

str_expr1 = str_expr1.replace("^", "**")
str_expr1 = str_expr1.replace("dx(", "diff(")
str_expr2 = str_expr2.replace("^", "**")

# 将字符串转换为符号表达式
expr1 = sp.sympify(str_expr1)
expr2 = sp.sympify(str_expr2)

# 使用 simplify 简化并比较表达式
simplified_expr1 = sp.expand(expr1)
simplified_expr2 = sp.expand(expr2)

print("Simplified Expression 1:", simplified_expr1)
print("Simplified Expression 2:", simplified_expr2)

with open("std.log", "w", encoding="utf-8") as file:
    file.write(str(simplified_expr1))
with open("usr.log", "w", encoding="utf-8") as file:
    file.write(str(simplified_expr2))
n_tests = 50
import mpmath
mpmath.mp.dps = 30
expr1_func = sp.lambdify([x], simplified_expr1, "mpmath")
expr2_func = sp.lambdify([x], simplified_expr2, "mpmath")
avg_tol = mpmath.mpf('0')
for _ in range(n_tests):
    # 生成随机测试点
    test_point = {var: random.uniform(-2*mpmath.pi, 2*mpmath.pi) for var in [x]}
    values = [mpmath.mpf(test_point[var]) for var in [x]]
    
    # 计算两个表达式在测试点的值
    val1 = expr1_func(*values)
    val2 = expr2_func(*values)
    aerr = abs(val1 - val2)
    if abs(val1) != 0:
        rerr = aerr / abs(val1)
    else:
        rerr = aerr    
    avg_tol += rerr
    # 如果差异超过容差，则认为不相等
avg_err = avg_tol / n_tests
print(avg_err)

# new_expr1 = sp.collect(simplified_expr1 - simplified_expr2, x)
# print("THE two exprs minus:",sp.collect(new_expr1, x))
# new_expr1 = sp.trigsimp(new_expr1)

# # 判断简化后的表达式是否相等
# if sp.simplify(new_expr1) == 0:
#     print("The expressions are equal.")
# else:
#     print("The expressions are NOT equal.")
