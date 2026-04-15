import os
import sys
import django

sys.path.insert(0, r'c:\Users\User\Desktop\app\ArenaGo\blog')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blog.settings')
django.setup()

from django.contrib.auth.models import User, Group

group, _ = Group.objects.get_or_create(name='support')
user, created = User.objects.get_or_create(
    username='testadmin',
    defaults={'is_active': True, 'is_staff': True}
)
if created:
    user.set_password('testpass123')
    user.save()

user.groups.add(group)
user.save()
print("Support agent created: testadmin / testpass123")
