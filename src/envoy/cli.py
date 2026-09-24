"""The ``envoy`` command."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
import urllib.request
import webbrowser

from . import __version__, db
from .config import Settings, data_dir


def _open_when_ready(url: str, timeout: float = 30.0) -> None:
    """Open the browser once the server (and its MCP servers) answer."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1) as r:
                if r.status == 200:
                    break
        except Exception:  # noqa: BLE001 - not up yet
            time.sleep(0.25)
    webbrowser.open(url)


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .app import create_app

    settings = Settings.load()
    host = args.host or settings.host
    port = args.port or settings.port
    url = f"http://{host}:{port}"
    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
    print(f"Envoy {__version__} at {url}  (provider: {settings.provider}, data: {data_dir()})")
    uvicorn.run(create_app(settings), host=host, port=port, log_level="warning")


def _check(args: argparse.Namespace) -> None:
    from .models import build_model

    s = Settings.load()
    print(f"data dir : {data_dir()}")
    print(f"provider : {s.provider}")
    print(f"endpoint : {s.endpoint}")
    print(f"model    : {s.model}")
    from .memory.embed import build_embedder

    print(f"memory   : embeddings by {build_embedder(s).name}")
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
        print("status   : stub provider (deterministic, offline). Use a real model with: "
              "envoy config --provider cohere --model <name> --api-key <key>  "
              "or  envoy config --provider openai --model <name>")


def _eval(args: argparse.Namespace) -> None:
    from .eval import main_eval

    models = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else None
    indexes = None
    if args.indexes:
        indexes = []
        for part in args.indexes.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                indexes.extend(range(int(a), int(b) + 1))
            elif part:
                indexes.append(int(part))
    raise SystemExit(main_eval(Settings.load(), models, indexes, args.out, args.set,
                               args.perturb, args.critic_model, args.report))


def _dialect(args: argparse.Namespace) -> None:
    from pathlib import Path

    from .evalx.dialect import NgramModel, discover, read_corpus

    if args.action == "train":
        src = Path(args.data)
        if not src.exists():
            print(f"no such file or directory: {src}")
            raise SystemExit(2)
        model = NgramModel(args.language).train(read_corpus(src))
        if not model.labels:
            print("no labelled lines found; expected 'text<TAB>label' lines or one file per label")
            raise SystemExit(2)
        out = Path(args.out) if args.out \
            else data_dir() / "models" / f"dialect-{args.language}.json"
        model.save(out)
        print(f"trained {args.language} dialect model on {sum(model.docs.values())} lines: "
              + ", ".join(f"{k} ({v})" for k, v in sorted(model.docs.items())))
        print(f"saved to {out}; envoy eval will use it for {args.language} samples")
        return
    scorers = discover(data_dir())
    if args.action == "list":
        if not scorers:
            print("no dialect scorers available. Train one with: envoy dialect train "
                  "--language pt --data <DSLCC dir>; for Arabic, pip install camel-tools "
                  "and camel_data -i dialectid")
        for lang, sc in sorted(scorers.items()):
            print(f"{lang}: {sc.name}")
        return
    sc = scorers.get(args.language)
    if sc is None:
        print(f"no dialect scorer for {args.language!r}; run 'envoy dialect list'")
        raise SystemExit(2)
    for text in args.text:
        print(f"{sc.predict(text) or '?'}\t{text}")


def _bench(args: argparse.Namespace) -> None:
    """Public-dataset benchmarks of single stages: the Reader on MASSIVE, the
    Critic's back-translation on FLORES-200."""
    from pathlib import Path

    from .evalx import flores, massive

    settings = Settings.load()
    data = Path(args.data)
    if not data.exists():
        print(f"no such directory: {data}")
        raise SystemExit(2)
    models = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else None
    languages = [x.strip() for x in args.languages.split(",") if x.strip()] \
        if args.languages else None
    if args.critic_model:
        settings.role_models = {**settings.role_models, "critic": args.critic_model}
    doc: dict = {}
    if args.dataset == "massive":
        def live(r):
            state = "ERROR" if r.error else ("ok" if r.language_ok else "lang?")
            print(f"  [{r.model}] {r.language} {r.id}: {state}, slots "
                  f"{r.slots_lenient}/{r.slots} ({r.seconds}s)", flush=True)

        print(f"Envoy bench massive  data={data}  n={args.n}/language  "
              f"provider={settings.provider}")
        rows = asyncio.run(massive.run_massive(settings, data, languages, args.n, models,
                                               on_row=live))
        if not rows:
            print("no utterances found; expected data/<locale>.jsonl files from MASSIVE 1.1")
            raise SystemExit(2)
        print(massive.render_massive(rows))
        doc = {"massive": massive.massive_to_dicts(rows)}
    else:
        def live_f(r):
            state = "ERROR" if r.error else f"chrF {r.chrf}"
            print(f"  [{r.model}] {r.language} #{r.index}: {state} ({r.seconds}s)", flush=True)

        print(f"Envoy bench flores  data={data}  n={args.n}/language  "
              f"provider={settings.provider}")
        rows = asyncio.run(flores.run_flores(settings, data, languages, args.n, models,
                                             on_row=live_f))
        if not rows:
            print("no sentences found; expected devtest/<code>.devtest files from FLORES-200")
            raise SystemExit(2)
        print(flores.render_flores(rows))
        doc = {"flores": flores.flores_to_dicts(rows)}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f"\nWrote {args.out}")


def _report(args: argparse.Namespace) -> None:
    from pathlib import Path

    from . import report

    text = report.render(report.load_docs(args.files), title=args.title)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)


def _study(args: argparse.Namespace) -> None:
    from pathlib import Path

    from . import study

    if args.action == "export":
        runs: list[dict] = []
        for f in args.source or []:
            doc = json.loads(Path(f).read_text(encoding="utf-8"))
            runs += doc.get("runs", doc if isinstance(doc, list) else [])
        if not runs:
            print("nothing to export: pass --from eval.json (from 'envoy eval --out'), "
                  "one or more times")
            raise SystemExit(2)
        items = study.build_items(runs, seed=args.seed)
        if not items:
            print("no comparable items: every draft equals its final, and only one model ran")
            raise SystemExit(2)
        paths = study.export(items, Path(args.out))
        kinds = {}
        for it in items:
            kinds[it.kind] = kinds.get(it.kind, 0) + 1
        print(f"{len(items)} blind items ({', '.join(f'{v} {k}' for k, v in kinds.items())}) "
              f"across {len(paths) - 1} locale sheets in {args.out}")
        print("Give raters the sheets and docs/RUBRIC.md; keep key.json to yourself.")
        return
    report = study.score(Path(args.sheets))
    print(study.render_report(report))
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"\nWrote {args.out}")


def _config(args: argparse.Namespace) -> None:
    s = Settings.load()
    for k in ("provider", "endpoint", "model", "api_key", "user_name", "user_email",
              "user_language", "embed_model"):
        v = getattr(args, k, None)
        if v is not None:
            setattr(s, k, v)
    s.save()
    print(json.dumps(s.public(), indent=2))


def _import(args: argparse.Namespace) -> None:
    from .memory import import_paths

    s = Settings.load()
    con = db.connect(s.db_path)
    mine = set(s.my_addresses) | {a.strip().lower() for a in (args.me or "").split(",")
                                  if a.strip()}
    if not mine:
        print("Tip: pass --me you@example.com (or envoy config --user-email) so Envoy knows "
              "which messages you wrote.")

    def progress(path, report):
        print(f"  {path}: {report.messages} message(s), {report.documents} document(s) so far",
              flush=True)

    report = import_paths(con, args.paths, mine, on_file=progress)
    print(report.summary())
    for line in report.skipped[:20]:
        print(f"  skipped {line}")
    counts = db.message_count(con)
    print(f"Memory now holds {counts['messages']} message(s), {counts['mine']} written by you.")
    if not args.no_index:
        _run_index(s, con)
    if args.extract:
        _extract(argparse.Namespace(limit=100000))


def _run_index(s: Settings, con) -> None:
    from .memory.embed import build_embedder
    from .memory.index import index_all
    from .models.base import ModelError

    emb = build_embedder(s)
    print(f"Indexing with {emb.name} …", flush=True)
    try:
        done = index_all(con, emb, on_progress=lambda kind, n, total: print(
            f"  {kind}: {n}/{total}", flush=True) if n == total or n % 256 == 0 else None)
    except ModelError as e:
        print(f"indexing failed: {e}")
        print("Search still works on words alone; run `envoy index` once the model is reachable.")
        return
    print(f"Indexed {done['mail']} mail paragraph(s) and {done['knowledge']} knowledge "
          f"paragraph(s); vectors stored: {db.embedding_count(con)}")


def _extract(args: argparse.Namespace) -> None:
    from .memory.facts import extract_pending_sync
    from .models import build_model

    s = Settings.load()
    con = db.connect(s.db_path)
    pending = len(db.messages_unextracted(con, args.limit))
    print(f"Extracting facts from {pending} message(s) with {s.provider}:{s.model} …",
          flush=True)
    report = extract_pending_sync(
        con, build_model(s), args.limit,
        on_message=lambda m, n: print(f"  {(m['date'] or '')[:10]} {m['subject'][:50]!r}: "
                                      f"{n} fact(s)", flush=True))
    counts = db.fact_count(con)
    print(f"{report.messages} message(s) read, {report.facts} fact(s) stored, "
          f"{report.failed} failed. Memory holds {counts['facts']} fact(s) "
          f"({counts['confirmed']} confirmed).")


def _index(args: argparse.Namespace) -> None:
    s = Settings.load()
    _run_index(s, db.connect(s.db_path))


def _demo(args: argparse.Namespace) -> None:
    from .demo import SAMPLE_MESSAGES, seed_demo
    from .locales import seed_locales
    from .models import build_model
    from .pipeline import PipelineError, compose
    from .schemas import ComposeRequest
    from .tools import DirectTools

    s = Settings.load()
    con = db.connect(s.db_path)
    seed_locales(con)
    print(f"Envoy {__version__}  provider={s.provider} model={s.model}")
    print("demo data:", seed_demo(con))
    msg = SAMPLE_MESSAGES[args.index]["text"]
    print(f"\nMessage:\n  {msg}\n")
    try:
        r = asyncio.run(compose(ComposeRequest(message=msg), settings=s, model=build_model(s),
                                tools=DirectTools(con), con=con))
    except PipelineError as e:
        print(f"Envoy could not run this message: {e}")
        if "401" in str(e) or "API key" in str(e):
            print("Fix: envoy config --api-key \"<your key>\"  (from your provider's dashboard)")
        raise SystemExit(1) from None
    print(f"Locale: {r.locale.locale} ({r.locale.variety})   Status: {r.status.value}")
    print(f"\nWhat they said:\n  {r.reading.gloss}")
    print(f"\nReply:\n{r.final_text}")
    print(f"\nBack-translation:\n{r.back_translation}")
    if r.flags:
        print("\nFlags:")
        for f in r.flags:
            print(f"  [{f.severity}] {f.segment_id} {f.kind.value}: {f.reason}")
    if r.stage_errors:
        print("\nStage errors:")
        for e in r.stage_errors:
            print(f"  {e}")
    if r.suggestions:
        print("\nSuggestions (do not affect status):")
        for sg in r.suggestions:
            print(f"  {sg.segment_id}: {sg.suggestion}")


def main() -> None:
    # Windows consoles default to a legacy code page; Envoy prints Arabic, Japanese, accents.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
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
    cfg.add_argument("--provider", choices=["stub", "openai", "cohere"])
    cfg.add_argument("--endpoint")
    cfg.add_argument("--model")
    cfg.add_argument("--api-key", dest="api_key", help="for hosted OpenAI-compatible endpoints")
    cfg.add_argument("--user-name", dest="user_name")
    cfg.add_argument("--user-email", dest="user_email",
                     help="your address(es), comma-separated: marks the mail you wrote")
    cfg.add_argument("--embed-model", dest="embed_model",
                     help="embedding model for memory search (see docs/MEMORY.md)")
    cfg.add_argument("--user-language", dest="user_language")
    cfg.set_defaults(func=_config)

    ev = sub.add_parser("eval", help="run a sample set through one or more models and score it")
    ev.add_argument("--set", default="demo", choices=["demo", "heldout", "injection", "all"],
                    help="demo (tuned on), heldout (never tuned on), injection (attacks), all")
    ev.add_argument("--models", help="comma-separated model names to compare (default: configured)")
    ev.add_argument("--critic-model", dest="critic_model",
                    help="judge with a different model than the one that drafts")
    ev.add_argument("--indexes", help="which samples of the set, e.g. 0-6 or 1,6 (default: all)")
    ev.add_argument("--perturb", action="store_true",
                    help="also plant known faults in every run and score what the verifier catches")
    ev.add_argument("--out", help="write full results as JSON to this file")
    ev.add_argument("--report", help="also write this run's tables as markdown to this file")
    ev.set_defaults(func=_eval)

    b = sub.add_parser("bench", help="score one stage against a public dataset: the Reader on "
                                     "MASSIVE, the Critic's back-translation on FLORES-200")
    b.add_argument("dataset", choices=["massive", "flores"])
    b.add_argument("--data", required=True, help="unpacked dataset directory")
    b.add_argument("--n", type=int, default=50, help="sentences per language (default 50)")
    b.add_argument("--languages", help="comma-separated ISO codes (default: all supported)")
    b.add_argument("--models", help="comma-separated model names to compare")
    b.add_argument("--critic-model", dest="critic_model", help="flores: the model that judges")
    b.add_argument("--out", help="write full results as JSON to this file")
    b.set_defaults(func=_bench)

    rp = sub.add_parser("report", help="one markdown report from eval, bench and study JSON")
    rp.add_argument("files", nargs="+", help="JSON written by envoy eval/bench/study --out")
    rp.add_argument("--out", help="markdown file to write (default: print)")
    rp.add_argument("--title", default="Envoy evaluation report")
    rp.set_defaults(func=_report)

    st = sub.add_parser("study", help="blind pairwise sheets for native readers, and their "
                                      "scores")
    st.add_argument("action", choices=["export", "score"])
    st.add_argument("--from", dest="source", action="append",
                    help="export: eval JSON from 'envoy eval --out' (repeatable)")
    st.add_argument("--out", help="export: directory for the sheets; score: JSON report path")
    st.add_argument("--seed", type=int, default=7, help="export: order and side randomization")
    st.add_argument("--sheets", help="score: directory holding filled sheets and key.json")
    st.set_defaults(func=_study)

    dl = sub.add_parser("dialect", help="train or query the dialect identifiers that score "
                                        "the Rewriter")
    dl.add_argument("action", choices=["train", "check", "list"])
    dl.add_argument("--language", default="pt", help="ISO 639-1 code the model is for")
    dl.add_argument("--data", help="train: a labelled file or directory (DSLCC, MADAR, ...)")
    dl.add_argument("--out", help="train: where to save (default: <data dir>/models/)")
    dl.add_argument("--text", action="append", default=[],
                    help="check: text to classify (repeatable)")
    dl.set_defaults(func=_dialect)

    im = sub.add_parser("import", help="import past mail (mbox, .eml) and documents (md, txt, "
                                       "pdf) into Envoy's memory")
    im.add_argument("paths", nargs="+", help="files or folders; folders are searched recursively")
    im.add_argument("--me", help="your address(es), comma-separated, in addition to settings")
    im.add_argument("--no-index", dest="no_index", action="store_true",
                    help="skip embedding after the import")
    im.set_defaults(func=_import)

    im.add_argument("--extract", action="store_true",
                    help="also extract dated facts from the imported mail (one model call "
                         "per message)")

    ix = sub.add_parser("index", help="embed imported mail and knowledge for cross-lingual search")
    ix.set_defaults(func=_index)

    ex = sub.add_parser("extract", help="extract dated facts (policies, prices, deadlines) from "
                                        "mail that has not been read yet")
    ex.add_argument("--limit", type=int, default=1000)
    ex.set_defaults(func=_extract)

    d = sub.add_parser("demo", help="load demo data and run one sample message")
    d.add_argument("--index", type=int, default=0)
    d.set_defaults(func=_demo)

    args = p.parse_args()
    if args.cmd is None:
        args = p.parse_args(["serve"])
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
