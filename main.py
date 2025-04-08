# main.py
import os
import sys
import yaml
import shutil
import importlib
import tempfile

# Import packaging module
from packaging import JavaProjPackager

class JarProcessor:
    """Static class to manage JAR processing, compilation and testing"""
    
    @staticmethod
    def process():
        """Main processing method that orchestrates the JAR handling workflow"""
        # Create necessary directories
        JarProcessor._create_directories()
        
        # Read config file
        config = JarProcessor._read_config()
        hw_number = config.get('hw', 1)
        assets_dir = config.get('assets_dir', None)
        class_path = config.get('class_path', None)
        
        class_path = os.path.abspath(os.path.join(assets_dir, class_path))
        
        print(f"Homework number from config: {hw_number}")
        if class_path:
            print(f"Class path from config: {class_path}")

        JarProcessor._compile_zips(class_path)
        
        jars = JarProcessor._get_jars()
        if not jars:
            print("No JAR files found in jar/ directory, and no new JARs were compiled from zip/. Exiting.")
            sys.exit(1)
        
        # Determine which unit to use
        unit_number = JarProcessor._determine_unit(hw_number)
        print(f"Using unit_{unit_number} for testing hw_{hw_number}")
        
        # Run tests
        JarProcessor._run_tests(unit_number)

    @staticmethod
    def _create_directories():
        """Create necessary directories if they don't exist"""
        for directory in ['jar', 'zip']:
            if not os.path.exists(directory):
                os.makedirs(directory)
                print(f"Created directory: {directory}")

    @staticmethod
    def _get_jars():
        """Get all JAR files from the jar/ directory"""
        if not os.path.exists('jar'):
            return []
        return [f for f in os.listdir('jar') if f.endswith('.jar')]

    @staticmethod
    def _compile_zips(class_path=None):
        """Compile all ZIP files in zip/ directory and move resulting JARs to jar/"""
        if not os.path.exists('jar') or not os.path.exists('zip'):
            JarProcessor._create_directories() #确保jar目录存在

        zip_files = [f for f in os.listdir('zip') if f.endswith('.zip')]
        if not zip_files:
            print("No ZIP files found in zip/ directory.")
            return
        
        existing_jar_basenames = set()
        if os.path.exists('jar'):
            existing_jar_basenames = {os.path.splitext(f)[0] for f in os.listdir('jar') if f.endswith('.jar')}

        zips_to_compile = []
        for zip_file in zip_files:
            zip_basename = os.path.splitext(zip_file)[0]
            if zip_basename not in existing_jar_basenames:
                zips_to_compile.append(zip_file)
                print(f"Found new ZIP file to compile: {zip_file}")
        
        if not zips_to_compile:
            print("All ZIP files in zip/ already have corresponding JAR files in jar/. No compilation needed.")
            return
        
        print(f"Found {len(zips_to_compile)} new ZIP files to compile: {', '.join(zips_to_compile)}")

        with tempfile.TemporaryDirectory(prefix="compile_") as temp_dir_path:
            print(f"Using temporary directory for compilation: {temp_dir_path}")

            # 将需要编译的 zip 文件复制到临时目录
            for zip_file in zips_to_compile:
                src_path = os.path.join('zip', zip_file)
                dst_path = os.path.join(temp_dir_path, zip_file)
                try:
                    shutil.copy2(src_path, dst_path) # copy2 保留元数据
                    # print(f"Copied {zip_file} to temporary directory.") # 用于调试
                except Exception as e:
                    print(f"Error copying {zip_file} to temporary directory: {e}")
                    # 可以选择继续处理其他文件或直接返回/抛出异常
                    continue # 继续处理下一个文件
        
            # Save the current directory
            original_dir = os.getcwd()
            
            try:
                os.chdir(temp_dir_path)
                print(f"Changed directory to: {os.getcwd()}") # 用于调试
                print("Starting compilation of new ZIP files...")
                
                JavaProjPackager.package(class_path)
                print("Compilation finished.")
                
                os.chdir(original_dir)
                print(f"Changed directory back to: {os.getcwd()}")
                
                moved_count = 0
                for file in os.listdir(temp_dir_path):
                    if file.endswith('.jar'):
                        # 检查目标文件是否已存在（理论上不应该，因为我们只编译了新的）
                        jar_basename = os.path.splitext(file)[0]
                        if jar_basename not in existing_jar_basenames:
                            src_path = os.path.join(temp_dir_path, file)
                            dst_path = os.path.join('jar', file)
                            try:
                                shutil.move(src_path, dst_path)
                                print(f"Moved newly compiled {file} to jar/ directory")
                                moved_count += 1
                            except Exception as e:
                                print(f"Error moving {file} from temp dir to jar/: {e}")
                        else:
                            print(f"Warning: Newly compiled JAR {file} corresponds to an already existing base name. Skipping move.")

                if moved_count == 0:
                    print("Warning: Compilation ran, but no new JAR files were found or moved from the temporary directory.")
                elif moved_count != len(zips_to_compile):
                    print(f"Warning: Expected {len(zips_to_compile)} JARs, but moved {moved_count}.")
            except Exception as e:
                print(f"Error during ZIP compilation in temporary directory: {e}")
                # 确保即使出错也切换回原始目录并清理临时目录
                os.chdir(original_dir) # 确保切换回来
                # tempfile.TemporaryDirectory 会在 with 块结束时自动清理
            finally:
                # 确保在任何情况下都切换回原始目录
                # （虽然try块和with语句应该已经处理了，但再加一层保险）
                if os.getcwd() != original_dir:
                    os.chdir(original_dir)
                # 临时目录会在 with 块结束时自动删除，无需手动清理
                print(f"Temporary directory {temp_dir_path} will be cleaned up.")

    @staticmethod
    def _read_config():
        """Read config.yml to determine the homework number and class path"""
        try:
            with open('config.yml', 'r', encoding='utf-8') as file:
                config = yaml.safe_load(file)
                return config or {}  # Return empty dict if None
        except Exception as e:
            print(f"Error reading config.yml: {e}")
            print("Using default settings")
            return {}

    @staticmethod
    def _determine_unit(hw_number):
        """Determine which unit the homework belongs to"""
        if hw_number in [1, 2, 3, 5, 6, 7, 9, 10, 11, 13, 14, 15]:
            return (hw_number // 4) + 1
        else:
            print(f"Invalid homework number: {hw_number}. Using unit 1.")
            return 1

    @staticmethod
    def _run_tests(unit_number):
        """Run tests using the appropriate unit's test module"""
        try:
            # Import and run the test module
            unit_module_name = f"unit_{unit_number}.test"
            try:
                test_module = importlib.import_module(unit_module_name)
                test_module.JarTester.test()
            except ImportError as e:
                print(f"Error: Could not import test module for unit_{unit_number}: {e}")
                print(f"Make sure unit_{unit_number}/test.py exists and is properly implemented.")
                sys.exit(1)
                    
        except Exception as e:
            print(f"Error during test execution: {e}")
            sys.exit(1)


if __name__ == "__main__":
    JarProcessor.process()
