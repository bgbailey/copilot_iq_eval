// Fabric SSO for the scorecard: embedded sign-in on load, popup sign-in from a click.
import { useCallback, useEffect, useRef, useState } from 'react';
import { ensureSignedInWithFabric, initEmbeddedAuth } from '@microsoft/rayfin-auth-provider-fabric';

type Session = { isAuthenticated?: boolean; user?: { email?: string | null } | null } | null;
type ClientModule = typeof import('./rayfinClient');

export function useAuth(enabled: boolean) {
  const [session, setSession] = useState<Session>(null);
  const [ready, setReady] = useState(!enabled);
  const [error, setError] = useState<string | null>(null);
  const client = useRef<ClientModule | null>(null);

  useEffect(() => {
    if (!enabled) return undefined;
    let mounted = true;
    let unsubscribe: (() => void) | undefined;
    void (async () => {
      try {
        const mod = await import('./rayfinClient');
        client.current = mod;
        unsubscribe = mod.rayfinClient.auth.onSessionChange((s) => {
          if (mounted) setSession(s as Session);
        });
        await initEmbeddedAuth(mod.rayfinClient.auth, mod.fabricOptions);
        if (mounted) setSession(mod.rayfinClient.auth.getSession() as Session);
      } catch (err) {
        if (mounted) setError(err instanceof Error ? err.message : 'Sign-in is not available');
      } finally {
        if (mounted) setReady(true);
      }
    })();
    return () => {
      mounted = false;
      unsubscribe?.();
    };
  }, [enabled]);

  // Call straight from a click handler so the browser allows the Fabric sign-in popup.
  const signIn = useCallback(() => {
    const mod = client.current;
    if (!mod) {
      setError('Sign-in is still loading. Try again in a moment.');
      return;
    }
    setError(null);
    ensureSignedInWithFabric(mod.rayfinClient.auth, mod.fabricOptions)
      .then((s) => setSession(s as Session))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Sign-in failed'));
  }, []);

  return { session, ready, error, isAuthenticated: Boolean(session?.isAuthenticated), signIn };
}
