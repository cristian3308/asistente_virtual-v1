# Asistente Virtual Profundo (JARVIS personal) — Windows

Asistente personal para Windows 11 que combina un modelo local (Ollama, en la GPU)
con modelos en la nube (OpenCode Go). Conversa por texto o voz, recuerda lo que le
cuentas, usa herramientas del PC con permisos, aprende habilidades nuevas probándolas
en un entorno aislado y se controla también desde Telegram. Un robot animado flotante
muestra lo que está haciendo y mueve la boca al ritmo de la voz.

Equipo de referencia: Intel i5-12500H · 24 GB RAM · RTX 3050 Laptop (4 GB).

## Requisitos

| Componente | Versión probada | Para qué |
|---|---|---|
| Windows 10/11 | 11 | Sistema |
| Python | 3.10 | El asistente |
| [Ollama](https://ollama.com) | — | Modelo local (`qwen2.5-coder:3b`) |
| Node.js | 22 | Solo para el avatar (Electron) |
| Clave de OpenCode Go | opcional | Modelos en la nube y escalado automático |

## Instalación

```powershell
git clone https://github.com/cristian3308/asistente_virtual-v1.git
cd asistente_virtual-v1
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt
ollama pull qwen2.5-coder:3b
copy .env.example .env      # y rellena tus valores
```

Avatar (opcional, recomendado):

```powershell
cd avatar
npm install
npm run build
```

## Arrancar

Doble clic en `iniciar_asistente.bat` (opción 1) o:

```powershell
.venv\Scripts\python.exe main.py
```

Al arrancar verás: Ollama/nube detectados, habilidades cargadas, el robot en la esquina
inferior derecha y, si está configurado, `✅ Telegram conectado: @tu_bot`.

## Uso

Habla en lenguaje normal: *"¿cuánta RAM uso?"*, *"abre Spotify"*, *"investiga X y hazme un
resumen"*, *"recuérdame en 10 minutos…"*, *"guarda una nota…"*.

| Comando | Qué hace |
|---|---|
| `/conversar` | Conversación por voz manos libres (responde cuando te callas 4 s; di "salir") |
| `/voz` | Activa la voz: Enter vacío para hablar |
| `/voces`, `/voz_probar jarvis`, `/voz_usar jarvis` | Ver, escuchar y elegir la voz |
| `/recuerdos`, `/olvidar <id o texto>` | Ver y borrar lo que sabe de ti |
| `/tareas`, `/tarea <objetivo>` | Ver tareas y encargar un trabajo en segundo plano (avisa al terminar) |
| `/cancelar`, `/pausar`, `/reactivar <id>` | Gestionar tareas |
| `/parar`, `/reanudar` | **Parada de emergencia**: corta todo al instante (también desde Telegram) |
| `/auditoria` | Últimas acciones registradas |
| `/habilidades`, `/autoprogramar <instrucción>` | Ver y crear habilidades |
| `/ver <pregunta>` | Analiza el texto de tu pantalla (OCR) |
| `/modelo local\|codigo\|razonamiento\|rapido\|turbo` | Elegir modelo |
| `/avatar` | Mostrar u ocultar el robot |
| `/estado`, `/benchmark`, `/centinela on\|off` | Estado del PC, velocidad del modelo, alertas |

### Memoria
Detecta y guarda automáticamente lo que dices de ti ("me llamo…", "mi mamá se llama…",
"me gusta…", "recuerda que…") y lo incluye en cada respuesta, también tras reiniciar.
Corrige diciéndolo de nuevo; borra con `/olvidar` o "olvida que…". Se guarda solo en tu
PC (`data/perfil.db`, `data/chroma_db`).

### Reglas, procedimientos y contexto
- **Reglas permanentes:** *"cuando te pida X, haz siempre Y"*, *"no uses Chrome, usa Brave"*, *"de ahora en
  adelante…"*, *"nunca me hables de usted"* se guardan y se cumplen en cada respuesta (`/recuerdos` las muestra).
- **Procedimientos aprendidos:** cuando resuelve algo encadenando varias herramientas, guarda la receta y la
  usa como guía la próxima vez que pidas algo parecido (`/procedimientos`).
- **Encadenamiento local:** el modelo local puede usar hasta 3 herramientas distintas por turno.
- **Ventana activa:** al preguntar *"¿por qué me sale este error?"* sabe en qué ventana estabas antes de escribirle.
- **Auto-reparación:** si una habilidad aprendida falla, se guarda el caso exacto y puede repararla con
  *"repara la habilidad X"* (ese caso pasa a ser prueba obligatoria). `/fallos` lista los fallos.
- **`/reiniciar`:** recarga el asistente con los cambios aplicados sin cerrar la ventana (lo hace `iniciar_asistente.bat`).

### Habilidades aprendidas
Cuando le pides algo calculable o de texto que no sabe hacer, genera una función, **la
prueba en un proceso aislado** (sin tus claves, sin archivos ni red, con límite de tiempo),
la repara si falla y te muestra el código con los resultados antes de instalarla.
Se usa en ese mismo momento, sin reiniciar.

### Tareas y recordatorios
Los recordatorios (*"recuérdame a las 18:30…"*) y las tareas en segundo plano (*"encárgate de investigar…"*, `/tarea …`) se guardan en `data/tareas.db`: sobreviven a cerrar el programa y las que quedaron a medias se reanudan al volver a abrirlo. Reintentan con espera creciente (máximo 3 intentos) y avisan en consola, por voz y por Telegram. En segundo plano no puede aprobar acciones sensibles: esas se rechazan solas.

### Agente programador (cambios en su propio código)
Pídele cambios como *"añade a tu bot el comando /hora"* o usa `/programar <cambio>`. Con tu
aprobación, un modelo de la nube trabaja en una **copia aislada** (`git worktree` en
`data/taller/<id>`, rama `agente/<id>`): lee, edita, añade pruebas y las ejecuta hasta que pasan
(máximo 30 llamadas y 15 minutos). Tu código no cambia hasta que lo revisas y lo apruebas:

| Comando | Qué hace |
|---|---|
| `/revisar <id>` | Resumen, resultado de las pruebas y diff, con avisos si toca seguridad, comandos o secretos |
| `/aprobar <id>` | Empieza un cambio pedido desde Telegram, o aplica uno ya revisado (merge en `master`) |
| `/rechazar <id>` | Descarta la rama sin tocar tu código |
| `/deshacer <id>` | Revierte un cambio ya aplicado (`git revert`) |

Protecciones: no puede modificar `core/auditoria.py`, `core/programador.py`, `core/self_coder.py`,
`tools/dev_sec_tools.py`, `.gitignore`, `AGENTS.md` ni `.env`; sus herramientas no salen de la copia;
las pruebas corren sin tus claves y con límite de tiempo. Limitación: no hay contenedor (Docker), así
que esas pruebas son procesos de tu Windows; por eso empezar un cambio pide tu aprobación.

### Auditoría y parada de emergencia
Cada herramienta, confirmación, habilidad instalada y escalado a la nube queda en `data/auditoria/acciones.jsonl` (con origen, duración y resultado; las claves se ocultan). `/parar` bloquea herramientas, corta la respuesta en curso, silencia la voz y pausa las tareas.

### Telegram
1. En Telegram, `@BotFather` → `/newbot` → copia el token.
2. `@userinfobot` → copia tu id numérico.
3. Ponlos en `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`) y reinicia.
4. Escribe `/start` a tu bot. Texto, notas de voz (responde con voz), `/captura`, `/tarea`, `/tareas`,
   `/cancelar` y la parada de emergencia `/parar` · `/reanudar`.

Solo responde a tu id. Desde Telegram no ejecuta PowerShell ni instala habilidades.

## Seguridad
- Las habilidades generadas se validan (lista blanca de módulos) y se ejecutan en un
  proceso aparte sin variables de entorno; instalarlas requiere tu confirmación.
- Lectura de archivos limitada al proyecto y la bóveda; `data/`, `.env` y bases de datos bloqueados.
- PowerShell no listado como seguro y acciones del navegador requieren confirmación.
- Las páginas web se tratan como datos, nunca como órdenes; sin acceso a la red local (SSRF).
- `.env`, `data/` y la bóveda personal están en `.gitignore`.

## Pruebas

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

Benchmark de modelos locales con herramientas: `.venv\Scripts\python.exe benchmarks\modelos_herramientas.py`.

## Solución de problemas

| Síntoma | Causa y solución |
|---|---|
| "No hay motores disponibles" | Ollama apagado: `ollama serve` (el `.bat` lo inicia). |
| Telegram no responde | Mira la consola al arrancar: debe decir `✅ Telegram conectado`. El `.env` solo se lee al iniciar; lo enviado con el asistente cerrado se descarta. |
| "mensaje ignorado de id …" | Ese número no coincide con `TELEGRAM_ALLOWED_USER_ID`. |
| Dos robots en pantalla | Versiones antiguas: cierra el asistente; el robot se cierra solo con él. |
| El robot no aparece | Falta `npm install` y `npm run build` en `avatar/`. |
| Tarda en entender la voz | `WHISPER_MODEL=base` es más rápido (menos preciso). |
| "ModelProtocolUnsupported" | Ese modelo de la nube no admite chat; usa kimi, qwen3.7-plus, glm-5.3 o minimax-m3. |

## Estructura

```
main.py                 consola y comandos
config/settings.py      configuración (lee .env)
core/brain.py           conversación, herramientas, memoria, escalado a la nube
core/router.py          selección de modelo local/nube y recorte de contexto
core/self_coder.py      creación de habilidades con pruebas aisladas
core/estado.py          estado observable (para el avatar)
memory/                 perfil personal, historial, memoria semántica, fallos
tools/                  herramientas (sistema, web, archivos, apps, notas…)
voice/                  escucha (Silero + Whisper) y voz (Edge TTS)
interfaces/             Telegram y avatar
avatar/                 robot animado (React + robot-heads + Electron)
tests/                  pruebas automatizadas
```

## Hoja de ruta

Hecho: chat local/nube con escalado automático, memoria personal persistente, voz, avatar, Telegram, habilidades con pruebas aisladas, investigación web, registro de auditoría, parada de emergencia, motor de tareas persistente con avisos y agente programador con revisión de cambios.

Próximo: interfaz web/PWA con acceso seguro desde Android (Tailscale), visión multimodal, resúmenes de memoria.

Créditos: avatar basado en [robot-heads](https://github.com/fayazara/robot-heads) (MIT).
