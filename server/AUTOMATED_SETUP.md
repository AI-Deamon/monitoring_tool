# 🚀 Automated Setup Guide

This guide shows you how to set up the SentinelEdge server with **one command** instead of following all the manual steps in QUICKSTART.md.

## Quick Start (Automated)

### 1. Make the script executable:
```bash
chmod +x setup.sh
```

### 2. Run the automated setup:
```bash
./setup.sh
```

That's it! The script will:
- ✅ Check Python and PostgreSQL installation
- ✅ Create virtual environment
- ✅ Install all dependencies
- ✅ Create PostgreSQL database and user
- ✅ Generate secure `.env` file
- ✅ Run all Alembic migrations
- ✅ Verify everything works

### 3. Start the server:
```bash
python start_server.py
```

### 4. Access the dashboard:
```
http://localhost:5050/dashboard
Login: admin / changeme123
```

---

## What the Script Does

The `setup.sh` script automates all 7 steps from QUICKSTART.md:

| Step | What It Does | Manual Equivalent |
|------|--------------|-------------------|
| 1 | Check prerequisites (Python, PostgreSQL) | Manual verification |
| 2 | Create virtual environment | `python3 -m venv venv` |
| 3 | Install dependencies | `pip install -r server_requirements.txt` |
| 4 | Create database and user | Multiple `psql` commands |
| 5 | Generate `.env` file | Manual file creation |
| 6 | Run migrations | `alembic upgrade head` |
| 7 | Verify setup | Manual testing |

---

## Default Configuration

The script creates these defaults:

- **Database Name:** `sentineledge`
- **Database User:** `sentinel_user`
- **Database Password:** `sentinel_secure_password_2024`
- **Server Port:** `5050`
- **Secret Key:** Auto-generated secure random key

All settings are saved in the `.env` file.

---

## Troubleshooting

### PostgreSQL Not Running
If you get "PostgreSQL service is not running":
```bash
sudo systemctl start postgresql
sudo systemctl enable postgresql  # Start on boot
```

### Permission Denied
If you get "Permission denied":
```bash
chmod +x setup.sh
```

### Database Already Exists
The script will ask if you want to drop and recreate the database. Choose:
- **Yes (y):** Fresh installation (all data will be lost)
- **No (n):** Keep existing database

### Python Version Issues
Ensure you have Python 3.8 or higher:
```bash
python3 --version
```

---

## Production Hardened Registration

By default, the automated setup uses `FLASK_ENV=development` to allow agents to register easily for the first time. For a secure production environment, you should protect the registration endpoint:

### 1. Set a Registration Secret
Edit your `.env` file and uncomment/set the secret:
```bash
REGISTRATION_SECRET=your-secure-password
```

### 2. Switch to Production Mode
Change the environment in `.env`:
```bash
FLASK_ENV=production
```

### 3. Configure Agents
Once the server is in production mode, all new agents **must** include the secret in their configuration to register.

---

## Troubleshooting

If you prefer manual setup or need to customize settings, follow the detailed steps in [QUICKSTART.md](./QUICKSTART.md).

---

## Need Help?

- **Automated Setup Issues:** Check the script output for specific errors
- **Manual Setup:** See [QUICKSTART.md](./QUICKSTART.md)
- **Production Deployment:** See [production_deployment_guide.md](./production_deployment_guide.md)
