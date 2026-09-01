from src.db.session import engine
from src.db.base import Base
from src.db import models  # noqa: F401  (ensures models are registered)


def main():
    Base.metadata.create_all(bind=engine)
    print("✅ DB tables ensured (create_all done).")


if __name__ == "__main__":
    main()
