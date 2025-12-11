import base64
import json
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
from google.oauth2 import service_account
import uvicorn

# ================================
#  CONFIGURACIÓN BASE
# ================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =======================================
#   CLASE DE ENTRADA
# =======================================

class PromptActividad(BaseModel):
    prompt: str
    idioma: str = "es"

# =======================================
#   DETECCIÓN BASE64 SIMPLE
# =======================================

def looks_like_base64(s: str):
    if not isinstance(s, str):
        return False
    if len(s) < 50:
        return False
    return re.fullmatch(r"[A-Za-z0-9+/=]+", s) is not None

# =======================================
#   ESCANEO RECURSIVO DE OBJETOS
# =======================================

def find_base64_in_obj(obj):
    if obj is None:
        return None

    if isinstance(obj, (bytes, bytearray)):
        return obj

    if isinstance(obj, str):
        if looks_like_base64(obj):
            return obj
        m = re.search(r"[A-Za-z0-9+/=]{200,}", obj)
        if m:
            return m.group(0)
        return None

    if isinstance(obj, dict):
        for v in obj.values():
            found = find_base64_in_obj(v)
            if found:
                return found

    if isinstance(obj, (list, tuple)):
        for item in obj:
            found = find_base64_in_obj(item)
            if found:
                return found

    for attr in dir(obj):
        if attr.startswith("_"):
            continue
        try:
            val = getattr(obj, attr)
            found = find_base64_in_obj(val)
            if found:
                return found
        except Exception:
            continue

    return None

# =======================================
#   FUNCIÓN PRINCIPAL: EXTRAER BASE64
# =======================================

def extraer_base64_de_respuesta(resp):
    """
    Extrae base64 de la respuesta de Gemini de forma robusta.
    """
    # 1) RUTAS CONOCIDAS
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

    # 2) CANDIDATES / INLINE_DATA
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
                                    except:
                                        pass
                except:
                    pass

                candidate = find_base64_in_obj(content)
                if candidate:
                    if isinstance(candidate, (bytes, bytearray)):
                        return base64.b64encode(candidate).decode("utf-8")
                    if isinstance(candidate, str) and looks_like_base64(candidate):
                        return candidate
                    m = re.search(r"[A-Za-z0-9+/=]{200,}", str(candidate))
                    if m:
                        return m.group(0)
    except:
        pass

    # 3) BÚSQUEDA EN TEXTO COMPLETO
    try:
        try:
            resp_text = json.dumps(resp.__dict__, default=str)
        except:
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
            except:
                pass

        m2 = re.search(r'(\\211PNG[\\\s\S]{100,20000}?)"', resp_text)
        if m2:
            raw = m2.group(1)
            try:
                unescaped = raw.encode("utf-8").decode("unicode_escape")
                bin_bytes = unescaped.encode("latin-1", errors="ignore")
                return base64.b64encode(bin_bytes).decode("utf-8")
            except:
                pass
    except:
        pass

    # 4) RECURSIVO FINAL
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

# =======================================
#   GENERAR IMAGEN CON GEMINI
# =======================================

def generar_imagen_gemini(prompt):
    model = genai.GenerativeModel("gemini-2.0-flash")
    resp = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "image/png"}
    )

    base64_img = extraer_base64_de_respuesta(resp)
    if not base64_img:
        raise Exception("No se pudo extraer imagen desde Gemini")

    return base64_img

# =======================================
#   ENDPOINT PRINCIPAL
# =======================================

@app.post("/generar-actividad")
async def generar_actividad(data: PromptActividad):
    prompt_usuario = data.prompt
    idioma = data.idioma

    prompt_llm = f"""
Genera una actividad educativa infantil en el idioma '{idioma}' basada en:
"{prompt_usuario}"

Entrega solo JSON:
{{
  "actividad": "texto",
  "imagen_base64": "..."
}}
"""

    model = genai.GenerativeModel("gemini-2.0-flash")
    resp = model.generate_content(prompt_llm)

    actividad_generada = (resp.text or "").strip()

    imagen_base64 = generar_imagen_gemini(prompt_usuario)

    return {
        "actividad": actividad_generada,
        "imagen_base64": imagen_base64
    }

# =======================================
#   INICIAR SERVIDOR
# =======================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
