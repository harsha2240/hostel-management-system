from django.urls import path

from . import views

urlpatterns = [path("audit/", views.event_list, name="audit-log")]
