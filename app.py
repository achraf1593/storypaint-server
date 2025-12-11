# app.py — Servidor simple y robusto para tu app infantil
import base64
import tempfile
import os
import json
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# Config — tu API key
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

MODEL_IMAGE = "models/gemini-2.5-flash-image"
MODEL_TEXT = "models/gemini-2.0-flash"

# -----------------------------------------------------------
# Utilidad simple: extraer base64 si viene dentro de images[]
# -----------------------------------------------------------
def extract_image_b64(resp):
    try:
        if hasattr(resp, "images") and resp.images:
            img = resp.images[0]
            raw = getattr(img, "data", None) or getattr(img, "base64_data", None)
            if isinstance(raw, bytes):
                return base64.b64encode(raw).decode()
            if isinstance(raw, str):
                return raw
    except:
        pass
    return None


# -----------------------------------------------------------
# POST /generar_imagen
# { "imagen": "<base64>", "prompt": "..." }
# -----------------------------------------------------------
@app.route("/generar_imagen", methods=["POST"])
def generar_imagen():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON inválido."}), 400

        if "imagen" not in data:
            return jsonify({"error": "Falta 'imagen'."}), 400

        imagen_b64 = data["imagen"]
        prompt_usuario = data.get("prompt", "")

        # Decodificar imagen
        try:
            imagen_bytes = base64.b64decode(imagen_b64)
        except:
            return jsonify({"error": "base64 inválido."}), 400

        # Guardar temporalmente
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(imagen_bytes)
            tmp_path = tmp.name

        # -------------------------------------
        # 1) GENERAR IMAGEN ARREGLADA DEL NIÑO
        # -------------------------------------
        model_img = genai.GenerativeModel(MODEL_IMAGE)

        instruccion_arreglo = (
            "Toma este dibujo hecho por un niño pequeño y devuélvelo como una versión "
            "ARREGLADA pero FIEL: refuerza las líneas, define contornos, corrige trazos "
            "torcidos y colorea suavemente sin cambiar la intención original. "
            "No añadas elementos nuevos. Devuelve SOLO la imagen PNG."
        )

        resp_imagen = model_img.generate_content(
            contents=[
                instruccion_arreglo,
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": imagen_b64
                    }
                }
            ]
        )

        imagen_generada = extract_image_b64(resp_imagen)

        # -------------------------------------
        # 2) GENERAR ACTIVIDAD (JSON obligatorio)
        # -------------------------------------
        model_text = genai.GenerativeModel(MODEL_TEXT)

        prompt_actividad = f"""
Eres un diseñador de juegos infantiles para niños de 5 a 8 años.
Basándote SOLO en el dibujo proporcionado y este texto del niño:
"{prompt_usuario}"

Genera UNA actividad simple y divertida que anime al niño a jugar con su propio dibujo.
Responde EXCLUSIVAMENTE con JSON válido con esta estructura:

{{
  "titulo": "...",
  "mision": "...",
  "instrucciones": ["Paso 1", "Paso 2", "Paso 3"],
  "duracion_minutos": 5,
  "materiales": ["lápiz", "colores"],
  "reto_extra": "..."
}}
        """

        resp_txt = model_text.generate_content(prompt_actividad)
        texto = resp_txt.text.strip()

        # Intentar cargar JSON
        try:
            actividad_json = json.loads(texto)
            actividad_generada = json.dumps(actividad_json, ensure_ascii=False)
        except:
            # fallback seguro: enviar el texto tal cual
            actividad_generada = texto

        return jsonify({
            "imagen_generada": imagen_generada,
            "actividad_generada": actividad_generada,
            "modelo_usado": MODEL_IMAGE
        })

    except Exception as e:
        return jsonify({"error": "Error interno", "detalle": str(e)}), 500

    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except:
            pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
