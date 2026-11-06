// Minimal type stubs so the preview type-checks without the Rayfin packages.
// The real packages come with `npm create @microsoft/rayfin` (see app/README.md).
declare module '@microsoft/rayfin-client' {
  export type Session = { isAuthenticated: boolean; user?: { email?: string } } | null;
  export interface Auth {
    getSession(): Session;
    onSessionChange(cb: (s: Session) => void): () => void;
    signOut(): Promise<void>;
  }
  export class ConnectorsRayfinClient<D, F, C> {
    constructor(config: { baseUrl: string; publishableKey: string; authStorage?: boolean; connectors: Record<string, unknown> }, runtime?: unknown);
    readonly auth: Auth;
    readonly connectors: C;
    readonly schemas?: [D, F];
  }
}
declare module '@microsoft/rayfin-auth-provider-fabric' {
  import type { Auth, Session } from '@microsoft/rayfin-client';
  export interface FabricAuthOptions { workspaceId: string; projectId: string; fabricPortalUrl: string; returnOrigin: string }
  export function ensureSignedInWithFabric(auth: Auth, options: FabricAuthOptions): Promise<NonNullable<Session>>;
  export function initEmbeddedAuth(auth: Auth, options: FabricAuthOptions): Promise<Session>;
}
declare module '@microsoft/rayfin-core' {
  type Decorator = (value: unknown, context: unknown) => void;
  export function role(name: string, actions: string[]): Decorator;
  export function entity(): Decorator;
  export function text(options?: object): Decorator;
  export function int(options?: object): Decorator;
  export function decimal(options?: object): Decorator;
  export function date(options?: object): Decorator;
  export function boolean(options?: object): Decorator;
  export function uuid(options?: object): Decorator;
}
declare module '@microsoft/rayfin-connectors' {
  export type ConnectorConfig = { connector: string; operations: readonly string[]; entities?: Record<string, readonly string[]> };
  export function Source(options: { schema: string; table: string; primaryKey: readonly string[] }): new () => object;
}
declare module '@microsoft/rayfin-connector-fabric-graphql' {
  export type GraphQLBackedConnector<S, C> = { [K in keyof S]: unknown } & { readonly config?: C };
}
