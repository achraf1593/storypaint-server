# app.py — servidor compatible con tu IAClient Android
import base64
import tempfile
import os
import re
import json
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# Config — pon tu API key en la env GEMINI_API_KEY
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Model names
MODEL_IMAGE = "models/gemini-2.5-flash-image"   # modelo de imagen
MODEL_TEXT = "models/gemini-2.0-flash"         # modelo de texto

# ---------------------------------------------------------------------
# Utilities: detectar base64 / buscar recursivamente / extraer imagen
# ---------------------------------------------------------------------
def looks_like_base64(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s_stripped = re.sub(r"\s+", "", s)
    # evitar falsos positivos
    if len(s_stripped) < 200:
        return False
    return re.fullmatch(r"[A-Za-z0-9+/=]+", s_stripped) is not None

def find_base64_in_obj(obj, _seen=None):
    if _seen is None:
        _seen = set()
    try:
        oid = id(obj)
    except Exception:
        oid = None
    if oid in _seen:
        return None
    if oid is not None:
        _seen.add(oid)

    if isinstance(obj, str):
        if looks_like_base64(obj):
            return obj
        return None
    if isinstance(obj, (bytes, bytearray)):
        try:
            s = obj.decode("utf-8", errors="ignore")
            if looks_like_base64(s):
                return s
        except Exception:
            pass
        return None
    if isinstance(obj, dict):
        for v in obj.values():
            c = find_base64_in_obj(v, _seen)
            if c:
                return c
        return None
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            c = find_base64_in_obj(v, _seen)
            if c:
                return c
        return None
    # objetos con attrs
    for attr in ("images", "candidates", "content", "image", "inline_data", "data", "base64_data", "blob", "output"):
        if hasattr(obj, attr):
            try:
                val = getattr(obj, attr)
                c = find_base64_in_obj(val, _seen)
                if c:
                    return c
            except Exception:
                pass
    # try vars fallback
    try:
        d = vars(obj)
    except Exception:
        d = None
    if isinstance(d, dict):
        for v in d.values():
            c = find_base64_in_obj(v, _seen)
            if c:
                return c
    return None

def extraer_base64_de_respuesta(resp):
    """
    Robusta: maneja bytes, strings base64, y cadenas con bytes escapados como "\\211PNG..."
    Retorna None si no encuentra.
    """
    # 1) images[0].{base64_data,data,image_data,blob}
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
                    if isinstance(val, str) and ("\\211PNG" in val or "PNG" in val[:50]):
                        try:
                            unescaped = val.encode("utf-8").decode("unicode_escape")
                            bin_bytes = unescaped.encode("latin-1", errors="ignore")
                            return base64.b64encode(bin_bytes).decode("utf-8")
                        except Exception:
                            pass
    except Exception:
        pass

    # 2) candidates -> content.parts -> inline_data.data
    try:
        if hasattr(resp, "candidates") and getattr(resp, "candidates"):
            for cand in resp.candidates:
                content = getattr(cand, "content", None)
                try:
                    parts = getattr(content, "parts", None)
                    if parts:
                        for p in parts:
                            inline = getattr(p, "inline_data", None)
                            if inline:
                                d = getattr(inline, "data", None)
                                if isinstance(d, (bytes, bytearray)):
                                    return base64.b64encode(d).decode("utf-8")
                                if isinstance(d, str) and looks_like_base64(d):
                                    return d
                                if isinstance(d, str):
                                    try:
                                        unescaped = d.encode("utf-8").decode("unicode_escape")
                                        bin_bytes = unescaped.encode("latin-1", errors="ignore")
                                        return base64.b64encode(bin_bytes).decode("utf-8")
                                    except Exception:
                                        pass
                except Exception:
                    pass
                # fallback recursivo sobre content
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

    # 3) Buscar en texto completo (por si viene inline_data como texto escapado en _result)
    try:
        try:
            resp_text = json.dumps(resp.__dict__, default=str)
        except Exception:
            resp_text = str(resp)
        m = re.search(r'data:\s*"([^"]{200,})"', resp_text, flags=re.DOTALL)
        if m:
            raw = m.group(1)
            if looks_like_base64(raw):
                return raw
            try:
                unescaped = raw.encode("utf-8").decode("unicode_escape")
                bin_bytes = unescaped.encode("latin-1", errors="ignore")
                return base64.b64encode(bin_bytes).decode("utf-8")
            except Exception:
                pass
        m2 = re.search(r'(\\211PNG[\\\s\S]{100,20000}?)"', resp_text)
        if m2:
            raw = m2.group(1)
            try:
                unescaped = raw.encode("utf-8").decode("unicode_escape")
                bin_bytes = unescaped.encode("latin-1", errors="ignore")
                return base64.b64encode(bin_bytes).decode("utf-8")
            except Exception:
                pass
    except Exception:
        pass

    # 4) último recurso: búsqueda recursiva general
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

# ---------------------------------------------------------------------
# Extraer JSON limpio de la respuesta de texto (quita ```json``` etc.)
# ---------------------------------------------------------------------
def extract_json_from_text(s: str):
    if not isinstance(s, str):
        return None
    # buscar fence ```json ... ```
    m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", s, flags=re.DOTALL)
    if m:
        js = m.group(1)
        try:
            return json.loads(js)
        except Exception:
            return js
    # buscar primer bloque {...}
    m2 = re.search(r"(\{[\s\S]{20,}\})", s)
    if m2:
        js_text = m2.group(1)
        try:
            return json.loads(js_text)
        except Exception:
            return js_text
    s_strip = s.strip()
    if s_strip.startswith("{") and s_strip.endswith("}"):
        try:
            return json.loads(s_strip)
        except Exception:
            return s_strip
    return s

# ---------------------------------------------------------------------
# Endpoint que tu app Android espera: POST /generar_imagen
# Request: JSON { "imagen": "<base64 PNG>", "prompt": "..." }
# Response JSON: { "imagen_generada": "<base64 or null>", "actividad_generada": "<string JSON or fallback>", "modelo_usado": "..." }
# ---------------------------------------------------------------------
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

        # decodificar input
        try:
            imagen_bytes = base64.b64decode(imagen_b64)
        except Exception as e:
            return jsonify({"error": "La imagen base64 está corrupta.", "detalle": str(e)}), 400

        if len(imagen_bytes) < 500:
            return jsonify({"error": "Imagen demasiado pequeña o corrupta."}), 400

        # guardar temp file (opcional)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(imagen_bytes)
            tmp_path = tmp.name

        app.logger.info(f"Imagen recibida -> {tmp_path} ({len(imagen_bytes)} bytes)")

        # ---------- generar imagen usando modelo de imagen y enviar inline_data ----------
        imagen_generada_b64 = None
        try:
            model_img = genai.GenerativeModel(MODEL_IMAGE)

            # preparar contents: prompt + inline_data con la imagen original + instrucción clara
            img_resp = model_img.generate_content(
                contents=[
                    prompt,
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(imagen_bytes).decode("utf-8")
                        }
                    },
                    "Genera una imagen PNG completa (mínimo 256x256) basada en este dibujo, manteniendo colores y formas. Devuelve la imagen en el objeto de respuesta."
                ],
                # si tu SDK/versión soporta parámetros extra, puedes añadirlos aquí
                # generation_config={"response_mime_type": "image/png"}
            )

            # intentar extraer base64
            imagen_generada_b64 = extraer_base64_de_respuesta(img_resp)
            if imagen_generada_b64 is None:
                app.logger.warning("No se pudo extraer imagen generada. image field is None.")
        except Exception as e:
            app.logger.warning(f"Fallo generando imagen: {e}")
            imagen_generada_b64 = None

        # ---------- generar actividad textual con modelo de texto ----------
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

            parsed = extract_json_from_text(raw_act)
            if isinstance(parsed, dict):
                # lo enviamos como string JSON (tu cliente espera optString)
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
        # limpiar temp
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
