#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blog.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.contrib.auth.models import User

# Fix testadmin permissions
user = User.objects.get(username='testadmin')
user.is_staff = True
user.is_superuser = True
user.save()

print(f"✅ Updated {user.username}:")
print(f"   is_staff: {user.is_staff}")
print(f"   is_superuser: {user.is_superuser}")
print(f"\n✅ testadmin can now access Django admin!")
