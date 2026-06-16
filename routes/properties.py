from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import Property, Alert
from app import db
from scraper import make_session, get_csrf_token, verify_address, scrape_bill_details

props_bp = Blueprint("props", __name__, url_prefix="/properties")


@props_bp.route("/add", methods=["GET", "POST"])
@login_required
def add():
    if request.method == "POST":
        account_number  = request.form.get("account_number", "").strip()
        service_address = request.form.get("service_address", "").strip()
        account_id      = request.form.get("account_id", "").strip()
        max_bill        = request.form.get("max_bill_amount", "200")
        alert_type      = request.form.get("alert_type", "high_bill")
        notify_inapp    = bool(request.form.get("notify_inapp"))
        notify_email    = bool(request.form.get("notify_email"))
        check_day       = int(request.form.get("check_day", 1))

        if not account_number or not service_address:
            flash("Account number and service address are required.", "error")
            return render_template("add_property.html")

        # Validate account number format
        if not account_number.isdigit() or not (8 <= len(account_number) <= 12):
            flash("Account number should be 8–12 digits.", "error")
            return render_template("add_property.html")

        try:
            max_bill_f = float(max_bill)
        except ValueError:
            max_bill_f = 200.0

        if check_day < 1 or check_day > 28:
            check_day = 1

        prop = Property(
            user_id         = current_user.id,
            account_number  = account_number,
            service_address = service_address,
            account_id      = account_id or None,
            max_bill_amount = max_bill_f,
            alert_type      = alert_type,
            notify_inapp    = notify_inapp,
            notify_email    = notify_email,
            check_day       = check_day,
            scrape_status   = "pending",
        )
        db.session.add(prop)
        db.session.commit()

        flash(f"Property added: {service_address}", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("add_property.html")


@props_bp.route("/<int:prop_id>/edit", methods=["GET", "POST"])
@login_required
def edit(prop_id):
    prop = Property.query.get_or_404(prop_id)
    if prop.user_id != current_user.id:
        flash("Not authorized.", "error")
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        prop.service_address = request.form.get("service_address", prop.service_address).strip()
        prop.account_id      = request.form.get("account_id", "").strip() or None
        prop.max_bill_amount = float(request.form.get("max_bill_amount", prop.max_bill_amount))
        prop.alert_type      = request.form.get("alert_type", prop.alert_type)
        prop.notify_inapp    = bool(request.form.get("notify_inapp"))
        prop.notify_email    = bool(request.form.get("notify_email"))
        prop.check_day       = int(request.form.get("check_day", prop.check_day))
        db.session.commit()
        flash("Property updated.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("edit_property.html", prop=prop)


@props_bp.route("/<int:prop_id>/delete", methods=["POST"])
@login_required
def delete(prop_id):
    prop = Property.query.get_or_404(prop_id)
    if prop.user_id != current_user.id:
        flash("Not authorized.", "error")
        return redirect(url_for("main.dashboard"))
    db.session.delete(prop)
    db.session.commit()
    flash("Property removed.", "success")
    return redirect(url_for("main.dashboard"))


@props_bp.route("/<int:prop_id>/check", methods=["POST"])
@login_required
def manual_check(prop_id):
    """Run an immediate bill check for one property."""
    prop = Property.query.get_or_404(prop_id)
    if prop.user_id != current_user.id:
        return jsonify({"error": "Not authorized"}), 403

    details = scrape_bill_details(prop.account_number)
    if not details:
        prop.scrape_status = "error"
        db.session.commit()
        flash(f"Could not retrieve bill for {prop.service_address}. Try again shortly.", "error")
        return redirect(url_for("main.dashboard"))

    from datetime import datetime
    for key, val in details.items():
        if hasattr(prop, key):
            setattr(prop, key, val)
    prop.last_scraped_at = datetime.utcnow()
    prop.scrape_status   = "ok"

    # Check alerts
    if prop.no_new_bill:
        days = prop.days_since_bill
        msg  = f"No new bill generated for {prop.service_address}. Last bill was {days} days ago."
        _save_alert(prop, "no_new_bill", msg, None)
        flash(msg, "warning")

    elif prop.is_over_max:
        amount = prop.current_bill if prop.alert_type == "high_bill" else prop.previous_balance
        label  = "bill" if prop.alert_type == "high_bill" else "balance"
        msg    = (f"{prop.service_address}: {label} of ${amount:.2f} "
                  f"exceeds your limit of ${prop.max_bill_amount:.2f}.")
        _save_alert(prop, prop.alert_type, msg, amount)
        flash(msg, "warning")
    else:
        flash(f"Bill check complete for {prop.service_address}. No alerts.", "success")

    db.session.commit()
    return redirect(url_for("main.dashboard"))


def _save_alert(prop, alert_type, message, amount):
    from models import Alert
    if prop.notify_inapp:
        db.session.add(Alert(
            property_id=prop.id,
            alert_type=alert_type,
            message=message,
            amount=amount,
        ))
    if prop.notify_email and prop.owner.email:
        try:
            from app import mail
            from jobs import send_alert_email
            send_alert_email(mail, prop.owner.email, prop.owner.username, message)
        except Exception:
            pass
