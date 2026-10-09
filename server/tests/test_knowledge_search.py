from sqlalchemy.orm import Session
import pytest

from app.agent.knowledge import read_knowledge_excerpt, resolve_city_code, search_knowledge
from app.models import KnowledgeEntry, User
from app.security import hash_password


def test_search_prefers_matching_same_city_and_hides_other_users(db_session: Session) -> None:
    owner = User(username="owner", password_hash=hash_password("password"))
    other = User(username="other", password_hash=hash_password("password"))
    db_session.add_all([owner, other])
    db_session.flush()
    db_session.add_all([
        KnowledgeEntry(user_id=owner.id, category="food_guide", title="南京小吃", body="鸭血粉丝汤", city_code="320100", city_name="南京市", tags=["小吃"]),
        KnowledgeEntry(user_id=owner.id, category="note", title="南京博物馆", body="提前预约", city_code="320100", city_name="南京市", tags=["博物馆"]),
        KnowledgeEntry(user_id=owner.id, category="food_guide", title="苏州小吃", body="桂花糕", city_code="320500", city_name="苏州市", tags=["小吃"]),
        KnowledgeEntry(user_id=other.id, category="food_guide", title="南京秘藏", body="私密内容", city_code="320100", city_name="南京市", tags=["小吃"]),
    ])
    db_session.commit()

    rows = search_knowledge(db_session, owner.id, "320100", keywords=["小吃"])
    assert [row.title for row in rows] == ["南京小吃"]
    assert "私密" not in str(rows)
    assert search_knowledge(db_session, owner.id, "320100", category="attraction_guide") == []
    assert search_knowledge(db_session, owner.id, "999999") == []


def test_search_limits_excerpt_and_detail_is_owner_scoped(db_session: Session) -> None:
    owner = User(username="owner", password_hash=hash_password("password"))
    other = User(username="other", password_hash=hash_password("password"))
    db_session.add_all([owner, other])
    db_session.flush()
    entry = KnowledgeEntry(
        user_id=owner.id, category="travel_guide", title="南京攻略",
        body="景点" * 5000, city_code="320100", city_name="南京市", tags=[],
    )
    db_session.add(entry)
    db_session.commit()

    rows = search_knowledge(db_session, owner.id, "320100")
    assert len(rows) == 1
    assert len(rows[0].excerpt) <= 240
    assert read_knowledge_excerpt(db_session, owner.id, entry.id, offset=240) is not None
    assert len(read_knowledge_excerpt(db_session, owner.id, entry.id, offset=240)) <= 600
    assert read_knowledge_excerpt(db_session, other.id, entry.id) is None
    with pytest.raises(ValueError):
        read_knowledge_excerpt(db_session, owner.id, entry.id, offset=10000)


def test_city_resolution_matches_android_city_granularity() -> None:
    assert resolve_city_code("南京") == "320100"
    assert resolve_city_code("北京市") == "110000"
    assert resolve_city_code("仙桃") == "429004"
    assert resolve_city_code("鼓楼区") is None
