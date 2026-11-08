"""
Agente de Transcricao de Audio (Audio Transcriber Agent)
Utiliza o modelo faster-whisper (open-source) para transcrever
audios e mensagens de voz enviadas por fornecedores (Telegram ou Web)
em texto limpo em portugues, repassando diretamente ao agente interpretador.
"""

import os
import io
import tempfile
from typing import Union, BinaryIO

_whisper_model = None

def get_whisper_model():
    """Inicializacao sob demanda (lazy) do modelo Whisper."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        model_size = os.getenv("WHISPER_MODEL_SIZE", "base")
        print(f"[audio_agent] Inicializando modelo faster-whisper '{model_size}' em CPU (int8)...")
        _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        print(f"[audio_agent] Modelo faster-whisper pronto.")
    return _whisper_model

def transcribe_audio(audio_source: Union[str, bytes, BinaryIO], filename_hint: str = "audio.ogg") -> str:
    """
    Transcreve um arquivo de audio ou bytes para texto em portugues.
    Suporta .ogg (Opus do Telegram), .mp3, .wav, .m4a, etc.
    """
    model = get_whisper_model()
    temp_path = None

    try:
        if isinstance(audio_source, (bytes, bytearray)):
            suffix = os.path.splitext(filename_hint)[1] or ".ogg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(audio_source)
                temp_path = tmp.name
            target = temp_path
        elif hasattr(audio_source, "read"):
            suffix = os.path.splitext(filename_hint)[1] or ".ogg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(audio_source.read())
                temp_path = tmp.name
            target = temp_path
        elif isinstance(audio_source, str):
            target = audio_source
        else:
            raise ValueError(f"Formato de audio nao suportado: {type(audio_source)}")

        # Transcricao com linguagem fixada em portugues (pt)
        segments, info = model.transcribe(
            target,
            language="pt",
            beam_size=5,
            vad_filter=True,  # filtra silencios
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        texts = []
        for segment in segments:
            t = segment.text.strip()
            if t:
                texts.append(t)

        transcription = " ".join(texts).strip()
        print(f"[audio_agent] Transcricao concluida ({info.duration:.1f}s, prob: {info.language_probability:.2f}): '{transcription}'")
        return transcription

    except Exception as e:
        print(f"[audio_agent] Erro ao transcrever audio: {e}")
        raise e
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
