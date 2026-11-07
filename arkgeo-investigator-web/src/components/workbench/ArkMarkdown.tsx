import type { ReactNode } from 'react';

/** Safe, dependency-free presentation for ARK's plain-text Markdown responses.
 * Text is rendered as React text nodes, never as untrusted HTML. */
function inline(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const tokens = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g;
  let last = 0;
  for (const match of text.matchAll(tokens)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(text.slice(last, index));
    const value = match[0];
    const key = parts.length;
    if (value.startsWith('`')) parts.push(<code key={key}>{value.slice(1, -1)}</code>);
    else if (value.startsWith('**') || value.startsWith('__')) parts.push(<strong key={key}>{value.slice(2, -2)}</strong>);
    else if (value.startsWith('*')) parts.push(<em key={key}>{value.slice(1, -1)}</em>);
    else {
      const split = value.indexOf('](');
      const label = value.slice(1, split);
      const url = value.slice(split + 2, -1);
      parts.push(<a key={key} href={url} target="_blank" rel="noopener noreferrer">{label}</a>);
    }
    last = index + value.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export function ArkMarkdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const nodes: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const fence = /^\s*```([^\s`]*)/.exec(line);
    if (fence) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
      if (i < lines.length) i++;
      nodes.push(<pre key={nodes.length}><code>{code.join('\n')}</code></pre>);
      continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const content = inline(heading[2]);
      nodes.push(level === 1 ? <h3 key={nodes.length}>{content}</h3> : <h4 key={nodes.length}>{content}</h4>);
      i++; continue;
    }
    if (/^\s*---+\s*$/.test(line)) { nodes.push(<hr key={nodes.length} />); i++; continue; }
    const bullet = /^\s*[-*+]\s+/.test(line);
    const ordered = /^\s*\d+[.)]\s+/.test(line);
    if (bullet || ordered) {
      const items: ReactNode[] = [];
      const pattern = bullet ? /^\s*[-*+]\s+/ : /^\s*\d+[.)]\s+/;
      while (i < lines.length && pattern.test(lines[i])) {
        items.push(<li key={items.length}>{inline(lines[i].replace(pattern, ''))}</li>);
        i++;
      }
      nodes.push(bullet ? <ul key={nodes.length}>{items}</ul> : <ol key={nodes.length}>{items}</ol>);
      continue;
    }
    const paragraph: string[] = [line];
    i++;
    while (i < lines.length && lines[i].trim()
      && !/^\s*(?:```|#{1,4}\s|[-*+]\s|\d+[.)]\s|---+\s*$)/.test(lines[i])) {
      paragraph.push(lines[i++]);
    }
    nodes.push(<p key={nodes.length}>{paragraph.map((part, j) => (
      <span key={j}>{j > 0 && <br />}{inline(part)}</span>
    ))}</p>);
  }
  return <div className="ark-markdown">{nodes}</div>;
}
