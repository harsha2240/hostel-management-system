from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.sign_in, name="login"),
    path("logout/", views.sign_out, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),
    path("manage/users/", views.user_management, name="user-management"),
    path("manage/users/<int:user_id>/update/", views.update_user, name="user-update"),
    path(
        "manage/users/<int:user_id>/deactivate/",
        views.deactivate_user,
        name="user-deactivate",
    ),
]
