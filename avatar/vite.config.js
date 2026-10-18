import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// robot-heads (MIT) anima la boca de "speaking" con un vaivén propio. Este ajuste
// hace que, si la página fija globalThis.__bocaNivel (0–1, volumen real del audio),
// la apertura de la boca lo siga sílaba por sílaba. Sin ese valor se comporta igual
// que el original. Si una versión nueva cambia el código, la compilación falla
// aquí en lugar de dejar la boca desincronizada en silencio.
const PARCHES = [
  [
    'const s = Math.max(0, Math.sin(t.time * 2.1) * 0.5 + Math.sin(t.time * 3.7 + 1) * 0.5);',
    'const __n = globalThis.__bocaNivel; const s = typeof __n === "number" ? __n : Math.max(0, Math.sin(t.time * 2.1) * 0.5 + Math.sin(t.time * 3.7 + 1) * 0.5);',
  ],
  [
    'i = Ft(t.time * 11 + e * 0.9) * o * (0.35 + s)',
    'i = typeof __n === "number" ? (0.7 + 0.3 * Ft(t.time * 11 + e * 0.9)) * o * (1.3 * s) : Ft(t.time * 11 + e * 0.9) * o * (0.35 + s)',
  ],
];

function bocaSincronizada() {
  return {
    name: 'boca-sincronizada',
    transform(code, id) {
      if (!id.replace(/\\/g, '/').includes('/robot-heads/dist/index.js')) return null;
      let resultado = code;
      for (const [original, nuevo] of PARCHES) {
        if (!resultado.includes(original)) {
          throw new Error('robot-heads cambió: revisa el ajuste de la boca en vite.config.js');
        }
        resultado = resultado.replace(original, nuevo);
      }
      return { code: resultado, map: null };
    },
  };
}

// Rutas relativas: el servidor Python sirve dist/ desde la raíz de 127.0.0.1.
export default defineConfig({
  base: './',
  plugins: [react(), bocaSincronizada()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: { proxy: { '/estado': 'http://127.0.0.1:8765' } },
});
