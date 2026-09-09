import os
import mysql.connector


def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password=os.getenv("DB_PASSWORD"),
        database="memovault"
    )


def get_notes():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, title, content, url, created_at, updated_at
        FROM notes
        ORDER BY updated_at DESC
    """)

    rows = cursor.fetchall()

    cursor.close()
    connection.close()

    return rows

def get_note(note_id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    sql = """
    SELECT id, title, content, url, created_at, updated_at
    FROM notes
    WHERE id = %s
    """

    cursor.execute(sql, (note_id,))

    row = cursor.fetchone()

    cursor.close()
    connection.close()

    return row

def add_note(title, content, url):
    connection = get_db_connection()
    cursor = connection.cursor()

    sql = """
    INSERT INTO notes (title, content, url)
    VALUES (%s, %s, %s)
    """

    cursor.execute(sql, (title, content, url))

    connection.commit()

    cursor.close()
    connection.close()
    
def update_note(note_id, title, content, url):
    connection = get_db_connection()
    cursor = connection.cursor()

    sql = """
    UPDATE notes
    SET title = %s,
        content = %s,
        url = %s
    WHERE id = %s
    """

    cursor.execute(
        sql,
        (title, content, url, note_id)
    )

    connection.commit()

    cursor.close()
    connection.close()
    
def delete_note(note_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    sql = """
    DELETE FROM notes
    WHERE id = %s
    """

    cursor.execute(sql, (note_id,))

    connection.commit()

    cursor.close()
    connection.close()