"""Обратная совместимость: ре-экспорт PostgreSQL Database из utils.postgres_db."""

from utils.postgres_db import Database, db  # noqa: F401

__all__ = ['Database', 'db']