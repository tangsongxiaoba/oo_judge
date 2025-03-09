import sympy as sp
import re
# 定义符号变量
x = sp.symbols('x')

# 两个字符串表达式
str_expr1 = input("Enter std ans: ")
str_expr2 = input("Enter usr ans: ")

str_expr1 = str_expr1.replace(" ", "")
str_expr1 = str_expr1.replace("\t", "")
str_expr1 = re.sub(r'\b0+(\d+)\b', r'\1', str_expr1)

str_expr1 = str_expr1.replace("^", "**")
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

new_expr1 = sp.collect(simplified_expr1 - simplified_expr2, x)
# print("THE two exprs minus:",sp.collect(new_expr1, x))
new_expr1 = sp.trigsimp(new_expr1)

# 判断简化后的表达式是否相等
if sp.simplify(new_expr1) == 0:
    print("The expressions are equal.")
else:
    print("The expressions are NOT equal.")

