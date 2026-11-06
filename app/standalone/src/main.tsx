// Standalone preview: the same scorecard code as the Fabric app, reading the bundled sample data.
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import EvalApp from '../../overlay/src/eval/EvalApp';

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <EvalApp />
  </StrictMode>,
);
