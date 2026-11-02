from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from accounts.models import User
from allocations.models import Allocation
from audit.models import AuditEvent
from tests.factories import make_room, make_student

from .models import Bed, Hostel, Room


class HostelManagementViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="hostel_admin", password="TestPassword123!", role=User.Role.ADMIN
        )
        self.warden = User.objects.create_user(
            username="hostel_warden", password="TestPassword123!", role=User.Role.WARDEN
        )
        self.client.force_login(self.admin)
        self.hostel = Hostel.objects.create(
            name="Filtered Boys Hostel", hostel_type=Hostel.HostelType.BOYS
        )
        self.other_hostel = Hostel.objects.create(
            name="Filtered Girls Hostel", hostel_type=Hostel.HostelType.GIRLS
        )
        self.room = make_room(
            "701",
            hostel=self.hostel,
            floor=7,
            room_type=Room.RoomType.DOUBLE,
            capacity=3,
        )
        self.other_room = make_room(
            "801",
            hostel=self.other_hostel,
            floor=8,
            room_type=Room.RoomType.SINGLE,
            capacity=1,
        )

    def test_admin_can_create_hostel_and_room(self):
        self.assertEqual(self.client.get(reverse("hostel-list")).status_code, 200)
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
        room_event = AuditEvent.objects.get(
            action=AuditEvent.Action.CREATE,
            record_type="hostels.room",
            record_id=str(room.pk),
        )
        self.assertEqual(room_event.user, self.admin)

    def test_empty_management_submissions_show_required_errors_without_saving(self):
        for route, args, required_field in (
            ("hostel-list", [], "name"),
            ("hostel-update", [self.hostel.pk], "name"),
            ("room-create", [], "room_number"),
            ("room-update", [self.room.pk], "room_number"),
        ):
            with self.subTest(route=route):
                response = self.client.post(reverse(route, args=args), {})
                self.assertEqual(response.status_code, 200)
                self.assertIn(required_field, response.context["form"].errors)

        self.assertEqual(Hostel.objects.count(), 2)
        self.assertEqual(Room.objects.count(), 2)
        self.assertFalse(
            AuditEvent.objects.filter(
                record_type__in=["hostels.hostel", "hostels.room"],
            ).exists()
        )

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("hostel-list"))
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('hostel-list')}",
        )

    def test_room_creation_rolls_back_if_audit_recording_fails(self):
        with patch(
            "hostels.views.record_event", side_effect=RuntimeError("audit failed")
        ):
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

        self.assertFalse(
            Room.objects.filter(hostel=self.hostel, room_number="799").exists()
        )
        self.assertFalse(
            Bed.objects.filter(room__hostel=self.hostel, label="799-A").exists()
        )

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
        student_user = User.objects.create_user(
            username="hostel_student",
            role=User.Role.STUDENT,
        )
        forbidden_requests = (
            ("get", reverse("hostel-list")),
            (
                "post",
                reverse("hostel-list"),
                {"name": "Forbidden", "hostel_type": "Boys"},
            ),
            ("get", reverse("hostel-update", args=[self.hostel.pk])),
            ("get", reverse("room-create")),
            (
                "post",
                reverse("room-create"),
                {
                    "hostel": self.hostel.pk,
                    "room_number": "702",
                    "floor": 7,
                    "room_type": "Single",
                    "capacity": 1,
                },
            ),
            ("get", reverse("room-update", args=[self.room.pk])),
        )

        for user in (self.warden, student_user):
            self.client.force_login(user)
            for method, url, *data in forbidden_requests:
                with self.subTest(role=user.role, method=method, url=url):
                    response = getattr(self.client, method)(url, *(data or [{}]))
                    self.assertEqual(response.status_code, 403)

        self.assertFalse(Hostel.objects.filter(name="Forbidden").exists())
        self.assertFalse(Room.objects.filter(room_number="702").exists())


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

        for number, label in ((1, "401-A"), (2, "401-B")):
            Allocation.objects.create(
                student=make_student(number),
                bed=room.beds.get(label=label),
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

        bed = room.beds.get(label="501-B")
        bed.status = Bed.BedStatus.MAINTENANCE
        bed.save(update_fields=["status"])

        before = list(room.beds.order_by("label").values_list("label", "status"))

        with self.assertRaises(ValueError):
            Room.objects.filter(pk=room.pk).update(capacity=2)

        with self.assertRaises(ValueError):
            Room.objects.filter(pk=room.pk).update(room_number="502")

        room.refresh_from_db()
        after = list(room.beds.order_by("label").values_list("label", "status"))

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

        bed = room.beds.get(label="601-B")
        bed.status = Bed.BedStatus.MAINTENANCE
        bed.save(update_fields=["status"])

        before = list(room.beds.order_by("label").values_list("label", "status"))

        room.capacity = 2
        with self.assertRaises(ValueError):
            Room.objects.bulk_update([room], ["capacity"])

        room.refresh_from_db()
        room.room_number = "602"
        with self.assertRaises(ValueError):
            Room.objects.bulk_update([room], ["room_number"])

        room.refresh_from_db()
        after = list(room.beds.order_by("label").values_list("label", "status"))

        self.assertEqual(room.capacity, 3)
        self.assertEqual(room.room_number, "601")
        self.assertEqual(len(after), 3)
        self.assertEqual(after, before)


class BedFilteringViewTests(TestCase):
    def setUp(self):

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
        self.assertTrue(all(bed.room.hostel_id == self.hostel1.pk for bed in beds))

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

    def test_invalid_numeric_filters_return_400_without_bed_results(self):
        invalid_values = {
            "hostel": ["bad", "1.5", "-1", "0", str(2**63), "9" * 5000],
            "floor": ["bad", "1.5", "-1", "65536", "9" * 5000],
        }

        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value[:30]):
                    response = self.client.get(
                        reverse("bed-list"), {field: value, "status": ""}
                    )

                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(list(response.context["beds"]), [])
                    self.assertEqual(response.context["page_obj"].paginator.count, 0)
                    self.assertIn(field, response.context["filter_form"].errors)
                    self.assertContains(response, 'role="alert"', status_code=400)
                    self.assertNotContains(
                        response,
                        f"<td>{self.available_bed.label}</td>",
                        status_code=400,
                    )

    def test_invalid_floor_is_escaped_and_other_filter_values_are_preserved(self):
        value = '"><script>alert("bad filter")</script>'
        response = self.client.get(
            reverse("bed-list"),
            {
                "hostel": self.hostel1.pk,
                "floor": value,
                "room_type": Room.RoomType.DOUBLE,
                "status": Bed.BedStatus.OCCUPIED,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(response.context["beds"]), [])
        self.assertEqual(response.context["selected_hostel"], str(self.hostel1.pk))
        self.assertEqual(response.context["selected_floor"], value)
        self.assertEqual(response.context["selected_room_type"], Room.RoomType.DOUBLE)
        self.assertEqual(response.context["selected_status"], Bed.BedStatus.OCCUPIED)
        self.assertContains(response, "Floor: Enter a whole number.", status_code=400)
        self.assertContains(response, escape(value), status_code=400)
        self.assertNotContains(response, "<script>", status_code=400)

    def test_zero_and_upper_boundary_floor_filters_match_only_their_beds(self):
        for floor in (0, 65535):
            with self.subTest(floor=floor):
                room = Room.objects.create(
                    hostel=self.hostel1,
                    room_number=f"B{floor}",
                    floor=floor,
                    room_type=Room.RoomType.SINGLE,
                    capacity=1,
                )
                response = self.client.get(
                    reverse("bed-list"),
                    {
                        "hostel": self.hostel1.pk,
                        "floor": str(floor),
                        "room_type": Room.RoomType.SINGLE,
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context["beds"]), list(room.beds.all()))
                self.assertEqual(response.context["selected_floor"], str(floor))

    def test_maximum_hostel_id_is_valid_and_has_no_matches(self):
        response = self.client.get(reverse("bed-list"), {"hostel": str(2**63 - 1)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["beds"]), [])
        self.assertFalse(response.context["filter_form"].errors)

    def test_invalid_filters_do_not_bypass_login(self):
        self.client.logout()

        response = self.client.get(reverse("bed-list"), {"floor": "bad"})

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('bed-list')}%3Ffloor%3Dbad",
            fetch_redirect_response=False,
        )

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
        second_page = self.client.get(reverse("bed-list"), {"status": "", "page": "2"})

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(len(first_page.context["beds"]), 50)
        self.assertEqual(first_page.context["page_obj"].paginator.count, 57)
        self.assertEqual(len(second_page.context["beds"]), 7)
        self.assertContains(second_page, "Page 2 of 2")
