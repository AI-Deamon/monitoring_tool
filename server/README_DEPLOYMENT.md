# SentinelEdge Server - Deployment Guide

## Quick Start: Moving Server to New Machine

### Prerequisites
- Python 3.8 or higher
- PostgreSQL 12 or higher
- Git (optional)

### Step 1: Backup on Old Machine
```bash
cd server_v3/server
python scripts/backup_database.py
# Creates: sentineledge_backup_YYYYMMDD_HHMMSS.sql
```

### Step 2: Setup on New Machine

#### Option A: Fresh Installation
```bash
# 1. Copy server files to new machine
# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Create .env file
copy .env.template .env
# Edit .env with your database credentials

# 4. Create PostgreSQL database
createdb sentineledge

# 5. Restore backup
python scripts/restore_database.py --input sentineledge_backup_YYYYMMDD_HHMMSS.sql

# 6. Start server
python server_main.py
```

#### Option B: Using Setup Script (Coming Soon)
```bash
python scripts/setup_new_machine.py
```

### Step 3: Update Agent Configurations
After moving server to new IP/hostname, update all agents:
```json
// In Agent/config.json on each machine
{
  "server_url": "http://NEW_SERVER_IP:5000"
}
```

## Configuration Files

### .env (Server Configuration)
```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/sentineledge
SERVER_HOST=0.0.0.0
SERVER_PORT=5000
SECRET_KEY=your-secret-key-here
```

### Important Notes
- **SECRET_KEY**: Generate a new random key for production
- **DATABASE_URL**: Update with your PostgreSQL credentials
- **SERVER_HOST**: Use 0.0.0.0 to accept connections from all network interfaces

## Troubleshooting

### Database Connection Failed
```bash
# Check PostgreSQL is running
pg_isready

# Test connection manually
psql -U postgres -d sentineledge
```

### Port Already in Use
```bash
# Change SERVER_PORT in .env
SERVER_PORT=5001
```

### Migration Errors
```bash
# Run migrations manually
cd server_v3/server
alembic upgrade head
```

## Security Checklist
- [ ] Change default admin password (admin/changeme123)
- [ ] Generate new SECRET_KEY
- [ ] Use strong PostgreSQL password
- [ ] Configure firewall rules
- [ ] Enable HTTPS in production
