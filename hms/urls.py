from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("students.urls")),
    path("", include("hostels.urls")),
    path("", include("allocations.urls")),
    path("", include("payments.urls")),
    path("", include("reports.urls")),
    path("", include("audit.urls")),
    path("", include("accounts.urls")),
    path(
        "",
        RedirectView.as_view(
            pattern_name="dashboard",
            permanent=False,
        ),
        name="home",
    ),
]
