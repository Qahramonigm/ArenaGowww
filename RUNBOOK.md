ArenaGo - Runbook (local + production)

Prereqs (local):
- Python 3.10+
- Node 16+
- Create and activate a virtualenv in project root

Backend (local):
1. Activate venv
   ```powershell
   & .venv\Scripts\Activate.ps1
   ```
2. Install Python dependencies (ensure requirements.txt includes django, djangorestframework, djangorestframework-simplejwt, django-axes, django-cors-headers, jazzmin)
   ```powershell
   pip install -r requirements.txt
   ```
3. Make migrations and migrate
   ```powershell
   python manage.py makemigrations
   python manage.py migrate
   ```
4. Create superuser
   ```powershell
   python manage.py createsuperuser
   ```
5. Run server
   ```powershell
   python manage.py runserver
   ```

Frontend (local):
1. Set backend URL in `.env` at project root of frontend:
   ```text
   REACT_APP_BACKEND_URL=http://localhost:8000
   ```
2. Install and run
   ```bash
   cd frontend
   npm install
   npm start
   ```

Production notes:
- Ensure `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True` and run behind HTTPS.
- Install and configure `django-axes` and `django-jazzmin` on production. Configure SMTP/SMS provider in environment for OTP delivery.
- Run `python manage.py migrate` and review `MIGRATION_STEPS.md` if migrating existing DB with NULL phones.
- Use secure storage for secrets and rotate as needed.

Security checklist (quick):
- Ensure `REACT_APP_BACKEND_URL` points to the correct backend and CORS is locked down.
- Ensure refresh tokens issued as HttpOnly `refresh_token` cookie.
- Ensure `SIMPLE_JWT` rotation and blacklist are enabled.
- Monitor `SecurityIncident`/axes logs for abusive behavior.
