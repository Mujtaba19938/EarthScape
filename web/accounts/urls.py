"""Account URLs."""
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("signup/", views.signup_view, name="signup"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/settings/", views.settings_view, name="settings"),
    path("dashboard/users/", views.users_view, name="users"),
    path("dashboard/users/new/", views.create_user_view, name="create_user"),
    path("dashboard/users/<str:user_id>/", views.update_user_view, name="update_user"),
]
