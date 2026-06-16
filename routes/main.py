from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from models import Alert, Property
from app import db

main_bp = Blueprint("main", __name__)


@main_bp.route("/dashboard")
@login_required
def dashboard():
    properties = Property.query.filter_by(user_id=current_user.id).order_by(Property.service_address).all()

    # Unread alerts for this user's properties
    prop_ids = [p.id for p in properties]
    unread_alerts = (Alert.query
                     .filter(Alert.property_id.in_(prop_ids), Alert.is_read == False)
                     .order_by(Alert.created_at.desc())
                     .all()) if prop_ids else []

    return render_template("dashboard.html",
                           properties=properties,
                           unread_alerts=unread_alerts)


@main_bp.route("/alerts/mark-read/<int:alert_id>", methods=["POST"])
@login_required
def mark_alert_read(alert_id):
    alert = Alert.query.get_or_404(alert_id)
    # Security: make sure this alert belongs to the current user
    if alert.property.user_id == current_user.id:
        alert.is_read = True
        db.session.commit()
    from flask import jsonify
    return jsonify({"ok": True})


@main_bp.route("/alerts/mark-all-read", methods=["POST"])
@login_required
def mark_all_read():
    prop_ids = [p.id for p in current_user.properties]
    if prop_ids:
        Alert.query.filter(
            Alert.property_id.in_(prop_ids),
            Alert.is_read == False
        ).update({"is_read": True}, synchronize_session=False)
        db.session.commit()
    from flask import redirect, url_for
    return redirect(url_for("main.dashboard"))
