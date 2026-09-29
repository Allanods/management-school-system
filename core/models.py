from django.contrib.auth.models import User
from django.db import models


class SchoolProfile(models.Model):
    name = models.CharField(max_length=150)
    motto = models.CharField(max_length=200, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    def __str__(self):
        return self.name


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class AcademicYear(models.Model):
    name = models.CharField(max_length=20, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ['-start_date']
        constraints = [
            models.UniqueConstraint(
                fields=['is_current'],
                condition=models.Q(is_current=True),
                name='only_one_current_academic_year',
            ),
        ]

    def __str__(self):
        return self.name


class Term(models.Model):
    name = models.CharField(max_length=30)
    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name='terms')
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ['year__name', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['year', 'name'],
                name='unique_term_per_year',
            ),
            models.UniqueConstraint(
                fields=['is_current'],
                condition=models.Q(is_current=True),
                name='only_one_current_term',
            ),
        ]

    def __str__(self):
        return f'{self.name} {self.year.name}'


class SchoolClass(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Stream(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Teacher(models.Model):
    class Gender(models.TextChoices):
        MALE = 'M', 'Male'
        FEMALE = 'F', 'Female'

    user = models.OneToOneField(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='teacher',
    )
    employee_no = models.CharField(max_length=20, unique=True)
    department = models.ForeignKey(
        Department, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='teachers',
    )
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=1, choices=Gender.choices)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    date_joined = models.DateField()
    is_active = models.BooleanField(default=True)
    classes = models.ManyToManyField(
        SchoolClass, blank=True, related_name='assigned_teachers',
    )

    class Meta:
        ordering = ['first_name', 'last_name']

    @property
    def full_name(self):
        middle = f' {self.middle_name}' if self.middle_name else ''
        return f'{self.first_name}{middle} {self.last_name}'

    def __str__(self):
        return self.full_name


class ClassStream(models.Model):
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.PROTECT, related_name='class_streams',
    )
    stream = models.ForeignKey(
        Stream, on_delete=models.PROTECT, related_name='class_streams',
    )
    class_teacher = models.ForeignKey(
        Teacher, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='headed_streams',
    )
    subjects = models.ManyToManyField(Subject, blank=True, related_name='class_streams')

    class Meta:
        ordering = ['school_class__name', 'stream__name']
        constraints = [
            models.UniqueConstraint(
                fields=['school_class', 'stream'],
                name='unique_class_stream',
            ),
        ]

    @property
    def students_count(self):
        return self.students.count()

    def __str__(self):
        return f'{self.school_class.name} {self.stream.name}'


class TeacherAssignment(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='assignments')
    class_stream = models.ForeignKey(ClassStream, on_delete=models.CASCADE, related_name='assignments')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='assignments')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['teacher', 'class_stream', 'subject'],
                name='unique_teacher_assignment',
            ),
        ]

    def __str__(self):
        return f'{self.teacher.full_name} - {self.subject.name} - {self.class_stream}'