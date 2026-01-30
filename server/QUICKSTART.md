# SentinelEdge Server - Quick Start Guide 🚀

This guide will help you get the SentinelEdge server running on any machine with minimal effort.

---

## 📋 Prerequisites
- **Python 3.8+**
- **PostgreSQL 12+**
- Packages: `pip install -r server_requirements.txt`

---

## ⚡ Quick Start: The "One Command" Solution

The easiest way to start the server (automatically handles setup, tables, and procedures):

### **For Production (Windows & Linux)**
Automatically detects OS and uses **Waitress** (Windows) or **Gunicorn** (Linux):
```bash
python start_production.py
```

### **For Development**
Runs a standard Flask dev server with auto-setup:
```bash
python start_server.py
```

---

## 🛠️ Step-by-Step Manual Setup

### 1. Environment Configuration
Copy `.env.template` to `.env` and update your database credentials:
```bash
cp .env.template .env
# Edit .env with your PostgreSQL database URL
```

### 2. Auto-Setup (The 6-Step Verification)
If you want to run the setup/fixes **without starting the server**:
```bash
python start_server.py --no-start
```
**This script automatically:**
1. ✅ Checks Database Connection
2. ✅ Creates Database Tables
3. ✅ Installs Stored Procedures (Critical for telemetry)
4. ✅ Fixes Schema Issues (Missing columns/indices)
5. ✅ Ensures Admin User Exists (`admin` / `changeme123`)

---

## 🌍 Production Servers

### **Windows: Waitress**
Included in `start_production.py`, but can be run manually:
```bash
pip install waitress
python start_production.py
```

### **Linux: Gunicorn**
Optimized for high-performance Linux environments:
```bash
# Using our helper script (includes auto-setup)
./start_gunicorn.sh

# Or manual (advanced)
gunicorn -c gunicorn_config.py server_main:application
```

---

## 📊 Accessing the Server
- **Dashboard:** [http://localhost:5000/dashboard](http://localhost:5000/dashboard)
- **Root Health:** [http://localhost:5000/](http://localhost:5000/)
- **Default Credentials:** `admin` / `changeme123`

---

## 🆘 Troubleshooting

| Issue | Solution |
|-------|----------|
| **Database Connection Failed** | Ensure PostgreSQL is running and `DATABASE_URL` in `.env` is correct. |
| **Gunicorn: No module 'fcntl'** | Gunicorn is Linux-only. Use `python start_production.py` (will use Waitress). |
| **Telemetry Error: Function not found** | Run `python start_server.py --no-start` to reinstall stored procedures. |
| **Access Denied** | Verify your IP is allowed in `server_config.py` or `.env` (CORS settings). |

---

> [!IMPORTANT]
> **Change the default admin password immediately** in the Dashboard settings after your first login for security!
