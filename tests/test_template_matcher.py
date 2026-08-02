from types import SimpleNamespace

from src.template_matcher import rank_candidates, score_candidate


def lesson(week: int, pair: int, subject: str, teacher: str, room: str = "101"):
    return SimpleNamespace(
        week=week,
        day_of_week="Пн",
        pair_num=pair,
        subject=subject,
        teacher=teacher,
        room=room,
    )


def test_score_prefers_unique_mapped_information():
    good_lessons = [
        lesson(1, 1, "Математика", "Иванов И.И."),
        lesson(2, 1, "Математика", "Иванов И.И."),
        lesson(1, 2, "Физика", "Петров П.П."),
    ]
    weak_lessons = [
        lesson(1, 1, "Математика", "Unknown"),
        lesson(1, 1, "Математика", "Unknown"),
        lesson(1, 1, "Математика", "Unknown"),
    ]
    good = score_candidate(
        {"errors": [], "warnings": [], "legend_entries": 4, "empty_week_columns": []},
        good_lessons,
    )
    weak = score_candidate(
        {"errors": [], "warnings": ["Не найден преподаватель"], "legend_entries": 0, "empty_week_columns": [8]},
        weak_lessons,
    )

    assert good["usable"] is True
    assert good["score"] > weak["score"]
    assert good["quality_percent"] > weak["quality_percent"]


def test_parser_error_makes_candidate_unusable():
    result = score_candidate(
        {"errors": ["Диапазон вне листа"], "warnings": [], "legend_entries": 0},
        [lesson(1, 1, "Физика", "Иванов И.И.")],
    )

    assert result["usable"] is False
    assert result["quality_percent"] == 0
    assert result["score"] < 0


def test_automatic_layout_wins_only_on_exact_tie():
    common = {
        "score": 100,
        "quality_percent": 90,
        "metrics": {"mapped_lessons": 10, "unique_lessons": 10},
    }
    ranked = rank_candidates([
        {**common, "source": "template", "name": "Шаблон"},
        {**common, "source": "automatic", "name": "Авто"},
    ])

    assert ranked[0]["source"] == "automatic"
