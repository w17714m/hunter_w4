from __future__ import annotations

import logging
import time

import httpx

from src.core.models import Offer

logger = logging.getLogger(__name__)

_TELEGRAM_API = 'https://api.telegram.org/bot{token}/sendMessage'

_MSG_TEMPLATE = """\
🎯 *{titulo}* — {empresa}
📍 {ubicacion}
🔗 {url}

✅ Skills: {skills_encontrados}
⚠️ Skills oferta no en tu perfil: {skills_gap}

🤖 Score: {score} | {razon}
👍 {puntos_favor}
👎 {puntos_contra}

ID: `{short_id}`\
"""


def _fmt_list(items: list[str]) -> str:
    return ', '.join(items) if items else '—'


def _build_message(offer: Offer) -> str:
    veredicto = offer.veredicto
    skill_match = offer.skill_match
    return _MSG_TEMPLATE.format(
        titulo=offer.titulo,
        empresa=offer.empresa or 'No especificada',
        ubicacion=offer.ubicacion or 'No especificada',
        url=offer.url,
        skills_encontrados=_fmt_list(skill_match.skills_encontrados if skill_match else []),
        skills_gap=_fmt_list(skill_match.skills_faltantes if skill_match else []),
        score=f'{veredicto.score:.0%}',  # type: ignore[union-attr]
        razon=veredicto.razon,  # type: ignore[union-attr]
        puntos_favor=_fmt_list(veredicto.puntos_favor),  # type: ignore[union-attr]
        puntos_contra=_fmt_list(veredicto.puntos_contra),  # type: ignore[union-attr]
        short_id=offer.id[:12],
    )


class TelegramNotifierError(Exception):
    pass


class TelegramRateLimitError(TelegramNotifierError):
    pass


class TelegramNotifier:
    """Envía notificaciones de match a un chat de Telegram.

    Solo requiere token y chat_id. No conoce el pipeline ni los collectors.
    Los errores de red o HTTP se propagan como TelegramNotifierError.
    """

    def __init__(
        self,
        token: str,
        chat_id: str,
        timeout_s: float = 15.0,
        retry_on_rate_limit: bool = True,
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.timeout_s = timeout_s
        self.retry_on_rate_limit = retry_on_rate_limit

    def notify(self, offer: Offer) -> None:
        """Envía la notificación de la oferta. Lanza TelegramNotifierError en fallo."""
        if offer.veredicto is None:
            raise TelegramNotifierError(
                f'La oferta {offer.id[:12]} no tiene veredicto; no se puede notificar.'
            )
        text = _build_message(offer)
        self._send(text)

    def _send(self, text: str, *, _retry: bool = True) -> None:
        url = _TELEGRAM_API.format(token=self.token)
        payload = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True,
        }
        try:
            resp = httpx.post(url, json=payload, timeout=self.timeout_s)
        except httpx.TransportError as exc:
            raise TelegramNotifierError(f'Error de red al contactar Telegram: {exc}') from exc

        if resp.status_code == 429:
            retry_after = int(resp.headers.get('Retry-After', 5))
            if _retry and self.retry_on_rate_limit:
                logger.warning('Telegram rate limit. Reintentando en %ds...', retry_after)
                time.sleep(retry_after)
                self._send(text, _retry=False)
                return
            raise TelegramRateLimitError(
                f'Telegram rate limit. Retry-After: {retry_after}s'
            )

        if resp.status_code != 200:
            raise TelegramNotifierError(
                f'Telegram respondió {resp.status_code}: {resp.text[:200]}'
            )
