from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import get_notes, get_note, add_note, update_note, delete_note, search_notes


app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    recent_notes = get_notes()[:5]

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"recent_notes": recent_notes}
    )


@app.get("/notes", response_class=HTMLResponse)
def notes(request: Request, q: str = ""):
    if q:
        rows = search_notes(q)
    else:
        rows = get_notes()

    return templates.TemplateResponse(
        request=request,
        name="notes.html",
        context={
            "notes": rows,
            "q": q
        }
    )

@app.post("/notes")
def create_note(
    title: str = Form(...),
    content: str = Form(""),
    url: str = Form("")
):
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url

    add_note(title, content, url)

    return RedirectResponse(
        url="/notes",
        status_code=303
    )

@app.get("/notes/{note_id}", response_class=HTMLResponse)
def note_detail(request: Request, note_id: int):
    note = get_note(note_id)

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

    return templates.TemplateResponse(
        request=request,
        name="note_detail.html",
        context={"note": note}
    )
    
@app.get("/notes/{note_id}/edit", response_class=HTMLResponse)
def edit_note_page(request: Request, note_id: int):
    note = get_note(note_id)

    if not note:
        return HTMLResponse(
            content="<h1>Record Not Found</h1>",
            status_code=404
        )

    return templates.TemplateResponse(
        request=request,
        name="edit_note.html",
        context={"note": note}
    )
    
@app.post("/notes/{note_id}/edit")
def edit_note(
    note_id: int,
    title: str = Form(...),
    content: str = Form(""),
    url: str = Form("")
):
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url

    update_note(note_id, title, content, url)

    return RedirectResponse(
        url=f"/notes/{note_id}",
        status_code=303
    )
    
@app.post("/notes/{note_id}/delete")
def remove_note(note_id: int):
    note = get_note(note_id)

    if not note:
        return HTMLResponse(
            content="<h1>Record Not Found</h1>",
            status_code=404
        )

    delete_note(note_id)

    return RedirectResponse(
        url="/notes",
        status_code=303
    )
