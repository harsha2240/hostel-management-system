from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction


class StudentQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if "status" in kwargs:
            raise ValidationError(
                "Save student status individually to check active allocations."
            )
        return super().update(**kwargs)


class Student(models.Model):
    class Gender(models.TextChoices):
        MALE = "Male", "Male"
        FEMALE = "Female", "Female"

    class Status(models.TextChoices):
        ACTIVE = "Active", "Active"
        INACTIVE = "Inactive", "Inactive"

    student_id = models.CharField(
        max_length=13,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^[A-Za-z0-9]{13}$",
                message="Student ID must contain exactly 13 letters or numbers.",
            )
        ],
    )
    name = models.CharField(max_length=60)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=6, choices=Gender.choices)
    course = models.CharField(max_length=30)
    year = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    mobile = models.CharField(
        max_length=10,
        validators=[RegexValidator(r"^\d{10}$", "Enter a 10-digit mobile number.")],
    )
    email = models.EmailField(max_length=80)
    guardian_name = models.CharField(max_length=60)
    guardian_mobile = models.CharField(
        max_length=10,
        validators=[
            RegexValidator(r"^\d{10}$", "Enter a 10-digit guardian mobile number.")
        ],
    )
    address = models.CharField(max_length=200, blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="student_profile",
        help_text="Optional Student login account allowed to view this profile.",
    )
    status = models.CharField(
        max_length=8,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = StudentQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.student_id} - {self.name}"

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.pk:
            Student.objects.select_for_update().get(pk=self.pk)
            if self.status == self.Status.INACTIVE:
                from allocations.models import Allocation

                if Allocation.objects.filter(
                    student_id=self.pk, status=Allocation.AllocationStatus.ACTIVE
                ).exists():
                    raise ValidationError(
                        "Release this student's active allocation before deactivation.",
                        code="HAS_ACTIVE_ALLOCATION",
                    )
        return super().save(*args, **kwargs)
