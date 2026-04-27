from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt
import re
import unicodedata
from typing import Any, Iterable


MODEL_PROVIDER = "local-incident-ai"
MODEL_VERSION = "v1.0-deterministic"


@dataclass(slots=True)
class IncidentAIAnalysis:
    incident_type: str
    required_specialty: str
    suggested_priority: str
    confidence: Decimal
    summary: str
    risk_signals: list[str] = field(default_factory=list)
    matched_keywords: dict[str, list[str]] = field(default_factory=dict)
    evidence_summary: str | None = None
    criteria: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AssignmentCandidateResult:
    workshop_id: int
    workshop_name: str
    branch_id: int | None
    branch_name: str | None
    worker_id: int | None
    worker_name: str | None
    score: Decimal
    distance_km: Decimal | None
    eta_minutes: int | None
    criteria: dict[str, Any]
    reason: str


TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "bateria": (
        "bateria",
        "batery",
        "arranca",
        "encender",
        "encendido",
        "alternador",
        "borne",
        "sin corriente",
    ),
    "llanta": (
        "llanta",
        "goma",
        "pinchazo",
        "pinchada",
        "neumatico",
        "rueda",
        "reventon",
    ),
    "motor": (
        "motor",
        "sobrecalienta",
        "calienta",
        "humo",
        "aceite",
        "correa",
        "mecanica",
        "no acelera",
    ),
    "choque": (
        "choque",
        "accidente",
        "colision",
        "golpe",
        "impacto",
        "abollado",
        "herido",
        "siniestro",
    ),
    "electrico": (
        "electrico",
        "luces",
        "fusible",
        "cable",
        "sensor",
        "tablero",
        "alarma",
        "corto",
    ),
    "cerradura": (
        "llave",
        "cerradura",
        "bloqueado",
        "encerrada",
        "encerrado",
        "puerta",
        "inmovilizador",
    ),
    "remolque": (
        "remolque",
        "grua",
        "varado",
        "traslado",
        "no se mueve",
        "atascado",
        "auxilio vial",
    ),
}

HIGH_RISK_KEYWORDS = (
    "herido",
    "heridos",
    "fuego",
    "incendio",
    "humo",
    "choque",
    "accidente",
    "colision",
    "autopista",
    "carretera",
    "noche",
    "niños",
    "embarazada",
)

MEDIUM_RISK_KEYWORDS = (
    "varado",
    "remolque",
    "grua",
    "sobrecalienta",
    "no arranca",
    "sin corriente",
    "avenida",
    "anillo",
    "trafico",
)

PRIORITY_ORDER = {"baja": 1, "media": 2, "alta": 3}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    without_accents = unicodedata.normalize("NFKD", value)
    ascii_text = without_accents.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def choose_highest_priority(*priorities: str | None) -> str:
    normalized = [normalize_text(priority) for priority in priorities if priority]
    return max(normalized or ["media"], key=lambda item: PRIORITY_ORDER.get(item, 2))


def analyze_incident(
    *,
    description_text: str | None,
    address_text: str | None,
    manual_incident_type: str | None,
    evidences: Iterable[Any] = (),
    requested_priority: str | None = None,
) -> IncidentAIAnalysis:
    evidence_texts: list[str] = []
    image_signals = 0
    audio_signals = 0
    for evidence in evidences:
        transcription = getattr(evidence, "audio_transcription", None)
        analysis = getattr(evidence, "ai_analysis", None)
        evidence_type = normalize_text(getattr(evidence, "evidence_type", ""))
        if transcription:
            audio_signals += 1
            evidence_texts.append(transcription)
        if analysis:
            image_signals += 1 if evidence_type in {"imagen", "image", "foto"} else 0
            evidence_texts.append(analysis)

    combined_text = " ".join(
        item
        for item in [
            description_text or "",
            address_text or "",
            manual_incident_type or "",
            *evidence_texts,
        ]
        if item
    )
    normalized = normalize_text(combined_text)
    matched_keywords: dict[str, list[str]] = {}
    scores: dict[str, int] = {}
    for incident_type, keywords in TYPE_KEYWORDS.items():
        matched = [keyword for keyword in keywords if keyword in normalized]
        if matched:
            matched_keywords[incident_type] = matched
            scores[incident_type] = len(matched)

    manual_type = normalize_text(manual_incident_type)
    if manual_type in TYPE_KEYWORDS:
        scores[manual_type] = scores.get(manual_type, 0) + 2
        matched_keywords.setdefault(manual_type, []).append("tipo manual reportado")

    incident_type = max(scores, key=scores.get) if scores else manual_type or "otro"
    if any(keyword in normalized for keyword in ("choque", "accidente", "colision", "siniestro", "impacto")):
        incident_type = "choque"
    elif any(keyword in normalized for keyword in ("grua", "remolque", "traslado", "no se mueve")):
        incident_type = "remolque"
    if incident_type not in TYPE_KEYWORDS:
        incident_type = "otro"

    high_risks = [keyword for keyword in HIGH_RISK_KEYWORDS if keyword in normalized]
    medium_risks = [keyword for keyword in MEDIUM_RISK_KEYWORDS if keyword in normalized]
    type_priority = "alta" if incident_type in {"choque", "remolque"} else "media"
    if incident_type in {"bateria", "llanta", "cerradura"} and not high_risks:
        type_priority = "baja"
    suggested_priority = choose_highest_priority(
        requested_priority,
        "alta" if high_risks else None,
        "media" if medium_risks else None,
        type_priority,
    )

    keyword_strength = max(scores.values(), default=0)
    confidence_value = Decimal(55 + min(keyword_strength * 9, 28) + min(len(evidence_texts) * 4, 10))
    if manual_type and manual_type == incident_type:
        confidence_value += Decimal("7")
    confidence_value = min(confidence_value, Decimal("97"))

    summary_source = description_text or "Incidente reportado sin descripcion textual extensa."
    summary = summary_source.strip()
    if len(summary) > 180:
        summary = f"{summary[:177].rstrip()}..."
    summary = (
        f"Clasificacion local: {incident_type}. "
        f"Prioridad sugerida: {suggested_priority}. {summary}"
    )

    evidence_summary = None
    if evidence_texts:
        evidence_summary = f"{len(evidence_texts)} evidencia(s) textualizadas: audio={audio_signals}, imagen={image_signals}."

    return IncidentAIAnalysis(
        incident_type=incident_type,
        required_specialty=incident_type if incident_type != "otro" else "motor",
        suggested_priority=suggested_priority,
        confidence=confidence_value.quantize(Decimal("0.01")),
        summary=summary,
        risk_signals=[*high_risks, *medium_risks],
        matched_keywords=matched_keywords,
        evidence_summary=evidence_summary,
        criteria={
            "keyword_scores": scores,
            "manual_type": manual_type or None,
            "requested_priority": requested_priority,
            "selected_priority": suggested_priority,
            "text_length": len(normalized),
        },
    )


def calculate_distance_km(
    origin_latitude: Decimal | None,
    origin_longitude: Decimal | None,
    destination_latitude: Decimal | None,
    destination_longitude: Decimal | None,
) -> Decimal | None:
    if None in {origin_latitude, origin_longitude, destination_latitude, destination_longitude}:
        return None
    lat1 = radians(float(origin_latitude))
    lon1 = radians(float(origin_longitude))
    lat2 = radians(float(destination_latitude))
    lon2 = radians(float(destination_longitude))
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    distance = 6371 * 2 * asin(sqrt(value))
    return Decimal(str(round(distance, 2)))


def rank_assignment_candidates(
    *,
    incident_latitude: Decimal,
    incident_longitude: Decimal,
    required_specialty: str,
    workshops: Iterable[Any],
    limit: int = 5,
) -> list[AssignmentCandidateResult]:
    candidates: list[AssignmentCandidateResult] = []
    normalized_specialty = normalize_text(required_specialty)
    for workshop in workshops:
        if not _workshop_can_receive(workshop):
            continue
        branch = _nearest_active_branch(workshop, incident_latitude, incident_longitude)
        origin_latitude = getattr(branch, "latitude", None) if branch else getattr(workshop, "latitude", None)
        origin_longitude = getattr(branch, "longitude", None) if branch else getattr(workshop, "longitude", None)
        distance_km = calculate_distance_km(origin_latitude, origin_longitude, incident_latitude, incident_longitude)
        coverage_radius = Decimal(str(getattr(branch, "coverage_radius_km", None) or getattr(workshop, "coverage_radius_km", 30)))
        if distance_km is not None and distance_km > coverage_radius + Decimal("8"):
            continue

        workers = list(getattr(workshop, "workers", []) or [])
        worker = _best_worker_for_specialty(workers, normalized_specialty)
        capacity_ratio = _capacity_ratio(workshop)
        distance_score = _distance_score(distance_km)
        capacity_score = Decimal("15.00") * capacity_ratio
        rating_score = min(Decimal(str(getattr(workshop, "average_rating", 0) or 0)) * Decimal("3.00"), Decimal("15.00"))
        availability_score = Decimal("20.00")
        specialty_score = Decimal("15.00") if worker else Decimal("5.00")
        coverage_score = Decimal("5.00") if distance_km is None or distance_km <= coverage_radius else Decimal("2.00")
        total = distance_score + capacity_score + rating_score + availability_score + specialty_score + coverage_score
        eta_minutes = max(8, int((distance_km or Decimal("5.00")) * Decimal("3.0")) + 6)
        criteria = {
            "distance_score": float(distance_score),
            "capacity_score": float(capacity_score),
            "rating_score": float(rating_score),
            "availability_score": float(availability_score),
            "specialty_score": float(specialty_score),
            "coverage_score": float(coverage_score),
            "required_specialty": normalized_specialty,
            "coverage_radius_km": float(coverage_radius),
            "current_capacity": getattr(workshop, "current_concurrent_capacity", 0),
            "max_capacity": getattr(workshop, "max_concurrent_capacity", 0),
        }
        candidates.append(
            AssignmentCandidateResult(
                workshop_id=workshop.id,
                workshop_name=workshop.trade_name,
                branch_id=getattr(branch, "id", None),
                branch_name=getattr(branch, "name", None),
                worker_id=getattr(worker, "id", None) if worker else None,
                worker_name=f"{worker.first_name} {worker.last_name}" if worker else None,
                score=total.quantize(Decimal("0.01")),
                distance_km=distance_km,
                eta_minutes=eta_minutes,
                criteria=criteria,
                reason=(
                    f"{workshop.trade_name} rankeado por distancia, capacidad, rating, "
                    f"disponibilidad y especialidad {normalized_specialty}."
                ),
            )
        )

    return sorted(candidates, key=lambda item: item.score, reverse=True)[:limit]


def _workshop_can_receive(workshop: Any) -> bool:
    if not getattr(workshop, "is_active", False):
        return False
    if not getattr(workshop, "is_available", False):
        return False
    if not getattr(workshop, "is_admin_approved", True):
        return False
    if not getattr(workshop, "accepts_requests", False):
        return False
    return getattr(workshop, "current_concurrent_capacity", 0) < getattr(workshop, "max_concurrent_capacity", 1)


def _nearest_active_branch(workshop: Any, latitude: Decimal, longitude: Decimal) -> Any | None:
    branches = [branch for branch in (getattr(workshop, "branches", []) or []) if getattr(branch, "is_active", False)]
    if not branches:
        return None
    return min(
        branches,
        key=lambda branch: calculate_distance_km(branch.latitude, branch.longitude, latitude, longitude) or Decimal("9999"),
    )


def _best_worker_for_specialty(workers: list[Any], required_specialty: str) -> Any | None:
    available_workers = [
        worker
        for worker in workers
        if getattr(worker, "is_active", False)
        and getattr(worker, "is_available", False)
        and (not getattr(worker, "operational_status", None) or worker.operational_status.name == "libre")
    ]
    if not available_workers:
        return None

    def worker_score(worker: Any) -> tuple[int, Decimal, int]:
        main_specialty = normalize_text(getattr(worker, "main_specialty", None))
        specialty_match = 1 if required_specialty and required_specialty in main_specialty else 0
        return (
            specialty_match,
            Decimal(str(getattr(worker, "average_rating", 0) or 0)),
            int(getattr(worker, "total_ratings", 0) or 0),
        )

    return max(available_workers, key=worker_score)


def _capacity_ratio(workshop: Any) -> Decimal:
    max_capacity = Decimal(str(max(getattr(workshop, "max_concurrent_capacity", 1) or 1, 1)))
    current_capacity = Decimal(str(max(getattr(workshop, "current_concurrent_capacity", 0) or 0, 0)))
    available_ratio = (max_capacity - current_capacity) / max_capacity
    return max(Decimal("0.00"), min(available_ratio, Decimal("1.00")))


def _distance_score(distance_km: Decimal | None) -> Decimal:
    if distance_km is None:
        return Decimal("15.00")
    return max(Decimal("0.00"), Decimal("35.00") - (distance_km * Decimal("1.20")))
