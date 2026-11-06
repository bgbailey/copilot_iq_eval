// Preview stub: no backend, never signed in.
export class ConnectorsRayfinClient {
  constructor() {
    this.auth = { getSession: () => null, onSessionChange: () => () => {}, signOut: async () => {} };
    this.connectors = {};
  }
}
