from django.db.models import Q

from .models import ClassStream


def teacher_authorized_class_streams(teacher):
    """All ClassStreams a teacher may access: stream-specific assignments,
    class-teachorship, and whole-class coverage via Teacher.classes."""
    if teacher is None:
        return ClassStream.objects.none()
    return ClassStream.objects.filter(
        Q(assignments__teacher=teacher)
        | Q(class_teacher=teacher)
        | Q(school_class__in=teacher.classes.all())
    ).distinct()


def teacher_mark_streams(teacher):
    """"ClassStreams a teacher may record marks for. Marks permission comes
    strictly from TeacherAssignment — class teachorship grants no marks rights."""
    if teacher is None:
        return ClassStream.objects.none()
    return ClassStream.objects.filter(assignments__teacher=teacher).distinct()


def teacher_authorized_attendance_streams(teacher):
    """ClassStreams a teacher may record attendance for. Attendance-writing
    permission comes strictly from class teachorship — subject assignments
    grant no attendance rights."""
    if teacher is None:
        return ClassStream.objects.none()
    return ClassStream.objects.filter(class_teacher=teacher)