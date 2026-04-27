from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.core.config import settings
from app.services.incident_ai import normalize_text


VISION_MODEL_VERSION = "vision-classifier-ready-v1"
IMAGE_EVIDENCE_TYPES = {"imagen", "image", "foto", "photo", "picture"}


@dataclass(slots=True)
class VisionInferenceResult:
    incident_type: str
    confidence: Decimal
    provider: str
    model_version: str
    summary: str
    source: str
    used_trained_model: bool

    def as_evidence_analysis(self) -> str:
        trained_flag = "modelo entrenado" if self.used_trained_model else "fallback local"
        return (
            f"Vision IA ({trained_flag}): imagen sugiere {self.incident_type} "
            f"con confianza {self.confidence}%. {self.summary}"
        )


class TrainedVisionClassifier:
    """Adapter for a trained visual classifier.

    The project keeps inference optional: if ONNX Runtime/Pillow/model files are not
    installed, it returns an explainable local fallback so the academic demo remains
    functional while the trained model artifact is plugged in later.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        provider: str,
        model_path: str | None,
        labels_path: str | None,
        input_size: int,
        confidence_threshold: float,
    ) -> None:
        self.enabled = enabled
        self.provider = provider
        self.model_path = Path(model_path) if model_path else None
        self.labels_path = Path(labels_path) if labels_path else None
        self.input_size = input_size
        self.confidence_threshold = Decimal(str(confidence_threshold))
        self._labels = self._load_labels()

    @classmethod
    def from_settings(cls) -> "TrainedVisionClassifier":
        return cls(
            enabled=settings.ai_vision_enabled,
            provider=settings.ai_vision_provider,
            model_path=settings.ai_vision_model_path,
            labels_path=settings.ai_vision_labels_path,
            input_size=settings.ai_vision_input_size,
            confidence_threshold=settings.ai_vision_confidence_threshold,
        )

    def analyze(self, resource_url: str, evidence_type: str | None = None) -> VisionInferenceResult | None:
        if not self.enabled or normalize_text(evidence_type) not in IMAGE_EVIDENCE_TYPES:
            return None
        trained_result = self._try_trained_model(resource_url)
        if trained_result:
            return trained_result
        return self._fallback_from_resource(resource_url)

    def _try_trained_model(self, resource_url: str) -> VisionInferenceResult | None:
        if self.provider not in {"onnx", "onnxruntime"}:
            return None
        if not self.model_path or not self.model_path.exists():
            return None
        local_path = _resolve_local_path(resource_url)
        if not local_path or not local_path.exists():
            return None

        try:
            import numpy as np  # type: ignore
            from PIL import Image  # type: ignore
            import onnxruntime as ort  # type: ignore
        except Exception:
            return None

        try:
            image = Image.open(local_path).convert("RGB").resize((self.input_size, self.input_size))
            image_array = np.asarray(image).astype("float32") / 255.0
            image_array = np.transpose(image_array, (2, 0, 1))[None, ...]
            session = ort.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])
            input_name = session.get_inputs()[0].name
            output = session.run(None, {input_name: image_array})[0][0]
            probabilities = _softmax(output)
            best_index = int(probabilities.argmax())
            confidence = Decimal(str(round(float(probabilities[best_index]) * 100, 2)))
            incident_type = self._labels.get(str(best_index), self._labels.get(best_index, "otro"))
            if confidence < self.confidence_threshold * Decimal("100"):
                incident_type = "otro"
            return VisionInferenceResult(
                incident_type=incident_type,
                confidence=confidence,
                provider="onnxruntime",
                model_version=VISION_MODEL_VERSION,
                summary=f"Inferencia visual ejecutada con {self.model_path.name}.",
                source=str(local_path),
                used_trained_model=True,
            )
        except Exception:
            return None

    def _fallback_from_resource(self, resource_url: str) -> VisionInferenceResult:
        normalized = normalize_text(unquote(resource_url))
        labels = {
            "choque": ("choque", "Se detectaron señales nominales de colision en la evidencia."),
            "accidente": ("choque", "Se detectaron señales nominales de accidente en la evidencia."),
            "llanta": ("llanta", "La evidencia referencia llanta/neumatico."),
            "rueda": ("llanta", "La evidencia referencia rueda/neumatico."),
            "motor": ("motor", "La evidencia referencia motor o falla mecanica."),
            "bateria": ("bateria", "La evidencia referencia bateria o encendido."),
            "electrico": ("electrico", "La evidencia referencia sistema electrico."),
            "cerradura": ("cerradura", "La evidencia referencia cerradura o llave."),
            "remolque": ("remolque", "La evidencia referencia grua/remolque."),
            "grua": ("remolque", "La evidencia referencia grua/remolque."),
        }
        for keyword, (incident_type, summary) in labels.items():
            if keyword in normalized:
                return VisionInferenceResult(
                    incident_type=incident_type,
                    confidence=Decimal("72.00"),
                    provider="local_heuristic",
                    model_version=VISION_MODEL_VERSION,
                    summary=summary,
                    source=resource_url,
                    used_trained_model=False,
                )
        return VisionInferenceResult(
            incident_type="otro",
            confidence=Decimal("50.00"),
            provider="local_heuristic",
            model_version=VISION_MODEL_VERSION,
            summary="Sin modelo visual entrenado disponible; se conserva la evidencia para reprocesamiento.",
            source=resource_url,
            used_trained_model=False,
        )

    def _load_labels(self) -> dict:
        if not self.labels_path or not self.labels_path.exists():
            return {
                "0": "bateria",
                "1": "llanta",
                "2": "motor",
                "3": "choque",
                "4": "electrico",
                "5": "cerradura",
                "6": "remolque",
                "7": "otro",
            }
        with self.labels_path.open("r", encoding="utf-8") as labels_file:
            data = json.load(labels_file)
        if isinstance(data, list):
            return {str(index): label for index, label in enumerate(data)}
        return data


def analyze_image_evidence(resource_url: str, evidence_type: str | None = None) -> VisionInferenceResult | None:
    return TrainedVisionClassifier.from_settings().analyze(resource_url, evidence_type)


def _resolve_local_path(resource_url: str) -> Path | None:
    parsed = urlparse(resource_url)
    if parsed.scheme in {"", "file"}:
        return Path(unquote(parsed.path if parsed.scheme else resource_url))
    return None


def _softmax(values):
    import numpy as np  # type: ignore

    shifted = values - np.max(values)
    exp_values = np.exp(shifted)
    return exp_values / exp_values.sum()
