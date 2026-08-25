from sqlalchemy.orm import Session

from app.models import Activity


def record_activity(db: Session, source: str, event: str, detail: str) -> None:
    db.add(Activity(source=source[:40], event=event[:80], detail=detail[:500]))
    db.commit()

