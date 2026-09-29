from django.urls import NoReverseMatch, reverse

from .access import get_role

# Navigation for every role. Entries whose URL does not exist yet are
# rendered as disabled placeholders until their module is built.
ROLE_NAV = {
    'ADMIN': [
        ('dashboard', 'Dashboard', 'accounts:dashboard', 'speedometer2'),
        ('students', 'Students', 'students:list', 'people'),
        ('teachers', 'Teachers', 'teachers:list', 'person-badge'),
        ('parents', 'Parents', 'students:parent_list', 'person-heart'),
        ('classes', 'Classes', 'structure:class_list', 'diagram-3'),
        ('streams', 'Streams', 'structure:stream_list', 'shapes'),
        ('class_streams', 'Class Streams', 'structure:classstream_list', 'hdd-stack'),
        ('subjects', 'Subjects', 'structure:subject_list', 'book'),
        ('assignments', 'Assignments', 'structure:assignment_list', 'journal-bookmark'),
        ('academics', 'Academics', 'academics:home', 'mortarboard'),
        ('grade_bands', 'Grade Bands', 'academics:gradeband_list', 'award'),
        ('attendance', 'Attendance', 'attendance:home', 'clipboard-check'),
        ('fees', 'Fees', 'fees:home', 'cash-coin'),
        ('announcements', 'Announcements', 'announcements:list', 'megaphone'),
        ('reports', 'Reports', 'reports:home', 'file-earmark-bar-graph'),
        ('users', 'Users', 'accounts:user_list', 'person-gear'),
        ('settings', 'Settings', 'accounts:settings', 'gear'),
    ],
    'TEACHER': [
        ('dashboard', 'Dashboard', 'accounts:dashboard', 'speedometer2'),
        ('profile', 'My Profile', 'teachers:profile', 'person-badge'),
        ('my_classes', 'My Classes', 'academics:my_classes', 'diagram-3'),
        ('attendance', 'Attendance', 'attendance:take', 'clipboard-check'),
        ('marks', 'Marks', 'academics:marks', 'mortarboard'),
        ('students', 'Students', 'students:my_students', 'people'),
        ('announcements', 'Announcements', 'announcements:list', 'megaphone'),
    ],
    'PARENT': [
        ('dashboard', 'Dashboard', 'accounts:dashboard', 'speedometer2'),
        ('my_children', 'My Children', 'students:my_children', 'people'),
        ('performance', 'Performance', 'academics:performance', 'mortarboard'),
        ('attendance', 'Attendance', 'attendance:my_children', 'clipboard-check'),
        ('fees', 'Fees', 'fees:my_children', 'cash-coin'),
        ('announcements', 'Announcements', 'announcements:list', 'megaphone'),
    ],
}


def role(request):
    current_role = None
    user_profile = None
    if request.user.is_authenticated:
        current_role = get_role(request.user)
        user_profile = getattr(request.user, 'profile', None)

    # Exact match against the resolved URL name so sub-pages (e.g. a parent
    # detail under /students/parents/...) do not highlight multiple entries.
    current_url_name = None
    if request.resolver_match is not None and request.resolver_match.url_name:
        namespace = request.resolver_match.namespace
        current_url_name = (
            f'{namespace}:{request.resolver_match.url_name}'
            if namespace
            else request.resolver_match.url_name
        )

    nav_items = []
    for key, label, url_name, icon in ROLE_NAV.get(current_role, []):
        try:
            href = reverse(url_name)
        except NoReverseMatch:
            href = None
        nav_items.append({
            'key': key,
            'label': label,
            'href': href,
            'icon': icon,
            'url_name': url_name,
            'active': href is not None and url_name == current_url_name,
        })

    # Fall back to prefix matching for detail/create/edit pages; the longest
    # href wins so e.g. /students/parents/5/ highlights Parents, not Students.
    if not any(item['active'] for item in nav_items):
        candidates = [
            item for item in nav_items
            if item['href'] and request.path.startswith(item['href'])
        ]
        if candidates:
            best = max(candidates, key=lambda item: len(item['href']))
            best['active'] = True

    return {
        'user_role': current_role,
        'user_profile': user_profile,
        'nav_items': nav_items,
    }