import socket
import os
import mysql.connector
from urllib.parse import urlparse, parse_qs


def read_html(filename):
    with open(filename, "r", encoding="utf-8") as file:
        return file.read()


def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password=os.getenv("DB_PASSWORD"),
        database="memovault"
    )


def get_notes():
    connection = get_db_connection()
    cursor = connection.cursor()

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
    cursor = connection.cursor()

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

    values = (title, content, url)

    cursor.execute(sql, values)
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

    values = (title, content, url, note_id)

    cursor.execute(sql, values)
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


server_socket = socket.socket()

server_socket.bind(("0.0.0.0", 8080))

server_socket.listen()

print("Server started on port 8080")

while True:
    client_socket, client_address = server_socket.accept()

    client_socket.settimeout(5)

    try:
        request = client_socket.recv(1024)

    except socket.timeout:
        client_socket.close()
        continue

    if not request:
        client_socket.close()
        continue

    request_text = request.decode()

    parts = request_text.split("\r\n\r\n", 1)

    if len(parts) > 1:
        request_body = parts[1]
    else:
        request_body = ""

    request_line = request_text.split("\r\n")[0]

    print(client_address, request_line)

    request_parts = request_line.split(" ")

    method = request_parts[0]
    path = request_parts[1]

    parsed_url = urlparse(path)

    real_path = parsed_url.path

    if method == "GET":
        params = parse_qs(parsed_url.query)

    elif method == "POST":
        params = parse_qs(request_body)

    else:
        params = {}

    if real_path == "/":
        status = "200 OK"
        content = read_html("index.html")

    elif real_path == "/about":
        status = "200 OK"
        content = read_html("about.html")
        
    elif real_path == "/edit" and method == "GET":
        note_id = params.get("id", [""])[0]

        note = get_note(note_id)

        if note:
            status = "200 OK"

            note_id = note[0]
            title = note[1]
            note_content = note[2]
            url = note[3] or ""

            content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>Edit Note</title>
            </head>

            <body>
                <h1>Edit Note</h1>

                <form action="/update" method="POST">

                    <input type="hidden" name="id" value="{note_id}">

                    <p>Title:</p>
                    <input type="text" name="title" value="{title}">

                    <p>Content:</p>
                    <textarea name="content">{note_content}</textarea>

                    <p>URL:</p>
                    <input type="text" name="url" value="{url}">

                    <br><br>

                    <button type="submit">
                        Save Changes
                    </button>

                </form>

                <br>

                <a href="/notes">Cancel</a>
            </body>
            </html>
            """

        else:
            status = "404 Not Found"

            content = """
            <!DOCTYPE html>
            <html>
            <body>
                <h1>404 Note Not Found</h1>
                <a href="/notes">Back to Notes</a>
            </body>
            </html>
            """

    elif real_path == "/update" and method == "POST":
        note_id = params.get("id", [""])[0]
        title = params.get("title", [""])[0]
        note_content = params.get("content", [""])[0]
        url = params.get("url", [""])[0]

        title = title.strip()
        note_content = note_content.strip()
        url = url.strip()

        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url

        if note_id and title:
            update_note(
                note_id,
                title,
                note_content,
                url
            )

        status = "303 See Other"
        content = ""
    
    elif real_path == "/delete" and method == "POST":
        note_id = params.get("id", [""])[0]

        if note_id:
            delete_note(note_id)

        status = "303 See Other"
        content = ""

    elif real_path == "/notes":

        if method == "POST":
            title = params.get("title", [""])[0]
            note_content = params.get("content", [""])[0]
            url = params.get("url", [""])[0]

            title = title.strip()
            note_content = note_content.strip()
            url = url.strip()

            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url

            if title:
                add_note(title, note_content, url)

        status = "200 OK"

        notes = get_notes()

        content = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>MemoVault Notes</title>
        </head>

        <body>
            <h1>MemoVault Notes</h1>
        """

        for note in notes:
            note_id = note[0]
            title = note[1]
            note_content = note[2]
            url = note[3]
            created_at = note[4]

            content += f"""
            <hr>

            <h2>{title}</h2>

            <p>{note_content}</p>

            <p>Created: {created_at}</p>
            """

            if url:
                content += f"""
                <p>
                    <a href="{url}" target="_blank">
                        Open Link
                    </a>
                </p>
                """
            content += f"""
            <p>
                <a href="/edit?id={note_id}">
                    Edit
                </a>
            </p>
            """
            
            content += f"""
            <form action="/delete" method="POST"
                  onsubmit="return confirm('确定要删除这条记录吗？')">

                <input type="hidden" name="id" value="{note_id}">

                <button type="submit">
                    Delete
                </button>

            </form>
            """

        content += """
            <hr>

            <a href="/">Back to Home</a>

        </body>
        </html>
        """

    elif real_path == "/hello":
        status = "200 OK"

        name = params.get("name", ["Guest"])[0]

        content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Hello</title>
        </head>

        <body>
            <h1>Hello, {name}!</h1>

            <a href="/">Back to Home</a>
        </body>
        </html>
        """

    else:
        status = "404 Not Found"

        content = """
        <html>
        <body>
            <h1>404 Not Found</h1>

            <p>The page does not exist.</p>
        </body>
        </html>
        """

    body = content.encode("utf-8")

    if status == "303 See Other":
        response = (
            "HTTP/1.1 303 See Other\r\n"
            "Location: /notes\r\n"
            "Content-Length: 0\r\n"
            "Connection: close\r\n"
            "\r\n"
        )

        client_socket.sendall(
            response.encode("utf-8")
        )

    else:
        response = (
            "HTTP/1.1 " + status + "\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "Content-Length: " + str(len(body)) + "\r\n"
            "Connection: close\r\n"
            "\r\n"
        )

        client_socket.sendall(
            response.encode("utf-8") + body
        )

    client_socket.close()