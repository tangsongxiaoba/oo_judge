import time
import subprocess
import os

java_dir = "jar"
test_file = "test.log"
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


for root, dirs, files in os.walk(java_dir) :
    for file in files:
        if file.endswith(".jar"):
            jars.append(os.path.join(root, file))

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
        print("-"* 50)
        print()
else :
    print(f"NO JARS FOUND IN {java_dir}")