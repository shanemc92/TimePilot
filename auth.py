import logging
import re

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError

from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db, limiter
from models import User

bp = Blueprint("auth", __name__)

# Shares the app's security-event logger (configured in create_app).
logger = logging.getLogger("timepilot")

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# A fixed dummy hash so login always pays the same hashing cost whether or
# not the username exists - otherwise "unknown user" returns fast (no hash
# check ran) while "known user, wrong password" takes ~100ms, and that gap
# is enough to enumerate valid usernames by timing.
_DUMMY_HASH = generate_password_hash("not-a-real-password-just-for-timing")


class SignupForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3, max=32)])
    # 12+ applies to NEW accounts only - existing users' passwords are
    # unaffected (login has no length check).
    password = PasswordField("Password", validators=[DataRequired(), Length(
        min=12, message="At least 12 characters - a few random words make a strong passphrase")])
    confirm = PasswordField("Confirm password", validators=[DataRequired(), EqualTo("password", message="Passwords don't match")])
    submit = SubmitField("Create account")

    def validate_username(self, field):
        if not USERNAME_RE.match(field.data):
            raise ValidationError("Letters, numbers, - and _ only")
        if User.query.filter_by(username=field.data.lower()).first():
            raise ValidationError("That username is taken")


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in")


@bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("10/minute")
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = SignupForm()
    if form.validate_on_submit():
        user = User(username=form.username.data.lower())
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        logger.info("new account created: %s (from %s)", user.username, request.remote_addr)
        login_user(user, remember=True)
        return redirect(url_for("index"))
    return render_template("signup.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10/minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.lower()).first()
        # always hash-check something, so a nonexistent username takes the
        # same time as a wrong password on a real one (see _DUMMY_HASH above)
        ok = user.check_password(form.password.data) if user else (
            check_password_hash(_DUMMY_HASH, form.password.data) and False)
        if user and ok:
            login_user(user, remember=True)
            logger.info("login OK: %s (from %s)", user.username, request.remote_addr)
            return redirect(url_for("index"))
        logger.warning("login FAILED for username %r (from %s)",
                       form.username.data, request.remote_addr)
        flash("Invalid username or password.", "error")
    return render_template("login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
