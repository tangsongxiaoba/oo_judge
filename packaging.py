import os
import zipfile
import javalang
import subprocess
import shutil  # Added for directory removal

class JavaProjPackager:
    @staticmethod
    def _find_main_class(dir):
        """使用Java解析器查找包含main方法的类"""
        file_path = ""
        for root, _, files in os.walk(dir):
            for file in files:
                if file.endswith('.java'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        tree = javalang.parse.parse(content)
                        for _, class_decl in tree.filter(javalang.tree.ClassDeclaration):
                            for method in class_decl.methods:
                                if (method.name == 'main' and method.modifiers.issuperset({'public', 'static'}) and 
                                    method.return_type is None):
                                    package_name = tree.package.name if tree.package else ""
                                    full_class_name = f"{package_name}.{class_decl.name}" if package_name else class_decl.name
                                    return (file_path, full_class_name)
                    except Exception as e:
                        print(f"Warning: Error parsing {file_path}: {e}")
                        exit(-1)
        print(f"Not found main in {file_path}")
        return None

    @staticmethod
    def _compile_and_package_java_project(project_dir, jar_name):
        """编译Java项目并打包成JAR文件"""
        main_class_info = JavaProjPackager._find_main_class(project_dir)
        if not main_class_info:
            print(f"Error: Could not find main class in {project_dir}")
            return False

        main_class_path, class_name = main_class_info
        src_path = os.path.dirname(main_class_path)
        # 编译Java项目
        compile_command = ["javac", "-Xlint:unchecked", "-nowarn", "-encoding", "UTF-8","-d", project_dir, main_class_path, "-sourcepath", src_path]
        try:
            subprocess.run(compile_command, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error: Failed to compile Java project: {e}")
            return False
        os.makedirs(f"{project_dir}\\META-INF", exist_ok=True)
        with open(f"{project_dir}\\META-INF\\MANIFEST.MF", "w") as f:
            f.write(f"Manifest-Version: 1.0\nMain-Class: {class_name}\n")
            f.close()
        # 打包成JAR文件
        jar_command = ["jar", "cfm", jar_name, f"{project_dir}\\META-INF\\MANIFEST.MF", "-C", project_dir, "."]
        try:
            subprocess.run(jar_command, check=True)
            print(f"Success: JAR file '{jar_name}' created successfully.")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error: Failed to create JAR file: {e}")
            return False

    @staticmethod
    def _process_zip_files():
        """查找并处理同目录下的所有ZIP文件"""
        current_dir = os.getcwd()
        for file in os.listdir(current_dir):
            if file.endswith('.zip'):
                zip_path = os.path.join(current_dir, file)
                extract_dir = os.path.splitext(zip_path)[0]
                
                # 解压ZIP文件
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
                
                # 编译并打包Java项目
                jar_name = os.path.splitext(file)[0] + ".jar"
                success = JavaProjPackager._compile_and_package_java_project(extract_dir, jar_name)
                
                # 删除解压后的文件夹
                try:
                    shutil.rmtree(extract_dir)
                    print(f"Removed directory: {extract_dir}")
                except Exception as e:
                    print(f"Warning: Failed to delete directory {extract_dir}: {e}")

    @staticmethod
    def package():
        JavaProjPackager._process_zip_files()

if __name__ == "__main__":
    JavaProjPackager.package()