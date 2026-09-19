from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from mysql.connector import Error as DatabaseError
from urllib.parse import urlsplit, parse_qs
import re
import os
from config import SESSION_SECRET, SESSION_HTTPS_ONLY
from starlette.middleware.sessions import SessionMiddleware
from security import hash_password, verify_password, get_csrf_token, verify_csrf_token
from argon2.exceptions import HashingError, VerificationError, InvalidHashError

from database import (
    ResourceNotFound,
    get_notes,
    get_note,
    add_note,
    update_note,
    delete_note,
    search_notes,
    get_types,
    add_type,
    update_type_name,
    delete_type,
    get_type_record_count,
    get_types_with_counts,
    get_ungrouped_count,
    get_notes_by_type,
    get_ungrouped_notes,
    get_type,
    get_sidebar_records,
    create_user,
    get_user_conflicts,
    get_user_by_login,
    get_user_by_id,
)


session_secret = SESSION_SECRET

def require_application_login(request: Request):
    # Run before endpoint parameter validation, including malformed resource IDs.
    if request.url.path in ("/login", "/register", "/logout"):
        return
    current_user = get_current_user(request)
    if current_user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    request.state.current_user = current_user


async def require_csrf(request: Request):
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    form = await request.form()
    tokens = form.getlist("csrf_token")
    if len(tokens) != 1 or not verify_csrf_token(request.session, tokens[0]):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


# Authentication keeps its existing redirect behavior; CSRF runs before route
# handlers, resource lookups and writes, independently of ownership checks.
app = FastAPI(dependencies=[Depends(require_application_login), Depends(require_csrf)])
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    same_site="lax",
    max_age=None,  # Browser-session cookie; no Remember Me option.
    # SessionMiddleware always sets HttpOnly; it has no httponly argument.
    https_only=SESSION_HTTPS_ONLY,
)

# Verify a dummy hash for unknown accounts to avoid a cheap account-existence probe.
dummy_password_hash = hash_password(os.urandom(32).hex())

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
templates.env.globals["csrf_token"] = get_csrf_token

def get_common_context(user_id):
    return {
        "sidebar_types": get_types_with_counts(user_id),
        "sidebar_records": get_sidebar_records(user_id),
        "ungrouped_count": get_ungrouped_count(user_id)
    }

def safe_return_to(value):
    if not isinstance(value, str) or not value.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return "/notes"
    if "\\" in value or re.search(r"%(?:0[0-9a-f]|1[0-9a-f]|7f|25|2f|5c)", value, re.I):
        return "/notes"
    try:
        parts = urlsplit(value)
    except ValueError:
        return "/notes"
    if parts.scheme or parts.netloc or parts.fragment:
        return "/notes"
    if not re.fullmatch(r"/|/notes|/notes/[0-9]+(?:/edit)?", parts.path):
        return "/notes"
    return value


def valid_return_to(user_id, value):
    target = safe_return_to(value)
    parts = urlsplit(target)
    match = re.fullmatch(r"/notes/([0-9]+)(?:/edit)?", parts.path)
    if match and get_note(user_id, int(match[1])) is None:
        return "/notes"
    return target


def render_form_error(request, return_to, fields, status_code=400):
    current_user = get_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    user_id = current_user["id"]
    target = valid_return_to(user_id, return_to)
    parts = urlsplit(target)
    scope = dict(request.scope, method="GET", path=parts.path,
                 query_string=parts.query.encode("utf-8"))
    source_request = Request(scope)
    if parts.path == "/":
        response = home(source_request)
    elif parts.path == "/notes":
        query = parse_qs(parts.query, keep_blank_values=True)
        response = notes(source_request, q=query.get("q", [""])[-1],
                         type=query.get("type", [""])[-1])
    elif parts.path.endswith("/edit"):
        response = edit_note_page(source_request, int(parts.path.split("/")[2]))
    else:
        response = note_detail(source_request, int(parts.path.split("/")[2]))
    context = dict(response.context)
    context.update(fields)
    context["form_return_to"] = target
    return templates.TemplateResponse(request=source_request, name=response.template.name,
                                      context=context, status_code=status_code)


def validate_registration(username, email, password, confirm_password):
    if not username:
        return ("Please enter a username.", "请输入用户名。")
    if len(username) > 50:
        return ("Username must be 50 characters or fewer.", "用户名不能超过 50 个字符。")
    if not email:
        return ("Please enter an email address.", "请输入邮箱地址。")
    if len(email) > 255:
        return ("Email must be 255 characters or fewer.", "邮箱不能超过 255 个字符。")
    if not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", email):
        return ("Please enter a valid email address.", "请输入有效的邮箱地址。")
    if not password:
        return ("Please enter a password.", "请输入密码。")
    if len(password) < 8:
        return ("Password must contain at least 8 characters.", "密码至少需要 8 个字符。")
    if password != confirm_password:
        return ("Passwords do not match.", "两次输入的密码不一致。")
    return None


def render_registration(request, username="", email="", error=None, status_code=200, success=False):
    context = dict(username=username, email=email, registration_error=error,
                   registration_success=success)
    return templates.TemplateResponse(request=request, name="register.html",
                                      context=context, status_code=status_code)


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, success: str = ""):
    return render_registration(request, success=success == "1")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render_login(request)


def render_login(request, login="", error=None, status_code=200):
    return templates.TemplateResponse(request=request, name="login.html",
                                      context={"login": login, "login_error": error},
                                      status_code=status_code)


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, login: str = Form(""), password: str = Form("")):
    login = login.strip()
    invalid = ("Invalid username/email or password.", "用户名、邮箱或密码错误。")
    if not login or not password:
        return render_login(request, login, invalid, 401)
    try:
        user = get_user_by_login(login)
        valid = verify_password(password, user["password_hash"] if user else dummy_password_hash)
    except (VerificationError, InvalidHashError):
        return render_login(request, login, invalid, 401)
    except DatabaseError:
        return render_login(request, login,
                            ("Unable to log in right now. Please try again later.", "暂时无法登录，请稍后重试。"), 503)
    if not user or not valid:
        return render_login(request, login, invalid, 401)
    request.session.clear()
    request.session["user_id"] = user["id"]
    get_csrf_token(request.session)
    return RedirectResponse(url="/", status_code=303)


def get_current_user(request: Request):
    if hasattr(request.state, "current_user"):
        return request.state.current_user
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    if type(user_id) is not int or user_id <= 0:
        request.session.clear()
        return None
    try:
        user = get_user_by_id(user_id)
    except DatabaseError:
        # A temporary outage does not mean the account was deleted.
        return None
    if user is None:
        request.session.clear()
    return user


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.post("/register", response_class=HTMLResponse)
def register(request: Request, username: str = Form(""), email: str = Form(""),
             password: str = Form(""), confirm_password: str = Form("")):
    username, email = username.strip(), email.strip()
    error = validate_registration(username, email, password, confirm_password)
    if error:
        return render_registration(request, username, email, error, 400)
    try:
        create_user(username, email, hash_password(password))
    except (DatabaseError, HashingError) as exc:
        error = ("Unable to register right now. Please try again later.", "暂时无法注册，请稍后重试。")
        status_code = 503
        if isinstance(exc, DatabaseError) and exc.errno == 1062:
            status_code = 409
            error = ("Username or email is already in use.", "用户名或邮箱已被使用。")
            try:
                username_taken, email_taken = get_user_conflicts(username, email)
                if username_taken:
                    error = ("Username is already in use.", "用户名已被使用。")
                elif email_taken:
                    error = ("Email is already in use.", "邮箱已被使用。")
            except DatabaseError:
                pass
        return render_registration(request, username, email, error, status_code)
    return RedirectResponse(url="/register?success=1", status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    current_user = get_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    user_id = current_user["id"]
    recent_notes = get_notes(user_id)[:5]

    context = get_common_context(user_id)
    context["recent_notes"] = recent_notes
    context["current_user"] = current_user

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=context
    )


@app.get("/notes", response_class=HTMLResponse)
def notes(
    request: Request,
    q: str = "",
    type: str = ""
):
    current_user = get_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    user_id = current_user["id"]
    type_not_found = False
    invalid_type = False
    if q:
        rows = search_notes(user_id, q)

    elif type == "ungrouped":
        rows = get_ungrouped_notes(user_id)

    elif type:
        if type.isdigit():
            selected_type = get_type(user_id, int(type))

            if selected_type:
                rows = get_notes_by_type(user_id, int(type))
            else:
                raise HTTPException(status_code=404, detail="Not found")
        else:
            rows = []
            invalid_type = True

    else:
        rows = get_notes(user_id)

    types = get_types(user_id)

    context = get_common_context(user_id)
    context["notes"] = rows
    context["types"] = types
    context["q"] = q
    context["selected_type"] = type
    context["type_not_found"] = type_not_found
    context["invalid_type"] = invalid_type

    return templates.TemplateResponse(
        request=request,
        name="notes.html",
        context=context
    )

@app.post("/types", response_class=HTMLResponse)
def create_type(request: Request, name: str = Form(""), return_to: str = Form("/notes")):
    current_user = get_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    user_id = current_user["id"]
    name = name.strip()
    if not name:
        error = ("Please enter a type name.", "请输入类型名称。")
    elif len(name) > 50:
        error = ("Type names must be 50 characters or fewer.", "类型名称不能超过 50 个字符。")
    else:
        try:
            if add_type(user_id, name):
                return RedirectResponse(url=valid_return_to(user_id, return_to), status_code=303)
            error = ("A type with this name already exists.", "该类型名称已存在，请使用其他名称。")
        except DatabaseError:
            error = ("Unable to create this type right now. Please try again later.",
                     "暂时无法创建该类型，请稍后重试。")

    return render_form_error(request, return_to, {
        "new_type_name": name, "new_type_error": error,
    })



@app.post("/types/{type_id}/rename", response_class=HTMLResponse)
def rename_type(request: Request, type_id: int, name: str = Form(""), return_to: str = Form("/notes")):
    current_user = get_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    user_id = current_user["id"]
    current_type = get_type(user_id, type_id)
    name = name.strip()
    status_code = 400
    if current_type is None:
        raise HTTPException(status_code=404, detail="Not found")
    elif current_type["is_default"] != False:
        error = ("Default types cannot be renamed.", "默认类型不能重命名。")
        status_code = 403
    elif not name:
        error = ("Please enter a type name.", "请输入类型名称。")
    elif len(name) > 50:
        error = ("Type names must be 50 characters or fewer.", "类型名称不能超过 50 个字符。")
    elif name == current_type["name"] or update_type_name(user_id, type_id, name):
        return RedirectResponse(url=valid_return_to(user_id, return_to), status_code=303)
    else:
        error = ("A type with this name already exists.", "该类型名称已存在，请使用其他名称。")

    context = get_common_context(user_id)
    context.update({
        "notes": get_notes(user_id), "types": get_types(user_id), "q": "", "selected_type": "",
        "rename_type_id": type_id,
        "rename_current_name": current_type["name"] if current_type else "",
        "rename_type_name": name,
        "rename_type_error": error,
    })
    return templates.TemplateResponse(
        request=request, name="notes.html", context=context, status_code=status_code
    )


@app.post("/types/{type_id}/delete", response_class=HTMLResponse)
def remove_type(request: Request, type_id: int, return_to: str = Form("/notes")):
    current_user = get_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    user_id = current_user["id"]
    current_type = None
    in_use_error = (
        "This type is used by records and cannot be deleted.",
        "该类型仍被记录使用，无法删除。"
    )
    try:
        current_type = get_type(user_id, type_id)
        if current_type is None:
            raise HTTPException(status_code=404, detail="Not found")
        elif current_type["is_default"] != False:
            error = ("Default types cannot be deleted.", "默认类型不能删除。")
            status_code = 403
        elif get_type_record_count(user_id, type_id) > 0:
            error = in_use_error
            status_code = 409
        elif delete_type(user_id, type_id):
            target = valid_return_to(user_id, return_to)
            parts = urlsplit(target)
            selected = parse_qs(parts.query).get("type", [])
            if parts.path == "/notes" and any(v.isascii() and v.isdigit() and int(v) == type_id for v in selected):
                target = "/notes"
            return RedirectResponse(url=target, status_code=303)
        else:
            error = ("The type has changed or no longer exists. Please refresh and try again.",
                     "该类型已变更或不存在，请刷新后重试。")
            status_code = 409
    except DatabaseError as exc:
        if exc.errno == 1451:
            error = in_use_error
            status_code = 409
        else:
            error = ("Unable to delete this type right now. Please try again later.",
                     "暂时无法删除该类型，请稍后重试。")
            status_code = 503

    template_name = "notes.html"
    try:
        context = get_common_context(user_id)
        context.update({"notes": get_notes(user_id), "types": get_types(user_id)})
    except DatabaseError:
        # Render the error modal even when the database cannot serve the Library.
        context = {"sidebar_types": [], "sidebar_records": [], "ungrouped_count": 0}
        template_name = "base.html"
    context.update({
        "q": "", "selected_type": "", "delete_type_id": type_id,
        "delete_type_name": current_type["name"] if current_type else "",
        "delete_type_error": error,
    })
    return templates.TemplateResponse(
        request=request, name=template_name, context=context, status_code=status_code
    )


@app.post("/notes")
def create_note(
    request: Request,
    title: str = Form(""),
    content: str = Form(""),
    url: str = Form(""),
    type_id: str = Form(""),
    return_to: str = Form("/notes")
):
    current_user = get_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    user_id = current_user["id"]
    fields = {"record_title": title, "record_content": content,
              "record_url": url, "record_type_id": type_id}
    error = None
    if not title.strip():
        error = ("Please enter a title.", "请输入标题。")
    elif type_id and (not type_id.isascii() or not type_id.isdigit()):
        error = ("Please choose a valid type.", "请选择有效的类型。")
    try:
        if error is None and type_id and get_type(user_id, int(type_id)) is None:
            raise HTTPException(status_code=404, detail="Not found")
        if error is None:
            saved_url = url
            if saved_url and not saved_url.startswith(("http://", "https://")):
                saved_url = "https://" + saved_url
            add_note(user_id, title, content, saved_url, int(type_id) if type_id else None)
            return RedirectResponse(url=valid_return_to(user_id, return_to), status_code=303)
    except DatabaseError:
        error = ("Unable to save this record. Please check the fields and try again.",
                 "无法保存记录，请检查输入后重试。")
    fields["record_error"] = error
    return render_form_error(request, return_to, fields)

@app.get("/notes/{note_id}", response_class=HTMLResponse)
def note_detail(request: Request, note_id: int):
    current_user = get_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    user_id = current_user["id"]
    note = get_note(user_id, note_id)

    if not note:
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>Record Not Found</title>
            </head>
            <body>
                <h1>Record Not Found</h1>
                <p>This record does not exist.</p>
                <a href="/notes">Back to Library</a>
            </body>
            </html>
            """,
            status_code=404
        )

    context = get_common_context(user_id)
    context["note"] = note
    context["selected_record_id"] = note["id"]
    context["selected_type"] = (
        str(note["type_id"]) if note["type_id"] is not None else "ungrouped"
    )

    return templates.TemplateResponse(
        request=request,
        name="note_detail.html",
        context=context
    )
    
@app.get("/notes/{note_id}/edit", response_class=HTMLResponse)
def edit_note_page(request: Request, note_id: int):
    current_user = get_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    user_id = current_user["id"]
    note = get_note(user_id, note_id)

    if not note:
        return HTMLResponse(
            content="<h1>Record Not Found</h1>",
            status_code=404
        )

    types = get_types(user_id)

    context = get_common_context(user_id)
    context["note"] = note
    context["types"] = types

    return templates.TemplateResponse(
        request=request,
        name="edit_note.html",
        context=context
    )
    
@app.post("/notes/{note_id}/edit")
def edit_note(
    request: Request,
    note_id: int,
    title: str = Form(...),
    content: str = Form(""),
    url: str = Form(""),
    type_id: str = Form("")
):
    current_user = get_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    user_id = current_user["id"]
    if get_note(user_id, note_id) is None:
        raise HTTPException(status_code=404, detail="Not found")
    if type_id and (not type_id.isascii() or not type_id.isdigit()):
        raise HTTPException(status_code=400, detail="Invalid type")
    type_id = int(type_id) if type_id else None
    if type_id is not None and get_type(user_id, type_id) is None:
        raise HTTPException(status_code=404, detail="Not found")

    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url

    update_note(user_id, note_id, title, content, url, type_id)

    return RedirectResponse(
        url=f"/notes/{note_id}",
        status_code=303
    )
    
@app.post("/notes/{note_id}/delete")
def remove_note(request: Request, note_id: int):
    current_user = get_current_user(request)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    user_id = current_user["id"]
    note = get_note(user_id, note_id)

    if not note:
        return HTMLResponse(
            content="<h1>Record Not Found</h1>",
            status_code=404
        )

    delete_note(user_id, note_id)

    return RedirectResponse(
        url="/notes",
        status_code=303
    )


@app.exception_handler(ResourceNotFound)
async def resource_not_found(request: Request, exc: ResourceNotFound):
    return HTMLResponse("Not found", status_code=404)
