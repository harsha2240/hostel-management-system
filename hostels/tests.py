
from datetime import date
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from allocations.models import Allocation
from audit.models import AuditEvent
from students.models import Student

from .models import Bed, Hostel, Room


class HostelManagementViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="hostel_admin", password="TestPassword123!", role=User.Role.ADMIN
        )
        self.warden = User.objects.create_user(
            username="hostel_warden", password="TestPassword123!", role=User.Role.WARDEN
        )
        self.client = Client()
        self.client.force_login(self.admin)
        self.hostel = Hostel.objects.create(
            name="Filtered Boys Hostel", hostel_type=Hostel.HostelType.BOYS
        )
        self.other_hostel = Hostel.objects.create(
            name="Filtered Girls Hostel", hostel_type=Hostel.HostelType.GIRLS
        )
        self.room = Room.objects.create(
            hostel=self.hostel,
            room_number="701",
            floor=7,
            room_type=Room.RoomType.DOUBLE,
            capacity=3,
        )
        self.other_room = Room.objects.create(
            hostel=self.other_hostel,
            room_number="801",
            floor=8,
            room_type=Room.RoomType.SINGLE,
            capacity=1,
        )

    def test_admin_can_create_hostel_and_room(self):
        hostel_response = self.client.post(
            reverse("hostel-list"),
            {"name": "Admin Created Hostel", "hostel_type": Hostel.HostelType.BOYS},
        )
        self.assertRedirects(hostel_response, reverse("hostel-list"))
        created_hostel = Hostel.objects.get(name="Admin Created Hostel")
        hostel_event = AuditEvent.objects.get(
            action=AuditEvent.Action.CREATE,
            record_type="hostels.hostel",
            record_id=str(created_hostel.pk),
        )
        self.assertEqual(hostel_event.user, self.admin)

        room_response = self.client.post(
            reverse("room-create"),
            {
                "hostel": created_hostel.pk,
                "room_number": "901",
                "floor": 9,
                "room_type": Room.RoomType.SINGLE,
                "capacity": 1,
            },
        )
        self.assertRedirects(room_response, reverse("bed-list"))
        room = Room.objects.get(hostel=created_hostel, room_number="901")
        self.assertTrue(room)
        room_event = AuditEvent.objects.get(
            action=AuditEvent.Action.CREATE,
            record_type="hostels.room",
            record_id=str(room.pk),
        )
        self.assertEqual(room_event.user, self.admin)

    def test_room_creation_rolls_back_if_audit_recording_fails(self):
        with patch("hostels.views.record_event", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse("room-create"),
                    {
                        "hostel": self.hostel.pk,
                        "room_number": "799",
                        "floor": 7,
                        "room_type": Room.RoomType.SINGLE,
                        "capacity": 1,
                    },
                )

        self.assertFalse(Room.objects.filter(hostel=self.hostel, room_number="799").exists())
        self.assertFalse(Bed.objects.filter(room__hostel=self.hostel, label="799-A").exists())

    def test_hostel_deactivation_is_audited(self):
        response = self.client.post(
            reverse("hostel-update", args=[self.hostel.pk]),
            {
                "name": self.hostel.name,
                "hostel_type": self.hostel.hostel_type,
            },
        )
        self.assertRedirects(response, reverse("hostel-list"))
        self.hostel.refresh_from_db()
        self.assertFalse(self.hostel.is_active)
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.DEACTIVATE,
            record_type="hostels.hostel",
            record_id=str(self.hostel.pk),
        )
        self.assertEqual(event.user, self.admin)

    def test_only_admin_can_create_or_edit_hostels_and_rooms(self):
        self.client.force_login(self.warden)
        forbidden_requests = (
            ("get", reverse("hostel-list")),
            ("post", reverse("hostel-list"), {"name": "Forbidden", "hostel_type": "Boys"}),
            ("get", reverse("hostel-update", args=[self.hostel.pk])),
            ("get", reverse("room-create")),
            ("post", reverse("room-create"), {
                "hostel": self.hostel.pk,
                "room_number": "702",
                "floor": 7,
                "room_type": "Single",
                "capacity": 1,
            }),
            ("get", reverse("room-update", args=[self.room.pk])),
        )

        for request in forbidden_requests:
            method, url, *data = request
            response = getattr(self.client, method)(url, *(data or [{}]))
            self.assertEqual(response.status_code, 403, f"{method.upper()} {url}")

        self.assertFalse(Hostel.objects.filter(name="Forbidden").exists())
        self.assertFalse(Room.objects.filter(room_number="702").exists())

    def test_available_bed_filter_combines_hostel_floor_and_room_type(self):
        available = self.room.beds.get(label="701-A")
        occupied = self.room.beds.get(label="701-B")
        maintenance = self.room.beds.get(label="701-C")
        occupied.status = Bed.BedStatus.OCCUPIED
        occupied.save(update_fields=["status"])
        maintenance.status = Bed.BedStatus.MAINTENANCE
        maintenance.save(update_fields=["status"])

        response = self.client.get(
            reverse("bed-list"),
            {
                "hostel": self.hostel.pk,
                "floor": 7,
                "room_type": Room.RoomType.DOUBLE,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["beds"]), [available])
        self.assertNotIn(self.other_room.beds.get(), response.context["beds"])

    def test_available_bed_results_exclude_occupied_and_maintenance_beds(self):
        occupied = self.room.beds.get(label="701-A")
        maintenance = self.room.beds.get(label="701-B")
        occupied.status = Bed.BedStatus.OCCUPIED
        occupied.save(update_fields=["status"])
        maintenance.status = Bed.BedStatus.MAINTENANCE
        maintenance.save(update_fields=["status"])

        response = self.client.get(reverse("bed-list"))

        self.assertEqual(response.status_code, 200)
        bed_ids = set(response.context["beds"].values_list("pk", flat=True))
        self.assertNotIn(occupied.pk, bed_ids)
        self.assertNotIn(maintenance.pk, bed_ids)


class HostelModelBehaviorTests(TestCase):
    def setUp(self):
        self.hostel = Hostel.objects.create(
            name="Test Hostel",
            hostel_type=Hostel.HostelType.BOYS,
        )

    def test_create_hostel(self):
        self.assertEqual(self.hostel.name, "Test Hostel")
        self.assertTrue(self.hostel.is_active)

    def test_duplicate_hostel_name_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Hostel.objects.create(
                    name="Test Hostel",
                    hostel_type=Hostel.HostelType.GIRLS,
                )

    def test_room_creation_automatically_creates_beds(self):
        room = Room.objects.create(
            hostel=self.hostel,
            room_number="101",
            floor=1,
            room_type=Room.RoomType.TRIPLE,
            capacity=3,
        )

        self.assertEqual(room.beds.count(), 3)
        self.assertSetEqual(
            set(room.beds.values_list("label", flat=True)),
            {"101-A", "101-B", "101-C"},
        )
        self.assertEqual(
            room.beds.filter(status=Bed.BedStatus.AVAILABLE).count(),
            3,
        )

    def test_room_capacity_cannot_exceed_four(self):
        room = Room(
            hostel=self.hostel,
            room_number="102",
            floor=1,
            room_type=Room.RoomType.TRIPLE,
            capacity=5,
        )

        with self.assertRaises(ValidationError):
            room.full_clean()

    def test_room_numbers_must_be_unique_within_hostel(self):
        Room.objects.create(
            hostel=self.hostel,
            room_number="103",
            floor=1,
            room_type=Room.RoomType.SINGLE,
            capacity=1,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Room.objects.create(
                    hostel=self.hostel,
                    room_number="103",
                    floor=2,
                    room_type=Room.RoomType.DOUBLE,
                    capacity=2,
                )

    def test_bed_status_can_be_changed(self):
        room = Room.objects.create(
            hostel=self.hostel,
            room_number="104",
            floor=1,
            room_type=Room.RoomType.SINGLE,
            capacity=1,
        )

        bed = room.beds.get()
        bed.status = Bed.BedStatus.MAINTENANCE
        bed.save()

        bed.refresh_from_db()
        self.assertEqual(bed.status, Bed.BedStatus.MAINTENANCE)

    def test_renaming_room_updates_existing_bed_labels(self):
        room = Room.objects.create(
            hostel=self.hostel,
            room_number="201",
            floor=2,
            room_type=Room.RoomType.TRIPLE,
            capacity=3,
        )

        room.room_number = "202"
        room.save()

        self.assertEqual(room.beds.count(), 3)
        self.assertSetEqual(
            set(room.beds.values_list("label", flat=True)),
            {"202-A", "202-B", "202-C"},
        )

    def test_reducing_capacity_removes_unallocated_beds(self):
        room = Room.objects.create(
            hostel=self.hostel,
            room_number="301",
            floor=3,
            room_type=Room.RoomType.TRIPLE,
            capacity=3,
        )

        room.capacity = 2
        room.save()

        self.assertEqual(room.beds.count(), 2)
        self.assertSetEqual(
            set(room.beds.values_list("label", flat=True)),
            {"301-A", "301-B"},
        )

    def test_capacity_cannot_be_reduced_below_active_allocations(self):
        room = Room.objects.create(
            hostel=self.hostel,
            room_number="401",
            floor=4,
            room_type=Room.RoomType.TRIPLE,
            capacity=3,
        )

        student1 = Student.objects.create(
            student_id="PES9876543210",
            name="Test Student One",
            date_of_birth=date(2005, 1, 15),
            gender=Student.Gender.MALE,
            course="Engineering",
            year=2,
            mobile="9876543210",
            email="student1@example.com",
            guardian_name="Guardian One",
            guardian_mobile="9876543211",
        )

        student2 = Student.objects.create(
            student_id="PES9876543211",
            name="Test Student Two",
            date_of_birth=date(2005, 2, 15),
            gender=Student.Gender.MALE,
            course="Engineering",
            year=2,
            mobile="9876543212",
            email="student2@example.com",
            guardian_name="Guardian Two",
            guardian_mobile="9876543213",
        )

        Allocation.objects.create(
            student=student1,
            bed=room.beds.get(label="401-A"),
            allocated_on=date.today(),
        )

        Allocation.objects.create(
            student=student2,
            bed=room.beds.get(label="401-B"),
            allocated_on=date.today(),
        )

        room.capacity = 1

        with self.assertRaises(ValidationError):
            room.full_clean()

        room.refresh_from_db()
        self.assertEqual(room.capacity, 3)
        self.assertEqual(room.beds.count(), 3)

    
    def test_queryset_update_rejects_capacity_and_room_number(self):
        room = Room.objects.create(
            hostel=self.hostel,
            room_number="501",
            floor=5,
            room_type=Room.RoomType.TRIPLE,
            capacity=3,
        )

        room.beds.get(label="501-B").status = Bed.BedStatus.MAINTENANCE
        room.beds.get(label="501-B").save()

        before = list(
            room.beds.order_by("label").values_list("label", "status")
        )

        with self.assertRaises(ValueError):
            Room.objects.filter(pk=room.pk).update(capacity=2)

        with self.assertRaises(ValueError):
            Room.objects.filter(pk=room.pk).update(room_number="502")

        room.refresh_from_db()
        after = list(
            room.beds.order_by("label").values_list("label", "status")
        )

        self.assertEqual(room.capacity, 3)
        self.assertEqual(room.room_number, "501")
        self.assertEqual(len(after), 3)
        self.assertEqual(after, before)

    def test_bulk_update_rejects_capacity_and_room_number(self):
        room = Room.objects.create(
            hostel=self.hostel,
            room_number="601",
            floor=6,
            room_type=Room.RoomType.TRIPLE,
            capacity=3,
        )

        room.beds.get(label="601-B").status = Bed.BedStatus.MAINTENANCE
        room.beds.get(label="601-B").save()

        before = list(
            room.beds.order_by("label").values_list("label", "status")
        )

        room.capacity = 2
        with self.assertRaises(ValueError):
            Room.objects.bulk_update([room], ["capacity"])

        room.refresh_from_db()
        room.room_number = "602"
        with self.assertRaises(ValueError):
            Room.objects.bulk_update([room], ["room_number"])

        room.refresh_from_db()
        after = list(
            room.beds.order_by("label").values_list("label", "status")
        )

        self.assertEqual(room.capacity, 3)
        self.assertEqual(room.room_number, "601")
        self.assertEqual(len(after), 3)
        self.assertEqual(after, before)

class HostelManagementPermissionTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.admin = User.objects.create_user(
            username="hostel_admin",
            password="TestPassword123!",
            role=User.Role.ADMIN,
        )
        self.warden = User.objects.create_user(
            username="hostel_warden",
            password="TestPassword123!",
            role=User.Role.WARDEN,
        )
        self.student_user = User.objects.create_user(
            username="hostel_student",
            password="TestPassword123!",
            role=User.Role.STUDENT,
        )

        self.hostel = Hostel.objects.create(
            name="Test Boys Hostel",
            hostel_type=Hostel.HostelType.BOYS,
        )

    def test_admin_can_access_hostel_management(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("hostel-list"))

        self.assertEqual(response.status_code, 200)

    def test_warden_cannot_manage_hostels(self):
        self.client.force_login(self.warden)

        response = self.client.get(reverse("hostel-list"))

        self.assertEqual(response.status_code, 403)

    def test_student_cannot_manage_hostels(self):
        self.client.force_login(self.student_user)

        response = self.client.get(reverse("hostel-list"))

        self.assertEqual(response.status_code, 403)

    def test_warden_cannot_add_room(self):
        self.client.force_login(self.warden)

        response = self.client.get(reverse("room-create"))

        self.assertEqual(response.status_code, 403)


    def test_warden_cannot_create_hostel_with_post(self):
        self.client.force_login(self.warden)

        response = self.client.post(
            reverse("hostel-list"),
            {
                "name": "Unauthorized Hostel",
                "hostel_type": Hostel.HostelType.BOYS,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Hostel.objects.filter(name="Unauthorized Hostel").exists()
        )

    def test_warden_cannot_create_room_with_post(self):
        self.client.force_login(self.warden)

        response = self.client.post(
            reverse("room-create"),
            {
                "hostel": self.hostel.pk,
                "room_number": "999",
                "floor": 1,
                "room_type": Room.RoomType.SINGLE,
                "capacity": 1,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Room.objects.filter(
                hostel=self.hostel,
                room_number="999",
            ).exists()
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("hostel-list"))

        self.assertEqual(response.status_code, 302)


class BedFilteringViewTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.user = User.objects.create_user(
            username="bed_filter_user",
            password="TestPassword123!",
            role=User.Role.STUDENT,
        )
        self.client.force_login(self.user)

        self.hostel1 = Hostel.objects.create(
            name="North Hostel",
            hostel_type=Hostel.HostelType.BOYS,
        )
        self.hostel2 = Hostel.objects.create(
            name="South Hostel",
            hostel_type=Hostel.HostelType.BOYS,
        )

        self.room1 = Room.objects.create(
            hostel=self.hostel1,
            room_number="101",
            floor=1,
            room_type=Room.RoomType.DOUBLE,
            capacity=2,
        )
        self.room2 = Room.objects.create(
            hostel=self.hostel1,
            room_number="201",
            floor=2,
            room_type=Room.RoomType.SINGLE,
            capacity=1,
        )
        self.room3 = Room.objects.create(
            hostel=self.hostel2,
            room_number="101",
            floor=1,
            room_type=Room.RoomType.DOUBLE,
            capacity=2,
        )

        self.available_bed = self.room1.beds.get(label="101-A")
        self.occupied_bed = self.room1.beds.get(label="101-B")
        self.maintenance_bed = self.room3.beds.get(label="101-A")

        self.occupied_bed.status = Bed.BedStatus.OCCUPIED
        self.occupied_bed.save()

        self.maintenance_bed.status = Bed.BedStatus.MAINTENANCE
        self.maintenance_bed.save()

    def test_available_filter_excludes_occupied_and_maintenance_beds(self):
        response = self.client.get(reverse("bed-list"))

        beds = list(response.context["beds"])

        self.assertIn(self.available_bed, beds)
        self.assertNotIn(self.occupied_bed, beds)
        self.assertNotIn(self.maintenance_bed, beds)

    def test_filter_by_hostel(self):
        response = self.client.get(
            reverse("bed-list"),
            {"hostel": self.hostel1.pk, "status": ""},
        )

        beds = list(response.context["beds"])

        self.assertTrue(beds)
        self.assertTrue(
            all(bed.room.hostel_id == self.hostel1.pk for bed in beds)
        )

    def test_filter_by_floor(self):
        response = self.client.get(
            reverse("bed-list"),
            {"floor": "2", "status": ""},
        )

        beds = list(response.context["beds"])

        self.assertEqual(len(beds), 1)
        self.assertEqual(beds[0].room.floor, 2)

    def test_filter_by_room_type(self):
        response = self.client.get(
            reverse("bed-list"),
            {"room_type": Room.RoomType.SINGLE, "status": ""},
        )

        beds = list(response.context["beds"])

        self.assertEqual(len(beds), 1)
        self.assertEqual(beds[0].room.room_type, Room.RoomType.SINGLE)

    def test_combined_filters_return_only_matching_available_beds(self):
        response = self.client.get(
            reverse("bed-list"),
            {
                "hostel": self.hostel1.pk,
                "floor": "1",
                "room_type": Room.RoomType.DOUBLE,
            },
        )

        beds = list(response.context["beds"])

        self.assertEqual(beds, [self.available_bed])

    def test_bed_list_is_paginated_and_keeps_filters_on_next_page(self):
        for index in range(13):
            Room.objects.create(
                hostel=self.hostel1,
                room_number=f"P{index:02d}",
                floor=3,
                room_type=Room.RoomType.DOUBLE,
                capacity=4,
            )

        first_page = self.client.get(reverse("bed-list"), {"status": ""})
        second_page = self.client.get(
            reverse("bed-list"), {"status": "", "page": "2"}
        )

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(len(first_page.context["beds"]), 50)
        self.assertEqual(first_page.context["page_obj"].paginator.count, 57)
        self.assertEqual(len(second_page.context["beds"]), 7)
        self.assertContains(second_page, "Page 2 of 2")