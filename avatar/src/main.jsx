import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { RobotHead } from 'robot-heads';

// El color del borde y la antena indica quién responde.
const COLORES = {
  local: { color: '#2b3a55', trim: '#4f8cff', screen: '#7fd4ff' },
  cloud: { color: '#3a2b55', trim: '#a970ff', screen: '#e0b3ff' },
  directo: { color: '#24443a', trim: '#3ddc97', screen: '#9dffd6' },
};
const ESTADOS_CON_ETIQUETA = new Set(['thinking', 'searching', 'working']);

function Arco({ radio, valor, color, etiqueta }) {
  // Arco de 270° (deja un hueco abajo, como un indicador); valor de 0 a 100.
  const largo = 2 * Math.PI * radio * 0.75;
  const lleno = Math.max(0, Math.min(100, valor ?? 0)) / 100 * largo;
  const alerta = (valor ?? 0) >= 85;
  return (
    <g transform="rotate(135 150 140)">
      <circle cx="150" cy="140" r={radio} className="pista" strokeDasharray={`${largo} 999`} />
      <circle cx="150" cy="140" r={radio} className={'valor' + (alerta ? ' alerta' : '')} stroke={color}
        strokeDasharray={`${lleno} 999`}>
        <title>{etiqueta}: {valor == null ? '—' : Math.round(valor) + ' %'}</title>
      </circle>
    </g>
  );
}

function App() {
  const [vista, setVista] = useState({ estado: 'idle', motor: 'local', detalle: '', subtitulo: '' });
  const [tele, setTele] = useState(null);
  const boca = useRef(null);

  useEffect(() => {
    let vivo = true;
    let fuente = null;
    let sondeo = null;

    const aplicar = (datos) => {
      boca.current = datos.boca && datos.boca.env && datos.boca.env.length ? datos.boca : null;
      if (datos.telemetria) setTele(datos.telemetria);
      setVista((v) => (v.estado === datos.estado && v.motor === datos.motor && v.detalle === datos.detalle
        && v.subtitulo === (datos.subtitulo || '')) ? v
        : { estado: datos.estado, motor: datos.motor, detalle: datos.detalle || '', subtitulo: datos.subtitulo || '' });
    };

    // Respaldo: si el servidor no tiene /eventos (versión vieja), pregunta cada 60 ms como antes.
    const sondear = async () => {
      try {
        const r = await fetch('/estado', { cache: 'no-store' });
        if (r.ok) aplicar(await r.json());
      } catch {
        boca.current = null;
        setVista((v) => (v.estado === 'sleeping' ? v : { ...v, estado: 'sleeping' }));
      }
      if (vivo) sondeo = setTimeout(sondear, 60);
    };

    // Lo normal: una conexión abierta por la que el asistente empuja el estado solo cuando cambia.
    const conectar = () => {
      fuente = new EventSource('/eventos');
      let recibio = false;
      fuente.onmessage = (e) => { recibio = true; aplicar(JSON.parse(e.data)); };
      fuente.onerror = () => {
        fuente.close();
        if (!vivo) return;
        if (recibio) setTimeout(conectar, 1500);   // se cortó: reconecta
        else sondear();                             // nunca funcionó: modo antiguo
      };
    };
    conectar();
    return () => { vivo = false; if (fuente) fuente.close(); clearTimeout(sondeo); };
  }, []);

  // Boca: en cada fotograma toma el volumen del instante exacto del audio, con el reloj de la página.
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
  const etiqueta = ESTADOS_CON_ETIQUETA.has(vista.estado) ? (vista.detalle || 'Pensando…') : '';
  const resumen = tele
    ? `CPU ${Math.round(tele.cpu)} % · RAM ${Math.round(tele.ram)} %` + (tele.gpu != null ? ` · GPU ${Math.round(tele.gpu)} %` : '')
      + (tele.temp != null ? ` · ${Math.round(tele.temp)} °C` : '')
    : '';
  return (
    <div className="wrap" title={resumen || (vista.motor === 'cloud' ? 'Respondiendo con la nube' : 'Respondiendo en local')}>
      <div className={'chip' + (etiqueta ? ' visible' : '')}>{etiqueta}</div>
      <div className="hud">
        <svg className="anillos" viewBox="0 0 300 280" aria-hidden="true">
          <Arco radio={124} valor={tele?.cpu} color={c.trim} etiqueta="CPU" />
          <Arco radio={116} valor={tele?.ram} color="#3ddc97" etiqueta="RAM" />
          <Arco radio={108} valor={tele?.gpu} color={c.screen} etiqueta="GPU" />
        </svg>
        <div className="robot">
          <RobotHead state={vista.estado} size={170} color={c.color} trimColor={c.trim} screenColor={c.screen} floorShadow={false} />
        </div>
      </div>
      <div className={'subtitulo' + (vista.subtitulo ? ' visible' : '')}>{vista.subtitulo}</div>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
