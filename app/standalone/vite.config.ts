// Standalone preview build: Rayfin packages are replaced with no-op stubs and the app is forced
// into sample-data mode. The deployed Fabric app uses the real packages (see app/README.md).
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const here = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  plugins: [react()],
  base: './',
  publicDir: here('../overlay/public'),
  define: { 'import.meta.env.VITE_EVAL_DATA': JSON.stringify('sample') },
  resolve: {
    // The scorecard source lives in ../overlay: resolve React from this folder's node_modules.
    dedupe: ['react', 'react-dom'],
    alias: {
      '@microsoft/rayfin-client': here('./stubs/rayfin-client.js'),
      '@microsoft/rayfin-auth-provider-fabric': here('./stubs/rayfin-auth-provider-fabric.js'),
      '@microsoft/rayfin-core': here('./stubs/rayfin-core.js'),
      '@microsoft/rayfin-connectors': here('./stubs/rayfin-connectors.js'),
    },
  },
  server: { fs: { allow: [here('..')] } },
});
