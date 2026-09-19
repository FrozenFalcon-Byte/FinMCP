/* A small, safe Markdown renderer for assistant replies: paragraphs, headings, lists, code, tables, bold, inline code. */
import { Fragment, type ReactNode } from "react";

function inline(text: string, key = 0): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\n]+\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("`")) out.push(<code key={`${key}-${i++}`}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("**")) out.push(<strong key={`${key}-${i++}`}>{tok.slice(2, -2)}</strong>);
    else out.push(<em key={`${key}-${i++}`}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const isNumeric = (s: string) => /^[-+]?[\d,]+(\.\d+)?%?$/.test(s.trim()) || /^[₹$€£]\s?[\d,]+(\.\d+)?$/.test(s.trim());

function table(lines: string[], key: number): ReactNode {
  const rows = lines.filter((l) => !/^\|?\s*:?-{2,}/.test(l)).map((l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim()));
  if (!rows.length) return null;
  const [head, ...body] = rows;
  return (
    <table key={key}>
      <thead><tr>{head.map((c, i) => <th key={i}>{inline(c, i)}</th>)}</tr></thead>
      <tbody>
        {body.map((r, ri) => (
          <tr key={ri}>{r.map((c, ci) => <td key={ci} className={isNumeric(c) ? "num" : undefined}>{inline(c, ci)}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const nodes: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (line.startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++;
      nodes.push(<pre key={key++}><code>{buf.join("\n")}</code></pre>);
      continue;
    }
    if (/^\|/.test(line.trim()) || (line.includes("|") && i + 1 < lines.length && /^\|?\s*:?-{2,}/.test(lines[i + 1]))) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].includes("|")) buf.push(lines[i++]);
      nodes.push(<div key={key++} className="table-wrap">{table(buf, key)}</div>);
      continue;
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) { nodes.push(h[1].length === 1 ? <h1 key={key++}>{inline(h[2])}</h1> : h[1].length === 2 ? <h2 key={key++}>{inline(h[2])}</h2> : <h3 key={key++}>{inline(h[2])}</h3>); i++; continue; }
    if (/^\s*[-*•]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*•]\s+/, ""));
      nodes.push(<ul key={key++}>{items.map((it, n) => <li key={n}>{inline(it, n)}</li>)}</ul>);
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+[.)]\s+/, ""));
      nodes.push(<ol key={key++}>{items.map((it, n) => <li key={n}>{inline(it, n)}</li>)}</ol>);
      continue;
    }
    const buf: string[] = [];
    while (i < lines.length && lines[i].trim() && !lines[i].startsWith("```") && !/^(#{1,3})\s/.test(lines[i]) && !/^\s*[-*•]\s+/.test(lines[i]) && !/^\s*\d+[.)]\s+/.test(lines[i]) && !/^\|/.test(lines[i].trim())) buf.push(lines[i++]);
    nodes.push(<p key={key++}>{buf.map((b, n) => <Fragment key={n}>{inline(b, n)}{n < buf.length - 1 ? <br /> : null}</Fragment>)}</p>);
  }
  return <div className="md">{nodes}</div>;
}
