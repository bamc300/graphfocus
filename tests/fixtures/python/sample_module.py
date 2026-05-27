"""Sample Python module for testing the Python extractor."""

import os
from pathlib import Path
from dataclasses import dataclass


class BaseModel:
    """A base model class."""

    def validate(self):
        pass


@dataclass
class User(BaseModel):
    """A user entity."""

    name: str
    email: str
    age: int = 0

    def greet(self):
        return f"Hello, {self.name}!"

    def save(self):
        validate_email(self.email)
        return True


class AdminUser(User):
    """An admin user with extra privileges."""

    role: str = "admin"

    def promote(self):
        self.role = "superadmin"


def validate_email(email: str) -> bool:
    """Validate an email address."""
    return "@" in email


def create_user(name: str, email: str) -> User:
    """Factory function to create a user."""
    if not validate_email(email):
        raise ValueError("Invalid email")
    return User(name=name, email=email)
