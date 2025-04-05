# main.py
import os
import sys
import yaml
import shutil
import importlib

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
        class_path = config.get('class_path', None)
        
        print(f"Homework number from config: {hw_number}")
        if class_path:
            print(f"Class path from config: {class_path}")
        
        # Check if there are JAR files; if not, compile ZIPs
        jars = JarProcessor._get_jars()
        if not jars:
            print("No JAR files found in jar/ directory. Checking for ZIP files...")
            JarProcessor._compile_zips(class_path)
            jars = JarProcessor._get_jars()
            if not jars:
                print("No JAR files available after compilation. Exiting.")
                sys.exit(1)
        
        # Determine which unit to use
        unit_number = JarProcessor._determine_unit(hw_number)
        print(f"Using unit_{unit_number} for testing hw_{hw_number}")
        
        # Run tests
        JarProcessor._run_tests(unit_number, hw_number)

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
        if not os.path.exists('zip'):
            return
        
        # Save the current directory
        original_dir = os.getcwd()
        
        try:
            os.chdir('zip')
            
            # Use the JavaProjPackager to compile the ZIP files
            JavaProjPackager.package(class_path)
            
            # Move back to the original directory
            os.chdir(original_dir)
            
            # Move all generated JAR files to the jar/ directory
            for file in os.listdir('zip'):
                if file.endswith('.jar'):
                    src_path = os.path.join('zip', file)
                    dst_path = os.path.join('jar', file)
                    shutil.move(src_path, dst_path)
                    print(f"Moved {file} to jar/ directory")
        except Exception as e:
            print(f"Error during ZIP compilation: {e}")
            os.chdir(original_dir)

    @staticmethod
    def _read_config():
        """Read config.yml to determine the homework number and class path"""
        try:
            with open('config.yml', 'r') as file:
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
    def _run_tests(unit_number, hw_number):
        """Run tests using the appropriate unit's test module"""
        try:
            # Import and run the test module
            unit_module_name = f"unit_{unit_number}.test"
            try:
                test_module = importlib.import_module(unit_module_name)
                test_module.JarTester.test(f"unit_{unit_number}.hw_{hw_number}", "jar", 1)
            except ImportError as e:
                print(f"Error: Could not import test module for unit_{unit_number}: {e}")
                print(f"Make sure unit_{unit_number}/test.py exists and is properly implemented.")
                sys.exit(1)
                    
        except Exception as e:
            print(f"Error during test execution: {e}")
            sys.exit(1)


if __name__ == "__main__":
    JarProcessor.process()
