import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def seed_data():
    import django
    from django.core.management import call_command

    django.setup()
    call_command("seed_data")


if __name__ == "__main__":
    seed_data()
