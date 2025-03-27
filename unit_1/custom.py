import random
import re
import sys
import subprocess
import os
import sympy as sp

java_dir = "../jar"
test_file = "" # put stdin file here
std_file = "" # put std.jar here
jars = []

print("TEST: ")
input_str = open(test_file, "r", encoding="utf-8").read()
def execute_jar(jar_path, input_expr) :
    try:        
        process = subprocess.Popen(['java', '-jar', jar_path], 
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    text=True)
        
        stdout, stderr = process.communicate(input=input_expr, timeout=10)
        
        if process.returncode == 0:
            return stdout.strip(), None
        else:
            return None,  f"JAR execution error: {stderr}"
    except subprocess.TimeoutExpired:
        process.kill()
        return None, "JAR execution timeout"
    except Exception as e:
        return None, f"Error running JAR: {e}"

def compare(str_expr1, str_expr2):
    x = sp.symbols("x")
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
    mpmath.mp.dps = 50
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
    print(f"AVG_ERR: {avg_err}")
    # new_expr1 = sp.collect(simplified_expr1 - simplified_expr2, x)
    # print("THE two exprs minus:",sp.collect(new_expr1, x))
    # new_expr1 = sp.trigsimp(new_expr1)

    # 判断简化后的表达式是否相等
    # if sp.simplify(new_expr1) == 0:
    #     print("The expressions are equal.")
    # else:
    #     print("The expressions are NOT equal.")

std_flag = False
actual_std_file = ""
for root, dirs, files in os.walk(java_dir) :
    for file in files:
        if file.endswith(".jar"):
            if file == std_file:
                std_flag = True
                actual_std_file = os.path.join(root, file)
            else:
                jars.append(os.path.join(root, file))
if not std_flag:
    print("ERROR: You don't have valid std_file, please check and set another one")
    sys.exit()

std_out = ""
std_err = ""
std_out, std_err = execute_jar(actual_std_file, input_str)
print(f"{os.path.basename(actual_std_file): <50}: ")
print("-" * 50)
print("\t" + std_out if std_out else "NULL")
if std_err :
    print("\t" + std_err)
    print("ERROR: std_file errors")
    sys.exit()
print("-"* 50)
print()

if jars:
    stdouts = []
    stderrs = []
    names = [os.path.basename(jar) for jar in jars]
    for jar in jars:
        stdout, stderr = execute_jar(jar, input_str)
        print(f"{os.path.basename(jar): <50}: ")
        print("-" * 50)
        print("\t" + stdout if stdout else "NULL")
        if stderr :
            print("\t" + stderr)
        else:
            compare(std_out, stdout)
        print("-"* 50)
        print()
else :
    print(f"NO JARS FOUND IN {java_dir}")