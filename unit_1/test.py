# test.py
import os
import time
import importlib
import subprocess
import concurrent.futures
import random
import numpy as np

import sympy
from sympy import symbols, expand, Poly, Eq

class JarTester:
    _LENGTH_ERROR = False
    _jar_files = []
    _finder_executed = False
    _hw_n = ""
    _jar_dir = ""
    
    @staticmethod
    def _find_jar_files():
        """Search for JAR files in the current directory"""
        if not JarTester._finder_executed:
            JarTester._jar_files = [JarTester._jar_dir + '/' + f for f in os.listdir(JarTester._jar_dir) if f.endswith('.jar')]
            JarTester._finder_executed = True
        return len(JarTester._jar_files) > 0
    
    @staticmethod
    def _run_jar_file(jar_path, input_expr):
        """Run a JAR file and get its output"""
        try:
            start_time = time.time()
            
            process = subprocess.Popen(['java', '-jar', jar_path], 
                                      stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE,
                                      text=True)
            
            stdout, stderr = process.communicate(input=input_expr, timeout=10)
            
            execution_time = time.time() - start_time
            
            if process.returncode == 0:
                return jar_path, stdout.strip(), execution_time, None
            else:
                return jar_path, None, execution_time, f"JAR execution error: {stderr}"
        except subprocess.TimeoutExpired:
            process.kill()
            return jar_path, None, 10, "JAR execution timeout"
        except Exception as e:
            return jar_path, None, 0, f"Error running JAR: {e}"

    @staticmethod
    def _compare_expressions(sympy_expr, jar_output):
        """Compare sympy expression with jar output for equivalence"""
        if sympy_expr is None or jar_output is None:
            return False
        
        jar_output = jar_output.replace('^', '**')
        
        def _is_eq_numeric(expr1, expr2, variables, n_tests=100, tolerance=1e-8):
            """通过数值方法验证两个表达式是否相等"""
            expr1_func = sympy.lambdify(variables, expr1, "numpy")
            expr2_func = sympy.lambdify(variables, expr2, "numpy")
            avg_tol = 0
            
            for _ in range(n_tests):
                # 生成随机测试点
                test_point = {var: random.uniform(-2*np.pi, 2*np.pi) for var in variables}
                values = [test_point[var] for var in variables]
                
                # 计算两个表达式在测试点的值
                val1 = expr1_func(*values)
                val2 = expr2_func(*values)

                aerr = abs(val1 - val2)
                rerr = aerr / val1

                avg_tol += rerr
                # 如果差异超过容差，则认为不相等
            avg_err = avg_tol / n_tests
            if abs(avg_err) > tolerance:
                return False, avg_err
            return True, avg_err

        try:
            x = symbols('x')

            math_funcs = {
                "sin": sympy.sin,
                "cos": sympy.cos,
                "x": x,
                "sympy": sympy
            }

            # sympy_expr = eval(str(sympy_expr), {"x": x, "__builtins__": {}}, math_funcs)
            jar_expr = eval(jar_output, {"x": x, "__builtins__": {}}, math_funcs)
            
            diff = expand(sympy_expr - jar_expr)
            
            if diff == 0:
                return True, 0
            
            # p1 = Poly(sympy_expr, x)
            # p2 = Poly(jar_expr, x)
            
            return _is_eq_numeric(sympy_expr, jar_expr, [x])
        except Exception as e:
            print(f"Error comparing expressions: {e}")
            return False, -114514

    @staticmethod
    def _process_jar(jar_file, input_expr, sympy_expr):
        """Process a single JAR file"""
        jar_path, jar_result, execution_time, error = JarTester._run_jar_file(jar_file, input_expr)
        
        result = {
            "jar_file": jar_file,
            "execution_time": execution_time,
            "success": False,
            "output": None,
            "matches_sympy": False,
            "avg_error": 0,
            "error": error
        }
        
        if jar_result:
            result["success"] = True
            result["output"] = jar_result
            result["matches_sympy"], result["avg_error"] = JarTester._compare_expressions(sympy_expr, jar_result)
        
        return result

    @staticmethod
    def _clear_screen():
        """Clear the terminal screen"""
        if os.name == 'nt':  # Windows
            os.system('cls')
        else:  # macOS, Linux, Unix
            os.system('clear')

    @staticmethod
    def _display_results(results, sympy_expr, input_expr):
        """Display and validate test results"""
        flag = True
        res_str = ""

        lens:list[int] = [len(str(result["output"])) for result in results]
        lens.sort()
        length_err = False
        if JarTester._LENGTH_ERROR and (lens[-1] - lens[0]) / lens[-1] > 0.1 and lens[-1] > 100: 
            flag = False
            length_err = True

        for result in results:
            if result["success"]:
                if not result["matches_sympy"] or length_err:
                    res_str += f"\n{result['jar_file']}:\n" \
                            + f"  jar output: {result['output']}\n" \
                            + f"sympy output: {sympy_expr}\n" \
                            + f"       Input: {input_expr}\n" \
                            + f"   avg_error: {result['avg_error']}\n" \
                            + "  ✗ Result doesn't match Sympy\n"
                    flag = False
            else:
                res_str += f"\n{result['jar_file']}:\n" \
                        + f"  Input: {input_expr}\n" \
                        + f"  ✗ Execution failed: {result['error']}\n"
                flag = False
        
        if not flag:
            res_str += f"{'JAR':<30} | {'Time(s)':<10} | {'Length':<10} | {'Run':<5} | {'Correct':<10} | {'error':<20}\n" \
                    + "-" * 100 + "\n"
            
            results.sort(key=lambda x: (len(str(x["output"])), x['execution_time']))

            for result in results:
                jar_name = result["jar_file"]
                time_str = f"{result['execution_time']:.3f}"
                length = len(str(result["output"]))
                success = "✓" if result["success"] else "✗"
                matches = "✓" if result["matches_sympy"] else "✗"
                error = str(result['avg_error'])
                
                res_str += f"{jar_name:<30} | {time_str:<10} | {length:<10} | {success:<5} | {matches:<10} | {error:<20}" + "\n"
            
        return res_str

    @staticmethod
    def _run_tests():
        """Run tests on all JAR files"""
        if not JarTester._find_jar_files():
            print("No JAR files found in the current directory")
            return
        
        try:
            gen = importlib.import_module(f"{JarTester._hw_n}.gen")
            print(f"Using generator from {JarTester._hw_n}")
        except ImportError as e:
            print(f"Error importing module {JarTester._hw_n}.gen: {e}")
            return

        print(f"Found {len(JarTester._jar_files)} JAR files, press Enter to begin concurrent processing...")
        input()

        cnt = 0
        local_time = time.localtime()
        formatted_time = time.strftime("%Y-%m-%d-%H-%M-%S", local_time)
        log_name = f"{formatted_time}_run.log"
        while True:
            cnt += 1
            JarTester._clear_screen()
            print(cnt)

            input_expr, sympy_expr = gen.TestGenerator.genData()
            print(input_expr)
            results = []
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future_to_jar = {
                    executor.submit(JarTester._process_jar, jar_file, input_expr, sympy_expr): jar_file 
                    for jar_file in JarTester._jar_files
                }
                
                for future in concurrent.futures.as_completed(future_to_jar):
                    jar_file = future_to_jar[future]
                    try:
                        results.append(future.result())
                    except Exception as e:
                        results.append({
                            "jar_file": jar_file,
                            "execution_time": 0,
                            "success": False,
                            "output": None,
                            "matches_sympy": False,
                            "error": f"Processing exception: {e}"
                        })
            
            # Sort results by execution time
            results.sort(key=lambda x: x["execution_time"])

            log = JarTester._display_results(results, sympy_expr, input_expr)
            
            if log:
                
                with open(os.path.join("logs", log_name), "a+", encoding="utf-8") as f:
                    f.write(log)

    @staticmethod
    def test(hw_n, jar_path):
        JarTester._hw_n = hw_n
        JarTester._jar_dir = jar_path
        try:
            JarTester._run_tests()
        except KeyboardInterrupt:
            print("\nProgram interrupted by user")
        except Exception as e:
            print(f"Program error: {e}")


if __name__ == "__main__":
    pass