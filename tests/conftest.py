"""
Pytest configuration for test suite.
Adds server and agent directories to Python path.

Run from the monitoring_tool repo root:  pytest tests/ -v
"""
import sys
from pathlib import Path

# monitoring_tool repo root (parent of tests/)
repo_root = Path(__file__).parent.parent
server_dir = repo_root / "server"
agent_dir = repo_root / "agent"

# Add repo root so 'server.xxx' and 'agent.xxx' work as packages
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Also add server dir directly so 'from server_app import ...' works
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

# Also add agent dir directly so 'from core.xxx import ...' works
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))
