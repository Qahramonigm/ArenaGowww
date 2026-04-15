from datetime import timedelta, time
from django.utils import timezone
from .models import FieldSlot

def create_daily_slots(field, date):
    hours = range(8, 24)  # 08:00 → 23:00

    for h in hours:
        FieldSlot.objects.get_or_create(
            field=field,
            date=date,
            start_time=time(hour=h)
        )



def generate_slots_for_field(field, days=30):
    today = timezone.now().date()

    for d in range(days):
        date = today + timedelta(days=d)

        for hour in range(8, 24):  # 08:00 → 23:00
            FieldSlot.objects.get_or_create(
                field=field,
                date=date,
                start_time=time(hour=hour)
            )