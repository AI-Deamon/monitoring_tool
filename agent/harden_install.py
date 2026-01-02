import os
import py_compile
import shutil
import glob
import sys

def compile_and_clean(root_dir):
    print(f"Hardening installation in: {root_dir}")
    
    # 1. Compile all .py files to .pyc
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip __pycache__ directories in traversal
        if '__pycache__' in dirnames:
            dirnames.remove('__pycache__')
            
        for filename in filenames:
            if filename.endswith('.py') and filename != 'harden_install.py':
                full_path = os.path.join(dirpath, filename)
                print(f"Compiling {filename}...")
                try:
                    # Compile to .pyc in the SAME directory (legacy behavior for compatibility)
                    # We manually define cfile to avoid __pycache__ which can be messy for entry points
                    cfile = full_path + 'c' 
                    py_compile.compile(full_path, cfile=cfile, doraise=True)
                    
                    # Remove original .py
                    os.remove(full_path)
                    print(f"Secured {filename}")
                except Exception as e:
                    print(f"Error processing {filename}: {e}")

    # 2. Cleanup __pycache__ if any exist
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if '__pycache__' in dirnames:
            shutil.rmtree(os.path.join(dirpath, '__pycache__'))
            print(f"Removed cache in {dirpath}")

def generate_integrity_manifest(root_dir):
    """SEC-024: Generate integrity manifest after compilation"""
    from pathlib import Path
    
    print("\nSEC-024: Generating integrity manifest...")
    
    try:
        # Import integrity module
        sys.path.insert(0, root_dir)
        from core.integrity import generate_manifest, save_manifest
        
        manifest = generate_manifest(Path(root_dir))
        
        if save_manifest(Path(root_dir), manifest):
            print(f"SEC-024: Integrity manifest created with {len(manifest)} files")
            for path in sorted(manifest.keys()):
                print(f"  - {path}")
        else:
            print("SEC-024: WARNING - Failed to create integrity manifest")
            
    except ImportError as e:
        print(f"SEC-024: Skipping manifest generation (integrity module not available: {e})")
    except Exception as e:
        print(f"SEC-024: Error generating manifest: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    else:
        target_dir = os.getcwd()
        
    compile_and_clean(target_dir)
    
    # SEC-024: Generate integrity manifest
    generate_integrity_manifest(target_dir)
    
    print("\nHardening complete.")
