"""
Events Models: StateChange, RawEvent
"""
from datetime import datetime
from extensions import db
from sqlalchemy.dialects import postgresql


class StateChange(db.Model):
    """State transition events (active/idle/locked)."""
    __tablename__ = 'state_changes'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id', ondelete='CASCADE'), nullable=False, index=True)
    username = db.Column(db.String(255), nullable=True)
    previous_state = db.Column(db.String(50), nullable=False)  # active, idle, locked
    current_state = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'agent_id': self.agent_id,
            'previous_state': self.previous_state,
            'current_state': self.current_state,
            'timestamp': self.timestamp.isoformat()
        }


class RawEvent(db.Model):
    """
    Raw event log for all incoming telemetry.
    Stores exact payload before processing for auditing and replay.
    """
    __tablename__ = 'raw_events'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id', ondelete='CASCADE'), nullable=False, index=True)
    event_type = db.Column(db.String(50), nullable=False)
    sequence = db.Column(db.Integer, nullable=True)  # From agent (if available)
    payload = db.Column(db.Text, nullable=False)  # JSON string
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed = db.Column(db.Boolean, default=False)
    error = db.Column(db.Text, nullable=True)
    
    __table_args__ = (
        db.Index('ix_raw_events_agent_seq', 'agent_id', 'sequence', 'event_type'),
    )
