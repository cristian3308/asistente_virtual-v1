// Ventana flotante transparente del avatar: `electron main.cjs <url> --padre=<pid>`.
// Solo se ve el robot; se arrastra con el ratón y queda siempre encima.
const { app, BrowserWindow, screen } = require('electron');

const ANCHO = 220;
const ALTO = 230;
const MARGEN = 12;

// robot-heads muestra una pose fija si Windows tiene desactivados los efectos de
// animación. El avatar es algo que el usuario activa para verlo moverse.
app.commandLine.appendSwitch('force-prefers-no-reduced-motion');

function leerArgumentos(argv) {
  const url = argv.find((arg) => arg.startsWith('http://127.0.0.1:')) || 'http://127.0.0.1:8765/';
  const padre = Number((argv.find((arg) => arg.startsWith('--padre=')) || '').slice('--padre='.length)) || null;
  return { url, padre };
}

let { url, padre } = leerArgumentos(process.argv);
let ventana = null;

// Un solo robot: si se abre otro, el que ya existe pasa a seguir al asistente nuevo.
if (!app.requestSingleInstanceLock({ url, padre })) {
  app.quit();
} else {
  app.on('second-instance', (_evento, _argv, _dir, datos) => {
    if (datos && datos.padre) padre = datos.padre;
    if (ventana && datos && datos.url && datos.url !== url) {
      url = datos.url;
      ventana.loadURL(url);
    }
  });
  app.whenReady().then(crearVentana);
}

// Si el asistente se cierra (aunque sea con la X de la consola), el robot se va con él.
setInterval(() => {
  if (!padre) return;
  try {
    process.kill(padre, 0);
  } catch {
    app.quit();
  }
}, 1500);

function crearVentana() {
  const area = screen.getPrimaryDisplay().workArea; // ya descuenta la barra de tareas y la escala DPI
  ventana = new BrowserWindow({
    width: ANCHO,
    height: ALTO,
    x: area.x + area.width - ANCHO - MARGEN,
    y: area.y + area.height - ALTO - MARGEN,
    transparent: true,
    backgroundColor: '#00000000',
    frame: false,
    hasShadow: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: {
      // Sin esto Chromium baja la animación a pocos fotogramas cuando la ventana
      // no tiene el foco (mientras escribes en la consola) y se ve trabada.
      backgroundThrottling: false,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  ventana.setAlwaysOnTop(true, 'floating');
  // La página solo puede ser el servidor local del asistente.
  ventana.webContents.on('will-navigate', (evento, destino) => {
    if (!destino.startsWith('http://127.0.0.1:')) evento.preventDefault();
  });
  ventana.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  ventana.loadURL(url);
}

app.on('window-all-closed', () => app.quit());
