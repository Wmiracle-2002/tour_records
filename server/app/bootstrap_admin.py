"""Create the first administrator via a private interactive terminal."""

from getpass import getpass

from app.bootstrap import initialize_admin
from app.database import SessionLocal


def main() -> None:
    password = getpass("Administrator password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    with SessionLocal() as db:
        try:
            initialize_admin(db, password)
        except ValueError as error:
            raise SystemExit(str(error)) from error
    print("Administrator initialized")


if __name__ == "__main__":
    main()
