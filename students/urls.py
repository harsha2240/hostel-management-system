
from django.urls import path

from . import views

urlpatterns = [
    path("students/", views.student_list, name="student-list"),
    path("students/register/", views.student_create, name="student-create"),
    path("students/<int:pk>/update/", views.student_update, name="student-update"),
    path("students/<int:pk>/deactivate/", views.student_deactivate, name="student-deactivate"),
    path("my-records/", views.my_records, name="student-self-service"),
]
