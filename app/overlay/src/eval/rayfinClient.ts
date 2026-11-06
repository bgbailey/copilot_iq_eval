// The one place the app touches the Rayfin SDK client.
import { ConnectorsRayfinClient } from '@microsoft/rayfin-client';
import { connectorConfig, type EvalsSchema } from './connectorSchema';

export type AppConnectorsSchema = { evals: EvalsSchema };

export const rayfinClient = new ConnectorsRayfinClient<Record<string, never>, Record<string, never>, AppConnectorsSchema>({
  baseUrl: import.meta.env.VITE_RAYFIN_API_URL,
  publishableKey: import.meta.env.VITE_RAYFIN_PUBLISHABLE_KEY,
  authStorage: true,
  connectors: { evals: connectorConfig },
});

export const fabricOptions = {
  workspaceId: import.meta.env.VITE_FABRIC_WORKSPACE_ID,
  projectId: import.meta.env.VITE_FABRIC_ITEM_ID,
  fabricPortalUrl: import.meta.env.VITE_FABRIC_PORTAL_URL,
  returnOrigin: window.location.origin,
};
