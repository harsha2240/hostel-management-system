
from datetime import date
from time import perf_counter
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from allocations.models import Allocation
from audit.models import AuditEvent
from hostels.models import Hostel, Room
from students.forms import StudentForm
from students.models import Student


class StudentModelTests(TestCase):
    def student_data(self, **overrides):
        data = {
            "student_id": "PES1234567890",
            "name": "Test Student",
            "date_of_birth": date(2005, 5, 15),
            "gender": Student.Gender.MALE,
            "course": "Computer Science",
            "year": 2,
            "mobile": "9876543210",
            "email": "student@example.com",
            "guardian_name": "Test Guardian",
            "guardian_mobile": "9876543211",
            "address": "Bengaluru",
        }
        data.update(overrides)
        return data

    def test_create_student(self):
        student = Student.objects.create(**self.student_data())
        self.assertEqual(student.status, Student.Status.ACTIVE)
        self.assertEqual(student.student_id, "PES1234567890")

    def test_duplicate_student_id_is_rejected(self):
        Student.objects.create(**self.student_data())
        with self.assertRaises(IntegrityError), transaction.atomic():
            Student.objects.create(**self.student_data(name="Another Student"))

    def test_duplicate_student_id_form_shows_exact_error_message(self):
        Student.objects.create(**self.student_data())

        form = StudentForm(
            data=self.student_data(name="Another Student")
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["student_id"],
            ["Student ID already registered"],
        )

    def test_student_can_be_deactivated_without_deleting_record(self):
        student = Student.objects.create(**self.student_data())
        student.status = Student.Status.INACTIVE
        student.save()

        student.refresh_from_db()
        self.assertEqual(student.status, Student.Status.INACTIVE)
        self.assertTrue(Student.objects.filter(pk=student.pk).exists())

    def test_student_year_must_be_between_one_and_five(self):
        student = Student(**self.student_data(year=6))
        with self.assertRaises(ValidationError):
            student.full_clean()

    def test_mobile_must_have_ten_digits(self):
        student = Student(**self.student_data(mobile="12345"))
        with self.assertRaises(ValidationError):
            student.full_clean()


class StudentDeactivationViewTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Create an administrator allowed to manage student records.
        self.admin = User.objects.create_user(
            username="student_admin",
            password="TestPassword123!",
            role=User.Role.ADMIN,
        )
        self.client.force_login(self.admin)

        self.student = Student.objects.create(
            student_id="PES1234567890",
            name="Test Student",
            date_of_birth=date(2005, 5, 15),
            gender=Student.Gender.MALE,
            course="Computer Science",
            year=2,
            mobile="9876543210",
            email="student@example.com",
            guardian_name="Test Guardian",
            guardian_mobile="9876543211",
        )

        self.hostel = Hostel.objects.create(
            name="Deactivation Test Hostel",
            hostel_type=Hostel.HostelType.BOYS,
        )
        self.room = Room.objects.create(
            hostel=self.hostel,
            room_number="101",
            floor=1,
            room_type=Room.RoomType.DOUBLE,
            capacity=2,
        )
        self.bed = self.room.beds.get(label="101-A")

    def student_payload(self, **overrides):
        payload = {
            "student_id": "PES1234567890",
            "name": "Test Student",
            "date_of_birth": "2005-05-15",
            "gender": Student.Gender.MALE,
            "course": "Computer Science",
            "year": "2",
            "mobile": "9876543210",
            "email": "student@example.com",
            "guardian_name": "Test Guardian",
            "guardian_mobile": "9876543211",
            "address": "Bengaluru",
            "status": Student.Status.ACTIVE,
        }
        payload.update(overrides)
        return payload

    def test_admin_can_register_student(self):
        response = self.client.post(
            reverse("student-create"),
            self.student_payload(student_id="PES0000000001"),
        )

        self.assertRedirects(response, reverse("student-list"))
        self.assertTrue(
            Student.objects.filter(student_id="PES0000000001").exists()
        )
        student = Student.objects.get(student_id="PES0000000001")
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.CREATE,
            record_type="students.student",
            record_id=str(student.pk),
        )
        self.assertEqual(event.user, self.admin)

    def test_student_creation_rolls_back_if_audit_recording_fails(self):
        with patch("students.views.record_event", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse("student-create"),
                    self.student_payload(student_id="PES0000000003"),
                )

        self.assertFalse(Student.objects.filter(student_id="PES0000000003").exists())

    def test_warden_can_register_student(self):
        warden = User.objects.create_user(
            username="student_warden",
            password="TestPassword123!",
            role=User.Role.WARDEN,
        )
        self.client.force_login(warden)

        response = self.client.post(
            reverse("student-create"), self.student_payload(student_id="PES0000000002")
        )

        self.assertRedirects(response, reverse("student-list"))
        self.assertTrue(
            Student.objects.filter(student_id="PES0000000002").exists()
        )

    def test_student_role_cannot_register_update_or_deactivate(self):
        student_user = User.objects.create_user(
            username="student_role",
            password="TestPassword123!",
            role=User.Role.STUDENT,
        )
        self.client.force_login(student_user)

        for url, method in (
            (reverse("student-list"), "get"),
            (reverse("student-create"), "get"),
            (reverse("student-update", args=[self.student.pk]), "get"),
            (reverse("student-deactivate", args=[self.student.pk]), "post"),
        ):
            response = getattr(self.client, method)(url)
            self.assertEqual(response.status_code, 403)

    def test_admin_can_update_contact_course_and_year_but_not_student_id(self):
        response = self.client.post(
            reverse("student-update", args=[self.student.pk]),
            self.student_payload(
                student_id="PES0000000001",
                mobile="9000000000",
                course="Engineering",
                year="3",
            ),
        )

        self.assertRedirects(response, reverse("student-list"))
        self.student.refresh_from_db()
        self.assertEqual(self.student.student_id, "PES1234567890")
        self.assertEqual(self.student.mobile, "9000000000")
        self.assertEqual(self.student.course, "Engineering")
        self.assertEqual(self.student.year, 3)

    def test_duplicate_registration_shows_required_message(self):
        response = self.client.post(
            reverse("student-create"),
            self.student_payload(student_id=self.student.student_id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Student ID already registered")
        self.assertEqual(Student.objects.count(), 1)

    def test_search_matches_student_id_partial_name_and_hostel(self):
        response = self.client.get(reverse("student-list"), {"q": "PES1234567890"})
        self.assertContains(response, self.student.student_id)

        response = self.client.get(reverse("student-list"), {"q": "Test Stud"})
        self.assertContains(response, self.student.student_id)

        Allocation.objects.create(student=self.student, bed=self.bed)
        response = self.client.get(
            reverse("student-list"), {"q": "Deactivation Test Hostel"}
        )
        self.assertContains(response, self.student.student_id)

    def test_student_search_handles_5000_records_within_two_seconds(self):
        Student.objects.bulk_create(
            [
                Student(
                    student_id=f"PES{index:010d}",
                    name=f"Synthetic Student {index:05d}",
                    date_of_birth=date(2005, 5, 15),
                    gender=Student.Gender.MALE,
                    course="Computer Science",
                    year=2,
                    mobile="9876543210",
                    email=f"student{index}@example.test",
                    guardian_name="Synthetic Guardian",
                    guardian_mobile="9876543211",
                )
                for index in range(5000)
            ]
        )

        started = perf_counter()
        response = self.client.get(
            reverse("student-list"), {"q": "PES0000004999"}
        )
        elapsed = perf_counter() - started

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PES0000004999")
        self.assertLess(elapsed, 2.0, f"5000-record search took {elapsed:.3f}s")

    def test_unallocated_student_can_be_deactivated(self):
        response = self.client.post(
            reverse("student-deactivate", args=[self.student.pk])
        )

        self.assertRedirects(response, reverse("student-list"))
        self.student.refresh_from_db()
        self.assertEqual(self.student.status, Student.Status.INACTIVE)
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.DEACTIVATE,
            record_type="students.student",
            record_id=str(self.student.pk),
        )
        self.assertEqual(event.user, self.admin)

    def test_student_deactivation_rolls_back_if_audit_recording_fails(self):
        with patch("students.views.record_event", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse("student-deactivate", args=[self.student.pk]))

        self.student.refresh_from_db()
        self.assertEqual(self.student.status, Student.Status.ACTIVE)

    def test_student_with_active_allocation_cannot_be_deactivated(self):
        Allocation.objects.create(
            student=self.student,
            bed=self.bed,
        )

        response = self.client.post(
            reverse("student-deactivate", args=[self.student.pk]),
            follow=True,
        )

        self.student.refresh_from_db()
        self.assertEqual(self.student.status, Student.Status.ACTIVE)
        self.assertContains(response, self.bed.label)
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())

    def test_student_deactivation_requires_post(self):
        response = self.client.get(
            reverse("student-deactivate", args=[self.student.pk])
        )

        self.assertEqual(response.status_code, 405)
        self.student.refresh_from_db()
        self.assertEqual(self.student.status, Student.Status.ACTIVE)

class StudentManagementViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="management_admin",
            password="TestPassword123!",
            role=User.Role.ADMIN,
        )
        self.warden = User.objects.create_user(
            username="management_warden",
            password="TestPassword123!",
            role=User.Role.WARDEN,
        )
        self.other_user = User.objects.create_user(
            username="management_student",
            password="TestPassword123!",
            role=User.Role.STUDENT,
        )

    def student_data(self, **overrides):
        data = {
            "student_id": "PES1234567890",
            "name": "Test Student",
            "date_of_birth": "2005-05-15",
            "gender": Student.Gender.MALE,
            "course": "Computer Science",
            "year": 2,
            "mobile": "9876543210",
            "email": "student@example.com",
            "guardian_name": "Test Guardian",
            "guardian_mobile": "9876543211",
            "address": "Bengaluru",
            "status": Student.Status.ACTIVE,
        }
        data.update(overrides)
        return data

    def create_student(self, **overrides):
        data = self.student_data(**overrides)
        data["date_of_birth"] = date.fromisoformat(data["date_of_birth"])
        return Student.objects.create(**data)

    def test_admin_can_register_student(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("student-create"),
            self.student_data(),
        )
        self.assertRedirects(response, reverse("student-list"))
        self.assertTrue(
            Student.objects.filter(student_id="PES1234567890").exists()
        )

    def test_warden_can_register_student(self):
        self.client.force_login(self.warden)
        response = self.client.post(
            reverse("student-create"),
            self.student_data(),
        )
        self.assertRedirects(response, reverse("student-list"))
        self.assertTrue(
            Student.objects.filter(student_id="PES1234567890").exists()
        )

    def test_admin_can_update_student(self):
        student = self.create_student()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("student-update", args=[student.pk]),
            self.student_data(name="Updated Student"),
        )

        self.assertRedirects(response, reverse("student-list"))
        student.refresh_from_db()
        self.assertEqual(student.name, "Updated Student")
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.UPDATE,
            record_type="students.student",
            record_id=str(student.pk),
        )
        self.assertEqual(event.user, self.admin)

    def test_student_search_matches_name_and_id(self):
        self.create_student(
            student_id="PES1111111111",
            name="Aarav Sharma",
            email="aarav@example.com",
        )
        self.create_student(
            student_id="PES2222222222",
            name="Meera Rao",
            email="meera@example.com",
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("student-list"), {"q": "Aarav"}
        )
        self.assertContains(response, "Aarav Sharma")
        self.assertNotContains(response, "Meera Rao")

        response = self.client.get(
            reverse("student-list"), {"q": "PES2222222222"}
        )
        self.assertContains(response, "Meera Rao")
        self.assertNotContains(response, "Aarav Sharma")

    def test_student_list_escapes_script_payload_and_search_treats_sql_as_literal(self):
        self.create_student(
            student_id="PES3333333333",
            name="<script>alert(1)</script>",
            email="literal@example.com",
        )
        self.create_student(
            student_id="PES4444444444",
            name="Private Other Student",
            email="private@example.com",
        )
        self.client.force_login(self.admin)

        page = self.client.get(reverse("student-list"))
        self.assertContains(page, "&lt;script&gt;alert(1)&lt;/script&gt;", html=False)
        self.assertNotContains(page, "<script>alert(1)</script>", html=False)

        injection = self.client.get(reverse("student-list"), {"q": "' OR 1=1--"})
        self.assertEqual(injection.status_code, 200)
        self.assertNotContains(injection, "Private Other Student")
        self.assertNotContains(injection, "PES4444444444")

    def test_student_role_cannot_access_management_views(self):
        student = self.create_student()
        self.client.force_login(self.other_user)

        urls = [
            reverse("student-list"),
            reverse("student-create"),
            reverse("student-update", args=[student.pk]),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        student = self.create_student()

        urls = [
            reverse("student-list"),
            reverse("student-create"),
            reverse("student-update", args=[student.pk]),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
    def test_student_search_performance_with_5000_records(self):
        students = [
            Student(
                student_id=f"PES{i:010d}",
                name=f"Test Student {i}",
                date_of_birth=date(2005, 5, 15),
                gender=Student.Gender.MALE,
                course="Computer Science",
                year=2,
                mobile="9876543210",
                email=f"student{i}@example.com",
                guardian_name="Test Guardian",
                guardian_mobile="9876543211",
                status=Student.Status.ACTIVE,
            )
            for i in range(1, 5001)
        ]

        Student.objects.bulk_create(students, batch_size=500)

        self.client.force_login(self.admin)

        start_time = perf_counter()
        response = self.client.get(
            reverse("student-list"),
            {"q": "Test Student 4999"},
        )
        elapsed_time = perf_counter() - start_time

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            elapsed_time,
            2.0,
            f"Search took {elapsed_time:.2f} seconds; expected under 2 seconds.",
        )
