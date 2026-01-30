# Windows Database Setup Guide

## Prerequisites
1. PostgreSQL 16 installed on Windows
2. Backup file from your Linux server (`.dump` or `.sql` format)
3. Python 3.11+ installed
4. Git Bash or PowerShell

## Step-by-Step Setup

### 1. Get Backup from Linux Server

On your **Linux server**, create a backup:

```bash
# Navigate to server directory
cd /path/to/server

# Create backup
pg_dump -h localhost -U postgres -Fc -f sentineledge_backup.dump sentinel_edge_v1

# Or if using different credentials
pg_dump -h localhost -U your_user -Fc -f sentineledge_backup.dump your_database_name
```

Transfer the `sentineledge_backup.dump` file to your Windows machine (e.g., `C:\backup\`).

### 2. Setup Database on Windows

Run the setup script:

```cmd
cd C:\Users\Pittala Bhaskar\Downloads\Agent_3.0\Agent_v3.0.1\Agent\server_v3\server
setup_windows_db.bat
```

When prompted:
- Enter the full path to your backup file
- Enter your PostgreSQL `postgres` user password

The script will:
- Create the `sentinelserver` user
- Create the `sentinel_edge_v1` database
- Restore all data from the backup

### 3. Setup Python Environment

```cmd
# Create virtual environment
python -m venv venv

# Activate it
venv\Scripts\activate

# Install dependencies
pip install -r server_requirements.txt
```

### 4. Verify Configuration

Check that `.env` file has the correct DATABASE_URL:

```ini
DATABASE_URL=postgresql://sentinelserver:sentinel_edge_secure@localhost:5432/sentinel_edge_v1
```

### 5. Start the Server

```cmd
start_server.bat
```

The server will:
- Check database connection
- Run startup checks
- Start on `http://localhost:5050`

### 6. Access Dashboard

Open your browser and navigate to:
- Dashboard: `http://localhost:5050/dashboard/`
- Login with: `admin` / `changeme123`

## Troubleshooting

### Issue: "Database connection failed"
**Solution**: 
- Verify PostgreSQL is running: `services.msc` → PostgreSQL 16
- Check credentials in `.env` file
- Test connection: `psql -h localhost -U sentinelserver -d sentinel_edge_v1`

### Issue: "No data showing in dashboard"
**Solution**:
- Verify backup was restored: `psql -h localhost -U sentinelserver -d sentinel_edge_v1 -c "SELECT COUNT(*) FROM agents;"`
- Check agent registration in the database
- Ensure agents are sending data to the Windows server

### Issue: "Template errors (UUID slicing)"
**Solution**:
- Restart the server to clear template cache
- Clear browser cache (Ctrl+F5)
- Check `server.log` for errors

### Issue: "Port 5050 already in use"
**Solution**:
- Change `SERVER_PORT` in `.env` file
- Or stop the conflicting process: `netstat -ano | findstr :5050`

## Database Schema Verification

After restore, verify the schema:

```sql
-- Connect to database
psql -h localhost -U sentinelserver -d sentinel_edge_v1

-- Check tables
\dt

-- Check agent_id column type in agents table
\d agents

-- Verify data
SELECT agent_id, hostname, last_seen FROM agents LIMIT 5;
```

Expected output:
- `agent_id` should be type `uuid`
- You should see your agents from the Linux server

## Next Steps

1. **Configure Firewall**: Allow port 5050 if agents are on different machines
2. **Update Agent Config**: Point agents to Windows server IP
3. **Monitor Logs**: Check `server.log` for any errors
4. **Backup Regularly**: Set up automated backups on Windows

## Notes

- The database credentials are:
  - User: `sentinelserver`
  - Password: `sentinel_edge_secure`
  - Database: `sentinel_edge_v1`
  
- All fixes for UUID/integer type mismatches have been applied
- Template slicing errors have been fixed
- API endpoints now correctly use UUID instead of integer IDs
