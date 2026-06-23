import os
import glob

def replace_in_files():
    files = glob.glob('*.py')
    for file in files:
        with open(file, 'r') as f:
            content = f.read()
        if 'cow/gemma2_tools:2b' in content:
            new_content = content.replace('cow/gemma2_tools:2b', 'cow/gemma2_tools:2b')
            with open(file, 'w') as f:
                f.write(new_content)
            print(f"Updated {file}")

if __name__ == '__main__':
    replace_in_files()
