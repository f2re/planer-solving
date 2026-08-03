from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "web" / "frontend" / "index.html"


def test_base_template_matches_nonblocking_product_contract() -> None:
    source = INDEX.read_text(encoding="utf-8")

    assert "Сформировать результат" in source
    assert "Результат создаётся из пригодных данных" in source
    assert "Вернуть исходный автоанализ" in source
    assert "Локальная правка текущего файла сохраняется независимо от шаблона" in source
    for obsolete in (
        "только после контрольного разбора",
        "Результат формируется только из файлов без критических ошибок",
        "Шаблоны хранятся локально в браузере",
        "Разметка ошибочна",
    ):
        assert obsolete not in source


def test_start_screen_does_not_duplicate_teacher_management() -> None:
    source = INDEX.read_text(encoding="utf-8")

    assert "teacher-card" not in source
    assert "Преподаватели кафедры" not in source
    assert "openManager('teachers')" not in source
