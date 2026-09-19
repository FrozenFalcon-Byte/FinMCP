import { useCallback, useEffect, useRef, useState } from "react";
import { useToast } from "../components/Toast";
import { Chip, Empty, ErrorBox, Icon, PageHead, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { dateLabel, money, num, relTime } from "../lib/format";
import { useLedger } from "../lib/ledger";
import { useStatus } from "../lib/status";
import type { ImportPreview, ImportRecord, ImportReport } from "../lib/types";

const KINDS = [
  { value: "auto", label: "Detect from file" },
  { value: "statement", label: "Bank statement PDF" },
  { value: "csv", label: "CSV export" },
  { value: "receipt", label: "Receipt photo" },
  { value: "sms", label: "SMS alerts (text)" },
];

function Stat({ k, v, tone }: { k: string; v: string; tone?: "accent" | "" }) {
  return <div className={`mini ${tone ?? ""}`}><div className="k">{k}</div><div className="v num">{v}</div></div>;
}

export default function Import() {
  const { currency } = useStatus();
  const { bump } = useLedger();
  const toast = useToast();
  const [kind, setKind] = useState("auto");
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [textKind, setTextKind] = useState<"sms" | "csv">("sms");
  const [recent, setRecent] = useState<ImportRecord[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadRecent = useCallback(() => api.get<ImportRecord[]>("/imports").then(setRecent).catch(() => undefined), []);
  useEffect(() => { void loadRecent(); }, [loadRecent]);

  const onFile = async (file: File) => {
    setBusy(true); setError(null); setReport(null); setPreview(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("kind", kind);
      setPreview(await api.upload<ImportPreview>("/import/preview", form));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const commit = async () => {
    if (!preview?.upload_path) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("upload_path", preview.upload_path);
      form.append("kind", kind);
      const r = await api.upload<ImportReport>("/import", form);
      setReport(r); setPreview(null);
      toast(`Imported ${r.inserted} new, skipped ${r.duplicates} duplicates.`);
      bump(); void loadRecent();
    } catch (e) { toast(e instanceof Error ? e.message : String(e), "err"); } finally { setBusy(false); }
  };
  const runText = async (dry: boolean) => {
    if (text.trim().length < 10) return;
    setBusy(true); setError(null);
    try {
      const r = await api.post<ImportReport & ImportPreview>("/import/text", { text, kind: textKind, dry_run: dry, source_name: dry ? undefined : `pasted ${textKind}` });
      if (dry) { setReport(null); setPreview({ ...r, upload_path: undefined }); }
      else { setPreview(null); setReport(r); setText(""); toast(`Imported ${r.inserted} new, ${r.duplicates} duplicates.`); bump(); void loadRecent(); }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const drop = (e: React.DragEvent) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files?.[0]; if (f) void onFile(f); };

  return (
    <>
      <PageHead title="Import" sub="Statements, receipts and SMS alerts become transactions. Duplicates are skipped by fingerprint.">{busy ? <Spinner /> : null}</PageHead>
      <div className="grid two">
        <div className="stack">
          <section className="card">
            <div className="card-head"><h2>Upload a file</h2>
              <select className="select" style={{ width: "auto", height: 38 }} value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}</select>
            </div>
            <div className={`drop ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop} onClick={() => fileRef.current?.click()} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && fileRef.current?.click()}>
              <div className="ic"><Icon name="upload" /></div>
              <div className="strong">Drop a file here</div>
              <div className="small muted">or click to choose · PDF statement, CSV export, receipt photo, SMS dump</div>
              <input ref={fileRef} type="file" hidden accept=".pdf,.csv,.tsv,.png,.jpg,.jpeg,.webp,.txt" onChange={(e) => { const f = e.target.files?.[0]; if (f) void onFile(f); e.target.value = ""; }} />
            </div>
            <p className="small muted" style={{ marginTop: 10 }}>Samples live in <code className="mono">fixtures/</code>: statement_sample.pdf, statement_sample.csv, receipt_sample.png, sms_sample.txt.</p>
          </section>
          <section className="card">
            <div className="card-head"><h2>Paste text</h2>
              <div className="tabs"><button className={textKind === "sms" ? "on" : ""} onClick={() => setTextKind("sms")}>SMS alerts</button><button className={textKind === "csv" ? "on" : ""} onClick={() => setTextKind("csv")}>CSV rows</button></div>
            </div>
            <textarea className="textarea" rows={7} placeholder={textKind === "sms" ? "Rs.450.00 debited from a/c **4321 on 12-09-26 to VPA swiggy@ybl (UPI Ref No 4263...)…" : "Date,Narration,Withdrawal Amt.,Deposit Amt.,Closing Balance\n12/09/2026,UPI/SWIGGY/…,450.00,,1,97,063.30"} value={text} onChange={(e) => setText(e.target.value)} />
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn" onClick={() => void runText(true)} disabled={busy || text.trim().length < 10}>Preview</button>
              <button className="btn primary" onClick={() => void runText(false)} disabled={busy || text.trim().length < 10}>Import</button>
            </div>
          </section>
        </div>
        <div className="stack">
          {error ? <ErrorBox>{error}</ErrorBox> : null}
          {preview ? (
            <section className="card">
              <div className="card-head"><h2>Preview · {preview.source_name ?? "pasted text"}</h2><span className="meta">{preview.parser}</span></div>
              <div className="mini-stats" style={{ marginTop: 0, marginBottom: 12, gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}>
                <Stat k="Parsed" v={num(preview.parsed)} />
                <Stat k="New" v={num(preview.new)} tone="accent" />
                <Stat k="Duplicates" v={num(preview.duplicates)} />
                <Stat k="Skipped" v={num(preview.skipped.length)} />
              </div>
              {preview.warnings.length ? <div className="chips" style={{ marginBottom: 10 }}>{preview.warnings.map((w, i) => <Chip key={i} tone="warn">{w}</Chip>)}</div> : null}
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Date</th><th>Merchant</th><th className="num">Amount</th><th></th></tr></thead>
                  <tbody>
                    {preview.transactions.map((t, i) => (
                      <tr key={i} className={t.duplicate ? "dup" : ""}>
                        <td className="num">{dateLabel(t.date, { day: "2-digit", month: "short", year: "2-digit" })}</td>
                        <td><div className="strong">{t.merchant}</div>{t.description ? <div className="micro muted ellipsis" style={{ maxWidth: 220 }} title={t.description}>{t.description}</div> : null}</td>
                        <td className={`num ${t.direction === "credit" ? "strong" : ""}`} style={t.direction === "credit" ? { color: "var(--good)" } : undefined}>{t.direction === "credit" ? "+" : ""}{money(t.amount, currency, 2)}</td>
                        <td>{t.duplicate ? <Chip>duplicate</Chip> : t.confidence < 0.7 ? <Chip tone="warn">review</Chip> : null}{t.line_items?.length ? <Chip title={t.line_items.map((li) => `${li.name} ${li.total ?? ""}`).join("\n")}>{t.line_items.length} items</Chip> : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!preview.transactions.length ? <Empty>Nothing parsable was found. {preview.skipped[0] ?? ""}</Empty> : null}
              </div>
              {preview.skipped.length ? <details style={{ marginTop: 8 }}><summary className="small muted">{preview.skipped.length} skipped lines</summary><ul className="small muted">{preview.skipped.map((s, i) => <li key={i}>{s}</li>)}</ul></details> : null}
              {preview.upload_path ? (
                <div className="row" style={{ marginTop: 12 }}>
                  <button className="btn primary" onClick={() => void commit()} disabled={busy || !preview.new}>Import {preview.new} new</button>
                  <button className="btn" onClick={() => setPreview(null)}>Discard</button>
                </div>
              ) : <p className="small muted" style={{ marginTop: 10 }}>Use the Import button under the text box to commit.</p>}
            </section>
          ) : null}
          {report ? (
            <section className="card">
              <div className="card-head"><h2>Imported · {report.source_name ?? "pasted text"}</h2><span className="meta">{report.parser}</span></div>
              <div className="mini-stats" style={{ marginTop: 0, marginBottom: 12, gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}>
                <Stat k="Inserted" v={num(report.inserted)} tone="accent" />
                <Stat k="Categorised" v={num(report.categorized)} />
                <Stat k="Needs review" v={num(report.needs_review)} />
                <Stat k="Duplicates" v={num(report.duplicates)} />
              </div>
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th className="num">Amount</th></tr></thead>
                  <tbody>
                    {report.transactions.map((t) => (
                      <tr key={t.id}><td className="num">{dateLabel(t.date, { day: "2-digit", month: "short", year: "2-digit" })}</td><td className="strong">{t.merchant}</td><td>{t.category ?? <Chip tone="warn">uncategorized</Chip>}</td><td className="num">{t.direction === "credit" ? "+" : ""}{money(t.amount, currency, 2)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}
          <section className="card">
            <div className="card-head"><h2>Recent imports</h2></div>
            {recent.length ? (
              <div className="list">
                {recent.map((r) => <div className="item" key={r.id}><div className="grow"><div className="t">{r.source_name ?? r.source_kind} <Chip>{r.source_kind}</Chip></div><div className="s">{relTime(r.ts)} · {r.parsed} parsed · {r.inserted} inserted · {r.duplicates} duplicates</div></div></div>)}
              </div>
            ) : <Empty>No imports yet.</Empty>}
          </section>
        </div>
      </div>
    </>
  );
}
