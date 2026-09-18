from config import require_environment
from contextlib import contextmanager
import mysql.connector

DEFAULT_TYPES = ("Note", "Website", "Article", "Video", "Tool", "Project")


def get_db_connection():
    return mysql.connector.connect(host="localhost", user="root",
        password=require_environment("DB_PASSWORD"), database="memovault")


@contextmanager
def _cursor(write=False):
    connection = get_db_connection()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        yield cursor
        if write:
            connection.commit()
    except Exception:
        if write:
            connection.rollback()
        raise
    finally:
        try:
            if cursor is not None:
                cursor.close()
        finally:
            connection.close()


NOTE_SELECT = """SELECT notes.*, types.name AS type_name FROM notes
    LEFT JOIN types ON notes.type_id = types.id AND notes.user_id = types.user_id
    WHERE notes.user_id = %s"""


def _notes(user_id, clause="", params=()):
    with _cursor() as cursor:
        cursor.execute(NOTE_SELECT + clause + " ORDER BY notes.updated_at DESC", (user_id, *params))
        return cursor.fetchall()


def get_notes(user_id):
    return _notes(user_id)


def get_note(user_id, note_id):
    with _cursor() as cursor:
        cursor.execute(NOTE_SELECT + " AND notes.id = %s", (user_id, note_id))
        return cursor.fetchone()


def search_notes(user_id, keyword):
    return _notes(user_id, " AND (notes.title LIKE %s OR notes.content LIKE %s)",
                  (f"%{keyword}%", f"%{keyword}%"))


def get_notes_by_type(user_id, type_id):
    return _notes(user_id, " AND notes.type_id = %s", (type_id,))


def get_ungrouped_notes(user_id):
    return _notes(user_id, " AND notes.type_id IS NULL")


class ResourceNotFound(Exception):
    pass


def _check_type(cursor, user_id, type_id):
    if type_id is not None:
        cursor.execute("SELECT id FROM types WHERE user_id = %s AND id = %s", (user_id, type_id))
        if cursor.fetchone() is None:
            raise ResourceNotFound()


def add_note(user_id, title, content, url, type_id):
    with _cursor(write=True) as cursor:
        _check_type(cursor, user_id, type_id)
        cursor.execute("INSERT INTO notes (user_id, title, content, url, type_id) VALUES (%s, %s, %s, %s, %s)",
                       (user_id, title, content, url, type_id))
        return cursor.lastrowid


def update_note(user_id, note_id, title, content, url, type_id):
    with _cursor(write=True) as cursor:
        cursor.execute("SELECT id FROM notes WHERE user_id = %s AND id = %s FOR UPDATE", (user_id, note_id))
        if cursor.fetchone() is None:
            raise ResourceNotFound()
        _check_type(cursor, user_id, type_id)
        cursor.execute("UPDATE notes SET title = %s, content = %s, url = %s, type_id = %s WHERE user_id = %s AND id = %s",
                       (title, content, url, type_id, user_id, note_id))


def delete_note(user_id, note_id):
    with _cursor(write=True) as cursor:
        cursor.execute("DELETE FROM notes WHERE user_id = %s AND id = %s", (user_id, note_id))
        if cursor.rowcount != 1:
            raise ResourceNotFound()


def add_type(user_id, name):
    try:
        with _cursor(write=True) as cursor:
            cursor.execute("INSERT INTO types (user_id, name, is_default) VALUES (%s, %s, FALSE)", (user_id, name))
        return True
    except mysql.connector.IntegrityError as error:
        if error.errno == 1062:
            return False
        raise


def update_type_name(user_id, type_id, name):
    try:
        with _cursor(write=True) as cursor:
            cursor.execute("UPDATE types SET name = %s WHERE user_id = %s AND id = %s AND is_default = FALSE", (name, user_id, type_id))
            changed = cursor.rowcount == 1
        return changed
    except mysql.connector.IntegrityError as error:
        if error.errno == 1062:
            return False
        raise


def delete_type(user_id, type_id):
    with _cursor(write=True) as cursor:
        cursor.execute("DELETE FROM types WHERE user_id = %s AND id = %s AND is_default = FALSE", (user_id, type_id))
        return cursor.rowcount == 1


def get_type_record_count(user_id, type_id):
    with _cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS record_count FROM notes WHERE user_id = %s AND type_id = %s", (user_id, type_id))
        return cursor.fetchone()["record_count"]


def get_types(user_id):
    with _cursor() as cursor:
        cursor.execute("SELECT id, name, is_default FROM types WHERE user_id = %s ORDER BY is_default DESC, name ASC", (user_id,))
        return cursor.fetchall()


def get_type(user_id, type_id):
    with _cursor() as cursor:
        cursor.execute("SELECT id, name, is_default FROM types WHERE user_id = %s AND id = %s", (user_id, type_id))
        return cursor.fetchone()


def get_types_with_counts(user_id):
    with _cursor() as cursor:
        cursor.execute("""SELECT types.id, types.name, types.is_default, COUNT(notes.id) AS record_count
            FROM types LEFT JOIN notes ON notes.type_id = types.id AND notes.user_id = types.user_id
            WHERE types.user_id = %s GROUP BY types.id, types.name, types.is_default
            ORDER BY types.is_default DESC, types.name ASC""", (user_id,))
        return cursor.fetchall()


def get_ungrouped_count(user_id):
    with _cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS record_count FROM notes WHERE user_id = %s AND type_id IS NULL", (user_id,))
        return cursor.fetchone()["record_count"]


def get_sidebar_records(user_id):
    with _cursor() as cursor:
        cursor.execute("SELECT id, title, type_id FROM notes WHERE user_id = %s ORDER BY updated_at DESC", (user_id,))
        return cursor.fetchall()


def create_user(username, email, password_hash):
    connection = get_db_connection()
    cursor = None
    try:
        connection.start_transaction()
        cursor = connection.cursor()
        cursor.execute("""
            INSERT INTO users (username, email, password_hash)
            VALUES (%s, %s, %s)
        """, (username, email, password_hash))
        user_id = cursor.lastrowid
        for name in DEFAULT_TYPES:
            cursor.execute("INSERT INTO types (user_id, name, is_default) VALUES (%s, %s, TRUE)", (user_id, name))
        connection.commit()
        return user_id
    except Exception:
        connection.rollback()
        raise
    finally:
        try:
            if cursor is not None:
                cursor.close()
        finally:
            connection.close()


def get_user_conflicts(username, email):
    """Use MySQL column collations to identify conflicts, not Python case folding."""
    connection = get_db_connection()
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT EXISTS(SELECT 1 FROM users WHERE username = %s),
                   EXISTS(SELECT 1 FROM users WHERE email = %s)
        """, (username, email))
        return cursor.fetchone()
    finally:
        try:
            if cursor is not None:
                cursor.close()
        finally:
            connection.close()

def get_user_by_login(login):
    connection = get_db_connection()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, username, email, password_hash, email_verified, created_at
            FROM users
            WHERE username = %s OR email = %s
            LIMIT 1
        """, (login, login))
        return cursor.fetchone()
    finally:
        try:
            if cursor is not None:
                cursor.close()
        finally:
            connection.close()


def get_user_by_id(user_id):
    connection = get_db_connection()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id, username FROM users WHERE id = %s", (user_id,))
        return cursor.fetchone()
    finally:
        try:
            if cursor is not None:
                cursor.close()
        finally:
            connection.close()
