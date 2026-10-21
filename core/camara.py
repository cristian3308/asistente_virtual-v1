"""Los ojos de Jarvis: saber si estás frente al PC, reconocerte y ver tu ánimo.

Privacidad (no negociable):
- La cámara solo se enciende con /camara on (su luz queda encendida mientras mira).
- Ninguna imagen se guarda ni sale del PC: cada foto se analiza en memoria y se descarta.
- De tu cara solo se guarda una "huella" numérica (128 números de SFace) en data/rostro.npy;
  no se puede convertir de vuelta en foto. /camara olvidar la borra.

Modelos de OpenCV Zoo en CPU (data/modelos_camara): YuNet encuentra caras, SFace dice si
eres tú y MobileFaceNet estima la expresión. Mirando una foto cada 2 s gasta muy poco.
"""
from __future__ import annotations

import threading
import time
from collections import Counter, deque

from config import settings

MODELOS = settings.DATA_DIR / "modelos_camara"
DETECTOR = MODELOS / "face_detection_yunet_2023mar.onnx"
RECONOCEDOR = MODELOS / "face_recognition_sface_2021dec.onnx"
EXPRESIONES = MODELOS / "facial_expression_recognition_mobilefacenet_2022july.onnx"
ROSTRO = settings.DATA_DIR / "rostro.npy"
UMBRAL_MISMA_PERSONA = 0.363      # similitud coseno recomendada por SFace
CADA_SEGUNDOS = 2.0
EMOCIONES = ["enojado", "disgustado", "asustado", "feliz", "neutral", "triste", "sorprendido"]


def disponible() -> bool:
    return all(p.exists() for p in (DETECTOR, RECONOCEDOR, EXPRESIONES))


class Ojos:
    """Analiza fotos: caras, si eres tú y tu expresión. Sin hilos ni cámara (fácil de probar)."""

    def __init__(self) -> None:
        import cv2
        self.cv2 = cv2
        self.detector = cv2.FaceDetectorYN.create(str(DETECTOR), "", (320, 320), 0.8, 0.3, 5)
        self.reconocedor = cv2.FaceRecognizerSF.create(str(RECONOCEDOR), "")
        self.expresiones = cv2.dnn.readNet(str(EXPRESIONES))

    def caras(self, imagen):
        alto, ancho = imagen.shape[:2]
        self.detector.setInputSize((ancho, alto))
        _ok, caras = self.detector.detect(imagen)
        return [] if caras is None else list(caras)

    def huella(self, imagen, cara):
        alineada = self.reconocedor.alignCrop(imagen, cara)
        return self.reconocedor.feature(alineada), alineada

    def parecido(self, huella_a, huella_b) -> float:
        return float(self.reconocedor.match(huella_a, huella_b, self.cv2.FaceRecognizerSF_FR_COSINE))

    def expresion(self, cara_alineada) -> str:
        import numpy as np
        rgb = self.cv2.cvtColor(cara_alineada, self.cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        entrada = self.cv2.dnn.blobFromImage((rgb - 0.5) / 0.5)
        self.expresiones.setInput(entrada)
        return EMOCIONES[int(np.argmax(self.expresiones.forward()))]

    def analizar(self, imagen, mi_huella=None) -> dict:
        """{'caras': n, 'tu': bool, 'parecido': float, 'emocion': str|None, 'desconocidos': n}"""
        resultado = {"caras": 0, "tu": False, "parecido": 0.0, "emocion": None, "desconocidos": 0}
        caras = self.caras(imagen)
        resultado["caras"] = len(caras)
        for cara in sorted(caras, key=lambda c: -c[2] * c[3]):   # la más grande (la más cercana) primero
            huella, alineada = self.huella(imagen, cara)
            parecido = self.parecido(huella, mi_huella) if mi_huella is not None else 0.0
            if mi_huella is not None and parecido >= UMBRAL_MISMA_PERSONA and not resultado["tu"]:
                resultado.update(tu=True, parecido=round(parecido, 2), emocion=self.expresion(alineada))
            elif mi_huella is not None:
                resultado["desconocidos"] += 1
            elif resultado["emocion"] is None:
                resultado["emocion"] = self.expresion(alineada)   # sin registro: la cara más cercana
        return resultado


class Camara:
    """Mira una foto cada 2 s mientras está encendida y resume lo que ve."""

    def __init__(self, al_cambiar=None, indice: int = 0) -> None:
        self.al_cambiar = al_cambiar or (lambda evento, datos: None)
        self.indice = indice
        self._ojos: Ojos | None = None
        self._captura = None
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()
        self._lock = threading.Lock()
        self.ultimo: dict = {}
        self._emociones: deque = deque(maxlen=15)   # ~30 s de historial para no reaccionar a un gesto suelto
        self._visto_hace = 0.0

    # --- registro de tu cara ---
    def mi_huella(self):
        import numpy as np
        return np.load(ROSTRO) if ROSTRO.exists() else None

    def registrar(self, fotos: int = 8) -> str:
        """Toma varias fotos con una sola cara y guarda el promedio de tu huella (no las fotos)."""
        import numpy as np
        huellas = []
        with self._lock:
            captura = self._abrir()
            try:
                inicio = time.monotonic()
                while len(huellas) < fotos and time.monotonic() - inicio < 20:
                    ok, imagen = captura.read()
                    if not ok:
                        continue
                    caras = self._ojos_().caras(imagen)
                    if len(caras) == 1:
                        huellas.append(self._ojos_().huella(imagen, caras[0])[0])
                    time.sleep(0.3)
            finally:
                if self._hilo is None or not self._hilo.is_alive():
                    self._cerrar()
        if len(huellas) < 3:
            return "No pude verte bien: ponte frente a la cámara, con buena luz y solo tú en la imagen."
        promedio = np.mean(np.vstack(huellas), axis=0, keepdims=True).astype(np.float32)
        ROSTRO.parent.mkdir(parents=True, exist_ok=True)
        np.save(ROSTRO, promedio)
        return f"Listo, {settings.USER_NAME}. Ya te reconozco (guardé solo una huella numérica, ninguna foto)."

    def olvidar(self) -> str:
        ROSTRO.unlink(missing_ok=True)
        return "Olvidé tu huella facial."

    # --- vigilancia ---
    def encender(self) -> str:
        if not disponible():
            return "Faltan los modelos de la cámara en data/modelos_camara (ver README)."
        try:
            with self._lock:
                self._abrir()
        except Exception as exc:
            return f"No pude abrir la cámara: {exc}"
        self._parar.clear()
        if self._hilo is None or not self._hilo.is_alive():
            self._hilo = threading.Thread(target=self._bucle, name="camara", daemon=True)
            self._hilo.start()
        aviso = "" if ROSTRO.exists() else " Aún no te conozco: di /camara registrar para que te reconozca."
        return "Cámara encendida (la luz queda prendida mientras miro; no guardo imágenes)." + aviso

    def apagar(self) -> str:
        self._parar.set()
        with self._lock:
            self._cerrar()
        self.ultimo = {}
        return "Cámara apagada."

    def encendida(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive() and not self._parar.is_set()

    def _ojos_(self) -> Ojos:
        if self._ojos is None:
            self._ojos = Ojos()
        return self._ojos

    def _abrir(self):
        if self._captura is None:
            import cv2
            captura = cv2.VideoCapture(self.indice, cv2.CAP_DSHOW)
            if not captura.isOpened():
                raise RuntimeError("no hay cámara disponible o la usa otro programa")
            captura.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            captura.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self._captura = captura
        return self._captura

    def _cerrar(self) -> None:
        if self._captura is not None:
            self._captura.release()
            self._captura = None

    def mirar(self) -> dict:
        """Una foto ahora mismo, analizada y descartada."""
        with self._lock:
            ok, imagen = self._abrir().read()
        if not ok:
            return {}
        datos = self._ojos_().analizar(imagen, self.mi_huella())
        del imagen   # nunca se guarda
        return datos

    def _bucle(self) -> None:
        presente_antes = None
        while not self._parar.wait(CADA_SEGUNDOS):
            try:
                datos = self.mirar()
            except Exception:
                continue
            if not datos:
                continue
            registrado = ROSTRO.exists()
            presente = datos["tu"] if registrado else datos["caras"] > 0
            if presente:
                self._visto_hace = time.monotonic()
                if datos["emocion"]:
                    self._emociones.append(datos["emocion"])
            self.ultimo = {**datos, "presente": presente, "hora": time.time()}
            if presente_antes is not None and presente != presente_antes:
                self.al_cambiar("llegaste" if presente else "te_fuiste", self.ultimo)
            if registrado and datos["desconocidos"] and not datos["tu"]:
                self.al_cambiar("desconocido", self.ultimo)
            presente_antes = presente

    # --- para el cerebro y las interfaces ---
    def animo(self) -> str | None:
        """La emoción más frecuente de los últimos ~30 s (un gesto suelto no cuenta)."""
        if not self._emociones:
            return None
        emocion, veces = Counter(self._emociones).most_common(1)[0]
        return emocion if veces >= max(2, len(self._emociones) // 3) else None

    def resumen(self) -> str:
        """Una línea para el modelo: solo si la cámara está encendida y hay datos recientes."""
        if not self.encendida() or not self.ultimo or time.time() - self.ultimo.get("hora", 0) > 10:
            return ""
        if not self.ultimo.get("presente"):
            return f"CÁMARA: {settings.USER_NAME} no está frente al PC ahora mismo."
        animo = self.animo()
        quien = settings.USER_NAME if ROSTRO.exists() else "alguien (aún no registraste tu cara)"
        return (f"CÁMARA: {quien} está frente al PC" + (f"; parece {animo}" if animo else "") +
                ". Menciónalo solo si viene al caso y con tacto (la expresión es una estimación).")


_camara: Camara | None = None


def obtener(al_cambiar=None) -> Camara:
    global _camara
    if _camara is None:
        _camara = Camara(al_cambiar)
    elif al_cambiar is not None:
        _camara.al_cambiar = al_cambiar
    return _camara


def resumen_actual() -> str:
    return _camara.resumen() if _camara is not None else ""
