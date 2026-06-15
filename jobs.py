"""
MeterMind scheduled jobs
Runs every day at 7am, checks properties whose check_day == today's date.
"""

import logging
from datetime import datetime, date
from flask_mail import Message

log = logging.getLogger(__name__)


def run_daily_checks(app):
    with app.app_context():
        from app import db, mail
        from models import Property, Alert
        from scraper import scrape_property, make_session, get_csrf_token

        today_day = date.today().day
        props = Property.query.filter_by(check_day=today_day).all()

        if not props:
            log.info(f"Daily check: no properties scheduled for day {today_day}.")
            return

        log.info(f"Daily check: {len(props)} property/ies scheduled for day {today_day}.")

        session = make_session()
        try:
            token = get_csrf_token(session)
        except Exception:
            token = ""

        for prop in props:
            try:
                details = scrape_property(prop, session, token)
                if not details:
                    log.error(f"Scrape failed for property {prop.id} — {prop.service_address}")
                    prop.scrape_status = "error"
                    db.session.commit()
                    continue

                # Update property fields
                for key, val in details.items():
                    if hasattr(prop, key):
                        setattr(prop, key, val)
                db.session.commit()

                alerts_to_send = []

                # ── No new bill check ─────────────────────────────────────────
                if prop.no_new_bill:
                    days = prop.days_since_bill
                    msg  = (f"No new bill generated for {prop.service_address}. "
                            f"Last bill was {days} days ago.")
                    alerts_to_send.append(("no_new_bill", msg, None))

                # ── High bill / high balance check ────────────────────────────
                elif prop.is_over_max:
                    amount = (prop.current_bill if prop.alert_type == "high_bill"
                              else prop.previous_balance)
                    label  = "bill" if prop.alert_type == "high_bill" else "balance"
                    msg    = (f"{prop.service_address}: {label} of ${amount:.2f} "
                              f"exceeds your limit of ${prop.max_bill_amount:.2f}.")
                    alerts_to_send.append((prop.alert_type, msg, amount))

                # ── Save alerts ───────────────────────────────────────────────
                for alert_type, message, amount in alerts_to_send:
                    # In-app alert
                    if prop.notify_inapp:
                        alert = Alert(
                            property_id=prop.id,
                            alert_type=alert_type,
                            message=message,
                            amount=amount,
                            is_read=False,
                            emailed=False,
                        )
                        db.session.add(alert)
                        db.session.commit()

                    # Email alert
                    if prop.notify_email and prop.owner.email:
                        try:
                            send_alert_email(mail, prop.owner.email,
                                             prop.owner.username, message)
                            # Mark as emailed
                            if prop.notify_inapp:
                                alert.emailed = True
                                db.session.commit()
                        except Exception as e:
                            log.error(f"Failed to send email for property {prop.id}: {e}")

            except Exception as e:
                log.error(f"Error processing property {prop.id}: {e}")
                continue

        log.info("Daily check complete.")


def send_alert_email(mail, to_email, username, message):
    msg = Message(
        subject="MeterMind — Water Bill Alert",
        recipients=[to_email],
        html=f"""
        <div style="font-family:sans-serif;max-width:500px;margin:0 auto">
          <h2 style="color:#1a56db">MeterMind Alert</h2>
          <p>Hi {username},</p>
          <p>{message}</p>
          <p style="margin-top:24px">
            <a href="#" style="background:#1a56db;color:white;padding:10px 20px;
               border-radius:6px;text-decoration:none">Log in to MeterMind</a>
          </p>
          <p style="color:#6b7280;font-size:12px;margin-top:24px">
            Triangle Property Management · MeterMind Water Monitor
          </p>
        </div>
        """,
    )
    mail.send(msg)
