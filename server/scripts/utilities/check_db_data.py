from server_app import create_app
from extensions import db
import server_models
from sqlalchemy import desc

app = create_app()

with app.app_context():
    print("=== Registered Agents ===")
    agents = server_models.Agent.query.all()
    for a in agents:
        print(f"ID: {a.id}\nHost: {a.hostname}\nOS: {a.os}\nLast Seen: {a.last_seen}")

    if not agents:
        print("No agents found.")
        exit()

    # check specifically for the agent we saw in logs if possible, otherwise first one
    target_agent = None
    for a in agents:
        if a.id == 'b4afd93c-0d0c-49cf-b6f9-f497dd8e3599':
            target_agent = a
            break
    
    if not target_agent:
        target_agent = agents[0]

    agent_id = target_agent.id
    print(f"\n\n=== Data for Agent {agent_id} ({target_agent.hostname}) ===")

    print("\n[1] Live Status (agent_current_status table)")
    status = server_models.AgentCurrentStatus.query.filter_by(agent_id=agent_id).first()
    if status:
        print(f"  Current App: {status.current_app}")
        print(f"  Window: {status.window_title}")
        print(f"  Current Domain: {status.current_domain}")
        print(f"  State: {status.current_state}")
        print(f"  Last Seen: {status.last_seen}")
    else:
        print("  No live status data found.")

    print("\n[2] Screen Time (screen_time table - Today's Totals)")
    st = server_models.ScreenTime.query.filter_by(agent_id=agent_id).order_by(desc(server_models.ScreenTime.date)).first()
    if st:
        print(f"  Date: {st.date}")
        print(f"  Active: {st.active_seconds}s")
        print(f"  Idle: {st.idle_seconds}s")
        print(f"  Locked: {st.locked_seconds}s")
    else:
        print("  No screen time data found.")

    print("\n[3] App Usage (app_usage table - Top 5 Today)")
    apps = server_models.AppUsage.query.filter_by(agent_id=agent_id).order_by(desc(server_models.AppUsage.duration_seconds)).limit(5).all()
    if apps:
        for a in apps:
            print(f"  {a.app}: {a.duration_seconds}s ({a.session_count} sessions)")
    else:
        print("  No app usage data found.")

    print("\n[4] Domain Usage (domain_usage table - Top 5 Today)")
    domains = server_models.DomainUsage.query.filter_by(agent_id=agent_id).order_by(desc(server_models.DomainUsage.duration_seconds)).limit(5).all()
    if domains:
        for d in domains:
            print(f"  {d.domain}: {d.duration_seconds}s ({d.session_count} sessions)")
    else:
        print("  No domain usage data found.")

    print("\n[5] Browser History (domain_visits table - Recent 5)")
    visits = server_models.DomainVisit.query.filter_by(agent_id=agent_id).order_by(desc(server_models.DomainVisit.visited_at)).limit(5).all()
    if visits:
        for v in visits:
            print(f"  {v.visited_at} - {v.domain} ({v.browser})")
    else:
        print("  No browser history found.")

    print("\n[6] Inventory (app_inventory table)")
    inv_count = server_models.AppInventory.query.filter_by(agent_id=agent_id).count()
    print(f"  Total Installed Apps: {inv_count}")
    if inv_count > 0:
        sample = server_models.AppInventory.query.filter_by(agent_id=agent_id).limit(3).all()
        print(f"  Sample: {', '.join([a.name for a in sample])}...")

    print("\n[7] State Changes (state_changes table - Recent 5)")
    changes = server_models.StateChange.query.filter_by(agent_id=agent_id).order_by(desc(server_models.StateChange.timestamp)).limit(5).all()
    if changes:
        for c in changes:
            print(f"  {c.timestamp}: {c.previous_state} -> {c.current_state}")
    else:
        print("  No state changes recorded.")
