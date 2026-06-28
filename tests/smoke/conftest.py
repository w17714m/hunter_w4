"""Configuración exclusiva para la suite smoke.

Estos tests son independientes de la suite principal (unit + integration).
Se ejecutan directamente apuntando a este directorio:

    uv run pytest tests/smoke/ -v -s

No requieren --run-integration ni ninguna variable de entorno adicional,
pero sí necesitan conexión a internet y Playwright instalado.
"""
