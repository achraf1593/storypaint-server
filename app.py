# app.py (reemplaza tu versión actual)
import base64
import tempfile
import os
import json
import re
import logging
from flask import Flask, request, jsonify
import google.generativeai as genai
from PIL import Image
from io import BytesIO

# Config
LOG = logging.getLogger("storypaint_server")
logging.basicConfig(level=logging.INFO)
MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB por request (ajustable)
ALLOWED_FORMATS = {"PNG", "JPEG", "JPG"}
IMAGE_MIN_DIM = 64
IMAGE_MAX_DIM = 2048

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Configura tu API key
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

MODEL_IMAGE = "models/gemini-2.5-flash-image"
MODEL_TEXT = "models/gemini-2.0-flash"

def extract_image_b64(resp):
    try:
        if hasattr(resp, "images") and resp.images:
            img = resp.images[0]
            raw = getattr(img, "data", None) or getattr(img, "base64_data", None)
            if isinstance(raw, bytes):
                return base64.b64encode(raw).decode()
            if isinstance(raw, str):
                return raw
    except Exception:
        LOG.exception("extract_image_b64 failed")
    return None

def sanitize_model_text_to_json(text):
    if not text:
        return None
    # Primero intenta encontrar el primer objeto JSON {...}
    m = re.search(r"\{[\s\S]*?\}", text)
    if m:
        candidate = m.group(0)
        try:
            obj = json.loads(candidate)
            return obj
        except Exception:
            # si no parsea, intenta limpiar fences y backticks y volver a intentar
            pass
    # Quitar fenced code blocks y backticks como fallback
    cleaned = re.sub(r"```[\s\S]*?```", "", text)
    cleaned = cleaned.replace("`", "").strip()
    m2 = re.search(r"\{[\s\S]*?\}", cleaned)
    if m2:
        try:
            return json.loads(m2.group(0))
        except Exception:
            LOG.warning("sanitize_model_text_to_json: failed to parse after cleaning")
    return None

def validate_and_save_image(b64):
    # Decode
    try:
        img_bytes = base64.b64decode(b64)
    except Exception:
        raise ValueError("base64 inválido")

    if len(img_bytes) > MAX_CONTENT_LENGTH:
        raise ValueError("Imagen demasiado grande")

    # Validate with PIL
    try:
        im = Image.open(BytesIO(img_bytes))
        im.verify()  # valida integridad
    except Exception:
        raise ValueError("No es una imagen válida")

    # Reopen to get size (verify() can close file)
    im = Image.open(BytesIO(img_bytes))
    fmt = im.format.upper() if im.format else None
    if fmt not in ALLOWED_FORMATS:
        raise ValueError(f"Formato no soportado: {fmt}")

    w, h = im.size
    if w < IMAGE_MIN_DIM or h < IMAGE_MIN_DIM:
        raise ValueError("Imagen con dimensiones demasiado pequeñas")
    if w > IMAGE_MAX_DIM or h > IMAGE_MAX_DIM:
        # opcional: redimensionar en lugar de fallar
        LOG.info("Imagen grande: redimensionando a 1024 manteniendo ratio")
        im = im.convert("RGBA")
        im.thumbnail((1024, 1024), Image.LANCZOS)

        out = BytesIO()
        im.save(out, format="PNG")
        out_bytes = out.getvalue()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(out_bytes)
        tmp.flush()
        tmp.close()
        return tmp.name
    else:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        # Normalizamos a PNG
        try:
            im = im.convert("RGBA")
            im.save(tmp, format="PNG")
            tmp.flush()
            tmp.close()
            return tmp.name
        except Exception:
            tmp.close()
            os.remove(tmp.name)
            raise

@app.route("/generar_imagen", methods=["POST"])
def generar_imagen():
    tmp_path = None
    try:
        # Requerir consentimiento explícito en header (cliente debe enviar)
        consent_header = request.headers.get("X-Upload-Consent", "").lower()
        if consent_header not in ("true", "1", "yes"):
            return jsonify({"error": "Consentimiento de subida requerido (header X-Upload-Consent)"}), 403

        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON inválido."}), 400

        imagen_b64 = data.get("imagen")
        prompt_usuario = data.get("prompt", "")

        if not imagen_b64:
            return jsonify({"error": "Falta 'imagen'."}), 400

        # Validar y guardar la imagen temporalmente (y normalizar a PNG)
        try:
            tmp_path = validate_and_save_image(imagen_b64)
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400
        except Exception as ex:
            LOG.exception("Error validating image")
            return jsonify({"error": "Error procesando la imagen"}), 400

        imagen_generada = None
        actividad_generada_obj = None

        # 1) Generar imagen mejorada (llamada al modelo de imágenes)
        try:
            model_img = genai.GenerativeModel(MODEL_IMAGE)
            prompt_imagen = (
                "Mejora este dibujo de un niño pequeño: refuerza todas las líneas, "
                "suaviza colores y limpia trazos. Mantén la intención original, "
                "no añadas elementos nuevos. Devuélvelo como PNG, solo la imagen."
            )

            # Llamada protegida: puede fallar por quota o timeout
            resp_imagen = model_img.generate_content(contents=[
                prompt_imagen,
                {"inline_data": {"mime_type": "image/png", "data": imagen_b64}}
            ])
            imagen_generada = extract_image_b64(resp_imagen)
        except Exception:
            LOG.exception("Error al generar la imagen con el modelo")
            # No abortamos; podemos continuar solo con actividad textual
            imagen_generada = None

        # 2) Generar actividad en JSON con modelo de texto
        try:
            model_text = genai.GenerativeModel(MODEL_TEXT)
            prompt_actividad = (
                f"Eres un diseñador de juegos para niños de 5 a 8 años.\n"
                f"Basándote solo en el dibujo y en este texto del niño: \"{prompt_usuario}\"\n\n"
                "Genera UNA actividad simple y divertida. Responde EXCLUSIVAMENTE con JSON válido:\n"
                '{ "titulo": "...", "mision": "...", "instrucciones": ["Paso 1","Paso 2"], "duracion_minutos": 5, "materiales": ["..."], "reto_extra": "..." }'
            )

            resp_txt = model_text.generate_content(prompt_actividad)
            texto = getattr(resp_txt, "text", str(resp_txt) if resp_txt is not None else "")
            actividad_generada_obj = sanitize_model_text_to_json(texto)

            if actividad_generada_obj is None:
                LOG.warning("El modelo no devolvió JSON válido, enviando fallback")
                actividad_generada_obj = {
                    "titulo": "Actividad creativa",
                    "mision": "Inventa una historia corta sobre el dibujo",
                    "instrucciones": ["Di un nombre a tu dibujo", "Cuenta una historia en 3 frases", "Dibuja el final"],
                    "duracion_minutos": 5,
                    "materiales": ["Papel", "Lápices"],
                    "reto_extra": "Cambia el final de la historia"
                }
        except Exception:
            LOG.exception("Error al generar texto con el modelo")
            actividad_generada_obj = {
                "titulo": "Actividad creativa",
                "mision": "Inventa una historia corta sobre el dibujo",
                "instrucciones": ["Di un nombre a tu dibujo", "Cuenta una historia en 3 frases", "Dibuja el final"],
                "duracion_minutos": 5,
                "materiales": ["Papel", "Lápices"],
                "reto_extra": "Cambia el final de la historia"
            }

        # Responder: imagen como base64 (si se generó) y actividad como OBJETO JSON
        response_payload = {
            "imagen_generada": imagen_generada,  # puede ser None
            "actividad_generada": actividad_generada_obj,
            "modelo_usado": MODEL_IMAGE
        }
        return jsonify(response_payload), 200

    except Exception as e:
        LOG.exception("Error interno en /generar_imagen")
        return jsonify({"error": "Error interno"}), 500

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                LOG.debug("No se pudo eliminar el fichero temporal", exc_info=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # En desarrollo está bien, en Render usar gunicorn
    app.run(host="0.0.0.0", port=port)