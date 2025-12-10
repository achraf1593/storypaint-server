import os
import base64
import tempfile
from flask import Flask, request, jsonify
import google.generativeai as genai

# Inicializar Flask
app = Flask(__name__)

# Configurar la API key de Gemini/Google
API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
if not API_KEY:
    app.logger.warning("⚠️ No se encontró GEMINI_API_KEY/GOOGLE_API_KEY en el entorno.")
else:
    genai.configure(api_key=API_KEY)

# Modelos candidatos
MODEL_CANDIDATES = [
    "models/gemini-2.5-flash-image",
    "models/gemini-2.5-flash-image-preview",
    "models/gemini-3-pro-image-preview",
    "models/gemini-flash-latest",
]

def extraer_base64_de_respuesta(respuesta):
    try:
        cand = respuesta.candidates[0]
        parts = getattr(cand, "content", None)
        if parts:
            try:
                p = parts.parts[0]
                inline = getattr(p, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    return inline.data
            except Exception:
                pass
        text = getattr(cand, "text", None)
        if text:
            import re, json
            b64match = re.search(r'([A-Za-z0-9+/=]{100,})', text)
            if b64match:
                return b64match.group(1)
            try:
                parsed = json.loads(text)
                for k in ("b64", "image", "imagen", "imagen_base64", "data"):
                    if k in parsed and isinstance(parsed[k], str):
                        return parsed[k]
            except Exception:
                pass
    except Exception:
        pass
    return None

@app.route("/generar_imagen", methods=["POST"])
def generar_imagen():
    try:
        data = request.get_json()
        if not data or "imagen" not in data or "prompt" not in data:
            return jsonify({"error": "Faltan campos requeridos (imagen o prompt)."}), 400

        imagen_b64 = data["imagen"]
        prompt = data["prompt"]

        try:
            imagen_bytes = base64.b64decode(imagen_b64)
        except Exception as e:
            return jsonify({"error": f"Error al decodificar la imagen: {e}"}), 400

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_file:
            tmp_file.write(imagen_bytes)
            tmp_path = tmp_file.name
            app.logger.debug(f"Imagen temporal guardada en {tmp_path}")

        last_error = None
        used_model = None
        respuesta = None

        for candidate in MODEL_CANDIDATES:
            try:
                app.logger.debug(f"Intentando generar con modelo: {candidate}")
                modelo = genai.GenerativeModel(candidate)
                respuesta = modelo.generate_content([prompt, {"mime_type": "image/png", "data": imagen_bytes}])
                used_model = candidate
                break
            except Exception as e:
                app.logger.warning(f"Modelo {candidate} falló: {e}")
                last_error = str(e)
                respuesta = None
                continue

        if respuesta is None:
            msg = f"Ningún modelo intentado funcionó. Último error: {last_error}"
            app.logger.error(msg)
            return jsonify({"error": msg, "detalle": last_error}), 500

        imagen_generada_b64 = extraer_base64_de_respuesta(respuesta)

        if not imagen_generada_b64:
            app.logger.error("No se pudo extraer imagen en base64 del modelo.")
            return jsonify({"error": "No se recibió una imagen válida del modelo.", "modelo_usado": used_model}), 500

        imagen_generada_b64 = imagen_generada_b64.replace("\n", "").replace(" ", "")

        return jsonify({
            "imagen_generada": imagen_generada_b64,
            "modelo_usado": used_model
        })

    except Exception as e:
        app.logger.error(f"Error general del servidor: {e}")
        return jsonify({"error": f"Error general del servidor: {e}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
