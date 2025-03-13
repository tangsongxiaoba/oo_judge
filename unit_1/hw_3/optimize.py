import random
import sympy as sp

COMMON_FACTOR = 3 # 公因数的最多由几个factor组成
MAX_TERM = 4
inner_polys = [
    ["1", "-1"],
    ["2", "-2"],
    ["3", "-3"],
    ["4", "-4"],
    ["5", "-5"],
    ["6", "-6"],
    ["7", "-7"],
    ["8", "-8"],
    ["x", "(-x)"],
    ["x", "(-x)"],
    ["x", "(-x)"],
    ["x", "(-x)"],
    ["sin(x)", "(-sin(x))", "sin((-x))", "(-sin((-x)))"],
    ["sin(x)", "(-sin(x))", "sin((-x))", "(-sin((-x)))"],
    ["sin(x)", "(-sin(x))", "sin((-x))", "(-sin((-x)))"],
    ["sin(x)", "(-sin(x))", "sin((-x))", "(-sin((-x)))"],
    ["cos(x)", "(-cos(x))", "cos((-x))", "(-cos((-x)))"],
    ["cos(x)", "(-cos(x))", "cos((-x))", "(-cos((-x)))"],
    ["cos(x)", "(-cos(x))", "cos((-x))", "(-cos((-x)))"],
    ["cos(x)", "(-cos(x))", "cos((-x))", "(-cos((-x)))"],
    ["(x-1)", "(1-x)"],
    ["(x-1)", "(1-x)"],
    ["(x-1)", "(1-x)"],
    ["(x-1)", "(1-x)"],
    ["(x+1)", "(-x-1)"],
    ["(x+1)", "(-x-1)"],
    ["(x+1)", "(-x-1)"],
    ["(x+1)", "(-x-1)"],
    ["(x^2+1)", "(-x^2-1)"],
    ["(x^2-1)", "(-x^2+1)"],
    ["(x^2+1)", "(-x^2-1)"],
    ["(x^2-1)", "(-x^2+1)"],
    ["(x^2+x+1)", "(-x^2-x-1)"],
    ["(x^2+x-1)", "(-x^2-x+1)"],
    ["(x^2-x+1)", "(-x^2+x-1)"],
    ["(x^2-x-1)", "(-x^2+x+1)"],
    ["(cos(x)+x+1)", "(-cos(x)-x-1)", "(cos((-x))+x+1)", "(-cos((-x))-x-1)"],
    ["(cos(x)+x-1)", "(-cos(x)-x+1)", "(cos((-x))+x-1)", "(-cos((-x))-x+1)"],
    ["(cos(x)-x+1)", "(-cos(x)+x-1)", "(cos((-x))-x+1)", "(-cos((-x))+x-1)"],
    ["(cos(x)-x-1)", "(-cos(x)+x+1)", "(cos((-x))-x-1)", "(-cos((-x))+x+1)"],
    ["(sin(x)+x+1)", "(-sin(x)-x-1)", "(sin((-x))+x+1)", "(-sin((-x))-x-1)"],
    ["(sin(x)+x-1)", "(-sin(x)-x+1)", "(sin((-x))+x-1)", "(-sin((-x))-x+1)"],
    ["(sin(x)-x+1)", "(-sin(x)+x-1)", "(sin((-x))-x+1)", "(-sin((-x))+x-1)"],
    ["(sin(x)-x-1)", "(-sin(x)+x+1)", "(sin((-x))-x-1)", "(-sin((-x))+x+1)"],
]

def get_pair(fir="sin", sec="cos", inner:list=[]):
    if not inner:
        top = len(inner_polys)
        rd = random.randint(0, top - 1)
        inner = inner_polys[rd]
    top = len(inner)
    rd1 = random.randint(0, top - 1)
    rd2 = random.randint(0, top - 1)
    sin_poly = f"{fir}({inner[rd1]})"
    cos_poly = f"{sec}({inner[rd2]})"
    return [sin_poly, cos_poly]

def get_common():
    top = len(inner_polys)
    rd = random.randint(0 ,top - 1)
    inner = inner_polys[rd]
    top = len(inner)
    rd1 = random.randint(0, top - 1)
    rd2 = random.randint(0, top - 1)
    choice = random.randint(0, 2)
    fir_common = ""
    sec_common = ""
    if choice == 1:
        fir_common = f"sin({inner[rd1]})"
        sec_common = f"sin({inner[rd2]})"
    elif choice == 2:
        fir_common = f"cos({inner[rd1]})"
        sec_common = f"cos({inner[rd2]})"
    else:
        fir_common = inner[rd1]
        sec_common = inner[rd2]
    return [fir_common, sec_common]

def get_commons():
    rd = random.randint(1, COMMON_FACTOR)
    commons = get_common()
    for _ in range(rd - 1):
        tmp = get_common()
        commons = [f"{commons[i]}*{tmp[i]}" for i in range(2)]
    return commons

def get_double_angle():
    exp1 = random.randint(1, 5)
    exp2 = random.randint(1, 5)
    if random.randint(0, 1) == 1 :
        exp2 = exp1
    pair = get_pair()
    
    choice = random.randint(0, 1)
    coe = 0
    if choice == 0:
        coe = pow(2, exp1)
    elif choice == 1:
        coe = random.randint(2, 32)
    rd = random.randint(0, 1)
    return f"{coe}*{pair[rd]}^{exp1}*{pair[1-rd]}^{exp2}"

def get_square_merge():
    pair = get_pair()
    coe1 = random.randint(-10, 10)
    coe2 = random.randint(-10, 10)
    choice = random.randint(0, 3)
    if choice == 0:
        coe1 = coe2
    elif choice == 1:
        coe1 = -coe2
    
    commons = get_commons()
    pair = get_pair()
    rd = random.randint(0, 1)
    return f"{coe1}*{commons[rd]}*{pair[rd]}^2 + {coe2}*{commons[1-rd]}*{pair[1-rd]}^2"

def get_minus_merge():
    first = get_pair()
    second = get_pair()
    rd = random.randint(0, 1)
    coe1 = random.randint(1, 10) if random.randint(0, 1) == 0 else random.randint(-10, -1)
    coe2 = coe1 if random.randint(0, 1) == 1 else -coe1
    rd = random.randint(0, 1)
    rd1 = random.randint(0, 1)
    rd2 = random.randint(0, 1)
    commons = get_commons()
    return f"{coe1}*{commons[rd]}*{first[rd1]}*{second[rd2]} + {coe2}*{commons[1-rd]}*{first[1-rd1]}*{second[1-rd2]}"

def genData():
    rd = random.randint(1, MAX_TERM)
    result = ""
    for _ in range(rd):
        choice = random.randint(0, 2)
        if choice == 0:
            result += get_double_angle()
        elif choice == 1:
            result += get_minus_merge()
        elif choice == 2:
            result += get_square_merge()
        result += "+"
    return result[:-1]