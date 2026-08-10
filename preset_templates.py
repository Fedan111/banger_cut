from __future__ import annotations

from typing import Any, Dict

PRESET_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "milo": {
        "name": "🔥 Milo Style (Желтый акцент)",
        "chunk_size": 4,
        "font_name": "Montserrat",
        "font_size": 72,
        "primary_color": "&H00FFFFFF",  # Белый
        "accent_color": "&H0000FFFF",   # Желтый (BGR)
        "outline_color": "&H00000000",  # Черный
        "outline": 4,
        "shadow": 2,
        "alignment": 2,                 # По центру снизу
        "margin_v": 280,
    },
    "single_word": {
        "name": "⚡ Single Word (По 1 слову)",
        "chunk_size": 1,
        "font_name": "Impact",
        "font_size": 88,
        "primary_color": "&H0000FFFF",  # Ярко-желтый
        "accent_color": "&H0000FFFF",
        "outline_color": "&H00000000",
        "outline": 6,
        "shadow": 0,
        "alignment": 2,
        "margin_v": 350,
    },
    "karaoke": {
        "name": "🎤 Karaoke (Зеленый фокус)",
        "chunk_size": 3,
        "font_name": "Arial",
        "font_size": 75,
        "primary_color": "&H00FFFFFF",
        "accent_color": "&H0000FF00",   # Зеленый акцент
        "outline_color": "&H00000000",
        "outline": 3,
        "shadow": 1,
        "alignment": 2,
        "margin_v": 250,
    },
    "minimal_red": {
        "name": "🥊 Red Accent (Красный акцент)",
        "chunk_size": 3,
        "font_name": "Arial",
        "font_size": 70,
        "primary_color": "&H00FFFFFF",
        "accent_color": "&H000000FF",   # Красный акцент
        "outline_color": "&H00000000",
        "outline": 4,
        "shadow": 2,
        "alignment": 2,
        "margin_v": 280,
    },
}