
from django.urls import path

from . import views

urlpatterns = [
    path("hostels/", views.hostel_list, name="hostel-list"),
    path("hostels/<int:pk>/edit/", views.hostel_update, name="hostel-update"),
    path("rooms/add/", views.room_create, name="room-create"),
    path("rooms/<int:pk>/edit/", views.room_update, name="room-update"),
    path("beds/", views.bed_list, name="bed-list"),
]
