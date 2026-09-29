from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    class Roles(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrator'
        TEACHER = 'TEACHER', 'Teacher'
        PARENT = 'PARENT', 'Parent'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=10, choices=Roles.choices, default=Roles.PARENT)
    phone = models.CharField(max_length=20, blank=True)

    @property
    def is_admin(self):
        return self.role == self.Roles.ADMIN

    @property
    def is_teacher(self):
        return self.role == self.Roles.TEACHER

    @property
    def is_parent(self):
        return self.role == self.Roles.PARENT

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, **kwargs):
    UserProfile.objects.get_or_create(
        user=instance,
        defaults={
            'role': UserProfile.Roles.ADMIN if instance.is_superuser else UserProfile.Roles.PARENT
        },
    )