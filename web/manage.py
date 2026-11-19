"""Django command line for EarthScape."""
import os
import sys


def main():
    # Project settings
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "earthscape.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
