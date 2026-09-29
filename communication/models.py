from django.contrib.auth.models import User
from django.db import models


class Announcement(models.Model):
    class Audience(models.TextChoices):
        ALL = 'ALL', 'All'
        TEACHERS = 'TEACHERS', 'Teachers'
        PARENTS = 'PARENTS', 'Parents'

    title = models.CharField(max_length=150)
    message = models.TextField()
    audience = models.CharField(
        max_length=10, choices=Audience.choices, default=Audience.ALL,
    )
    created_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='announcements',
    )
    published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-published_at', '-created_at']

    def __str__(self):
        return self.title