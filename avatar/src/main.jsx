import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { RobotHead } from 'robot-heads';

// El color del borde y la antena indica quién responde.
const COLORES = {
  local: { color: '#2b3a55', trim: '#4f8cff', screen: '#7fd4ff' },
  cloud: { color: '#3a2b55', trim: '#a970ff', screen: '#e0b3ff' },
  directo: { color: '#24443a', trim: '#3ddc97', screen: '#9dffd6' },
};

function App() {
  const [vista, setVista] = useState({ estado: 'idle', motor: 'local' });
  const boca = useRef(null);

  // Estado: sondeo local cada 60 ms; solo re-renderiza si cambia algo visible.
  useEffect(() => {
    let vivo = true;
    const leer = async () => {
      try {
        const respuesta = await fetch('/estado', { cache: 'no-store' });
        if (respuesta.ok) {
          const datos = await respuesta.json();
          boca.current = datos.boca && datos.boca.env && datos.boca.env.length ? datos.boca : null;
          setVista((v) => (v.estado === datos.estado && v.motor === datos.motor ? v : { estado: datos.estado, motor: datos.motor }));
        }
      } catch {
        boca.current = null;
        setVista((v) => (v.estado === 'sleeping' ? v : { ...v, estado: 'sleeping' }));
      }
      if (vivo) setTimeout(leer, 60);
    };
    leer();
    return () => { vivo = false; };
  }, []);

  // Boca: en cada fotograma toma el volumen del instante exacto del audio,
  // con el reloj de la propia página, así el sondeo no la retrasa.
  useEffect(() => {
    let id;
    const fotograma = () => {
      const b = boca.current;
      if (b) {
        const indice = Math.floor((Date.now() - b.inicio) / b.paso);
        globalThis.__bocaNivel = indice < 0 ? 0 : indice < b.env.length ? b.env[indice] : 0;
      } else {
        globalThis.__bocaNivel = undefined;
      }
      id = requestAnimationFrame(fotograma);
    };
    id = requestAnimationFrame(fotograma);
    return () => cancelAnimationFrame(id);
  }, []);

  const c = COLORES[vista.motor] || COLORES.local;
  return (
    <div className="wrap" title={vista.motor === 'cloud' ? 'Respondiendo con la nube' : 'Respondiendo en local'}>
      <RobotHead state={vista.estado} size={170} color={c.color} trimColor={c.trim} screenColor={c.screen} floorShadow={false} />
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
