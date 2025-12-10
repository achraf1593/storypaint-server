import base64
import tempfile
import os
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# Configurar tu API KEY
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Modelos
MODEL_IMAGE = "models/gemini-2.5-flash-image"
MODEL_TEXT = "models/gemini-2.0-flash"


def extraer_base64_de_respuesta(resp):
    """Extrae de manera robusta la base64 de la imagen generada."""
    # Primer intento: .images
    if hasattr(resp, "images") and resp.images:
        return resp.images[0].base64_data

    # Segundo intento: candidates -> content -> image
    if hasattr(resp, "candidates") and resp.candidates:
        candidate = resp.candidates[0]
        content = getattr(candidate, "content", [])
        if content and hasattr(content[0], "image"):
            img = getattr(content[0], "image", None)
            if img is None:
                return None
            if hasattr(img, "base64_data"):
                return img.base64_data
            if hasattr(img, "inline_data") and hasattr(img.inline_data, "data"):
                return img.inline_data.data

    return None


@app.route("/generar_imagen", methods=["POST"])
def generar_imagen():
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
        # GENERAR IMAGEN NUEVA
        # ---------------------------
        imagen_generada_b64 = None
        try:
            model_img = genai.GenerativeModel(MODEL_IMAGE)

            with open(tmp_path, "rb") as f:
                imagen_bytes_for_model = f.read()

            img_resp = model_img.generate_content(
                contents=[
                    prompt,
                    {"image": base64.b64encode(imagen_bytes_for_model).decode("utf-8")},
                    "Genera una nueva imagen creativa basada en este dibujo."
                ]
            )

            # -------------------------------
            # 🔥 DEBUG: RESPUESTA CRUDA
            # -------------------------------
            print("\n========== DEBUG RESPUESTA MODELO RAW ==========")
            print(img_resp)
            print("================================================\n")

            app.logger.debug(f"Respuesta raw del modelo: {img_resp}")

            imagen_generada_b64 = extraer_base64_de_respuesta(img_resp)
            if imagen_generada_b64 is None:
                app.logger.warning("No se pudo extraer imagen generada.")

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
                "crea una actividad para niños 5–8 años con título, pasos, materiales "
                "y duración. Responde SOLO en JSON.\n"
                f"Prompt: {prompt}"
            )

            txt_resp = model_text.generate_content(prompt_text)
            actividad_generada = getattr(txt_resp, "text", None) or str(txt_resp)

        except Exception as e:
            app.logger.warning(f"Fallo generando actividad textual: {e}")
            actividad_generada = None

        # ---------------------------
        # RESPUESTA FINAL
        # ---------------------------
        return jsonify({
            "imagen_generada": imagen_generada_b64,
            "actividad_generada"S: actividad_generada,
            "modelo_usado": MODEL_IMAGE
        })

    except Exception as e:
        app.logger.error(f"Error general en /generar_imagen: {e}")
        return jsonify({"error": "Error interno del servidor", "detalle": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
