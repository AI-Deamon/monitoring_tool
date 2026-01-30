#!/usr/bin/env python3
"""
Server Setup Script for New Machine
====================================
Automates the complete setup process for SentinelEdge server on a new machine.
"""
import sys
import subprocess
from pathlib import Path
import os

def print_step(step_num, description):
    print(f"\n{'='*60}")
    print(f"STEP {step_num}: {description}")
    print('='*60)

def run_command(cmd, description, check=True):
    """Run a command and handle errors"""
    print(f"→ {description}...")
    try:
        result = subprocess.run(cmd, shell=True, check=check, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ✅ Success")
            return True
        else:
            print(f"  ❌ Failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def check_prerequisites():
    """Check if all prerequisites are installed"""
    print_step(1, "Checking Prerequisites")
    
    checks = [
        ("python --version", "Python 3.8+"),
        ("psql --version", "PostgreSQL client"),
        ("pg_dump --version", "PostgreSQL dump utility"),
    ]
    
    all_ok = True
    for cmd, name in checks:
        if not run_command(cmd, f"Checking {name}", check=False):
            all_ok = False
            print(f"  ⚠️  Please install {name}")
    
    return all_ok

def install_dependencies():
    """Install Python dependencies"""
    print_step(2, "Installing Python Dependencies")
    return run_command("pip install -r requirements.txt", "Installing packages")

def setup_environment():
    """Create .env file if it doesn't exist"""
    print_step(3, "Setting Up Environment Configuration")
    
    if Path('.env').exists():
        print("  ℹ️  .env already exists, skipping")
        return True
    
    if not Path('.env.template').exists():
        print("  ❌ .env.template not found")
        return False
    
    # Copy template
    import shutil
    shutil.copy('.env.template', '.env')
    print("  ✅ Created .env from template")
    print("\n  ⚠️  IMPORTANT: Edit .env and update:")
    print("     - DATABASE_URL (PostgreSQL credentials)")
    print("     - SECRET_KEY (generate random key)")
    
    response = input("\n  Press Enter after editing .env...")
    return True

def create_database():
    """Create PostgreSQL database"""
    print_step(4, "Creating Database")
    
    # Try to create database
    db_name = "sentineledge"
    result = run_command(f'createdb {db_name}', f"Creating database '{db_name}'", check=False)
    
    if not result:
        print("  ℹ️  Database might already exist, continuing...")
    
    return True

def run_migrations():
    """Run database migrations"""
    print_step(5, "Running Database Migrations")
    
    # Check if using Alembic
    if Path('alembic.ini').exists():
        return run_command("alembic upgrade head", "Running Alembic migrations")
    else:
        print("  ℹ️  No Alembic configuration found")
        print("  ℹ️  Database schema will be created on first run")
        return True

def apply_stored_procedures():
    """Apply critical stored procedures"""
    print_step(6, "Applying Stored Procedures")
    
    scripts = [
        "scripts/fixes/apply_sync_functions.py",
        "scripts/fixes/fix_domain_sessions_schema.py",
    ]
    
    for script in scripts:
        script_path = Path(script)
        if script_path.exists():
            run_command(f"python {script}", f"Running {script_path.name}")
        else:
            print(f"  ⚠️  {script} not found, skipping")
    
    return True

def create_default_admin():
    """Create default admin user"""
    print_step(7, "Creating Default Admin User")
    
    print("  ℹ️  Default admin will be created on first server start")
    print("     Username: admin")
    print("     Password: changeme123")
    print("     ⚠️  CHANGE THIS PASSWORD IMMEDIATELY!")
    
    return True

def verify_setup():
    """Verify the setup is complete"""
    print_step(8, "Verifying Setup")
    
    checks = [
        (Path('.env').exists(), ".env file exists"),
        (Path('requirements.txt').exists(), "requirements.txt exists"),
        (Path('server_main.py').exists(), "server_main.py exists"),
    ]
    
    all_ok = True
    for check, description in checks:
        if check:
            print(f"  ✅ {description}")
        else:
            print(f"  ❌ {description}")
            all_ok = False
    
    return all_ok

def main():
    """Main setup workflow"""
    print("""
╔══════════════════════════════════════════════════════════╗
║   SentinelEdge Server - New Machine Setup               ║
║   This script will set up everything needed to run       ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    # Change to server directory
    server_dir = Path(__file__).parent.parent
    os.chdir(server_dir)
    print(f"Working directory: {server_dir}\n")
    
    # Run setup steps
    steps = [
        (check_prerequisites, "Prerequisites check"),
        (install_dependencies, "Install dependencies"),
        (setup_environment, "Setup environment"),
        (create_database, "Create database"),
        (run_migrations, "Run migrations"),
        (apply_stored_procedures, "Apply stored procedures"),
        (create_default_admin, "Create admin user"),
        (verify_setup, "Verify setup"),
    ]
    
    for step_func, description in steps:
        if not step_func():
            print(f"\n❌ Setup failed at: {description}")
            print("Please fix the errors and run this script again.")
            return False
    
    print("""
╔══════════════════════════════════════════════════════════╗
║   ✅ SETUP COMPLETE!                                     ║
╚══════════════════════════════════════════════════════════╝

Next steps:
1. Start the server:
   python server_main.py

2. Access the dashboard:
   http://localhost:5000/dashboard

3. Login with default credentials:
   Username: admin
   Password: changeme123
   
4. IMPORTANT: Change the admin password immediately!

5. If restoring from backup:
   python scripts/restore_database.py --input backup_file.sql
    """)
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
