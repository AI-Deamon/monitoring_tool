"""
Screen Time Spans Endpoint - Add to server_telemetry.py

This file contains the validation function and endpoint for screen time spans.
Copy the contents to server_telemetry.py after the safe_int function.
"""

def validate_span(span: dict, agent_id: str) -> tuple[bool, str]:
    """
    Validate screen time span before insertion.
    
    Checks:
    1. Duration range (1s - 86400s)
    2. Valid state ('active', 'idle', 'locked')
    3. Timestamp sanity
    4. Time ordering (start < end)
    5. Duration consistency (calculated vs reported, 5% tolerance)
    6. No future timestamps
    
    Returns: (is_valid, error_message)
    """
    duration = span.get('duration_seconds', 0)
    
    # Check 1: Duration range
    if duration < 1:
        return False, f"Duration too short: {duration}s"
    if duration > 86400:
        return False, f"Duration too long: {duration}s (max 24h)"
    
    # Check 2: Valid state
    valid_states = ['active', 'idle', 'locked']
    state = span.get('state')
    if state not in valid_states:
        return False, f"Invalid state: {state} (must be one of {valid_states})"
    
    # Check 3-6: Timestamp validation
    try:
        start = parse_agent_timestamp(span['start_time'], agent_id)
        end = parse_agent_timestamp(span['end_time'], agent_id)
        
        # Check 4: Time ordering
        if start >= end:
            return False, f"start_time >= end_time ({start} >= {end})"
        
        # Check 5: Duration consistency
        calculated = (end - start).total_seconds()
        drift = abs(calculated - duration)
        if drift > (duration * 0.05):  # 5% tolerance
            return False, f"Duration mismatch: reported={duration}s, calculated={calculated:.1f}s (drift={drift:.1f}s)"
        
        # Check 6: No future timestamps
        now = datetime.now(timezone.utc)
        if start > now:
            return False, f"Span in future: start={start}, now={now}"
        
    except Exception as e:
        return False, f"Timestamp parse error: {e}"
    
    return True, "OK"


@bp.route('/screentime-spans', methods=['POST'])
@require_auth
def telemetry_screentime_spans():
    """
    Receive screen time spans from agent.
    
    Idempotent: ON CONFLICT (span_id) DO NOTHING
    Validates: duration, state, timestamps, consistency
    """
    data = request.get_json() or {}
    agent_id = str(g.current_agent.agent_id)
    spans = data.get('spans', [])
    
    if not spans:
        return jsonify({'status': 'ok', 'inserted': 0, 'rejected': 0, 'total': 0})
    
    short_id = short_agent_id(agent_id)
    logger.info(f"[{short_id}] screentime-spans: Received {len(spans)} spans")
    
    inserted = 0
    rejected = 0
    
    for span in spans:
        # Validate span
        valid, reason = validate_span(span, agent_id)
        if not valid:
            logger.warning(f"[{short_id}] Rejected span: {reason}")
            rejected += 1
            continue
        
        try:
            # Parse timestamps
            start_time = parse_agent_timestamp(span['start_time'], agent_id)
            end_time = parse_agent_timestamp(span['end_time'], agent_id)
            
            # Insert with idempotency
            result = db.session.execute(text("""
                INSERT INTO screen_time_spans 
                (span_id, agent_id, state, start_time, end_time, duration_seconds)
                VALUES (:span_id, :agent_id::UUID, :state, :start_time, :end_time, :duration)
                ON CONFLICT (span_id) DO NOTHING
                RETURNING id
            """), {
                'span_id': span['span_id'],
                'agent_id': agent_id,
                'state': span['state'],
                'start_time': start_time,
                'end_time': end_time,
                'duration': span['duration_seconds']
            })
            
            if result.fetchone():
                inserted += 1
                
        except Exception as e:
            logger.error(f"[{short_id}] Failed to insert span {span.get('span_id')}: {e}")
            rejected += 1
    
    db.session.commit()
    
    logger.info(f"[{short_id}] screentime-spans: {inserted} inserted, {rejected} rejected")
    
    return jsonify({
        'status': 'ok', 
        'inserted': inserted, 
        'rejected': rejected,
        'total': len(spans)
    })


# Add to register_root_telemetry_endpoints function:
"""
    @app.route('/telemetry/screentime-spans', methods=['POST'])
    @require_auth
    def root_telemetry_screentime_spans():
        return telemetry_screentime_spans()
"""
