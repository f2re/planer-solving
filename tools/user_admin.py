"""Offline account recovery and administration for Planner Solving."""
from __future__ import annotations

import argparse
from getpass import getpass
import json
from pathlib import Path
import sys
from typing import Any, Dict

from src.transactional_platform_store import TransactionalPlatformStore
from src.workspace_domain import WorkspaceError, WorkspaceNotFound


def build_store(data_dir: Path, legacy_teachers: Path | None = None) -> TransactionalPlatformStore:
    root = data_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return TransactionalPlatformStore(
        root / "planner-solving.sqlite3",
        root / "workspaces.json",
        legacy_teachers,
    )


def find_user(store: TransactionalPlatformStore, username: str) -> Dict[str, Any]:
    normalized = username.strip().casefold()
    user = next(
        (item for item in store.list_users() if str(item.get("username", "")).casefold() == normalized),
        None,
    )
    if not user:
        raise WorkspaceNotFound(f"Пользователь «{username}» не найден.")
    return user


def read_password(args: argparse.Namespace) -> str:
    if getattr(args, "empty", False):
        return ""
    if getattr(args, "password", None) is not None:
        return args.password
    first = getpass("Новый пароль, можно пустой: ")
    second = getpass("Повторите пароль: ")
    if first != second:
        raise WorkspaceError("Введённые пароли не совпадают.")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Локальное управление пользователями Planner Solving",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("/opt/planner-solving/shared/data"),
        help="Каталог данных приложения",
    )
    parser.add_argument(
        "--legacy-teachers",
        type=Path,
        default=Path("/opt/planner-solving/shared/teachers.json"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="Показать пользователей")

    reset = subparsers.add_parser("reset-password", help="Задать новый пароль")
    reset.add_argument("username")
    reset.add_argument("--password", help="Пароль в командной строке; не рекомендуется для журнала shell")
    reset.add_argument("--empty", action="store_true", help="Установить пустой пароль")

    unlock = subparsers.add_parser("unlock", help="Включить пользователя")
    unlock.add_argument("username")

    role = subparsers.add_parser("set-role", help="Изменить роль")
    role.add_argument("username")
    role.add_argument("role", choices=["admin", "operator", "viewer"])

    create = subparsers.add_parser("create-admin", help="Создать администратора")
    create.add_argument("--username", default="admin")
    create.add_argument("--display-name", default="Администратор")
    create.add_argument("--password")
    create.add_argument("--empty", action="store_true")

    args = parser.parse_args(argv)
    try:
        store = build_store(
            args.data_dir,
            args.legacy_teachers if args.legacy_teachers.exists() else None,
        )
        if args.command == "list":
            print(json.dumps(store.list_users(), ensure_ascii=False, indent=2, default=str))
            return 0
        if args.command == "reset-password":
            user = find_user(store, args.username)
            updated = store.reset_user_password(user["id"], read_password(args))
            print(f"Пароль пользователя {updated['username']} сброшен; активные сеансы закрыты.")
            return 0
        if args.command == "unlock":
            user = find_user(store, args.username)
            updated = store.update_user(user["id"], {"is_active": True})
            print(f"Пользователь {updated['username']} включён.")
            return 0
        if args.command == "set-role":
            user = find_user(store, args.username)
            updated = store.update_user(user["id"], {"role": args.role})
            print(f"Роль пользователя {updated['username']}: {updated['role']}.")
            return 0
        if args.command == "create-admin":
            password = read_password(args)
            if store.user_count() == 0:
                user = store.bootstrap_admin(args.username, args.display_name, password)
            else:
                user = store.create_user({
                    "username": args.username,
                    "display_name": args.display_name,
                    "password": password,
                    "role": "admin",
                })
            print(f"Создан администратор {user['username']}.")
            return 0
    except (WorkspaceError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
