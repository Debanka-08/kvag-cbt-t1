from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models
from django.db.models import Q

from .utils import normalize_class, normalize_name, normalize_student_id


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", "super_admin")
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        TEACHER = "teacher", "Teacher"
        STUDENT = "student", "Student"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT, db_index=True)
    full_name = models.CharField(max_length=150, blank=True)
    # Unique at database level. NULL for staff, so many NULLs are allowed.
    student_id = models.CharField(max_length=32, unique=True, null=True, blank=True)
    student_class = models.CharField("class", max_length=10, blank=True)
    section = models.CharField(max_length=10, blank=True)
    is_approved = models.BooleanField(
        default=True,
        help_text="Students whose roster entry requires approval stay unapproved until an admin approves them.",
    )

    objects = UserManager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~Q(role="student") | Q(student_id__isnull=False),
                name="student_requires_student_id",
            ),
        ]
        indexes = [models.Index(fields=["role", "student_class", "section"])]

    def save(self, *args, **kwargs):
        self.student_id = normalize_student_id(self.student_id) or None
        self.full_name = normalize_name(self.full_name)
        self.student_class = normalize_class(self.student_class)
        self.section = normalize_class(self.section)
        if self.is_superuser:
            self.role = self.Role.SUPER_ADMIN
        if self.role == self.Role.STUDENT and self.student_id:
            self.username = self.student_id
        super().save(*args, **kwargs)

    # Role helpers -----------------------------------------------------
    @property
    def is_super_admin(self):
        return self.role == self.Role.SUPER_ADMIN or self.is_superuser

    @property
    def is_teacher(self):
        return self.role == self.Role.TEACHER

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def display_name(self):
        return self.full_name or self.get_full_name() or self.username

    def __str__(self):
        if self.is_student and self.student_id:
            return f"{self.display_name} ({self.student_id})"
        return self.display_name


class StudentRoster(models.Model):
    """The school's authorised student list. Registration is only allowed for people on it."""

    student_id = models.CharField(max_length=32, unique=True)
    full_name = models.CharField(max_length=150)
    student_class = models.CharField("class", max_length=10)
    section = models.CharField(max_length=10)
    requires_approval = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    claimed_by = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, editable=False,
        on_delete=models.SET_NULL, related_name="roster_entry",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student_class", "section", "full_name"]
        indexes = [models.Index(fields=["student_class", "section"])]

    def save(self, *args, **kwargs):
        self.student_id = normalize_student_id(self.student_id)
        self.full_name = normalize_name(self.full_name)
        self.student_class = normalize_class(self.student_class)
        self.section = normalize_class(self.section)
        super().save(*args, **kwargs)

    @property
    def is_registered(self):
        return self.claimed_by_id is not None

    def __str__(self):
        return f"{self.student_id} - {self.full_name} ({self.student_class}-{self.section})"
