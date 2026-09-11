"""The local server.

Instead of Electron: forward the port with `ssh -L` and data that lives on a compute
server can be viewed in the browser on your own machine (spec 8.1).
"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    Body,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)

from . import compose, figspec, files, loader
from .export import ExportError, to_pdf
from .figure import _read_src, build_figure, resolve
from .figspec import FIG_TOML, FigSpec, SpecError
from .security import TOKEN_COOKIE, TOKEN_HEADER, TOKEN_QUERY, new_token
from .files import ConflictError, FileAccessError
from .grid import GridError
from .layout import solve_layout
from .render import PanelRenderError, PanelSize, cache_stats, render_pdf, render_svg
from .units import UnitError, parse_length
from .watch import Hub, watching

STATIC = Path(__file__).parent / "static"
DEFAULT_HEIGHT_MM = 50.0  # only used by the single-panel view, where no solver runs


def create_app(root: Path, watch: bool = True, token: str | None = None) -> FastAPI:
    root = root.resolve()
    hub = Hub()
    # `token=""` disables the check; None asks for a fresh one.
    token = new_token() if token is None else token

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if not watch:
            yield
            return
        async with watching(root, hub):
            yield

    app = FastAPI(title="figalign", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.token = token

    def token_ok(request: Request) -> bool:
        if not token:
            return True
        offered = (
            request.query_params.get(TOKEN_QUERY)
            or request.headers.get(TOKEN_HEADER)
            or request.cookies.get(TOKEN_COOKIE)
        )
        return bool(offered) and secrets.compare_digest(offered, token)

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        """Reaching the API is enough to run code, so everything but the page needs the token.

        The page itself is allowed through so that the token can arrive in the query string
        and be exchanged for a cookie; it contains nothing but the shell of the UI.
        """
        if request.url.path == "/" or token_ok(request):
            return await call_next(request)
        return JSONResponse(
            {"detail": "missing or wrong token; open the URL figalign printed at startup"},
            status_code=403,
        )

    def current_spec() -> FigSpec:
        try:
            return figspec.load_spec(root)
        except (FileNotFoundError, SpecError, KeyError, GridError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def resolve_size(spec: FigSpec, w: str | None, h: str | None) -> PanelSize:
        try:
            w_mm = parse_length(w) if w else spec.preset.width_mm
            h_mm = parse_length(h) if h else DEFAULT_HEIGHT_MM
        except UnitError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if w_mm <= 0 or h_mm <= 0:
            raise HTTPException(status_code=400, detail="size must be positive")
        return PanelSize(w_mm=w_mm, h_mm=h_mm)

    def draw(spec: FigSpec, name: str, size: PanelSize, as_pdf: bool):
        panel = spec.panel(name)
        if panel.src is not None:
            if as_pdf:
                raise HTTPException(
                    status_code=501,
                    detail=f"[panels.{name}] is an SVG asset; there is no single-panel PDF route for it",
                )
            return compose.fit(_read_src(spec, panel.src), size.w_mm, size.h_mm)
        assert panel.fn is not None
        fn = loader.load_callable(spec.root, panel.fn)
        data = loader.load_data(spec.root, spec.data_ref)
        render = render_pdf if as_pdf else render_svg
        return render(fn, data, size, spec.preset, panel=name)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        if not token_ok(request):
            return PlainTextResponse(
                "figalign: open the URL printed at startup, the one carrying ?token=",
                status_code=403,
            )
        response = FileResponse(STATIC / "index.html")
        if token:
            # The page fetches /api/... itself, so hand it a cookie rather than making
            # every request in the front end remember to carry the token.
            response.set_cookie(
                TOKEN_COOKIE, token, httponly=True, samesite="strict", path="/"
            )
        return response

    @app.get("/api/spec")
    def api_spec() -> dict:
        spec = current_spec()
        preset = spec.preset
        resolved = resolve(spec)
        layout = resolved.layout
        return {
            "root": str(spec.root),
            "preset": {
                "name": preset.name,
                "width_mm": preset.width_mm,
                "font_size_pt": preset.font_size_pt,
                "font_family": preset.font_family,
            },
            "default_height_mm": DEFAULT_HEIGHT_MM,
            "data_ref": spec.data_ref,
            "grid": spec.grid,
            "labels": layout.labels,
            "figure": {
                "width_mm": layout.width_mm,
                "height_mm": layout.height_mm,
                "passes": resolved.passes,
                "converged": resolved.converged,
            },
            "panels": [_panel_info(spec, layout, name) for name in spec.order],
            "files": _editable_files(spec),
        }

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        """Push a notification whenever a watched file changes. The client re-fetches."""
        offered = socket.query_params.get(TOKEN_QUERY) or socket.cookies.get(TOKEN_COOKIE)
        if token and not (offered and secrets.compare_digest(offered, token)):
            await socket.close(code=1008)
            return
        await socket.accept()
        hub.add(socket)
        try:
            await socket.send_json({"kind": "hello", "root": str(root)})
            while True:
                # Nothing is expected from the client; this keeps the socket open and
                # notices when it goes away.
                await socket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.discard(socket)

    @app.get("/api/stats")
    def api_stats() -> dict:
        return {"clients": len(hub), "render_cache": cache_stats()}

    @app.get("/api/file")
    def api_file_read(path: str = Query(...)) -> dict:
        try:
            return vars(files.read(root, path))
        except FileAccessError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/file")
    def api_file_write(
        path: str = Query(...),
        text: str = Body(..., embed=True),
        if_match: str | None = Body(default=None, embed=True),
    ) -> dict:
        """Write a file. The watcher picks it up and every preview reloads."""
        try:
            return vars(files.write(root, path, text, if_match))
        except FileAccessError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ConflictError as exc:
            # 409 so the editor can offer to reload instead of overwriting silently
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/file/undo")
    def api_file_undo(path: str = Query(...)) -> dict:
        try:
            return vars(files.undo(root, path))
        except FileAccessError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/figure.svg")
    def api_figure() -> Response:
        """The final SVG with every panel composed."""
        spec = current_spec()
        try:
            result = build_figure(spec)
        except SpecError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            result.svg,
            media_type="image/svg+xml",
            headers={
                "X-Figalign-Errors": ",".join(sorted(result.errors)),
                "X-Figalign-Passes": str(result.passes),
                "X-Figalign-Converged": "1" if result.converged else "0",
            },
        )

    @app.get("/api/figure.pdf")
    def api_figure_pdf(text: str = Query(default="paths", pattern="^(paths|keep)$")) -> Response:
        """The deliverable. `text=keep` leaves the text as text instead of outlining it."""
        spec = current_spec()
        try:
            result = build_figure(spec, text_as_paths=(text == "paths"))
            pdf = to_pdf(result.svg)
        except SpecError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ExportError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return Response(
            pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'inline; filename="figure.pdf"',
                "X-Figalign-Errors": ",".join(sorted(result.errors)),
            },
        )

    @app.get("/api/panel/{name}.svg")
    def api_panel_svg(
        name: str,
        w: str | None = Query(default=None),
        h: str | None = Query(default=None),
    ) -> Response:
        spec = current_spec()
        size = resolve_size(spec, w, h)
        try:
            svg = draw(spec, name, size, as_pdf=False)
        except SpecError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PanelRenderError as exc:
            # spec 7.3: return the traceback instead of failing, and let the front end show it
            return PlainTextResponse(exc.traceback_text, status_code=422)
        except (FileNotFoundError, AttributeError, TypeError, ImportError) as exc:
            return PlainTextResponse(f"{type(exc).__name__}: {exc}", status_code=422)
        return Response(svg, media_type="image/svg+xml")

    @app.get("/api/panel/{name}.pdf")
    def api_panel_pdf(
        name: str,
        w: str | None = Query(default=None),
        h: str | None = Query(default=None),
    ) -> Response:
        spec = current_spec()
        size = resolve_size(spec, w, h)
        try:
            pdf = draw(spec, name, size, as_pdf=True)
        except SpecError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PanelRenderError as exc:
            return PlainTextResponse(exc.traceback_text, status_code=422)
        return Response(
            pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{name}.pdf"'},
        )

    return app


def _panel_info(spec: FigSpec, layout, name: str) -> dict:
    panel = spec.panels[name]
    info: dict[str, object] = {
        "name": name,
        "kind": panel.kind,
        "ref": panel.fn or panel.src,
        "box": vars(layout.boxes[name]),
        "inner": vars(layout.inner_box(name)),
    }
    if panel.fn:
        file, _, fn_name = panel.fn.partition(":")
        info["file"] = file
        info["line"] = files.definition_line(spec.root, file, fn_name)
    else:
        info["file"] = panel.src
        info["line"] = None
    return info


def _editable_files(spec: FigSpec) -> list[dict]:
    """Every file the tabs can open: the declaration, the panel modules, the assets."""
    seen: list[str] = [FIG_TOML]
    for panel in spec.panels.values():
        target = panel.fn.partition(":")[0] if panel.fn else panel.src
        if target and target not in seen:
            seen.append(target)
    if spec.data_ref:
        module = spec.data_ref.partition(":")[0]
        if module not in seen:
            seen.append(module)

    out = []
    for rel in seen:
        try:
            state = files.read(spec.root, rel)
        except (FileAccessError, FileNotFoundError):
            continue
        out.append({"path": rel, "digest": state.digest, "lines": state.text.count("\n") + 1})
    return out


def serve(
    root: Path, host: str = "127.0.0.1", port: int = 8765, token: str | None = None
) -> None:
    import uvicorn

    uvicorn.run(create_app(root, token=token), host=host, port=port, log_level="warning")
