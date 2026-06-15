"""
MeterMind - Baltimore City Water Bill Monitor
Flask application entry point
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from apscheduler.schedulers.background import BackgroundScheduler
import os
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
scheduler = BackgroundScheduler()


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me-in-production")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///metermind.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Email config (Gmail)
    app.config["MAIL_SERVER"]   = "smtp.gmail.com"
    app.config["MAIL_PORT"]     = 587
    app.config["MAIL_USE_TLS"]  = True
    app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
    app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_USERNAME")

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access MeterMind."
    login_manager.login_message_category = "info"

    from routes.auth   import auth_bp
    from routes.main   import main_bp
    from routes.properties import props_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(props_bp)

    with app.app_context():
        db.create_all()
        start_scheduler(app)

    return app


def start_scheduler(app):
    from jobs import run_daily_checks
    scheduler.add_job(
        func=lambda: run_daily_checks(app),
        trigger="cron",
        hour=7,
        minute=0,
        id="daily_check",
        replace_existing=True,
    )
    if not scheduler.running:
        scheduler.start()


if __name__ == "__main__":
    app = create_app()
    app.run(debug=False, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
