import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.data_loader import Lesson
from src.teacher_assignment import resolve_teacher_collisions
from src.teacher_resolver import TeacherResolver
from web.backend.app_factory import create_app


def teacher_payload(short_name: str, full_name: str) -> dict:
    return {
        "short_name": short_name,
        "full_name": full_name,
        "position": "",
        "rank": "",
        "academic_degree": "",
    }


def test_workspace_assignment_rules_are_persistent_and_canonical(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    workspace_id = client.get("/api/workspaces").json()[0]["id"]
    teachers = [
        teacher_payload("Иванов И.И.", "Иванов Иван Иванович"),
        teacher_payload("Петров П.П.", "Петров Пётр Петрович"),
        teacher_payload("Сидоров С.С.", "Сидоров Сергей Сергеевич"),
    ]
    for teacher in teachers:
        response = client.post(
            f"/api/workspaces/{workspace_id}/teachers",
            json=teacher,
        )
        assert response.status_code == 200

    saved = client.put(
        f"/api/workspaces/{workspace_id}/teacher-assignment-rules",
        json={
            "rules": [{
                "subject": "Математика",
                "lecturer": "Иванов Иван Иванович",
                "practice": "Петров П.П.",
                "reserve": "Сидоров Сергей Сергеевич",
            }]
        },
    )
    assert saved.status_code == 200
    item = saved.json()["items"][0]
    assert item["lecturer"] == "Иванов И.И."
    assert item["practice"] == "Петров П.П."
    assert item["reserve"] == "Сидоров С.С."

    loaded = client.get(
        f"/api/workspaces/{workspace_id}/teacher-assignment-rules"
    )
    assert loaded.status_code == 200
    assert loaded.json()["items"] == saved.json()["items"]


def test_role_preferences_feed_resolver_and_validation_report(tmp_path: Path) -> None:
    teachers_path = tmp_path / "teachers.json"
    teachers_path.write_text(
        json.dumps([
            {"id": 1, **teacher_payload("Иванов И.И.", "Иванов Иван Иванович")},
            {"id": 2, **teacher_payload("Петров П.П.", "Петров Пётр Петрович")},
            {"id": 3, **teacher_payload("Сидоров С.С.", "Сидоров Сергей Сергеевич")},
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    resolver = TeacherResolver(str(teachers_path))
    applied = resolver.set_teacher_overrides({
        "@lecturer|Математика": "Иванов И.И.",
        "@other|Математика": "Петров П.П.",
        "@reserve|Математика": "Сидоров С.С.",
    })
    assert applied == {}

    resolver.last_report = {}
    lecturer = resolver._assign_teacher(1, "Пн", 1, "Математика", "Л", [])
    practice = resolver._assign_teacher(1, "Пн", 2, "Математика", "П", [])

    assert lecturer == "Иванов И.И."
    assert practice == "Петров П.П."
    assert resolver.last_report["subjects"] == ["Математика"]
    assert resolver.last_report["teacher_candidates"]["Математика"] == {
        "lecturer": ["Иванов И.И."],
        "practice": ["Петров П.П."],
        "reserve": ["Сидоров С.С."],
    }


def test_configured_reserve_precedes_teacher_of_another_role() -> None:
    teachers = [
        {"id": 1, **teacher_payload("Иванов И.И.", "Иванов Иван Иванович")},
        {"id": 2, **teacher_payload("Петров П.П.", "Петров Пётр Петрович")},
        {"id": 3, **teacher_payload("Сидоров С.С.", "Сидоров Сергей Сергеевич")},
    ]
    lessons = [
        Lesson(
            group="Ф-1", subject="Физика", lesson_type_code="Л", room="101",
            week=1, day_of_week="Пн", pair_num=1, teacher="Иванов И.И.",
            date_day=1, month="Сентябрь",
        ),
        Lesson(
            group="М-1", subject="Математика", lesson_type_code="Л", room="102",
            week=1, day_of_week="Пн", pair_num=1, teacher="Иванов И.И.",
            date_day=1, month="Сентябрь",
        ),
    ]
    report = resolve_teacher_collisions(
        lessons,
        teachers,
        candidate_catalog={
            "физика": {
                "lecturer": ["Иванов И.И."],
                "other": [],
                "reserve": [],
                "all": ["Иванов И.И."],
            },
            "математика": {
                "lecturer": ["Иванов И.И."],
                "other": ["Петров П.П."],
                "reserve": ["Сидоров С.С."],
                "all": ["Иванов И.И.", "Петров П.П.", "Сидоров С.С."],
            },
        },
    )

    assert lessons[0].teacher == "Иванов И.И."
    assert lessons[1].teacher == "Сидоров С.С."
    decision = next(item for item in report["decisions"] if item["subject"] == "Математика")
    assert decision["reserve_used"] is True
