"""Sign-in, sign-up, sign-out, account settings and user management."""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from pymongo.errors import DuplicateKeyError

from earthscape.crypto import email_fields
from earthscape.db import db, notify, now
from earthscape.middleware import client_address

from . import auth

SIGNUP_ROLE = "Analyst"
SIGNUP_MESSAGE = "Thanks. An Admin will review your request, and you can sign in once it's approved."
PENDING_MESSAGE = "Your account is waiting for an Admin to approve it."
BAD_LOGIN = "Incorrect email or password."
TOO_MANY = "Too many failed sign-ins. Please try again in 15 minutes."
MIN_PASSWORD = 10


def next_page(request):
    """Safe redirect target."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}) and target.startswith("/"):
        return target
    return "/dashboard/"


def account_errors(name, email, password, confirm=None):
    """Shared field checks."""
    errors = []
    if not name:
        errors.append("Enter your name.")
    if len(name) > 100:
        errors.append("Name must not exceed 100 characters.")
    if not auth.EMAIL_PATTERN.match(email) or len(email) > 254:
        errors.append("Enter a valid email address.")
    if len(password) < MIN_PASSWORD:
        errors.append("Use a password of at least %d characters." % MIN_PASSWORD)
    if len(password) > 128:
        errors.append("Password must not exceed 128 characters.")
    if confirm is not None and password != confirm:
        errors.append("The two passwords don't match.")
    return errors


#----------------------------sign in--------------------------------------

def check_login(email, password, role, address):
    """Returns (user, error)."""
    if auth.login_blocked(email, address):
        return None, TOO_MANY
    user = auth.find_by_email(email)
    valid = auth.verify_password(password, user["password_hash"] if user else auth.DUMMY_HASH)
    if user and valid and user.get("pending"):
        # Only the password holder learns it's waiting
        return None, PENDING_MESSAGE
    if not user or not valid or not user.get("active", True):
        auth.record_failure(email, address)
        return None, BAD_LOGIN
    if role != user["role"]:
        return None, "This is an %s account. Use the %s sign-in instead." % (user["role"], user["role"])
    auth.clear_failures(email, address)
    return user, None


def login_view(request):
    if auth.current_user(request):
        return redirect(next_page(request))

    # Tab from the link
    role = "Admin" if request.GET.get("role") == "admin" else "Analyst"
    context = {"role": role, "next": request.GET.get("next", "")}

    if request.method == "POST":
        form_data = request.POST
        email = form_data.get("email", "").strip().lower()
        password = form_data.get("password", "")
        if form_data.get("role") in auth.ROLES:
            role = form_data.get("role")

        if not email or not password or len(email) > 254 or len(password) > 128:
            error = BAD_LOGIN
        else:
            user, error = check_login(email, password, role, client_address(request))
            if user:
                auth.sign_in(request, user)
                return redirect(next_page(request))

        context = {
            "role": role,
            "next": form_data.get("next", ""),
            "form_errors": [error],
            "form_data": {"email": email},
        }
        response = render(request, "accounts/login.html", context, status=429 if error == TOO_MANY else 401)
        if error == TOO_MANY:
            # When to retry
            response["Retry-After"] = str(auth.WINDOW_MINUTES * 60)
        return response

    return render(request, "accounts/login.html", context)


@require_POST
def logout_view(request):
    auth.sign_out(request)
    return redirect("accounts:login")


#----------------------------sign up--------------------------------------

def signup_view(request):
    if auth.current_user(request):
        return redirect("dashboard:home")

    if request.method == "POST":
        form_data = request.POST
        name = form_data.get("name", "").strip()
        title = form_data.get("title", "").strip()
        email = form_data.get("email", "").strip().lower()
        password = form_data.get("password", "")
        confirm = form_data.get("confirm", "")
        address = client_address(request)

        # Field checks
        errors = account_errors(name, email, password, confirm)
        if len(title) > 100:
            errors.append("Job title must not exceed 100 characters.")
        # Flood limit
        if not errors and auth.signup_blocked(address):
            errors.append("Too many sign-up requests from here. Please try again later.")

        if errors:
            context = {"form_errors": errors, "form_data": form_data}
            status = 429 if "Too many" in errors[0] else 200
            return render(request, "accounts/signup.html", context, status=status)

        auth.record_signup(address)
        try:
            # New accounts wait
            db.users.insert_one({
                "name": name, "title": title, **email_fields(email), "role": SIGNUP_ROLE,
                "active": False, "pending": True, "password_hash": auth.hash_password(password),
                "created_at": now(),
            })
        except DuplicateKeyError:
            # Same answer, so nobody learns who has an account
            pass
        else:
            for admin in db.users.find({"role": "Admin", "active": True}, {"_id": 1}):
                notify("%s asked for an Analyst account. Approve it in Users and roles." % name, str(admin["_id"]))

        context = {"done": True, "msg": SIGNUP_MESSAGE}
        return render(request, "accounts/signup.html", context)

    return render(request, "accounts/signup.html")


#----------------------------account settings--------------------------------------

@auth.login_required
def settings_view(request):
    user = auth.current_user(request)

    if request.method == "POST":
        form_data = request.POST

        if form_data.get("form") == "profile":
            # Profile form
            name = form_data.get("name", "").strip()
            title = form_data.get("title", "").strip()
            if not name or len(name) > 100 or len(title) > 100:
                messages.error(request, "Enter a name and title of up to 100 characters.")
            else:
                db.users.update_one({"_id": user["_id"]}, {"$set": {"name": name, "title": title}})
                messages.success(request, "Profile saved.")
        else:
            # Password form
            current_password = form_data.get("current_password", "")
            new_password = form_data.get("new_password", "")
            stored = db.users.find_one({"_id": user["_id"]})
            if not MIN_PASSWORD <= len(new_password) <= 128:
                messages.error(request, "Use a new password of at least %d characters." % MIN_PASSWORD)
            elif not auth.verify_password(current_password, stored["password_hash"]):
                messages.error(request, "Your current password is incorrect.")
            else:
                db.users.update_one({"_id": user["_id"]}, {"$set": {"password_hash": auth.hash_password(new_password)}})
                messages.success(request, "Password changed.")

        return redirect("accounts:settings")

    context = {"page": "settings"}
    return render(request, "dashboard/settings.html", context)


#----------------------------users and roles--------------------------------------

@auth.login_required
def users_view(request):
    rows = [auth.public_user(user) for user in db.users.find().sort("name", 1)]
    # Waiting requests first
    rows.sort(key=lambda row: not row["pending"])

    context = {"page": "rbac", "users": rows, "roles": auth.ROLES}
    return render(request, "dashboard/users.html", context)


@auth.admin_required
@require_POST
def create_user_view(request):
    form_data = request.POST
    name = form_data.get("name", "").strip()
    title = form_data.get("title", "").strip()
    email = form_data.get("email", "").strip().lower()
    role = form_data.get("role", "")
    password = form_data.get("password", "")

    errors = account_errors(name, email, password)
    if role not in auth.ROLES:
        errors.append("Choose a role.")
    if errors:
        messages.error(request, errors[0])
        return redirect("accounts:users")

    try:
        db.users.insert_one({
            "name": name, "title": title[:100], **email_fields(email), "role": role, "active": True,
            "password_hash": auth.hash_password(password), "created_at": now(),
        })
        messages.success(request, "User %s created." % name)
    except DuplicateKeyError:
        messages.error(request, "A user with this email already exists.")
    return redirect("accounts:users")


def change_user(admin, user_id, action):
    """Returns an error, or None."""
    target = auth.find_user(user_id)
    if not target:
        return "User not found."
    if target["_id"] == admin["_id"]:
        return "You can't change your own role or status."
    if action in auth.ROLES:
        changes = {"role": action}
    elif action in ("enable", "disable"):
        # Enabling approves it
        changes = {"active": action == "enable", "pending": False}
    else:
        return "Unknown change."
    db.users.update_one({"_id": target["_id"]}, {"$set": changes})
    return None


@auth.admin_required
@require_POST
def update_user_view(request, user_id):
    error = change_user(auth.current_user(request), user_id, request.POST.get("action"))
    if error:
        messages.error(request, error)
    else:
        messages.success(request, "User updated.")
    return redirect("accounts:users")
