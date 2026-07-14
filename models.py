from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class UserData(db.Model):
    """One encrypted row per (user, domain). Domains mirror the app's data
    model: settings / tasks / history / notes / snippets / clipboard /
    runtime / calendar_ics. JSON domains store an encrypted JSON document;
    calendar_ics stores the encrypted raw .ics bytes."""
    __tablename__ = "user_data"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    domain = db.Column(db.String(20), nullable=False)
    encrypted_blob = db.Column(db.LargeBinary, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                            onupdate=_utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", "domain", name="uq_user_domain"),
    )
