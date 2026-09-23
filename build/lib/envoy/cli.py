"""The ``envoy`` command."""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import webbrowser

from . import __version__, db
from .config import Settings, data_dir


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .app import create_app

    settings = Settings.load()
    host = args.host or settings.host
    port = args.port or settings.port
    url = f"http://{host}:{port}"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Envoy {__version__} at {url}  (provider: {settings.provider}, data: {data_dir()})")
    uvicorn.run(create_app(settings), host=host, port=port, log_level="warning")


def _check(args: argparse.Namespace) -> None:
    from .models import build_model

    s = Settings.load()
    print(f"data dir : {data_dir()}")
    print(f"provider : {s.provider}")
    print(f"endpoint : {s.endpoint}")
    print(f"model    : {s.model}")
    m = build_model(s)
    if hasattr(m, "check"):
        r = m.check()
        if r["ok"] and r["has_model"]:
            print(f"status   : ok, endpoint reachable and '{s.model}' is available")
        elif r["ok"]:
            print(f"status   : endpoint reachable but '{s.model}' not listed. "
                  f"Available: {', '.join(r['models']) or '(none)'}")
        else:
            print(f"status   : cannot reach endpoint ({r['error']})")
    else:
        print("status   : stub provider (deterministic, offline). Point Envoy at a local "
              "model with: envoy config --provider openai --model <name>")


def _config(args: argparse.Namespace) -> None:
    s = Settings.load()
    for k in ("provider", "endpoint", "model", "user_name", "user_language"):
        v = getattr(args, k, None)
        if v is not None:
            setattr(s, k, v)
    s.save()
    print(json.dumps(s.public(), indent=2))


def _demo(args: argparse.Namespace) -> None:
    from .demo import SAMPLE_MESSAGES, seed_demo
    from .locales import seed_locales
    from .models import build_model
    from .pipeline import compose
    from .schemas import ComposeRequest
    from .tools import DirectTools

    s = Settings.load()
    con = db.connect(s.db_path)
    seed_locales(con)
    print("demo data:", seed_demo(con))
    msg = SAMPLE_MESSAGES[args.index]["text"]
    print(f"\nMessage:\n  {msg}\n")
    r = asyncio.run(compose(ComposeRequest(message=msg), settings=s, model=build_model(s),
                            tools=DirectTools(con), con=con))
    print(f"Locale: {r.locale.locale} ({r.locale.variety})   Status: {r.status.value}")
    print(f"\nWhat they said:\n  {r.reading.gloss}")
    print(f"\nReply:\n{r.final_text}")
    print(f"\nBack-translation:\n{r.back_translation}")
    if r.flags:
        print("\nFlags:")
        for f in r.flags:
            print(f"  [{f.severity}] {f.segment_id} {f.kind.value}: {f.reason}")


def main() -> None:
    p = argparse.ArgumentParser(prog="envoy", description="Reply to anyone in their language.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="start Envoy and open the browser (default)")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(func=_serve)

    c = sub.add_parser("check", help="verify the model endpoint and show configuration")
    c.set_defaults(func=_check)

    cfg = sub.add_parser("config", help="set provider, endpoint, model, your name")
    cfg.add_argument("--provider", choices=["stub", "openai"])
    cfg.add_argument("--endpoint")
    cfg.add_argument("--model")
    cfg.add_argument("--user-name", dest="user_name")
    cfg.add_argument("--user-language", dest="user_language")
    cfg.set_defaults(func=_config)

    d = sub.add_parser("demo", help="load demo data and run one sample message")
    d.add_argument("--index", type=int, default=0)
    d.set_defaults(func=_demo)

    args = p.parse_args()
    if args.cmd is None:
        args = p.parse_args(["serve"])
    args.func(args)


if __name__ == "__main__":
    main()
