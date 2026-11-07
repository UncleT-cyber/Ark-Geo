/**
 * TabsProvider — hoists the investigation-tab surface above the workbench so
 * the investigation store can be keyed by the active investigation id.
 *
 * The tab registry is navigation metadata (see `tabRegistry.ts`); this provider
 * only makes the single tab surface available to every layer that needs it,
 * without a second store.
 */
import React, { createContext, useContext } from 'react';
import { useInvestigationTabs } from './useInvestigationTabs';

type TabsApi = ReturnType<typeof useInvestigationTabs>;

const Ctx = createContext<TabsApi | null>(null);

export function TabsProvider({ children }: { children: React.ReactNode }) {
  const api = useInvestigationTabs();
  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function useTabs(): TabsApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useTabs must be used within <TabsProvider>');
  return ctx;
}

export type { TabsApi };
