import base64
import tempfile
import os
import re
import json
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# Configurar tu API KEY
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Modelos
MODEL_IMAGE = "models/gemini-2.5-flash-image"
MODEL_TEXT = "models/gemini-2.0-flash"


def looks_like_base64(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s_stripped = re.sub(r"\s+", "", s)
    # mínimo 200 chars to avoid false positives
    if len(s_stripped) < 200:
        return False
    # base64 charset check (loosened)
    return re.fullmatch(r"[A-Za-z0-9+/=]+", s_stripped) is not None


def find_base64_in_obj(obj, _seen=None):
    """Recorre recursivamente objetos/dicts/listas/atributos buscando una cadena que parezca base64."""
    if _seen is None:
        _seen = set()
    oid = id(obj)
    if oid in _seen:
        return None
    _seen.add(oid)

    # strings
    if isinstance(obj, str):
        if looks_like_base64(obj):
            return obj
        return None

    # bytes
    if isinstance(obj, (bytes, bytearray)):
        try:
            # try decode bytes to base64-like string
            s = obj.decode("utf-8", errors="ignore")
            if looks_like_base64(s):
                return s
        except:
            pass
        return None

    # dict-like
    if isinstance(obj, dict):
        for k, v in obj.items():
            # keys like 'data', 'base64', 'base64_data', 'image' are interesting
            if isinstance(k, str) and k.lower() in ("data", "image", "base64", "base64_data", "inline_data"):
                candidate = find_base64_in_obj(v, _seen)
                if candidate:
                    return candidate
            else:
                candidate = find_base64_in_obj(v, _seen)
                if candidate:
                    return candidate
        return None

    # list/tuple
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            candidate = find_base64_in_obj(v, _seen)
            if candidate:
                return candidate
        return None

    # object with attrs: try common attr names then fallback to vars()
    for attr in ("images", "candidates", "content", "image", "inline_data", "data", "base64_data", "blob", "output"):
        if hasattr(obj, attr):
            try:
                val = getattr(obj, attr)
                candidate = find_base64_in_obj(val, _seen)
                if candidate:
                    return candidate
            except Exception:
                pass

    # try vars(obj) safely
    try:
        d = vars(obj)
    except Exception:
        d = None
    if isinstance(d, dict):
        for v in d.values():
            candidate = find_base64_in_obj(v, _seen)
            if candidate:
                return candidate

    return None


def extraer_base64_de_respuesta(resp):
    """
    Intenta extraer la base64 de la respuesta de Gemini de forma robusta.
    Primero intenta rutas comunes, luego escanea recursivamente.
    """
    # Rutas comunes conocidas
    try:
        if hasattr(resp, "images") and getattr(resp, "images"):
            img = resp.images[0]
            for attr in ("base64_data", "data", "image_data"):
                if hasattr(img, attr):
                    val = getattr(img, attr)
                    if val:
                        return val
    except Exception:
        pass

    try:
        if hasattr(resp, "candidates") and getattr(resp, "candidates"):
            for cand in resp.candidates:
                # cand.content puede ser lista de partes
                content = getattr(cand, "content", None)
                candidate = find_base64_in_obj(content)
                if candidate:
                    return candidate
    except Exception:
        pass

    # Fallback genérico: buscar en todo el objeto
    candidate = find_base64_in_obj(resp)
    if candidate:
        return candidate

    return None


@app.route("/generar_imagen", methods=["POST"])
def generar_imagen():
    tmp_path = None
    try:
        data = request.get_json()

        # ---------------------------
        # VALIDACIÓN DEL REQUEST
        # ---------------------------
        if not data or "imagen" not in data:
            return jsonify({"error": "Falta el campo 'imagen' en la solicitud."}), 400
        if "prompt" not in data:
            return jsonify({"error": "Falta el campo 'prompt'."}), 400

        imagen_b64 = data["imagen"]
        prompt = data["prompt"]

        # ---------------------------
        # DECODIFICAR BASE64
        # ---------------------------
        try:
            imagen_bytes = base64.b64decode(imagen_b64)
        except Exception as e:
            return jsonify({"error": "La imagen base64 está corrupta.", "detalle": str(e)}), 400

        if len(imagen_bytes) < 500:
            return jsonify({"error": "Imagen demasiado pequeña o corrupta."}), 400

        # Guardar a archivo temporal
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(imagen_bytes)
            tmp_path = tmp.name

        app.logger.info(f"Imagen recibida -> {tmp_path} ({len(imagen_bytes)} bytes)")

        # ---------------------------
        # GENERAR IMAGEN NUEVA (FORMATO CORRECTO)
        # ---------------------------
        imagen_generada_b64 = None
        try:
            model_img = genai.GenerativeModel(MODEL_IMAGE)

            with open(tmp_path, "rb") as f:
                imagen_bytes_for_model = f.read()

            # ---> Aquí: inline_data con mime_type + data
            img_resp = model_img.generate_content(
                contents=[
                    prompt,
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(imagen_bytes_for_model).decode("utf-8")
                        }
                    },
                    "Genera una nueva imagen creativa basada en este dibujo, conservando colores y formas."
                ]
            )

            # -------------------------------
            # 🔥 DEBUG: RESPUESTA CRUDA (IMAGEN)
            # -------------------------------
            print("\n========== DEBUG RESPUESTA MODELO RAW (IMAGEN) ==========")
            try:
                # si es convertible a JSON decente
                print(json.dumps(img_resp.__dict__, default=str, indent=2))
            except Exception:
                print(str(img_resp))
            print("========================================================\n")

            app.logger.debug(f"Respuesta raw del modelo (imagen): {str(img_resp)[:2000]}")

            # Extraer imagen en base64 de manera robusta
            imagen_generada_b64 = extraer_base64_de_respuesta(img_resp)
            if imagen_generada_b64 is None:
                app.logger.warning("No se pudo extraer imagen generada. image field is None.")

        except Exception as e:
            app.logger.warning(f"Fallo generando imagen: {e}")
            imagen_generada_b64 = None

        # ---------------------------
        # GENERAR ACTIVIDAD (TEXTO)
        # ---------------------------
        actividad_generada = None
        try:
            model_text = genai.GenerativeModel(MODEL_TEXT)

            prompt_text = (
                "Eres un educador creativo. A partir de este dibujo y prompt, "
                "crea UNA actividad segura para niños de 5-8 años. Debe incluir:\n"
                "- titulo (1 línea)\n"
                "- instrucciones paso a paso (3-5 pasos)\n"
                "- duracion_minutos\n"
                "- materiales simples\n"
                "Responde SOLO en JSON válido.\n"
                f"Prompt original: {prompt}"
            )

            txt_resp = model_text.generate_content(prompt_text)

            # -------------------------------
            # 🔥 DEBUG: RESPUESTA CRUDA (TEXTO)
            # -------------------------------
            print("\n========== DEBUG RESPUESTA MODELO RAW (TEXTO) ==========")
            try:
                print(json.dumps(txt_resp.__dict__, default=str, indent=2))
            except Exception:
                print(str(txt_resp))
            print("======================================================\n")
            app.logger.debug(f"Respuesta raw del modelo (texto): {str(txt_resp)[:2000]}")

            # intenta obtener texto directo
            actividad_generada = getattr(txt_resp, "text", None) or find_base64_in_obj(txt_resp) or str(txt_resp)

        except Exception as e:
            app.logger.warning(f"Fallo generando actividad textual: {e}")
            actividad_generada = None

        # ---------------------------
        # RESPUESTA FINAL
        # ---------------------------
        return jsonify({
            "imagen_generada": imagen_generada_b64,
            "actividad_generada": actividad_generada,
            "modelo_usado": MODEL_IMAGE
        })

    except Exception as e:
        app.logger.error(f"Error general en /generar_imagen: {e}")
        return jsonify({"error": "Error interno del servidor", "detalle": str(e)}), 500

    finally:
        # intentar limpiar el temp file
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
