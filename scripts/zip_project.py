
import os
import zipfile
import sys

EXCLUDED_DIRS = {
    '.git', 'node_modules', 'venv', '.venv', 'env', '.env.local', 
    '__pycache__', '.next', 'dist', 'build', '.idea', '.vscode',
    'local_pg_data', 'storage'
}

EXCLUDED_EXTENSIONS = {'.pyc', '.pyo', '.pyd', '.zip'}

def zip_project(output_filename='OmniCortex.zip'):
    cwd = os.getcwd()
    print(f"Zipping directory: {cwd}")
    print(f"Output file: {output_filename}")
    
    count = 0
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(cwd):
            # Modify dirs in-place to skip excluded directories
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            
            for file in files:
                file_path = os.path.join(root, file)
                
                # Check extension
                _, ext = os.path.splitext(file)
                if ext in EXCLUDED_EXTENSIONS:
                    continue
                
                # Check filename
                if file == output_filename:
                    continue
                
                # Calculate relative path for archive
                arcname = os.path.relpath(file_path, cwd)
                
                print(f"Adding: {arcname}")
                zipf.write(file_path, arcname)
                count += 1
    
    print(f"\n✅ Successfully created {output_filename} with {count} files.")

if __name__ == "__main__":
    zip_project()
