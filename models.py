from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(64), unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin      = db.Column(db.Boolean, default=False)

    properties = db.relationship("Property", backref="owner", lazy=True,
                                  cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"


class Property(db.Model):
    __tablename__ = "properties"

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Baltimore water portal identifiers
    account_number  = db.Column(db.String(20), nullable=False)
    service_address = db.Column(db.String(200), nullable=False)
    account_id      = db.Column(db.String(50))   # optional 3rd identifier

    # Alert settings
    max_bill_amount = db.Column(db.Float, default=200.0)
    alert_type      = db.Column(db.String(20), default="high_bill")  # high_bill | high_balance
    notify_inapp    = db.Column(db.Boolean, default=True)
    notify_email    = db.Column(db.Boolean, default=False)

    # Schedule: day of month to run check (1-28)
    check_day       = db.Column(db.Integer, default=1)

    # Latest scraped data
    current_bill      = db.Column(db.Float)
    previous_balance  = db.Column(db.Float)
    penalty_date      = db.Column(db.String(20))
    current_read_date = db.Column(db.String(20))
    current_bill_date = db.Column(db.String(20))
    last_pay_date     = db.Column(db.String(20))
    last_pay_amount   = db.Column(db.Float)
    last_scraped_at   = db.Column(db.DateTime)
    scrape_status     = db.Column(db.String(20), default="pending")  # pending|ok|error

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    alerts = db.relationship("Alert", backref="property", lazy=True,
                              cascade="all, delete-orphan")

    @property
    def days_since_bill(self):
        if not self.current_bill_date:
            return None
        try:
            bill_dt = datetime.strptime(self.current_bill_date, "%m/%d/%Y")
            return (datetime.utcnow() - bill_dt).days
        except ValueError:
            return None

    @property
    def no_new_bill(self):
        d = self.days_since_bill
        return d is not None and d > 33

    @property
    def is_over_max(self):
        if self.alert_type == "high_bill" and self.current_bill is not None:
            return self.current_bill > self.max_bill_amount
        if self.alert_type == "high_balance" and self.previous_balance is not None:
            return self.previous_balance > self.max_bill_amount
        return False

    def __repr__(self):
        return f"<Property {self.account_number} - {self.service_address}>"


class Alert(db.Model):
    __tablename__ = "alerts"

    id          = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id"), nullable=False)
    alert_type  = db.Column(db.String(30))   # high_bill | high_balance | no_new_bill
    message     = db.Column(db.String(500))
    amount      = db.Column(db.Float)
    is_read     = db.Column(db.Boolean, default=False)
    emailed     = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Alert {self.alert_type} - {self.property_id}>"
