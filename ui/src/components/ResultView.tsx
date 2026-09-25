import { useState } from "react";
import { AlertTriangle, Check, Copy, ShieldAlert, ShieldCheck } from "lucide-react";
import type { Result } from "../api";
import { Badge, Button, Card } from "./ui";

const STATUS = {
  ready: { label: "Ready to send", tone: "green" as const, Icon: ShieldCheck },
  check: { label: "Check the warnings", tone: "amber" as const, Icon: AlertTriangle },
  escalate: { label: "Needs your attention", tone: "red" as const, Icon: ShieldAlert },
};

const KIND_LABEL: Record<string, string> = {
  drifted: "Meaning drifted",
  tone_off: "Tone off",
  cultural_risk: "Cultural risk",
  off_glossary: "Glossary broken",
  unsupported_claim: "Unsupported claim",
  missing_item: "Segment missing",
  stage_failure: "Stage failed",
  conflicting_sources: "Sources disagree (newest used)",
  stale_source: "Older statement used",
};

const SOURCE_KIND: Record<string, { label: string; tone: "zinc" | "green" | "amber" | "red" | "indigo" }> = {
  knowledge: { label: "knowledge base", tone: "indigo" },
  glossary: { label: "glossary", tone: "indigo" },
  mail: { label: "your mail", tone: "green" },
  fact: { label: "remembered fact", tone: "green" },
  history: { label: "past reply", tone: "zinc" },
  thread: { label: "this thread", tone: "zinc" },
};

function sourceLine(src: { kind: string; meta: Record<string, unknown> } | undefined, id: string) {
  if (!src) return id;
  const m = src.meta;
  if (src.kind === "mail" || src.kind === "fact") {
    const said = String(m.said ?? "");
    const status = m.status === "confirmed" ? " · confirmed" : "";
    return `${said}${status}`;
  }
  if (src.kind === "knowledge") return String(m.title ?? "document");
  if (src.kind === "thread") return `exchange on ${String(m.created_at ?? "").slice(0, 10)}`;
  if (src.kind === "history") return `reply in ${String(m.locale ?? "")}`;
  return id;
}

function segTone(flags: Result["flags"]) {
  if (flags.some((f) => f.severity === "block")) return "border-rose-300 bg-rose-50/60 dark:border-rose-900 dark:bg-rose-950/30";
  if (flags.length) return "border-amber-300 bg-amber-50/60 dark:border-amber-900 dark:bg-amber-950/30";
  return "border-transparent";
}

function citedSummary(result: Result, sourceById: Map<string, Result["sources"][number]>) {
  const counts: Record<string, number> = {};
  const seen = new Set<string>();
  for (const e of result.ledger) for (const id of e.source_ids) {
    if (seen.has(id)) continue;
    seen.add(id);
    const k = sourceById.get(id)?.kind ?? "source";
    counts[k] = (counts[k] ?? 0) + 1;
  }
  const parts = Object.entries(counts).map(([k, n]) => `${n} from ${SOURCE_KIND[k]?.label ?? k}`);
  return parts.length ? <span className="text-xs text-zinc-500" data-testid="cited-summary">{parts.join(" · ")}</span> : null;
}

export default function ResultView({ result }: { result: Result }) {
  const [copied, setCopied] = useState(false);
  const s = STATUS[result.status];
  const sourceById = new Map(result.sources.map((x) => [x.id, x]));

  const copy = async () => {
    await navigator.clipboard.writeText(result.final_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="space-y-4" data-testid="result">
      <div className="flex flex-wrap items-center gap-3">
        <Badge tone={s.tone}><s.Icon className="mr-1 h-3.5 w-3.5" />{s.label}</Badge>
        <Badge tone="indigo">{result.locale.variety} · {result.locale.locale}</Badge>
        {result.revisions > 0 && <Badge>revised once after review</Badge>}
        <span className="text-xs text-zinc-500">model: {result.model}</span>
        <div className="ml-auto">
          <Button onClick={copy} kind="ghost">{copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}{copied ? "Copied" : "Copy reply"}</Button>
        </div>
      </div>

      <Card title="What they said">
        <p className="text-sm leading-relaxed">{result.reading.gloss}</p>
        {result.reading.must_preserve.length > 0 && (
          <p className="mt-2 text-xs text-zinc-500">Must keep exactly: {result.reading.must_preserve.map((m) => <code key={m} className="mx-0.5 rounded bg-zinc-100 px-1 dark:bg-zinc-800">{m}</code>)}</p>
        )}
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title={`Reply · ${result.locale.variety}`}>
          <div dir={result.locale.rtl ? "rtl" : "ltr"} className="space-y-2" data-testid="final">
            {result.ledger.map((e) => (
              <p key={e.segment_id} dir="auto" className={`whitespace-pre-wrap rounded-lg border px-2 py-1 text-[15px] leading-relaxed ${segTone(e.flags)}`}>
                {e.final_text}
              </p>
            ))}
          </div>
        </Card>
        <Card title="Back-translation · what a native reader gets">
          <div className="space-y-2" data-testid="back">
            {result.ledger.map((e) => (
              <p key={e.segment_id} dir="auto" className={`whitespace-pre-wrap rounded-lg border px-2 py-1 text-[15px] leading-relaxed text-zinc-700 dark:text-zinc-300 ${segTone(e.flags)}`}>
                {e.back_translation || <span className="text-zinc-400">—</span>}
              </p>
            ))}
          </div>
        </Card>
      </div>

      {result.flags.length > 0 && (
        <Card title="Flags">
          <ul className="space-y-2">
            {result.flags.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <Badge tone={f.severity === "block" ? "red" : "amber"}>{KIND_LABEL[f.kind] ?? f.kind}</Badge>
                <span><span className="text-zinc-500">{f.segment_id}</span> {f.reason}{f.span && <> · <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">{f.span}</code></>}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {result.stage_errors.length > 0 && (
        <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          A stage failed, so this reply is unverified. Read it yourself before sending. Details: {result.stage_errors.join("; ")}
        </p>
      )}

      {(result.suggestions ?? []).length > 0 && (
        <Card title="Suggestions from the native reader · optional, do not affect status">
          <ul className="space-y-1 text-sm text-zinc-600 dark:text-zinc-300">
            {result.suggestions.map((s, i) => (
              <li key={i}><span className="text-zinc-400">{s.segment_id}</span> {s.suggestion}</li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Sources behind each claim" action={citedSummary(result, sourceById)}>
          {result.ledger.some((e) => e.source_ids.length) ? (
            <ul className="space-y-2 text-sm" data-testid="sources">
              {result.ledger.filter((e) => e.source_ids.length).map((e) => (
                <li key={e.segment_id}>
                  <span className="text-zinc-500">{e.segment_id}</span>
                  {e.source_ids.map((id) => {
                    const src = sourceById.get(id);
                    const kind = SOURCE_KIND[src?.kind ?? ""] ?? { label: src?.kind ?? "source", tone: "zinc" as const };
                    return (
                      <div key={id} className="mt-1 rounded-lg bg-zinc-50 p-2 dark:bg-zinc-800/60">
                        <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500"><Badge tone={kind.tone}>{kind.label}</Badge><span>{sourceLine(src, id)}</span></div>
                        <div className="mt-1 text-zinc-700 dark:text-zinc-300">{src?.text ?? id}</div>
                      </div>
                    );
                  })}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-zinc-500">No factual claims were made, so nothing needed a source.</p>
          )}
        </Card>
        <Card title="What the local editor changed">
          {result.rewrite.changes.length ? (
            <ul className="space-y-1 text-sm">
              {result.rewrite.changes.map((c, i) => (
                <li key={i}><Badge>{c.kind}</Badge> <span className="text-zinc-500">{c.segment_id}</span> {c.note}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-zinc-500">No changes.</p>
          )}
        </Card>
      </div>
    </div>
  );
}
