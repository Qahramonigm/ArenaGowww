Migration steps for enforcing unique phone & OTP fields

1. Inspect existing `UserProfile` records and ensure `phone` is populated or migrate NULLs to unique placeholders:

   - List users without phone:
     ```bash
     python manage.py shell
     from core.models import UserProfile
     print(UserProfile.objects.filter(phone__isnull=True).count())
     ```

   - If non-zero, decide on remediation: contact users, or set a placeholder like `unknown_<id>` (NOT recommended for production without plan).

2. Create migrations:

   ```bash
   python manage.py makemigrations core
   python manage.py migrate
   ```

   Note: `makemigrations` will create a migration making `phone` non-nullable and adding indexes on `OTPCode`.

3. Run tests and smoke checks locally. Ensure the API endpoints for OTP request and verification work.

4. If you have a production DB with NULL phones, perform a careful migration strategy:
   - Add a nullable `phone_new` column
   - Backfill from business records or via a script
   - Run data cleanup and validation
   - Once complete, create a migration to make the column non-nullable and drop the old column

5. Additional: Ensure you run `python manage.py migrate --plan` to preview migrations before applying on production.

If you want, I can generate the exact Django migration files, but they should be reviewed against your current DB state to avoid accidental data loss.