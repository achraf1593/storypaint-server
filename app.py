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
    if len(s_stripped) < 200:
        return False
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
            s = obj.decode("utf-8", errors="ignore")
            if looks_like_base64(s):
                return s
        except:
            pass
        return None

    # dict-like
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in ("data", "image", "base64", "base64_data", "inline_data"):
                candidate = find_base64_in_obj(v, _seen)
                if candidate:
                    return candidate
            else:
                candidate = find_base64_in_obj(v, _seen)
                if candidate:
                    return candidate
        return None

    # list/tuple/set
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            candidate = find_base64_in_obj(v, _seen)
            if candidate:
                return candidate
        return None

    # object attributes
    for attr in ("images", "candidates", "content", "image", "inline_data", "data", "base64_data", "blob", "output"):
        if hasattr(obj, attr):
            try:
                val = getattr(obj, attr)
                candidate = find_base64_in_obj(val, _seen)
                if candidate:
                    return candidate
            except Exception:
                pass

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
    Extrae base64 de la respuesta de Gemini de forma robusta.
    Maneja rutas conocidas, bytes y strings con fence ```json``` alrededor.
    """
    try:
        if hasattr(resp, "images") and getattr(resp, "images"):
            img = resp.images[0]
            for attr in ("base64_data", "data", "image_data", "blob"):
                if hasattr(img, attr):
                    val = getattr(img, attr)
                    if isinstance(val, (bytes, bytearray)):
                        return base64.b64encode(val).decode("utf-8")
                    if isinstance(val, str) and looks_like_base64(val):
                        return val
    except Exception:
        pass

    try:
        if hasattr(resp, "candidates") and getattr(resp, "candidates"):
            for cand in resp.candidates:
                content = getattr(cand, "content", None)
                candidate = find_base64_in_obj(content)
                if candidate:
                    if isinstance(candidate, (bytes, bytearray)):
                        return base64.b64encode(candidate).decode("utf-8")
                    if isinstance(candidate, str) and looks_like_base64(candidate):
                        return candidate
                    m = re.search(r"[A-Za-z0-9+/=]{200,}", str(candidate))
                    if m:
                        return m.group(0)
    except Exception:
        pass

    candidate = find_base64_in_obj(resp)
    if candidate:
        if isinstance(candidate, (bytes, bytearray)):
            return base64.b64encode(candidate).decode("utf-8")
        if isinstance(candidate, str) and looks_like_base64(candidate):
            return candidate
        m = re.search(r"[A-Za-z0-9+/=]{200,}", str(candidate))
        if m:
            return m.group(0)

    return None


@app.route("/generar_imagen", methods=["POST"])
def generar_imagen():
    tmp_path = None
    try:
        data = request.get_json()
        if not data or "imagen" not in data:
            return jsonify({"error": "Falta el campo 'imagen' en la solicitud."}), 400
        if "prompt" not in data:
            return jsonify({"error": "Falta el campo 'prompt'."}), 400

        imagen_b64 = data["imagen"]
        prompt = data["prompt"]

        try:
            imagen_bytes = base64.b64decode(imagen_b64)
        except Exception as e:
            return jsonify({"error": "La imagen base64 está corrupta.", "detalle": str(e)}), 400

        if len(imagen_bytes) < 500:
            return jsonify({"error": "Imagen demasiado pequeña o corrupta."}), 400

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(imagen_bytes)
            tmp_path = tmp.name

        app.logger.info(f"Imagen recibida -> {tmp_path} ({len(imagen_bytes)} bytes)")

        imagen_generada_b64 = None
        try:
            model_img = genai.GenerativeModel(MODEL_IMAGE)
            with open(tmp_path, "rb") as f:
                imagen_bytes_for_model = f.read()

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

            app.logger.debug(f"Respuesta raw del modelo (imagen): {str(img_resp)[:2000]}")
            imagen_generada_b64 = extraer_base64_de_respuesta(img_resp)
            if imagen_generada_b64 is None:
                app.logger.warning("No se pudo extraer imagen generada. image field is None.")

        except Exception as e:
            app.logger.warning(f"Fallo generando imagen: {e}")
            imagen_generada_b64 = None

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

            raw_act = getattr(txt_resp, "text", None) or find_base64_in_obj(txt_resp) or str(txt_resp)

            def extract_json_from_text(s: str):
                if not isinstance(s, str):
                    return None
                m = re.search(r"```json\\s*(\\{.*?\\})\\s*```", s, flags=re.DOTALL)
                if m:
                    try:
                        return json.loads(m.group(1))
                    except Exception:
                        return m.group(1)
                m2 = re.search(r"(\\{[\\s\\S]{50,}\\})", s)
                if m2:
                    js_text = m2.group(1)
                    try:
                        return json.loads(js_text)
                    except Exception:
                        return js_text
                s_stripped = s.strip()
                if s_stripped.startswith("{") and s_stripped.endswith("}"):
                    try:
                        return json.loads(s_stripped)
                    except Exception:
                        return s_stripped
                return s

            parsed = extract_json_from_text(raw_act)
            if isinstance(parsed, dict):
                actividad_generada = json.dumps(parsed, ensure_ascii=False)
            else:
                actividad_generada = parsed

        except Exception as e:
            app.logger.warning(f"Fallo generando actividad textual: {e}")
            actividad_generada = None

        return jsonify({
            "imagen_generada": imagen_generada_b64,
            "actividad_generada": actividad_generada,
            "modelo_usado": MODEL_IMAGE
        })

    except Exception as e:
        app.logger.error(f"Error general en /generar_imagen: {e}")
        return jsonify({"error": "Error interno del servidor", "detalle": str(e)}), 500

    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
