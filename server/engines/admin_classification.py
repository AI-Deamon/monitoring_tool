"""
Admin endpoints for domain classification management
"""

from flask import Blueprint, request, jsonify, render_template
from extensions import db
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

admin_classification_bp = Blueprint('admin_classification', __name__)

# ========================================================================
# CLASSIFICATION RULES MANAGEMENT
# ========================================================================

@admin_classification_bp.route('/api/admin/classification/rules', methods=['GET'])
def get_classification_rules():
    """Get all classification rules"""
    try:
        result = db.session.execute(text('''
            SELECT id, pattern, pattern_type, classified_as, action, 
                   priority, is_active, match_count, last_matched_at,
                   created_by, created_at
            FROM domain_classification_rules
            ORDER BY priority ASC, created_at DESC
        '''))

        rules = []
        for row in result:
            rules.append({
                'id': row[0],
                'pattern': row[1],
                'pattern_type': row[2],
                'classified_as': row[3],
                'action': row[4],
                'priority': row[5],
                'is_active': row[6],
                'match_count': row[7],
                'last_matched_at': row[8].isoformat() if row[8] else None,
                'created_by': row[9],
                'created_at': row[10].isoformat() if row[10] else None
            })

        return jsonify({'rules': rules})

    except Exception as e:
        logger.error(f"Error fetching rules: {e}")
        return jsonify({'error': str(e)}), 500


@admin_classification_bp.route('/api/admin/classification/rules', methods=['POST'])
def create_classification_rule():
    """Create new classification rule"""
    try:
        data = request.get_json()

        # Validate required fields
        required = ['pattern', 'classified_as', 'action']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing field: {field}'}), 400

        # Insert rule
        result = db.session.execute(text('''
            INSERT INTO domain_classification_rules
            (pattern, pattern_type, classified_as, action, priority, created_by)
            VALUES (:pattern, :pattern_type, :classified_as, :action, :priority, :created_by)
            RETURNING id
        '''), {
            'pattern': data['pattern'],
            'pattern_type': data.get('pattern_type', 'substring'),
            'classified_as': data['classified_as'],
            'action': data['action'],
            'priority': data.get('priority', 100),
            'created_by': data.get('created_by', 'admin')
        })

        rule_id = result.fetchone()[0]
        db.session.commit()

        # Clear classifier cache
        try:
            from domain_classifier import get_classifier
            classifier = get_classifier(db)
            classifier.clear_cache()
        except:
            pass

        logger.info(f"[ADMIN] Created classification rule: {data['pattern']}")

        return jsonify({'status': 'success', 'rule_id': rule_id})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating rule: {e}")
        return jsonify({'error': str(e)}), 500


@admin_classification_bp.route('/api/admin/classification/rules/<int:rule_id>', methods=['PUT'])
def update_classification_rule(rule_id):
    """Update classification rule"""
    try:
        data = request.get_json()

        # Build update query dynamically
        updates = []
        params = {'rule_id': rule_id}

        if 'pattern' in data:
            updates.append('pattern = :pattern')
            params['pattern'] = data['pattern']
        if 'classified_as' in data:
            updates.append('classified_as = :classified_as')
            params['classified_as'] = data['classified_as']
        if 'action' in data:
            updates.append('action = :action')
            params['action'] = data['action']
        if 'priority' in data:
            updates.append('priority = :priority')
            params['priority'] = data['priority']
        if 'is_active' in data:
            updates.append('is_active = :is_active')
            params['is_active'] = data['is_active']

        if not updates:
            return jsonify({'error': 'No fields to update'}), 400

        updates.append('updated_at = NOW()')

        query = f'''
            UPDATE domain_classification_rules
            SET {', '.join(updates)}
            WHERE id = :rule_id
        '''

        db.session.execute(text(query), params)
        db.session.commit()

        # Clear classifier cache
        try:
            from domain_classifier import get_classifier
            classifier = get_classifier(db)
            classifier.clear_cache()
        except:
            pass

        logger.info(f"[ADMIN] Updated classification rule: {rule_id}")

        return jsonify({'status': 'success'})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating rule: {e}")
        return jsonify({'error': str(e)}), 500


@admin_classification_bp.route('/api/admin/classification/rules/<int:rule_id>', methods=['DELETE'])
def delete_classification_rule(rule_id):
    """Delete classification rule"""
    try:
        db.session.execute(text('''
            DELETE FROM domain_classification_rules WHERE id = :rule_id
        '''), {'rule_id': rule_id})
        db.session.commit()

        # Clear classifier cache
        try:
            from domain_classifier import get_classifier
            classifier = get_classifier(db)
            classifier.clear_cache()
        except:
            pass

        logger.info(f"[ADMIN] Deleted classification rule: {rule_id}")

        return jsonify({'status': 'success'})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting rule: {e}")
        return jsonify({'error': str(e)}), 500


# ========================================================================
# REVIEW QUEUE
# ========================================================================

@admin_classification_bp.route('/api/admin/classification/review-queue', methods=['GET'])
def get_review_queue():
    """Get sessions that need manual classification"""
    try:
        # Get sessions with needs_review = TRUE
        # Group by raw_title for easier review
        result = db.session.execute(text('''
            SELECT 
                raw_title,
                raw_url,
                COUNT(*) as session_count,
                SUM(duration_seconds) as total_duration,
                MAX(created_at) as last_seen,
                MIN(id) as first_session_id
            FROM domain_sessions
            WHERE needs_review = TRUE
                AND raw_title IS NOT NULL
            GROUP BY raw_title, raw_url
            ORDER BY session_count DESC, last_seen DESC
            LIMIT 100
        '''))

        queue = []
        for row in result:
            queue.append({
                'raw_title': row[0],
                'raw_url': row[1],
                'session_count': row[2],
                'total_duration': float(row[3]) if row[3] else 0,
                'last_seen': row[4].isoformat() if row[4] else None,
                'first_session_id': row[5]
            })

        return jsonify({'queue': queue})

    except Exception as e:
        logger.error(f"Error fetching review queue: {e}")
        return jsonify({'error': str(e)}), 500


@admin_classification_bp.route('/api/admin/classification/classify', methods=['POST'])
def classify_sessions():
    """Manually classify sessions"""
    try:
        data = request.get_json()

        raw_title = data.get('raw_title')
        classified_as = data.get('classified_as')
        action = data.get('action', 'map')
        create_rule = data.get('create_rule', False)

        if not raw_title or not classified_as:
            return jsonify({'error': 'Missing required fields'}), 400

        # Update all matching sessions
        if action == 'ignore':
            # Delete sessions that should be ignored
            result = db.session.execute(text('''
                DELETE FROM domain_sessions
                WHERE raw_title = :raw_title AND needs_review = TRUE
            '''), {'raw_title': raw_title})
            updated_count = result.rowcount
        else:
            # Update domain and mark as reviewed
            result = db.session.execute(text('''
                UPDATE domain_sessions
                SET domain = :classified_as,
                    domain_source = 'admin',
                    needs_review = FALSE
                WHERE raw_title = :raw_title AND needs_review = TRUE
            '''), {'classified_as': classified_as, 'raw_title': raw_title})
            updated_count = result.rowcount

        # Create rule for future sessions if requested
        rule_id = None
        if create_rule:
            result = db.session.execute(text('''
                INSERT INTO domain_classification_rules
                (pattern, pattern_type, classified_as, action, priority, created_by)
                VALUES (:pattern, 'substring', :classified_as, :action, 50, 'admin')
                RETURNING id
            '''), {
                'pattern': raw_title[:50],
                'classified_as': classified_as,
                'action': action
            })
            rule_id = result.fetchone()[0]

            # Clear classifier cache
            try:
                from domain_classifier import get_classifier
                classifier = get_classifier(db)
                classifier.clear_cache()
            except:
                pass

        db.session.commit()

        logger.info(
            f"[ADMIN] Classified '{raw_title[:30]}...' as '{classified_as}' "
            f"(updated {updated_count} sessions, rule: {rule_id})"
        )

        return jsonify({
            'status': 'success',
            'updated_count': updated_count,
            'rule_id': rule_id
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error classifying sessions: {e}")
        return jsonify({'error': str(e)}), 500


# ========================================================================
# ADMIN UI PAGE
# ========================================================================

@admin_classification_bp.route('/admin/classification')
def classification_admin_page():
    """Render the admin classification UI"""
    return render_template('admin/classification.html')
