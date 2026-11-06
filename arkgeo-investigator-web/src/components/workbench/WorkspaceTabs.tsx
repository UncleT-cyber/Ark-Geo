import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';

interface Tab<Id extends string> {
  id: Id;
  label: string;
  hint: string;
}

export function WorkspaceTabs<Id extends string>({ scope, tabs, active, onSelect }: {
  scope: string;
  tabs: readonly Tab<Id>[];
  active: Id;
  onSelect: (id: Id) => void;
}) {
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    list.current?.querySelector('[aria-selected="true"]')
      ?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [active]);

  function move(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = {
      ArrowRight: (index + 1) % tabs.length,
      ArrowLeft: (index + tabs.length - 1) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    onSelect(tabs[next].id);
    list.current?.querySelectorAll('button')[next]?.focus();
  }

  return <div ref={list} className="workspace-tabs" role="tablist" aria-label={`${scope} tools`}>
    {tabs.map((tab, index) => <button type="button" role="tab" key={tab.id}
      id={`${scope}-tab-${tab.id}`} aria-controls={`${scope}-panel-${tab.id}`}
      aria-selected={tab.id === active} tabIndex={tab.id === active ? 0 : -1}
      title={tab.hint} onClick={() => onSelect(tab.id)} onKeyDown={event => move(event, index)}>
      {tab.label}
    </button>)}
  </div>;
}

export function WorkspaceTabPanels<Id extends string>({ scope, ids, active, render, remount }: {
  scope: string;
  ids: readonly Id[];
  active: Id;
  render: (id: Id) => ReactNode;
  remount?: Id;
}) {
  const [visited, setVisited] = useState<ReadonlySet<Id>>(() => new Set([active]));
  useEffect(() => {
    setVisited(previous => previous.has(active) ? previous : new Set([...previous, active]));
  }, [active]);

  return <>{ids.map(id => <div key={id} className="workspace-tab-panel" role="tabpanel"
    id={`${scope}-panel-${id}`} aria-labelledby={`${scope}-tab-${id}`}
    hidden={id !== active} tabIndex={0}>
    {(id === active || (id !== remount && visited.has(id))) && render(id)}
  </div>)}</>;
}
