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
};

function segTone(flags: Result["flags"]) {
  if (flags.some((f) => f.severity === "block")) return "border-rose-300 bg-rose-50/60 dark:border-rose-900 dark:bg-rose-950/30";
  if (flags.length) return "border-amber-300 bg-amber-50/60 dark:border-amber-900 dark:bg-amber-950/30";
  return "border-transparent";
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

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Sources behind each claim">
          {result.ledger.some((e) => e.source_ids.length) ? (
            <ul className="space-y-2 text-sm">
              {result.ledger.filter((e) => e.source_ids.length).map((e) => (
                <li key={e.segment_id}>
                  <span className="text-zinc-500">{e.segment_id}</span>
                  {e.source_ids.map((id) => {
                    const src = sourceById.get(id);
                    return (
                      <div key={id} className="mt-1 rounded-lg bg-zinc-50 p-2 dark:bg-zinc-800/60">
                        <div className="text-xs text-zinc-500">{src?.kind ?? "source"} · {String(src?.meta?.title ?? id)}</div>
                        <div className="text-zinc-700 dark:text-zinc-300">{src?.text ?? id}</div>
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
