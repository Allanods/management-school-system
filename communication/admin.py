from django.contrib import admin

from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'audience', 'published', 'published_at', 'created_at')
    list_filter = ('audience', 'published')
    search_fields = ('title', 'message')