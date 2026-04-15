import os
import sys
import django
import secrets

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blog.settings_production')
django.setup()

from django.contrib.auth.models import User


def create_superuser():
    username = os.getenv('ADMIN_USERNAME', 'admin')
    email = os.getenv('ADMIN_EMAIL', 'admin@arenago.uz')
    password = os.getenv('ADMIN_PASSWORD')

    if User.objects.filter(username=username).exists():
        print(f"✅ Superuser '{username}' already exists")
        return

    if not password:
        password = secrets.token_urlsafe(32)
        print("⚠️  No ADMIN_PASSWORD provided. Generated secure password:")
        print(f"   Password: {password}")

    try:
        user = User.objects.create_superuser(
            username=username,
            email=email,
            password=password
        )
        print(f"✅ Superuser created successfully!")
        print(f"   Username: {username}")
        print(f"   Email: {email}")
        print(f"\n📝 SECURE PASSWORD STORAGE INSTRUCTIONS:")
        print(f"   1. Store this password in your password manager (1Password, LastPass, etc.)")
        print(f"   2. Do NOT commit to git or share")
        print(f"   3. To login: navigate to /admin/")
        print(f"   4. To reset password later: python manage.py changepassword {username}")
        
        return user
    except Exception as e:
        print(f"❌ Error creating superuser: {e}")
        sys.exit(1)


if __name__ == '__main__':
    create_superuser()
