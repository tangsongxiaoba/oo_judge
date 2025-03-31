import random
import time
from playwright.sync_api import sync_playwright
import playwright
import os
import subprocess
import ast
import re
import sys
import importlib
import importlib.util
import shutil
import playwright.sync_api

STD_JAR = os.path.join("jar","plook_weigh_longflr.jar") # 生成STDOUT的jar包
PYTHON = "python" # python
DATAINPUT = os.path.join("unit_2","hw_5","datainput_student_win64.exe") # 投喂包
CHECKER = os.path.join("unit_2","hw_5","checker.py") # 使用的checker
GENERATOR = os.path.join("hackgen.py") # 数据生成器，需要有genData方法返回str类型数据
REJECTED = []
PASSED = []
USR = "" # 统一身份验证账号
PASSWORD = "" # 密码
HACK_DIR = os.path.join("hack")
CNT = 5 # 第几次作业作业
spec = importlib.util.spec_from_file_location("hackgen", GENERATOR)
gen = importlib.util.module_from_spec(spec)
sys.modules["hackgen"] = gen
spec.loader.exec_module(gen)

def login(page, Usr, passWd):
    page.goto("http://oo.buaa.edu.cn")
    # time.sleep(10000)
    page.locator(".topmost a").click()

    # 切换到 iframe
    page.wait_for_selector("iframe#loginIframe", timeout=10000)
    iframe = page.frame_locator("iframe#loginIframe")
    time.sleep(1)
    iframe.locator("div.content-con-box:nth-of-type(1) div.item:nth-of-type(1) input").fill(Usr)
    time.sleep(1)
    iframe.locator("div.content-con-box:nth-of-type(1) div.item:nth-of-type(3) input").fill(passWd)
    time.sleep(1)
    iframe.locator("div.content-con-box:nth-of-type(1) div.item:nth-of-type(7) input").click()
    try:
        iframe.locator(".v-btn__content .align-center").click()
    except:
        pass

def decode_checker_out(checker_output):
    try:
        # 如果是 bytes，先解码
        if isinstance(checker_output, bytes):
            checker_output = checker_output.decode('utf-8')
        # 使用 ast.literal_eval 解析（兼容单引号）
        checker_output = ast.literal_eval(checker_output)
        return checker_output
        # 或者用 json.loads（需要确保是标准 JSON）
        # checker_data = json.loads(checker_output.replace("'", '"'))
    except (ValueError, SyntaxError) as e:
        print(f"解析失败！原始数据: {checker_output}")
        raise

def remove(list1: list, list2):
    for arg in list2:
        if arg in list1:
            list1.remove(arg)

def choose_existed_one(stdins, stdouts):
    global REJECTED, THISSTDIN
    remove(stdins, REJECTED)
    remove(stdins, PASSED)
    stdin = random.choice(stdins)
    if not stdin in stdouts:
        print(f"ERROR: Can't find stdout paired with {stdin}")
        REJECTED.append(stdin)
        os.remove(os.path.join(HACK_DIR, "stdin", stdin))    
    stdin_path = os.path.join(HACK_DIR, "stdin", stdin)
    stdout_path = os.path.join(HACK_DIR, "stdout", stdin)
    checker_output = subprocess.run([PYTHON, CHECKER, stdin_path, stdout_path], capture_output=True, text=True).stdout.strip()
    isPass = re.findall(r"Verdict: (.*?)", checker_output)[0] == "CORRECT"
    # checker_output = decode_checker_out(checker_output)
    if not isPass:
        print(f"ERROR: stdin {stdin} and stdout can't pass checker_test")
        REJECTED.append(stdin)
    stdin = open(stdin_path, "r", encoding="utf-8").read()
    stdout = open(stdout_path, "r", encoding="utf-8").read()
    THISSTDIN = stdin_path
    return stdin, stdout

def generate_random_ones():
    global USEDATAINPUT
    USEDATAINPUT = os.path.basename(DATAINPUT)
    shutil.copy(f"{DATAINPUT}", os.path.join(HACK_DIR, "stdin", f"{USEDATAINPUT}"))
    local_time = time.localtime()
    formatted_time = time.strftime("%Y%m%d_%H%M%S", local_time)
    for i in range(10):
        stdin = gen.genData()
        with open(os.path.join(HACK_DIR, "stdin", f"stdin.txt"), "w", encoding="utf-8") as file:
            file.write(stdin)
        # print(USEDATAINPUT)
        stdout_path = os.path.join(HACK_DIR, "stdout", f"{formatted_time}_{i}.txt")
        with open(stdout_path, "w", encoding="utf-8") as stdout_file:
            # print(os.path.join(HACK_DIR, "stdin"))
            datainput_proc = subprocess.Popen([os.path.join(os.path.abspath(HACK_DIR), "stdin", f"{USEDATAINPUT}")], cwd=os.path.join(HACK_DIR, "stdin"), stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            java_proc = subprocess.Popen(["java", "-jar", STD_JAR], stdin=datainput_proc.stdout, stdout=stdout_file)
            java_proc.wait()
            datainput_proc.wait()
        shutil.move(os.path.join(HACK_DIR, "stdin", "stdin.txt"), os.path.join(HACK_DIR, "stdin", f"{formatted_time}_{i}.txt"))
    os.remove(os.path.join(HACK_DIR, "stdin", f"{USEDATAINPUT}"))

def select_point():
    if not os.path.exists(os.path.join(HACK_DIR, "stdin")):
        os.makedirs(os.path.join(HACK_DIR, "stdin"))
    if not os.path.exists(os.path.join(HACK_DIR, "stdout")):
        os.makedirs(os.path.join(HACK_DIR, "stdout"))

    stdins = os.listdir(os.path.join(HACK_DIR, "stdin"))
    stdouts = os.listdir(os.path.join(HACK_DIR, "stdout"))
    if not stdins:
        generate_random_ones()
    stdins = os.listdir(os.path.join(HACK_DIR, "stdin"))
    stdouts = os.listdir(os.path.join(HACK_DIR, "stdout"))
    return choose_existed_one(stdins, stdouts)


def std_send_point(std: playwright.sync_api.Locator, text: str):
    std.fill(text)

def seng_point(page: playwright.sync_api.Page):
    block = page.locator("div.v-card__text div.v-input textarea")
    stdin_block = block.nth(0)
    stdout_block = block.nth(1)
    stdin, stdout = select_point()
    std_send_point(stdin_block, stdin)
    std_send_point(stdout_block, stdout)

    submit = page.locator("button.primary--text span.v-btn__content").nth(1)
    submit.click()
    cold = False
    try:
        cold = page.locator("#appSnackbar > div > div")
        text = cold.text_content()
        print(text)
        if "冷却期" in text:
            cold = True
            end = page.locator("button.primary--text span.v-btn__content").nth(0)
            end.click()
        time.sleep(10)
    except:
        cold = True
    if cold:
        return True, None        
            
    submitted = False
    try:
        error = page.locator("#app > div:nth-child(6) > div > div > div.v-card__text.py-2")
        page.locator("#app > div:nth-child(6) > div > div > div.v-card__title.py-1.pl-2.pr-1 > button > span > i").click(timeout=10)
        end = page.locator("button.primary--text span.v-btn__content").nth(0)
        end.click()
        submitted = False
        global REJECTED
        REJECTED.append(THISSTDIN)
        print("ERROR")
    except:
        global PASSED
        PASSED.append(THISSTDIN)
        print("COMMITED")
    return False, submitted

def get_course(page: playwright.sync_api.Page):
    page.goto("http://oo.buaa.edu.cn/course/62")
    time.sleep(0.5)
    page.locator("div.v-tab:nth-of-type(3)").click()
    time.sleep(0.5)
    page.locator(f'div.v-window-item a.v-list-item--link[href*="assignment"]:nth-of-type({CNT})').click()
    page.wait_for_url("**/intro")
    for _ in range(5):
        time.sleep(1)
        url = page.url
        if url.split('/')[-1] != "course":
            break

    url = "/".join(url.split('/')[:-1]) + "/mutual"
    page.goto(url)
    time.sleep(0.5)
    enabled_button = page.locator('div[role="list"] button:not([disabled="disabled"])').nth(0)
    # 执行操作，例如点击
    enabled_button.click()
    # time.sleep(1000)

def ready_to_break(page: playwright.sync_api.Page):
    hacks = page.locator("div > div:nth-child(9) > div.container.pa-0.container--fluid > div:nth-child(2) > div > div > div > div > div.v-list-item__content.mx-3 > div.v-list-item__subtitle > div:nth-child(2) > span")
    counts = hacks.count()
    for i in range(counts):
        cnt = re.findall(r"(\d)/\d", hacks.nth(i).text_content())[0]
        # print(cnt)
        if int(cnt) >= 3:
            return True
    return False

def main(Usr, passWd):
    if not os.path.exists(CHECKER):
        print(f"ERROR: No Checker in path {CHECKER} you provide")
        raise ValueError
    if not os.path.exists(GENERATOR):
        print(f"ERROR: You don't have the generator({GENERATOR}) used for generating stdin")
    if not os.path.exists(STD_JAR):
        print(f"ERROR: You don't have the std_jar({STD_JAR}) used for generating stdout")

    os.makedirs(HACK_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        login(page, Usr, passWd)
        get_course(page)
        while (True):
            if ready_to_break(page):
                break
            cold, submmited = seng_point(page)
            if cold:
                wait = page.locator("div.mb-1 > p").text_content()
                print(wait)
                wait = re.findall("\d+", wait)[0]
                print(wait)
                time.sleep(int(wait) + 1)
                continue
            if not submmited:
                pass
                print("SUBMIT IS REJECTED!!!")
            print(f"SUBMITED: {PASSED}")
            print(f"REJECTED: {REJECTED}")
        browser.close()  

if __name__ == "__main__":
    # Usr = ""
    # PassWd = ""
    # Usr = input("账号名:")
    # PassWd = input("密码:")
    Usr = USR
    PassWd = PASSWORD
    main(Usr, PassWd)
