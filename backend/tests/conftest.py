"""Settings for every test, so the suite never needs the real backend/.env."""
import os

from cryptography.fernet import Fernet

os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
